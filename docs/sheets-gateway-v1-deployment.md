# Sheets Gateway v1.0 — دليل النشر والتحقق من الهاتف

هذا الدليل يخص **DEV فقط** حتى يراجع المالك التغيير قبل أي تشغيل حي. لا تُجرى أي كتابة على الشيت الحي، ولا تُفعّل Telegram أو Railway أو `AI_STRATEGIC_CREATOR_ENABLED` في بيئة LIVE أثناء هذه الخطوات.

## 0) قواعد قبل البدء

1. أنشئ أو اختر شيت DEV منفصلًا عن الشيت الحي.
2. الشيت الحي المحظور أثناء التطوير هو:
   `1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc`
3. يجب أن يختلف `APPROVAL_SECRET` عن `AGENT_SECRET`.
4. الأسرار توضع في **Script Properties** أو **Railway Variables** فقط؛ لا تُنسخ إلى GitHub أو Telegram أو سجل الاختبار.
5. قرار T3 الخاص بـ `TELEGRAM_ALLOWED_CHAT_ID` ما زال مطلوبًا من المالك. لا تُفعّل Telegram قبل اختياره.

---

## 1) إعداد Google Apps Script من الهاتف

### 1.1 فتح المشروع وتحديث الملف

1. افتح متصفح الهاتف وانتقل إلى `script.google.com`.
2. اضغط **My Projects** ثم افتح مشروع الـ Apps Script المرتبط بالـ Gateway.
3. من القائمة اليسرى اضغط **Editor**.
4. افتح الملف `google_sheets_webhook.gs`.
5. استبدل محتوى الملف كاملًا بمحتوى:
   `connectors/google_sheets_webhook.gs`.
6. اضغط **Save project**.

### 1.2 ضبط Script Properties

1. من القائمة اليسرى اضغط **Project Settings**.
2. انزل إلى قسم **Script Properties**.
3. لكل متغير اضغط **Add script property**، وأدخل الاسم والقيمة، ثم اضغط **Save script properties**.
4. استخدم هذه الأسماء والقيم:

| الاسم الحرفي | القيمة في DEV |
|---|---|
| `SPREADSHEET_ID` | معرّف شيت DEV فقط |
| `AGENT_SECRET` | السر الذي سيستخدمه Railway في `GOOGLE_SHEETS_WEBHOOK_SECRET` |
| `APPROVAL_SECRET` | السر الذي سيستخدمه Railway في `GOOGLE_SHEETS_APPROVAL_SECRET`؛ يجب أن يختلف عن `AGENT_SECRET` |
| `GATEWAY_ENV` | `DEV` |
| `LIVE_SPREADSHEET_ID` | معرّف الشيت الحي المحظور أعلاه |

لا تضع معرّف الشيت الحي في `SPREADSHEET_ID` أثناء التطوير.

### 1.3 تشغيل التهيئة مرة واحدة

1. من القائمة اليسرى اضغط **Editor**.
2. من قائمة الدوال أعلى المحرر اختر `setupGateway`.
3. اضغط **Run**.
4. عند ظهور نافذة الصلاحيات اضغط **Review permissions**.
5. اختر حساب Google المالك للمشروع.
6. إذا ظهرت شاشة تحذير، اضغط **Advanced** ثم **Go to [اسم المشروع] (unsafe)**، ثم اضغط **Allow**.
7. ارجع إلى **Execution log** وتأكد من ظهور أن Gateway بالإصدار `1.0.0` وبيئة `DEV`.

تُنشأ أو تُجهّز التبويبات `Gateway_Audit` و`Gateway_Approvals`. لا تعدّل صفوفهما يدويًا.

### 1.4 نشر New version على نفس الـ deployment

