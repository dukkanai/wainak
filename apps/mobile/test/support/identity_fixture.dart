import 'dart:async';
import 'dart:convert';
import 'package:wainak_mobile/src/api/transport.dart';

/// Synthetic contract fixture, not Django or evidence of real email delivery.
class IdentityFixture implements ApiTransport {
  bool verified = false, closed = false, expired = false, failNetwork = false;
  bool holdSignup = false, holdProfile = false, badIdentity = false;
  Completer<ApiResponse>? pendingSignup, pendingProfile;
  int registrations = 0,
      verifications = 0,
      deletions = 0,
      reauths = 0,
      answers = 0;
  String token = 'synthetic-pending-only';
  final calls = <String>[];
  final headerNames = <Set<String>>[];
  Map<String, dynamic>? lastProfile,
      lastPreferences,
      storedProfile,
      storedPreferences;
  ApiResponse reply(int status, Object value) =>
      ApiResponse(status, jsonEncode(value));
  Map<String, dynamic> get meta => {
    'is_authenticated': verified,
    'session_token': token,
  };
  ApiResponse get authReply => reply(verified ? 200 : 401, {
    'status': verified ? 200 : 401,
    'meta': meta,
    'data': {
      'flows': verified
          ? []
          : [
              {'id': 'verify_email', 'is_pending': true},
            ],
    },
  });
  Map<String, dynamic> get question => {
    'complete': answers >= 3,
    'next_question': answers >= 3
        ? null
        : {
            'id': ['family_plan', 'parenting', 'communication'][answers],
            'prompt_ar': 'سؤال من خادم الاختبار ${answers + 1}',
            'options': [
              ['children'],
              ['shared_planning'],
              ['quiet_time'],
            ][answers],
          },
  };
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    calls.add('$method ${uri.path}');
    headerNames.add(headers.keys.toSet());
    if (failNetwork) throw StateError('Synthetic unavailable transport');
    final data = body == null
        ? <String, dynamic>{}
        : jsonDecode(body) as Map<String, dynamic>;
    if (uri.path.endsWith('/auth/signup')) {
      registrations++;
      if (holdSignup) {
        pendingSignup = Completer<ApiResponse>();
        return pendingSignup!.future;
      }
      return authReply;
    }
    if (uri.path.endsWith('/auth/login')) {
      token = verified ? 'synthetic-login-only' : 'synthetic-pending-only';
      return authReply;
    }
    if (expired)
      return reply(401, {
        'error': {'code': 'unauthenticated', 'message': 'not displayed'},
      });
    if (headers['X-Session-Token'] != token)
      return reply(401, {
        'error': {'code': 'unauthenticated'},
      });
    if (uri.path.endsWith('/auth/email/verify')) {
      verifications++;
      if (data['key'] != '654321')
        return reply(400, {
          'status': 400,
          'errors': [
            {'code': 'invalid_code', 'message': 'not displayed'},
          ],
        });
      verified = true;
      token = 'synthetic-verified-rotated-only';
      return authReply;
    }
    if (uri.path.endsWith('/auth/email/verify/resend'))
      return reply(200, {'status': 200, 'meta': meta});
    if (uri.path.endsWith('/auth/session')) {
      if (method == 'DELETE')
        return reply(401, {
          'status': 401,
          'meta': {'is_authenticated': false},
          'data': {'flows': []},
        });
      return authReply;
    }
    if (uri.path == '/identity/v1/logout-all')
      return reply(200, {'revoked_all': true});
    if (uri.path == '/identity/v1/reauthenticate') {
      reauths++;
      return data['password'] == 'bad'
          ? reply(403, {
              'error': {'code': 'reauthentication_failed'},
            })
          : reply(200, {'reauthenticated': true});
    }
    if (method == 'DELETE') {
      if (uri.path.endsWith('/pending-account') &&
          (verified || data['password'] == 'bad'))
        return reply(403, {
          'error': {'code': 'denied'},
        });
      if (data['confirmation'] != 'DELETE')
        return reply(400, {
          'error': {'code': 'denied'},
        });
      deletions++;
      return reply(200, {'deleted': true, 'identity_erased': true});
    }
    if (uri.path == '/identity/v1/me')
      return reply(200, {
        'id': '11111111-1111-4111-8111-111111111111',
        'domain_id': 'usr_11111111111111111111111111111111',
        'email': 'member@example.invalid',
        'email_verified': true,
        'mode': 'synthetic_identity_sandbox',
        'email_is_identity_verification': badIdentity,
      });
    if (uri.path == '/v1/me/profile') {
      lastProfile = data;
      if (holdProfile) {
        pendingProfile = Completer<ApiResponse>();
        return pendingProfile!.future;
      }
      return reply(200, {'profile': data});
    }
    if (uri.path == '/v1/me/preferences') {
      lastPreferences = data;
      return reply(200, {'preferences': data});
    }
    if (uri.path == '/v1/me/assessment/answers') {
      if (!data.containsKey('option_id') || data.containsKey('option'))
        return reply(400, {
          'error': {'code': 'invalid_fields'},
        });
      answers++;
      return reply(200, question);
    }
    if (uri.path == '/v1/me/assessment') return reply(200, question);
    if (uri.path == '/v1/me')
      return reply(200, {
        'id': 'usr_11111111111111111111111111111111',
        'dev_email_verified': true,
        'profile': storedProfile,
        'preferences': storedPreferences,
      });
    if (uri.path == '/v1/candidates') return reply(200, {'items': []});
    throw StateError('Unimplemented synthetic fixture request');
  }

  @override
  void close() {
    closed = true;
  }
}
