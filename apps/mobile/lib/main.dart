import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'src/app.dart';
import 'src/repository.dart';
import 'src/theme.dart';
import 'src/connected_app.dart';
import 'src/api/client.dart';
import 'src/api/http_repository.dart';
import 'src/api/native_factory.dart';
import 'src/identity/client.dart';
import 'src/identity/app.dart';
import 'src/native_archive/app.dart';
import 'src/native_archive/channel.dart';

void main() {
  const devEnabled = bool.fromEnvironment('WAINAK_DEV_MODE');
  const mode = String.fromEnvironment(
    'WAINAK_REPOSITORY',
    defaultValue: 'fake',
  );
  const baseUrl = String.fromEnvironment('WAINAK_API_BASE_URL');
  const iosArchivePreview = bool.fromEnvironment('WAINAK_IOS_ARCHIVE_PREVIEW');
  if (!devEnabled) {
    runApp(const DisabledBuild());
    return;
  }
  if (mode == 'native_archive') {
    if (!nativeArchiveHostAllowed(
      platform: defaultTargetPlatform,
      isWeb: kIsWeb,
      release: kReleaseMode,
      devOptIn: devEnabled,
      iosPreview: iosArchivePreview,
    )) {
      runApp(
        const DisabledBuild(
          message:
              'اختبار الأرشيف يتطلب منصة تطوير مدعومة وموافقة معاينة صريحة على iOS. لا محاكاة ناجحة بديلة ولا حفظ أو إرسال.',
        ),
      );
      return;
    }
    runApp(NativeArchiveApp(port: MethodChannelArchiveProbe()));
    return;
  }
  if (mode == 'fake') {
    runApp(WainakApp(repository: DevJourneyRepository()));
    return;
  }
  if (mode == 'identity') {
    try {
      final client = IdentityClient(
        baseUri: Uri.parse(baseUrl),
        transport: createNativeTransport(timeout: const Duration(seconds: 35)),
      );
      runApp(IdentityApp(client: client));
    } catch (_) {
      runApp(
        const DisabledBuild(
          message:
              'وضع الهوية الاختباري يتطلب عنوان loopback صريحًا ومنصة أصلية. الويب غير مدعوم، ولم نتحول إلى بيانات وهمية.',
        ),
      );
    }
    return;
  }
  if (mode == 'api') {
    try {
      final uri = Uri.parse(baseUrl);
      if (!['127.0.0.1', 'localhost', '::1', '[::1]'].contains(uri.host)) {
        throw ArgumentError('Only explicit loopback development is supported.');
      }
      final api = WainakApiClient(
        baseUri: uri,
        transport: createNativeTransport(),
      );
      runApp(ConnectedWainakApp(repository: HttpJourneyRepository(api)));
      return;
    } catch (_) {
      runApp(
        const DisabledBuild(
          message:
              'تعذر تهيئة اتصال التطوير. يلزم عنوان loopback صريح ومنصة أصلية؛ الويب غير مدعوم لهذا الوضع. لم نتحول إلى بيانات وهمية بصمت.',
        ),
      );
      return;
    }
  }
  runApp(const DisabledBuild(message: 'وضع التطوير غير معروف؛ لم تُفتح جلسة.'));
}

/// Fail closed: the synthetic repository cannot silently become a production app.
class DisabledBuild extends StatelessWidget {
  const DisabledBuild({
    super.key,
    this.message =
        'وينك قيد التطوير. الخدمات الفعلية غير متصلة. هذه النسخة لا تنشئ حسابًا ولا ترسل بيانات.',
  });
  final String message;
  @override
  Widget build(BuildContext context) => MaterialApp(
    locale: const Locale('ar'),
    supportedLocales: const [Locale('ar')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    theme: WainakTokens.theme(Brightness.light),
    home: Scaffold(
      body: SafeArea(
        child: Padding(padding: EdgeInsets.all(24), child: Text(message)),
      ),
    ),
  );
}

/// iOS remains a separate explicit preview until native artifact/device evidence.
bool nativeArchiveHostAllowed({
  required TargetPlatform platform,
  required bool isWeb,
  required bool release,
  required bool devOptIn,
  required bool iosPreview,
}) =>
    archiveProbeEnabled(optedIn: devOptIn, release: release) &&
    !isWeb &&
    (platform == TargetPlatform.android ||
        (platform == TargetPlatform.iOS && iosPreview));
