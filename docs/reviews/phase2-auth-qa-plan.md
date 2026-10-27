# خطة QA مستقلة — المصادقة والجلسات ومقاومة الإساءة والحذف

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

التاريخ: 2026-10-24. الحالة: معايير قبول أولية بانتظار عقد backend الجديد؛
**لا نتيجة نجاح، ولا اعتماد أمني أو إنتاجي**.

## الفصل عن المرحلة الأولى

نتائج المرحلة الأولى ثابتة عند backend59a79ea75fe37daf36bf1f7203140dcad66e3c2f،
mobileefd0421d559af6ee50ce04b887c7c40481d01aa0 وQA6ecb205821b4f96919a1c1cd94a1e2d862b0a7b2.
لا تُنقل تلك النتائج إلى المصادقة الجديدة لمجرد اشتراك الاسم أو قاعدة البيانات.

عمل QA الجديد في /home/chatbot/wainak-dev/qa-auth-phase2،
الفرع dev/phase2-auth-qa-20261024. ملفّات QA فقط؛ لا تعديل لشجرة المطور أوmain،
ولا push/merge/deploy. كل كتابة وأمر Git واختبار كـchatbot.

قبل التشغيل: تثبيت framework versions/lockfile وعقد المسارات والحالات والجلسة،
قراءة مصدر harness، وربط النتائج بـcommit أو inventory ثم إثبات مطابقته للـcommit.
مرشح المطور في /home/chatbot/wainak-dev/backend-auth-phase2، الفرع
 dev/phase2-auth-20261024 من59a79ea. الإصدارات المقترحة: Django5.2.18،
django-allauth65.20.1، Argon2-cffi25.1.0 وpsycopg3.3.6؛ أبلغ المطور أنه تحقق
من provenance في PyPI. لم تُراجع QA بعد lockfile النهائي أو بايتات المكتبات
المثبتة أو إعداداتها؛ لا نسمي هذه الأرقام اختيارًا إنتاجيًا معتمدًا.

## حدود التجربة

- sandbox وfake mail فقط؛ لا SMTP أو بريد فعلي أو staging أو قاعدة قائمة.
- بيانات شخصيات example.invalid اصطناعية. لا حساب أو صلاحية تشغيل حقيقية جديدة.
- tokens/passwords اللازمة لاختبار lifecycle تبقى داخل ذاكرة الاختبار/مخزن
  مؤقت مملوك للتجربة، ولا تدخل أوامر shell أو تقارير أو رسائل أو snapshots.
- لا echo لمحتوى البريد الوهمي أو bearer/reset/verify token عند فشل assertion؛
  تستخدم مقارنة boolean/status ورسالة عامة بدل طباعة السر في operands.
- PostgreSQL جديد disposable فقط، صورة مثبتة موجودة، دون منافذ منشورة،
  وعزل/cleanup مملوك متحقق. schema migration داخل تلك القاعدة الجديدة فقط.
- حد owner عاد1GiB؛ لا compiler Flutter ثقيل أو تغيير موارد/صلاحيات/خدمات
  تلقائي. تنسيق نافذة PG/Python مع المطور قبل التنفيذ.
- أي ادعاء UI أو بريد/عمر/هوية حقيقي أو إنتاج/متجر يحتاج دليله المنفصل.

## قرارات يجب أن يصرح بها العقد

نوع الجلسة (cookie أو bearer)، عمرها وسياسة تجديدها، معنى logout/logout-all،
ما يبطل sessions عند reset/change-password، مدة كل token واستهلاكه، أثر
إعادة التسجيل بعد الحذف، canonicalization للبريد، مفاتيح وحدود rate-limit،
حدود الثقة بالـproxy، نطاق idempotency وتعارض payload، وسياسة حذف البيانات.

