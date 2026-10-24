import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import '../app.dart' show Notice, Panel, Choice, ActionButton;
import '../theme.dart';
import 'client.dart';

class IdentityApp extends StatefulWidget {
  const IdentityApp({super.key, required this.client});
  final IdentityClient client;
  @override
  State<IdentityApp> createState() => _IdentityAppState();
}

class _IdentityAppState extends State<IdentityApp> {
  ThemeMode mode = ThemeMode.system;
  @override
  void dispose() {
    widget.client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    debugShowCheckedModeBanner: false,
    title: 'وينك · اختبار الهوية',
    theme: WainakTokens.theme(Brightness.light),
    darkTheme: WainakTokens.theme(Brightness.dark),
    themeMode: mode,
    home: IdentityJourney(
      client: widget.client,
      onTheme: () => setState(
        () => mode = mode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark,
      ),
    ),
  );
}

class IdentityJourney extends StatefulWidget {
  const IdentityJourney({
    super.key,
    required this.client,
    required this.onTheme,
  });
  final IdentityClient client;
  final VoidCallback onTheme;
  @override
  State<IdentityJourney> createState() => _IdentityJourneyState();
}

class _IdentityJourneyState extends State<IdentityJourney> {
  IdentityClient get client => widget.client;
  final email = TextEditingController(),
      password = TextEditingController(),
      code = TextEditingController();
  final heading = FocusNode(debugLabel: 'identity heading');
  final scroll = ScrollController();
  bool creating = false,
      busy = false,
      adult = false,
      muslim = false,
      terms = false,
      privacy = false,
      discoverable = false;
  int age = 29, minAge = 18, maxAge = 60;
  String country = 'SA', notice = '';
  String? error, selected;
  Map<String, dynamic>? assessment;
  bool profileSaved = false, profileLoaded = false;
  Map<String, dynamic> profileData = {
    'gender': 'female',
    'country': 'SA',
    'marital_status': 'single',
    'declared_wives': 0,
    'marriage_goal': 'build_family',
    'discoverable': false,
  };
  Map<String, dynamic> preferenceData = {
    'min_age': 18,
    'max_age': 60,
    'countries': <String>[],
    'marital_statuses': ['single', 'divorced', 'widowed'],
  };
  int _generation = 0;
  @override
  void dispose() {
    _generation++;
    for (final field in [email, password, code]) {
      field.clear();
      field.dispose();
    }
    heading.dispose();
    scroll.dispose();
    super.dispose();
  }

  void resetFields() {
    for (final field in [email, password, code]) {
      field.clear();
    }
    adult = muslim = terms = privacy = discoverable = false;
    age = 29;
    minAge = 18;
    maxAge = 60;
    country = 'SA';
    assessment = null;
    selected = null;
    profileSaved = false;
    profileLoaded = false;
    profileData = {
      'gender': 'female',
      'country': 'SA',
      'marital_status': 'single',
      'declared_wives': 0,
      'marriage_goal': 'build_family',
      'discoverable': false,
    };
    preferenceData = {
      'min_age': 18,
      'max_age': 60,
      'countries': <String>[],
      'marital_statuses': ['single', 'divorced', 'widowed'],
    };
  }

