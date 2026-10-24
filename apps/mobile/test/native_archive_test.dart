import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/native_archive/channel.dart';
import 'package:wainak_mobile/src/native_archive/controller.dart';

class ProbeFixture implements ArchiveProbePort {
  Completer<ArchiveLease>? opening;
  Completer<ArchiveProbeReceipt>? running;
  bool failClose = false;
  int opens = 0;
  int probes = 0;
  final closed = <ArchiveLease>[];
  @override
  Future<ArchiveLease> open(int epoch) async {
    opens++;
    return opening?.future ??
        ArchiveLease('probe_${opens.toString().padLeft(32, '0')}', epoch);
  }

  @override
  Future<ArchiveProbeReceipt> probe(ArchiveLease lease) async {
    probes++;
    return running?.future ?? const ArchiveProbeReceipt();
  }

  @override
  Future<void> close(ArchiveLease lease) async {
    closed.add(lease);
    if (failClose) throw const ArchiveProbeFailure('failed');
  }
}

void agree(ArchiveProbeController c) => c.acknowledge(c.viewToken, true);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'fixture only: consent gate, one operation and completion after close',
    () async {
      final port = ProbeFixture();
      final c = ArchiveProbeController(port);
      await c.run(c.viewToken);
      expect(port.opens, 0);
      agree(c);
      final token = c.viewToken;
      final first = c.run(token);
      await c.run(token);
      await first;
      expect(port.opens, 1);
      expect(port.probes, 1);
      expect(port.closed, hasLength(1));
      expect(c.stage, ArchiveProbeStage.completed);
      expect(c.consent, false);
      c.dispose();
    },
  );
  test('stale and foreign view capabilities cannot reopen the gate', () async {
    final port = ProbeFixture();
    final a = ArchiveProbeController(port);
    final b = ArchiveProbeController(port);
    final old = a.viewToken;
    a.clear();
    a.acknowledge(old, true);
    a.acknowledge(b.viewToken, true);
    await a.run(old);
    expect(a.consent, false);
    expect(port.opens, 0);
    a.dispose();
    b.dispose();
  });
  test(
    'late open after clear closes own lease and never runs crypto',
    () async {
      final port = ProbeFixture()..opening = Completer<ArchiveLease>();
      final c = ArchiveProbeController(port);
      agree(c);
      final task = c.run(c.viewToken);
      c.clear();
      const lease = ArchiveLease('probe_00000000000000000000000000000001', 2);
      port.opening!.complete(lease);
      await task;
      expect(port.probes, 0);
      expect(port.closed.single, same(lease));
      expect(c.stage, ArchiveProbeStage.locked);
      c.dispose();
    },
  );
  test('late previous result cannot overwrite a replacement view', () async {
    final port = ProbeFixture()..running = Completer<ArchiveProbeReceipt>();
    final c = ArchiveProbeController(port);
    agree(c);
    final old = c.run(c.viewToken);
    await Future<void>.delayed(Duration.zero);
    final pending = port.running!;
    c.clear();
    port.running = null;
    agree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.completed);
    pending.complete(const ArchiveProbeReceipt());
    await old;
    expect(c.stage, ArchiveProbeStage.completed);
    expect(port.opens, 2);
    expect(port.closed.map((x) => x.handle).toSet(), hasLength(2));
    c.dispose();
  });
  test(
    'disposed controller rejects late open and all future callbacks',
    () async {
      final port = ProbeFixture()..opening = Completer<ArchiveLease>();
      final c = ArchiveProbeController(port);
      agree(c);
      final token = c.viewToken;
      final task = c.run(token);
      c.dispose();
      port.opening!.complete(
        const ArchiveLease('probe_00000000000000000000000000000001', 2),
      );
      await task;
      c.acknowledge(token, true);
      await c.run(c.viewToken);
      expect(c.stage, ArchiveProbeStage.disposed);
      expect(port.opens, 1);
      expect(port.probes, 0);
      expect(port.closed, hasLength(1));
    },
  );
  test('cleanup uncertainty prevents success', () async {
    final c = ArchiveProbeController(ProbeFixture()..failClose = true);
    agree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.failed);
    expect(c.failure, 'cleanup_unconfirmed');
    c.dispose();
  });

  const channel = MethodChannel('wainak/native_archive_v1');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  test(
    'channel validates exact safe receipt; no native evidence implied',
    () async {
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        if (call.method == 'open') return call.arguments;
        if (call.method == 'close') return {'closed': true};
        return {
          'schema': 1,
          'profile': 'age-x25519-history-v1',
          'records': 2,
          'imported': true,
          'authenticated_author': false,
          'synthetic': true,
          'persisted': false,
          'transmitted': false,
        };
      });
      final c = ArchiveProbeController(MethodChannelArchiveProbe());
      agree(c);
      await c.run(c.viewToken);
      expect(c.stage, ArchiveProbeStage.completed);
      expect(calls.map((x) => x.method), ['open', 'probe', 'close']);
      expect(
        calls.every(
          (x) => (x.arguments as Map).keys.toSet().difference({
            'schema',
            'handle',
            'epoch',
          }).isEmpty,
        ),
        true,
      );
      c.dispose();
    },
  );
  test(
    'malformed open closes requested handle, not returned foreign handle',
    () async {
      String? opened;
      String? closed;
      messenger.setMockMethodCallHandler(channel, (call) async {
        final args = call.arguments as Map;
        if (call.method == 'open') {
          opened = args['handle'] as String;
          return {'schema': 1, 'handle': 'foreign', 'epoch': args['epoch']};
        }
        closed = args['handle'] as String;
        return {'closed': true};
      });
      final c = ArchiveProbeController(MethodChannelArchiveProbe());
      agree(c);
      await c.run(c.viewToken);
      expect(c.stage, ArchiveProbeStage.failed);
      expect(closed == opened, true);
      c.dispose();
    },
  );
  test('unknown/trust-bearing receipt rejected and closed', () async {
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'open') return call.arguments;
      if (call.method == 'close') return {'closed': true};
      return {'schema': 1, 'authenticated_author': true};
    });
    final c = ArchiveProbeController(MethodChannelArchiveProbe());
    agree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.failed);
    c.dispose();
  });
  test('absent plugin never silently falls back to fixture', () async {
    final c = ArchiveProbeController(MethodChannelArchiveProbe());
    agree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.failed);
    expect(c.failure, 'unavailable');
    expect(
      const ArchiveProbeFailure('private operand').toString(),
      'ArchiveProbeFailure',
    );
    c.dispose();
  });
}
