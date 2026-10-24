import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/main.dart' as application;
import 'package:wainak_mobile/src/native_archive/app.dart';

void main() {
  const dev = bool.fromEnvironment('WAINAK_DEV_MODE');
  const mode = String.fromEnvironment(
    'WAINAK_REPOSITORY',
    defaultValue: 'fake',
  );
  testWidgets(
    'actual entry default-off or explicit Android missing-plugin failure',
    (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      try {
        application.main();
        await tester.pumpAndSettle();
        if (!dev) {
          expect(find.byType(application.DisabledBuild), findsOneWidget);
          expect(find.byType(NativeArchiveApp), findsNothing);
        } else {
          expect(find.byType(NativeArchiveApp), findsOneWidget);
          await tester.ensureVisible(find.byKey(const ValueKey('archive-ack')));
          await tester.tap(find.byKey(const ValueKey('archive-ack')));
          await tester.pumpAndSettle();
          expect(
            tester
                .widget<CheckboxListTile>(
                  find.byKey(const ValueKey('archive-ack')),
                )
                .value,
            true,
          );
          expect(
            tester
                .widget<FilledButton>(find.byKey(const ValueKey('archive-run')))
                .onPressed,
            isNotNull,
          );
          await tester.ensureVisible(find.byKey(const ValueKey('archive-run')));
          await tester.tap(find.byKey(const ValueKey('archive-run')));
          await tester.pumpAndSettle();
          // Let the real Flutter test-engine missing-plugin reply arrive;
          // pumpAndSettle only drains scheduled frames, not platform futures.
          for (
            var turn = 0;
            turn < 30 &&
                find
                    .textContaining('المحرك الأصلي غير متاح')
                    .evaluate()
                    .isEmpty;
            turn++
          ) {
            await tester.runAsync(
              () => Future<void>.delayed(const Duration(milliseconds: 20)),
            );
            await tester.pump();
          }
          expect(
            find.textContaining('المحرك الأصلي غير متاح'),
            findsOneWidget,
            reason: tester
                .widget<Text>(find.byKey(const ValueKey('archive-status')))
                .data,
          );

          expect(find.textContaining('أعاد المحرك نجاح'), findsNothing);
        }
        await tester.pumpWidget(const SizedBox());
      } finally {
        debugDefaultTargetPlatformOverride = null;
      }
    },
    skip: dev && mode != 'native_archive',
  );

  testWidgets('actual entry rejects non-Android even with opt-in', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      application.main();
      await tester.pumpAndSettle();
      expect(find.byType(application.DisabledBuild), findsOneWidget);
      expect(find.byType(NativeArchiveApp), findsNothing);
      await tester.pumpWidget(const SizedBox());
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  }, skip: dev && mode != 'native_archive');
}
