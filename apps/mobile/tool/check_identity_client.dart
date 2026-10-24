import 'dart:async';
import 'dart:convert';
import 'dart:io';
import '../lib/src/api/transport.dart';
import '../lib/src/identity/client.dart';
import '../test/support/identity_fixture.dart';

void check(bool condition, String label) {
  if (!condition) throw StateError(label);
}

Future<void> rejected(Future<void> Function() action, String label) async {
  try {
    await action();
  } on IdentityFailure {
    return;
  }
  throw StateError(label);
}

IdentityClient client(IdentityFixture fixture) => IdentityClient(
  baseUri: Uri.parse('http://127.0.0.1:8089'),
  transport: fixture,
);
Future<void> signup(IdentityClient c) => c.signup(
  email: 'member@example.invalid',
  password: 'SyntheticOnlyPassword!12',
  age: 29,
  adult: true,
  muslim: true,
  terms: true,
  privacy: true,
);

class ScriptTransport implements ApiTransport {
  ScriptTransport(this.handler);
  final Future<ApiResponse> Function(String, Uri, Map<String, String>, String?)
  handler;
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) => handler(method, uri, headers, body);
  @override
  void close() {}
}

Future<void> main() async {
  var passed = 0;
  Future<void> test(String name, Future<void> Function() work) async {
    try {
      await work();
      passed++;
      stdout.writeln('PASS $name');
    } catch (_) {
      throw StateError('FAIL $name (secret-bearing details suppressed)');
    }
  }

  await test('explicit fixture origin and real email rejection', () async {
    final f = IdentityFixture();
    final c = client(f);
    await rejected(
      () => c.login('person@example.com', 'SyntheticOnlyPassword!12'),
      'real address accepted',
    );
    check(f.calls.isEmpty, 'rejected before network');
    var bad = false;
    try {
      IdentityClient(baseUri: Uri.parse('https://example.com'), transport: f);
    } on ArgumentError {
      bad = true;
    }
    check(bad, 'nonfixture origin accepted');
    c.close();
  });
  await test('minor and missing declarations never reach network', () async {
    final f = IdentityFixture();
    final c = client(f);
    await rejected(
      () => c.signup(
        email: 'member@example.invalid',
        password: 'SyntheticOnlyPassword!12',
        age: 17,
        adult: true,
        muslim: true,
        terms: true,
        privacy: true,
      ),
      'minor',
    );
    await rejected(
      () => c.signup(
        email: 'member@example.invalid',
        password: 'SyntheticOnlyPassword!12',
        age: 29,
        adult: true,
        muslim: true,
        terms: false,
        privacy: true,
      ),
      'terms',
    );
    check(f.calls.isEmpty, 'no signup');
    c.close();
  });
  await test('401 signup pending cannot access domain', () async {
    final f = IdentityFixture();
    final c = client(f);
    await signup(c);
    check(
      c.stage == IdentityStage.pendingVerification && c.identity == null,
      'pending is not identity',
    );
    await rejected(() async {
      await c.domain('GET', '/v1/me');
    }, 'pending domain');
    c.close();
  });
  await test('verify rotates header and proves email only', () async {
    final f = IdentityFixture();
    final c = client(f);
    await signup(c);
    await c.verify('654321');
    check(
      c.authenticated && c.identity?['domain_id'] != null,
      'verified projection',
    );
    check(
      f.headerNames.every(
        (h) =>
            !h.contains('Authorization') &&
            !h.contains('Cookie') &&
            !h.contains('Origin'),
      ),
      'native authority headers',
    );
    await c.domain('GET', '/v1/me');
    c.close();
  });
  await test('invalid code and bounded resend preserve pending', () async {
    final f = IdentityFixture();
    final c = client(f);
    await signup(c);
    await rejected(
      () => c.verify('reset-link-not-code'),
      'wrong purpose accepted',
    );
    check(c.stage == IdentityStage.pendingVerification, 'pending preserved');
    await c.resend();
    c.close();
  });
  await test('email verification cannot claim identity verification', () async {
    final f = IdentityFixture()..badIdentity = true;
    final c = client(f);
    await signup(c);
    await rejected(() => c.verify('654321'), 'identity claim accepted');
    check(!c.authenticated, 'not authenticated');
    c.close();
  });
  await test(
    'profile preferences and adaptive question body use domain bridge',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      await c.verify('654321');
      await c.domain('PUT', '/v1/me/profile', body: {'discoverable': false});
      await c.domain(
        'PUT',
        '/v1/me/preferences',
        body: {'min_age': 18, 'max_age': 60},
      );
      await c.domain(
        'POST',
        '/v1/me/assessment/answers',
        body: {'question_id': 'family_plan', 'option_id': 'children'},
      );
      check(
        f.answers == 1 && f.lastProfile?['discoverable'] == false,
        'profile bridge',
      );
      c.close();
    },
  );
  await test('domain401 expires current state', () async {
    final f = IdentityFixture();
    final c = client(f);
    await signup(c);
    await c.verify('654321');
    f.expired = true;
    await rejected(() async {
      await c.domain('GET', '/v1/me');
    }, 'expiry');
    check(
      c.stage == IdentityStage.signedOut && c.identity == null,
      'clear expired',
    );
    c.close();
  });
  await test('401 logout is success and next login can authenticate', () async {
    final f = IdentityFixture();
    final c = client(f);
    await signup(c);
    await c.verify('654321');
    await c.logout();
    check(!c.authenticated, 'logout');
    await c.login('member@example.invalid', 'SyntheticOnlyPassword!12');
    check(c.authenticated, 'login');
    c.close();
  });
  await test(
    'logout-all clears session and requires acknowledged revocation',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      await c.verify('654321');
      await c.logout(everywhere: true);
      check(!c.authenticated, 'revoke');
      c.close();
    },
  );
  await test(
    'network-uncertain logout still clears local credentials',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      await c.verify('654321');
      f.failNetwork = true;
      await rejected(() => c.logout(), 'uncertain logout');
      check(c.stage == IdentityStage.signedOut, 'local logout');
      c.close();
    },
  );
  await test(
    'owned pending delete requires password and explicit confirmation',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      await rejected(
        () => c.deleteAccount('SyntheticOnlyPassword!12', confirmed: false),
        'confirmation',
      );
      await rejected(() => c.deleteAccount('bad', confirmed: true), 'password');
      check(f.deletions == 0, 'no deletion');
      await c.deleteAccount('SyntheticOnlyPassword!12', confirmed: true);
      check(
        f.deletions == 1 &&
            f.reauths == 0 &&
            c.stage == IdentityStage.signedOut,
        'pending deletion',
      );
      c.close();
    },
  );
  await test(
    'verified deletion reauthenticates and never uses pending route',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      await c.verify('654321');
      await c.deleteAccount('SyntheticOnlyPassword!12', confirmed: true);
      check(
        f.reauths == 1 &&
            f.deletions == 1 &&
            c.stage == IdentityStage.signedOut,
        'verified delete',
      );
      check(!f.calls.any((p) => p.contains('pending-account')), 'no fallback');
      c.close();
    },
  );
  await test(
    'late signup after close cannot resurrect pending token',
    () async {
      final f = IdentityFixture()..holdSignup = true;
      final c = client(f);
      final pending = signup(c);
      await Future<void>.delayed(Duration.zero);
      c.close();
      f.pendingSignup!.complete(f.authReply);
      await rejected(() => pending, 'late signup');
      check(c.stage == IdentityStage.signedOut, 'closed state');
    },
  );
  await test(
    'late signup after logout cannot resurrect pending token',
    () async {
      final f = IdentityFixture()..holdSignup = true;
      final c = client(f);
      final pending = signup(c);
      await Future<void>.delayed(Duration.zero);
      await c.logout();
      f.pendingSignup!.complete(f.authReply);
      await rejected(() => pending, 'late signup logout');
      check(c.stage == IdentityStage.signedOut, 'logout state');
      c.close();
    },
  );
  await test('old domain401 cannot clear a newer login session', () async {
    final f = IdentityFixture();
    final late = Completer<ApiResponse>();
    final c = IdentityClient(
      baseUri: Uri.parse('http://127.0.0.1:8089'),
      transport: ScriptTransport((method, uri, headers, body) {
        if (uri.path == '/v1/me') return late.future;
        return f.send(method, uri, headers, body);
      }),
    );
    await signup(c);
    await c.verify('654321');
    final old = c.domain('GET', '/v1/me');
    await c.login('member@example.invalid', 'SyntheticOnlyPassword!12');
    late.complete(
      ApiResponse(
        401,
        jsonEncode({
          'error': {'code': 'unauthenticated'},
        }),
      ),
    );
    await rejected(() async {
      await old;
    }, 'stale401');
    check(c.authenticated, 'new session retained');
    c.close();
  });
  for (final operation in ['resend', 'refresh', 'expired']) {
    await test(
      'late pending $operation cannot downgrade verified session',
      () async {
        final f = IdentityFixture();
        final late = Completer<ApiResponse>();
        final c = IdentityClient(
          baseUri: Uri.parse('http://127.0.0.1:8089'),
          transport: ScriptTransport((method, uri, headers, body) {
            if (operation == 'resend' &&
                    uri.path.endsWith('/auth/email/verify/resend') ||
                operation != 'resend' && uri.path.endsWith('/auth/session'))
              return late.future;
            return f.send(method, uri, headers, body);
          }),
        );
        await signup(c);
        final before = operation == 'expired'
            ? ApiResponse(
                410,
                jsonEncode({
                  'error': {'code': 'flow_expired'},
                }),
              )
            : f.authReply;
        final pending = operation == 'resend' ? c.resend() : c.refreshSession();
        await c.verify('654321');
        late.complete(before);
        await rejected(() => pending, 'stale pending response');
        check(c.authenticated, 'verified session retained');
        await c.domain('GET', '/v1/me');
        c.close();
      },
    );
  }
  await test(
    'confirmation generation cannot delete a replacement session',
    () async {
      final f = IdentityFixture();
      final c = client(f);
      await signup(c);
      final generation = c.sessionGeneration;
      await c.verify('654321');
      await rejected(
        () => c.deleteAccount(
          'SyntheticOnlyPassword!12',
          confirmed: true,
          expectedGeneration: generation,
        ),
        'old confirmation',
      );
      check(f.deletions == 0 && f.reauths == 0, 'no deletion request sent');
      c.close();
    },
  );
  await test(
    'leap-day synthetic adult date clamps rather than moving into March',
    () async {
      final f = IdentityFixture();
      String? birth;
      final c = IdentityClient(
        baseUri: Uri.parse('http://127.0.0.1:8089'),
        clock: () => DateTime.utc(2024, 2, 29),
        transport: ScriptTransport((method, uri, headers, body) {
          if (uri.path.endsWith('/auth/signup'))
            birth = (jsonDecode(body!) as Map)['birth_date'] as String;
          return f.send(method, uri, headers, body);
        }),
      );
      await c.signup(
        email: 'member@example.invalid',
        password: 'SyntheticOnlyPassword!12',
        age: 18,
        adult: true,
        muslim: true,
        terms: true,
        privacy: true,
      );
      check(birth == '2006-02-28', 'leap birth date');
      c.close();
    },
  );
  stdout.writeln('IDENTITY_CLIENT_CHECKS_PASSED=$passed');
}
