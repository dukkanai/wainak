import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/identity/client.dart';
import '../tool/check_identity_profile_save.dart' as checks;
import 'identity_widget_test.dart' as helpers;
import 'support/identity_fixture.dart';

void main() {
  test('profile-save coordinator contract checks', checks.main);
  testWidgets(
    'partial save names confirmed write and preserves draft for explicit retry',
    (t) async {
      final f = IdentityFixture();
      await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      await helpers.tapIdentity(t, 'identity-discoverable');
      f.failProfileSaveAt = 'preferences';
      await helpers.tapIdentity(t, 'identity-profile');
      expect(f.storedProfile?['discoverable'], isTrue);
      expect(f.storedPreferences, isNull);
      expect(find.textContaining('أكد الخادم كتابة الملف'), findsOneWidget);
      expect(find.byKey(const Key('identity-notice')), findsNothing);
      expect(find.byKey(const Key('identity-answer')), findsNothing);
      expect(
        t
            .widget<CheckboxListTile>(
              find.byKey(const Key('identity-discoverable')),
            )
            .value,
        isTrue,
      );
      expect(f.calls.where((x) => x == 'PUT /v1/me/profile').length, 1);
      expect(f.calls.where((x) => x == 'PUT /v1/me/preferences').length, 1);
      f.failProfileSaveAt = null;
      await helpers.tapIdentity(t, 'identity-profile');
      expect(find.byKey(const Key('identity-error')), findsNothing);
      expect(
        find.text('أكد الخادم حفظ الملف والتفضيلات الاصطناعية.'),
        findsOneWidget,
      );
      expect(find.byKey(const Key('identity-answer')), findsOneWidget);
      expect(f.calls.where((x) => x == 'PUT /v1/me/profile').length, 2);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'applied write with lost response is observed not claimed acknowledged',
    (t) async {
      final f = IdentityFixture();
      await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      f.failProfileSaveAt = 'profile';
      f.applyBeforeFailure = true;
      await helpers.tapIdentity(t, 'identity-profile');
      expect(f.storedProfile, isNotNull);
      expect(f.lastPreferences, isNull);
      expect(
        find.textContaining('دون تأكيد نتيجة طلب الكتابة'),
        findsOneWidget,
      );
      expect(find.textContaining('لم نرسل طلب حفظ التفضيلات'), findsOneWidget);
      expect(find.byKey(const Key('identity-notice')), findsNothing);
      expect(find.byKey(const Key('identity-answer')), findsNothing);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'assessment read failure does not deny confirmed profile and preferences',
    (t) async {
      final f = IdentityFixture();
      await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      f.failProfileSaveAt = 'assessment';
      await helpers.tapIdentity(t, 'identity-profile');
      expect(f.storedProfile, isNotNull);
      expect(f.storedPreferences, isNotNull);
      expect(find.textContaining('لكن لم نؤكد تحميل الأسئلة'), findsOneWidget);
      expect(find.byKey(const Key('identity-notice')), findsNothing);
      expect(find.byKey(const Key('identity-answer')), findsNothing);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'failed readback stays uncertain and does not reset chosen draft',
    (t) async {
      final f = IdentityFixture();
      await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      await helpers.tapIdentity(t, 'identity-discoverable');
      f.failProfileSaveAt = 'preferences';
      f.failReadback = true;
      await helpers.tapIdentity(t, 'identity-profile');
      expect(
        find.textContaining('لم نؤكد نتيجة كتابة التفضيلات'),
        findsOneWidget,
      );
      expect(
        t
            .widget<CheckboxListTile>(
              find.byKey(const Key('identity-discoverable')),
            )
            .value,
        isTrue,
      );
      expect(f.calls.where((x) => x == 'PUT /v1/me/preferences').length, 1);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'pending save blocks repeated clicks and disposal prevents continuation',
    (t) async {
      final f = IdentityFixture();
      final c = await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      f.holdProfile = true;
      await helpers.tapIdentity(t, 'identity-profile');
      await t.tap(
        find.byKey(const Key('identity-profile')),
        warnIfMissed: false,
      );
      await t.pump();
      expect(f.calls.where((x) => x == 'PUT /v1/me/profile').length, 1);
      await t.pumpWidget(const SizedBox());
      f.pendingProfile!.complete(f.reply(200, {'profile': f.lastProfile}));
      await t.pumpAndSettle();
      expect(c.stage, IdentityStage.signedOut);
      expect(f.lastPreferences, isNull);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'session change during partial readback never displays prior-account outcome',
    (t) async {
      final f = IdentityFixture();
      final c = await helpers.openIdentity(t, f);
      await helpers.signupIdentity(t);
      await helpers.verifyIdentity(t);
      f.failProfileSaveAt = 'preferences';
      f.holdReadback = true;
      await helpers.tapIdentity(t, 'identity-profile');
      c.forgetLocalSession();
      f.pendingReadback!.complete(
        f.reply(200, {
          'id': 'usr_11111111111111111111111111111111',
          'profile': f.lastProfile,
          'preferences': f.lastPreferences,
        }),
      );
      await t.pumpAndSettle();
      expect(find.byKey(const Key('identity-profile')), findsNothing);
      expect(find.textContaining('أكد الخادم كتابة الملف'), findsNothing);
      expect(find.byKey(const Key('identity-answer')), findsNothing);
      expect(t.takeException(), isNull);
    },
  );
}
