import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/main.dart';
import 'package:wainak_mobile/src/app.dart';
import 'package:wainak_mobile/src/repository.dart';
import 'package:wainak_mobile/src/theme.dart';

Future<void> tap(WidgetTester t, String key) async {
  final finder = find.byKey(Key(key));
  await t.ensureVisible(finder);
  await t.pumpAndSettle();
  await t.tap(finder);
  await t.pumpAndSettle();
}

Future<void> choose(WidgetTester t, String text) async {
  final finder = find.text(text).last;
  await t.ensureVisible(finder);
  await t.pumpAndSettle();
  await t.tap(finder);
  await t.pumpAndSettle();
}

Future<void> toCandidate(WidgetTester t, DevJourneyRepository r) async {
  await t.pumpWidget(WainakApp(repository: r));
  for (final key in [
    'adult',
    'muslim',
    'terms',
    'privacy',
    'register',
    'save-profile',
  ]) {
    await tap(t, key);
  }
  await choose(t, 'القيم والأهداف');
  await tap(t, 'save-assessment');
}

void main() {
  testWidgets('default build is inert without explicit development flag', (
    t,
  ) async {
    await t.pumpWidget(const DisabledBuild());
    expect(find.byKey(const Key('register')), findsNothing);
    expect(find.textContaining('الخدمات الفعلية غير متصلة'), findsOneWidget);
  });
  testWidgets('RTL and required eligibility failures are readable', (t) async {
    await t.pumpWidget(WainakApp(repository: DevJourneyRepository()));
    expect(
      Directionality.of(t.element(find.byKey(const Key('register')))),
      TextDirection.rtl,
    );
    await tap(t, 'register');
    expect(find.byKey(const Key('error')), findsOneWidget);
    expect(find.textContaining('أكمل الإقرارات'), findsOneWidget);
  });
  testWidgets(
    'full path acceptance activation choice offline retry block report delete',
    (t) async {
      final r = DevJourneyRepository();
      await toCandidate(t, r);
      await tap(t, 'request');
      expect(find.byKey(const Key('activate')), findsNothing);
      await tap(t, 'accept');
      expect(r.relationship, RelationshipState.acceptedPendingActivation);
      await tap(t, 'activate');
      await choose(t, 'نحدد وقتًا هادئًا للحوار');
      expect(r.answer, isNull);
      await tap(t, 'network');
      await tap(t, 'send');
      expect(r.answerPending, isTrue);
      await tap(t, 'network');
      expect(r.answerPending, isTrue);
      await tap(t, 'retry');
      expect(r.answerPending, isFalse);
      await tap(t, 'block');
      await choose(t, 'تأكيد الحظر');
      expect(r.relationship, RelationshipState.blocked);
      expect(find.byKey(const Key('send')), findsNothing);
      await tap(t, 'report');
      await choose(t, 'تحرش أو إساءة');
      await tap(t, 'submit-report');
      expect(r.reports, 1);
      await tap(t, 'account');
      await tap(t, 'delete');
      await choose(t, 'تأكيد حذف التجربة');
      expect(r.registered, isFalse);
      expect(find.byKey(const Key('register')), findsOneWidget);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'cancelled request remains cancelled across back and forward navigation',
    (t) async {
      final r = DevJourneyRepository();
      await toCandidate(t, r);
      await tap(t, 'request');
      await tap(t, 'cancel-request');
      await tap(t, 'back');
      await tap(t, 'save-assessment');
      expect(r.relationship, RelationshipState.cancelled);
      expect(find.byKey(const Key('activate')), findsNothing);
    },
  );
  testWidgets(
    '200% at 320 logical pixels covers whole path and safety dialogs',
    (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1;
      t.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(() {
        t.view.resetPhysicalSize();
        t.view.resetDevicePixelRatio();
        t.platformDispatcher.clearTextScaleFactorTestValue();
      });
      final r = DevJourneyRepository();
      await toCandidate(t, r);
      expect(t.takeException(), isNull);
      await tap(t, 'theme');
      expect(t.takeException(), isNull);
      await tap(t, 'request');
      await tap(t, 'accept');
      await tap(t, 'activate');
      await choose(t, 'أحتاج وقتًا للتفكير أولًا');
      await tap(t, 'send');
      await tap(t, 'report');
      await choose(t, 'سلامة طفل أو قاصر');
      await tap(t, 'submit-report');
      await tap(t, 'block');
      await choose(t, 'الرجوع');
      await tap(t, 'account');
      await tap(t, 'delete');
      await choose(t, 'الرجوع');
      expect(t.takeException(), isNull);
    },
  );
  testWidgets('48 targets and labeled tap actions on eligibility', (t) async {
    final handle = t.ensureSemantics();
    try {
      await t.pumpWidget(WainakApp(repository: DevJourneyRepository()));
      await t.pumpAndSettle();
      await t.ensureVisible(find.byKey(const Key('register')));
      await t.pumpAndSettle();
      expect(
        t.getSize(find.byKey(const Key('register'))).height,
        greaterThanOrEqualTo(48),
      );
      await expectLater(t, meetsGuideline(androidTapTargetGuideline));
      await expectLater(t, meetsGuideline(labeledTapTargetGuideline));
    } finally {
      handle.dispose();
    }
  });
  test(
    'design tokens keep helper text at 16 and contrast above required thresholds',
    () {
      final theme = WainakTokens.theme(Brightness.light);
      expect(theme.textTheme.bodySmall!.fontSize, 16);
      double contrast(Color a, Color b) {
        final x = a.computeLuminance(), y = b.computeLuminance();
        return ((x > y ? x : y) + .05) / ((x < y ? x : y) + .05);
      }

      expect(
        contrast(WainakTokens.ink, WainakTokens.background),
        greaterThan(4.5),
      );
      expect(
        contrast(WainakTokens.muted, WainakTokens.background),
        greaterThan(4.5),
      );
      expect(contrast(Colors.white, WainakTokens.primary), greaterThan(4.5));
      expect(contrast(WainakTokens.outline, Colors.white), greaterThan(3));
      final dark = WainakTokens.theme(Brightness.dark).colorScheme;
      expect(contrast(dark.primary, dark.onPrimary), greaterThan(4.5));
      expect(contrast(dark.onSurfaceVariant, dark.surface), greaterThan(4.5));
    },
  );
}
