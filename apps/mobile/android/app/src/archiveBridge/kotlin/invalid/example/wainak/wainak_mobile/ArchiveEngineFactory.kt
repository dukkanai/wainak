package invalid.example.wainak.wainak_mobile

// Generated facade name is pinned by the planned Go package, but compilation
// against an actual AAR remains a required gate while Android SDK is unavailable.
import archivebridge.Archivebridge
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import org.json.JSONObject

internal object ArchiveEngineFactory {
    fun create(): ArchiveEngine = GoArchiveEngine()
}

private class GoArchiveEngine : ArchiveEngine {
    override fun newSession(): Long = Archivebridge.newSyntheticSession()

    override fun syntheticRoundTrip(session: Long): Int {
        val epoch = Archivebridge.epoch(session)
        val records = """[{"event_id":"event_one","occurred_at":"2026-10-24T00:00:00Z","card_id":"sample_card","response_id":"sample_defer"},{"event_id":"event_two","occurred_at":"2026-10-24T00:01:00Z","card_id":"sample_card","response_id":"sample_yes"}]""".toByteArray(Charsets.UTF_8)
        var cipher: ByteArray? = null
        var history: ByteArray? = null
        try {
            // Gobind byte arrays may alias: copy every boundary, never retain a
            // mutable caller buffer across a native operation.
            val exported = Archivebridge.exportHistory(session, epoch, records.copyOf())
            if (exported.size > 2 * 1024 * 1024 || exported.isEmpty()) throw ArchiveEngineFailure("invalid")
            cipher = exported.copyOf()
            Archivebridge.importHistory(session, epoch, cipher.copyOf())
            val snapshot = Archivebridge.historySnapshot(session, epoch)
            if (snapshot.size > 1024 * 1024 || snapshot.isEmpty()) throw ArchiveEngineFailure("invalid")
            history = snapshot.copyOf()
            val decoder = Charsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
            val raw = JSONObject(decoder.decode(ByteBuffer.wrap(history)).toString())
            if (raw.keys().asSequence().toSet() != setOf("profile", "synthetic", "records") ||
                raw.opt("profile") != "wainak-synthetic-history-bridge-v1" || raw.opt("synthetic") != true) {
                throw ArchiveEngineFailure("invalid")
            }
            val rows = raw.getJSONArray("records")
            if (rows.length() != 2) throw ArchiveEngineFailure("invalid")
            val expected = mapOf(
                "event_one" to Pair("2026-10-24T00:00:00Z", "sample_defer"),
                "event_two" to Pair("2026-10-24T00:01:00Z", "sample_yes"),
            )
            val seen = mutableSetOf<String>()
            for (index in 0 until rows.length()) {
                val row = rows.getJSONObject(index)
                if (row.keys().asSequence().toSet() != setOf("event_id", "occurred_at", "card_id", "response_id", "imported", "authenticated_author")) {
                    throw ArchiveEngineFailure("invalid")
                }
                val event = row.opt("event_id") as? String ?: throw ArchiveEngineFailure("invalid")
                val pair = expected[event] ?: throw ArchiveEngineFailure("invalid")
                if (!seen.add(event) || row.opt("occurred_at") != pair.first ||
                    row.opt("card_id") != "sample_card" || row.opt("response_id") != pair.second ||
                    row.opt("imported") != true || row.opt("authenticated_author") != false) {
                    throw ArchiveEngineFailure("invalid")
                }
            }
            return rows.length()
        } finally {
            // Best-effort mutation of our byte arrays, NOT secure zeroization.
            records.fill(0)
            cipher?.fill(0)
            history?.fill(0)
        }
    }

    override fun close(session: Long) = Archivebridge.close(session)
}
