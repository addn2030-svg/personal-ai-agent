# دليل النشر — Sheets Gateway v1.0 (T5)

**المنصة:** هاتفك (Chrome) تكفي لكل الخطوات. أسماء الأزرار حرفية كما تظهر في الواجهات.
**القاعدة الصارمة:** لا كتابة على الشيت الحي `1ZXmC_3_…` أثناء التطوير أو التحقق. النشر الفعلي للـ LIVE لا يبدأ إلا بعد نجاح حزمة T4 على DEV.

---

## 0) جدول المتغيرات (كما هو في التسليم)

| الموقع | المتغير | ملاحظة |
|---|---|---|
| Apps Script | `SPREADSHEET_ID` | إلزامي، ولا توجد قيمة احتياطية |
| Apps Script | `AGENT_SECRET` | = Railway `GOOGLE_SHEETS_WEBHOOK_SECRET` |
| Apps Script | `APPROVAL_SECRET` | = Railway `GOOGLE_SHEETS_APPROVAL_SECRET`، ويجب أن يختلف عن `AGENT_SECRET` |
| Apps Script | `GATEWAY_ENV` | `DEV` أو `LIVE` |
| Apps Script | `LIVE_SPREADSHEET_ID` | معرّف الشيت الحي، يُستخدم لحارس DEV |
| Railway | `GOOGLE_SHEETS_WEBHOOK_URL` | رابط نشر الـ Web App |
| Railway | `GOOGLE_SHEETS_WEBHOOK_SECRET` | موجود مسبقاً |
| Railway | `GOOGLE_SHEETS_APPROVAL_SECRET` | **جديد** |
| Railway | `TELEGRAM_ALLOWED_CHAT_ID` | يجب ضبطه (راجع T3) |

---

## 1) ترتيب النشر الإلزامي

1. ضبط الأسرار في Apps Script وRailway (الخطوتان 2 و3 أدناه).
2. نشر الـ gateway باختيار **New version** على نفس الـ deployment، حتى لا يتغير الرابط (الخطوة 4).
3. تشغيل حزمة التحقق `scripts/verify_sheets_gateway.py` على DEV (الخطوة 5).
4. دمج الـ PR بعد مراجعة المالك فقط (الخطوة 6). **لا دمج لأي PR قبل مراجعة المالك. لا دمج لـ PR #75 إطلاقاً.**

---

## 2) Apps Script — الكود والمتغيرات (على الهاتف)

1. افتح `script.google.com` → سجّل الدخول بحساب المالك → اضغط على اسم المشروع «Abdulrahman AI OS Sheets Gateway» (أو الاسم الحالي) لفتحه.
2. من قائمة يسار الشاشة «المنتجات» (Project Overview اضغط سهم الرجوع «Back» أعلى اليسار إن لزم) اختر ملف السكربت `GoogleSheetsWebhook` (امتداد `.gs`).
3. احذف محتواه بالكامل والصق محتوى `connectors/google_sheets_webhook.gs` من الفرع المراجَع (نسخة v1.0 بعد دمج T2). زر اللصق على الهاتف: اضغط مطولاً داخل المحرر → «Paste».
4. اضغط أيقونة الترس ⚙️ «Project Settings» في اللوحة اليسرى → افتح قسم «Properties» → اضغط «Script Properties» ثم زر «View properties» → زر «Edit properties».
5. أضف سطراً بسطر (اكتب الاسم ثم القيمة ثم زر «+ Add property»): `SPREADSHEET_ID` = **معرّف شيت DEV**، `AGENT_SECRET`، `APPROVAL_SECRET` (مختلف عن AGENT_SECRET)، `GATEWAY_ENV` = `DEV`، `LIVE_SPREADSHEET_ID` = `1ZXmC_3_OTYYtXglNMXRQiSWu2rjDDIzoqaK0SQuWcWc`. اضغط «Done».
6. توليد قيمتين عشوائيتين longتين للأسرار (مثال محطة أمانة: افتح `1password`/أو نفّذ `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` مرة واحدة من جهازك). لا تُخزّن الأسرار في الشيت ولا في Telegram.
7. شغّل التهيئة مرة واحدة: في شريط الأدوات العلوي قائمة اختيار الدالة (بجانب زر ▶ Run) → اختر `setupGateway` → اضغط ▶ «Run» → نافذة «Review permissions» → اختر حسابك → «Advanced» → «Go to … (unsafe)» → «Allow». النتيجة المتوقعة: إنشاء/تجهيز تبويبي `Gateway_Audit` و`Gateway_Approvals` دون أخطاء في سجل «Execution log» بالأسفل.

