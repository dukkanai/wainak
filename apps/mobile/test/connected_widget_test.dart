import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/api/client.dart';
import 'package:wainak_mobile/src/api/http_repository.dart';
import 'package:wainak_mobile/src/api/transport.dart';
import 'package:wainak_mobile/src/connected_app.dart';

const meId = 'usr_11111111111111111111111111111111';
const peerId = 'usr_22222222222222222222222222222222';
const relationId = 'rel_11111111111111111111111111111111';

class FixtureApi implements ApiTransport {
  final calls = <String>[];
  bool verified = false,
      closed = false,
      holdRegistration = false,
      failCandidates = false,
      incoming = false,
      revokeSession = false;
  String? blockedTarget;
  final reportedTargets = <String>[];
  Map<String, dynamic>? nextCandidate;
  Completer<ApiResponse>? registration;
  int answered = 0, reports = 0;
  String state = 'requested';
  Map<String, dynamic> get account => {
    'id': meId,
    'alias': 'مشاركة اصطناعية من الخدمة',
    'age': 29,
    'dev_email_verified': verified,
  };
  Map<String, dynamic> get candidate => {
    'id': peerId,
    'alias': 'مرشح من الخدمة',
    'age': 32,
    'country': 'SA',
    'marital_status': 'single',
    'marriage_goal': 'build_family',
    'synthetic': true,
    'rating': {'state': 'insufficient_data'},
  };
  Map<String, dynamic> get relation => {
    'id': relationId,
    'initiator_id': incoming ? peerId : meId,
    'recipient_id': incoming ? meId : peerId,
    'status': state,
    'peer': state == 'blocked' ? null : candidate,
    'activation_mode': 'development_simulation_only',
    'permissions': {
      'can_send_cards': state == 'active_cards',
      'can_send_text': false,
      'can_send_media': false,
      'can_disclose_identity': false,
    },
  };
  Map<String, dynamic> get assessment => {
    'complete': answered == 3,
    'next_question': answered == 3
        ? null
        : {
            'id': ['family_plan', 'parenting', 'communication'][answered],
            'prompt_ar': 'سؤال من الخدمة ${answered + 1}',
            'options': [
              ['children'],
              ['shared_planning'],
              ['quiet_time'],
            ][answered],
          },
  };
  ApiResponse ok(Object value, [int code = 200]) =>
      ApiResponse(code, jsonEncode(value));
  ApiResponse get registrationResponse => ok({
    'account': account,
    'access_token': 'synthetic-fixture-only',
    'token_type': 'Bearer',
    'mode': 'synthetic_development_only',
  }, 201);
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    calls.add('$method ${uri.path}');
    if (uri.path == '/v1/dev/accounts') {
      if (holdRegistration) {
        registration = Completer<ApiResponse>();
        return registration!.future;
      }
      return registrationResponse;
    }
    expect(headers['Authorization'], 'Bearer synthetic-fixture-only');
    if (revokeSession)
      return ok({
        'error': {'code': 'unauthorized', 'message': 'expired'},
      }, 401);
    switch ('$method ${uri.path}') {
      case 'POST /v1/dev/verify-email':
        verified = true;
        return ok(account);
      case 'GET /v1/me':
        return ok(account);
      case 'PUT /v1/me/profile':
        expect(jsonDecode(body!)['discoverable'], isTrue);
        return ok(account);
      case 'PUT /v1/me/preferences':
        return ok(account);
      case 'GET /v1/me/assessment':
        return ok(assessment);
      case 'POST /v1/me/assessment/answers':
        answered++;
        return ok(assessment);
      case 'GET /v1/candidates':
        if (failCandidates) throw StateError('synthetic network failure');
        return ok({
          'items': [nextCandidate ?? candidate],
        });
      case 'GET /v1/relationships':
        return ok({
          'items': incoming ? [relation] : [],
          'next_cursor': null,
        });
      case 'POST /v1/relationships/$relationId/respond':
        expect(incoming, isTrue);
        state = jsonDecode(body!)['decision'] == 'accept'
            ? 'accepted_pending_activation'
            : 'declined';
        return ok(relation);
      case 'POST /v1/relationships':
        expect(headers['Idempotency-Key'], isNotNull);
        return ok(relation, 201);
      case 'GET /v1/relationships/$relationId':
        return ok(relation);
      case 'POST /v1/dev/relationships/$relationId/activate':
        expect(state, 'accepted_pending_activation');
        state = 'active_cards';
        return ok(relation);
      case 'GET /v1/relationships/$relationId/cards':
        return ok({
          'answers_transport': 'not_implemented',
          'server_stores_dialogue_answers': false,
          'items': [
            {
              'prompt_ar': 'بطاقة فعلية من الخدمة',
              'options': ['نستمع أولًا', 'نحدد موعدًا'],
            },
          ],
        });
      case 'POST /v1/blocks':
        blockedTarget = jsonDecode(body!)['target_id'] as String;
        state = 'blocked';
        return ok({'blocked': true});
      case 'POST /v1/reports':
        reportedTargets.add(jsonDecode(body!)['target_id'] as String);
        reports++;
        expect(jsonDecode(body).containsKey('evidence'), isFalse);
        return ok({
          'status': 'recorded_development_only',
          'evidence_uploaded': false,
        }, 201);
      case 'DELETE /v1/me':
        return ok({'deleted': true});
    }
    throw StateError('Unexpected fixture request');
  }

  @override
  void close() {
    closed = true;
  }
}

