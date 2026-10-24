import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:wainak_mobile/src/identity/client.dart';
import 'package:wainak_mobile/src/api/transport_io.dart';
import 'identity_fixture_bridge.dart';

void check(bool value, String name) {
  if (!value) throw StateError(name);
}

String nonce() => base64UrlEncode(
  List<int>.generate(18, (_) => Random.secure().nextInt(256)),
).replaceAll('=', '');
Future<void> main(List<String> args) async {
  if (args.length != 1 || args.single != '--run-disposable-identity') {
    stderr.writeln(
      'Explicit --run-disposable-identity required; no fixture started.',
    );
    exitCode = 2;
    return;
  }
  IdentityFixtureBridge? bridge;
  IdentityClient? first, second;
  var successful = false;
  try {
    bridge = await IdentityFixtureBridge.start();
    first = IdentityClient(
      baseUri: bridge.baseUri,
      transport: NativeApiTransport(timeout: const Duration(seconds: 35)),
    );
    second = IdentityClient(
      baseUri: bridge.baseUri,
      transport: NativeApiTransport(timeout: const Duration(seconds: 35)),
    );
    final email =
        'mobile_${nonce().toLowerCase().replaceAll(RegExp('[^a-z0-9]'), '')}@example.invalid';
    final password = '${nonce()}!7aZ';
    await first.signup(
      email: email,
      password: password,
      age: 29,
      adult: true,
      muslim: true,
      terms: true,
      privacy: true,
    );
    check(first.stage == IdentityStage.pendingVerification, 'pending state');
    final mail = await bridge.verification(email);
    await first.verify(mail.code);
    check(first.authenticated, 'framework verification');
    await first.domain(
      'PUT',
      '/v1/me/profile',
      body: {
        'gender': 'female',
        'country': 'SA',
        'marital_status': 'single',
        'declared_wives': 0,
        'marriage_goal': 'build_family',
        'discoverable': false,
      },
    );
    await first.domain(
      'PUT',
      '/v1/me/preferences',
      body: {
        'min_age': 18,
        'max_age': 60,
        'countries': <String>[],
        'marital_statuses': ['single'],
      },
    );
    var assessment = await first.domain('GET', '/v1/me/assessment');
    var count = 0;
    while (assessment['complete'] != true) {
      check(count++ < 4, 'bounded questions');
      final question = assessment['next_question'] as Map;
      assessment = await first.domain(
        'POST',
        '/v1/me/assessment/answers',
        body: {
          'question_id': question['id'],
          'option_id': (question['options'] as List).first,
        },
      );
    }
    check(count == 3, 'adaptive question count');
    await second.login(email, password);
    check(second.authenticated, 'independent login');
    await first.logout(everywhere: true);
    var rejected = false;
    try {
      await second.domain('GET', '/v1/me');
    } on IdentityFailure {
      rejected = true;
    }
    check(
      rejected && second.stage == IdentityStage.signedOut,
      'global revoke401 clears client',
    );
    await first.login(email, password);
    await first.logout();
    check(first.stage == IdentityStage.signedOut, 'allauth401 logout success');
    await first.login(email, password);
    await first.deleteAccount(
      password,
      confirmed: true,
      expectedGeneration: first.sessionGeneration,
    );
    check(first.stage == IdentityStage.signedOut, 'verified deletion');
    await bridge.shutdown();
    successful = true;
    stdout.writeln(
      'LIVE_IDENTITY_NATIVE_PASS; real framework auth/profile/revoke/delete; private PIPE and normal cleanup verified.',
    );
  } catch (_) {
    stderr.writeln(
      'LIVE_IDENTITY_NATIVE_FAILED; private values suppressed; inspect safe fixture/QA evidence only.',
    );
    exitCode = 1;
  } finally {
    first?.close();
    second?.close();
    if (!successful && bridge != null) {
      try {
        await bridge.abort();
      } catch (_) {
        stderr.writeln('OWNED_FIXTURE_CLEANUP_AUDIT_REQUIRED');
        exitCode = 1;
      }
    }
  }
}
