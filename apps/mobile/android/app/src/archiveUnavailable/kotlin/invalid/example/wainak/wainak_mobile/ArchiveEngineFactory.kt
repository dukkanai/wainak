package invalid.example.wainak.wainak_mobile

internal object ArchiveEngineFactory {
    fun create(): ArchiveEngine = object : ArchiveEngine {
        override fun newSession(): Long = throw ArchiveEngineFailure("unavailable")
        override fun syntheticRoundTrip(session: Long): Int = throw ArchiveEngineFailure("unavailable")
        override fun close(session: Long) = Unit
    }
}
