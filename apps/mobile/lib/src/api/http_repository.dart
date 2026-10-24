import 'dart:math';
import '../repository.dart';
import 'client.dart';

/// Actual development HTTP orchestration. Never used unless explicitly selected.
/// No peer acceptance, message delivery or verification is invented locally.
class HttpJourneyRepository extends JourneyRepository {
  HttpJourneyRepository(this.api, {DateTime Function()? clock})
    : _clock = clock ?? DateTime.now;
  final WainakApiClient api;
  final DateTime Function() _clock;
  bool _disposed = false;
  String? _email;
  String? _requestKey;
  String? _targetId;
  Map<String, dynamic>? _account;
  Map<String, dynamic>? _assessment;
  CandidateDto? _candidate;
  RelationshipDto? _relation;
  Map<String, dynamic>? _card;
  bool _profileReady = false;
  bool _discoverable = false;
  int _reports = 0;
  @override
  bool get isRemote => true;
  @override
  bool get incomingRequest =>
      _relation?.recipientId == _account?['id'] && _relation != null;
  @override
  bool get canReport => _targetId != null;
  @override
  bool get canActivate =>
      _relation?.initiatorId == _account?['id'] &&
      relationship == RelationshipState.acceptedPendingActivation;
  @override
  bool get registered => _account != null && api.hasSession;
  @override
  bool get emailVerified => _account?['dev_email_verified'] == true;
  @override
  bool get profileSaved => _profileReady;
  @override
  bool get assessmentSaved => _assessment?['complete'] == true;
  @override
  bool get hasCandidate => _candidate != null;
  @override
  bool get online => true; // Not exposed as a connectivity truth in HTTP UI.
  @override
  String get alias => _account?['alias'] as String? ?? 'ملف تطوير';
  @override
  int get age => _account?['age'] as int? ?? 29;
  @override
  String? get answer => null;
  @override
  bool get answerPending => false;
  @override
  int get reports => _reports;
  @override
  String get candidateName =>
      _candidate?.alias ?? _relation?.peer?.alias ?? 'العلاقة التجريبية';
  @override
  String get candidateDetails {
    final c = _candidate ?? _relation?.peer;
    if (c == null) return 'الملف غير متاح.';
    return '${c.age} سنة · ${_countries[c.country] ?? c.country} · ${_marital[c.maritalStatus] ?? c.maritalStatus}';
  }

  static const _countries = {
    'SA': 'السعودية',
    'MA': 'المغرب',
    'AE': 'الإمارات',
  };
  static const _marital = {
    'single': 'غير متزوج',
    'married': 'متزوج',
    'divorced': 'منفصل بالطلاق',
    'widowed': 'أرمل',
  };
  @override
  RelationshipState get relationship => _blocked
      ? RelationshipState.blocked
      : switch (_relation?.status) {
          'requested' => RelationshipState.requested,
          'accepted_pending_activation' =>
            RelationshipState.acceptedPendingActivation,
          'active_cards' => RelationshipState.activeCards,
          'exclusive_cards' => RelationshipState.exclusiveCards,
          'frozen' => RelationshipState.frozen,
          'declined' => RelationshipState.declined,
          'cancelled' => RelationshipState.cancelled,
          'ended' => RelationshipState.ended,
          'blocked' => RelationshipState.blocked,
          _ => RelationshipState.none,
        };
  Map<String, dynamic>? get _question =>
      _assessment?['next_question'] as Map<String, dynamic>?;
  @override
  String get assessmentPrompt =>
      _question?['prompt_ar'] as String? ?? 'اكتملت أسئلة التأمل الذاتي.';
  @override
  List<String> get assessmentOptions =>
      (_question?['options'] as List? ?? []).cast<String>();
  @override
  String get dialoguePrompt =>
      _card?['prompt_ar'] as String? ??
      'لا توجد بطاقة متاحة في الحالة الحالية.';
  @override
  List<String> get dialogueOptions =>
      (_card?['options'] as List? ?? []).cast<String>();
  @override
  String labelForOption(String option) =>
      const {
        'children': 'أرغب في إنجاب أطفال',
        'discuss_together': 'نناقش القرار معًا',
        'prefer_not_to_say': 'أفضل عدم الإجابة الآن',
        'shared_planning': 'تخطيط مشترك',
        'discuss_roles': 'نناقش توزيع الأدوار',
        'not_applicable': 'لا ينطبق الآن',
        'home': 'الحياة المنزلية',
        'work': 'العمل',
        'family': 'الأسرة',
        'quiet_time': 'وقت هادئ للحوار',
        'listen_first': 'الاستماع أولًا',
        'scheduled_talk': 'نحدد موعدًا للنقاش',
      }[option] ??
      option;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> _run(Future<void> Function() operation) async {
    if (_disposed) throw const JourneyFailure('أُغلقت جلسة التطبيق.');
    try {
      await operation();
      if (!_disposed) _notify();
    } on ApiFailure catch (e) {
      if (!api.hasSession && _account != null) {
        _clear();
        _notify();
      }
      throw JourneyFailure(e.message);
    } on FormatException {
      throw const JourneyFailure(
        'استجابة الخدمة غير متوافقة؛ لم نفتح صلاحيات جديدة.',
      );
    } on TypeError {
      throw const JourneyFailure(
        'استجابة الخدمة غير متوافقة؛ لم نفتح صلاحيات جديدة.',
      );
    }
  }

