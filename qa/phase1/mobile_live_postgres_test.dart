import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/api/client.dart';
import 'package:wainek_mobile/src/api/http_repository.dart';
import 'package:wainek_mobile/src/api/transport_io.dart';
import 'package:wainek_mobile/src/connected_app.dart';
import 'package:wainek_mobile/src/repository.dart';

// Deliberate opt-in for this independently reviewed loopback-only test.
class LiveLoopbackBinding extends AutomatedTestWidgetsFlutterBinding {
  @override
  bool get overrideHttpClient => false;
}

Future<void> settleNetwork(WidgetTester tester) async {
  for (var attempt = 0; attempt < 400; attempt++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 25)),
    );
    await tester.pump(const Duration(milliseconds: 25));
    if (find.byKey(const Key('api-busy')).evaluate().isEmpty) {
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('api-error')), findsNothing);
      return;
    }
  }
  fail('UI request did not settle within the bounded loopback window');
}

Future<void> tapLive(WidgetTester tester, Finder target) async {
  expect(target, findsOneWidget);
  await tester.ensureVisible(target);
  await tester.pumpAndSettle();
  // Start IO in the real async zone; the UI, not the test, invokes the repository.
  await tester.runAsync(() async {
    await tester.tap(target);
    await Future<void>.delayed(const Duration(milliseconds: 10));
  });
  await tester.pump();
  await settleNetwork(tester);
}

Future<void> tapKey(WidgetTester tester, String key) =>
    tapLive(tester, find.byKey(Key(key)));
Future<void> tapText(WidgetTester tester, String label) =>
    tapLive(tester, find.text(label).last);

