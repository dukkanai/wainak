import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'repository.dart';
import 'theme.dart';

class WainakApp extends StatefulWidget {
  const WainakApp({super.key, required this.repository});
  final JourneyRepository repository;
  @override
  State<WainakApp> createState() => _WainakAppState();
}

class _WainakAppState extends State<WainakApp> {
  ThemeMode mode = ThemeMode.system;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'وينك · تطوير',
    debugShowCheckedModeBanner: false,
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: WainakTokens.theme(Brightness.light),
    darkTheme: WainakTokens.theme(Brightness.dark),
    themeMode: mode,
    home: Journey(
      repository: widget.repository,
      onTheme: () => setState(() {
        mode = mode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
      }),
    ),
  );
}

enum JourneyPage {
  eligibility,
  profile,
  assessment,
  candidate,
  dialogue,
  account,
}

class Journey extends StatefulWidget {
  const Journey({super.key, required this.repository, required this.onTheme});
  final JourneyRepository repository;
  final VoidCallback onTheme;
  @override
  State<Journey> createState() => _JourneyState();
}

class _JourneyState extends State<Journey> {
  JourneyRepository get repo => widget.repository;
  JourneyPage page = JourneyPage.eligibility;
  JourneyPage returnPage = JourneyPage.candidate;
  final ScrollController scroll = ScrollController();
  final FocusNode headingFocus = FocusNode(debugLabel: 'page heading');
  int age = 29;
  bool adult = false, muslim = false, terms = false, privacy = false;
  String country = 'السعودية', goal = 'زواج جاد بعد تعارف منظم';
  String? priority, selection, error;
  String status = '';

  @override
  void initState() {
    super.initState();
    repo.addListener(_changed);
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    repo.removeListener(_changed);
    scroll.dispose();
    headingFocus.dispose();
    super.dispose();
  }

  void go(JourneyPage value) {
    setState(() {
      page = value;
      error = null;
      status = '';
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (scroll.hasClients) scroll.jumpTo(0);
      headingFocus.requestFocus();
    });
  }

  void act(VoidCallback action, {String message = '', JourneyPage? next}) {
    try {
      action();
      if (next != null) {
        go(next);
      } else {
        setState(() {
          error = null;
          status = message;
        });
      }
    } on JourneyFailure catch (failure) {
      setState(() {
        error = failure.message;
      });
    }
  }