  Future<void> run(
    Future<void> Function() action, {
    String success = '',
  }) async {
    if (busy) return;
    final generation = ++_generation;
    final before = client.stage;
    setState(() {
      busy = true;
      error = null;
      notice = '';
    });
    try {
      await action();
      if (client.authenticated && before != IdentityStage.authenticated)
        await hydrateProfile();
      if (!mounted || generation != _generation) return;
      setState(() {
        notice = success;
        if (client.stage != before) {
          code.clear();
          password.clear();
        }
      });
    } on IdentityFailure catch (failure) {
      if (!mounted || generation != _generation) return;
      setState(() => error = failure.message);
    } on FormatException {
      if (!mounted || generation != _generation) return;
      setState(
        () => error = 'استجابة الملف غير متوافقة؛ لم نعرض بيانات بديلة.',
      );
    } on TypeError {
      if (!mounted || generation != _generation) return;
      setState(
        () => error = 'استجابة الملف غير متوافقة؛ لم نعرض بيانات بديلة.',
      );
    } finally {
      if (mounted && generation == _generation) {
        setState(() {
          busy = false;
          if (client.stage == IdentityStage.signedOut &&
              before != IdentityStage.signedOut)
            resetFields();
        });
        if (client.stage != before) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted) return;
            if (scroll.hasClients) scroll.jumpTo(0);
            heading.requestFocus();
          });
        }
      }
    }
  }

  Future<void> hydrateProfile() async {
    final me = await client.domain('GET', '/v1/me');
    if (me['id'] != client.identity?['domain_id'])
      throw const FormatException('Unrelated profile');
    final profile = me['profile'], preferences = me['preferences'];
    Map<String, dynamic>? loadedProfile, loadedPreferences;
    if (profile != null) {
      if (profile is! Map ||
          profile['country'] is! String ||
          profile['discoverable'] is! bool ||
          profile['gender'] is! String ||
          profile['marital_status'] is! String ||
          profile['declared_wives'] is! int ||
          profile['marriage_goal'] is! String)
        throw const FormatException('Invalid profile');
      loadedProfile = {
        for (final key in [
          'gender',
          'country',
          'marital_status',
          'declared_wives',
          'marriage_goal',
          'discoverable',
        ])
          key: profile[key],
      };
    }
    if (preferences != null) {
      if (preferences is! Map ||
          preferences['min_age'] is! int ||
          preferences['max_age'] is! int ||
          preferences['countries'] is! List ||
          preferences['marital_statuses'] is! List)
        throw const FormatException('Invalid preferences');
      loadedPreferences = {
        for (final key in [
          'min_age',
          'max_age',
          'countries',
          'marital_statuses',
        ])
          key: preferences[key],
      };
    }
    if (!mounted) return;
    if (loadedProfile != null) profileData = loadedProfile;
    if (loadedPreferences != null) preferenceData = loadedPreferences;
    country = profileData['country'] as String;
    discoverable = profileData['discoverable'] as bool;
    minAge = preferenceData['min_age'] as int;
    maxAge = preferenceData['max_age'] as int;
    profileLoaded = true;
  }

  String get title => switch (client.stage) {
    IdentityStage.signedOut =>
      creating ? 'إنشاء حساب اختبار' : 'تسجيل دخول الاختبار',
    IdentityStage.pendingVerification => 'بانتظار إثبات البريد',
    IdentityStage.authenticated => 'حسابك وملفك الاختباري',
  };
  Widget check(
    String id,
    String label,
    bool value,
    ValueChanged<bool> change,
  ) => CheckboxListTile(
    key: Key(id),
    contentPadding: EdgeInsets.zero,
    title: Text(label),
    value: value,
    controlAffinity: ListTileControlAffinity.leading,
    onChanged: busy ? null : (v) => setState(() => change(v ?? false)),
  );
  Widget field(
    String id,
    String label,
    TextEditingController controller, {
    bool secret = false,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 16),
    child: TextField(
      key: Key(id),
      controller: controller,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: false,
      enableIMEPersonalizedLearning: false,
      keyboardType: secret
          ? TextInputType.visiblePassword
          : TextInputType.emailAddress,
      textDirection: TextDirection.ltr,
      readOnly: busy,
      decoration: InputDecoration(labelText: label),
    ),
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      toolbarHeight: math.max(
        64,
        MediaQuery.textScalerOf(context).scale(24) + 24,
      ),
      title: const Text('وينك'),
      actions: [
        IconButton(
          tooltip: 'تبديل الوضع الفاتح والداكن',
          onPressed: widget.onTheme,
          icon: const Icon(Icons.contrast),
        ),
      ],
    ),
    body: SafeArea(
      child: SingleChildScrollView(
        controller: scroll,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Notice(
                    'اختبار هوية محلي · Django/allauth · بيانات example.invalid اصطناعية فقط. لا SMTP أو بريد حقيقي ولا دفع. الجلسة في ذاكرة التطبيق فقط؛ إغلاقه ليس حذفًا للحساب.',
                  ),
                  const SizedBox(height: 24),
                  Focus(
                    focusNode: heading,
                    child: Semantics(
                      header: true,
                      child: Text(
                        title,
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (busy)
                    const Notice(
                      'جارٍ تنفيذ الطلب؛ لا تعِد الإجراء حتى تظهر النتيجة.',
                      key: Key('identity-busy'),
                      live: true,
                    ),
                  ExcludeFocus(
                    excluding: busy,
                    child: AbsorbPointer(
                      absorbing: busy,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          ...switch (client.stage) {
                            IdentityStage.signedOut => signedOut(),
                            IdentityStage.pendingVerification => pending(),
                            IdentityStage.authenticated => signedIn(),
                          },
                        ],
                      ),
                    ),
                  ),
                  if (error != null)
                    Notice(
                      error!,
                      error: true,
                      live: true,
                      key: const Key('identity-error'),
                    ),
                  if (notice.isNotEmpty)
                    Notice(
                      notice,
                      live: true,
                      key: const Key('identity-notice'),
                    ),
                  const SizedBox(height: 32),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
  List<Widget> signedOut() => [
    field('identity-email', 'بريد اختبار example.invalid', email),
    field('identity-password', 'كلمة مرور اختبار فقط', password, secret: true),
    if (creating) ...[
      const Notice(
        '18+ إقرار أهلية وليس توثيق عمر أو هوية. كلمة المرور 12 محرفًا على الأقل وتخضع لفحوص الخادم.',
      ),
      DropdownButtonFormField<int>(
        key: const Key('identity-age'),
        initialValue: age,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'عمر الشخصية الاصطناعية'),
        items: [17, 18, 29, 45]
            .map((v) => DropdownMenuItem(value: v, child: Text('$v سنة')))
            .toList(),
        onChanged: (v) {
          if (v != null) setState(() => age = v);
        },
      ),
      check(
        'identity-adult',
        'أقر أن الشخصية الاختبارية بلغت 18 سنة',
        adult,
        (v) => adult = v,
      ),
      check(
        'identity-muslim',
        'أقر أن الشخصية الاختبارية مسلمة',
        muslim,
        (v) => muslim = v,
      ),
      check(
        'identity-terms',
        'أوافق على شروط الاختبار الموضحة أدناه',
        terms,
        (v) => terms = v,
      ),
      check(
        'identity-privacy',
        'اطلعت على حدود الخصوصية للاختبار',
        privacy,
        (v) => privacy = v,
      ),
    ],
    ActionButton(
      creating ? 'بدء التسجيل والتحقق' : 'تسجيل الدخول',
      'identity-submit',
      () {
        final mail = email.text, secret = password.text;
        password.clear();
        run(
          () => creating
              ? client.signup(
                  email: mail,
                  password: secret,
                  age: age,
                  adult: adult,
                  muslim: muslim,
                  terms: terms,
                  privacy: privacy,
                )
              : client.login(mail, secret),
        );
      },
    ),
    ActionButton(
      creating ? 'لدي حساب اختبار' : 'إنشاء حساب اختبار جديد',
      'identity-toggle',
      () => setState(() {
        creating = !creating;
        resetFields();
        notice = '';
        error = null;
      }),
      secondary: true,
    ),
    ActionButton(
      'حدود الاختبار والخصوصية',
      'identity-policies',
      policies,
      secondary: true,
    ),
  ];
  List<Widget> pending() => [
    const Notice(
      'لم يُمنح وصول للملف بعد. أدخل رمز إثبات البريد من صندوق الاختبار الخاص بالمشغّل فقط. لا توجد خدمة لقراءة الرموز عبر HTTP، ولا يصل بريد حقيقي. الرمز ليس رابط استعادة كلمة المرور.',
    ),
    field('identity-code', 'رمز إثبات بريد الاختبار', code, secret: true),
    ActionButton('التحقق من الرمز', 'identity-verify', () {
      final value = code.text;
      code.clear();
      run(() => client.verify(value));
    }),
    ActionButton(
      'إعادة رمز إلى صندوق الاختبار',
      'identity-resend',
      () => run(
        client.resend,
        success:
            'أكد الخادم إعادة الرمز إلى صندوق الاختبار فقط؛ الرمز السابق لم يعد صالحًا.',
      ),
      secondary: true,
    ),
    ActionButton(
      'تحديث حالة الجلسة',
      'identity-refresh',
      () => run(client.refreshSession),
      secondary: true,
    ),
    ...sessionActions(pending: true),
  ];
  List<Widget> signedIn() {
    if (!profileLoaded)
      return [
        const Notice(
          'لم نحمّل الملف بعد؛ لن نحفظ قيمًا افتراضية فوق ملف موجود.',
        ),
        ActionButton(
          'تحميل الملف الحالي',
          'identity-load-profile',
          () => run(hydrateProfile),
        ),
        ...sessionActions(pending: false),
      ];
    return [
      const Notice(
        'أُثبت الوصول لبريد الاختبار فقط؛ ليس توثيق هوية قانونية أو عمر أو مفاتيح محادثة. لا تفعيل علاقات أو اشتراك أو قناة رسائل في هذا الوضع.',
      ),
      const Text(
        'محرر محدود لبلد الملف والتفضيلات. للحساب الجديد عينة أنثى غير متزوجة؛ عند الدخول نحتفظ بالجنس والحالة والهدف المخزنة دون تغيير صامت.',
      ),
      DropdownButtonFormField<String>(
        key: const Key('identity-country'),
        initialValue: country,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'بلد الملف الاصطناعي'),
        items: [
          const DropdownMenuItem(value: 'SA', child: Text('السعودية')),
          const DropdownMenuItem(value: 'MA', child: Text('المغرب')),
          const DropdownMenuItem(value: 'AE', child: Text('الإمارات')),
          if (!['SA', 'MA', 'AE'].contains(country))
            DropdownMenuItem(
              value: country,
              child: Text('بلد محفوظ: $country'),
            ),
        ],
        onChanged: (v) {
          if (v != null) setState(() => country = v);
        },
      ),
      const SizedBox(height: 16),
      DropdownButtonFormField<int>(
        initialValue: minAge,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'أصغر عمر مفضل'),
        items: ({18, 25, 40, minAge}.toList()..sort())
            .map((v) => DropdownMenuItem(value: v, child: Text('$v سنة')))
            .toList(),
        onChanged: (v) {
          if (v != null) setState(() => minAge = v);
        },
      ),
      const SizedBox(height: 16),
      DropdownButtonFormField<int>(
        initialValue: maxAge,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'أكبر عمر مفضل'),
        items: ({25, 40, 60, maxAge}.toList()..sort())
            .map((v) => DropdownMenuItem(value: v, child: Text('$v سنة')))
            .toList(),
        onChanged: (v) {
          if (v != null) setState(() => maxAge = v);
        },
      ),
      check(
        'identity-discoverable',
        'أسمح بعرض هذا الملف الاصطناعي في اكتشاف الاختبار',
        discoverable,
        (v) => discoverable = v,
      ),
      ActionButton(
        'حفظ الملف والتفضيلات',
        'identity-profile',
        () => run(() async {
          if (minAge > maxAge)
            throw const IdentityFailure(
              'age_range',
              'راجع حدود العمر المفضلة.',
            );
          await client.domain(
            'PUT',
            '/v1/me/profile',
            body: {
              ...profileData,
              'country': country,
              'discoverable': discoverable,
            },
          );
          await client.domain(
            'PUT',
            '/v1/me/preferences',
            body: {...preferenceData, 'min_age': minAge, 'max_age': maxAge},
          );
          final result = await client.domain('GET', '/v1/me/assessment');
          if (!mounted) return;
          assessment = result;
          profileSaved = true;
          selected = null;
        }, success: 'أكد الخادم حفظ الملف والتفضيلات الاصطناعية.'),
      ),
      if (profileSaved) ...questions(),
      ActionButton(
        'التحقق من استمرار الجلسة',
        'identity-refresh',
        () => run(client.refreshSession),
        secondary: true,
      ),
      ...sessionActions(pending: false),
    ];
  }

  List<Widget> questions() {
    if (assessment?['complete'] == true)
      return [
        const Notice(
          'اكتملت أسئلة التأمل الذاتي من الخادم. ليست تشخيصًا أو درجة توافق. واجهة العلاقات غير موصولة بهذا الوضع بعد.',
        ),
      ];
    final question = assessment?['next_question'];
    if (question is! Map ||
        question['id'] is! String ||
        question['prompt_ar'] is! String ||
        question['options'] is! List) {
      return [
        const Notice('لا يوجد سؤال متوافق؛ لم ننشئ إجابة أو سؤالًا بديلًا.'),
      ];
    }
    const labels = {
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
    };
    return [
      Panel(
        children: [
          Text(question['prompt_ar'] as String),
          for (final option
              in (question['options'] as List).whereType<String>())
            Choice(
              label: labels[option] ?? option,
              selected: selected == option,
              onTap: () => setState(() => selected = option),
            ),
          ActionButton(
            'حفظ الإجابة',
            'identity-answer',
            selected == null
                ? null
                : () => run(() async {
                    final result = await client.domain(
                      'POST',
                      '/v1/me/assessment/answers',
                      body: {
                        'question_id': question['id'],
                        'option_id': selected,
                      },
                    );
                    if (!mounted) return;
                    assessment = result;
                    selected = null;
                  }),
          ),
        ],
      ),
    ];
  }

  List<Widget> sessionActions({required bool pending}) => [
    const SizedBox(height: 24),
    ActionButton(
      'تسجيل الخروج',
      'identity-logout',
      () => run(
        () => client.logout(),
        success: 'مُسحت جلسة التطبيق؛ تسجيل الخروج ليس حذفًا للحساب.',
      ),
      secondary: true,
    ),
    if (!pending)
      ActionButton('إبطال جميع جلسات الحساب', 'identity-revoke', () async {
        final generation = client.sessionGeneration;
        if (await confirm(
          'إبطال جميع الجلسات؟',
          'يشمل هذا جلسات الحساب ومسارات التحقق المرتبطة؛ ليس استعادة لمفاتيح محادثة.',
          'تأكيد إبطال الجلسات',
        )) {
          if (!mounted) return;
          await run(
            () async {
              if (generation != client.sessionGeneration)
                throw const IdentityFailure(
                  'actor_changed',
                  'تغيرت الجلسة؛ افتح تأكيدًا جديدًا للحساب الحالي.',
                );
              await client.logout(everywhere: true);
            },
            success: 'أكد الخادم إبطال جلسات الحساب؛ يلزم تسجيل الدخول مجددًا.',
          );
        }
      }, secondary: true),
    ActionButton(
      pending ? 'حذف الحساب المعلّق المملوك' : 'حذف الحساب الاصطناعي',
      'identity-delete',
      deleteAccount,
      secondary: true,
    ),
    ActionButton(
      'حدود الاختبار والخصوصية',
      'identity-policies',
      policies,
      secondary: true,
    ),
  ];
  Future<bool> confirm(String title, String text, String action) async =>
      await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          scrollable: true,
          title: Text(title),
          content: Text(text),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('الرجوع'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;
  Future<void> policies() => showDialog<void>(
    context: context,
    builder: (c) => AlertDialog(
      scrollable: true,
      title: const Text('حدود نسخة الاختبار'),
      content: const Text(
        'هذه شروط اختبار وليست سياسة قانونية معتمدة. الخادم يحتفظ ببيانات اصطناعية وجلسات وموافقات، ولا يرسل بريدًا حقيقيًا. إثبات البريد ليس توثيق هوية أو عمر. حذف الحساب يمحو بياناته الخاصة وفق العقد، لكنه قد يبقي شواهد وعدادات وسجلات اصطناعية محدودة؛ لا ضمان لمحو نسخ احتياطية أو ذاكرة طرف آخر. لا يلغي اشتراك متجر ولا يستعيد محادثات أو مفاتيح. لا فريق بلاغات حي أو رسائل أو دفع هنا.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(c),
          child: const Text('فهمت'),
        ),
      ],
    ),
  );
  Future<void> deleteAccount() async {
    final generation = client.sessionGeneration;
    final label = client.accountLabel ?? 'جلسة اختبار معلقة';
    final submitted = await showDialog<String>(
      context: context,
      builder: (_) => _DeleteIdentityDialog(label: label),
    );
    if (submitted == null || !mounted) return;
    await run(
      () => client.deleteAccount(
        submitted,
        confirmed: true,
        expectedGeneration: generation,
      ),
      success:
          'أكد الخادم محو الهوية والبيانات الخاصة ضمن حدود الاختبار الموضحة؛ لا إلغاء اشتراك ولا ضمان محو كل النسخ.',
    );
  }
}

