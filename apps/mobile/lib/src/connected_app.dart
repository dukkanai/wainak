import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'app.dart' show Notice, Panel, Choice, ActionButton;
import 'repository.dart';
import 'theme.dart';

class ConnectedWainakApp extends StatefulWidget {
  const ConnectedWainakApp({super.key, required this.repository});
  final JourneyRepository repository;
  @override
  State<ConnectedWainakApp> createState() => _ConnectedWainakAppState();
}

class _ConnectedWainakAppState extends State<ConnectedWainakApp> {
  ThemeMode mode = ThemeMode.system;
  @override
  void dispose() {
    widget.repository.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    debugShowCheckedModeBanner: false,
    title: 'وينك · خدمة تطوير',
    theme: WainakTokens.theme(Brightness.light),
    darkTheme: WainakTokens.theme(Brightness.dark),
    themeMode: mode,
    home: ConnectedJourney(
      repository: widget.repository,
      onTheme: () => setState(
        () => mode = mode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark,
      ),
    ),
  );
}

enum _Step { eligibility, profile, assessment, candidate, dialogue, account }

class ConnectedJourney extends StatefulWidget {
  const ConnectedJourney({
    super.key,
    required this.repository,
    required this.onTheme,
  });
  final JourneyRepository repository;
  final VoidCallback onTheme;
  @override
  State<ConnectedJourney> createState() => _ConnectedJourneyState();
}

class _ConnectedJourneyState extends State<ConnectedJourney> {
  JourneyRepository get repo => widget.repository;
  _Step step = _Step.eligibility, previous = _Step.eligibility;
  final scroll = ScrollController();
  final heading = FocusNode(debugLabel: 'connected heading');
  bool busy = false,
      adult = false,
      muslim = false,
      terms = false,
      privacy = false,
      discoverable = false;
  int age = 29, minAge = 18, maxAge = 60;
  String country = 'السعودية';
  String? selected, error;
  String notice = '';
  @override
  void dispose() {
    scroll.dispose();
    heading.dispose();
    super.dispose();
  }

  void go(_Step next) {
    setState(() {
      step = next;
      selected = null;
      error = null;
      notice = '';
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (scroll.hasClients) scroll.jumpTo(0);
      heading.requestFocus();
    });
  }

  void resetDeclarations() {
    adult = muslim = terms = privacy = discoverable = false;
    age = 29;
    minAge = 18;
    maxAge = 60;
    country = 'السعودية';
    selected = null;
    previous = _Step.eligibility;
  }

