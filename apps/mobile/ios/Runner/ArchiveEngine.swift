import Foundation

/// Native-only synthetic engine contract. Keys/archive/history never enter Flutter.
/// A concrete Go adapter must own/copy its buffers, validate its bounded history,
/// and support concurrent, idempotent close while a worker is in a native call.
protocol ArchiveEngine: AnyObject {
  var isAvailable: Bool { get }
  func newSession() throws -> Int64
  func syntheticRoundTrip(_ session: Int64) throws -> Int
  func close(_ session: Int64) throws
}

enum ArchiveFailure: String, Error {
  case unavailable, invalid, busy, stale, timeout, failed, capacity
  case cleanupUnconfirmed = "cleanup_unconfirmed"
}

final class UnavailableArchiveEngine: ArchiveEngine {
  var isAvailable: Bool { false }
  func newSession() throws -> Int64 { throw ArchiveFailure.unavailable }
  func syntheticRoundTrip(_ session: Int64) throws -> Int { throw ArchiveFailure.unavailable }
  func close(_ session: Int64) throws { throw ArchiveFailure.unavailable }
}

enum ArchiveEngineFactory {
  static func make() -> ArchiveEngine {
    // Both Swift and Clang conditions must be supplied by the reviewed artifact
    // verifier. A missing/mismatched native framework fails compilation/linking.
    #if WAINEK_ARCHIVE_BRIDGE
    return GoArchiveEngine()
    #else
    return UnavailableArchiveEngine()
    #endif
  }
}