Future<void> checkpoint(String directory, String phase) async {
  final ready = File('$directory/$phase.ready');
  final resumed = File('$directory/$phase.resumed');
  expect(
    await FileSystemEntity.type(directory, followLinks: false),
    FileSystemEntityType.directory,
  );
  expect(
    await FileSystemEntity.type(ready.path, followLinks: false),
    FileSystemEntityType.notFound,
  );
  expect(
    await FileSystemEntity.type(resumed.path, followLinks: false),
    FileSystemEntityType.notFound,
  );
  await ready.writeAsString('ready', flush: true);
  final deadline = DateTime.now().add(const Duration(seconds: 90));
  while (!await resumed.exists()) {
    if (DateTime.now().isAfter(deadline)) {
      throw TimeoutException('Owned restart harness did not resume');
    }
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
  expect(
    await FileSystemEntity.type(resumed.path, followLinks: false),
    FileSystemEntityType.file,
  );
  expect(await resumed.readAsString(), 'resumed');
}

void main() {
  LiveLoopbackBinding();
  final url = Platform.environment['WAINEK_TEST_BASE_URL'];
  final controls = Platform.environment['WAINEK_TEST_CONTROL_DIR'];
  testWidgets(
    'QA live widgets -> native HTTP -> PostgreSQL: consent, two actors, restart, block/report/delete',
    (tester) async {
      final uri = Uri.parse(url!);
      expect(uri.scheme, 'http');
      expect(uri.host, '127.0.0.1');
      expect(uri.hasPort && uri.port > 0, isTrue);
      expect(uri.userInfo.isEmpty && !uri.hasQuery && !uri.hasFragment, isTrue);
      expect(uri.path.isEmpty || uri.path == '/', isTrue);
      expect(Directory(controls!).isAbsolute, isTrue);
      final peer = WainekApiClient(
        baseUri: uri,
        transport: NativeApiTransport(),
      );
      final repo = HttpJourneyRepository(
        WainekApiClient(baseUri: uri, transport: NativeApiTransport()),
      );
      String? peerId;
      try {
        await tester.runAsync(() async {
          final now = DateTime.now();
          final stamp = now.microsecondsSinceEpoch;
          final birthYear = now.year - 32;
          final account = await peer.register(
            email: 'qa_widget_peer_$stamp@example.invalid',
            birthDate: '$birthYear-01-01',
            isMuslim: true,
            acceptedTerms: true,
            acknowledgedPrivacy: true,
          );
          peerId = account['id'] as String;
          await peer.verifyEmailSimulation();
          await peer.saveProfile({
            'gender': 'male',
            'country': 'SA',
            'marital_status': 'single',
            'declared_wives': 0,
            'marriage_goal': 'build_family',
            'discoverable': true,
          });
          await peer.savePreferences({
            'min_age': 18,
            'max_age': 60,
            'countries': <String>[],
            'marital_statuses': ['single'],
          });
        });
        await tester.pumpWidget(ConnectedWainekApp(repository: repo));
        expect(
          Directionality.of(tester.element(find.byType(Scaffold))),
          TextDirection.rtl,
        );
        for (final key in [
          'api-adult',
          'api-muslim',
          'api-terms',
          'api-privacy',
          'api-register',
          'api-verify',
          'api-discoverable',
          'api-save-profile',
        ]) {
          await tapKey(tester, key);
        }
        expect(repo.registered && repo.emailVerified, isTrue);
        for (final answer in [
          'أرغب في إنجاب أطفال',
          'تخطيط مشترك',
          'وقت هادئ للحوار',
        ]) {
          await tapText(tester, answer);
          await tapKey(tester, 'api-assess');
        }
        expect(repo.hasCandidate, isTrue);
        final peerAlias = repo.candidateName;
        expect(find.text(peerAlias), findsOneWidget);
        await tapKey(tester, 'api-request');
        expect(repo.relationship, RelationshipState.requested);
        expect(find.byKey(const Key('api-accept-incoming')), findsNothing);
        expect(find.byKey(const Key('api-activate')), findsNothing);
        // Only the authenticated recipient approves, via its own separate session.
        await tester.runAsync(() async {
          final incoming = await peer.relationships();
          final relation = (incoming['items'] as List).single as Map;
          expect(relation['recipient_id'], peerId);
          await peer.respond(relation['id'] as String, accept: true);
        });
        await tapKey(tester, 'api-refresh-relation');
        expect(repo.relationship, RelationshipState.acceptedPendingActivation);
        await tapKey(tester, 'api-activate');
        expect(repo.relationship, RelationshipState.activeCards);
        expect(repo.dialogueOptions, isNotEmpty);
        expect(repo.dialogueTransportAvailable, isFalse);
        expect(find.byKey(const Key('send')), findsNothing);
        // Both actual WSGI process and disposable DB restart, same client sessions.
        await tester.runAsync(() => checkpoint(controls, 'active'));
        await tapKey(tester, 'api-refresh-cards');
        expect(repo.relationship, RelationshipState.activeCards);
        expect(repo.dialogueOptions, isNotEmpty);
        await tester.runAsync(() async {
          expect((await peer.me())['id'], peerId);
          expect((await repo.api.me())['dev_email_verified'], isTrue);
        });
        await tapKey(tester, 'api-report');
        await tapText(tester, 'تحرش أو إساءة');
        await tapKey(tester, 'api-submit-report');
        expect(repo.reports, 1);
        expect(repo.relationship, RelationshipState.activeCards);
        await tapKey(tester, 'api-block');
        await tapText(tester, 'تأكيد الحظر');
        expect(repo.relationship, RelationshipState.blocked);
        expect(find.textContaining(peerAlias), findsNothing);
        expect(repo.dialogueOptions, isEmpty);
        await tester.runAsync(() => checkpoint(controls, 'blocked'));
        await tapKey(tester, 'api-refresh-cards');
        expect(repo.relationship, RelationshipState.blocked);
        expect(repo.hasCandidate, isFalse);
        expect(repo.dialogueOptions, isEmpty);
        expect(find.textContaining(peerAlias), findsNothing);
        await tapKey(tester, 'api-report');
        await tapText(tester, 'سلامة طفل أو قاصر');
        await tapKey(tester, 'api-submit-report');
        expect(repo.reports, 2);
        await tapKey(tester, 'api-account');
        await tapKey(tester, 'api-delete');
        await tapText(tester, 'تأكيد الحذف من الخدمة');
        expect(repo.registered, isFalse);
        expect(repo.api.hasSession, isFalse);
        expect(find.byKey(const Key('api-register')), findsOneWidget);
        expect(find.byKey(const Key('api-account')), findsNothing);
        for (final key in [
          'api-adult',
          'api-muslim',
          'api-terms',
          'api-privacy',
        ]) {
          expect(
            tester.widget<CheckboxListTile>(find.byKey(Key(key))).value,
            isFalse,
          );
        }
        expect(tester.takeException(), isNull);
      } finally {
        peer.close();
        await tester.pumpWidget(const SizedBox());
        // App disposal owns repo/client disposal; no token/credential logs or files.
      }
    },
    skip: url == null || controls == null,
    timeout: const Timeout(Duration(minutes: 5)),
  );
}
