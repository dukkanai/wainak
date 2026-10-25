import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../theme.dart';
import 'controller.dart';

bool archiveProbeEnabled({required bool optedIn, required bool release}) =>
    optedIn && !release;

/// Standalone development probe. Not connected to an account or relationship.
class NativeArchiveApp extends StatefulWidget {
  const NativeArchiveApp({super.key, required this.port});
  final ArchiveProbePort port;

  @override
  State<NativeArchiveApp> createState() => _NativeArchiveAppState();
}

class _NativeArchiveAppState extends State<NativeArchiveApp> {
  final observer = RouteObserver<ModalRoute<void>>();

  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: WainakTokens.theme(Brightness.light),
    darkTheme: WainakTokens.theme(Brightness.dark),
    navigatorObservers: [observer],
    home: ArchiveProbeScreen(port: widget.port, observer: observer),
  );
}

class ArchiveProbeScreen extends StatefulWidget {
  const ArchiveProbeScreen({
    super.key,
    required this.port,
    required this.observer,
    this.visible = true,
    this.scope = 'standalone-synthetic',
  });
  final ArchiveProbePort port;
  final RouteObserver<ModalRoute<void>> observer;
  final bool visible;
  final String scope;

  @override
  State<ArchiveProbeScreen> createState() => _ArchiveProbeScreenState();
}

class _ArchiveProbeScreenState extends State<ArchiveProbeScreen>
    with WidgetsBindingObserver, RouteAware {
  late final ArchiveProbeController controller;
  bool _dying = false;
  ModalRoute<void>? _route;

  @override
  void initState() {
    super.initState();
    controller = ArchiveProbeController(
      widget.port,
      onChanged: () {
        if (mounted && !_dying) setState(() {});
      },
    );
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != _route) {
      widget.observer.unsubscribe(this);
      _route = route;
      if (route != null) widget.observer.subscribe(this, route);
    }
  }

  @override
  void didUpdateWidget(ArchiveProbeScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.visible ||
        oldWidget.scope != widget.scope ||
        !identical(oldWidget.port, widget.port)) {
      // This sample never retargets a controller to a replacement engine.
      controller.clear();
    }
    if (!identical(oldWidget.port, widget.port)) controller.dispose();
  }

  @override
  void didPushNext() => controller.clear();
  @override
  void didPop() => controller.clear();
  @override
  void didPopNext() => controller.clear();
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) controller.clear();
  }

  @override
  void dispose() {
    _dying = true;
    widget.observer.unsubscribe(this);
    WidgetsBinding.instance.removeObserver(this);
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final token = controller.viewToken;
    final busy = controller.stage == ArchiveProbeStage.running;
    final enabled =
        widget.visible && controller.stage != ArchiveProbeStage.disposed;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (_, _) => controller.clear(),
      child: Scaffold(
        appBar: AppBar(title: const Text('اختبار الأرشيف المحلي')),
        body: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'تجربة تطوير فقط — بيانات اصطناعية في الذاكرة. ليست محادثة ولا نسخة احتياطية محفوظة.',
                ),
                const SizedBox(height: 16),
                const Text(
                  'تختبر هذه الشاشة محرك Android الأصلي عند توفره. لا حساب متصل، ولا إرسال أو ملف أو رفع سحابي. السجل المستورد غير موثّق المصدر ولا يستعيد الثقة أو صلاحية إرسال الرسائل.',
                ),
                const SizedBox(height: 16),
                CheckboxListTile(
                  key: const ValueKey('archive-ack'),
                  value: controller.consent,
                  onChanged: enabled && !busy
                      ? (value) => controller.acknowledge(token, value == true)
                      : null,
                  title: const Text(
                    'أفهم أن البيانات وهمية وأن الاختبار لا يحفظ نسخة لاستعادتها لاحقًا',
                  ),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                ),
                const SizedBox(height: 16),
                FilledButton(
                  key: const ValueKey('archive-run'),
                  onPressed: enabled && !busy && controller.consent
                      ? () => unawaited(controller.run(token))
                      : null,
                  child: const Text('اختبار تشفير واستيراد وهمي في الذاكرة'),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  key: const ValueKey('archive-clear'),
                  onPressed: controller.clear,
                  child: const Text('إغلاق المعاينة وإلغاء العملية الجارية'),
                ),
                const SizedBox(height: 16),
                Semantics(
                  liveRegion: true,
                  child: Text(_status(), key: const ValueKey('archive-status')),
                ),
                const SizedBox(height: 16),
                const Text(
                  'الخروج أو الانتقال للخلف يزيل المعاينة. إزالة مراجع الذاكرة ليست ضمانًا للمحو الآمن من النظام. لا دليل هنا على تشغيل iOS أو اختبار هاتف ما لم يُنفّذ فعليًا.',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _status() => switch (controller.stage) {
    ArchiveProbeStage.locked => 'لم يبدأ الاختبار. لم يُحفظ أو يُرسل شيء.',
    ArchiveProbeStage.running =>
      'جارٍ طلب الاختبار الأصلي؛ يمكنك إلغاء المعاينة.',
    ArchiveProbeStage.completed =>
      'أعاد المحرك نجاح اختبار سجلّين اصطناعيين. لم يُحفظ ملف ولم تُرسل بيانات. هذا ليس توثيقًا لهوية كاتب السجل.',
    ArchiveProbeStage.disposed => 'أُغلقت المعاينة.',
    ArchiveProbeStage.failed => switch (controller.failure) {
      'unavailable' =>
        'المحرك الأصلي غير متاح في هذه النسخة. لم نستبدله بمحاكاة ناجحة.',
      'timeout' => 'انتهت مهلة الاختبار. لا نجاح مؤكد ولا نسخة محفوظة.',
      'capacity' =>
        'بلغت هذه الجلسة حد التجارب المحلية. أغلق التطبيق وافتحه لبدء جلسة جديدة؛ لم يُحفظ أو يُرسل شيء.',
      'cleanup_unconfirmed' =>
        'تعذّر تأكيد إغلاق المحرك؛ لا يُعتمد الاختبار ناجحًا. أغلق هذه النسخة التجريبية.',
      _ => 'لم يكتمل الاختبار؛ لم نعلن نجاح الاستيراد أو حفظ نسخة.',
    },
  };
}