1. من أعلى الصفحة اضغط **Deploy**.
2. اضغط **Manage deployments**.
3. افتح الـ Web app deployment الموجود.
4. اضغط أيقونة القلم **Edit**.
5. عند **Version** اختر **New version**.
6. اترك **Execute as** على **Me**.
7. في **Who has access** اختر مستوى الوصول الذي يسمح لخدمة Railway باستدعاء الرابط. إذا كان الخيار متاحًا، اختر **Anyone**؛ حماية الطلب تتم بالـ `AGENT_SECRET`.
8. اضغط **Deploy**.
9. اضغط **Copy** بجانب **Web app URL**، أو انسخ الرابط من شاشة **Manage deployments**.
10. لا تنشئ Deployment جديدًا ولا تغيّر رابط الـ deployment المستخدم؛ المطلوب هو **New version** على نفس الـ deployment.

إذا عدّلت Script Properties لاحقًا، أعد خطوة **New version** على نفس الـ deployment.

---

## 2) إعداد Railway من الهاتف

نفّذ هذه الخطوات على بيئة DEV أو خدمة اختبار منفصلة، وليس على خدمة LIVE.

1. افتح `railway.app` وسجّل الدخول.
2. افتح **Project** ثم اختر خدمة Python الخاصة بالوكيل.
3. افتح تبويب **Variables**.
4. اضغط **New Variable** لكل متغير، أو **Add Variable** إذا ظهر بهذا الاسم.
5. أضف المتغيرات التالية:

| الاسم الحرفي | القيمة |
|---|---|
| `GOOGLE_SHEETS_WEBHOOK_URL` | رابط **Web app URL** الذي نُسخ من Apps Script |
| `GOOGLE_SHEETS_WEBHOOK_SECRET` | نفس قيمة `AGENT_SECRET` في Apps Script |
| `GOOGLE_SHEETS_APPROVAL_SECRET` | نفس قيمة `APPROVAL_SECRET` في Apps Script |
| `TELEGRAM_ALLOWED_CHAT_ID` | لا تتركه فارغًا إذا اختار المالك خيار T3-A؛ لا تُفعّل Telegram قبل القرار |

6. اضغط **Save** أو **Add** بعد إدخال كل متغير.
7. إذا لم تبدأ إعادة النشر تلقائيًا، افتح **Deployments** واضغط **Redeploy**.
8. افتح **Deploy Logs** أو **Logs** وانتظر الحالة **Deployed**.
9. لا تضع أي Secret في رسالة commit أو في مخرجات الطرفية.

### متغيرات التشغيل المحلي للتحقق الآمن

لتشغيل T4 من جهاز التطوير، اجعل `SHEETS_GATEWAY_TARGET_SPREADSHEET_ID` هو معرّف DEV، وليس معرّف الشيت الحي. يرفض السكربت التشغيل إذا كان المعرف حيًا أو إذا أعاد `/health` بيئة غير `DEV`.

```bash
read -r -p "DEV Web app URL: " GOOGLE_SHEETS_WEBHOOK_URL
read -r -s -p "AGENT_SECRET: " GOOGLE_SHEETS_WEBHOOK_SECRET; printf '\\n'
read -r -s -p "APPROVAL_SECRET: " GOOGLE_SHEETS_APPROVAL_SECRET; printf '\\n'
read -r -p "DEV spreadsheet ID: " SHEETS_GATEWAY_TARGET_SPREADSHEET_ID
export GOOGLE_SHEETS_WEBHOOK_URL GOOGLE_SHEETS_WEBHOOK_SECRET GOOGLE_SHEETS_APPROVAL_SECRET
export SHEETS_GATEWAY_TARGET_SPREADSHEET_ID
export SHEETS_GATEWAY_VERIFY_SHEET='Executive_Brief'
export SHEETS_GATEWAY_VERIFY_RANGE='ZZ1'
python3 scripts/verify_sheets_gateway.py
```

القيم بين علامات الاقتباس أعلاه تُقرأ من مدير الأسرار ولا تُحفظ في Git. يمكن تغيير خلية DEV عبر `SHEETS_GATEWAY_VERIFY_RANGE` إذا كانت `ZZ1` غير مناسبة.

النتيجة المقبولة هي:

