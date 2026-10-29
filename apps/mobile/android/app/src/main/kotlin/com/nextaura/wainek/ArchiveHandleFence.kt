package com.nextaura.wainek

/**
 * Bounded RAM-only stale-callback fence for one synthetic engine lifetime.
 * A caller handle is never reissued after close/clear. This is not account
 * authentication, and does not persist content or restore authority.
 */
internal class ArchiveHandleFence(private val capacity: Int = 64) {
    init { require(capacity in 1..64) }
    private val used = HashSet<String>()

    /** Null means the handle was atomically reserved; errors are fixed labels. */
    @Synchronized
    fun claim(handle: String): String? {
        if (handle in used) return "stale"
        if (used.size >= capacity) return "capacity"
        used.add(handle)
        return null
    }
}
