import 'package:flutter/material.dart';
import '../app.dart' show Notice, Panel, ActionButton;
import 'client.dart';
import 'matching_repository.dart';

enum MatchingView { candidates, requests }

class IdentityMatchingPane extends StatefulWidget {
  const IdentityMatchingPane({
    super.key,
    required this.repository,
    required this.view,
    required this.onSessionChanged,
    required this.onRequestCreated,
  });
  final IdentityMatchingRepository repository;
  final MatchingView view;
  final VoidCallback onSessionChanged, onRequestCreated;
  @override
  State<IdentityMatchingPane> createState() => _IdentityMatchingPaneState();
}

class _IdentityMatchingPaneState extends State<IdentityMatchingPane> {
  IdentityMatchingRepository get repository => widget.repository;
  bool busy = false, loaded = false;
  bool loadingMore = false, pageFailed = false;
  String? error;
  String notice = '';
  int _operation = 0;
  @override
  void initState() {
    super.initState();
    loaded =
        widget.view == MatchingView.requests && repository.hasRelationshipPage;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) refresh();
    });
  }

  @override
  void dispose() {
    _operation++;
    super.dispose();
  }

  Future<void> run(
    Future<void> Function() action, {
    String success = '',
    bool marksLoaded = false,
    VoidCallback? onSuccess,
    bool nextPage = false,
  }) async {
    if (busy || !mounted) return;
    final operation = ++_operation;
    setState(() {
      busy = true;
      error = null;
      notice = '';
      loadingMore = nextPage;
      pageFailed = false;
    });
    try {
      await action();
      if (!mounted || operation != _operation) return;
      setState(() {
        notice = success;
        if (marksLoaded) loaded = true;
      });
      onSuccess?.call();
    } on IdentityFailure catch (failure) {
      if (mounted && operation == _operation)
        setState(() {
          error = failure.message;
          pageFailed = nextPage;
        });
    } catch (_) {
      if (mounted && operation == _operation)
        setState(() {
          error = 'لم نؤكد العملية؛ حدّث الحالة دون تكرار تلقائي.';
          pageFailed = nextPage;
        });
    } finally {
      if (mounted && operation == _operation) {
        setState(() {
          busy = false;
          loadingMore = false;
        });
        widget.onSessionChanged();
      }
    }
  }

  void refresh() => run(
    widget.view == MatchingView.candidates
        ? repository.refreshCandidates
        : repository.refreshRelationships,
    marksLoaded: true,
  );
  void loadMore() => run(
    repository.loadNextRelationships,
    success: 'اكتمل تحميل الصفحة التالية من الطلبات.',
    marksLoaded: true,
    nextPage: true,
  );
  Future<bool> confirm(String title, String body, String label) async =>
      await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          scrollable: true,
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(
              key: const Key('matching-dialog-cancel'),
              onPressed: () => Navigator.pop(c, false),
              child: const Text('الرجوع'),
            ),
            FilledButton(
              key: const Key('matching-dialog-confirm'),
              onPressed: () => Navigator.pop(c, true),
              child: Text(label),
            ),
          ],
        ),
      ) ??
      false;
  bool sameContext(IdentityMatchingRepository captured) {
    if (!mounted) return false;
    if (!identical(captured, repository) || !captured.current) {
      setState(
        () => error = 'تغيرت الجلسة؛ افتح تأكيدًا جديدًا من الحساب الحالي.',
      );
      widget.onSessionChanged();
      return false;
    }
    return true;
  }

  Future<void> request(MatchCandidate candidate) async {
    final captured = repository;
    if (!await confirm(
          'إرسال طلب تعارف؟',
          'الطلب يخص ${candidate.alias}، ${candidate.age} سنة، ${country(candidate.country)}. لا يكشف هوية أو صورًا ولا يفتح محادثة أو دفعًا. يلزم قرار مستقل من الطرف الآخر.',
          'تأكيد إرسال الطلب',
        ) ||
        !sameContext(captured))
      return;
    await run(
      () async {
        await captured.request(candidate);
      },
      success: 'أكد خادم الاختبار تسجيل الطلب؛ ما زلنا ننتظر قرار الطرف الآخر.',
      onSuccess: widget.onRequestCreated,
    );
  }

  Future<void> retryRequest(String target) async {
    final captured = repository;
    if (!await confirm(
          'إعادة محاولة الطلب غير المؤكد؟',
          'سنستخدم مرجع الطلب نفسه والطرف نفسه، دون إنشاء نية جديدة أو تبديل الحساب.',
          'إعادة المحاولة بنفس المرجع',
        ) ||
        !sameContext(captured))
      return;
    await run(
      () async {
        await captured.retryRequest(target);
      },
      success: 'أكد الخادم نتيجة الطلب نفسه.',
      onSuccess: widget.onRequestCreated,
    );
  }

  Future<void> relationAction(
    MatchRelationship relation,
    MatchAction action,
  ) async {
    final captured = repository;
    final label = switch (action) {
      MatchAction.accept => 'قبول الطلب',
      MatchAction.decline => 'رفض الطلب',
      MatchAction.cancel => 'إلغاء الطلب',
      MatchAction.end => 'إنهاء التعارف',
      _ => '',
    };
    final description = action == MatchAction.accept
        ? 'هذا قبول لطلب التعارف فقط، وليس كشف صورة أو هوية أو شراءً أو فتح محادثة.'
        : 'يتغير هذا الطلب فقط. يبقى البلاغ والحظر إجراءين مستقلين.';
    if (!await confirm(
          '$label؟',
          'الطرف: ${relation.peer?.alias ?? 'لا نعرض بيانات ملفه'}. $description',
          'تأكيد $label',
        ) ||
        !sameContext(captured))
      return;
    await run(
      () async {
        await captured.act(relation, action);
      },
      success: action == MatchAction.accept
          ? 'أكد الخادم الموافقة المتبادلة. المرحلة التالية غير متاحة؛ لا دفع أو تفعيل أو محادثة هنا.'
          : 'أكد الخادم تحديث حالة الطلب.',
    );
  }

  Future<void> block(MatchSafetyContext target) async {
    final captured = repository;
    if (!await confirm(
          'حظر الطرف المحدد؟',
          'الطرف: ${target.alias ?? 'سياق طلب محفوظ دون بيانات الملف'}. يوقف الحظر التعامل وفق الخادم. لا يُرسل بلاغًا ولا يحتاج اشتراكًا.',
          'تأكيد الحظر',
        ) ||
        !sameContext(captured))
      return;
    await run(
      () => captured.block(target),
      success:
          'أكد خادم الاختبار الحظر. أزلنا بيانات الطرف القديمة؛ يمكنك الإبلاغ بشكل مستقل.',
      onSuccess: () {
        if (mounted) setState(() => loaded = false);
      },
    );
  }

  Future<void> report(MatchSafetyContext target) async {
    final captured = repository;
    final category = await showDialog<String>(
      context: context,
      builder: (_) => _MatchingReportDialog(alias: target.alias),
    );
    if (category == null || !sameContext(captured)) return;
    await run(
      () => captured.report(target, category),
      success:
          'سجّل خادم الاختبار بلاغًا وصفيًا فقط. لا فريق مراجعة حي ولا أدلة أو محتوى محادثة مرفوع. لم نحظر الطرف تلقائيًا.',
    );
  }

  Widget matchingButton(
    String label,
    String key,
    VoidCallback action, {
    bool secondary = false,
    String? semantics,
  }) => Semantics(
    button: true,
    enabled: !busy,
    label: semantics ?? label,
    onTap: busy ? null : action,
    child: ExcludeSemantics(
      child: ActionButton(
        label,
        key,
        busy ? null : action,
        secondary: secondary,
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Semantics(
        header: true,
        child: Text(
          widget.view == MatchingView.candidates
              ? 'ترشيحات الاختبار'
              : 'طلبات التعارف',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      const Notice(
        'بيانات اصطناعية فقط. الترشيح ليس تزكية أو ضمان توافق. لا محادثة أو دفع أو صور أو كشف هوية في هذه المرحلة.',
      ),
      if (busy)
        Notice(
          loadingMore
              ? 'جارٍ تحميل الصفحة التالية؛ تبقى الطلبات المحملة محفوظة.'
              : 'جارٍ التحقق من الخادم؛ لا نكرر الطلب تلقائيًا.',
          key: const Key('matching-busy'),
          live: true,
        ),
      ExcludeFocus(
        excluding: busy,
        child: AbsorbPointer(
          absorbing: busy,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              matchingButton(
                'تحديث الحالة من الخادم',
                'matching-refresh',
                refresh,
                secondary: true,
              ),
              if (!repository.current)
                const Notice(
                  'تغير الحساب؛ أعد فتح هذا القسم من الجلسة الحالية.',
                ),
              if (widget.view == MatchingView.candidates) ...[
                const Text(
                  'تعتمد الترشيحات على الملف والتفضيلات والموافقات والأهلية المتبادلة. نتيجة فارغة لا تكشف سبب عدم ظهور أي شخص.',
                ),
                if (loaded &&
                    !busy &&
                    error == null &&
                    repository.candidates.isEmpty)
                  const Notice(
                    'لا توجد ترشيحات متاحة الآن. لا ننشئ حسابات أو نتائج بديلة.',
                  ),
                if (loaded)
                  for (final entry in repository.candidates.indexed)
                    candidateCard(entry.$2, entry.$1 + 1),
                for (final target in repository.pendingRequestTargets)
                  matchingButton(
                    'إعادة محاولة الطلب غير المؤكد',
                    'matching-retry-$target',
                    () => retryRequest(target),
                    secondary: true,
                  ),
              ] else ...[
                const Text(
                  'كل طلب مرتبط بطرفيه. أزرار الإجراءات مستمدة من حالة الخادم، ويُعاد فحص الصلاحية عند التنفيذ.',
                ),
                if (loaded &&
                    !busy &&
                    error == null &&
                    repository.relationships.isEmpty)
                  const Notice('لا توجد طلبات في جلسة الاختبار الحالية.'),
                if (loaded)
                  for (final entry in repository.relationships.indexed)
                    relationshipCard(entry.$2, entry.$1 + 1),
                if (loaded && repository.hasRelationshipPage)
                  Notice(
                    'عدد الطلبات المحملة: ${repository.relationships.length}. '
                    '${repository.hasMoreRelationships ? 'توجد طلبات أخرى؛ استخدم تحميل المزيد.' : 'اكتمل تحميل الطلبات الحالية.'}',
                    key: const Key('matching-page-status'),
                    live: true,
                  ),
                if (repository.hasMoreRelationships)
                  matchingButton(
                    pageFailed
                        ? 'إعادة محاولة تحميل المزيد من الطلبات'
                        : 'تحميل المزيد من الطلبات',
                    'matching-load-more',
                    loadMore,
                    secondary: true,
                  ),
              ],
              if (repository.lastSafety case final target?) ...[
                const Notice(
                  'يمكنك الإبلاغ عن الطرف المحدد سابقًا من سياقه المحفوظ، حتى بعد الحظر. لا نعرض بيانات ملف محجوب.',
                ),
                matchingButton(
                  'بلاغ من السياق المحفوظ',
                  'matching-last-report',
                  () => report(target),
                  secondary: true,
                ),
              ],
            ],
          ),
        ),
      ),
      if (error != null)
        Notice(
          error!,
          key: const Key('matching-error'),
          error: true,
          live: true,
        ),
      if (notice.isNotEmpty)
        Notice(notice, key: const Key('matching-notice'), live: true),
    ],
  );
  Widget candidateCard(MatchCandidate candidate, int position) => Panel(
    children: [
      Semantics(
        header: true,
        child: Text(
          candidate.alias,
          style: Theme.of(context).textTheme.titleLarge,
        ),
      ),
      Text('${candidate.age} سنة · ${country(candidate.country)}'),
      Text(
        '${marital(candidate.maritalStatus)} · ${candidate.goal == 'build_family' ? 'بناء أسرة' : 'رفقة وزواج جاد'}',
      ),
      const Text('لا توجد بيانات كافية للتقييم؛ لا درجة توافق رقمية.'),
      matchingButton(
        repository.hasPendingRequest(candidate.id)
            ? 'إعادة محاولة الطلب نفسه'
            : 'طلب تعارف جاد',
        'matching-request-${candidate.id}',
        () => request(candidate),
        semantics: 'طلب تعارف مع ${candidate.alias}، الترشيح $position',
      ),
      matchingButton(
        'حظر هذا الطرف',
        'matching-block-${candidate.id}',
        () => block(repository.candidateContext(candidate)),
        secondary: true,
        semantics: 'حظر ${candidate.alias}، الترشيح $position',
      ),
      matchingButton(
        'الإبلاغ عن هذا الطرف',
        'matching-report-${candidate.id}',
        () => report(repository.candidateContext(candidate)),
        secondary: true,
        semantics: 'بلاغ عن ${candidate.alias}، الترشيح $position',
      ),
    ],
  );
  Widget relationshipCard(MatchRelationship relation, int position) => Panel(
    children: [
      Semantics(
        header: true,
        child: Text(
          relation.peer?.alias ?? 'طرف لا تتوفر بيانات ملفه',
          style: Theme.of(context).textTheme.titleLarge,
        ),
      ),
      Text(
        relation.direction == MatchDirection.incoming ? 'طلب وارد' : 'طلب صادر',
      ),
      Text(
        relation.status == 'requested' &&
                relation.direction == MatchDirection.incoming
            ? 'بانتظار قرارك'
            : status(relation.status),
      ),
      if ({
        'accepted_pending_activation',
        'active_cards',
        'exclusive_cards',
        'frozen',
      }.contains(relation.status))
        const Notice(
          'المحادثة والتفعيل غير متاحين في هذه الواجهة. لا نعرض محرر إجابات أو نحفظ محتوى حوار على الخادم.',
        ),
      for (final action in [
        MatchAction.accept,
        MatchAction.decline,
        MatchAction.cancel,
        MatchAction.end,
      ])
        if (relation.can(action))
          matchingButton(
            switch (action) {
              MatchAction.accept => 'قبول الطلب',
              MatchAction.decline => 'رفض الطلب',
              MatchAction.cancel => 'إلغاء الطلب',
              MatchAction.end => 'إنهاء التعارف',
              _ => '',
            },
            'matching-${action.name}-${relation.id}',
            () => relationAction(relation, action),
            secondary: action != MatchAction.accept,
            semantics:
                '${actionLabel(action)}، الطلب $position، ${relation.peer?.alias ?? 'طرف محجوب البيانات'}',
          ),
      if (relation.can(MatchAction.block))
        matchingButton(
          'حظر الطرف في هذا الطلب',
          'matching-block-${relation.id}',
          () => block(repository.relationshipContext(relation)),
          secondary: true,
          semantics:
              'حظر الطرف في الطلب $position، ${relation.peer?.alias ?? 'بيانات محجوبة'}',
        ),
      if (relation.can(MatchAction.report))
        matchingButton(
          'بلاغ عن الطرف في هذا الطلب',
          'matching-report-${relation.id}',
          () => report(repository.relationshipContext(relation)),
          secondary: true,
          semantics:
              'بلاغ عن الطرف في الطلب $position، ${relation.peer?.alias ?? 'بيانات محجوبة'}',
        ),
    ],
  );
  String actionLabel(MatchAction action) => switch (action) {
    MatchAction.accept => 'قبول الطلب',
    MatchAction.decline => 'رفض الطلب',
    MatchAction.cancel => 'إلغاء الطلب',
    MatchAction.end => 'إنهاء التعارف',
    MatchAction.block => 'حظر',
    MatchAction.report => 'بلاغ',
  };
  String country(String code) =>
      const {'SA': 'السعودية', 'MA': 'المغرب', 'AE': 'الإمارات'}[code] ??
      'بلد محفوظ: $code';
  String marital(String value) =>
      const {
        'single': 'غير متزوج',
        'married': 'متزوج',
        'divorced': 'مطلق',
        'widowed': 'أرمل',
      }[value] ??
      'حالة محفوظة';
  String status(String value) => switch (value) {
    'requested' => 'بانتظار قرار الطرف الآخر',
    'accepted_pending_activation' =>
      'اكتملت الموافقة المتبادلة؛ لم تُفتح محادثة',
    'active_cards' ||
    'exclusive_cards' => 'علاقة محفوظة من مرحلة سابقة؛ الحوار غير متاح هنا',
    'frozen' => 'التعامل متوقف حاليًا',
    'declined' => 'لم تكتمل الموافقة المتبادلة',
    'cancelled' => 'أُلغي الطلب',
    'ended' => 'انتهى التعارف',
    'blocked' => 'التعامل محظور',
    _ => 'حالة غير متاحة',
  };
}