  @override
  Future<void> register({
    required int age,
    required bool adult,
    required bool muslim,
    required bool terms,
    required bool privacy,
  }) => _run(() async {
    if (age < 18 || !(adult && muslim && terms && privacy))
      throw const JourneyFailure('يلزم بلوغ 18 سنة وإكمال الإقرارات.');
    if (registered) throw const JourneyFailure('الجلسة بدأت بالفعل.');
    final now = _clock();
    final birth = DateTime(now.year - age, now.month, now.day);
    _email ??=
        'mobile_${now.microsecondsSinceEpoch}_${Random.secure().nextInt(1 << 30)}@example.invalid';
    final account = await api.register(
      email: _email!,
      birthDate:
          '${birth.year.toString().padLeft(4, '0')}-${birth.month.toString().padLeft(2, '0')}-${birth.day.toString().padLeft(2, '0')}',
      isMuslim: muslim,
      acceptedTerms: terms,
      acknowledgedPrivacy: privacy,
    );
    if (!_disposed) _account = account;
  });
  @override
  Future<void> verifyDevelopmentEmail() => _run(() async {
    await api.verifyEmailSimulation();
    final account = await api.me();
    if (!_disposed) _account = account;
  });
  @override
  Future<void> saveProfile({
    required String country,
    required String goal,
    required bool discoverable,
    int minAge = 18,
    int maxAge = 60,
  }) => _run(() async {
    if (!emailVerified)
      throw const JourneyFailure('نفذ محاكاة التحقق من البريد أولًا.');
    if (minAge < 18 || maxAge < minAge || maxAge > 120)
      throw const JourneyFailure('راجع حدود العمر المفضلة.');
    _profileReady = false;
    await api.saveProfile({
      'gender': 'female',
      'country': _countries.entries.firstWhere((e) => e.value == country).key,
      'marital_status': 'single',
      'declared_wives': 0,
      'marriage_goal': 'build_family',
      'discoverable': discoverable,
    });
    await api.savePreferences({
      'min_age': minAge,
      'max_age': maxAge,
      'countries': <String>[],
      'marital_statuses': ['single', 'divorced', 'widowed'],
    });
    final assessment = await api.assessment();
    if (!_disposed) {
      _profileReady = true;
      _discoverable = discoverable;
      _assessment = assessment;
    }
  });
  @override
  Future<void> saveAssessment(String option) => _run(() async {
    final id = _question?['id'] as String?;
    if (id == null || !assessmentOptions.contains(option))
      throw const JourneyFailure('حدّث السؤال قبل الإجابة.');
    final result = await api.answerAssessment(id, option);
    if (!_disposed) _assessment = result;
    if (assessmentSaved) await refreshCandidate();
  });
  @override
  Future<void> refreshCandidate() => _run(() async {
    // Keep actions bound to one relationship, even after editing preferences.
    if (_blocked) return;
    if (_relation != null) {
      await refreshRelationship();
      return;
    }
    if (!_discoverable) {
      _candidate = null;
      return;
    }
    final result = await api.candidates();
    final items = (result['items'] as List).cast<Map<String, dynamic>>();
    final relationships = await api.relationships();
    final incoming = (relationships['items'] as List)
        .cast<Map<String, dynamic>>()
        .map(RelationshipDto.fromJson)
        .where(
          (r) => r.recipientId == _account?['id'] && r.status == 'requested',
        );
    if (!_disposed) {
      if (_relation != null) {
        _candidate = _relation!.peer;
      } else if (incoming.isNotEmpty) {
        _relation = incoming.first;
        _candidate = _relation!.peer;
      } else {
        _candidate = items.isEmpty ? null : CandidateDto.fromJson(items.first);
      }
      _targetId = _candidate?.id ?? _targetId;
    }
  });
  @override
  Future<void> requestRelationship() => _run(() async {
    if (_candidate == null || relationship != RelationshipState.none)
      throw const JourneyFailure('لا يوجد طلب جديد متاح.');
    _requestKey ??=
        'mobile_${_clock().microsecondsSinceEpoch}_${Random.secure().nextInt(1 << 30)}';
    final result = await api.requestRelationship(_candidate!.id, _requestKey!);
    if (!_disposed) {
      _relation = result;
      _candidate = result.peer;
    }
  });
  @override
  Future<void> refreshRelationship() => _run(() async {
    final id = _relation?.id;
    if (id == null) return;
    final result = await api.relationship(id);
    if (!_disposed) {
      _relation = result;
      _candidate = result.peer;
    }
    if (result.canSendCards)
      await _loadCards();
    else
      _card = null;
  });
  Future<void> _loadCards() async {
    final response = await api.cards(_relation!.id);
    if (response['answers_transport'] != 'not_implemented' ||
        response['server_stores_dialogue_answers'] != false) {
      throw const FormatException('Unsupported card transport');
    }
    final items = (response['items'] as List).cast<Map<String, dynamic>>();
    if (!_disposed) _card = items.isEmpty ? null : items.first;
  }

