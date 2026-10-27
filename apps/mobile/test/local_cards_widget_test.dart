import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/local_cards/app.dart';

import '../tool/check_local_cards.dart' as checks;

Future<void> tapLocal(WidgetTester t, String key) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

Future<void> startLocal(WidgetTester t) async {
  await tapLocal(t, 'local-cards-ack');
  await tapLocal(t, 'local-cards-start');
}

Future<void> chooseLocal(WidgetTester t) async {
  await startLocal(t);
  await tapLocal(t, 'local-card-daily_rhythm');
  await tapLocal(t, 'local-response-rhythm_plan');
}

void lockedLocal() {
  expect(find.byKey(const Key('local-cards-ack')), findsOneWidget);
  expect(find.byKey(const Key('local-cards-preview-response')), findsNothing);
  expect(find.byKey(const Key('local-cards-preview')), findsNothing);
}

void main() {
  test(
    'pure local catalogue controller and release gate invariants',
    checks.main,
  );
  testWidgets('explicit local boundary gate and no free text input', (t) async {
    await t.pumpWidget(const LocalCardsApp());
    expect(
      t
          .widget<FilledButton>(find.byKey(const Key('local-cards-start')))
          .onPressed,
      isNull,
    );
    expect(find.byType(TextField), findsNothing);
    await startLocal(t);
    expect(find.byKey(const Key('local-card-daily_rhythm')), findsOneWidget);
    expect(find.byKey(const Key('local-cards-boundary')), findsOneWidget);
  });
  testWidgets(
    'one preview remains not delivered and clear returns unchecked gate',
    (t) async {
      await t.pumpWidget(const LocalCardsApp());
      await chooseLocal(t);
      await tapLocal(t, 'local-cards-preview');
      expect(
        find.byKey(const Key('local-cards-not-delivered')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('local-cards-preview-response')),
        findsOneWidget,
      );
      await tapLocal(t, 'local-cards-clear');
      lockedLocal();
      expect(
        t
            .widget<CheckboxListTile>(find.byKey(const Key('local-cards-ack')))
            .value,
        isFalse,
      );
      await startLocal(t);
      await tapLocal(t, 'local-card-daily_rhythm');
      expect(
        t
            .widget<FilledButton>(find.byKey(const Key('local-cards-preview')))
            .onPressed,
        isNull,
      );
    },
  );
  testWidgets('return to catalogue never restores previous response', (
    t,
  ) async {
    await t.pumpWidget(const LocalCardsApp());
    await chooseLocal(t);
    await tapLocal(t, 'local-cards-catalog');
    await tapLocal(t, 'local-card-different_views');
    expect(
      t
          .widget<FilledButton>(find.byKey(const Key('local-cards-preview')))
          .onPressed,
      isNull,
    );
    expect(find.byKey(const Key('local-response-rhythm_plan')), findsNothing);
    await tapLocal(t, 'local-response-views_defer');
    await tapLocal(t, 'local-cards-preview');
    expect(find.byKey(const Key('local-cards-not-delivered')), findsOneWidget);
  });
  testWidgets('stale response callback after clear cannot resurrect draft', (
    t,
  ) async {
    await t.pumpWidget(const LocalCardsApp());
    await startLocal(t);
    await tapLocal(t, 'local-card-daily_rhythm');
    final old = t
        .widget<OutlinedButton>(
          find.byKey(const Key('local-response-rhythm_plan')),
        )
        .onPressed!;
    await tapLocal(t, 'local-cards-clear');
    old();
    await t.pumpAndSettle();
    lockedLocal();
    expect(t.takeException(), isNull);
  });
  testWidgets('unchecking local boundary invalidates captured start callback', (
    t,
  ) async {
    await t.pumpWidget(const LocalCardsApp());
    await tapLocal(t, 'local-cards-ack');
    final old = t
        .widget<FilledButton>(find.byKey(const Key('local-cards-start')))
        .onPressed!;
    await tapLocal(t, 'local-cards-ack');
    old();
    await t.pumpAndSettle();
    lockedLocal();
    expect(find.byKey(const Key('local-card-daily_rhythm')), findsNothing);
  });
  testWidgets('inactive lifecycle and resume do not retain preview', (t) async {
    await t.pumpWidget(const LocalCardsApp());
    await chooseLocal(t);
    await tapLocal(t, 'local-cards-preview');
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await t.pumpAndSettle();
    expect(find.byKey(const Key('local-cards-preview-response')), findsNothing);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await t.pumpAndSettle();
    lockedLocal();
  });
  testWidgets('covered route and pop back reset the draft even while mounted', (
    t,
  ) async {
    await t.pumpWidget(const LocalCardsApp());
    await chooseLocal(t);
    await tapLocal(t, 'local-cards-preview');
    final nav = Navigator.of(t.element(find.byType(Scaffold)));
    nav.push(
      MaterialPageRoute<void>(
        builder: (_) => const Scaffold(body: Text('صفحة اختبار مستقلة')),
      ),
    );
    await t.pumpAndSettle();
    nav.pop();
    await t.pumpAndSettle();
    lockedLocal();
    expect(t.takeException(), isNull);
  });
  testWidgets(
    'explicit hidden host and scope switch clear retained widget state',
    (t) async {
      const key = Key('retained-local-app');
      await t.pumpWidget(const LocalCardsApp(key: key));
      await chooseLocal(t);
      await t.pumpWidget(const LocalCardsApp(key: key, visible: false));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('local-cards-preview')), findsNothing);
      await t.pumpWidget(const LocalCardsApp(key: key));
      await t.pumpAndSettle();
      lockedLocal();
      await chooseLocal(t);
      await t.pumpWidget(const LocalCardsApp(key: key, scopeRevision: 1));
      await t.pumpAndSettle();
      lockedLocal();
    },
  );
  testWidgets(
    'system back and disposal discard rather than restore local choice',
    (t) async {
      await t.pumpWidget(const LocalCardsApp());
      await chooseLocal(t);
      await t.binding.handlePopRoute();
      await t.pumpAndSettle();
      lockedLocal();
      await chooseLocal(t);
      await t.pumpWidget(const SizedBox());
      await t.pumpWidget(const LocalCardsApp());
      await t.pumpAndSettle();
      lockedLocal();
    },
  );
  testWidgets(
    'Arabic RTL at320 and200percent keeps semantic actions and preview usable',
    (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1;
      t.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(t.view.resetPhysicalSize);
      addTearDown(t.view.resetDevicePixelRatio);
      addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);
      final semantics = t.ensureSemantics();
      try {
        await t.pumpWidget(const LocalCardsApp());
        expect(
          Directionality.of(t.element(find.byType(Scaffold))),
          TextDirection.rtl,
        );
        await startLocal(t);
        final named = find.bySemanticsLabel('معاينة بطاقة إيقاع اليوم');
        expect(named, findsOneWidget);
        expect(t.getSize(named).height >= 48, isTrue);
        await tapLocal(t, 'local-card-daily_rhythm');
        await tapLocal(t, 'local-response-rhythm_defer');
        await tapLocal(t, 'local-cards-preview');
        await tapLocal(t, 'local-cards-clear');
        lockedLocal();
        expect(t.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
}
