import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/main.dart' as entry;
import 'package:wainek_mobile/src/app.dart';
import 'package:wainek_mobile/src/repository.dart';
import 'package:wainek_mobile/src/native_archive/app.dart';

void main() {
  const optedIn = bool.fromEnvironment('WAINEK_DEV_MODE');
  const mode = String.fromEnvironment(
    'WAINEK_REPOSITORY',
    defaultValue: 'fake',
  );

  testWidgets(
    'internal UI entry stays local and default entry stays disabled',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        entry.main();
        await tester.pumpAndSettle();
        if (optedIn && mode == 'fake') {
          final app = tester.widget<WainekApp>(find.byType(WainekApp));
          expect(app.repository, isA<DevJourneyRepository>());
          expect(find.byType(entry.DisabledBuild), findsNothing);
          expect(find.text('بداية واضحة، على مهل'), findsWidgets);
          expect(find.byType(TextField), findsNothing);
          expect(find.byType(NativeArchiveApp), findsNothing);
          expect(
            Directionality.of(tester.element(find.byType(Journey))),
            TextDirection.rtl,
          );
        } else {
          expect(find.byType(entry.DisabledBuild), findsOneWidget);
          expect(find.byType(WainekApp), findsNothing);
        }
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
}
