package invalid.example.wainak.wainak_mobile

/** Standalone pure-Kotlin checks, NOT RUN. No Android/JNI/runtime claim.
 * Uses check(), not JVM assertions; requires only Kotlin stdlib and the source.
 * Compile/run later with the reviewed Kotlin toolchain, separately from iOS CI.
 */
fun main() {
    fun handle(n: Int) = "probe_" + n.toString(16).padStart(32, '0')
    val fence = ArchiveHandleFence()
    check(fence.claim(handle(1)) == null)
    // Epoch is deliberately not part of the fence: reusing a caller handle at
    // any epoch cannot make an old close match a new context.
    check(fence.claim(handle(1)) == "stale")
    for (n in 2..64) check(fence.claim(handle(n)) == null)
    check(fence.claim(handle(65)) == "capacity")
    check(fence.claim(handle(1)) == "stale")
    check(ArchiveHandleFence().claim(handle(1)) == null)
    for (capacity in listOf(0, 65)) {
        var rejected = false
        try { ArchiveHandleFence(capacity) } catch (_: IllegalArgumentException) { rejected = true }
        check(rejected)
    }
    println("PASS bounded synthetic handle fence checks")
}