  @override
  Future<void> respondToIncoming(bool accept) => _run(() async {
    if (!incomingRequest || relationship != RelationshipState.requested)
      throw const JourneyFailure('القرار متاح للطرف المستلم فقط.');
    final result = await api.respond(_relation!.id, accept: accept);
    if (!_disposed) {
      _relation = result;
      _candidate = result.peer;
    }
  });
  @override
  Future<void> simulateActivation() => _run(() async {
    if (!canActivate)
      throw const JourneyFailure('التفعيل متاح لصاحب الطلب المقبول فقط.');
    final result = await api.activateSimulation(_relation!.id);
    if (!_disposed) {
      _relation = result;
      _candidate = result.peer;
    }
    await _loadCards();
  });
  @override
  Future<void> cancelRequest() => _run(() async {
    if (_relation == null) throw const JourneyFailure('لا يوجد طلب.');
    final result = await api.cancelRelationship(_relation!.id);
    if (!_disposed) {
      _relation = result;
      _candidate = result.peer;
    }
  });
  @override
  void simulateDecision({required bool accepted}) =>
      throw const JourneyFailure('القبول قرار الطرف الآخر من جلسته المستقلة.');
  @override
  void sendAnswer(String answer) => throw const JourneyFailure(
    'قناة إرسال إجابات الحوار غير منفذة؛ لم تُرسل إجابة.',
  );
  @override
  void retryAnswer() =>
      throw const JourneyFailure('لا توجد قناة إرسال في هذه المرحلة.');
  @override
  void setOnline(bool value) => throw const JourneyFailure(
    'وضع الخدمة لا يحاكي الاتصال؛ يعرض نتيجة الطلب الفعلية.',
  );
  @override
  Future<void> block() => _run(() async {
    if (_targetId == null)
      throw const JourneyFailure('لا يوجد ملف معروف للحظر.');
    final receipt = await api.block(_targetId!);
    if (receipt['blocked'] != true)
      throw const FormatException('Unexpected block receipt');
    if (!_disposed) {
      _candidate = null;
      _card = null;
      _blocked = true;
      if (_relation != null) _relation = RelationshipDto.blocked(_relation!);
    }
  });
  bool _blocked = false;
  @override
  Future<void> report(String reason) => _run(() async {
    if (_targetId == null)
      throw const JourneyFailure('لا يوجد ملف معروف للإبلاغ.');
    final category = const {
      'تحرش أو إساءة': 'harassment',
      'اشتباه بانتحال هوية': 'impersonation',
      'سلامة طفل أو قاصر': 'child_safety',
    }[reason];
    if (category == null) throw const JourneyFailure('اختر سببًا معروفًا.');
    final receipt = await api.report(
      _targetId!,
      category,
      relationshipId: _relation?.id,
    );
    if (receipt['status'] != 'recorded_development_only' ||
        receipt['evidence_uploaded'] != false)
      throw const FormatException('Unexpected report receipt');
    if (!_disposed) _reports++;
  });
  @override
  Future<void> deleteDemoAccount() => _run(() async {
    await api.deleteAccount();
    if (!_disposed) _clear();
  });
  void _clear() {
    _account = null;
    _assessment = null;
    _candidate = null;
    _relation = null;
    _card = null;
    _targetId = null;
    _email = null;
    _requestKey = null;
    _profileReady = false;
    _discoverable = false;
    _reports = 0;
    _blocked = false;
  }

  @override
  void dispose() {
    _disposed = true;
    api.close();
    super.dispose();
  }
}
