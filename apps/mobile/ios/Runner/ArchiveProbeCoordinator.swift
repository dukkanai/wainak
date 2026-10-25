import Foundation
import CoreFoundation

/// Platform-codec validation is runtime, exact-key and rejects bool/float epochs.
struct ArchiveRequest {
  let handle: String
  let epoch: Int64

  init?(_ arguments: Any?) {
    guard let values = arguments as? [String: Any],
      Set(values.keys) == Set(["schema", "handle", "epoch"]),
      ArchiveRequest.integer(values["schema"]) == 1,
      let handle = values["handle"] as? String,
      handle.utf8.count == 38,
      handle.range(of: "^probe_[a-f0-9]{32}$", options: .regularExpression) != nil,
      let epoch = ArchiveRequest.integer(values["epoch"]),
      (1...9_007_199_254_740_991).contains(epoch)
    else { return nil }
    self.handle = handle
    self.epoch = epoch
  }

  private static func integer(_ raw: Any?) -> Int64? {
    guard let number = raw as? NSNumber,
      CFGetTypeID(number) != CFBooleanGetTypeID(),
      ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: number.objCType))
    else { return nil }
    return number.int64Value
  }
}

enum ArchiveReply {
  case opened(ArchiveRequest)
  // Acknowledges lease invalidation only, NOT native completion/zeroization.
  case closed
  case receipt
  case failure(ArchiveFailure)
}

protocol ArchiveExecutor: AnyObject {
  var occupied: Bool { get }
  func submit(_ operation: @escaping () -> Void) -> Bool
}

/// Reservation occurs before enqueue. At most one queued/running closure.
final class BoundedArchiveExecutor: ArchiveExecutor {
  private let lock = NSLock()
  private let queue: DispatchQueue
  private var reserved = false
  init(label: String) { queue = DispatchQueue(label: label, qos: .userInitiated) }
  var occupied: Bool { lock.lock(); defer { lock.unlock() }; return reserved }
  func submit(_ operation: @escaping () -> Void) -> Bool {
    lock.lock()
    guard !reserved else { lock.unlock(); return false }
    reserved = true
    lock.unlock()
    queue.async {
      defer { self.lock.lock(); self.reserved = false; self.lock.unlock() }
      operation()
    }
    return true
  }
}

protocol ArchiveDeadline: AnyObject { func cancel() }
final class DispatchArchiveDeadline: ArchiveDeadline {
  private let timer: DispatchSourceTimer
  init(seconds: TimeInterval, operation: @escaping () -> Void) {
    timer = DispatchSource.makeTimerSource(queue: .main)
    timer.setEventHandler(handler: operation)
    timer.schedule(deadline: .now() + seconds)
    timer.resume()
  }
  func cancel() { timer.setEventHandler {}; timer.cancel() }
  deinit { cancel() }
}

/// Exactly-once delivery, always dispatched to the main executor in production.
private final class ArchiveReplyTicket {
  private let lock = NSLock()
  private var sent = false
  private let deliver: (@escaping () -> Void) -> Void
  private let reply: (ArchiveReply) -> Void
  init(deliver: @escaping (@escaping () -> Void) -> Void, reply: @escaping (ArchiveReply) -> Void) {
    self.deliver = deliver; self.reply = reply
  }
  func send(_ value: ArchiveReply) { sendValidated { value } }
  func sendValidated(_ value: @escaping () -> ArchiveReply) {
    lock.lock()
    guard !sent else { lock.unlock(); return }
    sent = true
    lock.unlock()
    deliver { self.reply(value()) }
  }
}

/// No IO, serialization, account access or background task extension.
/// All state uses one lock; native methods and callbacks run OUTSIDE that lock.
final class ArchiveProbeCoordinator {
  private final class Context {
    let request: ArchiveRequest
    var live = true
    var started = false
    var native: Int64 = 0
    init(_ request: ArchiveRequest) { self.request = request }
  }
  private let lock = NSLock()
  private let engine: ArchiveEngine
  private let allowed: Bool
  private let worker: ArchiveExecutor
  private let control: ArchiveExecutor
  private let deliver: (@escaping () -> Void) -> Void
  private let schedule: (TimeInterval, @escaping () -> Void) -> ArchiveDeadline
  private var current: Context?
  private var working = false
  private var cleaning = 0
  private var cleanupFailed = false
  private var disposed = false
  // Bounded replay fence for this synthetic engine instance, not authentication.
  // Ordinary close/clear/background never erase these caller-handle tombstones.
  private var usedHandles = Set<String>()
  private static let maximumLifetimeHandles = 64

  init(engine: ArchiveEngine, allowed: Bool,
       worker: ArchiveExecutor = BoundedArchiveExecutor(label: "wainak.archive.worker"),
       control: ArchiveExecutor = BoundedArchiveExecutor(label: "wainak.archive.control"),
       deliver: @escaping (@escaping () -> Void) -> Void = { operation in
         if Thread.isMainThread { operation() } else { DispatchQueue.main.async(execute: operation) }
       },
       schedule: @escaping (TimeInterval, @escaping () -> Void) -> ArchiveDeadline = {
         DispatchArchiveDeadline(seconds: $0, operation: $1)
       }) {
    self.engine = engine; self.allowed = allowed; self.worker = worker
    self.control = control; self.deliver = deliver; self.schedule = schedule
  }

