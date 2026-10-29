import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/identity/app.dart';
import 'package:wainek_mobile/src/identity/client.dart';
import 'package:wainek_mobile/src/api/transport.dart';
import 'package:wainek_mobile/src/api/transport_io.dart';
import '../tool/identity_fixture_bridge.dart';

class MatchingLoopbackBinding extends AutomatedTestWidgetsFlutterBinding {
  @override
  bool get overrideHttpClient => false;
}

/// Fault seam only: forwards actual HTTP, then drops exactly one request reply.
/// No fake relationship/recipient response and no automatic retry are supplied.
class DropOneRequestReply implements ApiTransport {
  final NativeApiTransport inner = NativeApiTransport(
    timeout: const Duration(seconds: 35),
  );
  bool armed = false;
  final keys = <String?>[];
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    final request = method == 'POST' && uri.path == '/v1/relationships';
    if (request) keys.add(headers['Idempotency-Key']);
    final response = await inner.send(method, uri, headers, body);
    if (request && armed) {
      armed = false;
      throw StateError('Intentionally lost test reply after real HTTP');
    }
    return response;
  }

  @override
  void close() => inner.close();
}

String fixtureNonce() => base64UrlEncode(
  List<int>.generate(18, (_) => Random.secure().nextInt(256)),
).replaceAll('=', '');
Future<void> settleMatchLive(WidgetTester t, {bool expectError = false}) async {
  for (var i = 0; i < 3200; i++) {
    await t.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 25)),
    );
    await t.pump(const Duration(milliseconds: 25));
    if (find.byKey(const Key('matching-busy')).evaluate().isEmpty &&
        find.byKey(const Key('identity-busy')).evaluate().isEmpty) {
      await t.pumpAndSettle();
      if (find.byKey(const Key('matching-busy')).evaluate().isNotEmpty ||
          find.byKey(const Key('identity-busy')).evaluate().isNotEmpty)
        continue;
      expect(t.takeException(), isNull);
      expect(
        find.byKey(const Key('matching-error')),
        expectError ? findsOneWidget : findsNothing,
      );
      return;
    }
  }
  fail(
    'Live matching request exceeded bounded wait; private values suppressed',
  );
}

Future<void> matchLive(
  WidgetTester t,
  String key, {
  bool expectError = false,
}) async {
  final target = find.byKey(Key(key));
  expect(target, findsOneWidget);
  await t.ensureVisible(target);
  await t.pumpAndSettle();
  await t.runAsync(() async {
    await t.tap(target);
    await Future<void>.delayed(const Duration(milliseconds: 10));
  });
  await t.pump();
  await settleMatchLive(t, expectError: expectError);
}

Future<void> prepareParticipant(
  IdentityClient client,
  IdentityFixtureBridge bridge,
  String gender,
) async {
  final email =
      'match_${fixtureNonce().toLowerCase().replaceAll(RegExp('[^a-z0-9]'), '')}@example.invalid';
  final password = '${fixtureNonce()}!7aZ';
  await client.signup(
    email: email,
    password: password,
    age: 29,
    adult: true,
    muslim: true,
    terms: true,
    privacy: true,
  );
  final message = await bridge.verification(email);
  await client.verify(message.code);
  await client.domain(
    'PUT',
    '/v1/me/profile',
    body: {
      'gender': gender,
      'country': 'SA',
      'marital_status': 'single',
      'declared_wives': 0,
      'marriage_goal': 'build_family',
      'discoverable': true,
    },
  );
  await client.domain(
    'PUT',
    '/v1/me/preferences',
    body: {
      'min_age': 18,
      'max_age': 60,
      'countries': <String>[],
      'marital_statuses': ['single'],
    },
  );
  var assessment = await client.domain('GET', '/v1/me/assessment');
  var steps = 0;
  while (assessment['complete'] != true) {
    if (steps++ >= 4) throw StateError('Unbounded synthetic assessment');
    final question = assessment['next_question'] as Map;
    assessment = await client.domain(
      'POST',
      '/v1/me/assessment/answers',
      body: {
        'question_id': question['id'],
        'option_id': (question['options'] as List).first,
      },
    );
  }
}

