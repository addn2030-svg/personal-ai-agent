# إعداد النشر عبر Buffer

موصل `connectors/buffer_publisher.py` ينشر أو جدولة منشورًا (نص + صورة) في Buffer
عبر واجهة **GraphQL API** الرسمية (`https://api.buffer.com`).

## الطريقة (٠) — من تيليجرام، خلف بوابة الاعتماد (C2)

الأمر `/buffer_post` من المحادثة نفسها يُنشئ **مسودة إجراء** في طابور الاعتماد
(`Store.action_queue` بربط بصمة المحتوى وصلاحية 48 ساعة) — ولا يخرج أي أثر خارجي
حتى تضغط زر **✅ اعتماد**؛ عندها فقط يُنشر عبر Buffer ويصلك إيصال بالإغلاق `EXECUTED`.

```
/buffer_post instagram | نص المنشور
/buffer_post instagram | نص المنشور | https://raw.githubusercontent.com/.../cover.jpg
/buffer_post linkedin | نص المنشور | 2026-09-12 18:00 | مسودة
```

- الحقل الأول: اسم الشبكة (`instagram` / `linkedin` / `twitter` …) أو معرف القناة الصريح
  (اكتشفه بـ `/buffer_channels`).
- الحقول الإضافية بعد النص اختيارية وبأي ترتيب: رابط صورة عامة · وقت الجدولة
  `YYYY-MM-DD HH:MM` بتوقيت السعودية · كلمة `مسودة` للحفظ كمسودة في Buffer بدل الطابور.
- يتطلب `BUFFER_API_KEY` مضبوطًا في بيئة تشغيل البوت (يُرفض الأمر قبل ضبطه).
- إن فشل النشر عند الاعتماد (شبكة/مفتاح) يعود الإجراء إلى `PENDING_APPROVAL` مع تسجيل
  السبب — عالجه ثم اضغط الاعتماد مرة أخرى.
- الاعتماد من سطر الأوامر (`engine/approve.py approve`) ينفّذ النشر بالطريقة نفسها.
- نص يحتوي الرمز `|`؟ استخدم الطريقة (ب) أدناه.

## الطريقة (أ) — GitHub Actions دون تثبيت أي شيء

انشر مباشرة من المستودع دون تشغيل أي شيء محليًا:

1. **أضف المفتاح كـ Secret مشفّر** (مرة واحدة فقط):
   - GitHub → المستودع → **Settings → Secrets and variables → Actions → New repository secret**
   - الاسم: `BUFFER_API_KEY` — القيمة: مفتاحك من publish.buffer.com/settings/api
   - (أو من الطرفية: `gh secret set BUFFER_API_KEY` ثم ألصق المفتاح)
2. اختر طريقة التشغيل:
   - **قائمة الانتظار (موصى بها):** أضف ملف JSON في `posts/buffer/` داخل PR نحو `main`
     — يُجدول المنشور تلقائيًا عند فتح الـ PR (الحقول في `posts/buffer/README.md`)
   - **يدويًا:** تبويب **Actions** → **Buffer Publish** → **Run workflow**
     (أو `gh workflow run buffer-publish.yml --ref main -f text="نص المنشور" -f service=instagram`)

المفتاح يبقى مشفّرًا ولا يظهر في السجلات أبدًا.

## الطريقة (ب) — من جهازك مباشرة

## 1) الحصول على مفتاح API

1. افتح **publish.buffer.com/settings/api**
2. أنشئ مفتاح API شخصيًا (Personal API Key)
3. صدّره كمتغير بيئة (لا تضعه في أي ملف داخل المستودع):

```bash
export BUFFER_API_KEY="مفتاحك_هنا"        # Linux / macOS
setx BUFFER_API_KEY "مفتاحك_هنا"          # Windows (ثم أعد فتح الطرفية)
```

## 2) استعراض القنوات

كل منشور يستهدف **قناة** واحدة بمعرّفها:

```bash
python3 -m connectors.buffer_publisher --list
```

سيطبع المؤسسات ثم كل قناة (X، لينكدإن، إنستغرام …) مع `channel id`.

## 3) النشر / الجدولة

```bash
# إضافة إلى الطابور (حسب جدول Buffer التلقائي)
python3 -m connectors.buffer_publisher \
  --channel-id CHANNEL_ID \
  --text "نص المنشور" \
  --image-url https://raw.githubusercontent.com/addn2030-svg/personal-ai-agent/main/assets/book-cover.jpg

# جدولة في وقت محدد (افتراضيًا بتوقيت السعودية +03:00)
python3 -m connectors.buffer_publisher \
  --channel-id CHANNEL_ID --text "نص المنشور" --image-url https://... \
  --due-at "2026-09-12 18:00"

# حفظ كمسودة للمراجعة قبل النشر
python3 -m connectors.buffer_publisher \
  --channel-id CHANNEL_ID --text "نص" --image-url https://... --draft
```

## قيود معروفة

- **الصور يجب أن تكون على رابط عام** — واجهة Buffer لا تدعم رفع الملفات.
  الطريقة المعتمدة في هذا المستودع: ضع الصورة في `assets/` وارفعها،
  ثم استخدم رابط `raw.githubusercontent.com` الخاص بها.
- المفتاح شخصي بصلاحيات كاملة (لا توجد مفاتيح للقراءة فقط) — احتفظ به سريًا.
