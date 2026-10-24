// Regression from independent keyboard/consent QA.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/connected_app.dart';
import 'connected_widget_test.dart' as fixture;

Future<bool> focusAdultByTab(WidgetTester t) async {
  for (var i = 0; i < 32; i++) {
    await t.sendKeyEvent(LogicalKeyboardKey.tab);
    await t.pump();
    final context = FocusManager.instance.primaryFocus?.context;
    final tile = context?.findAncestorWidgetOfExactType<CheckboxListTile>();
    if (tile?.key == const Key('api-adult')) return true;
  }
  return false;
}

void main() {
  testWidgets('pending registration cannot silently edit declarations by keyboard', (
    t,
  ) async {
    final api = fixture.FixtureApi()..holdRegistration = true;
    await t.pumpWidget(ConnectedWainakApp(repository: fixture.repository(api)));
    for (final key in ['api-adult', 'api-muslim', 'api-terms', 'api-privacy']) {
      await fixture.tap(t, key);
    }
    // Positive control: prove the keyboard path reaches and changes this tile while idle.
    expect(await focusAdultByTab(t), isTrue);
    await t.sendKeyEvent(LogicalKeyboardKey.space);
    await t.pump();
    expect(
      t.widget<CheckboxListTile>(find.byKey(const Key('api-adult'))).value,
      isFalse,
    );
    await t.sendKeyEvent(LogicalKeyboardKey.space);
    await t.pump();
    expect(
      t.widget<CheckboxListTile>(find.byKey(const Key('api-adult'))).value,
      isTrue,
    );
    await fixture.tap(t, 'api-register');
    expect(find.byKey(const Key('api-busy')), findsOneWidget);
    try {
      // Tab through the actual tree rather than calling a callback directly.
      final focusedAdult = await focusAdultByTab(t);
      if (focusedAdult) {
        await t.ensureVisible(find.byKey(const Key('api-adult')));
        await t.sendKeyEvent(LogicalKeyboardKey.space);
        await t.pump();
      }
      // It is also acceptable for busy declarations to be excluded from focus.
      expect(
        t.widget<CheckboxListTile>(find.byKey(const Key('api-adult'))).value,
        isTrue,
        reason:
            'An in-flight declaration must not visibly change while its request is pending.',
      );
      expect(api.calls.where((c) => c == 'POST /v1/dev/accounts').length, 1);
    } finally {
      if (api.registration != null && !api.registration!.isCompleted) {
        api.registration!.complete(api.registrationResponse);
      }
      await t.pumpAndSettle();
      await t.pumpWidget(const SizedBox());
    }
    expect(t.takeException(), isNull);
  });
}