class _DeleteIdentityDialog extends StatefulWidget {
  const _DeleteIdentityDialog({required this.label});
  final String label;
  @override
  State<_DeleteIdentityDialog> createState() => _DeleteIdentityDialogState();
}

class _DeleteIdentityDialogState extends State<_DeleteIdentityDialog> {
  final secret = TextEditingController();
  bool accepted = false;
  @override
  void dispose() {
    secret.clear();
    secret.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    scrollable: true,
    title: const Text('حذف الحساب الاصطناعي؟'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          'طلب الحذف يخص: ${widget.label}. لا يمنح العرض وحده ملكية الحساب.',
        ),
        const Text(
          'يلزم إثبات كلمة المرور وجلسة حالية. يمحو الخادم الهوية والملف والموافقات والجلسات ضمن حدود الاختبار؛ قد تبقى شواهد وسجلات محدودة. لا يلغي اشتراكًا ولا يمحو ذاكرة الأجهزة أو يستعيد مفاتيح.',
        ),
        TextField(
          key: const Key('identity-delete-password'),
          controller: secret,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          enableIMEPersonalizedLearning: false,
          decoration: const InputDecoration(labelText: 'كلمة مرور الاختبار'),
        ),
        CheckboxListTile(
          key: const Key('identity-delete-confirm'),
          title: const Text('أؤكد طلب حذف هذا الحساب'),
          value: accepted,
          onChanged: (v) => setState(() => accepted = v ?? false),
        ),
      ],
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('الرجوع'),
      ),
      FilledButton(
        key: const Key('identity-delete-submit'),
        onPressed: accepted ? () => Navigator.pop(context, secret.text) : null,
        child: const Text('تأكيد الحذف'),
      ),
    ],
  );
}
