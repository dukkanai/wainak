import 'dart:math';
import 'client.dart';

const _userPattern = r'^usr_[0-9a-f]{32}$';
const _relationPattern = r'^rel_[0-9a-f]{32}$';
Never _badProjection() => throw const IdentityFailure(
  'invalid_matching_response',
  'استجابة التعارف غير متوافقة؛ لم نعرض بيانات أو صلاحيات بديلة.',
);
bool _id(Object? value, String pattern) =>
    value is String && RegExp(pattern).hasMatch(value);
Map<String, dynamic> _object(Object? value) {
  if (value is! Map<String, dynamic>) _badProjection();
  return value;
}

void _keys(Map<String, dynamic> value, Set<String> expected) {
  if (value.keys.toSet().difference(expected).isNotEmpty ||
      expected.difference(value.keys.toSet()).isNotEmpty)
    _badProjection();
}

enum MatchAction { accept, decline, cancel, end, block, report }

enum MatchDirection { incoming, outgoing }

class MatchCandidate {
  const MatchCandidate._(
    this.id,
    this.alias,
    this.age,
    this.country,
    this.maritalStatus,
    this.goal,
    this.actorId,
    this.generation,
  );
  final String id, alias, country, maritalStatus, goal, actorId;
  final int generation;
  final int age;
  factory MatchCandidate.fromJson(
    Object? source, {
    required String actorId,
    required int generation,
  }) {
    final data = _object(source);
    _keys(data, {
      'id',
      'alias',
      'age',
      'country',
      'marital_status',
      'marriage_goal',
      'rating',
      'synthetic',
    });
    final rating = _object(data['rating']);
    _keys(rating, {'state'});
    if (!_id(data['id'], _userPattern) ||
        data['alias'] is! String ||
        (data['alias'] as String).trim().isEmpty ||
        (data['alias'] as String).length > 160 ||
        data['age'] is! int ||
        data['age'] < 18 ||
        data['age'] > 120 ||
        data['country'] is! String ||
        !RegExp(r'^[A-Z]{2}$').hasMatch(data['country']) ||
        !{
          'single',
          'married',
          'divorced',
          'widowed',
        }.contains(data['marital_status']) ||
        !{'build_family', 'companionship'}.contains(data['marriage_goal']) ||
        rating['state'] != 'insufficient_data' ||
        data['synthetic'] != true)
      _badProjection();
    return MatchCandidate._(
      data['id'],
      data['alias'],
      data['age'],
      data['country'],
      data['marital_status'],
      data['marriage_goal'],
      actorId,
      generation,
    );
  }
}

