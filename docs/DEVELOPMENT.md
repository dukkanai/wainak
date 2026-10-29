# دليل التطوير والاختبارات

هذا الدليل يصف مصدر wainek المجمع. نتيجة التنفيذ في [الحالة الحالية](STATUS.md)، والأوامر التفصيلية لكل مكون في دليله. لا تستخدم قاعدة التشغيل أو بيانات شخصية في الاختبارات.

## هيكل المشروع

- `apps/mobile`: الواجهات العربية وعميل HTTP الأصلي وأوضاع التجربة المنفصلة.
- `backend/wainek`: قواعد النطاق ومحولات الذاكرة وPostgreSQL التجريبية.
- `backend/wainek_identity`: حسابات Django/allauth وجلسات الاختبار والحذف.
- `contracts`: العقود ووسيلة فحص تطابقها مع المصدر.
- `archive` و`archivebridge`: أرشيف تاريخ اصطناعي والجسر المحدود، مع Go modules مثبتة.
- `prototype`: واجهة HTML للمراجعة وليست هدف إنتاج للهاتف.
- `ops`: إدارة PostgreSQL ونسخه واستعادته.
- `ci`: وصفات وضوابط بناء أصلي يدوي، و`qa`: اختبارات مستقلة إضافية.

## الأدوات والتبعيات

تستخدم الاختبارات Python 3.14، وNode 24 للنموذج، وFlutter الموافق لملفات التثبيت الحالية. تثبت حزم Python من `backend/requirements-identity.lock` و`backend/requirements-postgres.txt` مع البصمات، وحزم JavaScript من `prototype/package-lock.json`، وحزم Flutter من `apps/mobile/pubspec.lock`، وGo من ملفات `go.mod` و`go.sum`.

نسخة Go المطلوبة حاليًا 1.27.3. تتطلب اختبارات كاشف السباقات مترجم C مثل GCC ومكتبات تطوير libc؛ توفرها بيئة Ubuntu المستخدمة في CI. لا يفترض اختبار Go أن تنزيل toolchain أحدث مقبول ضمنيًا؛ استخدم الأداة المحددة و`GOTOOLCHAIN=local`. نسخ Apple وFlutter الخاصة ببناء iOS مصدرها `ci/ios-host-pins.json`؛ لا تنقل قبول SDK أو artifact قديم إلى نسخة أخرى دون تحقق.

تشغل الاختبارات محليًا بتوازٍ محدود، وFlutter بـ`--concurrency=1`. حساب CI المستضاف مستقل عن السيرفر ولا يستعمل أسراره. تجهز صور Docker والتبعيات المطلوبة قبل الاختبار؛ مشغلات PostgreSQL المعزولة لا تقبل قاعدة أو DSN إنتاجيًا.

## فحوص سريعة من جذر المستودع

```bash
python3 scripts/check_publication.py
```

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -v
```

```bash
python3 contracts/build_contract.py --check
```

```bash
python3 -m unittest discover -s ops -p 'test_*.py' -v
```

```bash
python3 -m unittest discover -s prototype -p 'test_*.py' -v
```

يفحص `check_publication.py` النسخة المضافة إلى فهرس Git؛ أضف تغييرات المصدر المقصودة قبل استخدامه كفحص للنشر. لا يكتشف كل سر محتمل ولا يغني عن مراجعة الملفات.

## اختبار الهاتف

داخل `apps/mobile`، بعد تجهيز Flutter الصحيح والاعتماديات من القفل:

```bash
flutter analyze --no-pub
```

```bash
flutter test --no-pub --concurrency=1
```

الاختبارات المتصلة تحتاج المشغلات المعزولة وتفعيلها الصريح؛ بعض هذه الاختبارات تتخطى نفسها في التشغيل العادي. لذلك لا يعد نجاح الأمر العام نجاحًا للتكامل الحي. الأوضاع وأوامر التشغيل موثقة في [دليل الهاتف](../apps/mobile/README.md)، واختبار HTTP وقاعدة البيانات في [دليل سلسلة Flutter/PostgreSQL](../backend/integration/FLUTTER_CHAIN.md) و[بروتوكول fixture الهوية](../backend/integration/IDENTITY_PIPE.md).

## فحوص CI المجمعة

الوصفة الحالية تضيف فحوص الخادم والتكامل وFlutter وGo وضوابط البناء إلى الفحوص الأربعة الأصلية. يستخدم `scripts/bootstrap_flutter.py` أداة Flutter المثبتة، ويجمع `scripts/run_flutter_ci.py` فحوصها مع تمييز الاختبارات الافتراضية من الرحلات المتصلة؛ ويجمع `scripts/run_go_checks.py` اختبارات الأرشيف والجسر المستقلة. راجع معاملات هذه الأدوات وملف workflow قبل التشغيل، واستعمل مسار أدوات مملوكًا خارج مصدر المشروع. لا تشغّل بناء Apple أو خدمة إنتاج بمجرد تشغيل الفحوص.

## بقية المكونات

- [اختبارات PostgreSQL المعزولة](../backend/integration/README.md).
- [دليل الهوية والحسابات](../backend/IDENTITY.md).
- [الأرشيف](../archive/README.md) و[الجسر](../archivebridge/README.md).
- [بناء iOS وضوابطه](../ci/README.md).
- [نموذج HTML](../prototype/README.md).
- [التشغيل والاستعادة](server-operations.md).

## الفروع والقبول

يبدأ العمل من `main` المتزامن، داخل فرع قصير العمر، ويدخل عبر طلب دمج. لا تستخدم عشرات worktrees كأرشيف؛ تاريخ Git والتقارير المنقحة يحفظان المصدر والأدلة. تحفظ الأدوات القابلة لإعادة الاستخدام في مكان واحد خارج Git، وتزال المخرجات المؤقتة بعد حفظ ما له قيمة.

يربط القبول بالرأس والأساس والشجرة ونتيجة التشغيل الفعلية. CI ناجح لا يعني جهازًا حقيقيًا أو قبول متجر أو نشر خدمة. راجع [سياسة المستودع](repository-and-ci.md) و[سجل الأدلة التاريخية](history/README.md).
