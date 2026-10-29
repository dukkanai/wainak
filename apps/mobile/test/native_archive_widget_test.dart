import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/native_archive/app.dart';
import 'package:wainek_mobile/src/native_archive/controller.dart';

import 'native_archive_test.dart' show ProbeFixture;

Future<void> tapVisible(WidgetTester tester, String key) async {
  final finder = find.byKey(ValueKey(key));
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  test('development gate is default-off and rejects release', () {
    expect(archiveProbeEnabled(optedIn: false, release: false), false);
    expect(archiveProbeEnabled(optedIn: true, release: true), false);
    expect(archiveProbeEnabled(optedIn: true, release: false), true);
  });
  testWidgets(
    'fixture UI Arabic RTL, 200% text and explicit synthetic success',
    (tester) async {
      tester.view.physicalSize = const Size(320, 1100);
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final port = ProbeFixture();
      await tester.pumpWidget(NativeArchiveApp(port: port));
      expect(
        Directionality.of(tester.element(find.byType(Scaffold))),
        TextDirection.rtl,
      );
      await tapVisible(tester, 'archive-ack');
      await tapVisible(tester, 'archive-run');
      expect(port.probes, 1);
      expect(find.textContaining('أعاد المحرك نجاح'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tapVisible(tester, 'archive-clear');
      expect(find.textContaining('لم يبدأ الاختبار'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'background invalidates pending result and captured consent callback',
    (tester) async {
      final port = ProbeFixture()..running = Completer<ArchiveProbeReceipt>();
      await tester.pumpWidget(NativeArchiveApp(port: port));
      final oldCheck = tester
          .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
          .onChanged!;
      await tapVisible(tester, 'archive-ack');
      await tapVisible(tester, 'archive-run');
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
            .onChanged,
        isNull,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await tester.pump();
      oldCheck(true);
      port.running!.complete(const ArchiveProbeReceipt());
      await tester.pumpAndSettle();
      expect(find.textContaining('أعاد المحرك نجاح'), findsNothing);
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
            .value,
        false,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets('cover and return cannot replay a captured start callback', (
    tester,
  ) async {
    final port = ProbeFixture();
    await tester.pumpWidget(NativeArchiveApp(port: port));
    await tapVisible(tester, 'archive-ack');
    final start = tester
        .widget<FilledButton>(find.byKey(const ValueKey('archive-run')))
        .onPressed!;
    final nav = tester.state<NavigatorState>(find.byType(Navigator));
    unawaited(
      nav.push(
        MaterialPageRoute<void>(
          builder: (_) => const Scaffold(body: Text('غطاء اختباري')),
        ),
      ),
    );
    await tester.pumpAndSettle();
    start();
    nav.pop();
    await tester.pumpAndSettle();
    start();
    await tester.pumpAndSettle();
    expect(port.opens, 0);
    expect(
      tester
          .widget<CheckboxListTile>(find.byKey(const ValueKey('archive-ack')))
          .value,
      false,
    );
    await tester.pumpWidget(const SizedBox());
  });
}
