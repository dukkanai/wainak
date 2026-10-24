import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/native_archive/app.dart';
import 'package:wainak_mobile/src/native_archive/channel.dart';
import 'package:wainak_mobile/src/native_archive/controller.dart';

// Independent synthetic ports only. Passing these cases is not native evidence.
final class QaPort implements ArchiveProbePort {
  final openings = <int, Completer<ArchiveLease>>{};
  final probes = <String, Completer<ArchiveProbeReceipt>>{};
  final closings = <String, Completer<void>>{};
  final closed = <ArchiveLease>[];
  final called = <ArchiveLease>[];
  bool holdOpen = false;
  bool holdProbe = false;
  bool holdClose = false;
  int opens = 0;
  @override
  Future<ArchiveLease> open(int epoch) async {
    opens++;
    if (holdOpen) return (openings[epoch] = Completer<ArchiveLease>()).future;
    return ArchiveLease('probe_${opens.toString().padLeft(32, '0')}', epoch);
  }

  @override
  Future<ArchiveProbeReceipt> probe(ArchiveLease lease) async {
    called.add(lease);
    if (holdProbe)
      return (probes[lease.handle] = Completer<ArchiveProbeReceipt>()).future;
    return const ArchiveProbeReceipt();
  }

  @override
  Future<void> close(ArchiveLease lease) async {
    closed.add(lease);
    if (holdClose) return (closings[lease.handle] ??= Completer<void>()).future;
  }
}