void main() {
  MatchingLoopbackBinding();
  testWidgets(
    'two authenticated UI actors request retry recipient acceptance safety over actual allauth PostgreSQL',
    (t) async {
      IdentityFixtureBridge? bridge;
      IdentityClient? first, second;
      ValueNotifier<int>? actor;
      var normalCleanup = false;
      try {
        bridge = await t.runAsync(() => IdentityFixtureBridge.start());
        if (bridge == null) fail('Owned fixture readiness failed');
        final fixture = bridge;
        debugPrint(
          'TEST_FIXTURE_PROVENANCE ${jsonEncode(fixture.testProvenance)}',
        );
        final dropped = DropOneRequestReply();
        first = IdentityClient(baseUri: fixture.baseUri, transport: dropped);
        second = IdentityClient(
          baseUri: fixture.baseUri,
          transport: NativeApiTransport(timeout: const Duration(seconds: 35)),
        );
        final a = first, b = second;
        await t.runAsync(() => prepareParticipant(a, fixture, 'female'));
        await t.runAsync(() => prepareParticipant(b, fixture, 'male'));
        final target = b.identity!['domain_id'] as String;
        actor = ValueNotifier(0);
        final active = actor;
        await t.pumpWidget(
          Directionality(
            textDirection: TextDirection.rtl,
            child: ValueListenableBuilder<int>(
              valueListenable: active,
              builder: (_, index, child) => IndexedStack(
                index: index,
                children: [
                  IdentityApp(key: const Key('matching-actor-a'), client: a),
                  IdentityApp(key: const Key('matching-actor-b'), client: b),
                ],
              ),
            ),
          ),
        );
        await settleMatchLive(t);
        debugPrint('MATCHING_LIVE_STAGE actors_mounted');
        await matchLive(t, 'identity-section-candidates');
        dropped.armed = true;
        await matchLive(t, 'matching-request-$target');
        await matchLive(t, 'matching-dialog-confirm', expectError: true);
        expect(dropped.keys.length, 1);
        await matchLive(t, 'matching-retry-$target', expectError: true);
        await matchLive(t, 'matching-dialog-confirm');
        expect(dropped.keys.length, 2);
        expect(dropped.keys.first == dropped.keys.last, isTrue);
        debugPrint('MATCHING_LIVE_STAGE same_intent_retry_acknowledged');
        final own = await t.runAsync(
          () => a.domain('GET', '/v1/relationships'),
        );
        if (own == null) fail('Missing own relationship result');
        final rows = own['items'] as List;
        expect(rows.length, 1);
        final relation = rows.single as Map;
        final id = relation['id'] as String;
        expect(
          relation['direction'] == 'outgoing' &&
              relation['status'] == 'requested',
          isTrue,
        );
        expect(find.byKey(Key('matching-accept-$id')), findsNothing);
        var unauthorized = false;
        await t.runAsync(() async {
          try {
            await a.domain(
              'POST',
              '/v1/relationships/$id/respond',
              body: {'decision': 'accept'},
            );
          } on IdentityFailure {
            unauthorized = true;
          }
        });
        expect(unauthorized, isTrue);
        active.value = 1;
        await t.pumpAndSettle();
        await matchLive(t, 'identity-section-requests');
        expect(find.text('طلب وارد'), findsOneWidget);
        await matchLive(t, 'matching-accept-$id');
        await matchLive(t, 'matching-dialog-cancel');
        await matchLive(t, 'matching-accept-$id');
        await matchLive(t, 'matching-dialog-confirm');
        expect(
          find.text('اكتملت الموافقة المتبادلة؛ لم تُفتح محادثة'),
          findsOneWidget,
        );
        debugPrint('MATCHING_LIVE_STAGE recipient_acceptance_acknowledged');
        active.value = 0;
        await t.pumpAndSettle();
        await matchLive(t, 'matching-refresh');
        final accepted = await t.runAsync(
          () => a.domain('GET', '/v1/relationships/$id'),
        );
        if (accepted == null) fail('Missing accepted relationship');
        expect(
          accepted['status'] == 'accepted_pending_activation' &&
              (accepted['permissions'] as Map)['can_send_cards'] == false,
          isTrue,
        );
        expect(
          (accepted['available_actions'] as List).any(
            (v) => v == 'activate' || v == 'send_cards',
          ),
          isFalse,
        );
        await matchLive(t, 'matching-report-$id');
        await matchLive(t, 'matching-category-harassment');
        await matchLive(t, 'matching-report-submit');
        final afterReport = await t.runAsync(
          () => a.domain('GET', '/v1/relationships/$id'),
        );
        expect(afterReport?['status'] == 'accepted_pending_activation', isTrue);
        await matchLive(t, 'matching-block-$id');
        await matchLive(t, 'matching-dialog-confirm');
        active.value = 1;
        await t.pumpAndSettle();
        await matchLive(t, 'matching-refresh');
        expect(find.text('التعامل محظور'), findsOneWidget);
        expect(find.byKey(Key('matching-accept-$id')), findsNothing);
        await matchLive(t, 'matching-report-$id');
        await matchLive(t, 'matching-category-other_safety');
        await matchLive(t, 'matching-report-submit');
        final hidden = await t.runAsync(
          () => b.domain('GET', '/v1/relationships/$id'),
        );
        expect(
          hidden?['peer'] == null && hidden?['status'] == 'blocked',
          isTrue,
        );
        debugPrint('MATCHING_LIVE_STAGE blocked_peer_report_acknowledged');
        await t.pumpWidget(const SizedBox());
        await t.runAsync(() async {
          await fixture.shutdown();
          normalCleanup = true;
        });
        expect(normalCleanup, isTrue);
      } finally {
        try {
          await t.pumpWidget(const SizedBox());
        } finally {
          actor?.dispose();
          first?.close();
          second?.close();
          if (!normalCleanup && bridge != null)
            await t.runAsync(() => bridge!.abort());
        }
      }
    },
    skip: Platform.environment['WAINEK_RUN_MATCHING_WIDGET'] != '1',
    timeout: const Timeout(Duration(minutes: 7)),
  );
}
