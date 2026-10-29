import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/identity/app.dart';
import 'package:wainek_mobile/src/identity/client.dart';
import '../tool/check_identity_matching.dart' as checks;
import 'support/matching_fixture.dart';

Future<void> tapMatch(WidgetTester t, String key) async {
  final target = find.byKey(Key(key));
  await t.ensureVisible(target);
  await t.pumpAndSettle();
  await t.tap(target);
  await t.pumpAndSettle();
}

Future<IdentityClient> openMatch(
  WidgetTester t,
  MatchingFixture fixture, {
  String view = 'candidates',
}) async {
  fixture.verified = true;
  final client = IdentityClient(
    baseUri: Uri.parse('http://127.0.0.1:8089'),
    transport: fixture,
  );
  await client.login(fixture.email, 'SyntheticOnlyPassword!12');
  await t.pumpWidget(IdentityApp(client: client));
  await tapMatch(t, 'identity-section-$view');
  return client;
}

const relationId = 'rel_44444444444444444444444444444444';
void main() {
  test('typed matching domain and deferred response checks', checks.main);
  testWidgets(
    'candidate request is explicit outgoing and never recipient acceptance',
    (t) async {
      final handle = t.ensureSemantics();
      try {
        final f = MatchingFixture();
        await openMatch(t, f);
        final labeled = find.bySemanticsLabel(
          'طلب تعارف مع طرف اختبار، الترشيح 1',
        );
        expect(labeled, findsOneWidget);
        expect(t.getSize(labeled).height >= 48, isTrue);
        await tapMatch(t, 'matching-request-${f.targetId}');
        await tapMatch(t, 'matching-dialog-cancel');
        expect(f.requestCreates, 0);
        await tapMatch(t, 'matching-request-${f.targetId}');
        await tapMatch(t, 'matching-dialog-confirm');
        expect(f.requestCreates, 1);
        expect(find.text('طلب صادر'), findsOneWidget);
        expect(
          find.byKey(const Key('matching-cancel-$relationId')),
          findsOneWidget,
        );
        expect(
          find.byKey(const Key('matching-accept-$relationId')),
          findsNothing,
        );
        expect(
          f.matchingCalls.any(
            (v) =>
                (v['path'] as String).contains('/activate') ||
                (v['path'] as String).contains('/cards'),
          ),
          isFalse,
        );
      } finally {
        handle.dispose();
      }
    },
  );
  testWidgets(
    'recipient accepts only own incoming request and remains pending without cards',
    (t) async {
      final f = MatchingFixture()
        ..incoming = true
        ..hasRelation = true;
      await openMatch(t, f, view: 'requests');
      expect(find.text('طلب وارد'), findsOneWidget);
      expect(find.text('بانتظار قرارك'), findsOneWidget);
      await tapMatch(t, 'matching-accept-$relationId');
      await tapMatch(t, 'matching-dialog-confirm');
      expect(f.relationStatus, 'accepted_pending_activation');
      expect(
        find.text('اكتملت الموافقة المتبادلة؛ لم تُفتح محادثة'),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('matching-accept-$relationId')),
        findsNothing,
      );
      expect(find.byKey(const Key('matching-end-$relationId')), findsOneWidget);
      await tapMatch(t, 'matching-end-$relationId');
      await tapMatch(t, 'matching-dialog-cancel');
      expect(f.relationStatus, 'accepted_pending_activation');
    },
  );
  testWidgets(
    'stale redacted incoming peer keeps decline and safety independent',
    (t) async {
      final f = MatchingFixture()
        ..incoming = true
        ..hasRelation = true
        ..peerHidden = true;
      await openMatch(t, f, view: 'requests');
      expect(find.text('طرف اختبار'), findsNothing);
      expect(
        find.byKey(const Key('matching-accept-$relationId')),
        findsNothing,
      );
      await tapMatch(t, 'matching-decline-$relationId');
      await tapMatch(t, 'matching-dialog-confirm');
      expect(f.relationStatus, 'declined');
      expect(find.text('لم تكتمل الموافقة المتبادلة'), findsOneWidget);
      expect(
        find.byKey(const Key('matching-report-$relationId')),
        findsOneWidget,
      );
    },
  );
  testWidgets(
    'cancelled block/report do nothing; report remains after block and consent error',
    (t) async {
      final f = MatchingFixture();
      await openMatch(t, f);
      await tapMatch(t, 'matching-block-${f.targetId}');
      await tapMatch(t, 'matching-dialog-cancel');
      expect(f.blockCalls, 0);
      await tapMatch(t, 'matching-report-${f.targetId}');
      await tapMatch(t, 'matching-report-cancel');
      expect(f.reportCalls, 0);
      await tapMatch(t, 'matching-block-${f.targetId}');
      await tapMatch(t, 'matching-dialog-confirm');
      expect(f.blockCalls, 1);
      expect(find.text('طرف اختبار'), findsNothing);
      f.denyCandidates = true;
      await tapMatch(t, 'matching-refresh');
      expect(find.byKey(const Key('matching-error')), findsOneWidget);
      await tapMatch(t, 'matching-last-report');
      await tapMatch(t, 'matching-category-child_safety');
      await tapMatch(t, 'matching-report-submit');
      expect(f.reportCalls, 1);
      expect(f.blockCalls, 1);
      expect(find.textContaining('لا فريق مراجعة حي'), findsWidgets);
    },
  );
  testWidgets(
    'uncertain request retry survives navigation with original target and key',
    (t) async {
      final f = MatchingFixture()..failRequestOnce = true;
      await openMatch(t, f);
      await tapMatch(t, 'matching-request-${f.targetId}');
      await tapMatch(t, 'matching-dialog-confirm');
      expect(find.byKey(const Key('matching-error')), findsOneWidget);
      await tapMatch(t, 'identity-section-profile');
      await tapMatch(t, 'identity-section-candidates');
      await tapMatch(t, 'matching-retry-${f.targetId}');
      await tapMatch(t, 'matching-dialog-confirm');
      final calls = f.matchingCalls
          .where(
            (v) => v['path'] == '/v1/relationships' && v['method'] == 'POST',
          )
          .toList();
      expect(calls.length, 2);
      expect(calls[0]['key'] == calls[1]['key'], isTrue);
      expect(f.requestCreates, 1);
    },
  );
  testWidgets(
    'late relationship read after navigation and block cannot restore peer UI',
    (t) async {
      final f = MatchingFixture()
        ..incoming = true
        ..hasRelation = true;
      await openMatch(t, f, view: 'requests');
      final old = f.reply(200, {
        'items': [f.relationship],
        'next_cursor': null,
      });
      f.holdRelationships = true;
      await tapMatch(t, 'matching-refresh');
      expect(find.byKey(const Key('matching-busy')), findsOneWidget);
      await tapMatch(t, 'identity-section-candidates');
      await tapMatch(t, 'matching-block-${f.targetId}');
      await tapMatch(t, 'matching-dialog-confirm');
      f.pendingRelationships!.complete(old);
      await t.pumpAndSettle();
      f.holdRelationships = false;
      await tapMatch(t, 'identity-section-requests');
      expect(find.text('طرف اختبار'), findsNothing);
      expect(
        find.byKey(const Key('matching-accept-$relationId')),
        findsNothing,
      );
      expect(find.text('التعامل محظور'), findsOneWidget);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets('open request confirmation cannot target a replacement account', (
    t,
  ) async {
    final f = MatchingFixture();
    final client = await openMatch(t, f);
    await tapMatch(t, 'matching-request-${f.targetId}');
    f.actorId = 'usr_33333333333333333333333333333333';
    f.email = 'replacement@example.invalid';
    await client.login(f.email, 'SyntheticOnlyPassword!12');
    await tapMatch(t, 'matching-dialog-confirm');
    expect(f.requestCreates, 0);
    expect(client.authenticated, isTrue);
    expect(find.byKey(const Key('identity-load-profile')), findsOneWidget);
  });
  testWidgets(
    'RTL320 at200percent supports candidate and metadata report without overflow',
    (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1;
      t.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(t.view.resetPhysicalSize);
      addTearDown(t.view.resetDevicePixelRatio);
      addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);
      final f = MatchingFixture();
      await openMatch(t, f);
      expect(
        Directionality.of(t.element(find.byType(Scaffold))),
        TextDirection.rtl,
      );
      await tapMatch(t, 'matching-report-${f.targetId}');
      await tapMatch(t, 'matching-category-other_safety');
      await tapMatch(t, 'matching-report-submit');
      expect(f.reportCalls, 1);
      expect(t.takeException(), isNull);
    },
  );
}
