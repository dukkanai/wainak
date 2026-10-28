import 'dart:convert';
import 'client.dart';

enum ProfileSaveStep { profile, preferences, assessment }

/// Acknowledgement is distinct from observing matching values after uncertainty.
class ProfileSaveReport {
  const ProfileSaveReport({
    required this.stoppedAt,
    required this.profileAcknowledged,
    required this.preferencesAcknowledged,
    this.profileObserved,
    this.preferencesObserved,
  });
  final ProfileSaveStep stoppedAt;
  final bool profileAcknowledged, preferencesAcknowledged;
  final bool? profileObserved, preferencesObserved;

  String get message {
    if (profileAcknowledged && preferencesAcknowledged) {
      return 'أكد الخادم حفظ الملف والتفضيلات، لكن لم نؤكد تحميل الأسئلة. '
          'بقيت اختياراتك؛ لا نكرر أي كتابة تلقائيًا.';
    }
    final parts = <String>['لم يكتمل مسار حفظ الملف والتفضيلات.'];
    if (profileAcknowledged) {
      parts.add('أكد الخادم كتابة الملف.');
    } else if (profileObserved == true) {
      parts.add(
        'آخر قراءة من الخادم تطابق الملف المطلوب، دون تأكيد نتيجة طلب الكتابة.',
      );
    } else if (profileObserved == false) {
      parts.add('آخر قراءة من الخادم لا تطابق الملف المطلوب؛ لم نؤكد الكتابة.');
    } else {
      parts.add('لم نؤكد نتيجة كتابة الملف.');
    }
    if (stoppedAt == ProfileSaveStep.profile) {
      parts.add('لم نرسل طلب حفظ التفضيلات.');
    } else if (preferencesObserved == true) {
      parts.add(
        'آخر قراءة تطابق التفضيلات المطلوبة، دون تأكيد نتيجة طلب كتابتها.',
      );
    } else if (preferencesObserved == false) {
      parts.add('آخر قراءة لا تطابق التفضيلات المطلوبة؛ لم نؤكد كتابتها.');
    } else {
      parts.add('لم نؤكد نتيجة كتابة التفضيلات.');
    }
    parts.add(
      'لم نتراجع عن كتابة مؤكدة ولم نكرر أي كتابة تلقائيًا. '
      'بقيت اختياراتك للمراجعة وإعادة المحاولة الصريحة.',
    );
    return parts.join(' ');
  }
}

class ProfileSaveFailure extends IdentityFailure {
  ProfileSaveFailure(this.report, this.causeCode)
    : super('profile_save_incomplete', report.message);
  final ProfileSaveReport report;
  final String causeCode;
}

Map<String, dynamic> _snapshot(Map<String, dynamic> value) =>
    jsonDecode(jsonEncode(value)) as Map<String, dynamic>;

bool _matches(Object? actual, Object? expected) {
  if (expected is Map) {
    if (actual is! Map) return false;
    return expected.keys.every(
      (key) => actual.containsKey(key) && _matches(actual[key], expected[key]),
    );
  }
  if (expected is List) {
    if (actual is! List || actual.length != expected.length) return false;
    for (var i = 0; i < expected.length; i++) {
      if (!_matches(actual[i], expected[i])) return false;
    }
    return true;
  }
  return actual == expected;
}

/// Sequential writes are NOT a transaction. Failure readback is GET-only and
/// never changes the submitted draft, retries a write, or claims a rollback.
Future<Map<String, dynamic>> saveIdentityProfile(
  IdentityClient client, {
  required Map<String, dynamic> profile,
  required Map<String, dynamic> preferences,
  required bool Function() isCurrent,
}) async {
  final generation = client.sessionGeneration;
  final actor = client.identity?['domain_id'];
  final submittedProfile = _snapshot(profile);
  final submittedPreferences = _snapshot(preferences);
  bool current() =>
      isCurrent() &&
      client.authenticated &&
      client.sessionGeneration == generation &&
      actor is String &&
      client.identity?['domain_id'] == actor;
  void checkCurrent() {
    if (!current()) {
      throw const IdentityFailure(
        'stale_response',
        'تغيرت الجلسة؛ لم نتابع الحفظ ولم نعرض نتيجة الجلسة السابقة.',
      );
    }
  }

  var step = ProfileSaveStep.profile;
  var profileAcknowledged = false, preferencesAcknowledged = false;
  try {
    checkCurrent();
    await client.domain('PUT', '/v1/me/profile', body: submittedProfile);
    checkCurrent();
    profileAcknowledged = true;
    step = ProfileSaveStep.preferences;
    await client.domain(
      'PUT',
      '/v1/me/preferences',
      body: submittedPreferences,
    );
    checkCurrent();
    preferencesAcknowledged = true;
    step = ProfileSaveStep.assessment;
    final assessment = await client.domain('GET', '/v1/me/assessment');
    checkCurrent();
    return assessment;
  } on IdentityFailure catch (failure) {
    // No reconciliation or stale result can cross an account/session change.
    if (!current()) rethrow;
    bool? profileObserved, preferencesObserved;
    try {
      final stored = await client.domain('GET', '/v1/me');
      checkCurrent();
      if (stored['id'] == actor) {
        profileObserved = _matches(stored['profile'], submittedProfile);
        preferencesObserved = _matches(
          stored['preferences'],
          submittedPreferences,
        );
      }
    } on IdentityFailure {
      checkCurrent();
      // An unavailable readback is uncertainty, never proof of no write.
    }
    checkCurrent();
    throw ProfileSaveFailure(
      ProfileSaveReport(
        stoppedAt: step,
        profileAcknowledged: profileAcknowledged,
        preferencesAcknowledged: preferencesAcknowledged,
        profileObserved: profileObserved,
        preferencesObserved: preferencesObserved,
      ),
      failure.code,
    );
  }
}
