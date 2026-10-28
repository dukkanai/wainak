import 'dart:async';
import 'dart:convert';
import 'package:wainak_mobile/src/api/transport.dart';
import 'identity_fixture.dart';

class MatchingFixture extends IdentityFixture {
  String actorId = 'usr_11111111111111111111111111111111',
      targetId = 'usr_22222222222222222222222222222222',
      email = 'member@example.invalid';
  bool incoming = false,
      hasRelation = false,
      blocked = false,
      peerHidden = false,
      failRequestOnce = false,
      failReportOnce = false,
      reportGone = false,
      unknownGone = false,
      rejectActions = false,
      denyCandidates = false;
  bool holdCandidates = false, holdRelationships = false, holdAction = false;
  bool failRelationships = false;
  List<Map<String, dynamic>>? relationshipRows;
  Map<String, dynamic>? relationshipPageOverride;
  Completer<ApiResponse>? pendingCandidates,
      pendingRelationships,
      pendingAction;
  int requestCreates = 0, blockCalls = 0, reportCalls = 0;
  String relationStatus = 'requested';
  final matchingCalls = <Map<String, dynamic>>[];
  final requestKeys = <String, String>{};
  Map<String, dynamic> relationshipPage(String? cursor) {
    final rows = relationshipRows ?? (hasRelation ? [relationship] : []);
    final start = cursor == null
        ? 0
        : rows.indexWhere((row) => row['id'] == cursor) + 1;
    final end = (start + 20).clamp(0, rows.length);
    final page = rows.sublist(start, end);
    return {
      'items': page,
      'next_cursor': end < rows.length ? page.last['id'] : null,
    };
  }

  Map<String, dynamic> get candidate => {
    'id': targetId,
    'alias': 'طرف اختبار',
    'age': 30,
    'country': 'SA',
    'marital_status': 'single',
    'marriage_goal': 'build_family',
    'rating': {'state': 'insufficient_data'},
    'synthetic': true,
  };
  Map<String, dynamic> get relationship => {
    'id': 'rel_44444444444444444444444444444444',
    'initiator_id': incoming ? targetId : actorId,
    'recipient_id': incoming ? actorId : targetId,
    'status': blocked ? 'blocked' : relationStatus,
    'peer': blocked || peerHidden ? null : candidate,
    'exclusive_requested_by': null,
    'permissions': {
      'can_send_cards': false,
      'can_send_text': false,
      'can_send_media': false,
      'can_disclose_identity': false,
    },
    'activation_mode': 'development_simulation_only',
    'direction': incoming ? 'incoming' : 'outgoing',
    'available_actions': [
      if (!blocked && relationStatus == 'requested') ...[
        if (incoming) ...[if (!peerHidden) 'accept', 'decline'] else 'cancel',
      ],
      if (!blocked &&
          {
            'accepted_pending_activation',
            'active_cards',
            'exclusive_cards',
            'frozen',
          }.contains(relationStatus))
        'end',
      'block',
      'report',
    ],
  };
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    if (uri.path == '/identity/v1/me')
      return reply(200, {
        'id': '11111111-1111-4111-8111-111111111111',
        'domain_id': actorId,
        'email': email,
        'email_verified': true,
        'mode': 'synthetic_identity_sandbox',
        'email_is_identity_verification': false,
      });
    if (uri.path == '/v1/me')
      return reply(200, {
        'id': actorId,
        'profile': storedProfile,
        'preferences': storedPreferences,
      });
    if (!uri.path.startsWith('/v1/relationships') &&
        !{'/v1/candidates', '/v1/blocks', '/v1/reports'}.contains(uri.path))
      return super.send(method, uri, headers, body);
    final data = body == null
        ? <String, dynamic>{}
        : jsonDecode(body) as Map<String, dynamic>;
    matchingCalls.add({
      'method': method,
      'path': uri.path,
      'query': uri.query,
      'key': headers['Idempotency-Key'],
      'body': data,
      'header_names': headers.keys.toSet(),
    });
    if (expired || headers['X-Session-Token'] != token)
      return reply(401, {
        'error': {'code': 'unauthenticated'},
      });
    if (unknownGone)
      return reply(410, {
        'error': {'code': 'unavailable_business_record'},
      });
    if (uri.path == '/v1/candidates') {
      if (holdCandidates) {
        pendingCandidates = Completer<ApiResponse>();
        return pendingCandidates!.future;
      }
      if (denyCandidates)
        return reply(403, {
          'error': {'code': 'consent_required'},
        });
      return reply(200, {
        'items': blocked ? [] : [candidate],
        'mode': 'synthetic_development_only',
      });
    }
    if (uri.path == '/v1/relationships' && method == 'GET') {
      if (failRelationships) throw StateError('Synthetic page failure');
      if (holdRelationships) {
        pendingRelationships = Completer<ApiResponse>();
        return pendingRelationships!.future;
      }
      return reply(
        200,
        relationshipPageOverride ??
            relationshipPage(uri.queryParameters['cursor']),
      );
    }
    if (uri.path == '/v1/relationships' && method == 'POST') {
      final key = headers['Idempotency-Key'];
      if (key == null)
        return reply(400, {
          'error': {'code': 'idempotency_key_required'},
        });
      if (requestKeys.containsKey(key) &&
          requestKeys[key] != data['candidate_id'])
        return reply(409, {
          'error': {'code': 'idempotency_conflict'},
        });
      if (!requestKeys.containsKey(key)) {
        requestKeys[key] = data['candidate_id'];
        requestCreates++;
      }
      hasRelation = true;
      incoming = false;
      if (failRequestOnce) {
        failRequestOnce = false;
        throw StateError('Synthetic lost response after request');
      }
      return reply(201, relationship);
    }
    if (uri.path == '/v1/blocks') {
      blockCalls++;
      blocked = true;
      return reply(200, {'blocked': true});
    }
    if (uri.path == '/v1/reports') {
      reportCalls++;
      if (headers['Idempotency-Key'] == null)
        return reply(400, {
          'error': {'code': 'idempotency_key_required'},
        });
      if (reportGone)
        return reply(410, {
          'error': {'code': 'report_no_longer_available'},
        });
      if (failReportOnce) {
        failReportOnce = false;
        throw StateError('Synthetic lost report response');
      }
      return reply(201, {
        'id': 'rpt_55555555555555555555555555555555',
        'status': 'recorded_development_only',
        'evidence_uploaded': false,
        'notice': 'Synthetic receipt',
      });
    }
    if (method == 'GET') return reply(200, relationship);
    if (holdAction) {
      pendingAction = Completer<ApiResponse>();
      return pendingAction!.future;
    }
    if (blocked || rejectActions)
      return reply(409, {
        'error': {'code': 'invalid_transition'},
      });
    if (uri.path.endsWith('/respond')) {
      if (!incoming)
        return reply(403, {
          'error': {'code': 'recipient_only'},
        });
      relationStatus = data['decision'] == 'accept'
          ? 'accepted_pending_activation'
          : 'declined';
    } else if (uri.path.endsWith('/cancel')) {
      relationStatus = 'cancelled';
    } else if (uri.path.endsWith('/end')) {
      relationStatus = 'ended';
    }
    return reply(200, relationship);
  }
}
