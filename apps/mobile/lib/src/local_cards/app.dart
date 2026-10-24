import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../theme.dart';
import 'catalog.dart';
import 'controller.dart';

/// Standalone development surface. It receives no account, relation, client,
/// entitlement, transport or persistence handle. Embedders must explicitly pass
/// visibility/scope changes; dispose alone cannot detect a hidden tab.
class LocalCardsApp extends StatefulWidget {
  const LocalCardsApp({super.key, this.visible = true, this.scopeRevision = 0});
  final bool visible;
  final int scopeRevision;
  @override
  State<LocalCardsApp> createState() => _LocalCardsAppState();
}

class _LocalCardsAppState extends State<LocalCardsApp> {
  final observer = RouteObserver<ModalRoute<dynamic>>();
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: WainakTokens.theme(Brightness.light),
    darkTheme: WainakTokens.theme(Brightness.dark),
    navigatorObservers: [observer],
    home: _LocalCardsHome(
      observer: observer,
      visible: widget.visible,
      scopeRevision: widget.scopeRevision,
    ),
  );
}

class _LocalCardsHome extends StatefulWidget {
  const _LocalCardsHome({
    required this.observer,
    required this.visible,
    required this.scopeRevision,
  });
  final RouteObserver<ModalRoute<dynamic>> observer;
  final bool visible;
  final int scopeRevision;
  @override
  State<_LocalCardsHome> createState() => _LocalCardsHomeState();
}

