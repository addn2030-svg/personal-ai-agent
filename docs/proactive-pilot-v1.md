# Proactive Chief of Staff Pilot v1

هذا الإصدار يفصل الطبقة الاستباقية عن Calendar. لا تُرسل تعليمات الإعداد الطويلة إلى محلل المواعيد؛ استخدم أوامر `/proactive`.

## أوامر Telegram

```text
/proactive status
/proactive suggest
/proactive run
/proactive log exercise done
/proactive log reading done
/proactive log contact Rania
/proactive respond ALERT_ID تم
/proactive respond ALERT_ID أجّل
/proactive respond ALERT_ID تجاهل
/proactive config
/proactive config reading_time=07:00
/proactive config exercise_days=0,2,4,6
/proactive config quiet=22:00-05:15
```

- `status`: يعرض حالة Pilot، الحد اليومي، ساعات الهدوء، وأي مدخلات ناقصة.
- `suggest`: يعرض اقتراحًا واحدًا مبنيًا على السجلات الموجودة.
- `run`: محاكاة دورة دون إرسال Telegram.
- `log`: يسجل إنجازًا فعليًا في StateStore؛ لا يعتبر الخطة إنجازًا.
- `respond`: يسجل استجابة المالك محليًا ثم يحاول append إلى `FollowUp_Log` عبر Gateway.
- `config`: يعرض الإعدادات، ويسمح فقط بالتعديلات الصريحة المحدودة (`reading_time`, `exercise_days`, `quiet`, `off`). لا توجد صيغة Telegram لرفع اعتماد T3 أو تشغيل LIVE.

## المتغيرات

الإعدادات الآمنة الافتراضية:

| المتغير | الافتراضي | الملاحظة |
|---|---:|---|
| `PROACTIVE_ENABLED` | `0` | لا يبدأ العامل تلقائيًا |
| `PROACTIVE_DRY_RUN` | `1` | لا إرسال Telegram |
| `PROACTIVE_INTERVAL_SECONDS` | `60` | دورة العامل |
| `proactive_config.t3_approved` | `false` | بوابة اعتماد T3 في StateStore؛ لا تُرفع قبل موافقة المالك |
| `TELEGRAM_ALLOWED_CHAT_ID` | إلزامي للإرسال | لا يرسل العامل بدونه |
| `GOOGLE_SHEETS_WEBHOOK_URL` | — | مطلوب لتسجيل `FollowUp_Log` |
| `GOOGLE_SHEETS_WEBHOOK_SECRET` | — | سر Gateway فقط |
| `GOOGLE_SHEETS_APPROVAL_SECRET` | — | لا يُستخدم لتسجيل التنبيه؛ يبقى لمسار الموافقات |

الإرسال الحي يحتاج جميع الآتي، إضافة إلى أن `proactive_config` في StateStore يحمل `enabled=true` و`t3_approved=true` بعد موافقة T3. لا يوجد أمر Telegram يرفع بوابة T3:

```text
PROACTIVE_ENABLED=1
PROACTIVE_DRY_RUN=0
TELEGRAM_ALLOWED_CHAT_ID=<owner>
GOOGLE_SHEETS_WEBHOOK_URL=<DEV-or-approved-live-gateway>
GOOGLE_SHEETS_WEBHOOK_SECRET=<agent-secret>
```

لا يُفعّل الإرسال الحي قبل اختبار DEV وقرار هوية المالك T3.

## تشغيل DEV

محاكاة آمنة من مجلد المشروع:

```bash
python3 engine/proactive_worker.py --once --dry-run --context
```

تشغيل أمر الحالة دون Telegram:

```bash
python3 -m unittest tests.test_proactive_controller
```

العامل الحي لا يُشغّل إلا كخدمة Railway منفصلة:

```bash
python3 engine/proactive_worker.py
```

يجب أن تكون الخدمة المنفصلة على نفس Volume الخاص بـ `AI_OS_DATA_DIR`، وألا تستخدم نفس عملية webhook. العامل لا يرسل لطرف آخر؛ رسائل الأطراف الأخرى تبقى `PROPOSE`.

## سياسة التنبيه

كل تنبيه يحتوي على:

1. الإشارة.
2. الدليل ومصدره وتاريخه.
3. إجراء واحد.
4. `تم / أجّل / تجاهل`.

الحد اليومي ثلاثة. لا إرسال بين 22:00 و05:15 بتوقيت الرياض. إذا لم يوجد سجل فعلي، يعرض العامل أن البيانات غير مؤكدة ولا يخمن.

أيام التمرين لا تُفترض؛ إلى أن تُضبط، لا ينشئ العامل تنبيه تمرين تلقائيًا. القراءة مضبوطة افتراضيًا من الأحد إلى الخميس عند 07:00. الملخص التنفيذي عند 06:00، والمراجعة الأسبوعية الأحد عند 08:00.

## سجل FollowUp_Log

في التشغيل الحي فقط، قبل أي إرسال للمالك، يحاول العامل إضافة صف `PROPOSED` عبر Gateway. إذا فشل التسجيل، لا يرسل التنبيه. بعد الإرسال يضيف `SENT`، وبعد رد المالك يضيف `RESPONSE`. لا يستخدم العامل `update` لهذا السجل. أما `--dry-run` فهو بلا Telegram وبلا Gateway وبلا كتابة محلية.

## منع خطأ Calendar

المسار المخصص `/proactive` يسبق Calendar. كما أن Calendar لا يلتقط كلمات مثل «موعد تسليم» داخل تعليمات طويلة ما لم تبدأ الرسالة بطلب جدولة واضح. لذلك لا تستخدم `/confirm_event` لتأكيد إعداد الطبقة الاستباقية.
