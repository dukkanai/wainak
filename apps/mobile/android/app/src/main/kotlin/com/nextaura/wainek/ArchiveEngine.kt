package com.nextaura.wainek

/** Internal only: no native key, ciphertext or history enters a platform reply. */
internal interface ArchiveEngine {
    fun newSession(): Long
    fun syntheticRoundTrip(session: Long): Int
    fun close(session: Long)
}

internal class ArchiveEngineFailure(val safeCode: String) : Exception("archive_probe_failed")