void qaAgree(ArchiveProbeController c) => c.acknowledge(c.viewToken, true);
Future<void> qaTick() => Future<void>.delayed(Duration.zero);
const qaChannel = MethodChannel('wainak/native_archive_v1');
const qaReceipt = <String, Object>{
  'schema': 1,
  'profile': 'age-x25519-history-v1',
  'records': 2,
  'imported': true,
  'authenticated_author': false,
  'synthetic': true,
  'persisted': false,
  'transmitted': false,
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() => messenger.setMockMethodCallHandler(qaChannel, null));

  test(
    'QA old open cannot retarget or overwrite completed replacement',
    () async {
      final port = QaPort()..holdOpen = true;
      final c = ArchiveProbeController(port);
      qaAgree(c);
      final first = c.run(c.viewToken);
      final oldEpoch = port.openings.keys.single;
      c.clear();
      port.holdOpen = false;
      qaAgree(c);
      await c.run(c.viewToken);
      expect(c.stage, ArchiveProbeStage.completed);
      final replacement = port.called.single;
      const oldHandle = 'probe_11111111111111111111111111111111';
      port.openings[oldEpoch]!.complete(ArchiveLease(oldHandle, oldEpoch));
      await first;
      expect(port.called, [replacement]);
      expect(port.closed.map((e) => e.handle).toSet(), {
        oldHandle,
        replacement.handle,
      });
      expect(c.stage, ArchiveProbeStage.completed);
      c.dispose();
    },
  );

  test(
    'QA completion requires close acknowledgement and cannot race clear',
    () async {
      final port = QaPort()..holdClose = true;
      final c = ArchiveProbeController(port);
      qaAgree(c);
      final work = c.run(c.viewToken);
      await qaTick();
      expect(c.stage, ArchiveProbeStage.running);
      expect(port.closings, hasLength(1));
      c.clear();
      port.closings.values.single.complete();
      await work;
      expect(c.stage, ArchiveProbeStage.locked);
      expect(c.consent, false);
      c.dispose();
    },
  );

  test(
    'QA late failure after disposal cannot mutate state or notify',
    () async {
      final port = QaPort()..holdProbe = true;
      var changes = 0;
      final c = ArchiveProbeController(port, onChanged: () => changes++);
      qaAgree(c);
      final task = c.run(c.viewToken);
      await qaTick();
      c.dispose();
      final atDispose = changes;
      port.probes.values.single.completeError(
        const ArchiveProbeFailure('private_detail'),
      );
      await task;
      expect(c.stage, ArchiveProbeStage.disposed);
      expect(c.failure, isNull);
      expect(changes, atDispose);
      expect(
        port.closed.every((e) => e.handle == port.called.single.handle),
        true,
      );
    },
  );

  test(
    'QA mismatched open epoch is rejected and its lease is closed',
    () async {
      final port = QaPort()..holdOpen = true;
      final c = ArchiveProbeController(port);
      qaAgree(c);
      final task = c.run(c.viewToken);
      final epoch = port.openings.keys.single;
      const handle = 'probe_22222222222222222222222222222222';
      port.openings[epoch]!.complete(ArchiveLease(handle, epoch + 1));
      await task;
      expect(port.called, isEmpty);
      expect(port.closed.single.handle, handle);
      expect(c.stage, ArchiveProbeStage.failed);
      expect(c.failure, 'failed');
      c.dispose();
    },
  );

  test(
    'QA stale callbacks remain invalid after clear and new acknowledgement',
    () async {
      final port = QaPort();
      final c = ArchiveProbeController(port);
      qaAgree(c);
      final stale = c.viewToken;
      c.clear();
      qaAgree(c);
      c.acknowledge(stale, false);
      await c.run(stale);
      expect(c.consent, true);
      expect(port.opens, 0);
      await c.run(c.viewToken);
      expect(port.opens, 1);
      c.dispose();
    },
  );

  test('QA lost open response closes only caller-known lifecycle ID', () async {
    final pending = Completer<Object?>();
    String? opened;
    String? closed;
    messenger.setMockMethodCallHandler(qaChannel, (call) async {
      final args = call.arguments as Map;
      if (call.method == 'open') {
        opened = args['handle'] as String;
        return pending.future;
      }
      expect(call.method, 'close');
      closed = args['handle'] as String;
      return {'closed': true};
    });
    final port = MethodChannelArchiveProbe(
      timeout: const Duration(milliseconds: 10),
    );
    await expectLater(
      port.open(3),
      throwsA(
        isA<ArchiveProbeFailure>().having((e) => e.code, 'code', 'timeout'),
      ),
    );
    expect(closed, opened);
    pending.complete({'schema': 1, 'epoch': 3, 'handle': opened});
    await qaTick();
  });

  test(
    'QA receipt rejects every authority and numeric type deviation',
    () async {
      final variants = <Map<String, Object>>[
        {...qaReceipt, 'schema': 1.0},
        {...qaReceipt, 'records': 2.0},
        {...qaReceipt, 'authenticated_author': true},
        {...qaReceipt, 'persisted': true},
        {...qaReceipt, 'transmitted': true},
        {...qaReceipt, 'synthetic': false},
        {...qaReceipt, 'extra': 'public_fixture'},
        {...qaReceipt, 'records': 1},
        {...qaReceipt, 'profile': 'unexpected'},
        {...qaReceipt}..remove('imported'),
      ];
      for (final invalid in variants) {
        var closes = 0;
        messenger.setMockMethodCallHandler(qaChannel, (call) async {
          if (call.method == 'open') return call.arguments;
          if (call.method == 'close') {
            closes++;
            return {'closed': true};
          }
          return invalid;
        });
        final c = ArchiveProbeController(MethodChannelArchiveProbe());
        qaAgree(c);
        await c.run(c.viewToken);
        expect(c.stage, ArchiveProbeStage.failed);
        expect(closes, 1);
        c.dispose();
      }
    },
  );

  test('QA malformed close never acknowledges successful probe', () async {
    messenger.setMockMethodCallHandler(qaChannel, (call) async {
      if (call.method == 'open') return call.arguments;
      if (call.method == 'close') return {'closed': true, 'extra': false};
      return qaReceipt;
    });
    final c = ArchiveProbeController(MethodChannelArchiveProbe());
    qaAgree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.failed);
    expect(c.failure, 'cleanup_unconfirmed');
    c.dispose();
  });

  test('QA error operands and absent plugin cannot become success', () async {
    messenger.setMockMethodCallHandler(qaChannel, (call) async {
      throw PlatformException(
        code: 'private_code',
        message: 'private_message',
        details: 'private_detail',
      );
    });
    final c = ArchiveProbeController(MethodChannelArchiveProbe());
    qaAgree(c);
    await c.run(c.viewToken);
    expect(c.stage, ArchiveProbeStage.failed);
    expect(c.failure, 'failed');
    expect(
      const ArchiveProbeFailure('private_detail').toString(),
      'ArchiveProbeFailure',
    );
    c.dispose();
  });

  testWidgets(
    'QA hidden scope invalidates acknowledgement and captured callback',
    (tester) async {
      final port = QaPort();
      final observer = RouteObserver<ModalRoute<void>>();
      Widget view(bool visible, String scope) => MaterialApp(
        home: ArchiveProbeScreen(
          port: port,
          observer: observer,
          visible: visible,
          scope: scope,
        ),
      );
      await tester.pumpWidget(view(true, 'first'));
      await tester.tap(find.byKey(const ValueKey('archive-ack')));
      await tester.pump();
      final oldRun = tester
          .widget<FilledButton>(find.byKey(const ValueKey('archive-run')))
          .onPressed!;
      await tester.pumpWidget(view(false, 'second'));
      oldRun();
      await tester.pump();
      expect(port.opens, 0);
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
            .value,
        false,
      );
      await tester.pumpWidget(view(true, 'second'));
      expect(
        tester
            .widget<FilledButton>(find.byKey(const ValueKey('archive-run')))
            .onPressed,
        isNull,
      );
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'QA back clears while open is pending and late reply stays closed',
    (tester) async {
      final port = QaPort()..holdOpen = true;
      await tester.pumpWidget(NativeArchiveApp(port: port));
      await tester.tap(find.byKey(const ValueKey('archive-ack')));
      await tester.pump();
      await tester.ensureVisible(find.byKey(const ValueKey('archive-run')));
      await tester.tap(find.byKey(const ValueKey('archive-run')));
      await tester.pump();
      final epoch = port.openings.keys.single;
      await tester.binding.handlePopRoute();
      await tester.pump();
      port.openings[epoch]!.complete(
        ArchiveLease('probe_33333333333333333333333333333333', epoch),
      );
      await tester.pump();
      await tester.pump();
      expect(port.called, isEmpty);
      expect(port.closed, hasLength(1));
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
            .value,
        false,
      );
      expect(find.textContaining('أعاد المحرك نجاح'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('QA replacement port is not silently retargeted', (tester) async {
    final first = QaPort();
    final replacement = QaPort();
    final observer = RouteObserver<ModalRoute<void>>();
    Widget view(QaPort port) => MaterialApp(
      home: ArchiveProbeScreen(port: port, observer: observer),
    );
    await tester.pumpWidget(view(first));
    await tester.tap(find.byKey(const ValueKey('archive-ack')));
    await tester.pump();
    await tester.pumpWidget(view(replacement));
    expect(
      tester
          .widget<FilledButton>(find.byKey(const ValueKey('archive-run')))
          .onPressed,
      isNull,
    );
    expect(first.opens, 0);
    expect(replacement.opens, 0);
    await tester.pumpWidget(const SizedBox());
  });
}
