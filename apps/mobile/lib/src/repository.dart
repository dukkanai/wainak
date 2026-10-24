import 'package:flutter/foundation.dart';

enum RelationshipState {
  none,
  requested,
  acceptedPendingActivation,
  activeCards,
  declined,
  cancelled,
  ended,
  blocked,
}

class JourneyFailure implements Exception {
  const JourneyFailure(this.message);
  final String message;
}

/// Development-only, synchronous seam. A future API adapter must enforce all
/// eligibility, authorization and transitions on the server, not trust this UI.
abstract class JourneyRepository extends ChangeNotifier {
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
  void register({
    required int age,
    required bool adult,
    required bool muslim,
    required bool terms,
    required bool privacy,
  });
  void saveProfile({required String country, required String goal});
  void saveAssessment(String priority);
  void requestRelationship();
  void simulateDecision({required bool accepted});
  void simulateActivation();
  void cancelRequest();
  void sendAnswer(String answer);
  void retryAnswer();
  void setOnline(bool value);
  void block();
  void report(String reason);
  void deleteDemoAccount();
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
  void saveProfile({required String country, required String goal}) {
    _require(registered, 'ابدأ بإقرارات الأهلية.');
    _require(country.isNotEmpty && goal.isNotEmpty, 'اختر البلد والهدف.');
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
    relationship = RelationshipState.none;
    answer = null;
    answerPending = false;
    reports = 0;
    country = goal = priority = null;
    notifyListeners();
  }
}
