import Foundation
import XCTest
@testable import Runner

/// Source-prepared tests; no claim that XCTest/Xcode has run on this host.
final class NativeArchiveTests: XCTestCase {
  private final class Executor: ArchiveExecutor {
    private var operation: (() -> Void)?
    var reject = false
    var occupied: Bool { operation != nil }
    func submit(_ operation: @escaping () -> Void) -> Bool {
      guard !reject && self.operation == nil else { return false }
      self.operation = operation
      return true
    }
    func run() {
      let pending = operation
      // Keep reservation occupied during the body, like the production executor.
      pending?()
      operation = nil
    }
  }
  private final class Deadline: ArchiveDeadline {
    var action: (() -> Void)?
    func cancel() { action = nil }
    func fire() { let pending = action; action = nil; pending?() }
  }
  private final class Engine: ArchiveEngine {
    var isAvailable = true
    var opened = 0
    var closed = 0
    var roundTrips = 0
    var failClose = false
    var failOpenCleanup = false
    var onOpen: (() -> Void)?
    var onRoundTrip: (() -> Void)?
    func newSession() throws -> Int64 {
      opened += 1; onOpen?()
      if failOpenCleanup { throw ArchiveFailure.cleanupUnconfirmed }
      return 7
    }
    func syntheticRoundTrip(_ session: Int64) throws -> Int {
      roundTrips += 1; onRoundTrip?(); return 2
    }
    func close(_ session: Int64) throws {
      closed += 1
      if failClose { throw ArchiveFailure.failed }
    }
  }
  private let first = "probe_11111111111111111111111111111111"
  private let second = "probe_22222222222222222222222222222222"
  private func args(_ handle: String, epoch: Int64 = 1) -> [String: Any] {
    ["schema": 1, "handle": handle, "epoch": epoch]
  }
  private func core(_ engine: Engine, _ worker: Executor, _ control: Executor,
                    deadline: Deadline = Deadline()) -> ArchiveProbeCoordinator {
    ArchiveProbeCoordinator(engine: engine, allowed: true, worker: worker, control: control,
      deliver: { $0() }, schedule: { _, action in deadline.action = action; return deadline })
  }
  private func failure(_ value: ArchiveReply, _ expected: ArchiveFailure) -> Bool {
    if case .failure(let actual) = value { return actual == expected }; return false
  }

  func testStrictArgumentsRejectBooleansFloatsExtrasAndMalformedHandles() {
    XCTAssertNotNil(ArchiveRequest(args(first)))
    for value in [true, 1.0, "1", -1, 0, Int64(9_007_199_254_740_992)] as [Any] {
      var input = args(first); input["epoch"] = value
      XCTAssertNil(ArchiveRequest(input))
    }
    var input = args(first); input["schema"] = true
    XCTAssertNil(ArchiveRequest(input))
    input = args(first); input["extra"] = "no"
    XCTAssertNil(ArchiveRequest(input))
    XCTAssertNil(ArchiveRequest(args(first + "\n")))
  }

  func testUnavailableAndReleaseGateCannotReturnReceipt() {
    let missing = ArchiveProbeCoordinator(engine: UnavailableArchiveEngine(), allowed: true,
      deliver: { $0() })
    missing.handle(method: "open", arguments: args(first)) { XCTAssertTrue(self.failure($0, .unavailable)) }
    let disabled = ArchiveProbeCoordinator(engine: Engine(), allowed: false, deliver: { $0() })
    disabled.handle(method: "open", arguments: args(first)) { XCTAssertTrue(self.failure($0, .unavailable)) }
  }

