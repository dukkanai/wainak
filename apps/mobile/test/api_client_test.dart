import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/api/client.dart';
import 'package:wainak_mobile/src/api/transport.dart';

class RecordingTransport implements ApiTransport {
  final calls =
      <({String method, Uri uri, Map<String, String> headers, String? body})>[];
  final responses = <ApiResponse>[];
  bool closed = false;
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    calls.add((method: method, uri: uri, headers: headers, body: body));
    return responses.removeAt(0);
  }

  @override
  void close() {
    closed = true;
  }
}

const userId = 'usr_0123456789abcdef0123456789abcdef';
const relId = 'rel_0123456789abcdef0123456789abcdef';
Map<String, dynamic> candidate() => {
  'id': userId,
  'alias': 'مشارك اصطناعي',
  'age': 29,
  'country': 'SA',
  'marital_status': 'single',
  'marriage_goal': 'build_family',
  'rating': {'state': 'insufficient_data'},
  'synthetic': true,
};
Map<String, dynamic> relation({
  String status = 'requested',
  bool cards = false,
  bool media = false,
  bool nullPeer = false,
}) => {
  'id': relId,
  'status': status,
  'peer': nullPeer ? null : candidate(),
  'activation_mode': 'development_simulation_only',
  'permissions': {
    'can_send_cards': cards,
    'can_send_text': false,
    'can_send_media': media,
    'can_disclose_identity': false,
  },
};
Future<void> login(WainakApiClient api, RecordingTransport transport) async {
  transport.responses.add(
    ApiResponse(
      201,
      jsonEncode({
        'account': {'id': userId},
        'access_token': 'synthetic-test-only',
        'token_type': 'Bearer',
        'mode': 'synthetic_development_only',
      }),
    ),
  );
  await api.register(
    email: 'fixture@example.invalid',
    birthDate: '1997-01-01',
    isMuslim: true,
    acceptedTerms: true,
    acknowledgedPrivacy: true,
  );
}

void main() {
  test('transport accepts only HTTPS origins or loopback HTTP', () {
    for (final bad in [
      'http://example.com',
      'https://user:pass@example.com',
      'https://example.com/path',
      'https://example.com?q=x',
    ]) {
      expect(
        () => WainakApiClient(
          baseUri: Uri.parse(bad),
          transport: RecordingTransport(),
        ),
        throwsArgumentError,
      );
    }
    expect(
      WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8766'),
        transport: RecordingTransport(),
      ).hasSession,
      isFalse,
    );
  });
  test('required declarations cannot be silently asserted', () async {
    final t = RecordingTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8766'),
      transport: t,
    );
    await expectLater(
      api.register(
        email: 'fixture@example.invalid',
        birthDate: '1997-01-01',
        isMuslim: false,
        acceptedTerms: true,
        acknowledgedPrivacy: true,
      ),
      throwsA(isA<ApiFailure>()),
    );
    expect(t.calls, isEmpty);
  });
  test(
    'registration versions and token are kept separate from account DTO',
    () async {
      final t = RecordingTransport();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8766'),
        transport: t,
      );
      await login(api, t);
      expect(api.hasSession, isTrue);
      expect(t.calls.single.headers.containsKey('Authorization'), isFalse);
      expect(
        jsonDecode(t.calls.single.body!)['terms_version'],
        'dev-2026-10-24',
      );
      t.responses.add(const ApiResponse(200, '{}'));
      await api.me();
      expect(
        t.calls.last.headers['Authorization'],
        'Bearer synthetic-test-only',
      );
      api.close();
      expect(api.hasSession, isFalse);
      expect(t.closed, isTrue);
    },
  );
  test(
    'request carries idempotency key; 409 is not retried or raw-message exposed',
    () async {
      final t = RecordingTransport();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8766'),
        transport: t,
      );
      await login(api, t);
      t.responses.add(
        const ApiResponse(
          409,
          '{"error":{"code":"stale_state","message":"secret internal data"}}',
        ),
      );
      await expectLater(
        api.requestRelationship(userId, 'request-0001'),
        throwsA(
          isA<ApiFailure>()
              .having((e) => e.code, 'stable code', 'stale_state')
              .having(
                (e) => e.message.contains('secret'),
                'no raw message',
                isFalse,
              ),
        ),
      );
      expect(t.calls.length, 2);
      expect(t.calls.last.headers['Idempotency-Key'], 'request-0001');
      expect(jsonDecode(t.calls.last.body!), {'candidate_id': userId});
    },
  );
  test('401 invalidates session without implicit reauthentication', () async {
    final t = RecordingTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8766'),
      transport: t,
    );
    await login(api, t);
    t.responses.add(
      const ApiResponse(401, '{"error":{"code":"session_revoked"}}'),
    );
    await expectLater(api.me(), throwsA(isA<ApiFailure>()));
    expect(api.hasSession, isFalse);
    await expectLater(api.me(), throwsA(isA<ApiFailure>()));
    expect(t.calls.length, 2);
  });
  test(
    'unsupported media or blocked card rights fails closed; null peer allowed',
    () {
      expect(
        () =>
            RelationshipDto.fromJson(relation(status: 'blocked', cards: true)),
        throwsFormatException,
      );
      expect(
        () => RelationshipDto.fromJson(
          relation(status: 'active_cards', cards: true, media: true),
        ),
        throwsFormatException,
      );
      expect(
        RelationshipDto.fromJson(
          relation(status: 'blocked', nullPeer: true),
        ).peer,
        isNull,
      );
      expect(
        RelationshipDto.fromJson(
          relation(status: 'exclusive_cards', cards: true),
        ).canSendCards,
        isTrue,
      );
      expect(
        RelationshipDto.fromJson(relation(status: 'frozen')).canSendCards,
        isFalse,
      );
    },
  );
  test(
    'real identity and numeric ratings are not accepted as candidate models',
    () {
      expect(CandidateDto.fromJson(candidate()).alias, 'مشارك اصطناعي');
      expect(
        () => CandidateDto.fromJson({...candidate(), 'synthetic': false}),
        throwsFormatException,
      );
      expect(
        () => CandidateDto.fromJson({
          ...candidate(),
          'rating': {'score': 100},
        }),
        throwsFormatException,
      );
    },
  );
  test(
    'report has metadata only and account deletion clears session',
    () async {
      final t = RecordingTransport();
      final api = WainakApiClient(
        baseUri: Uri.parse('http://127.0.0.1:8766'),
        transport: t,
      );
      await login(api, t);
      t.responses.add(
        const ApiResponse(
          201,
          '{"status":"recorded_development_only","evidence_uploaded":false}',
        ),
      );
      await api.report(userId, 'child_safety', relationshipId: relId);
      expect(jsonDecode(t.calls.last.body!), {
        'target_id': userId,
        'category': 'child_safety',
        'relationship_id': relId,
      });
      t.responses.add(const ApiResponse(200, '{"deleted":true}'));
      await api.deleteAccount();
      expect(api.hasSession, isFalse);
      expect(t.calls.last.method, 'DELETE');
    },
  );
}