class _MatchingReportDialog extends StatefulWidget {
  const _MatchingReportDialog({this.alias});
  final String? alias;
  @override
  State<_MatchingReportDialog> createState() => _MatchingReportDialogState();
}

class _MatchingReportDialogState extends State<_MatchingReportDialog> {
  String? category;
  @override
  Widget build(BuildContext context) => AlertDialog(
    scrollable: true,
    title: const Text('بلاغ مستقل دون حظر'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'الطرف المحدد: ${widget.alias ?? 'سياق محفوظ دون بيانات الملف'}. لا اشتراك مطلوب.',
        ),
        const Text(
          'اختر وصفًا فقط؛ لا تكتب رسائل أو ترفع أدلة. هذا اختبار بلا فريق مراجعة حي.',
        ),
        for (final item in const {
          'harassment': 'مضايقة',
          'threat': 'تهديد',
          'impersonation': 'انتحال',
          'child_safety': 'سلامة طفل أو اشتباه بقاصر',
          'other_safety': 'مشكلة سلامة أخرى',
        }.entries)
          Semantics(
            selected: category == item.key,
            child: TextButton(
              key: Key('matching-category-${item.key}'),
              onPressed: () => setState(() => category = item.key),
              child: Text('${category == item.key ? '✓ ' : ''}${item.value}'),
            ),
          ),
      ],
    ),
    actions: [
      TextButton(
        key: const Key('matching-report-cancel'),
        onPressed: () => Navigator.pop(context),
        child: const Text('الرجوع'),
      ),
      FilledButton(
        key: const Key('matching-report-submit'),
        onPressed: category == null
            ? null
            : () => Navigator.pop(context, category),
        child: const Text('تأكيد البلاغ الوصفي'),
      ),
    ],
  );
}
