import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/identity/app.dart';
import 'package:wainek_mobile/src/identity/client.dart';
import 'package:wainek_mobile/src/api/transport_io.dart';
import '../tool/identity_fixture_bridge.dart';

class IdentityLoopbackBinding extends AutomatedTestWidgetsFlutterBinding {
  @override
  bool get overrideHttpClient => false;
}

String syntheticNonce() => base64UrlEncode(
  List<int>.generate(18, (_) => Random.secure().nextInt(256)),
).replaceAll('=', '');
Future<void> settleIdentity(WidgetTester t, {bool expectError = false}) async {
  for (var i = 0; i < 1600; i++) {
    await t.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 25)),
    );
    await t.pump(const Duration(milliseconds: 25));
    if (find.byKey(const Key('identity-busy')).evaluate().isEmpty) {
      await t.pumpAndSettle();
      expect(t.takeException(), isNull);
      expect(
        find.byKey(const Key('identity-error')),
        expectError ? findsOneWidget : findsNothing,
      );
      return;
    }
  }
  fail(
    'Identity UI exceeded its bounded request window; private values suppressed',
  );
}

Future<void> tapIdentityLive(
  WidgetTester t,
  Finder target, {
  bool expectError = false,
}) async {
  expect(target, findsOneWidget);
  await t.ensureVisible(target);
  await t.pumpAndSettle();
  await t.runAsync(() async {
    await t.tap(target);
    await Future<void>.delayed(const Duration(milliseconds: 10));
  });
  await t.pump();
  await settleIdentity(t, expectError: expectError);
}

Future<void> keyLive(WidgetTester t, String key, {bool expectError = false}) =>
    tapIdentityLive(t, find.byKey(Key(key)), expectError: expectError);
Future<void> enterIdentity(WidgetTester t, String key, String value) async {
  final target = find.byKey(Key(key));
  await t.ensureVisible(target);
  await t.enterText(target, value);
  await t.pumpAndSettle();
}

Future<void> loginLive(WidgetTester t, String email, String password) async {
  if (find.byKey(const Key('identity-adult')).evaluate().isNotEmpty)
    await keyLive(t, 'identity-toggle');
  await enterIdentity(t, 'identity-email', email);
  await enterIdentity(t, 'identity-password', password);
  await keyLive(t, 'identity-submit');
}

Future<void> createLive(WidgetTester t, String email, String password) async {
  if (find.byKey(const Key('identity-adult')).evaluate().isEmpty)
    await keyLive(t, 'identity-toggle');
  await enterIdentity(t, 'identity-email', email);
  await enterIdentity(t, 'identity-password', password);
  for (final key in [
    'identity-adult',
    'identity-muslim',
    'identity-terms',
    'identity-privacy',
  ]) {
    await keyLive(t, key);
  }
  await keyLive(t, 'identity-submit');
}

Future<void> deleteLive(WidgetTester t, String password) async {
  await keyLive(t, 'identity-delete');
  await enterIdentity(t, 'identity-delete-password', password);
  await keyLive(t, 'identity-delete-confirm');
  await keyLive(t, 'identity-delete-submit');
}

void main() {
  IdentityLoopbackBinding();
  final enabled = Platform.environment['WAINEK_RUN_IDENTITY_WIDGET'] == '1';
  testWidgets(
    'real identity widgets -> Django/allauth -> fresh PostgreSQL with private RAM mailbox',
    (t) async {
      IdentityFixtureBridge? bridge;
      IdentityClient? client, other;
      var normalCleanup = false;
      try {
        bridge = await t.runAsync(() => IdentityFixtureBridge.start());
        if (bridge == null)
          fail('Owned identity fixture failed before readiness');
        final active = bridge;
        debugPrint(
          'TEST_FIXTURE_PROVENANCE ' + jsonEncode(active.testProvenance),
        );
        client = IdentityClient(
          baseUri: active.baseUri,
          transport: NativeApiTransport(timeout: const Duration(seconds: 35)),
        );
        other = IdentityClient(
          baseUri: active.baseUri,
          transport: NativeApiTransport(timeout: const Duration(seconds: 35)),
        );
        final account = client, peer = other;
        final email =
            'widget_${syntheticNonce().toLowerCase().replaceAll(RegExp('[^a-z0-9]'), '')}@example.invalid';
        final password = '${syntheticNonce()}!7aZ';
        await t.pumpWidget(IdentityApp(client: account));
        expect(
          Directionality.of(t.element(find.byType(Scaffold))),
          TextDirection.rtl,
        );
        await createLive(t, email, password);
        expect(account.stage, IdentityStage.pendingVerification);
        final mail = await t.runAsync(() => active.verification(email));
        if (mail == null)
          fail(
            'Private fake mailbox did not return a committed verification event',
          );
        await enterIdentity(t, 'identity-code', mail.code);
        await keyLive(t, 'identity-verify');
        expect(account.authenticated, isTrue);
        await keyLive(t, 'identity-profile');
        for (final answer in [
          'أرغب في إنجاب أطفال',
          'تخطيط مشترك',
          'وقت هادئ للحوار',
        ]) {
          await tapIdentityLive(t, find.text(answer).last);
          await keyLive(t, 'identity-answer');
        }
        expect(
          find.textContaining('اكتملت أسئلة التأمل الذاتي'),
          findsOneWidget,
        );
        await t.runAsync(() => peer.login(email, password));
        expect(peer.authenticated, isTrue);
        await keyLive(t, 'identity-revoke');
        await tapIdentityLive(t, find.text('تأكيد إبطال الجلسات'));
        expect(account.stage, IdentityStage.signedOut);
        var peerRejected = false;
        await t.runAsync(() async {
          try {
            await peer.domain('GET', '/v1/me');
          } on IdentityFailure {
            peerRejected = true;
          }
        });
        expect(peerRejected && peer.stage == IdentityStage.signedOut, isTrue);
        await loginLive(t, email, password);
        expect(account.authenticated, isTrue);
        await t.runAsync(() => peer.login(email, password));
        await t.runAsync(() => peer.logout(everywhere: true));
        await keyLive(t, 'identity-refresh', expectError: true);
        expect(account.stage, IdentityStage.signedOut);
        await loginLive(t, email, password);
        await keyLive(t, 'identity-logout');
        expect(account.stage, IdentityStage.signedOut);
        await loginLive(t, email, password);
        await deleteLive(t, password);
        expect(account.stage, IdentityStage.signedOut);
        final pendingEmail =
            'pending_${syntheticNonce().toLowerCase().replaceAll(RegExp('[^a-z0-9]'), '')}@example.invalid';
        final pendingPassword = '${syntheticNonce()}!7aZ';
        await createLive(t, pendingEmail, pendingPassword);
        expect(account.stage, IdentityStage.pendingVerification);
        await deleteLive(t, pendingPassword);
        expect(account.stage, IdentityStage.signedOut);
        await t.pumpWidget(const SizedBox());
        peer.close();
        await t.runAsync(() async {
          await active.shutdown();
          normalCleanup = true;
        });
        expect(normalCleanup, isTrue);
      } finally {
        await t.pumpWidget(const SizedBox());
        other?.close();
        if (!normalCleanup && bridge != null)
          await t.runAsync(() => bridge!.abort());
      }
    },
    skip: !enabled,
    timeout: const Timeout(Duration(minutes: 6)),
  );
}