لا نخترع مدة احتفاظ إنتاجية: D25 يجيز الإرفاق الاختياري الصريح إلى مخزن أدلة
معزول فقط. لا مدة/أساس قانوني نهائي معتمد. يلزم جدول نوع بيانات/غرض/مدة/
صلاحية وصول/آلية انتهاء ومسوغ الاستثناء، وتبقى سياسة الإنتاج pending.
verification يثبت حيازة البريد فقط؛ reset لاسترجاع الحساب فقط، ولا يسترد
مفاتيح أو تاريخ E2EE ولا يمنح ثقة جهاز جديد ضمنيًا؛ لا تسويق
ولا مشاركة محادثات/أدلة بالبريد. مسار حذف ويب فعلي متطلب إطلاق منفصل،
وليس صفحة سياسة عامة أو أمرًا يجبر المستخدم على إعادة تثبيت التطبيق.

## مصفوفة القبول

P0: تجاوز هوية/أهلية/عزل أو resurrection أو تسرب سر/بيانات أو اتصال فعلي غير
مأذون. P1: خلل lifecycle/race/expiry/replay/throttle/delete أو ادعاء مضلل.
كل صف يبدأ NOT RUN حتى يرتبط باختبار ونسخة ونتيجة فعلية.

| المعرّف | الأولوية | الاختبار/دليل القبول |
|---|---|---|
| A2-ENV-01 | P0 | وضع التطوير صريح، SMTP ممنوع، fake mailbox لا يرسل، ولا fallback إلى DB/config إنتاجية |
| A2-REG-01 | P1 | canonical email موثق، إدخال ناقص/مشوه/طويل مرفوض، التسجيل المتزامن لا ينشئ duplicate identity |
| A2-ELIG-01 | P0 |17/18 والتاريخ غير الصالح/current consent؛ signup أو verify لا يتجاوز أهلية profile/discovery/relationships |
| A2-PASS-01 | P0 | hashing مدعوم بالإطار لا plaintext، validators وحدود إدخال؛ لا كلمات مرور في DB/log/mail/report |
| A2-VERIFY-01 | P0 | token محصور في الغرض والحساب والبريد/الإصدار المقصود؛ لا يُستخدم reset token للتحقق أو العكس |
| A2-EXPIRY-01 | P1 | قبل/عند/بعد حد الانتهاء لكل token/session وفق عقد صريح وساعة اختبار مضبوطة، لا sleeps هشة |
| A2-REPLAY-01 | P0 | replay واستهلاك متزامن عبر اتصالين لا يمنحان وصولًا أو أثرًا جديدًا؛ نتيجة idempotent آمنة إن كانت موثقة |
| A2-SECRET-01 | P0 | سر عشوائي صادر من الخادم، مخزن hash حيث يلزم، لا قبول قيمة يحددها العميل ولا تسرب في الأخطاء/الروابط/السجلات |
| A2-RESET-01 | P0 | reset يغير كلمة المرور للحساب المقصود فقط، لا يغير/يتحقق من البريد ضمنيًا، ويبطل reset القديم |
| A2-LOGIN-01 | P0 | كلمة مرور خاطئة/غير متحقق/محذوف/disabled لا تمنح session؛ البريد وحده ليس هوية مصرحًا بها |
| A2-SESSION-01 | P0 | مقاومة fixation، جلسة جديدة أو rotation موثق بعد انتقال الصلاحية، تجاهل/رفض session ID يختاره العميل |
| A2-REVOKE-01 | P0 | logout/session-specific وlogout-all وreset/change-password حسب العقد؛ session القديمة تفشل بعد إعادة التشغيل |
| A2-RACE-01 | P0 | reset/delete مقابل login/verify/refresh وblock مقابل activation؛ لا resurrect لحساب أو حق ملغى |
| A2-AUTHZ-01 | P0 | جميع الموارد تشتق actor من الجلسة الحالية؛ cross-user/cross-relationship IDs لا تغير حسابًا آخر أو تكشف بياناته |
| A2-CSRF-01 | P0 | حماية CSRF/origin إن كانت cookie auth، Host/proxy trust واضح، لا bypass بتبديل headers أو اختيار auth آخر |
| A2-ENUM-01 | P1 | signup/resend/reset/login لا يكشف وجود البريد في body/status/header؛ timing يراجع دون ادعاء ثبات كامل غير مقاس |
| A2-LIMIT-01 | P1 | حدود rate-limit ذرية عبر عمليات/اتصالات PG مستقلة؛ العدد المقبول لا يتجاوز الحد في race |
| A2-LIMIT-02 | P1 | نطاق الحساب/IP/البريد والفترة واضح؛ لا bypass عبر case/whitespace أو X-Forwarded-For غير موثوق، Retry-After/انتهاء النافذة صحيح |
| A2-REPORT-01 | P1 | idempotency للبلاغ مقيد actor+operation+key+payload؛ إعادة الإرسال لا تضاعف السجل، التعارض مرفوض، ولا كشف نتيجة مستخدم آخر |
| A2-REPORT-02 | P0 | الحظر لا يمنع البلاغ، وthrottle لا يحول البلاغ إلى كشف/تواصل؛ لا محتوى/إرفاق تلقائي أو عقوبة عامة من عداد |
| A2-DELETE-01 | P0 | تأكيد/مصادقة حديثة كما ينص العقد، إلغاء لا يحذف، حذف/إخفاء البيانات المحددة وإبطال الجلسات والtokens |
| A2-DELETE-02 | P0 | الحالة تبقى بعد restart؛ روابط verify/reset المعلقة لا تعيد الحساب؛ إعادة التسجيل لا ترث علاقات/حقوق الحساب المحذوف |
| A2-RETENTION-01 | P1 | سياسة sandbox معلنة وقابلة للفحص تشمل fake mail/tokens/throttles/reports؛ الإنتاج pending إن لم يقرر جدول الاحتفاظ |
| A2-ATOMIC-01 | P1 | rollback لا يترك token مستهلكًا مع أثر ناقص أو session صالحة بعد delete/reset فاشل؛ constraints تمنع التكرار |
| A2-MAIL-01 | P1 | فشل fake delivery/resend موثق ومتسق بلا سر في الخطأ؛ لا links خارج allowlist أو بريد فيه بيانات حساسة |
| A2-PG-01 | P1 | اختبارات فعلية لـpersistence/constraints/rollback/races وحذف القاعدة والموارد المؤقتة بعد النجاح والفشل |
| A2-CLIENT-01 | P1 | لا نقل نتيجة backend إلى UI غير مربوط؛ أي adapter/واجهة جديدة تحتاج جلسات قديمة/إلغاء/انقطاع واختبارات نسخة مستقلة |
| A2-CLAIM-01 | P1 | لا ادعاء SMTP/هوية/عمر فعلي/متجر/إنتاج أو سياسات احتفاظ نهائية من نجاح sandbox |