class MatchRelationship {
  const MatchRelationship._({
    required this.id,
    required this.actorId,
    required this.targetId,
    required this.status,
    required this.direction,
    required this.actions,
    required this.peer,
    required this.generation,
  });
  final String id, actorId, targetId, status;
  final MatchDirection direction;
  final Set<MatchAction> actions;
  final MatchCandidate? peer;
  final int generation;
  bool can(MatchAction action) => actions.contains(action);
  factory MatchRelationship.fromJson(
    Object? source, {
    required String actorId,
    required int generation,
  }) {
    final data = _object(source);
    _keys(data, {
      'id',
      'initiator_id',
      'recipient_id',
      'status',
      'peer',
      'exclusive_requested_by',
      'permissions',
      'activation_mode',
      'direction',
      'available_actions',
    });
    if (!_id(data['id'], _relationPattern) ||
        !_id(data['initiator_id'], _userPattern) ||
        !_id(data['recipient_id'], _userPattern) ||
        data['initiator_id'] == data['recipient_id'])
      _badProjection();
    final incoming = data['recipient_id'] == actorId,
        outgoing = data['initiator_id'] == actorId;
    if (incoming == outgoing ||
        data['direction'] != (incoming ? 'incoming' : 'outgoing'))
      _badProjection();
    final target =
        (incoming ? data['initiator_id'] : data['recipient_id']) as String;
    const states = {
      'requested',
      'accepted_pending_activation',
      'active_cards',
      'exclusive_cards',
      'frozen',
      'declined',
      'cancelled',
      'ended',
      'blocked',
    };
    if (!states.contains(data['status']) ||
        data['activation_mode'] != 'development_simulation_only')
      _badProjection();
    final exclusive = data['exclusive_requested_by'];
    if (exclusive != null && exclusive != actorId && exclusive != target)
      _badProjection();
    final permissions = _object(data['permissions']);
    _keys(permissions, {
      'can_send_cards',
      'can_send_text',
      'can_send_media',
      'can_disclose_identity',
    });
    if (permissions['can_send_cards'] is! bool ||
        permissions['can_send_text'] != false ||
        permissions['can_send_media'] != false ||
        permissions['can_disclose_identity'] != false)
      _badProjection();
    // Legacy active rows may still carry a card permission. This client never
    // exposes a card/activation route, action, editor, or stored answer/history.
    final peer = data['peer'] == null
        ? null
        : MatchCandidate.fromJson(
            data['peer'],
            actorId: actorId,
            generation: generation,
          );
    if (peer != null && peer.id != target) _badProjection();
    final rawActions = data['available_actions'];
    if (rawActions is! List || rawActions.any((v) => v is! String))
      _badProjection();
    final actions = <MatchAction>{};
    for (final value in rawActions) {
      final matches = MatchAction.values.where((v) => v.name == value);
      if (matches.length != 1 || !actions.add(matches.single)) _badProjection();
    }
    final status = data['status'] as String;
    if (permissions['can_send_cards'] == true &&
        (peer == null || !{'active_cards', 'exclusive_cards'}.contains(status)))
      _badProjection();
    if ((actions.contains(MatchAction.accept) ||
            actions.contains(MatchAction.decline)) &&
        (!incoming || status != 'requested'))
      _badProjection();
    if (actions.contains(MatchAction.accept) && peer == null) _badProjection();
    if (actions.contains(MatchAction.cancel) &&
        (!outgoing || status != 'requested'))
      _badProjection();
    if (actions.contains(MatchAction.end) &&
        !{
          'accepted_pending_activation',
          'active_cards',
          'exclusive_cards',
          'frozen',
        }.contains(status))
      _badProjection();
    return MatchRelationship._(
      id: data['id'],
      actorId: actorId,
      targetId: target,
      status: status,
      direction: incoming ? MatchDirection.incoming : MatchDirection.outgoing,
      actions: Set.unmodifiable(actions),
      peer: peer,
      generation: generation,
    );
  }
}

class MatchSafetyContext {
  const MatchSafetyContext._(
    this.targetId,
    this.relationshipId,
    this.generation,
    this.alias,
    this.actorId,
  );
  final String targetId, actorId;
  final String? relationshipId, alias;
  final int generation;
  MatchSafetyContext redacted() =>
      MatchSafetyContext._(targetId, relationshipId, generation, null, actorId);
}

/// Per-auth-generation RAM-only adapter. UI hints are never server authority.
/// Pending intent keys survive view navigation, not logout/account replacement.
class IdentityMatchingRepository {
  IdentityMatchingRepository(this.client)
    : generation = client.sessionGeneration,
      actorId = client.identity?['domain_id'] as String? ?? '' {
    _current();
  }
  final IdentityClient client;
  final int generation;
  final String actorId;
  bool _closed = false;
  int _mutationRevision = 0,
      _pendingMutations = 0,
      _candidateRead = 0,
      _relationshipRead = 0;
  final _requestKeys = <String, String>{}, _reportKeys = <String, String>{};
  List<MatchCandidate> _candidates = [];
  List<MatchRelationship> _relationships = [];
  String? _nextRelationshipCursor;
  bool _hasRelationshipPage = false;
  MatchSafetyContext? _lastSafety;
  bool get current =>
      !_closed &&
      client.authenticated &&
      client.sessionGeneration == generation &&
      client.identity?['domain_id'] == actorId;
  List<MatchCandidate> get candidates =>
      current ? List.unmodifiable(_candidates) : const [];
  List<MatchRelationship> get relationships =>
      current ? List.unmodifiable(_relationships) : const [];
  bool get hasMoreRelationships => current && _nextRelationshipCursor != null;
  bool get hasRelationshipPage => current && _hasRelationshipPage;
  List<String> get pendingRequestTargets =>
      current ? List.unmodifiable(_requestKeys.keys) : const [];
  MatchSafetyContext? get lastSafety => current ? _lastSafety : null;
  void _current() {
    if (!current || !_id(actorId, _userPattern))
      throw const IdentityFailure(
        'stale_matching_context',
        'تغيرت الجلسة؛ افتح سياق التعارف من الحساب الحالي.',
      );
  }

