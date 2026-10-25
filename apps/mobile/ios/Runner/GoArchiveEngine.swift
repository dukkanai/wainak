import Foundation

#if WAINAK_ARCHIVE_BRIDGE
/// Real native path only. The private C shim uses the verified generated ObjC
/// prototypes; this is source preparation until an Apple compile/runtime test.
final class GoArchiveEngine: ArchiveEngine {
  var isAvailable: Bool { true }
  func newSession() throws -> Int64 {
    let session = WainakArchiveOpen()
    if session == -1 { throw ArchiveFailure.cleanupUnconfirmed }
    guard session > 0 else { throw ArchiveFailure.failed }
    return session
  }
  func syntheticRoundTrip(_ session: Int64) throws -> Int {
    guard session > 0, WainakArchiveRoundTrip(session) == 2 else { throw ArchiveFailure.failed }
    return 2
  }
  func close(_ session: Int64) throws {
    guard session > 0, WainakArchiveClose(session) else { throw ArchiveFailure.cleanupUnconfirmed }
  }
}
#endif