## التنفيذ والتقرير

1. مراجعة خطة backend وإضافة العقد والإصدارات الدقيقة لهذه الخطة أو ملحقها.
2. فحص مصدر auth/settings/models/migrations/transport/harness دون قراءة .env.
3. تشغيل مجموعة المطور على نسخة مثبتة، ثم اختبارات خصومية مستقلة في QA فقط.
4. اختبارات التزامن تستخدم اتصالين/عمليتين فعليتين حيث يُدّعى ضمان DB،
   ولا تستبدل ذلك بقفل Python واحد أو mock.
5. تسجل PASS/FAIL/NOT RUN، عدد الحالات وحدودها، الأمر والبيئة وSHA والخروج،
   مع تفسير fixture failure بدل نسبته للتطبيق.
6. إرسال P0/P1 فورًا، إعادة فحص commit الإصلاح، وفحص cleanup/provenance.
7. عدم إغلاق المراجعة على خطة أو suite معلقة؛ انتظار المرشح/الإصلاح جزء من العمل.

مصادر قرارات سياسة الحذف التي نقلها مراجع المتاجر:
- https://support.google.com/googleplay/android-developer/answer/13327111
- https://developer.apple.com/help/app-review/guideline-reference/5-1-1-account-deletion

هذه المراجع ليست إثبات امتثال التنفيذ، ولم يتغير قرار الإطلاق بسبب هذه الخطة.

