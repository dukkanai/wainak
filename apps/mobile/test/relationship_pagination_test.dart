import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/api/client.dart';
import 'package:wainak_mobile/src/api/http_repository.dart';
import 'package:wainak_mobile/src/api/relationship_page.dart';
import 'package:wainak_mobile/src/api/transport.dart';
import 'package:wainak_mobile/src/identity/client.dart';
import 'package:wainak_mobile/src/identity/matching_repository.dart';
import 'package:wainak_mobile/src/repository.dart';
import 'api_client_test.dart' as legacy;
import 'connected_widget_test.dart' show FixtureApi, meId;
import 'identity_matching_widget_test.dart' show openMatch, tapMatch;
import 'support/matching_fixture.dart';

String relationId(int n) => 'rel_${n.toRadixString(16).padLeft(32, '0')}';
String userId(int n) => 'usr_${n.toRadixString(16).padLeft(32, '0')}';
List<Map<String, dynamic>> manyRows(MatchingFixture f, int count) => [
  for (var i = 1; i <= count; i++)
    {
      ...f.relationship,
      'id': relationId(i),
      'initiator_id': userId(i),
      'recipient_id': f.actorId,
      'direction': 'incoming',
      'peer': {...f.candidate, 'id': userId(i), 'alias': 'طرف اختبار $i'},
    },
];

Future<(MatchingFixture, IdentityClient, IdentityMatchingRepository)> setup(
  int count,
) async {
  final f = MatchingFixture()..incoming = true;
  f.relationshipRows = manyRows(f, count);
  f.verified = true;
  final client = IdentityClient(
    baseUri: Uri.parse('http://127.0.0.1:8089'),
    transport: f,
  );
  await client.login(f.email, 'SyntheticOnlyPassword!12');
  return (f, client, IdentityMatchingRepository(client));
}

class LegacyPages extends FixtureApi {
  bool failPages = false;
  bool includeIncoming = true;
  int rowCount = 101;
  final pageCursors = <String?>[];
  List<Map<String, dynamic>> get rows => [
    for (var i = 1; i <= rowCount; i++)
      {
        ...relation,
        'id': relationId(i),
        'initiator_id': includeIncoming && i == 101 ? userId(i) : meId,
        'recipient_id': includeIncoming && i == 101 ? meId : userId(i),
        'peer': {...candidate, 'id': userId(i)},
      },
  ];
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    if (method == 'GET' && uri.path == '/v1/relationships') {
      if (failPages) throw StateError('Synthetic page failure');
      final cursor = uri.queryParameters['cursor'];
      pageCursors.add(cursor);
      final all = rows;
      final start = cursor == null
          ? 0
          : all.indexWhere((row) => row['id'] == cursor) + 1;
      final end = (start + 20).clamp(0, all.length);
      final page = all.sublist(start, end);
      return ok({
        'items': page,
        'next_cursor': end < all.length ? page.last['id'] : null,
      });
    }
    return super.send(method, uri, headers, body);
  }
}

class ReplacingSessionClient extends WainakApiClient {
  ReplacingSessionClient(legacy.RecordingTransport transport)
    : super(baseUri: Uri.parse('http://127.0.0.1:8089'), transport: transport);
  bool replaceAfterPage = false;
  @override
  Future<RelationshipPage> relationshipsPage({String? cursor}) async {
    final page = await super.relationshipsPage(cursor: cursor);
    if (replaceAfterPage) {
      replaceAfterPage = false;
      await legacy.login(this, transport as legacy.RecordingTransport);
    }
    return page;
  }
}

class HeldCards extends FixtureApi {
  Completer<ApiResponse>? pendingCards;
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) {
    if (uri.path.endsWith('/cards')) {
      pendingCards = Completer<ApiResponse>();
      return pendingCards!.future;
    }
    return super.send(method, uri, headers, body);
  }
}

Future<void> prepareLegacy(HttpJourneyRepository r) async {
  await r.register(
    age: 29,
    adult: true,
    muslim: true,
    terms: true,
    privacy: true,
  );
  await r.verifyDevelopmentEmail();
  await r.saveProfile(
    country: 'السعودية',
    goal: 'build_family',
    discoverable: true,
  );
}

