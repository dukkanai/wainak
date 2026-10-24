import 'dart:async';
import 'dart:math';

import 'package:flutter/services.dart';

import 'controller.dart';

/// Fixed, versioned channel. No untrusted native message/details are surfaced.
final class MethodChannelArchiveProbe implements ArchiveProbePort {
  MethodChannelArchiveProbe({
    MethodChannel? channel,
    this.timeout = const Duration(seconds: 35),
  }) : _channel = channel ?? const MethodChannel('wainak/native_archive_v1') {
    if (timeout <= Duration.zero || timeout > const Duration(seconds: 35)) {
      throw ArgumentError('archive_timeout');
    }
  }

  final MethodChannel _channel;
  final Duration timeout;
  static final _handle = RegExp(r'^probe_[a-f0-9]{32}$');

  Future<Map<Object?, Object?>> _call(
    String method,
    Map<String, Object> arguments,
  ) async {
    try {
      final raw = await _channel
          .invokeMethod<Object?>(method, arguments)
          .timeout(timeout);
      if (raw is! Map<Object?, Object?>) {
        throw const ArchiveProbeFailure('invalid');
      }
      return raw;
    } on MissingPluginException {
      throw const ArchiveProbeFailure('unavailable');
    } on TimeoutException {
      throw const ArchiveProbeFailure('timeout');
    } on PlatformException catch (error) {
      throw ArchiveProbeFailure(
        error.code == 'unavailable' ? 'unavailable' : 'failed',
      );
    }
  }

  void _validLease(ArchiveLease lease) {
    if (!_handle.hasMatch(lease.handle) ||
        lease.epoch < 1 ||
        lease.epoch > 0x1fffffffffffff) {
      throw const ArchiveProbeFailure('invalid');
    }
  }

  @override
  Future<ArchiveLease> open(int epoch) async {
    if (epoch < 1 || epoch > 0x1fffffffffffff) {
      throw const ArchiveProbeFailure('invalid');
    }
    final random = Random.secure();
    final handle =
        'probe_${List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';
    final lease = ArchiveLease(handle, epoch);
    try {
      final raw = await _call('open', {
        'schema': 1,
        'epoch': epoch,
        'handle': handle,
      });
      if (raw.length != 3 ||
          raw['schema'] is! int ||
          raw['schema'] != 1 ||
          raw['epoch'] is! int ||
          raw['epoch'] != epoch ||
          raw['handle'] != handle) {
        throw const ArchiveProbeFailure('invalid');
      }
      return lease;
    } catch (_) {
      // The request ID is known even if the open reply is lost or malformed.
      try {
        await close(lease);
      } catch (_) {
        // No success/cleanup claim; native Activity lifecycle also invalidates.
      }
      rethrow;
    }
  }

  @override
  Future<ArchiveProbeReceipt> probe(ArchiveLease lease) async {
    _validLease(lease);
    final raw = await _call('probe', {
      'schema': 1,
      'handle': lease.handle,
      'epoch': lease.epoch,
    });
    const expected = <String, Object>{
      'schema': 1,
      'profile': 'age-x25519-history-v1',
      'records': 2,
      'imported': true,
      'authenticated_author': false,
      'synthetic': true,
      'persisted': false,
      'transmitted': false,
    };
    if (raw.length != expected.length ||
        expected.entries.any((entry) => raw[entry.key] != entry.value) ||
        raw['schema'] is! int ||
        raw['records'] is! int) {
      throw const ArchiveProbeFailure('invalid');
    }
    return const ArchiveProbeReceipt();
  }

  @override
  Future<void> close(ArchiveLease lease) async {
    _validLease(lease);
    final raw = await _call('close', {
      'schema': 1,
      'handle': lease.handle,
      'epoch': lease.epoch,
    });
    if (raw.length != 1 || raw['closed'] != true) {
      throw const ArchiveProbeFailure('invalid');
    }
  }
}