  Future<void> run(
    FutureOr<void> Function() action, {
    _Step? next,
    String success = '',
  }) async {
    if (busy) return;
    final hadSession = repo.registered;
    setState(() {
      busy = true;
      error = null;
      notice = '';
    });
    try {
      await action();
      if (!mounted) return;
      if (hadSession && !repo.registered) resetDeclarations();
      if (next != null) go(next);
      setState(() => notice = success);
    } on JourneyFailure catch (e) {
      if (!mounted) return;
      setState(() {
        error = e.message;
        if (hadSession && !repo.registered) {
          resetDeclarations();
          step = _Step.eligibility;
        }
      });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String get title => switch (step) {
    _Step.eligibility => 'بداية مع خدمة التطوير',
    _Step.profile => 'ملف وتفضيلات اصطناعية',
    _Step.assessment => 'نفهم ما يهمك',
    _Step.candidate => 'تعارف له معنى',
    _Step.dialogue => 'بطاقات ${repo.candidateName}',
    _Step.account => 'الحساب والخصوصية',
  };
  void back() {
    if (busy) return;
    go(switch (step) {
      _Step.profile => _Step.eligibility,
      _Step.assessment => _Step.profile,
      _Step.candidate => _Step.assessment,
      _Step.dialogue => _Step.candidate,
      _Step.account => previous,
      _ => _Step.eligibility,
    });
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: step == _Step.eligibility && !busy,
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
        leading: step == _Step.eligibility
            ? null
            : IconButton(
                key: const Key('api-back'),
                tooltip: 'العودة',
                onPressed: busy ? null : back,
                icon: const BackButtonIcon(),
              ),
        actions: [
          IconButton(
            tooltip: 'تبديل الوضع الفاتح والداكن',
            onPressed: widget.onTheme,
            icon: const Icon(Icons.contrast),
          ),
          if (repo.registered && step != _Step.account)
            IconButton(
              key: const Key('api-account'),
              tooltip: 'الحساب والخصوصية',
              icon: const Icon(Icons.person_outline),
              onPressed: busy
                  ? null
                  : () {
                      previous = step;
                      go(_Step.account);
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
                      'وضع خدمة تطوير متصلة · تُرسل بيانات اصطناعية فقط إلى الخادم المحدد. لا بريد أو شراء أو تحقق هوية حقيقي. لا تدخل معلومات شخصية.',
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
                        'جارٍ تنفيذ الطلب. انتظر النتيجة قبل تكرار الإجراء.',
                        live: true,
                        key: Key('api-busy'),
                      ),
                    ExcludeFocus(
                      excluding: busy,
                      child: AbsorbPointer(
                        absorbing: busy,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: switch (step) {
                            _Step.eligibility => eligibility(),
                            _Step.profile => profile(),
                            _Step.assessment => assessment(),
                            _Step.candidate => candidate(),
                            _Step.dialogue => dialogue(),
                            _Step.account => account(),
                          },
                        ),
                      ),
                    ),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: Notice(
                          error!,
                          error: true,
                          live: true,
                          key: const Key('api-error'),
                        ),
                      ),
                    if (notice.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: Notice(
                          notice,
                          live: true,
                          key: const Key('api-status'),
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
    onChanged: (v) => setState(() => change(v ?? false)),
  );
  List<Widget> eligibility() => [
    const Text(
      'ننشئ ملفًا اصطناعيًا ببريد example.invalid مولّد. لا يُرسل بريد، ولا يُعد الإقرار إثباتًا للعمر أو الهوية.',
    ),
    if (repo.registered)
      ActionButton('متابعة الملف', 'api-resume', () => go(_Step.profile))
    else ...[
      const SizedBox(height: 16),
      DropdownButtonFormField<int>(
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
        'api-adult',
        'أقر ببلوغ 18 سنة في هذا السيناريو',
        adult,
        (v) => adult = v,
      ),
      check(
        'api-muslim',
        'أقر بأنني مسلم أو مسلمة في هذا السيناريو',
        muslim,
        (v) => muslim = v,
      ),
      check(
        'api-terms',
        'أوافق على قواعد استخدام التطوير',
        terms,
        (v) => terms = v,
      ),
      check(
        'api-privacy',
        'اطلعت على بيان خصوصية التطوير',
        privacy,
        (v) => privacy = v,
      ),
      ActionButton(
        'قراءة قواعد الاستخدام والخصوصية',
        'api-policies',
        policies,
        secondary: true,
      ),
      ActionButton(
        'إنشاء جلسة اصطناعية',
        'api-register',
        () => run(
          () => repo.register(
            age: age,
            adult: adult,
            muslim: muslim,
            terms: terms,
            privacy: privacy,
          ),
          next: _Step.profile,
        ),
      ),
    ],
  ];
  List<Widget> profile() => [
    Panel(
      children: [
        Text('${repo.alias} · ${repo.age} سنة'),
        const Text(
          'شخصية أنثى غير متزوجة في هذه الشريحة. لا بيانات صحية أو صورة أو اسم حقيقي.',
        ),
      ],
    ),
    if (!repo.emailVerified) ...[
      const Notice(
        'يلزم تحقق بريد تجريبي مستقل. هذا لا يثبت الهوية ولا يرسل رسالة.',
      ),
      ActionButton(
        'محاكاة التحقق من البريد',
        'api-verify',
        () => run(
          repo.verifyDevelopmentEmail,
          success: 'اكتملت محاكاة البريد فقط، لا تحقق الهوية.',
        ),
      ),
    ],
    const SizedBox(height: 16),
    DropdownButtonFormField<String>(
      initialValue: country,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'بلد الإقامة التجريبي'),
      items: [
        'السعودية',
        'المغرب',
        'الإمارات',
      ].map((v) => DropdownMenuItem(value: v, child: Text(v))).toList(),
      onChanged: (v) {
        if (v != null) setState(() => country = v);
      },
    ),
    const SizedBox(height: 16),
    const Text(
      'الهدف: تأسيس أسرة. بلدان الشريك: أي بلد؛ الحالات المفضلة: غير متزوج، مطلق أو أرمل.',
    ),
    const SizedBox(height: 16),
    DropdownButtonFormField<int>(
      initialValue: minAge,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'أصغر عمر مفضل'),
      items: [
        18,
        25,
        40,
      ].map((v) => DropdownMenuItem(value: v, child: Text('$v سنة'))).toList(),
      onChanged: (v) {
        if (v != null) setState(() => minAge = v);
      },
    ),
    const SizedBox(height: 16),
    DropdownButtonFormField<int>(
      initialValue: maxAge,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'أكبر عمر مفضل'),
      items: [
        25,
        40,
        60,
      ].map((v) => DropdownMenuItem(value: v, child: Text('$v سنة'))).toList(),
      onChanged: (v) {
        if (v != null) setState(() => maxAge = v);
      },
    ),
    check(
      'api-discoverable',
      'أسمح بعرض الملف الاصطناعي في اكتشاف خدمة التطوير',
      discoverable,
      (v) => discoverable = v,
    ),
    ActionButton(
      'حفظ الملف والتفضيلات',
      'api-save-profile',
      !repo.emailVerified
          ? null
          : () => run(
              () => repo.saveProfile(
                country: country,
                goal: 'build_family',
                discoverable: discoverable,
                minAge: minAge,
                maxAge: maxAge,
              ),
              next: _Step.assessment,
            ),
    ),
  ];
  List<Widget> assessment() => [
    const Text(
      'أسئلة تأمل ذاتي متفرعة من خدمة التطوير؛ ليست تحليلًا نفسيًا أو درجة توافق.',
    ),
    const SizedBox(height: 16),
    Text(repo.assessmentPrompt, style: Theme.of(context).textTheme.titleLarge),
    for (final option in repo.assessmentOptions)
      Choice(
        label: repo.labelForOption(option),
        selected: selected == option,
        onTap: () => setState(() => selected = option),
      ),
    if (repo.assessmentSaved)
      ActionButton(
        'عرض المرشح المتاح',
        'api-discover',
        () => run(repo.refreshCandidate, next: _Step.candidate),
      )
    else
      ActionButton(
        'حفظ الإجابة والمتابعة',
        'api-assess',
        selected == null
            ? null
            : () => run(() async {
                await repo.saveAssessment(selected!);
                if (!mounted) return;
                go(repo.assessmentSaved ? _Step.candidate : _Step.assessment);
              }),
      ),
  ];
  List<Widget> candidate() => [
    if (repo.hasCandidate && repo.relationship != RelationshipState.blocked)
      Panel(
        children: [
          Text(
            repo.candidateName,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          Text(repo.candidateDetails),
          const Text('هدف جاد للزواج · تجارب التعامل: لا توجد تقييمات كافية.'),
        ],
      ),
    const Notice(
      'الصورة والهوية خاصة. القبول أو التفعيل أو الحصرية لا تكشفها.',
    ),
    if (!repo.hasCandidate && repo.relationship == RelationshipState.none) ...[
      const Notice(
        'لا يوجد مرشح متاح وفق التفضيلات والأهلية الحالية. قد لا توجد ملفات تجريبية أخرى؛ لا ننشئ مرشحًا وهميًا بدل استجابة الخدمة.',
      ),
      ActionButton(
        'تحديث المرشحين',
        'api-refresh-candidates',
        () => run(repo.refreshCandidate),
        secondary: true,
      ),
    ] else
      ...switch (repo.relationship) {
        RelationshipState.none => [
          ActionButton(
            'إرسال طلب تعارف',
            'api-request',
            () => run(
              repo.requestRelationship,
              success: 'سُجل الطلب في خدمة التطوير؛ ننتظر الطرف الآخر.',
            ),
          ),
        ],
        RelationshipState.requested => [
          if (repo.incomingRequest) ...[
            const Notice(
              'طلب وارد إليك من هذا الملف. القبول يخص التعارف فقط ولا يكشف الصورة أو الهوية.',
            ),
            ActionButton(
              'قبول طلب التعارف الوارد',
              'api-accept-incoming',
              () => run(() => repo.respondToIncoming(true)),
            ),
            ActionButton(
              'رفض الطلب الوارد',
              'api-decline-incoming',
              () => run(() => repo.respondToIncoming(false)),
              secondary: true,
            ),
          ] else ...[
            const Notice(
              'في انتظار الطرف الآخر. لا يمكنك قبول الطلب نيابة عنه. يجب أن يقرر من جلسته المستقلة.',
            ),
            ActionButton(
              'إلغاء الطلب',
              'api-cancel',
              () => run(repo.cancelRequest),
              secondary: true,
            ),
          ],
          ActionButton(
            'تحديث حالة الطلب',
            'api-refresh-relation',
            () => run(repo.refreshRelationship),
            secondary: true,
          ),
        ],
        RelationshipState.acceptedPendingActivation => [
          const Notice(
            'قُبل الطلب. التفعيل الآتي محاكاة حق استخدام مستقلة؛ لا شراء ولا كشف صورة.',
          ),
          if (repo.canActivate)
            ActionButton(
              'محاكاة تفعيل البطاقات',
              'api-activate',
              () => run(repo.simulateActivation, next: _Step.dialogue),
            )
          else ...[
            const Notice(
              'ننتظر محاكاة التفعيل من صاحب الطلب؛ لا يمكنك تنفيذها نيابة عنه.',
            ),
            ActionButton(
              'تحديث حالة العلاقة',
              'api-refresh-relation',
              () => run(repo.refreshRelationship),
              secondary: true,
            ),
          ],
        ],
        RelationshipState.activeCards || RelationshipState.exclusiveCards => [
          ActionButton(
            'فتح البطاقات المسموحة',
            'api-open-cards',
            () => run(repo.refreshRelationship, next: _Step.dialogue),
          ),
        ],
        RelationshipState.frozen => [
          const Notice('العلاقة مجمدة. لا إرسال أو كشف.'),
        ],
        RelationshipState.blocked => [
          const Notice('العلاقة محظورة. لا حوار أو كشف. يبقى البلاغ متاحًا.'),
        ],
        RelationshipState.declined => [
          const Notice(
            'رُفض طلب التعارف؛ لم تُفتح البطاقات. لا إعادة طلب ضاغطة.',
          ),
        ],
        RelationshipState.cancelled => [const Notice('أُلغي الطلب.')],
        RelationshipState.ended => [
          const Notice('انتهى التعارف، دون تغيير الحالة الزوجية.'),
        ],
      },
    if (repo.canReport) ...safety(),
  ];
  List<Widget> dialogue() => [
    const Notice(
      'البطاقة التالية من خدمة التطوير. قناة تبادل إجابات الحوار غير منفذة؛ لا حفظ إجابة أو ادعاء تسليم.',
    ),
    if ([
      RelationshipState.activeCards,
      RelationshipState.exclusiveCards,
    ].contains(repo.relationship)) ...[
      const SizedBox(height: 16),
      Text(repo.dialoguePrompt, style: Theme.of(context).textTheme.titleLarge),
      for (final option in repo.dialogueOptions)
        Choice(
          label: repo.labelForOption(option),
          selected: selected == option,
          onTap: () => setState(() => selected = option),
        ),
      if (selected != null)
        const Notice('اختيار محلي للمعاينة فقط؛ لم يُرسل.', live: true),
    ] else
      const Notice('البطاقات غير متاحة في الحالة الحالية.'),
    ActionButton(
      'تحديث صلاحية العلاقة',
      'api-refresh-cards',
      () => run(repo.refreshRelationship),
      secondary: true,
    ),
    if (repo.canReport) ...safety(),
  ];
  List<Widget> safety() => [
    const SizedBox(height: 24),
    const Text('البلاغ والحظر مستقلان ومتاحان دون دفع.'),
    ActionButton('الإبلاغ عن الملف', 'api-report', report, secondary: true),
    if (repo.relationship != RelationshipState.blocked)
      ActionButton('حظر العلاقة', 'api-block', block, secondary: true),
  ];
  List<Widget> account() => [
    const Text(
      'بيانات اصطناعية في خدمة التطوير. حذف الحساب يرسل طلبًا للخدمة ويفسخ الجلسة؛ لا اشتراك حقيقي هنا.',
    ),
    Text('بلاغات سُجلت من هذه الجلسة: ${repo.reports}'),
    const Notice(
      'حذف الحساب لا يلغي اشتراك المتجر ولا يعني انتهاء زواج. لا فريق بلاغات حي في هذه النسخة.',
    ),
    ActionButton(
      'قواعد التطوير والخصوصية',
      'api-account-policies',
      policies,
      secondary: true,
    ),
    ActionButton(
      'حذف الحساب الاصطناعي من الخدمة',
      'api-delete',
      delete,
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
  Future<void> block() async {
    if (await confirm(
      'حظر العلاقة؟',
      'سيمنع الخادم التواصل في الاتجاهين. يبقى الإبلاغ متاحًا.',
      'تأكيد الحظر',
    )) {
      if (!mounted) return;
      await run(repo.block, success: 'أكدت خدمة التطوير الحظر.');
    }
  }

  Future<void> delete() async {
    if (await confirm(
      'حذف الحساب الاصطناعي؟',
      'يحذف هذا الطلب بيانات الحساب الاصطناعي وفق عقد خدمة التطوير، ويبطل الجلسة. لا يلغي اشتراك متجر.',
      'تأكيد الحذف من الخدمة',
    )) {
      if (!mounted) return;
      await run(
        repo.deleteDemoAccount,
        next: _Step.eligibility,
        success: 'أكدت خدمة التطوير حذف الحساب.',
      );
    }
  }

  Future<void> policies() async {
    await confirm(
      'قواعد وخصوصية التطوير',
      'هذه ليست سياسات إطلاق نهائية. للبالغين المسلمين فقط. يمنع التحرش والاستغلال والابتزاز وانتحال الهوية وتعريض القاصرين للخطر. ترسل هذه الشريحة ملفًا وإقرارات وتفضيلات وتأملًا ذاتيًا وطلبات وبلاغات اصطناعية إلى الخدمة المحددة. لا ترسل صورًا أو محادثات أو بيانات حقيقية.',
      'فهمت',
    );
  }

  Future<void> report() async {
    String? reason;
    final result = await showDialog<String>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, update) => AlertDialog(
          scrollable: true,
          title: const Text('بلاغ إلى خدمة التطوير'),
          content: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'سيسجل الخادم بيانات البلاغ الوصفية فقط. ليس هناك فريق مراجعة حي، ولن تُرفق المحادثة أو أدلة تلقائيًا.',
              ),
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
                'إرفاق الأدلة الاختياري D25 يحتاج معاينة وموافقة مستقلة، وهو غير منفذ هنا.',
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('الرجوع'),
            ),
            FilledButton(
              key: const Key('api-submit-report'),
              onPressed: reason == null ? null : () => Navigator.pop(c, reason),
              child: const Text('تسجيل البلاغ بالخدمة'),
            ),
          ],
        ),
      ),
    );
    if (!mounted || result == null) return;
    await run(
      () => repo.report(result),
      success:
          'أكدت خدمة التطوير تسجيل البلاغ دون أدلة. لا ادعاء بمراجعته من إدارة حية.',
    );
  }
}
