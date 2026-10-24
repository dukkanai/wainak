import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'src/app.dart';
import 'src/repository.dart';
import 'src/theme.dart';

void main() {
  const devEnabled = bool.fromEnvironment('WAINAK_DEV_MODE');
  runApp(
    devEnabled
        ? WainakApp(repository: DevJourneyRepository())
        : const DisabledBuild(),
  );
}

/// Fail closed: the synthetic repository cannot silently become a production app.
class DisabledBuild extends StatelessWidget {
  const DisabledBuild({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: WainakTokens.theme(Brightness.light),
    home: const Scaffold(
      body: SafeArea(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'وينك قيد التطوير. الخدمات الفعلية غير متصلة. هذه النسخة لا تنشئ حسابًا ولا ترسل بيانات.',
          ),
        ),
      ),
    ),
  );
}