void main() {
  test(
    '101 incoming rows traverse bounded pages and later safety actions',
    () async {
      final (f, c, r) = await setup(101);
      addTearDown(c.close);
      expect(
        utf8.encode(jsonEncode(f.relationshipRows)).length,
        greaterThan(65536),
      );
      await r.refreshRelationships();
      expect(r.relationships.length, 20);
      for (var page = 1; page < 6; page++) {
        expect(r.hasMoreRelationships, isTrue);
        final cursor = relationId(page * 20);
        expect(
          utf8.encode(jsonEncode(f.relationshipPage(cursor))).length,
          lessThanOrEqualTo(65536),
        );
        await r.loadNextRelationships();
      }
      expect(r.relationships.length, 101);
      expect(r.hasMoreRelationships, isFalse);
      final last = r.relationshipContext(r.relationships.last);
      await r.report(last, 'harassment');
      expect(f.matchingCalls.last['body']['target_id'], userId(101));
      expect(f.matchingCalls.last['body']['relationship_id'], relationId(101));
      await r.block(last);
      expect(f.matchingCalls.last['body']['target_id'], userId(101));
      expect(r.relationships, isEmpty);
      expect(r.hasMoreRelationships, isFalse);
      expect(
        f.matchingCalls.where((call) => call['method'] == 'GET').length,
        6,
      );
    },
  );

  test(
    'failed refresh and failed next page retain list and continuation',
    () async {
      final (f, c, r) = await setup(101);
      addTearDown(c.close);
      await r.refreshRelationships();
      await r.loadNextRelationships();
      final ids = r.relationships.map((row) => row.id).toList();
      f.failRelationships = true;
      await expectLater(
        r.refreshRelationships(),
        throwsA(isA<IdentityFailure>()),
      );
      await expectLater(
        r.loadNextRelationships(),
        throwsA(isA<IdentityFailure>()),
      );
      expect(r.relationships.map((row) => row.id), ids);
      expect(r.hasMoreRelationships, isTrue);
      f.failRelationships = false;
      await r.loadNextRelationships();
      expect(r.relationships.length, 60);
      expect(f.matchingCalls.last['query'], 'cursor=${relationId(40)}');
      await r.refreshRelationships();
      expect(r.relationships.length, 20);
    },
  );

  for (final action in ['block', 'logout', 'newer refresh']) {
    test('late page after $action cannot restore old rows', () async {
      final (f, c, r) = await setup(41);
      addTearDown(c.close);
      await r.refreshRelationships();
      final next = f.reply(200, f.relationshipPage(relationId(20)));
      final safety = r.relationshipContext(r.relationships.first);
      f.holdRelationships = true;
      final pending = r.loadNextRelationships();
      final rejected = expectLater(pending, throwsA(isA<IdentityFailure>()));
      await Future<void>.delayed(Duration.zero);
      if (action == 'block') {
        await r.block(safety);
      } else if (action == 'logout') {
        c.forgetLocalSession();
      } else {
        f.holdRelationships = false;
        await r.refreshRelationships();
      }
      f.pendingRelationships!.complete(next);
      await rejected;
      expect(r.relationships.length, action == 'newer refresh' ? 20 : 0);
      expect(r.hasMoreRelationships, action == 'newer refresh');
    });
  }

  test(
    'strict page schema rejects oversized unordered duplicate and bad cursors',
    () {
      final rows = [
        for (var i = 1; i <= 20; i++) {'id': relationId(i)},
      ];
      final valid = {'items': rows, 'next_cursor': relationId(20)};
      expect(RelationshipPage.fromJson(valid).items.length, 20);
      for (final invalid in <Map<String, dynamic>>[
        {'items': rows},
        {...valid, 'extra': true},
        {
          ...valid,
          'items': [
            ...rows,
            {'id': relationId(21)},
          ],
        },
        {
          ...valid,
          'items': [rows.first, rows.first],
        },
        {...valid, 'items': rows.reversed.toList()},
        {...valid, 'next_cursor': relationId(19)},
        {...valid, 'next_cursor': 'rel_INVALID'},
        {...valid, 'next_cursor': 20},
        {...valid, 'items': []},
        {...valid, 'items': 'invalid'},
        {
          'items': [
            {'id': 'invalid'},
          ],
          'next_cursor': null,
        },
        {
          'items': [null],
          'next_cursor': null,
        },
      ]) {
        expect(() => RelationshipPage.fromJson(invalid), throwsFormatException);
      }
      expect(
        () => RelationshipPage.fromJson(valid, after: relationId(1)),
        throwsFormatException,
      );
    },
  );

  test('invalid next page never changes cached rows or cursor', () async {
    final (f, c, r) = await setup(41);
    addTearDown(c.close);
    await r.refreshRelationships();
    f.relationshipPageOverride = f.relationshipPage(null); // replay first page
    await expectLater(
      r.loadNextRelationships(),
      throwsA(isA<IdentityFailure>()),
    );
    expect(r.relationships.length, 20);
    expect(r.hasMoreRelationships, isTrue);
    f.relationshipPageOverride = null;
    await r.loadNextRelationships();
    expect(r.relationships.length, 40);
  });

  test(
    'cursor builder does not allow arbitrary domain query strings',
    () async {
      final (f, c, _) = await setup(1);
      addTearDown(c.close);
      final before = f.matchingCalls.length;
      for (final cursor in [
        'bad',
        '${relationId(1)}&extra=true',
        relationId(1).toUpperCase(),
      ]) {
        await expectLater(
          c.relationshipsPage(cursor: cursor),
          throwsArgumentError,
        );
      }
      await expectLater(
        c.domain('GET', '/v1/relationships?cursor=${relationId(1)}'),
        throwsArgumentError,
      );
      await expectLater(
        c.domain('GET', '/v1/me', relationshipCursor: relationId(1)),
        throwsArgumentError,
      );
      expect(f.matchingCalls.length, before);
    },
  );

  test(
    'legacy repository finds incoming request after 100 outgoing rows',
    () async {
      final f = LegacyPages();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8089'),
        transport: f,
      );
      final r = HttpJourneyRepository(api);
      addTearDown(r.dispose);
      await r.register(
        age: 29,
        adult: true,
        muslim: true,
        terms: true,
        privacy: true,
      );
      await r.verifyDevelopmentEmail();
      await r.saveProfile(
        country: 'السعودية',
        goal: 'build_family',
        discoverable: true,
      );
      await r.refreshCandidate();
      expect(r.incomingRequest, isTrue);
      expect(r.relationship, RelationshipState.requested);
      expect(f.pageCursors.length, 6);
      await r.block();
      expect(f.blockedTarget, userId(101));
    },
  );

  test(
    'legacy complete-list cap rejects rather than returning truncated rows',
    () async {
      final t = legacy.RecordingTransport();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8089'),
        transport: t,
      );
      addTearDown(api.close);
      await legacy.login(api, t);
      for (var page = 0; page < 50; page++) {
        t.responses.add(
          ApiResponse(
            200,
            jsonEncode({
              'items': [
                for (var i = 1; i <= 20; i++) {'id': relationId(page * 20 + i)},
              ],
              'next_cursor': relationId((page + 1) * 20),
            }),
          ),
        );
      }
      await expectLater(
        api.relationships(),
        throwsA(
          isA<ApiFailure>().having(
            (e) => e.code,
            'bounded rejection',
            'relationship_page_limit',
          ),
        ),
      );
      expect(t.calls.length, 51);
    },
  );

  test(
    'legacy collector cannot combine pages across session replacement',
    () async {
      final transport = legacy.RecordingTransport();
      final api = ReplacingSessionClient(transport);
      addTearDown(api.close);
      await legacy.login(api, transport);
      transport.responses.add(
        ApiResponse(
          200,
          jsonEncode({
            'items': [
              for (var i = 1; i <= 20; i++) {'id': relationId(i)},
            ],
            'next_cursor': relationId(20),
          }),
        ),
      );
      api.replaceAfterPage = true;
      await expectLater(
        api.relationships(),
        throwsA(
          isA<ApiFailure>().having(
            (error) => error.code,
            'session boundary',
            'stale_response',
          ),
        ),
      );
      expect(transport.calls.where((call) => call.method == 'GET').length, 1);
      expect(api.hasSession, isTrue);
    },
  );

  test('legacy page failures and cap preserve previous candidate', () async {
    final fixture = LegacyPages()..includeIncoming = false;
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: fixture,
    );
    final r = HttpJourneyRepository(api);
    addTearDown(r.dispose);
    await prepareLegacy(r);
    await r.refreshCandidate();
    final name = r.candidateName;
    fixture.failPages = true;
    await expectLater(r.refreshCandidate(), throwsA(isA<JourneyFailure>()));
    expect(r.hasCandidate, isTrue);
    expect(r.candidateName, name);
    fixture.failPages = false;
    fixture.rowCount = 1001;
    await expectLater(r.refreshCandidate(), throwsA(isA<JourneyFailure>()));
    expect(r.hasCandidate, isTrue);
    expect(r.candidateName, name);
  });

  test(
    'legacy card response after block cannot restore candidate or cards',
    () async {
      final fixture = HeldCards();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8089'),
        transport: fixture,
      );
      final r = HttpJourneyRepository(api);
      addTearDown(r.dispose);
      await prepareLegacy(r);
      await r.refreshCandidate();
      await r.requestRelationship();
      fixture.state = 'active_cards';
      final pending = r.refreshRelationship();
      final rejection = expectLater(pending, throwsA(isA<JourneyFailure>()));
      await Future<void>.delayed(Duration.zero);
      expect(fixture.pendingCards, isNotNull);
      await r.block();
      fixture.pendingCards!.complete(
        fixture.ok({
          'answers_transport': 'not_implemented',
          'server_stores_dialogue_answers': false,
          'items': [
            {
              'prompt_ar': 'بطاقة قديمة',
              'options': ['خيار قديم'],
            },
          ],
        }),
      );
      await rejection;
      expect(r.relationship, RelationshipState.blocked);
      expect(r.hasCandidate, isFalse);
      expect(r.dialogueOptions, isEmpty);
    },
  );

  testWidgets(
    'accessible load more retries without losing rows and reaches later safety action',
    (t) async {
      final semantics = t.ensureSemantics();
      try {
        final f = MatchingFixture()..incoming = true;
        f.relationshipRows = manyRows(f, 101);
        final c = await openMatch(t, f, view: 'requests');
        addTearDown(c.close);
        expect(
          find.bySemanticsLabel('تحميل المزيد من الطلبات'),
          findsOneWidget,
        );
        final statusSemantics = t.widget<Semantics>(
          find
              .descendant(
                of: find.byKey(const Key('matching-page-status')),
                matching: find.byType(Semantics),
              )
              .first,
        );
        expect(statusSemantics.properties.liveRegion, isTrue);
        f.failRelationships = true;
        await tapMatch(t, 'matching-load-more');
        expect(find.text('طرف اختبار 1'), findsOneWidget);
        expect(
          find.bySemanticsLabel('إعادة محاولة تحميل المزيد من الطلبات'),
          findsOneWidget,
        );
        expect(find.byKey(const Key('matching-error')), findsOneWidget);
        f.failRelationships = false;
        for (var page = 0; page < 5; page++) {
          await tapMatch(t, 'matching-load-more');
        }
        expect(find.byKey(const Key('matching-load-more')), findsNothing);
        expect(
          find.textContaining('عدد الطلبات المحملة: 101.'),
          findsOneWidget,
        );
        await tapMatch(t, 'matching-block-${relationId(101)}');
        await tapMatch(t, 'matching-dialog-confirm');
        expect(f.matchingCalls.last['body']['target_id'], userId(101));
        expect(find.text('طرف اختبار 101'), findsNothing);
        expect(t.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
}
