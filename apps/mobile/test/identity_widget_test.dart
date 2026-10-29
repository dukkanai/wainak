import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/identity/app.dart';
import 'package:wainek_mobile/src/identity/client.dart';
import '../tool/check_identity_client.dart' as checks;
import 'support/identity_fixture.dart';

Future<void> tapIdentity(WidgetTester t, String key) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

Future<void> textIdentity(WidgetTester t, String key, String value) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.enterText(f, value);
  await t.pumpAndSettle();
}

Future<IdentityClient> openIdentity(WidgetTester t, IdentityFixture f) async {
  final c = IdentityClient(
    baseUri: Uri.parse('http://127.0.0.1:8089'),
    transport: f,
  );
  await t.pumpWidget(IdentityApp(client: c));
  return c;
}

Future<void> signupIdentity(WidgetTester t) async {
  await tapIdentity(t, 'identity-toggle');
  await textIdentity(t, 'identity-email', 'member@example.invalid');
  await textIdentity(t, 'identity-password', 'SyntheticOnlyPassword!12');
  for (final key in [
    'identity-adult',
    'identity-muslim',
    'identity-terms',
    'identity-privacy',
  ]) {
    await tapIdentity(t, key);
  }
  await tapIdentity(t, 'identity-submit');
}

Future<void> verifyIdentity(WidgetTester t) async {
  await textIdentity(t, 'identity-code', '654321');
  await tapIdentity(t, 'identity-verify');
}