  func testSyntheticReceiptRequiresWorkerAndCloseCompletion() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { if case .opened = $0 {} else { XCTFail("open") } }
    var completed = false
    host.handle(method: "probe", arguments: args(first)) {
      if case .receipt = $0 { completed = true } else { XCTFail("receipt") }
    }
    XCTAssertFalse(completed); XCTAssertEqual(engine.opened, 0)
    worker.run()
    XCTAssertTrue(completed); XCTAssertEqual(engine.closed, 1)
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    host.dispose()
  }

  func testDeferredOpenReplyCannotResurrectClearedLease() {
    let engine = Engine(), worker = Executor(), control = Executor()
    var pending: [() -> Void] = []
    let host = ArchiveProbeCoordinator(engine: engine, allowed: true, worker: worker, control: control,
      deliver: { pending.append($0) })
    var replies = 0
    host.handle(method: "open", arguments: args(first)) {
      replies += 1; XCTAssertTrue(self.failure($0, .stale))
    }
    host.clear()
    pending.removeFirst()()
    XCTAssertEqual(replies, 1)
    host.dispose()
  }

  func testClearKeepsWorkerReservationAndRejectsLateCompletion() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { _ in }
    var replies = 0
    host.handle(method: "probe", arguments: args(first)) {
      replies += 1; XCTAssertTrue(self.failure($0, .stale))
    }
    host.clear()
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .busy)) }
    worker.run()
    XCTAssertEqual(engine.opened, 0); XCTAssertEqual(replies, 1)
    host.handle(method: "open", arguments: args(second)) { if case .opened = $0 {} else { XCTFail("replacement") } }
    host.handle(method: "close", arguments: args(first)) { if case .closed = $0 {} else { XCTFail("old_close") } }
    host.handle(method: "probe", arguments: args(second)) { if case .receipt = $0 {} else { XCTFail("new_context") } }
    worker.run()
    host.dispose()
  }

  func testLateNativeOpenAfterDisposeIsClosedWithoutRoundTrip() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    engine.onOpen = { host.dispose() }
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    worker.run()
    XCTAssertEqual(engine.opened, 1); XCTAssertEqual(engine.closed, 1)
    XCTAssertEqual(engine.roundTrips, 0)
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .unavailable)) }
  }

  func testControlCloseDoesNotWaitBehindCryptoWorker() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    engine.onRoundTrip = {
      host.clear()
      XCTAssertTrue(worker.occupied); XCTAssertTrue(control.occupied)
      host.handle(method: "open", arguments: self.args(self.second)) { XCTAssertTrue(self.failure($0, .busy)) }
      control.run()
      XCTAssertEqual(engine.closed, 1)
    }
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    worker.run()
    XCTAssertEqual(engine.closed, 2) // idempotent final close of the same native ID
    host.dispose()
  }

  func testTimeoutRepliesOnceAndKeepsReservationUntilReturn() {
    let engine = Engine(), worker = Executor(), control = Executor(), deadline = Deadline()
    let host = core(engine, worker, control, deadline: deadline)
    host.handle(method: "open", arguments: args(first)) { _ in }
    var replies = 0
    host.handle(method: "probe", arguments: args(first)) {
      replies += 1; XCTAssertTrue(self.failure($0, .timeout))
    }
    deadline.fire()
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .busy)) }
    worker.run()
    XCTAssertEqual(replies, 1); XCTAssertEqual(engine.opened, 0)
    host.dispose()
  }

  func testCleanupFailurePreventsReceiptAndNewWork() {
    let engine = Engine(), worker = Executor(), control = Executor()
    engine.failClose = true
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .cleanupUnconfirmed)) }
    worker.run(); host.clear()
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .cleanupUnconfirmed)) }
    host.dispose()
  }

  func testCloseDuringNativeOpenClosesLateHandle() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    engine.onOpen = {
      host.handle(method: "close", arguments: self.args(self.first)) {
        if case .closed = $0 {} else { XCTFail("invalidation_ack") }
      }
    }
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    worker.run()
    XCTAssertEqual(engine.closed, 1); XCTAssertEqual(engine.roundTrips, 0)
    host.dispose()
  }

  func testAlreadyQueuedReceiptRechecksLifecycleBeforeDelivery() {
    let engine = Engine(), worker = Executor(), control = Executor(), deadline = Deadline()
    var pending: [() -> Void] = []
    let host = ArchiveProbeCoordinator(engine: engine, allowed: true, worker: worker, control: control,
      deliver: { pending.append($0) }, schedule: { _, action in deadline.action = action; return deadline })
    host.handle(method: "open", arguments: args(first)) { _ in }
    pending.removeFirst()()
    var replies = 0
    host.handle(method: "probe", arguments: args(first)) {
      replies += 1; XCTAssertTrue(self.failure($0, .stale))
    }
    let racingTimeout = deadline.action
    worker.run() // receipt selected, but its main-thread delivery has not run
    racingTimeout?() // already-enqueued timeout racing with cancellation
    pending.removeFirst()()
    XCTAssertEqual(replies, 1); XCTAssertTrue(pending.isEmpty)
    host.dispose()
  }

  func testRejectedControlAdmissionFailsClosedAndWorkerStillCloses() {
    let engine = Engine(), worker = Executor(), control = Executor()
    control.reject = true
    let host = core(engine, worker, control)
    engine.onRoundTrip = {
      host.handle(method: "close", arguments: self.args(self.first)) {
        XCTAssertTrue(self.failure($0, .cleanupUnconfirmed))
      }
    }
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    worker.run()
    XCTAssertEqual(engine.closed, 1)
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .cleanupUnconfirmed)) }
    host.dispose()
  }


  func testUsedHandleCannotRetargetSameOrHigherEpochAfterClose() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "close", arguments: args(first)) { _ in }
    for epoch in [Int64(1), Int64(2)] {
      host.handle(method: "open", arguments: args(first, epoch: epoch)) {
        XCTAssertTrue(self.failure($0, .stale))
      }
    }
    host.dispose()
  }

  func testClearPreservesUsedHandleFenceAndDisposeIsTerminal() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.clear()
    host.handle(method: "open", arguments: args(first)) { XCTAssertTrue(self.failure($0, .stale)) }
    host.dispose()
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .unavailable)) }
  }

  func testLifetimeHandleCapacityIsBoundedBeforeAdmission() {
    let engine = Engine(), worker = Executor(), control = Executor()
    let host = core(engine, worker, control)
    for index in 1...64 {
      let handle = "probe_" + String(repeating: "0", count: 30) + String(format: "%02x", index)
      host.handle(method: "open", arguments: args(handle)) {
        if case .opened = $0 {} else { XCTFail("capacity_admission") }
      }
      host.handle(method: "close", arguments: args(handle)) { _ in }
    }
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .capacity)) }
    XCTAssertEqual(engine.opened, 0)
    host.dispose()
  }


  func testUnconfirmedCleanupDuringOpenPermanentlyClosesAdmission() {
    let engine = Engine(), worker = Executor(), control = Executor()
    engine.failOpenCleanup = true
    let host = core(engine, worker, control)
    host.handle(method: "open", arguments: args(first)) { _ in }
    host.handle(method: "probe", arguments: args(first)) { XCTAssertTrue(self.failure($0, .cleanupUnconfirmed)) }
    worker.run(); host.clear()
    host.handle(method: "open", arguments: args(second)) { XCTAssertTrue(self.failure($0, .cleanupUnconfirmed)) }
    host.dispose()
  }
}


#if WAINEK_ARCHIVE_BRIDGE
/// Conditional real binding test, NOT RUN during source preparation.
final class LinkedArchiveEngineTests: XCTestCase {
  func testLinkedSyntheticRoundTripAndRepeatedClose() throws {
    let engine = ArchiveEngineFactory.make()
    XCTAssertTrue(engine.isAvailable)
    let session = try engine.newSession()
    var closed = false
    defer { if !closed { try? engine.close(session) } }
    XCTAssertEqual(try engine.syntheticRoundTrip(session), 2)
    try engine.close(session)
    closed = true
    try engine.close(session)
  }
}
#endif