  Never _stale() => throw const IdentityFailure(
    'stale_matching_result',
    'تغيرت حالة التعارف أثناء الطلب؛ تجاهلنا النتيجة القديمة. حدّث الحالة.',
  );
  int _beginMutation({bool safety = false}) {
    _current();
    if (_pendingMutations > 0 && !safety)
      throw const IdentityFailure(
        'matching_busy',
        'لم ينته الإجراء السابق؛ انتظر ثم حدّث الحالة. البلاغ والحظر مستقلان.',
      );
    _pendingMutations++;
    _candidates = [];
    _relationships = [];
    _nextRelationshipCursor = null;
    _hasRelationshipPage = false;
    return ++_mutationRevision;
  }

  void _mutationCurrent(int ticket) {
    _current();
    if (ticket != _mutationRevision || _pendingMutations != 1) _stale();
  }

  void _finishMutation() {
    _pendingMutations--;
    _mutationRevision++;
  }

  void _readCurrent(int revision, int read, int latest) {
    _current();
    if (_pendingMutations != 0 ||
        revision != _mutationRevision ||
        read != latest)
      _stale();
  }

  void _readAllowed() {
    _current();
    if (_pendingMutations != 0)
      throw const IdentityFailure(
        'matching_busy',
        'هناك إجراء لم ينته بعد؛ حدّث الحالة بعد ظهور نتيجته.',
      );
  }

  String _key(String prefix) =>
      '${prefix}_${List.generate(18, (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';
  bool hasPendingRequest(String target) =>
      current && _requestKeys.containsKey(target);
  Future<void> refreshCandidates() async {
    _current();
    _candidates = [];
    _readAllowed();
    final revision = _mutationRevision, read = ++_candidateRead;
    final data = await client.domain('GET', '/v1/candidates');
    _readCurrent(revision, read, _candidateRead);
    _keys(data, {'items', 'mode'});
    if (data['mode'] != 'synthetic_development_only' ||
        data['items'] is! List ||
        (data['items'] as List).length > 20)
      _badProjection();
    final items = (data['items'] as List)
        .map(
          (v) => MatchCandidate.fromJson(
            v,
            actorId: actorId,
            generation: generation,
          ),
        )
        .toList();
    if (items.any((p) => p.id == actorId) ||
        items.map((p) => p.id).toSet().length != items.length)
      _badProjection();
    _candidates = items;
  }

  Future<void> refreshRelationships() => _readRelationships(append: false);

  Future<void> loadNextRelationships() => _readRelationships(append: true);

  Future<void> _readRelationships({required bool append}) async {
    _readAllowed();
    final cursor = append ? _nextRelationshipCursor : null;
    if (append && cursor == null) return;
    final revision = _mutationRevision, read = ++_relationshipRead;
    final page = await client.relationshipsPage(cursor: cursor);
    _readCurrent(revision, read, _relationshipRead);
    final items = page.items
        .map(
          (v) => MatchRelationship.fromJson(
            v,
            actorId: actorId,
            generation: generation,
          ),
        )
        .toList();
    if (append) {
      final known = _relationships.map((r) => r.id).toSet();
      if (items.any((r) => known.contains(r.id))) _badProjection();
    }
    // Commit list and cursor together only after validation and stale guards.
    // Failed refresh/page reads leave previously loaded safety actions visible.
    _relationships = append ? [..._relationships, ...items] : items;
    _nextRelationshipCursor = page.nextCursor;
    _hasRelationshipPage = true;
  }

  MatchSafetyContext candidateContext(MatchCandidate candidate) {
    _current();
    if (candidate.actorId != actorId || candidate.generation != generation)
      throw const IdentityFailure(
        'stale_matching_context',
        'الترشيح من جلسة سابقة؛ لم نرسل إجراءً من الحساب الجديد.',
      );
    if (candidate.id == actorId || !_id(candidate.id, _userPattern))
      _badProjection();
    return MatchSafetyContext._(
      candidate.id,
      null,
      generation,
      candidate.alias,
      actorId,
    );
  }

  MatchSafetyContext relationshipContext(MatchRelationship relation) {
    _relationContext(relation);
    return MatchSafetyContext._(
      relation.targetId,
      relation.id,
      generation,
      relation.peer?.alias,
      actorId,
    );
  }

  void _safetyContext(MatchSafetyContext context) {
    _current();
    if (context.actorId != actorId ||
        context.generation != generation ||
        context.targetId == actorId ||
        !_id(context.targetId, _userPattern))
      _badProjection();
  }

  void _relationContext(MatchRelationship relation) {
    _current();
    if (relation.generation != generation || relation.actorId != actorId)
      throw const IdentityFailure(
        'stale_matching_context',
        'تغير سياق الطلب؛ حدّث قائمة الطلبات.',
      );
  }

