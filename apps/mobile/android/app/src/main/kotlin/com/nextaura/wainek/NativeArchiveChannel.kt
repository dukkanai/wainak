package com.nextaura.wainek

import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/** Development-only; one native job, one context, no background task retention. */
internal class NativeArchiveChannel(
    messenger: BinaryMessenger,
    private val engine: ArchiveEngine,
    private val allowed: Boolean,
) {
    private data class Context(val handle: String, val epoch: Long) {
        val live = AtomicBoolean(true)
        val started = AtomicBoolean(false)
        val native = AtomicLong(0)
    }
    private val channel = MethodChannel(messenger, "wainek/native_archive_v1")
    private val main = Handler(Looper.getMainLooper())
    private val worker = ThreadPoolExecutor(
        1, 1, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(1),
        ThreadPoolExecutor.AbortPolicy(),
    )
    private val control = ThreadPoolExecutor(
        1, 1, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue<Runnable>(1),
        ThreadPoolExecutor.AbortPolicy(),
    )
    private val working = AtomicBoolean(false)
    private val cleaning = AtomicInteger(0)
    private val cleanupFailed = AtomicBoolean(false)
    private var context: Context? = null
    private val handleFence = ArchiveHandleFence()
    private var disposed = false
    private val handlePattern = Regex("^probe_[a-f0-9]{32}$")

    init { channel.setMethodCallHandler(::handle) }

    private fun fail(result: MethodChannel.Result, code: String) {
        result.error(code, "archive_probe_failed", null)
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        if (disposed || !allowed) { fail(result, "unavailable"); return }
        val args = call.arguments as? Map<*, *>
        if (args == null || args.keys != setOf("schema", "handle", "epoch") ||
            args["schema"] != 1) { fail(result, "invalid"); return }
        val handle = args["handle"] as? String
        val rawEpoch = args["epoch"]
        val epoch = when (rawEpoch) { is Int -> rawEpoch.toLong(); is Long -> rawEpoch; else -> 0L }
        if (handle == null || !handlePattern.matches(handle) || epoch !in 1..9007199254740991L) {
            fail(result, "invalid"); return
        }
        when (call.method) {
            "open" -> {
                if (cleanupFailed.get()) { fail(result, "cleanup_unconfirmed"); return }
                if (context != null || working.get() || cleaning.get() != 0) { fail(result, "busy"); return }
                val rejection = handleFence.claim(handle)
                if (rejection != null) { fail(result, rejection); return }
                context = Context(handle, epoch)
                result.success(mapOf("schema" to 1, "handle" to handle, "epoch" to epoch))
            }
            "close" -> {
                val old = context
                if (old != null && old.handle == handle && old.epoch == epoch) {
                    context = null
                    if (!invalidate(old)) { fail(result, "cleanup_unconfirmed"); return }
                }
                // Idempotent and scoped: an old close cannot clear another lease.
                result.success(mapOf("closed" to true))
            }
            "probe" -> {
                val current = context
                if (current == null || current.handle != handle || current.epoch != epoch || !current.live.get()) {
                    fail(result, "stale"); return
                }
                if (!current.started.compareAndSet(false, true)) { fail(result, "stale"); return }
                if (!working.compareAndSet(false, true)) { fail(result, "busy"); return }
                run(current, result)
            }
            else -> fail(result, "invalid")
        }
    }

    private fun invalidate(old: Context): Boolean {
        old.live.set(false)
        val native = old.native.getAndSet(0)
        if (native <= 0) return !cleanupFailed.get()
        cleaning.incrementAndGet()
        try {
            control.execute {
                try { engine.close(native) }
                catch (_: Exception) { cleanupFailed.set(true) }
                catch (_: LinkageError) { cleanupFailed.set(true) }
                finally { cleaning.decrementAndGet() }
            }
        } catch (_: RejectedExecutionException) {
            cleaning.decrementAndGet()
            // Fail closed. The active worker still owns its local native ID and
            // must close it in finally; no replacement work is admitted.
            cleanupFailed.set(true)
            return false
        }
        return true
    }

    private fun run(current: Context, result: MethodChannel.Result) {
        // Deadline invalidates publication even if a native call finishes later.
        val timeout = Runnable { if (context === current) { context = null; invalidate(current) } }
        main.postDelayed(timeout, 30000)
        try { worker.execute {
            var native = 0L
            var count = 0
            var code: String? = null
            try {
                if (!current.live.get()) throw ArchiveEngineFailure("stale")
                native = engine.newSession()
                if (native <= 0) throw ArchiveEngineFailure("invalid")
                current.native.set(native)
                if (!current.live.get()) throw ArchiveEngineFailure("stale")
                count = engine.syntheticRoundTrip(native)
                if (count != 2) throw ArchiveEngineFailure("invalid")
            } catch (error: ArchiveEngineFailure) {
                code = if (error.safeCode == "unavailable") "unavailable" else "failed"
            } catch (_: Exception) {
                code = "failed"
            } catch (_: LinkageError) {
                // Missing/incompatible JNI is unavailable, never simulated success.
                code = "unavailable"
            } finally {
                current.native.compareAndSet(native, 0)
                if (native > 0) {
                    try { engine.close(native) }
                    catch (_: Exception) { cleanupFailed.set(true); code = "cleanup_unconfirmed" }
                    catch (_: LinkageError) { cleanupFailed.set(true); code = "cleanup_unconfirmed" }
                }
                working.set(false)
            }
            val failure = code
            main.post {
                main.removeCallbacks(timeout)
                if (disposed || context !== current || !current.live.get()) {
                    fail(result, "stale")
                } else if (failure != null) {
                    fail(result, failure)
                } else {
                    result.success(mapOf(
                        "schema" to 1, "profile" to "age-x25519-history-v1", "records" to count,
                        "imported" to true, "authenticated_author" to false,
                        "synthetic" to true, "persisted" to false, "transmitted" to false,
                    ))
                }
            }
        } } catch (_: RejectedExecutionException) {
            working.set(false)
            main.removeCallbacks(timeout)
            if (context === current) context = null
            invalidate(current)
            fail(result, "unavailable")
        }
    }

    fun clear() {
        val old = context
        context = null
        if (old != null) invalidate(old)
    }

    fun dispose() {
        if (disposed) return
        disposed = true
        clear()
        channel.setMethodCallHandler(null)
        worker.shutdown()
        control.shutdown()
    }
}
