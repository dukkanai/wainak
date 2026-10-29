import 'dart:convert';
import 'transport.dart';
import 'relationship_page.dart';

class ApiFailure implements Exception {
  const ApiFailure(this.code, this.message);
  final String code, message;
  // Do not include raw server output or bearer credentials in diagnostics.
  @override
  String toString() => 'ApiFailure($code)';
}

class CandidateDto {
  const CandidateDto({
    required this.id,
    required this.alias,
    required this.age,
    required this.country,
    required this.maritalStatus,
    required this.marriageGoal,
  });
  factory CandidateDto.fromJson(Map<String, dynamic> json) {
    if (json['synthetic'] != true ||
        json['rating'] is! Map ||
        json['rating']['state'] != 'insufficient_data') {
      throw const FormatException('Unsupported candidate projection');
    }
    return CandidateDto(
      id: json['id'] as String,
      alias: json['alias'] as String,
      age: json['age'] as int,
      country: json['country'] as String,
      maritalStatus: json['marital_status'] as String,
      marriageGoal: json['marriage_goal'] as String,
    );
  }
  final String id, alias, country, maritalStatus, marriageGoal;
  final int age;
}

class RelationshipDto {
  /// Clear peer projection after acknowledged block, without a second request.
  RelationshipDto.blocked(RelationshipDto source)
    : id = source.id,
      initiatorId = source.initiatorId,
      recipientId = source.recipientId,
      status = 'blocked',
      peer = null,
      canSendCards = false;
  RelationshipDto.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      initiatorId = json['initiator_id'] as String,
      recipientId = json['recipient_id'] as String,
      status = json['status'] as String,
      peer = json['peer'] == null
          ? null
          : CandidateDto.fromJson(json['peer'] as Map<String, dynamic>),
      canSendCards =
          (json['permissions'] as Map<String, dynamic>)['can_send_cards'] ==
          true {
    final p = json['permissions'] as Map<String, dynamic>;
    if (![
          'requested',
          'accepted_pending_activation',
          'active_cards',
          'exclusive_cards',
          'frozen',
          'declined',
          'cancelled',
          'ended',
          'blocked',
        ].contains(status) ||
        p['can_send_text'] != false ||
        p['can_send_media'] != false ||
        p['can_disclose_identity'] != false ||
        json['activation_mode'] != 'development_simulation_only' ||
        (canSendCards &&
            (!['active_cards', 'exclusive_cards'].contains(status) ||
                peer == null))) {
      throw const FormatException('Unsupported relationship permissions');
    }
  }
  final String id, status, initiatorId, recipientId;
  final CandidateDto? peer;
  final bool canSendCards;
}

/// Phase-one contract client used by the explicit native development repository.
/// Tokens exist only in this object; no automatic retries, persistence or logging.
class WainekApiClient {
  WainekApiClient({required this.baseUri, required this.transport}) {
    final loopback = [
      '127.0.0.1',
      '::1',
      '[::1]',
      'localhost',
    ].contains(baseUri.host);
    if (!(baseUri.scheme == 'https' ||
            (baseUri.scheme == 'http' && loopback)) ||
        baseUri.userInfo.isNotEmpty ||
        baseUri.hasQuery ||
        baseUri.hasFragment ||
        !['', '/'].contains(baseUri.path)) {
      throw ArgumentError(
        'Use an explicit HTTPS origin or development loopback.',
      );
    }
  }
  final Uri baseUri;
  final ApiTransport transport;
  String? _token;
  int _sessionEpoch = 0;
  bool _closed = false;
  bool get hasSession => _token != null;
  static const policyVersion = 'dev-2026-10-24';
  String _id(String id, String prefix) {
    if (!RegExp('^${prefix}_[0-9a-f]{32}\u0024').hasMatch(id))
      throw ArgumentError('Invalid opaque resource ID');
    return id;
  }

