import 'dart:async';
import 'package:flutter/foundation.dart';

enum RelationshipState {
  none,
  requested,
  acceptedPendingActivation,
  activeCards,
  exclusiveCards,
  frozen,
  declined,
  cancelled,
  ended,
  blocked,
}

class JourneyFailure implements Exception {
  const JourneyFailure(this.message);
  final String message;
}

/// Async-capable repository seam. The backend must enforce all
/// eligibility, authorization and transitions on the server, not trust this UI.
abstract class JourneyRepository extends ChangeNotifier {
  bool get isRemote => false;
  bool get incomingRequest => false;
  bool get canActivate =>
      !incomingRequest &&
      relationship == RelationshipState.acceptedPendingActivation;
  FutureOr<void> respondToIncoming(bool accept) =>
      throw const JourneyFailure('لا يوجد طلب وارد متاح.');
  bool get canReport => hasCandidate || relationship != RelationshipState.none;
  bool get emailVerified => registered;
  bool get hasCandidate => profileSaved;
  String get candidateName => 'عمر · ملف اصطناعي';
  String get candidateDetails => '32 سنة · السعودية · غير متزوج';
  String get assessmentPrompt => 'اختر أولوية لتبدأ بها.';
  List<String> get assessmentOptions => [
    'القيم والأهداف',
    'الأسرة والحدود',
    'التواصل وحل الخلاف',
  ];
  String labelForOption(String option) => option;
  String get dialoguePrompt => 'كيف تفضلان مناقشة اختلاف مهم؟';
  List<String> get dialogueOptions => [
    'نحدد وقتًا هادئًا للحوار',
    'أحتاج وقتًا للتفكير أولًا',
    'نستعين بشخص موثوق عند الحاجة',
  ];
  bool get dialogueTransportAvailable => !isRemote;
  FutureOr<void> verifyDevelopmentEmail() {}
  FutureOr<void> refreshCandidate() {}
  FutureOr<void> refreshRelationship() {}
  bool get registered;
  bool get profileSaved;
  bool get assessmentSaved;
  bool get online;
  String get alias;
  int get age;
  RelationshipState get relationship;
  String? get answer;
  bool get answerPending;
  int get reports;
  FutureOr<void> register({
    required int age,
    required bool adult,
    required bool muslim,
    required bool terms,
    required bool privacy,
  });
  FutureOr<void> saveProfile({
    required String country,
    required String goal,
    required bool discoverable,
    int minAge = 18,
    int maxAge = 60,
  });
  FutureOr<void> saveAssessment(String priority);
  FutureOr<void> requestRelationship();
  FutureOr<void> simulateDecision({required bool accepted});
  FutureOr<void> simulateActivation();
  FutureOr<void> cancelRequest();
  FutureOr<void> sendAnswer(String answer);
  FutureOr<void> retryAnswer();
  FutureOr<void> setOnline(bool value);
  FutureOr<void> block();
  FutureOr<void> report(String reason);
  FutureOr<void> deleteDemoAccount();
}

class DevJourneyRepository extends JourneyRepository {
  @override
  bool registered = false;
  @override
  bool profileSaved = false;
  @override
  bool assessmentSaved = false;
  @override
  bool online = true;
  @override
  String get alias => 'سارة · ملف اصطناعي';
  @override
  int age = 29;
  @override
  RelationshipState relationship = RelationshipState.none;
  @override
  String? answer;
  @override
  bool answerPending = false;
  @override
  int reports = 0;
  bool discoverable = false;
  int minAge = 18, maxAge = 60;
  @override
  bool get hasCandidate =>
      profileSaved && discoverable && minAge <= 32 && maxAge >= 32;
  String? country;
  String? goal;
  String? priority;

  void _require(bool condition, String message) {
    if (!condition) throw JourneyFailure(message);
  }

  @override
  void register({
    required int age,
    required bool adult,
    required bool muslim,
    required bool terms,
    required bool privacy,
  }) {
    _require(!registered, 'بدأت الجلسة التجريبية بالفعل.');
    _require(
      age >= 18,
      'وينك للبالغين 18 سنة فأكثر. لا يمكن متابعة هذا السيناريو.',
    );
    _require(
      adult && muslim && terms && privacy,
      'أكمل الإقرارات المطلوبة قبل المتابعة.',
    );
    registered = true;
    this.age = age;
    notifyListeners();
  }