## محور خاص بموائم SessionStore المقترح

يقترح المطور إبقاء session bearer خارج التخزين، واستعمال digest lookup مع
SessionStore مخصص بدل استبدال آلية المصادقة. هذا موضع مراجعة وليس موافقة:

- نموذج Django الأساسي يقيد session_key إلى40 حرفًا؛ digest SHA256 السداسي
  يحتاج تمثيلًا/حقلًا مناسبًا، دون truncation صامت أو DataError.
- يغطي الموائم create/save/load/exists/delete/clear_expired وcycle_key/flush؛
  لا double-hash، ولا fallback خام في المسارات async إن كانت متاحة للاستعمال.
- تبقى rotation عند login وحماية fixation وسلوك expiry مع الإطار، وتفحص
  نسخة مخزن جديدة بعد restart. APIs الخاصة بالنموذج والمدير تحتاج مراجعة أيضًا.
- لا يكفي تحميل user_id من الجلسة؛ يجب إبقاء Django session auth-hash check
  حتى يبطل تغيير كلمة المرور/logout الجلسة فعلًا.
- تفحص جداول/ميزات allauth الإضافية للتأكد من عدم نسخ raw token في موضع آخر؛
  لا تفعيل usersessions أو caching جانبي بلا إثبات حدود التخزين والإبطال.

Django يوثق امتداد نموذج/مخزن الجلسات، وallauth يوثق تحقق auth-hash لجلسة
X-Session-Token. السلوك النهائي يثبت من المصدر المثبت والاختبارات، لا الوثيقة
وحدها. [Django5.2 sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/#extending-database-backed-session-engines)،
[allauth session tokens](https://docs.allauth.org/en/latest/headless/token-strategies/session-tokens.html).

## تحديث معماري قبل التنفيذ

أوضح المطور أن allauth قد يحتفظ برمز تحقق داخل session state، لذلك يقترح
تشفير payload بـFernet من cryptography مع مفتاح مستقل في ذاكرة harness،
وربط digest الصف داخل payload لمنع تبديل ciphertext بين جلسات. المنسق أكد
جواز مفاتيح fixture مؤقتة في الذاكرة فقط؛ لا key files أو بيانات اعتماد تشغيل.
ليست هذه E2EE، ولا سياسة KMS/rotation إنتاجية. يلزم فحص tamper/wrong-key/
cross-row substitution، وعدم وجود fallback إلى plaintext أو حفظ كود خام آخر.
إعادة التشغيل هنا تحفظ المفتاح في parent harness؛ لا تثبت provisioning إنتاجي.

خطر يجب إغلاقه قبل قبول الحذف: transaction في Django مع اتصال مستقل داخل
PostgresRepository لا يصنع معاملة واحدة بين auth/domain. نطلب إثبات rollback
موحد أو حالة انتقال fail-closed موثقة قابلة للاستكمال، واختبارات failure
injection بين حدود الحفظ دون ادعاء حذف مكتمل مبكرًا. ترتيب الأقفال ثابت لتجنب
deadlocks. هذه ملاحظة تصميم، لا عيب مثبت في مصدر لم يُسلَّم بعد.

التسجيل المكرر لبريد متحقق لا يبدل كلمة مروره ولا يورث جلسة/علاقة لمبادر آخر؛
تُفحص collisions قبل التحقق وبعده وcase variants والتسجيل المتزامن.
اختبارات Argon2 الفعلية محدودة التوازي تحت1GiB؛ أي كلفة hash مخفضة للاختبار
تُعلن ولا تستخدم كدليل على اختبار كلفة الإنتاج.
