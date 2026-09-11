# إعداد النشر عبر Buffer

موصل `connectors/buffer_publisher.py` ينشر أو يجدول منشورًا (نص + صورة) في Buffer
عبر واجهة **GraphQL API** الرسمية (`https://api.buffer.com`).

## الطريقة الموصى بها — Telegram Content Creator على Railway

اضبط في Railway: `BUFFER_API_KEY` و`CONTENT_DEFAULT_PLATFORM=linkedin` و
`BUFFER_DEFAULT_MODE=draft`. ثم استخدم `/content linkedin الفكرة`. يمر الطلب عبر
Researcher → Critic → Creator ويعود Preview فقط. لا يتصل Buffer حتى ترسل
`/approve_content ID CODE`؛ عند النجاح يُحفظ `post_id` وحالة Buffer كإيصال في
`action_queue`. استخدم `/content_status` لفحص الإعداد دون نشر.

## الطريقة (أ) — GitHub Actions دون تثبيت أي شيء

انشر مباشرة من المستودع دون تشغيل أي شيء محليًا:

1. **أضف المفتاح كـ Secret مشفّر** (مرة واحدة فقط):
   - GitHub → المستودع → **Settings → Secrets and variables → Actions → New repository secret**
   - الاسم: `BUFFER_API_KEY` — القيمة: مفتاحك من publish.buffer.com/settings/api
   - (أو من الطرفية: `gh secret set BUFFER_API_KEY` ثم ألصق المفتاح)
2. اختر طريقة التشغيل:
   - **قائمة الانتظار (موصى بها):** أضف ملف JSON في `posts/buffer/` داخل PR نحو `main`.
     فتح الـPR لا ينشر شيئًا؛ يبدأ الإرسال إلى Buffer فقط بعد المراجعة والدمج في `main`
     (الحقول في `posts/buffer/README.md`).
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