Future<void> tap(WidgetTester t, String key) async {
  final f = find.byKey(Key(key));
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

Future<void> choose(WidgetTester t, String text) async {
  final f = find.text(text).last;
  await t.ensureVisible(f);
  await t.pumpAndSettle();
  await t.tap(f);
  await t.pumpAndSettle();
}

HttpJourneyRepository repository(FixtureApi f) => HttpJourneyRepository(
  WainakApiClient(baseUri: Uri.parse('http://127.0.0.1:8089'), transport: f),
);
Future<void> onboard(WidgetTester t, FixtureApi f) async {
  await t.pumpWidget(ConnectedWainakApp(repository: repository(f)));
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
    await tap(t, key);
  }
  for (final option in [
    'أرغب في إنجاب أطفال',
    'تخطيط مشترك',
    'وقت هادئ للحوار',
  ]) {
    await choose(t, option);
    await tap(t, 'api-assess');
  }
}

void expectDeclarationsCleared(WidgetTester t) {
  for (final key in ['api-adult', 'api-muslim', 'api-terms', 'api-privacy']) {
    expect(t.widget<CheckboxListTile>(find.byKey(Key(key))).value, isFalse);
  }
}

void main() {
  testWidgets(
    'existing relationship stays pinned after back and preference refresh',
    (t) async {
      final f = FixtureApi();
      await onboard(t, f);
      await tap(t, 'api-request');
      f.nextCandidate = {
        ...f.candidate,
        'id': 'usr_33333333333333333333333333333333',
        'alias': 'ملف آخر',
      };
      await tap(t, 'api-back');
      await tap(t, 'api-back');
      await tap(t, 'api-save-profile');
      await tap(t, 'api-discover');
      expect(find.text('مرشح من الخدمة'), findsOneWidget);
      expect(find.text('ملف آخر'), findsNothing);
      await tap(t, 'api-block');
      await choose(t, 'تأكيد الحظر');
      await tap(t, 'api-report');
      await choose(t, 'تحرش أو إساءة');
      await tap(t, 'api-submit-report');
      expect(f.blockedTarget, peerId);
      expect(f.reportedTargets, [peerId]);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'revoked session clears all declarations before new registration',
    (t) async {
      final f = FixtureApi();
      await onboard(t, f);
      await tap(t, 'api-request');
      f.revokeSession = true;
      await tap(t, 'api-refresh-relation');
      expect(find.byKey(const Key('api-register')), findsOneWidget);
      expectDeclarationsCleared(t);
      expect(find.byKey(const Key('api-account')), findsNothing);
      expect(t.takeException(), isNull);
    },
  );

  testWidgets(
    'incoming acceptance uses recipient repository and real respond operation',
    (t) async {
      final f = FixtureApi()..incoming = true;
      await onboard(t, f);
      expect(find.byKey(const Key('api-cancel')), findsNothing);
      await tap(t, 'api-accept-incoming');
      expect(f.state, 'accepted_pending_activation');
      expect(f.calls, contains('POST /v1/relationships/$relationId/respond'));
      expect(find.byKey(const Key('api-activate')), findsNothing);
      expect(find.byKey(const Key('api-refresh-relation')), findsOneWidget);
      f.state = 'active_cards';
      await tap(t, 'api-refresh-relation');
      await tap(t, 'api-open-cards');
      expect(find.text('بطاقة فعلية من الخدمة'), findsOneWidget);
    },
  );

  testWidgets(
    'connected widgets drive actual repository/client contracts without fake peer acceptance',
    (t) async {
      final f = FixtureApi();
      await onboard(t, f);
      expect(find.text('مرشح من الخدمة'), findsOneWidget);
      await tap(t, 'api-request');
      expect(find.byKey(const Key('accept')), findsNothing);
      expect(
        find.textContaining('لا يمكنك قبول الطلب نيابة عنه'),
        findsOneWidget,
      );
      f.state = 'accepted_pending_activation';
      await tap(t, 'api-refresh-relation');
      await tap(t, 'api-activate');
      expect(find.text('بطاقة فعلية من الخدمة'), findsOneWidget);
      expect(find.byKey(const Key('send')), findsNothing);
      await tap(t, 'api-report');
      await choose(t, 'تحرش أو إساءة');
      await tap(t, 'api-submit-report');
      await tap(t, 'api-block');
      await choose(t, 'تأكيد الحظر');
      expect(find.textContaining('مرشح من الخدمة'), findsNothing);
      await tap(t, 'api-report');
      await choose(t, 'سلامة طفل أو قاصر');
      await tap(t, 'api-submit-report');
      expect(f.reports, 2);
      await tap(t, 'api-account');
      await tap(t, 'api-delete');
      await choose(t, 'تأكيد الحذف من الخدمة');
      expect(find.byKey(const Key('api-register')), findsOneWidget);
      expectDeclarationsCleared(t);
      expect(f.calls.where((x) => x == 'POST /v1/relationships').length, 1);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'busy registration suppresses repeat and disposed UI ignores late HTTP success',
    (t) async {
      final f = FixtureApi()..holdRegistration = true;
      await t.pumpWidget(ConnectedWainakApp(repository: repository(f)));
      for (final key in [
        'api-adult',
        'api-muslim',
        'api-terms',
        'api-privacy',
      ]) {
        await tap(t, key);
      }
      await tap(t, 'api-register');
      expect(find.byKey(const Key('api-busy')), findsOneWidget);
      await t.tap(find.byKey(const Key('api-register')), warnIfMissed: false);
      await t.pump();
      expect(f.calls.where((x) => x == 'POST /v1/dev/accounts').length, 1);
      await t.pumpWidget(const SizedBox());
      f.registration!.complete(f.registrationResponse);
      await t.pumpAndSettle();
      expect(f.closed, isTrue);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'HTTP candidate failure does not silently fall back to fake profile',
    (t) async {
      final f = FixtureApi()..failCandidates = true;
      await onboard(t, f);
      expect(find.byKey(const Key('api-error')), findsOneWidget);
      expect(find.text('عمر · ملف اصطناعي'), findsNothing);
      expect(find.textContaining('تعذر الاتصال'), findsOneWidget);
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'connected 200% layout at 320 keeps safety and server-driven questions usable',
    (t) async {
      t.view.physicalSize = const Size(320, 900);
      t.view.devicePixelRatio = 1;
      t.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(() {
        t.view.resetPhysicalSize();
        t.view.resetDevicePixelRatio();
        t.platformDispatcher.clearTextScaleFactorTestValue();
      });
      final f = FixtureApi();
      await onboard(t, f);
      await tap(t, 'api-request');
      f.state = 'accepted_pending_activation';
      await tap(t, 'api-refresh-relation');
      await tap(t, 'api-activate');
      await tap(t, 'api-report');
      await choose(t, 'سلامة طفل أو قاصر');
      await tap(t, 'api-submit-report');
      expect(t.takeException(), isNull);
    },
  );
}
