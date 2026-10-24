import 'dart:collection';

/// Static sample copy, not a conversation record or a compatibility assessment.
final class LocalCatalogFailure implements Exception {
  const LocalCatalogFailure();
  @override
  String toString() => 'LocalCatalogFailure';
}

bool _validId(String value) =>
    RegExp(r'^[a-z][a-z0-9_]{1,47}$').firstMatch(value)?.group(0) == value;
bool _validCopy(String value, int max) =>
    value.trim().isNotEmpty &&
    value == value.trim() &&
    value.length <= max &&
    !RegExp(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]').hasMatch(value);
void _require(bool condition) {
  if (!condition) throw const LocalCatalogFailure();
}

enum LocalCardTopic { dailyLife, communication, expectations, privacy }

final class LocalCardResponse {
  LocalCardResponse({required this.id, required this.label}) {
    _require(_validId(id) && _validCopy(label, 120));
  }
  final String id, label;
  @override
  String toString() => 'LocalCardResponse';
}

final class LocalDialogueCard {
  LocalDialogueCard({
    required this.id,
    required this.topic,
    required this.title,
    required this.prompt,
    required List<LocalCardResponse> responses,
  }) : responses = UnmodifiableListView(List<LocalCardResponse>.of(responses)) {
    _require(_validId(id) && _validCopy(title, 80) && _validCopy(prompt, 240));
    _require(this.responses.length >= 2 && this.responses.length <= 5);
    _require(
      this.responses.map((v) => v.id).toSet().length == this.responses.length,
    );
  }
  final String id, title, prompt;
  final LocalCardTopic topic;
  final List<LocalCardResponse> responses;
  @override
  String toString() => 'LocalDialogueCard';
}

final class LocalDialogueCatalog {
  LocalDialogueCatalog({
    required this.version,
    required this.locale,
    required List<LocalDialogueCard> cards,
  }) : cards = UnmodifiableListView(List<LocalDialogueCard>.of(cards)) {
    _require(_validId(version) && locale == 'ar');
    _require(this.cards.isNotEmpty && this.cards.length <= 12);
    _require(this.cards.map((v) => v.id).toSet().length == this.cards.length);
    final responseIds = this.cards
        .expand((v) => v.responses)
        .map((v) => v.id)
        .toList();
    _require(responseIds.toSet().length == responseIds.length);
  }
  final String version, locale;
  final List<LocalDialogueCard> cards;
  @override
  String toString() => 'LocalDialogueCatalog';
}

/// Arabic fusha sample only. Future dialects need explicitly reviewed catalogues;
/// unsupported locales fail closed, with no remote loading or silent fallback.
LocalDialogueCatalog sampleLocalCatalog() => LocalDialogueCatalog(
  version: 'local_cards_v1',
  locale: 'ar',
  cards: [
    LocalDialogueCard(
      id: 'daily_rhythm',
      topic: LocalCardTopic.dailyLife,
      title: 'إيقاع اليوم',
      prompt: 'عند التخطيط لأسبوع مشترك، ما الأسلوب الأقرب لك؟',
      responses: [
        LocalCardResponse(
          id: 'rhythm_plan',
          label: 'أفضل اتفاقًا بسيطًا مسبقًا مع مساحة للتغيير.',
        ),
        LocalCardResponse(
          id: 'rhythm_flexible',
          label: 'أفضل المرونة ومراجعة الخطط حسب ظروف اليوم.',
        ),
        LocalCardResponse(
          id: 'rhythm_discuss',
          label: 'أحتاج أن نتحدث عن الروتين قبل اختيار أسلوب مشترك.',
        ),
        LocalCardResponse(
          id: 'rhythm_defer',
          label: 'أفضل تأجيل هذا السؤال الآن.',
        ),
      ],
    ),
    LocalDialogueCard(
      id: 'different_views',
      topic: LocalCardTopic.communication,
      title: 'اختلاف الرأي',
      prompt: 'عند اختلاف الرأي، ما البداية التي تفضلها؟',
      responses: [
        LocalCardResponse(
          id: 'views_listen',
          label: 'نستمع لكل طرف دون مقاطعة ثم نوضح ما فهمناه.',
        ),
        LocalCardResponse(
          id: 'views_pause',
          label: 'نأخذ وقتًا للهدوء ونتفق على وقت للعودة إلى النقاش.',
        ),
        LocalCardResponse(
          id: 'views_questions',
          label: 'نبدأ بأسئلة هادئة لفهم سبب الاختلاف.',
        ),
        LocalCardResponse(
          id: 'views_defer',
          label: 'أفضل تأجيل هذا السؤال الآن.',
        ),
      ],
    ),
    LocalDialogueCard(
      id: 'daily_responsibilities',
      topic: LocalCardTopic.expectations,
      title: 'المسؤوليات اليومية',
      prompt: 'كيف تفضل مناقشة توزيع المسؤوليات اليومية؟',
      responses: [
        LocalCardResponse(
          id: 'roles_explicit',
          label: 'نوضح التوقعات ونتفق على توزيع قابل للمراجعة.',
        ),
        LocalCardResponse(
          id: 'roles_circumstances',
          label: 'نراعي ظروف كل طرف ونتحدث عند تغيرها.',
        ),
        LocalCardResponse(
          id: 'roles_explore',
          label: 'أحتاج أن أفهم تفاصيل الحياة المشتركة قبل الاتفاق.',
        ),
        LocalCardResponse(
          id: 'roles_defer',
          label: 'أفضل تأجيل هذا السؤال الآن.',
        ),
      ],
    ),
    LocalDialogueCard(
      id: 'private_details',
      topic: LocalCardTopic.privacy,
      title: 'حدود الخصوصية',
      prompt: 'ما الأسلوب الذي تفضله عند مشاركة تفاصيل خاصة؟',
      responses: [
        LocalCardResponse(
          id: 'privacy_agree',
          label: 'نتفق أولًا على ما يناسب مشاركته وما يبقى خاصًا.',
        ),
        LocalCardResponse(
          id: 'privacy_ask',
          label: 'نسأل عن الإذن قبل نقل تفاصيل تخص الطرف الآخر.',
        ),
        LocalCardResponse(
          id: 'privacy_gradual',
          label: 'نتدرج في الحديث ونحترم رغبة كل طرف في التوقف.',
        ),
        LocalCardResponse(
          id: 'privacy_defer',
          label: 'أفضل تأجيل هذا السؤال الآن.',
        ),
      ],
    ),
  ],
);