Future<void> chooseIdentity(WidgetTester t, String label) async {
  final f = find.text(label).last;
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

void main() {
  test(
    'standalone identity client checks remain part of the Flutter suite',
    checks.main,
  );
  testWidgets(
    'signup pending verify profile adaptive logout login and verified delete',
    (t) async {
      final f = IdentityFixture();
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      expect(c.stage, IdentityStage.pendingVerification);
      expect(find.byKey(const Key('identity-profile')), findsNothing);
      await textIdentity(t, 'identity-code', 'incorrect');
      await tapIdentity(t, 'identity-verify');
      expect(find.byKey(const Key('identity-error')), findsOneWidget);
      await tapIdentity(t, 'identity-resend');
      await verifyIdentity(t);
      expect(c.authenticated, isTrue);
      expect(
        t
            .widget<CheckboxListTile>(
              find.byKey(const Key('identity-discoverable')),
            )
            .value,
        isFalse,
      );
      await tapIdentity(t, 'identity-profile');
      for (final label in [
        'أرغب في إنجاب أطفال',
        'تخطيط مشترك',
        'وقت هادئ للحوار',
      ]) {
        await chooseIdentity(t, label);
        await tapIdentity(t, 'identity-answer');
      }
      expect(f.answers, 3);
      expect(find.textContaining('اكتملت أسئلة التأمل الذاتي'), findsOneWidget);
      await tapIdentity(t, 'identity-logout');
      expect(c.stage, IdentityStage.signedOut);
      for (final key in [
        'identity-adult',
        'identity-muslim',
        'identity-terms',
        'identity-privacy',
      ]) {
        expect(t.widget<CheckboxListTile>(find.byKey(Key(key))).value, isFalse);
      }
      await tapIdentity(t, 'identity-toggle');
      await textIdentity(t, 'identity-email', 'member@example.invalid');
      await textIdentity(t, 'identity-password', 'SyntheticOnlyPassword!12');
      await tapIdentity(t, 'identity-submit');
      expect(c.authenticated, isTrue);
      await tapIdentity(t, 'identity-delete');
      await chooseIdentity(t, 'الرجوع');
      expect(f.deletions, 0);
      await tapIdentity(t, 'identity-delete');
      await textIdentity(
        t,
        'identity-delete-password',
        'SyntheticOnlyPassword!12',
      );
      await tapIdentity(t, 'identity-delete-confirm');
      await tapIdentity(t, 'identity-delete-submit');
      expect(f.reauths, 1);
      expect(f.deletions, 1);
      expect(c.stage, IdentityStage.signedOut);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'owned pending deletion uses pending route and no authenticated fallback',
    (t) async {
      final f = IdentityFixture();
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      await tapIdentity(t, 'identity-delete');
      await textIdentity(t, 'identity-delete-password', 'bad');
      await tapIdentity(t, 'identity-delete-confirm');
      await tapIdentity(t, 'identity-delete-submit');
      expect(c.stage, IdentityStage.pendingVerification);
      expect(f.deletions, 0);
      await tapIdentity(t, 'identity-delete');
      await textIdentity(
        t,
        'identity-delete-password',
        'SyntheticOnlyPassword!12',
      );
      await tapIdentity(t, 'identity-delete-confirm');
      await tapIdentity(t, 'identity-delete-submit');
      expect(c.stage, IdentityStage.signedOut);
      expect(f.reauths, 0);
      expect(f.calls.where((x) => x == 'DELETE /identity/v1/me'), isEmpty);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'session expiry clears profile and previously checked declarations',
    (t) async {
      final f = IdentityFixture();
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      await verifyIdentity(t);
      f.expired = true;
      await tapIdentity(t, 'identity-refresh');
      expect(c.stage, IdentityStage.signedOut);
      expect(find.byKey(const Key('identity-profile')), findsNothing);
      expect(
        t
            .widget<CheckboxListTile>(find.byKey(const Key('identity-adult')))
            .value,
        isFalse,
      );
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'revoke cancellation is inert and explicit confirmation clears session',
    (t) async {
      final f = IdentityFixture();
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      await verifyIdentity(t);
      await tapIdentity(t, 'identity-revoke');
      await chooseIdentity(t, 'الرجوع');
      expect(c.authenticated, isTrue);
      await tapIdentity(t, 'identity-revoke');
      await chooseIdentity(t, 'تأكيد إبطال الجلسات');
      expect(c.stage, IdentityStage.signedOut);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'pending signup blocks keyboard edits and ignores late success after close',
    (t) async {
      final f = IdentityFixture()..holdSignup = true;
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      expect(find.byKey(const Key('identity-busy')), findsOneWidget);
      expect(
        t
            .widget<CheckboxListTile>(find.byKey(const Key('identity-adult')))
            .onChanged,
        isNull,
      );
      for (var i = 0; i < 12; i++) {
        await t.sendKeyEvent(LogicalKeyboardKey.tab);
        await t.sendKeyEvent(LogicalKeyboardKey.space);
        await t.pump();
      }
      expect(
        t
            .widget<CheckboxListTile>(find.byKey(const Key('identity-adult')))
            .value,
        isTrue,
      );
      await t.pumpWidget(const SizedBox());
      f.pendingSignup!.complete(f.authReply);
      await t.pumpAndSettle();
      expect(c.stage, IdentityStage.signedOut);
      expect(f.registrations, 1);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'login preserves stored marital profile and unedited preference lists',
    (t) async {
      final f = IdentityFixture()
        ..verified = true
        ..storedProfile = {
          'gender': 'male',
          'country': 'GB',
          'marital_status': 'married',
          'declared_wives': 1,
          'marriage_goal': 'build_family',
          'discoverable': true,
        }
        ..storedPreferences = {
          'min_age': 27,
          'max_age': 47,
          'countries': ['GB'],
          'marital_statuses': ['single'],
        };
      await openIdentity(t, f);
      await textIdentity(t, 'identity-email', 'member@example.invalid');
      await textIdentity(t, 'identity-password', 'SyntheticOnlyPassword!12');
      await tapIdentity(t, 'identity-submit');
      await tapIdentity(t, 'identity-profile');
      expect(f.lastProfile?['gender'], 'male');
      expect(f.lastProfile?['marital_status'], 'married');
      expect(f.lastProfile?['declared_wives'], 1);
      expect(f.lastProfile?['country'], 'GB');
      expect(f.lastPreferences?['countries'], ['GB']);
      expect(f.lastPreferences?['min_age'], 27);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'open deletion confirmation cannot target a later session generation',
    (t) async {
      final f = IdentityFixture();
      final c = await openIdentity(t, f);
      await signupIdentity(t);
      await tapIdentity(t, 'identity-delete');
      await textIdentity(
        t,
        'identity-delete-password',
        'SyntheticOnlyPassword!12',
      );
      await tapIdentity(t, 'identity-delete-confirm');
      await c.verify('654321');
      await tapIdentity(t, 'identity-delete-submit');
      expect(f.deletions, 0);
      expect(f.reauths, 0);
      expect(find.byKey(const Key('identity-error')), findsOneWidget);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'Arabic RTL at320 and200percent keeps verification and deletion usable',
    (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1;
      t.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(() {
        t.view.resetPhysicalSize();
        t.view.resetDevicePixelRatio();
        t.platformDispatcher.clearTextScaleFactorTestValue();
      });
      final f = IdentityFixture();
      await openIdentity(t, f);
      await signupIdentity(t);
      await verifyIdentity(t);
      await tapIdentity(t, 'identity-profile');
      await tapIdentity(t, 'identity-delete');
      await textIdentity(
        t,
        'identity-delete-password',
        'SyntheticOnlyPassword!12',
      );
      await tapIdentity(t, 'identity-delete-confirm');
      await tapIdentity(t, 'identity-delete-submit');
      expect(t.takeException(), isNull);
    },
  );
}