class _LocalCardsHomeState extends State<_LocalCardsHome>
    with WidgetsBindingObserver, RouteAware {
  final controller = LocalDraftController(sampleLocalCatalog());
  final heading = FocusNode();
  final scroll = ScrollController();
  ModalRoute<dynamic>? route;
  bool accepted = false, resumed = true, routeVisible = true;
  String? error;
  bool get active => widget.visible && resumed && routeVisible;
  @override
  void initState() {
    super.initState();
    resumed =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final current = ModalRoute.of(context);
    if (!identical(current, route)) {
      widget.observer.unsubscribe(this);
      route = current;
      if (current != null) widget.observer.subscribe(this, current);
    }
  }

  @override
  void didUpdateWidget(covariant _LocalCardsHome oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.visible || widget.scopeRevision != oldWidget.scopeRevision)
      _clear(LocalDraftInvalidation.scopeChanged);
  }

  void _clear(LocalDraftInvalidation reason) {
    controller.invalidate(reason);
    accepted = false;
    error = null;
    if (mounted) setState(() {});
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    resumed = state == AppLifecycleState.resumed;
    if (!resumed)
      _clear(LocalDraftInvalidation.background);
    else if (mounted)
      setState(() {});
  }

  @override
  void didPushNext() {
    routeVisible = false;
    _clear(LocalDraftInvalidation.routeCovered);
  }

  @override
  void didPopNext() {
    routeVisible = true;
    _clear(LocalDraftInvalidation.routeCovered);
  }

  @override
  void didPop() {
    _clear(LocalDraftInvalidation.back);
  }

  @override
  void dispose() {
    widget.observer.unsubscribe(this);
    WidgetsBinding.instance.removeObserver(this);
    controller.dispose();
    heading.dispose();
    scroll.dispose();
    super.dispose();
  }

  void action(VoidCallback operation) {
    if (!mounted || !active) return;
    final before = controller.stage;
    setState(() {
      error = null;
      try {
        operation();
      } on LocalDraftFailure {
        error = 'تغير العرض أو لم يكتمل الاختيار. لم نرسل أو نحفظ شيئًا خارج حالة العرض المحلية.';
      }
    });
    final resultingView = controller.viewToken;
    if (before != controller.stage)
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !active || !controller.isCurrentView(resultingView))
          return;
        if (scroll.hasClients) scroll.jumpTo(0);
        heading.requestFocus();
      });
  }

  Widget button(
    String label,
    String key,
    VoidCallback? onPressed, {
    bool secondary = false,
    bool selected = false,
    String? semanticLabel,
  }) => Padding(
    padding: const EdgeInsets.only(top: 12),
    child: Semantics(
      button: true,
      enabled: onPressed != null,
      selected: selected,
      label: semanticLabel ?? label,
      onTap: onPressed,
      child: ExcludeSemantics(
        child: SizedBox(
          width: double.infinity,
          child: secondary
              ? OutlinedButton(
                  key: Key(key),
                  onPressed: onPressed,
                  child: Text(label, textAlign: TextAlign.center),
                )
              : FilledButton(
                  key: Key(key),
                  onPressed: onPressed,
                  child: Text(label, textAlign: TextAlign.center),
                ),
        ),
      ),
    ),
  );
  Widget notice(String text, {Key? key, bool live = false}) => Semantics(
    liveRegion: live,
    child: Padding(
      key: key,
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Text(text),
    ),
  );
  @override
  Widget build(BuildContext context) {
    // Capture the rendered capability, never resolve a fresh one inside callbacks.
    final token = controller.viewToken;
    final stage = controller.stage;
    final acknowledgedInView = accepted;
    final card = controller.card;
    final response = controller.response;
    final title = switch (stage) {
      LocalDraftStage.catalog => 'اختر بطاقة للمعاينة',
      LocalDraftStage.choosing => 'رد مكتوب مسبقًا',
      LocalDraftStage.preview => 'معاينة محلية — لم تُرسل',
      _ => 'تجربة بطاقات محلية فقط',
    };
    return PopScope<void>(
      canPop: stage == LocalDraftStage.locked,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) _clear(LocalDraftInvalidation.back);
      },
      child: Scaffold(
        body: SafeArea(
          child: SingleChildScrollView(
            controller: scroll,
            padding: const EdgeInsets.all(24),
            child: FocusTraversalGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Focus(
                    focusNode: heading,
                    child: Semantics(
                      header: true,
                      child: Text(
                        title,
                        key: const Key('local-cards-heading'),
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                    ),
                  ),
                  notice(
                    'نموذج تطوير مستقل؛ لا حساب أو شريك متصل، ولا إرسال أو دفع أو تفعيل علاقة. ليست قناة محادثة مشفرة.',
                    key: const Key('local-cards-boundary'),
                  ),
                  if (!active)
                    notice(
                      'العرض غير نشط. أزلنا مراجع المسودة المحلية، ولن تعود عند الرجوع.',
                      key: const Key('local-cards-inactive'),
                    )
                  else if (stage == LocalDraftStage.locked) ...[
                    notice(
                      'اختيارك يبقى مؤقتًا في ذاكرة هذا العرض فقط. نمسحه من حالة التطبيق عند الرجوع أو الإخفاء أو مغادرة المقدمة. هذا ليس وعدًا بمحو آمن لذاكرة الجهاز أو منع لقطات النظام.',
                    ),
                    notice(
                      'أربع بطاقات تجريبية بالفصحى، وليست مكتبة نهائية أو مقياس توافق. يمكنك تأجيل السؤال أو الخروج دون رد.',
                    ),
                    CheckboxListTile(
                      key: const Key('local-cards-ack'),
                      contentPadding: EdgeInsets.zero,
                      value: accepted,
                      title: const Text(
                        'أفهم أن هذه معاينة محلية لا تصل إلى أحد',
                      ),
                      onChanged: (value) {
                        if (!active ||
                            controller.stage != LocalDraftStage.locked ||
                            !controller.isCurrentView(token))
                          return;
                        setState(() {
                          controller.clear();
                          accepted = value == true;
                          error = null;
                        });
                      },
                    ),
                    button(
                      'بدء المعاينة المحلية',
                      'local-cards-start',
                      accepted
                          ? () => action(
                              () => controller.start(
                                token,
                                acceptedLocalOnly: acknowledgedInView,
                              ),
                            )
                          : null,
                    ),
                  ] else if (stage == LocalDraftStage.catalog) ...[
                    notice(
                      'اختيار بطاقة لا ينشئ سجلًا. كل رد يُراجع ضمن بطاقته فقط، بلا تقييم أو تشخيص.',
                    ),
                    for (final item in controller.catalog.cards)
                      button(
                        item.title,
                        'local-card-${item.id}',
                        () => action(() => controller.openCard(token, item.id)),
                        secondary: true,
                        semanticLabel: 'معاينة بطاقة ${item.title}',
                      ),
                  ] else if (card != null &&
                      stage == LocalDraftStage.choosing) ...[
                    Semantics(
                      header: true,
                      child: Text(
                        card.title,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                    ),
                    Text(card.prompt),
                    for (final item in card.responses)
                      button(
                        '${response?.id == item.id ? 'اختيارك الحالي: ' : ''}${item.label}',
                        'local-response-${item.id}',
                        () => action(() => controller.choose(token, item.id)),
                        secondary: true,
                        selected: response?.id == item.id,
                        semanticLabel:
                            'اختيار رد في بطاقة ${card.title}: ${item.label}',
                      ),
                    button(
                      'عرض اختياري محليًا فقط',
                      'local-cards-preview',
                      response == null
                          ? null
                          : () => action(() => controller.preview(token)),
                    ),
                    button(
                      'مسح الاختيار واختيار بطاقة أخرى',
                      'local-cards-catalog',
                      () => action(() => controller.returnToCatalog(token)),
                      secondary: true,
                    ),
                  ] else if (card != null &&
                      response != null &&
                      stage == LocalDraftStage.preview) ...[
                    notice(
                      'معاينة محلية — لم تُرسل',
                      key: const Key('local-cards-not-delivered'),
                      live: true,
                    ),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Semantics(
                              header: true,
                              child: Text(
                                card.title,
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                            ),
                            Text(card.prompt),
                            const SizedBox(height: 16),
                            const Text('اختيارك التجريبي:'),
                            Text(
                              response.label,
                              key: const Key('local-cards-preview-response'),
                            ),
                          ],
                        ),
                      ),
                    ),
                    notice(
                      'لا يوجد رد من طرف آخر، أو إيصال تسليم، أو سجل يمكن استرجاعه.',
                    ),
                    button(
                      'مسح الاختيار واختيار بطاقة أخرى',
                      'local-cards-catalog',
                      () => action(() => controller.returnToCatalog(token)),
                      secondary: true,
                    ),
                  ],
                  if (stage != LocalDraftStage.locked)
                    button(
                      'مسح المسودة والرجوع للبداية',
                      'local-cards-clear',
                      () => _clear(LocalDraftInvalidation.cancel),
                      secondary: true,
                    ),
                  if (error != null)
                    notice(
                      error!,
                      key: const Key('local-cards-error'),
                      live: true,
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