  String get title => switch (page) {
    JourneyPage.eligibility => 'بداية واضحة، على مهل',
    JourneyPage.profile => 'ملفك التجريبي',
    JourneyPage.assessment => 'ما الذي يهمك؟',
    JourneyPage.candidate => 'تعارف له معنى',
    JourneyPage.dialogue => 'مساحتك مع عمر',
    JourneyPage.account => 'الحساب والخصوصية',
  };
  void back() => go(switch (page) {
    JourneyPage.account => returnPage,
    JourneyPage.dialogue => JourneyPage.candidate,
    JourneyPage.candidate => JourneyPage.assessment,
    JourneyPage.assessment => JourneyPage.profile,
    _ => JourneyPage.eligibility,
  });

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: page == JourneyPage.eligibility,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) back();
      },
      child: Scaffold(
        appBar: AppBar(
          toolbarHeight: math.max(
            64,
            MediaQuery.textScalerOf(context).scale(24) + 24,
          ),
          title: const Text('وينك'),
          leading: page != JourneyPage.eligibility
              ? IconButton(
                  key: const Key('back'),
                  tooltip: 'العودة',
                  onPressed: back,
                  icon: const BackButtonIcon(),
                )
              : null,
          actions: [
            IconButton(
              key: const Key('theme'),
              tooltip: 'تبديل الوضع الفاتح والداكن',
              onPressed: widget.onTheme,
              icon: const Icon(Icons.contrast),
            ),
            if (repo.registered && page != JourneyPage.account)
              IconButton(
                key: const Key('account'),
                tooltip: 'الحساب والخصوصية',
                icon: const Icon(Icons.person_outline),
                onPressed: () {
                  returnPage = page;
                  go(JourneyPage.account);
                },
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
                        'نسخة تطوير · بيانات اصطناعية وذاكرة مؤقتة فقط. لا حساب حقيقي أو إرسال أو دفع. لا تدخل معلومات شخصية.',
                      ),
                      const SizedBox(height: 24),
                      Focus(
                        focusNode: headingFocus,
                        child: Semantics(
                          header: true,
                          child: Text(
                            title,
                            key: const Key('page-heading'),
                            style: Theme.of(context).textTheme.headlineMedium,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      ...switch (page) {
                        JourneyPage.eligibility => eligibility(),
                        JourneyPage.profile => profile(),
                        JourneyPage.assessment => assessment(),
                        JourneyPage.candidate => candidate(),
                        JourneyPage.dialogue => dialogue(),
                        JourneyPage.account => account(),
                      },
                      if (error != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 16),
                          child: Notice(
                            error!,
                            error: true,
                            live: true,
                            key: const Key('error'),
                          ),
                        ),
                      if (status.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 16),
                          child: Notice(
                            status,
                            live: true,
                            key: const Key('status'),
                          ),
                        ),
                      const SizedBox(height: 32),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> eligibility() => [
    const Text(
      'وينك للمسلمين البالغين الباحثين عن زواج جاد. العمر والإقرارات هنا محاكاة، وليست إثبات هوية أو تحققًا إنتاجيًا.',
    ),
    const SizedBox(height: 20),
    if (repo.registered) ...[
      const Notice('الجلسة التجريبية بدأت بالفعل؛ بياناتها في الذاكرة فقط.'),
      ActionButton(
        'متابعة الملف',
        'resume-profile',
        () => go(JourneyPage.profile),
      ),
    ] else ...[
      DropdownButtonFormField<int>(
        key: const Key('age'),
        initialValue: age,
        isExpanded: true,
        decoration: const InputDecoration(labelText: 'عمر الشخصية الاصطناعية'),
        items: [17, 18, 29, 45]
            .map((a) => DropdownMenuItem(value: a, child: Text('$a سنة')))
            .toList(),
        onChanged: (value) {
          if (value != null) setState(() => age = value);
        },
      ),
      consent(
        'adult',
        'أقر أن عمري 18 سنة أو أكثر في هذا السيناريو',
        adult,
        (v) => adult = v,
      ),
      consent(
        'muslim',
        'أقر أنني مسلم أو مسلمة في هذا السيناريو',
        muslim,
        (v) => muslim = v,
      ),
      consent(
        'terms',
        'أوافق على قواعد الاستخدام التجريبية',
        terms,
        (v) => terms = v,
      ),
      consent(
        'privacy',
        'اطلعت على بيان الخصوصية التجريبي',
        privacy,
        (v) => privacy = v,
      ),
      TextButton(
        key: const Key('policies'),
        onPressed: policyDialog,
        child: const Text('قراءة قواعد الاستخدام والخصوصية'),
      ),
      ActionButton(
        'ابدأ التجربة',
        'register',
        () => act(
          () => repo.register(
            age: age,
            adult: adult,
            muslim: muslim,
            terms: terms,
            privacy: privacy,
          ),
          next: JourneyPage.profile,
        ),
      ),
    ],
  ];
  Widget consent(
    String id,
    String label,
    bool value,
    ValueChanged<bool> setter,
  ) => CheckboxListTile(
    key: Key(id),
    contentPadding: EdgeInsets.zero,
    title: Text(label),
    value: value,
    controlAffinity: ListTileControlAffinity.leading,
    onChanged: (v) => setState(() => setter(v ?? false)),
  );

  List<Widget> profile() => [
    Panel(
      children: [
        Text('سارة · ${repo.age} سنة · شخصية اصطناعية غير متزوجة'),
        const Text(
          'لا توجد صورة أو بيانات هوية أو معلومات صحية في هذه الشريحة.',
        ),
      ],
    ),
    const SizedBox(height: 20),
    DropdownButtonFormField<String>(
      initialValue: country,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'بلد الإقامة التجريبي'),
      items: [
        'السعودية',
        'المغرب',
        'الإمارات',
      ].map((c) => DropdownMenuItem(value: c, child: Text(c))).toList(),
      onChanged: (v) {
        if (v != null) setState(() => country = v);
      },
    ),
    const SizedBox(height: 16),
    const Text(
      'الهدف: زواج جاد بعد تعارف منظم. تفضيل البداية: حوار بالبطاقات دون كشف صورة.',
    ),
    ActionButton(
      'حفظ ومتابعة',
      'save-profile',
      () => act(
        () =>
            repo.saveProfile(country: country, goal: goal, discoverable: true),
        next: JourneyPage.assessment,
      ),
    ),
  ];

  List<Widget> assessment() => [
    const Text(
      'اختر أولوية لتبدأ بها. هذه خطوة تأمل ذاتي، وليست تحليلًا نفسيًا أو درجة توافق.',
    ),
    const SizedBox(height: 16),
    for (final item in [
      'القيم والأهداف',
      'الأسرة والحدود',
      'التواصل وحل الخلاف',
    ])
      Choice(
        label: item,
        selected: priority == item,
        onTap: () => setState(() => priority = item),
      ),
    ActionButton(
      'متابعة إلى المرشح',
      'save-assessment',
      priority == null
          ? null
          : () => act(
              () => repo.saveAssessment(priority!),
              next: JourneyPage.candidate,
            ),
    ),
  ];

  List<Widget> candidate() => [
    const Panel(
      children: [
        Text(
          'عمر · ملف اصطناعي',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
        ),
        Text('32 سنة · السعودية · غير متزوج'),
        Text('الهدف: زواج جاد، وحوار يحترم الاختلاف والخصوصية.'),
        Text('تجارب التعامل: لا توجد تقييمات كافية.'),
      ],
    ),
    const SizedBox(height: 16),
    const Notice(
      'الصورة والاسم الحقيقي ورقم الهاتف غير مكشوفة. القبول والتفعيل لا يفتحانها، والحصرية قرار آخر مستقل.',
    ),
    const SizedBox(height: 16),
    ...relationshipActions(),
    const SizedBox(height: 24),
    ...safetyActions(),
  ];

  List<Widget> relationshipActions() => switch (repo.relationship) {
    RelationshipState.none => [
      ActionButton(
        'إرسال طلب تعارف',
        'request',
        () => act(
          repo.requestRelationship,
          message: 'أُرسل طلب اصطناعي. ننتظر قرار الطرف الآخر.',
        ),
      ),
    ],
    RelationshipState.requested => [
      const Notice('في انتظار قبول الطرف الآخر؛ الحوار غير مفتوح.'),
      ActionButton(
        'إلغاء الطلب',
        'cancel-request',
        () => act(repo.cancelRequest, message: 'أُلغي الطلب التجريبي.'),
        secondary: true,
      ),
      const Text('أدوات محاكاة للمراجعة فقط — ليست قرارًا نيابة عن شخص حقيقي.'),
      ActionButton(
        'محاكاة قبول الطرف الآخر',
        'accept',
        () => act(() => repo.simulateDecision(accepted: true)),
      ),
      ActionButton(
        'محاكاة رفض الطرف الآخر',
        'decline',
        () => act(() => repo.simulateDecision(accepted: false)),
        secondary: true,
      ),
    ],
    RelationshipState.acceptedPendingActivation => [
      const Notice(
        'قُبل الطلب التجريبي. فتح الحوار خطوة مستقلة عن القبول، ولا يشمل صورة أو حصرية.',
      ),
      const Text(
        'التفعيل الآتي محاكاة بلا سعر أو شراء. ربط الاستحقاقات والمتجر لم يُنفذ.',
      ),
      ActionButton(
        'محاكاة تفعيل حوار البطاقات',
        'activate',
        () => act(repo.simulateActivation, next: JourneyPage.dialogue),
      ),
    ],
    RelationshipState.activeCards => [
      ActionButton(
        'فتح مساحة الحوار',
        'open-dialogue',
        () => go(JourneyPage.dialogue),
      ),
    ],
    RelationshipState.declined => [
      const Notice('لم يُقبل الطلب. لا إعادة طلب ضاغطة، ولم تُكشف معلومات.'),
    ],
    RelationshipState.cancelled => [
      const Notice('أُلغي طلب التعارف. لا يوجد حوار مفتوح.'),
    ],
    RelationshipState.exclusiveCards => [
      const Notice('حصرية مستقلة؛ لا كشف للصورة أو الهوية.'),
    ],
    RelationshipState.frozen => [
      const Notice('العلاقة مجمدة ولا تسمح بإرسال البطاقات.'),
    ],
    RelationshipState.ended => [const Notice('انتهى التعارف.')],
    RelationshipState.blocked => [
      const Notice('العلاقة محظورة. لا حوار أو إرسال أو كشف صورة.'),
    ],
  };

  List<Widget> dialogue() => [
    const Notice(
      'تعارف أولي بالبطاقات فقط · الصورة خاصة · لا حصرية أو موافقة كشف هوية.',
    ),
    const SizedBox(height: 20),
    if (repo.relationship != RelationshipState.activeCards) ...[
      const Notice(
        'الحوار غير متاح في الحالة الحالية. لم تُرسل الإجابات المعلقة.',
      ),
    ] else ...[
      Semantics(
        header: true,
        child: Text(
          'كيف تفضلان مناقشة اختلاف مهم؟',
          style: Theme.of(context).textTheme.titleLarge,
        ),
      ),
      const SizedBox(height: 16),
      if (repo.answer == null) ...[
        for (final item in [
          'نحدد وقتًا هادئًا للحوار',
          'أحتاج وقتًا للتفكير أولًا',
          'نستعين بشخص موثوق عند الحاجة',
        ])
          Choice(
            label: item,
            selected: selection == item,
            onTap: () => setState(() => selection = item),
          ),
        if (selection != null)
          const Notice('تم تحديد الاختيار، ولم يُرسل بعد.', live: true),
        ActionButton(
          'إرسال الإجابة',
          'send',
          selection == null
              ? null
              : () => act(
                  () => repo.sendAnswer(selection!),
                  message: repo.online
                      ? 'تم التسليم في المحاكاة فقط.'
                      : 'على جهازك بانتظار الإرسال.',
                ),
        ),
      ] else ...[
        Panel(
          children: [
            const Text('إجابتك'),
            Text(repo.answer!),
            Text(
              repo.answerPending
                  ? 'على جهازك بانتظار الإرسال'
                  : 'تم التسليم في المحاكاة فقط',
            ),
          ],
        ),
        if (repo.answerPending)
          ActionButton(
            'إعادة محاولة الإرسال',
            'retry',
            !repo.online
                ? null
                : () => act(
                    repo.retryAnswer,
                    message: 'تم التسليم في المحاكاة فقط.',
                  ),
          ),
      ],
      const SizedBox(height: 16),
      SwitchListTile(
        key: const Key('network'),
        contentPadding: EdgeInsets.zero,
        title: const Text('محاكاة توفر الاتصال'),
        subtitle: Text(
          repo.online ? 'متصل في المحاكاة' : 'غير متصل في المحاكاة',
        ),
        value: repo.online,
        onChanged: (v) => act(
          () => repo.setOnline(v),
          message: v
              ? 'عاد الاتصال؛ الإجابة المعلقة تحتاج إعادة محاولة.'
              : 'انقطع الاتصال في المحاكاة.',
        ),
      ),
    ],
    const SizedBox(height: 24),
    ...safetyActions(),
  ];

  List<Widget> safetyActions() => [
    const Text('الحماية متاحة دون اشتراك، حتى بعد الحظر.'),
    ActionButton(
      'الإبلاغ عن هذا الملف',
      'report',
      reportDialog,
      secondary: true,
    ),
    if (repo.relationship != RelationshipState.blocked)
      ActionButton('حظر هذه العلاقة', 'block', blockDialog, secondary: true),
  ];

  List<Widget> account() => [
    const Text(
      'هذا حساب محاكاة على الذاكرة، دون تسجيل دخول أو تخزين أو بيانات حقيقية.',
    ),
    Text('بلاغات اصطناعية في هذه الجلسة: ${repo.reports}'),
    const SizedBox(height: 16),
    const Notice(
      'حذف الحساب ليس إلغاءً للاشتراك. لا اشتراك حقيقي في هذه النسخة؛ إدارة الاشتراك والاستعادة والحذف الخادمي لم تُنفذ.',
    ),
    ActionButton(
      'قواعد الاستخدام والخصوصية',
      'account-policies',
      policyDialog,
      secondary: true,
    ),
    ActionButton(
      'حذف حساب التجربة وبياناته',
      'delete',
      deleteDialog,
      secondary: true,
    ),
  ];

  Future<void> policyDialog() => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      scrollable: true,
      title: const Text('قواعد تجربة التطوير'),
      content: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'هذه ليست الشروط أو سياسة الخصوصية النهائية. لا تستخدم بيانات حقيقية.',
          ),
          SizedBox(height: 16),
          Text(
            'للبالغين المسلمين فقط. يمنع التحرش والاستغلال والابتزاز وانتحال الهوية وأي محتوى يعرّض القاصرين للخطر.',
          ),
          SizedBox(height: 16),
          Text(
            'تبقى بيانات هذه الشريحة في ذاكرة التطبيق وتزول بإغلاقه. لا تُرسل البلاغات أو الإجابات إلى إدارة أو شخص آخر.',
          ),
          SizedBox(height: 16),
          Text(
            'الموافقة على التعارف منفصلة عن الحصرية والصورة والهوية. لا يشتري الدفع موافقة شخص.',
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('إغلاق'),
        ),
      ],
    ),
  );

  Future<bool> confirm(String title, String body, String action) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          scrollable: true,
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('الرجوع'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> blockDialog() async {
    if (await confirm(
      'حظر هذه العلاقة؟',
      'سيُغلق التواصل وتُلغى الإجابة المعلقة. يبقى الإبلاغ متاحًا دون دفع. لا يغير ذلك حالة زواج.',
      'تأكيد الحظر',
    )) {
      if (!mounted) return;
      act(repo.block, message: 'حُظرت العلاقة وأُلغي الإرسال المعلق.');
    }
  }

  Future<void> deleteDialog() async {
    if (await confirm(
      'حذف حساب التجربة؟',
      'ستُمسح بيانات هذه الجلسة الاصطناعية من الذاكرة. هذا ليس طلب حذف خادمي ولا يلغي اشتراك متجر.',
      'تأكيد حذف التجربة',
    )) {
      if (!mounted) return;
      repo.deleteDemoAccount();
      setState(() {
        adult = muslim = terms = privacy = false;
        priority = selection = null;
      });
      go(JourneyPage.eligibility);
    }
  }

  Future<void> reportDialog() async {
    String? reason;
    final result = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          scrollable: true,
          title: const Text('بلاغ سلامة'),
          content: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'اختر سببًا. سيُسجل بلاغ اصطناعي محلي فقط، ولن يصل إلى إدارة.',
              ),
              const SizedBox(height: 16),
              for (final item in [
                'تحرش أو إساءة',
                'اشتباه بانتحال هوية',
                'سلامة طفل أو قاصر',
              ])
                Choice(
                  label: item,
                  selected: reason == item,
                  onTap: () => update(() => reason = item),
                ),
              const Notice(
                'لا تُرفق المحادثة تلقائيًا. معاينة الأدلة وإرفاقها الاختياري (D25) لم تُنفذا؛ هذا البلاغ بلا أدلة.',
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('الرجوع'),
            ),
            FilledButton(
              key: const Key('submit-report'),
              onPressed: reason == null
                  ? null
                  : () => Navigator.pop(context, reason),
              child: const Text('تسجيل بلاغ تجريبي'),
            ),
          ],
        ),
      ),
    );
    if (!mounted || result == null) return;
    act(
      () => repo.report(result),
      message:
          'سُجل البلاغ محليًا للتجربة فقط. لم يصل إلى إدارة ولم تُرفق محادثة.',
    );
  }
}

