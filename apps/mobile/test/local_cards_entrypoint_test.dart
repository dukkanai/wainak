import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:wainek_mobile/main.dart' as entry;
import 'package:wainek_mobile/src/local_cards/app.dart';

void main() {
  const enabled =
      bool.fromEnvironment('WAINEK_DEV_MODE') &&
      String.fromEnvironment('WAINEK_REPOSITORY') == 'local_cards';
  testWidgets(
    'explicit development entry opens isolated local cards without API configuration',
    (t) async {
      entry.main();
      await t.pumpAndSettle();
      expect(find.byType(LocalCardsApp), findsOneWidget);
      expect(find.byKey(const Key('local-cards-boundary')), findsOneWidget);
      expect(find.byKey(const Key('local-cards-ack')), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      expect(t.takeException(), isNull);
    },
    skip: !enabled,
  );
}
