import Flutter
import UIKit

/// Count-only channel. No platform reply contains a native key or archive bytes.
final class NativeArchivePlugin: NSObject, FlutterPlugin {
  private let coordinator: ArchiveProbeCoordinator
  private let channel: FlutterMethodChannel
  private var observers: [NSObjectProtocol] = []

  static func register(with registrar: FlutterPluginRegistrar) {
    let channel = FlutterMethodChannel(
      name: "wainek/native_archive_v1", binaryMessenger: registrar.messenger())
    #if DEBUG
    let allowed = true
    #else
    let allowed = false
    #endif
    let plugin = NativeArchivePlugin(channel: channel,
      coordinator: ArchiveProbeCoordinator(engine: ArchiveEngineFactory.make(), allowed: allowed))
    registrar.addMethodCallDelegate(plugin, channel: channel)
    // Required by Flutter for detachFromEngine(for:) to be delivered.
    registrar.publish(plugin)
  }

  init(channel: FlutterMethodChannel, coordinator: ArchiveProbeCoordinator) {
    self.channel = channel
    self.coordinator = coordinator
    super.init()
    // App and scene notifications cover modern UIScene lifecycle. They only
    // invalidate; no background task, persistence or automatic restart exists.
    for name in [UIApplication.willResignActiveNotification,
                 UIApplication.didEnterBackgroundNotification,
                 UIApplication.willTerminateNotification,
                 UIScene.willDeactivateNotification,
                 UIScene.didDisconnectNotification] {
      observers.append(NotificationCenter.default.addObserver(
        forName: name, object: nil, queue: .main) { [weak self] _ in self?.coordinator.clear() })
    }
  }

  func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    coordinator.handle(method: call.method, arguments: call.arguments) { reply in
      switch reply {
      case .opened(let request):
        result(["schema": 1, "handle": request.handle, "epoch": request.epoch] as [String: Any])
      case .closed:
        result(["closed": true])
      case .receipt:
        result(["schema": 1, "profile": "age-x25519-history-v1", "records": 2,
                "imported": true, "authenticated_author": false, "synthetic": true,
                "persisted": false, "transmitted": false] as [String: Any])
      case .failure(let failure):
        result(FlutterError(code: failure.rawValue, message: "archive_probe_failed", details: nil))
      }
    }
  }

  func detachFromEngine(for registrar: FlutterPluginRegistrar) {
    coordinator.dispose()
    channel.setMethodCallHandler(nil)
    removeObservers()
  }
  private func removeObservers() {
    observers.forEach { NotificationCenter.default.removeObserver($0) }
    observers.removeAll()
  }
  deinit { coordinator.dispose(); removeObservers() }
}