  @override
  void saveProfile({
    required String country,
    required String goal,
    required bool discoverable,
    int minAge = 18,
    int maxAge = 60,
  }) {
    _require(registered, 'ابدأ بإقرارات الأهلية.');
    _require(country.isNotEmpty && goal.isNotEmpty, 'اختر البلد والهدف.');
    _require(
      minAge >= 18 && maxAge >= minAge && maxAge <= 120,
      'راجع حدود العمر المفضلة.',
    );
    this.discoverable = discoverable;
    this.minAge = minAge;
    this.maxAge = maxAge;
    this.country = country;
    this.goal = goal;
    profileSaved = true;
    notifyListeners();
  }

  @override
  void saveAssessment(String priority) {
    _require(profileSaved, 'أكمل الملف التجريبي أولًا.');
    _require(priority.isNotEmpty, 'اختر ما يهمك.');
    this.priority = priority;
    assessmentSaved = true;
    notifyListeners();
  }

  @override
  void requestRelationship() {
    _require(assessmentSaved, 'أكمل خطوة فهم الاحتياج.');
    _require(hasCandidate, 'لا يوجد مرشح متاح لهذه التفضيلات.');
    _require(
      relationship == RelationshipState.none,
      'هذا الطلب غير متاح في الحالة الحالية.',
    );
    relationship = RelationshipState.requested;
    notifyListeners();
  }

  @override
  void simulateDecision({required bool accepted}) {
    _require(
      relationship == RelationshipState.requested,
      'لا يوجد طلب ينتظر القرار.',
    );
    relationship = accepted
        ? RelationshipState.acceptedPendingActivation
        : RelationshipState.declined;
    notifyListeners();
  }

  @override
  void simulateActivation() {
    _require(
      relationship == RelationshipState.acceptedPendingActivation,
      'يلزم قبول الطرف الآخر أولًا.',
    );
    relationship = RelationshipState.activeCards;
    notifyListeners();
  }

  @override
  void cancelRequest() {
    _require(
      relationship == RelationshipState.requested,
      'لا يوجد طلب قابل للإلغاء.',
    );
    relationship = RelationshipState.cancelled;
    notifyListeners();
  }

  @override
  void sendAnswer(String value) {
    _require(
      relationship == RelationshipState.activeCards,
      'الحوار غير متاح لهذه العلاقة.',
    );
    _require(answer == null, 'سجلت هذه الإجابة بالفعل.');
    _require(value.isNotEmpty, 'اختر إجابة أولًا.');
    answer = value;
    answerPending = !online;
    notifyListeners();
  }

  @override
  void retryAnswer() {
    _require(
      relationship == RelationshipState.activeCards,
      'الحوار غير متاح لهذه العلاقة.',
    );
    _require(
      online && answerPending,
      'تحتاج الإجابة المعلقة إلى اتصال قبل المحاولة.',
    );
    answerPending = false;
    notifyListeners();
  }

  @override
  void setOnline(bool value) {
    online = value;
    // Returning online never claims delivery automatically.
    notifyListeners();
  }

  @override
  void block() {
    _require(registered, 'ابدأ جلسة تجربة أولًا.');
    relationship = RelationshipState.blocked;
    // Cancel pending outbox entries; never send after a safety block.
    if (answerPending) answer = null;
    answerPending = false;
    notifyListeners();
  }

  @override
  void report(String reason) {
    _require(registered, 'ابدأ جلسة تجربة أولًا.');
    _require(reason.isNotEmpty, 'اختر سبب البلاغ.');
    // No conversation evidence or personal data leaves this process.
    reports += 1;
    notifyListeners();
  }

  @override
  void deleteDemoAccount() {
    registered = false;
    profileSaved = false;
    assessmentSaved = false;
    online = true;
    age = 29;
    discoverable = false;
    minAge = 18;
    maxAge = 60;
    relationship = RelationshipState.none;
    answer = null;
    answerPending = false;
    reports = 0;
    country = goal = priority = null;
    notifyListeners();
  }
}