```text
PASS 1. health
...
PASS 11. wrong approval secret
RESULT PASS: 11/11 gateway checks passed
```

يُتوقع أن تضيف الحالات 2 و9 و10 صفوف تحقق في `Agent_Log` في شيت DEV؛ لا تحذف أو تعدّل سجلات Gateway يدويًا.

---

## 3) مراجعة المالك قبل PR

1. افتح نتيجة T4 وتأكد من `RESULT PASS: 11/11 gateway checks passed`.
2. افتح `Gateway_Audit` في شيت DEV وتأكد من وجود آثار `append` و`record_approval` و`update`.
3. تأكد يدويًا أن صف `=1+1` في `Agent_Log` ظهر كنص، وليس نتيجة `2`.
4. تأكد أن الشيت الحي لم يتغير.
5. اتخذ قرار T3:
   - **A**: فشل مغلق إذا غاب `TELEGRAM_ALLOWED_CHAT_ID`.
   - **B**: تحذير فقط في `/status`.
6. لا تُدمج أي PR قبل مراجعة المالك واعتماده.

---

## 4) إنشاء GitHub Pull Request من الهاتف

> في جلسة Arena الحالية الفرع المثبت هو `arena/01a08dc1-personal-ai-agent`. لا تستخدم اسم الفرع المقترح القديم `fix/sheets-gateway-v1.0` في هذه الجلسة.

### 4.1 تجهيز الفرع

من جهاز التطوير أو الطرفية:

1. نفّذ `git status` وتأكد أن التغييرات في الفرع المثبت.
2. شغّل الاختبارات المطلوبة:

```bash
python3 -m unittest tests.test_sheets_gateway_v1 tests.test_workspace_write_actions
python3 -m unittest $(ls tests/test_*.py | sed 's#/#.#; s#\.py$##')
```

3. نفّذ `git add` للملفات المطلوبة فقط.
4. نفّذ `git commit` برسالة تصف Sheets Gateway v1.0.
5. نفّذ:

```bash
git push origin arena/01a08dc1-personal-ai-agent
```

### 4.2 فتح PR في GitHub على الهاتف

1. افتح تطبيق GitHub أو `github.com`.
2. افتح المستودع `addn2030-svg/personal-ai-agent`.
3. اضغط **Pull requests**.
4. اضغط **New pull request**.
5. في **base** اختر `main`.
6. في **compare** اختر `arena/01a08dc1-personal-ai-agent`.
7. راجع قائمة **Commits** و **Files changed**.
8. اضغط **Create pull request**.
9. اكتب عنوانًا واضحًا، مثل: `fix: route Sheets writes through Gateway v1.0`.
10. في الوصف أدرج: نتيجة الاختبارات، نتيجة T4، أن التحقق كان على DEV، وقرار T3 المطلوب.
11. اضغط **Create pull request** مرة أخرى.
12. اترك PR مفتوحًا للمراجعة؛ لا تضغط **Merge pull request** قبل موافقة المالك.

لا تفتح أو تدمج PR رقم `75` ضمن هذا التسليم.

---

## 5) ترتيب النشر الإلزامي

1. ضبط الأسرار في Apps Script وRailway، مع فصل `AGENT_SECRET` عن `APPROVAL_SECRET`.
2. نشر الـ Gateway باختيار **New version** على نفس الـ deployment.
3. تشغيل `scripts/verify_sheets_gateway.py` على DEV والتأكد من `11/11`.
4. رفع الفرع وفتح PR، ثم انتظار مراجعة المالك قبل الدمج.

## 6) رجوع آمن

إذا فشل التحقق أو ظهرت كتابة غير متوقعة، أوقف خدمة DEV، ثم من Apps Script افتح **Deploy** → **Manage deployments** → أيقونة القلم **Edit** → اختر الإصدار السابق في **Version** → **Deploy**. لا تغيّر `SPREADSHEET_ID` إلى الشيت الحي كحل سريع، ولا تُجرِ اختبارًا ثانيًا قبل تحديد السبب.
