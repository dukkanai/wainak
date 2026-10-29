import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/main.dart' as application;
import 'package:wainek_mobile/src/native_archive/app.dart';

void main() {
  test('native preview requires platform and explicit development gates', () {
    for (final platform in TargetPlatform.values) {
      for (final web in [false, true]) {
        for (final release in [false, true]) {
          for (final dev in [false, true]) {
            for (final iosPreview in [false, true]) {
              expect(
                application.nativeArchiveHostAllowed(
                  platform: platform,
                  isWeb: web,
                  release: release,
                  devOptIn: dev,
                  iosPreview: iosPreview,
                ),
                dev &&
                    !release &&
                    !web &&
                    (platform == TargetPlatform.android ||
                        (platform == TargetPlatform.iOS && iosPreview)),
              );
            }
          }
        }
      }
    }
  });

  const dev = bool.fromEnvironment('WAINEK_DEV_MODE');
  const mode = String.fromEnvironment('WAINEK_REPOSITORY');
  const iosPreview = bool.fromEnvironment('WAINEK_IOS_ARCHIVE_PREVIEW');
  testWidgets(
    'iOS preview does not simulate success when native plugin is missing',
    (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      try {
        application.main();
        await tester.pumpAndSettle();
        expect(find.byType(NativeArchiveApp), findsOneWidget);
        await tester.ensureVisible(find.byKey(const ValueKey('archive-ack')));
        await tester.tap(find.byKey(const ValueKey('archive-ack')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const ValueKey('archive-run')));
        await tester.tap(find.byKey(const ValueKey('archive-run')));
        await tester.pumpAndSettle();
        for (
          var turn = 0;
          turn < 30 &&
              find.textContaining('المحرك الأصلي غير متاح').evaluate().isEmpty;
          turn++
        ) {
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 20)),
          );
          await tester.pump();
        }
        expect(find.textContaining('المحرك الأصلي غير متاح'), findsOneWidget);
        expect(find.textContaining('أعاد المحرك نجاح'), findsNothing);
        await tester.pumpWidget(const SizedBox());
      } finally {
        debugDefaultTargetPlatformOverride = null;
      }
    },
    skip: !dev || !iosPreview || mode != 'native_archive',
  );
}
