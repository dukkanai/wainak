import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainak_mobile/src/api/client.dart';
import 'package:wainak_mobile/src/api/transport.dart';

class DeferredTransport implements ApiTransport {
  final replies = <Completer<ApiResponse>>[];
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) {
    final c = Completer<ApiResponse>();
    replies.add(c);
    return c.future;
  }

  @override
  void close() {}
}

ApiResponse registration({bool validAccount = true}) => ApiResponse(
  201,
  jsonEncode({
    'mode': 'synthetic_development_only',
    'token_type': 'Bearer',
    'access_token': 'synthetic-session',
    'account': validAccount
        ? {'id': 'usr_0123456789abcdef0123456789abcdef'}
        : null,
  }),
);
Future<Map<String, dynamic>> register(WainakApiClient api) => api.register(
  email: 'fixture@example.invalid',
  birthDate: '1997-01-01',
  isMuslim: true,
  acceptedTerms: true,
  acknowledgedPrivacy: true,
);
void main() {
  test('register response after close cannot resurrect session', () async {
    final t = DeferredTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: t,
    );
    final pending = register(api);
    final expectation = expectLater(
      pending,
      throwsA(
        isA<ApiFailure>().having((e) => e.code, 'code', 'stale_response'),
      ),
    );
    api.close();
    t.replies[0].complete(registration());
    await expectation;
    expect(api.hasSession, isFalse);
    await expectLater(
      register(api),
      throwsA(isA<ApiFailure>().having((e) => e.code, 'code', 'client_closed')),
    );
  });
  test('old 401 cannot clear a newer session', () async {
    final t = DeferredTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: t,
    );
    final first = register(api);
    t.replies[0].complete(registration());
    await first;
    final old = api.me();
    final expectation = expectLater(
      old,
      throwsA(
        isA<ApiFailure>().having((e) => e.code, 'code', 'stale_response'),
      ),
    );
    final newer = register(api);
    t.replies[2].complete(registration());
    await newer;
    t.replies[1].complete(
      const ApiResponse(401, '{"error":{"code":"session_revoked"}}'),
    );
    await expectation;
    expect(api.hasSession, isTrue);
  });
  test('old deletion completion cannot clear newer session', () async {
    final t = DeferredTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: t,
    );
    final first = register(api);
    t.replies[0].complete(registration());
    await first;
    final old = api.deleteAccount();
    final expectation = expectLater(
      old,
      throwsA(
        isA<ApiFailure>().having((e) => e.code, 'code', 'stale_response'),
      ),
    );
    final newer = register(api);
    t.replies[2].complete(registration());
    await newer;
    t.replies[1].complete(const ApiResponse(200, '{"deleted":true}'));
    await expectation;
    expect(api.hasSession, isTrue);
  });
  test('invalid account shape does not install bearer session', () async {
    final t = DeferredTransport();
    final api = WainakApiClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: t,
    );
    final pending = register(api);
    final expectation = expectLater(
      pending,
      throwsA(
        isA<ApiFailure>().having((e) => e.code, 'code', 'invalid_response'),
      ),
    );
    t.replies[0].complete(registration(validAccount: false));
    await expectation;
    expect(api.hasSession, isFalse);
  });
}