## 3) Railway — المتغيرات

1. افتح `railway.app` → مشروع «personal-ai-agent» → اضغط على الخدمة (service) التي تشغّل البوت.
2. في الأعلى اختر تبويب «Variables».
3. أضف/عدّل: `GOOGLE_SHEETS_WEBHOOK_URL` = رابط Web App (من خطوة 4.7)، `GOOGLE_SHEETS_APPROVAL_SECRET` = قيمة `APPROVAL_SECRET` نفسها (اضغط أيقونة القفل على يمين الحقل لتحويله Secret)، وتحقق من بقاء `GOOGLE_SHEETS_WEBHOOK_SECRET` مطابقاً لـ `AGENT_SECRET`، و`TELEGRAM_ALLOWED_CHAT_ID` مضبوطاً.
4. اضغط «Save» ثم «Deploy» (أو أعِد التشغيل: نقاط (…) يمين الخدمة → «Restart»).
5. لا تفعّل `AI_STRATEGIC_CREATOR_ENABLED` ولا أي مفتاح live في هذه الجولة.

## 4) نشر Web App بدون تغيير الرابط (الأهم)

1. في محرر Apps Script اضغط زر «Deploy» الأزرق أعلى اليمين → «Manage deployments».
2. اضغط أيقونة القلم ✏️ على نشر الـ Web App الحالي (لا تنشئ «New deployment»).
3. في خانة «Version» افتح القائمة واختر **New version** (وليس «Test deployments»).
4. تأكد: «Execute as: Me» و«Who has access: Anyone».
5. اضغط «Deploy» → «OK» في نافذة الأذونات إن ظهرت. **الرابط لا يتغير** — هذا هو المقصود.
6. للرجوع عند الطوارئ: نفس القلم ✏️ → «Version» → اختيار الإصدار السابق (القائمة تحتفظ بالإصدارات) → «Deploy».

## 5) حزمة التحقق T4 على DEV

من حاسوب (أو Termux):

```bash
export GOOGLE_SHEETS_WEBHOOK_URL='https://script.google.com/macros/s/…/exec'
export GOOGLE_SHEETS_WEBHOOK_SECRET='…'      # = AGENT_SECRET
export GOOGLE_SHEETS_APPROVAL_SECRET='…'     # = APPROVAL_SECRET
export SHEETS_DEV_SPREADSHEET_ID='معرّف شيت DEV'
python3 scripts/verify_sheets_gateway.py
```

- المتوقع: `RESULT: 12/12 PASS` وخروج بكود 0.
- يرفض السكربت العمل إذا طابق `SHEETS_DEV_SPREADSHEET_ID` معرّف الشيت الحي، أو لم يبلّغ الـ gateway عن `env:"DEV"`.
- راجع تبويب `Gateway_Audit`: يجب أن ترى صفوف update (نجحت ورُفضت) مطابقة لنتائج الحالتين 5 و6 و8.

## 6) GitHub — الـ PR

1. الفرع: `fix/sheets-gateway-v1.0` (أو فرع Arena بعد المواءمة). 
2. على الهاتف عبر المتصفح: افتح `github.com/addn2030-svg/personal-ai-agent/pulls` → «New pull request» → base: `main`، compare: الفرع → راجع «Files changed» → عنوان مثل `Sheets Gateway v1.0 (+T2 routing, T4 suite, T5 runbook)` → «Create pull request».
3. أو من الطرفية: `gh pr create --base main --head fix/sheets-gateway-v1.0 --title "Sheets Gateway v1.0" --body "..."`.
4. مراجعة المالك إلزامية قبل الدمج؛ لا يدمَج تلقائياً. بعد الدمج تُعاد خطوة 4 (نشر New version pointing للـ LIVE properties عند الانتقال لبيئة LIVE لاحقاً) ثم تُشغَّل حزمة T4 على DEV مرة أخيرة.

## 7) قائمة قبل الانتقال إلى GATEWAY_ENV=LIVE (لاحقاً، بموافقة المالك)

- [ ] StateStore في الإنتاج يعمل، ومراجعة Option B (حذف update نهائياً) مؤجلة بقرار المالك.
- [ ] سطر `TELEGRAM_ALLOWED_CHAT_ID` مضبوط ومثبت (قرار T3 منفَّذ).
- [ ] `APPROVAL_SECRET` ≠ `AGENT_SECRET`، والأسرار مكتوبة في Secrets فقط.
- [ ] حزمة T4 خضراء على DEV، وسجل `Gateway_Audit` يعرض الصفوف المتوقعة.