  Future<Map<String, dynamic>> _request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool anonymous = false,
    String? idempotencyKey,
  }) async {
    if (_closed) throw const ApiFailure('client_closed', 'أُغلقت هذه الجلسة.');
    final epoch = _sessionEpoch;
    if (!anonymous && _token == null)
      throw const ApiFailure('session_required', 'ابدأ جلسة التطوير أولًا.');
    final headers = <String, String>{
      'Accept': 'application/json',
      if (method != 'GET') 'Content-Type': 'application/json',
      if (!anonymous) 'Authorization': 'Bearer $_token',
      if (idempotencyKey != null) 'Idempotency-Key': idempotencyKey,
    };
    final encoded = method == 'GET'
        ? null
        : jsonEncode(body ?? <String, dynamic>{});
    if (encoded != null && utf8.encode(encoded).length > 16384)
      throw const ApiFailure('input_too_large', 'حجم الطلب أكبر من المسموح.');
    ApiResponse response;
    try {
      response = await transport.send(
        method,
        baseUri.resolve(path),
        headers,
        encoded,
      );
    } catch (_) {
      throw const ApiFailure(
        'network_unavailable',
        'تعذر الاتصال. لم نؤكد إتمام العملية؛ تحقق من الحالة قبل تكرارها.',
      );
    }
    if (_closed || epoch != _sessionEpoch) {
      throw const ApiFailure(
        'stale_response',
        'تغيرت الجلسة؛ تجاهلنا الاستجابة القديمة.',
      );
    }
    if (response.statusCode == 401) {
      _token = null;
      _sessionEpoch++;
    }
    Map<String, dynamic> decoded;
    try {
      decoded = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw const ApiFailure('invalid_response', 'تعذر فهم استجابة الخدمة.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final raw = decoded['error'];
      final code = raw is Map && raw['code'] is String
          ? raw['code'] as String
          : 'request_failed';
      throw ApiFailure(code, switch (response.statusCode) {
        401 => 'انتهت الجلسة؛ يلزم بدء جلسة جديدة.',
        403 => 'لا تملك صلاحية هذا الإجراء.',
        404 => 'هذا المورد غير متاح.',
        409 => 'تغيرت الحالة. حدّثها قبل اتخاذ قرار جديد.',
        _ => 'لم تكتمل العملية. راجع المدخلات وحاول بعد التحقق من الحالة.',
      });
    }
    return decoded;
  }

  Future<Map<String, dynamic>> register({
    required String email,
    required String birthDate,
    required bool isMuslim,
    required bool acceptedTerms,
    required bool acknowledgedPrivacy,
  }) async {
    if (!(isMuslim && acceptedTerms && acknowledgedPrivacy)) {
      throw const ApiFailure(
        'consent_required',
        'أكمل الإقرارات قبل إنشاء جلسة.',
      );
    }
    if (_closed) throw const ApiFailure('client_closed', 'أُغلقت هذه الجلسة.');
    final registrationEpoch = ++_sessionEpoch;
    _token = null;
    final result = await _request(
      'POST',
      '/v1/dev/accounts',
      anonymous: true,
      body: {
        'email': email,
        'birth_date': birthDate,
        'is_muslim': true,
        'terms_version': policyVersion,
        'privacy_version': policyVersion,
      },
    );
    if (_closed || registrationEpoch != _sessionEpoch) {
      throw const ApiFailure(
        'stale_response',
        'تغيرت الجلسة؛ تجاهلنا الاستجابة القديمة.',
      );
    }
    final account = result['account'];
    if (account is! Map<String, dynamic> ||
        account['id'] is! String ||
        !RegExp(r'^usr_[0-9a-f]{32}$').hasMatch(account['id'] as String) ||
        result['mode'] != 'synthetic_development_only' ||
        result['token_type'] != 'Bearer' ||
        result['access_token'] is! String ||
        (result['access_token'] as String).isEmpty) {
      throw const ApiFailure(
        'invalid_response',
        'استجابة جلسة التطوير غير صالحة.',
      );
    }
    _token = result['access_token'] as String;
    return account;
  }

  Future<Map<String, dynamic>> verifyEmailSimulation() => _request(
    'POST',
    '/v1/dev/verify-email',
    body: {'simulate_verified': true},
  );
  Future<Map<String, dynamic>> me() => _request('GET', '/v1/me');
  Future<Map<String, dynamic>> saveProfile(Map<String, dynamic> profile) =>
      _request('PUT', '/v1/me/profile', body: profile);
  Future<Map<String, dynamic>> savePreferences(
    Map<String, dynamic> preferences,
  ) => _request('PUT', '/v1/me/preferences', body: preferences);
  Future<Map<String, dynamic>> assessment() =>
      _request('GET', '/v1/me/assessment');
  Future<Map<String, dynamic>> answerAssessment(
    String questionId,
    String optionId,
  ) => _request(
    'POST',
    '/v1/me/assessment/answers',
    body: {'question_id': questionId, 'option_id': optionId},
  );
  Future<RelationshipPage> relationshipsPage({String? cursor}) async {
    final data = await _request('GET', relationshipPagePath(cursor));
    try {
      return RelationshipPage.fromJson(data, after: cursor);
    } on FormatException {
      throw const ApiFailure('invalid_response', 'صفحة الطلبات غير متوافقة.');
    }
  }

  /// Preserve the legacy complete-list contract without an unbounded response
  /// or silently hiding a relevant incoming request on a later page.
  Future<Map<String, dynamic>> relationships() async {
    final epoch = _sessionEpoch;
    final items = <Map<String, dynamic>>[];
    String? cursor;
    for (var pageNumber = 0; pageNumber < 50; pageNumber++) {
      final page = await relationshipsPage(cursor: cursor);
      if (_closed || epoch != _sessionEpoch) {
        throw const ApiFailure('stale_response', 'تغيرت الجلسة؛ حدّث الطلبات.');
      }
      items.addAll(page.items);
      cursor = page.nextCursor;
      if (cursor == null) return {'items': items, 'next_cursor': null};
    }
    throw const ApiFailure(
      'relationship_page_limit',
      'تجاوز سجل الطلبات حد هذه المعاينة؛ لم نعرض قائمة مبتورة. استخدم قائمة الطلبات في مسار الحسابات.',
    );
  }

  Future<Map<String, dynamic>> candidates() =>
      _request('GET', '/v1/candidates');
  Future<RelationshipDto> requestRelationship(
    String candidateId,
    String idempotencyKey,
  ) async {
    if (!RegExp(r'^[A-Za-z0-9_-]{8,64}$').hasMatch(idempotencyKey))
      throw ArgumentError('Invalid idempotency key');
    return RelationshipDto.fromJson(
      await _request(
        'POST',
        '/v1/relationships',
        body: {'candidate_id': _id(candidateId, 'usr')},
        idempotencyKey: idempotencyKey,
      ),
    );
  }

  Future<RelationshipDto> relationship(String id) async =>
      RelationshipDto.fromJson(
        await _request('GET', '/v1/relationships/${_id(id, 'rel')}'),
      );
  Future<RelationshipDto> respond(String id, {required bool accept}) async =>
      RelationshipDto.fromJson(
        await _request(
          'POST',
          '/v1/relationships/${_id(id, 'rel')}/respond',
          body: {'decision': accept ? 'accept' : 'decline'},
        ),
      );
  Future<RelationshipDto> cancelRelationship(String id) async =>
      RelationshipDto.fromJson(
        await _request('POST', '/v1/relationships/${_id(id, 'rel')}/cancel'),
      );

  Future<RelationshipDto> activateSimulation(String id) async =>
      RelationshipDto.fromJson(
        await _request(
          'POST',
          '/v1/dev/relationships/${_id(id, 'rel')}/activate',
          body: {'simulate_entitlement': true},
        ),
      );
  Future<Map<String, dynamic>> cards(String id) =>
      _request('GET', '/v1/relationships/${_id(id, 'rel')}/cards');
  Future<Map<String, dynamic>> block(String targetId) =>
      _request('POST', '/v1/blocks', body: {'target_id': _id(targetId, 'usr')});
  Future<Map<String, dynamic>> report(
    String targetId,
    String category, {
    String? relationshipId,
  }) => _request(
    'POST',
    '/v1/reports',
    body: {
      'target_id': _id(targetId, 'usr'),
      'category': category,
      if (relationshipId != null) 'relationship_id': _id(relationshipId, 'rel'),
    },
  );
  Future<void> deleteAccount() async {
    await _request('DELETE', '/v1/me', body: {'confirmation': 'DELETE'});
    _token = null;
    _sessionEpoch++;
  }

  void close() {
    _closed = true;
    _sessionEpoch++;
    _token = null;
    transport.close();
  }
}
