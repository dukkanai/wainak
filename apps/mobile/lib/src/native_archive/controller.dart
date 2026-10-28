import 'dart:async';

/// No archive bytes, keys, account IDs or conversation content cross this API.
abstract interface class ArchiveProbePort {
  Future<ArchiveLease> open(int epoch);
  Future<ArchiveProbeReceipt> probe(ArchiveLease lease);
  Future<void> close(ArchiveLease lease);
}

final class ArchiveProbeFailure implements Exception {
  const ArchiveProbeFailure(this.code);
  final String code;
  @override
  String toString() => 'ArchiveProbeFailure';
}

final class ArchiveLease {
  const ArchiveLease(this.handle, this.epoch);
  final String handle;
  final int epoch;
  @override
  String toString() => 'ArchiveLease';
}

final class ArchiveProbeReceipt {
  const ArchiveProbeReceipt();
  // The first probe uses exactly two fixed, synthetic records, never user data.
  int get recordCount => 2;
  bool get authenticatedAuthor => false;
  bool get persisted => false;
  bool get transmitted => false;
  @override
  String toString() => 'ArchiveProbeReceipt';
}

enum ArchiveProbeStage { locked, running, completed, failed, disposed }

/// Captured by UI callbacks; a callback cannot acquire a fresh capability late.
final class ArchiveViewToken {
  ArchiveViewToken._(this._owner, this._revision);
  final Object _owner;
  final int _revision;
}

final class ArchiveProbeController {
  ArchiveProbeController(this._port, {this.onChanged});
  final ArchiveProbePort _port;
  final void Function()? onChanged;
  final Object _owner = Object();
  int _revision = 0;
  ArchiveProbeStage _stage = ArchiveProbeStage.locked;
  ArchiveLease? _lease;
  bool _consent = false;
  String? _failure;

  ArchiveProbeStage get stage => _stage;
  bool get consent => _consent;
  String? get failure => _failure;
  ArchiveViewToken get viewToken => ArchiveViewToken._(_owner, _revision);
  bool current(ArchiveViewToken token) =>
      _stage != ArchiveProbeStage.disposed &&
      identical(token._owner, _owner) &&
      token._revision == _revision;

  void acknowledge(ArchiveViewToken token, bool value) {
    if (!current(token) || _stage == ArchiveProbeStage.running) return;
    _revision++;
    _consent = value;
    _stage = ArchiveProbeStage.locked;
    _failure = null;
    onChanged?.call();
  }

  Future<void> run(ArchiveViewToken token) async {
    if (!current(token) || !_consent || _stage == ArchiveProbeStage.running) {
      return;
    }
    final revision = ++_revision;
    _stage = ArchiveProbeStage.running;
    _failure = null;
    onChanged?.call();
    ArchiveLease? opened;
    bool succeeded = false;
    String? failure;
    try {
      opened = await _port.open(revision);
      if (!_active(revision)) return;
      if (opened.epoch != revision) {
        throw const ArchiveProbeFailure('invalid');
      }
      _lease = opened;
      await _port.probe(opened);
      succeeded = true;
    } on ArchiveProbeFailure catch (error) {
      failure = switch (error.code) {
        'unavailable' => 'unavailable',
        'timeout' => 'timeout',
        'capacity' => 'capacity',
        _ => 'failed',
      };
    } catch (_) {
      failure = 'failed';
    } finally {
      // Late open also closes its own lease, never a replacement operation.
      if (opened != null) {
        try {
          await _port.close(opened);
        } catch (_) {
          succeeded = false;
          failure = 'cleanup_unconfirmed';
        }
      }
      if (_active(revision)) {
        _lease = null;
        _consent = false;
        _failure = failure;
        _stage = succeeded
            ? ArchiveProbeStage.completed
            : ArchiveProbeStage.failed;
        _revision++;
        onChanged?.call();
      }
    }
  }

  bool _active(int revision) =>
      _stage == ArchiveProbeStage.running && _revision == revision;

  /// Invalidates visible state immediately. Does not promise secure zeroization.
  void clear() {
    if (_stage == ArchiveProbeStage.disposed) return;
    _revision++;
    final old = _lease;
    _lease = null;
    _consent = false;
    _failure = null;
    _stage = ArchiveProbeStage.locked;
    if (old != null) unawaited(_closeQuietly(old));
    onChanged?.call();
  }

  Future<void> _closeQuietly(ArchiveLease lease) async {
    try {
      await _port.close(lease);
    } catch (_) {
      // Visible state remains cleared; platform cleanup is not claimed here.
    }
  }

  void dispose() {
    if (_stage == ArchiveProbeStage.disposed) return;
    clear();
    _revision++;
    _stage = ArchiveProbeStage.disposed;
  }
}
