# إعداد النشر عبر Buffer

موصل `connectors/buffer_publisher.py` ينشر أو يجدول منشورًا (نص + صورة) في Buffer
عبر واجهة **GraphQL API** الرسمية (`https://api.buffer.com`).

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