  void _put(MatchRelationship relation) {
    _relationships = [
      relation,
      ..._relationships.where((r) => r.id != relation.id),
    ];
  }

  Future<MatchRelationship> request(MatchCandidate candidate) {
    _lastSafety = candidateContext(candidate).redacted();
    return _requestTarget(candidate.id);
  }

  Future<MatchRelationship> retryRequest(String target) {
    _current();
    if (!_requestKeys.containsKey(target))
      throw const IdentityFailure(
        'request_intent_missing',
        'لا يوجد طلب سابق غير مؤكد لهذا السياق.',
      );
    return _requestTarget(target);
  }

  Future<MatchRelationship> _requestTarget(String target) async {
    final ticket = _beginMutation();
    try {
      final key = _requestKeys.putIfAbsent(target, () => _key('request'));
      final data = await client.domain(
        'POST',
        '/v1/relationships',
        body: {'candidate_id': target},
        idempotencyKey: key,
      );
      _mutationCurrent(ticket);
      final relation = MatchRelationship.fromJson(
        data,
        actorId: actorId,
        generation: generation,
      );
      if (relation.targetId != target ||
          relation.direction != MatchDirection.outgoing)
        _badProjection();
      _requestKeys.remove(target);
      _put(relation);
      return relation;
    } finally {
      _finishMutation();
    }
  }

  Future<MatchRelationship> act(
    MatchRelationship relation,
    MatchAction action,
  ) async {
    _relationContext(relation);
    if (!relation.can(action) ||
        !{
          MatchAction.accept,
          MatchAction.decline,
          MatchAction.cancel,
          MatchAction.end,
        }.contains(action))
      throw const IdentityFailure(
        'action_unavailable',
        'هذا الإجراء غير متاح في حالة الطلب الحالية؛ حدّث القائمة.',
      );
    final ticket = _beginMutation();
    try {
      final suffix =
          (action == MatchAction.accept || action == MatchAction.decline)
          ? 'respond'
          : action.name;
      final body = <String, dynamic>{
        if (suffix == 'respond') 'decision': action.name,
        if (action == MatchAction.end) 'confirm': true,
      };
      final data = await client.domain(
        'POST',
        '/v1/relationships/${relation.id}/$suffix',
        body: body,
      );
      _mutationCurrent(ticket);
      final updated = MatchRelationship.fromJson(
        data,
        actorId: actorId,
        generation: generation,
      );
      if (updated.id != relation.id || updated.targetId != relation.targetId)
        _badProjection();
      _put(updated);
      return updated;
    } finally {
      _finishMutation();
    }
  }

  Future<void> block(MatchSafetyContext context) async {
    _safetyContext(context);
    _lastSafety = context.redacted();
    _beginMutation(
      safety: true,
    ); // Safety can supersede an in-flight non-safety mutation.
    _requestKeys.remove(
      context.targetId,
    ); // A confirmed block intent stops local request retries.
    try {
      final data = await client.domain(
        'POST',
        '/v1/blocks',
        body: {'target_id': context.targetId},
      );
      _current();
      if (data['blocked'] != true) _badProjection();
      _candidates = [];
      _relationships = [];
    } finally {
      _finishMutation();
    }
  }

  static const reportCategories = {
    'harassment',
    'threat',
    'impersonation',
    'child_safety',
    'other_safety',
  };
  Future<void> report(MatchSafetyContext context, String category) async {
    _safetyContext(context);
    if (!reportCategories.contains(category))
      throw const IdentityFailure(
        'report_category_required',
        'اختر سبب البلاغ.',
      );
    _lastSafety = context.redacted();
    final intent =
        '${context.targetId}|${context.relationshipId ?? ''}|$category';
    final key = _reportKeys.putIfAbsent(intent, () => _key('report'));
    final data = await client.domain(
      'POST',
      '/v1/reports',
      body: {
        'target_id': context.targetId,
        'category': category,
        if (context.relationshipId != null)
          'relationship_id': context.relationshipId,
      },
      idempotencyKey: key,
    );
    _current();
    if (!_id(data['id'], r'^rpt_[0-9a-f]{32}$') ||
        data['status'] != 'recorded_development_only' ||
        data['evidence_uploaded'] != false)
      _badProjection();
    _reportKeys.remove(intent);
  }

  void close() {
    _closed = true;
    _mutationRevision++;
    _candidates = [];
    _relationships = [];
    _nextRelationshipCursor = null;
    _hasRelationshipPage = false;
    _lastSafety = null;
    _requestKeys.clear();
    _reportKeys.clear();
  }
}