  func handle(method: String, arguments: Any?, reply: @escaping (ArchiveReply) -> Void) {
    let ticket = ArchiveReplyTicket(deliver: deliver, reply: reply)
    lock.lock()
    guard !disposed && allowed && engine.isAvailable else {
      lock.unlock(); ticket.send(.failure(.unavailable)); return
    }
    guard let request = ArchiveRequest(arguments) else {
      lock.unlock(); ticket.send(.failure(.invalid)); return
    }
    switch method {
    case "open":
      guard !cleanupFailed else { lock.unlock(); ticket.send(.failure(.cleanupUnconfirmed)); return }
      guard !usedHandles.contains(request.handle) else {
        lock.unlock(); ticket.send(.failure(.stale)); return
      }
      guard usedHandles.count < Self.maximumLifetimeHandles else {
        lock.unlock(); ticket.send(.failure(.capacity)); return
      }
      guard current == nil && !working && cleaning == 0 && !worker.occupied && !control.occupied else {
        lock.unlock(); ticket.send(.failure(.busy)); return
      }
      let context = Context(request)
      usedHandles.insert(request.handle)
      current = context
      lock.unlock()
      // Recheck at delivery time: lifecycle may clear before the main turn.
      ticket.sendValidated { [self] in
        isCurrent(context) ? .opened(request) : .failure(.stale)
      }
    case "close":
      let context = matching(request)
      let native = context.map { invalidateLocked($0) } ?? 0
      lock.unlock()
      let accepted = queueClose(native)
      ticket.send(accepted ? .closed : .failure(.cleanupUnconfirmed))
    case "probe":
      guard let context = matching(request), context.live, !context.started else {
        lock.unlock(); ticket.send(.failure(.stale)); return
      }
      guard !working && cleaning == 0 && !cleanupFailed else {
        lock.unlock(); ticket.send(.failure(.busy)); return
      }
      context.started = true
      working = true
      lock.unlock()
      run(context, ticket: ticket)
    default:
      lock.unlock(); ticket.send(.failure(.invalid))
    }
  }

  // Call only with lock held. No other instance can furnish this Context object.
  private func matching(_ request: ArchiveRequest) -> Context? {
    guard let context = current,
      context.request.handle == request.handle && context.request.epoch == request.epoch
    else { return nil }
    return context
  }
  private func isCurrent(_ context: Context) -> Bool {
    lock.lock(); defer { lock.unlock() }
    return !disposed && current === context && context.live
  }
  private func invalidateLocked(_ context: Context) -> Int64 {
    context.live = false
    if current === context { current = nil }
    let native = context.native
    context.native = 0
    if native > 0 { cleaning += 1 }
    return native
  }
  private func queueClose(_ native: Int64) -> Bool {
    guard native > 0 else { return true }
    let accepted = control.submit { [self] in
      var failed = false
      do { try engine.close(native) } catch { failed = true }
      lock.lock(); cleanupFailed = cleanupFailed || failed; cleaning -= 1; lock.unlock()
    }
    if !accepted {
      // Worker still owns this native ID and closes it in its finalization.
      // A failed control admission must never reopen capacity to another job.
      lock.lock(); cleanupFailed = true; cleaning -= 1; lock.unlock()
    }
    return accepted
  }
  private func run(_ context: Context, ticket: ArchiveReplyTicket) {
    let deadline = schedule(30) { [weak self, weak context] in
      guard let self = self, let context = context else { return }
      self.lock.lock()
      let native = self.current === context ? self.invalidateLocked(context) : 0
      self.lock.unlock()
      _ = self.queueClose(native)
      ticket.send(.failure(.timeout))
    }
    let accepted = worker.submit { [self] in
      var native: Int64 = 0
      var failure: ArchiveFailure?
      do {
        guard isCurrent(context) else { throw ArchiveFailure.stale }
        native = try engine.newSession()
        guard native > 0 else { throw ArchiveFailure.invalid }
        lock.lock()
        let live = !disposed && current === context && context.live
        if live { context.native = native }
        lock.unlock()
        guard live else { throw ArchiveFailure.stale }
        guard try engine.syntheticRoundTrip(native) == 2 else { throw ArchiveFailure.invalid }
      } catch let error as ArchiveFailure {
        if error == .cleanupUnconfirmed {
          lock.lock(); cleanupFailed = true; lock.unlock()
          failure = .cleanupUnconfirmed
        } else {
          failure = error == .unavailable ? .unavailable : .failed
        }
      } catch { failure = .failed }
      // Includes handles returned after clear/dispose/timeout. Close is idempotent.
      if native > 0 {
        do { try engine.close(native) }
        catch {
          lock.lock(); cleanupFailed = true; lock.unlock()
          failure = .cleanupUnconfirmed
        }
      }
      lock.lock()
      context.native = 0
      working = false
      let cleanupOK = !cleanupFailed && cleaning == 0
      lock.unlock()
      deadline.cancel()
      let completedFailure = failure
      ticket.sendValidated { [self] in
        guard isCurrent(context) else { return .failure(.stale) }
        if let error = completedFailure { return .failure(error) }
        if !cleanupOK { return .failure(.cleanupUnconfirmed) }
        return .receipt
      }
    }
    if !accepted {
      deadline.cancel()
      lock.lock(); working = false; _ = invalidateLocked(context); lock.unlock()
      ticket.send(.failure(.busy))
    }
  }

  func clear() {
    lock.lock()
    let native = current.map { invalidateLocked($0) } ?? 0
    lock.unlock()
    _ = queueClose(native)
  }
  func dispose() {
    lock.lock()
    disposed = true
    let native = current.map { invalidateLocked($0) } ?? 0
    lock.unlock()
    _ = queueClose(native)
  }
}
