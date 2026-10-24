import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/api/transport.dart';
import 'file:///home/chatbot/wainak-dev/mobile-auth-phase2/apps/mobile/lib/src/identity/client.dart';

const pending = 'qa-pending-fixture-not-a-real-token';
const verified = 'qa-verified-fixture-not-a-real-token';
ApiResponse reply(int status, Map<String, dynamic> body) => ApiResponse(status, jsonEncode(body));
Map<String, dynamic> flow() => {
  'meta': {'is_authenticated': false, 'session_token': pending},
  'data': {'flows': [{'id': 'verify_email', 'is_pending': true}]}
};

class DeferredFixture implements ApiTransport {
  DeferredFixture(this.kind);
  final String kind;
  final held = Completer<ApiResponse>();
  bool pendingHeaderUsedAfterVerify = false;
  @override
  Future<ApiResponse> send(String method, Uri uri, Map<String, String> headers, String? body) async {
    if (uri.path.endsWith('/auth/signup')) return reply(401, flow());
    if ((kind == 'refresh' && uri.path.endsWith('/auth/session')) ||
        (kind != 'refresh' && uri.path.endsWith('/auth/email/verify/resend'))) {
      return held.future;
    }
    if (uri.path.endsWith('/auth/email/verify')) {
      return reply(200, {'meta': {'is_authenticated': true, 'session_token': verified}});
    }
    if (uri.path == '/identity/v1/me') {
      return reply(200, {'email_verified': true, 'email_is_identity_verification': false,
        'mode': 'synthetic_identity_sandbox', 'id': '11111111-1111-4111-8111-111111111111',
        'domain_id': 'usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'email': 'qa@example.invalid'});
    }
    if (uri.path == '/v1/me') {
      pendingHeaderUsedAfterVerify = headers['X-Session-Token'] == pending;
      return headers['X-Session-Token'] == verified
          ? reply(200, {'id': 'usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'})
          : reply(401, {'error': {'code': 'unauthenticated'}});
    }
    return reply(404, {'error': {'code': 'not_found'}});
  }
  @override
  void close() {}
}

Future<bool> checkCase(String kind) async {
  final fixture = DeferredFixture(kind);
  final client = IdentityClient(baseUri: Uri.parse('http://127.0.0.1:8089'), transport: fixture);
  try {
    await client.signup(email: 'qa@example.invalid', password: 'SyntheticFixtureOnly!123',
      age: 29, adult: true, muslim: true, terms: true, privacy: true);
    final late = kind == 'refresh' ? client.refreshSession() : client.resend();
    await client.verify('123456');
    if (!client.authenticated) throw StateError('Fixture did not establish positive authentication control');
    fixture.held.complete(kind == 'refresh' ? reply(401, flow()) :
      kind == 'expired' ? reply(410, {'error': {'code': 'pending_flow_expired'}}) :
      reply(200, {'meta': {'session_token': pending}}));
    var rejectedStale = false;
    try { await late; } on IdentityFailure { rejectedStale = true; }
    var domainSucceeded = false;
    try { await client.domain('GET', '/v1/me'); domainSucceeded = true; } on IdentityFailure { /* no secret operands */ }
    final safe = rejectedStale && client.authenticated && domainSucceeded && !fixture.pendingHeaderUsedAfterVerify;
    stdout.writeln('${safe ? "PASS" : "FAIL"}: late $kind cannot replace/revoke a newer verified flow');
    return safe;
  } finally { client.close(); }
}

Future<void> main() async {
  var failed = 0;
  for (final kind in ['resend', 'refresh', 'expired']) {
    if (!await checkCase(kind)) failed++;
  }
  stdout.writeln('Deferred auth-transition cases:3; failed:$failed. No network or real credentials.');
  exitCode = failed == 0 ? 0 : 1;
}