class ActionButton extends StatelessWidget {
  const ActionButton(
    this.label,
    this.id,
    this.onPressed, {
    super.key,
    this.secondary = false,
  });
  final String label, id;
  final VoidCallback? onPressed;
  final bool secondary;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 16),
    child: secondary
        ? OutlinedButton(
            key: Key(id),
            onPressed: onPressed,
            child: Text(label, textAlign: TextAlign.center),
          )
        : FilledButton(
            key: Key(id),
            onPressed: onPressed,
            child: Text(label, textAlign: TextAlign.center),
          ),
  );
}

class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.error = false, this.live = false});
  final String text;
  final bool error, live;
  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: live,
    child: Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: Theme.of(context).colorScheme.surface,
        border: Border.all(
          color: error
              ? Theme.of(context).colorScheme.error
              : Theme.of(context).colorScheme.outline,
        ),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: error ? Theme.of(context).colorScheme.error : null,
        ),
      ),
    ),
  );
}

class Panel extends StatelessWidget {
  const Panel({super.key, required this.children});
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final child in children)
            Padding(padding: const EdgeInsets.only(bottom: 12), child: child),
        ],
      ),
    ),
  );
}

class Choice extends StatelessWidget {
  const Choice({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Semantics(
      label: label,
      checked: selected,
      inMutuallyExclusiveGroup: true,
      onTap: onTap,
      child: ExcludeSemantics(
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            alignment: AlignmentDirectional.centerStart,
            side: BorderSide(
              color: selected
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).colorScheme.outline,
              width: selected ? 2 : 1,
            ),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                size: 24,
              ),
              const SizedBox(width: 12),
              Expanded(child: Text(label)),
            ],
          ),
        ),
      ),
    ),
  );
}
