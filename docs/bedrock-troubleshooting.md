# Bedrock Troubleshooting — دليل إصلاح أخطاء Bedrock

This document explains the three errors you saw in Telegram and how to fix them in production (Railway).

## The errors you received

### 1. `Authentication failed: Please make sure your API Key is valid.`
- **السبب**: `AWS_BEARER_TOKEN_BEDROCK` منتهي أو تم إلغاؤه، أو نسخته ناقصة في Railway Variables.
- **الحل**:
  1. افتح AWS Console > Bedrock > API keys
  2. احذف المفتاح القديم `BedrockAPIKey-hr8l`
  3. أنشئ مفتاح جديد (Create API key)
  4. انسخ القيمة كاملة (تبدأ بـ `...`)
  5. في Railway > Variables حدّث `AWS_BEARER_TOKEN_BEDROCK` بالقيمة الجديدة
  6. أعد النشر (Redeploy) ثم جرّب `/ai_status` و `/bedrock_test`

### 2. `Your account is currently being verified. Verification normally takes less than 2 hours.`
- **السبب**: حساب AWS جديد لم يكتمل التحقق للوصول إلى Bedrock.
- **الحل**:
  1. انتظر حتى ساعتين
  2. راجع AWS Console > Bedrock > Model access — يجب أن ترى حالة الحساب
  3. إذا استمر أكثر من 2 ساعة: افتح AWS Support case (Bedrock > Account verification)
  4. كحل مؤقت: فعّل `OPENROUTER_API_KEY` ليستخدم البوت OpenRouter بدل Bedrock
     - احصل على مفتاح من https://openrouter.ai/keys
     - أضفه في Railway Variables كـ `OPENROUTER_API_KEY`
     - اضبط `AI_MODEL_PROVIDER=auto` (الافتراضي) و `OPENROUTER_FALLBACK_BEDROCK=1`

### 3. `User: arn:aws:iam::410126553135:user/BedrockAPIKey-hr8l is not authorized to perform: bedrock:Converse`
- **السبب**: المستخدم `BedrockAPIKey-hr8l` ليس لديه صلاحيات IAM كافية، أو الموديل غير مفعل في Model access.
- **الحل**:
  1. **IAM**: افتح IAM Console > Users > BedrockAPIKey-hr8l > Add permissions
     - أضف `AmazonBedrockFullAccess` (أسهل) أو سياسة مخصصة:
       ```json
       {
         "Version": "2012-10-17",
         "Statement": [{
           "Effect": "Allow",
           "Action": [
             "bedrock:Converse",
             "bedrock:ConverseStream",
             "bedrock:InvokeModel",
             "bedrock:InvokeModelWithResponseStream",
             "bedrock:ListFoundationModels",
             "bedrock:GetFoundationModel"
           ],
           "Resource": "*"
         }]
       }
       ```
  2. **Model access**: افتح Bedrock Console > Model access > Manage model access
     - فعّل `Claude Sonnet 4.6` (أو `us.anthropic.claude-sonnet-4-6`) و `Amazon Nova Micro`
     - اضغط Save — قد يستغرق دقائق
  3. **Region**: تأكد أن `AWS_REGION` في Railway يطابق المنطقة التي فعّلت فيها الموديل (مثلاً `us-east-1`)
  4. أعد النشر ثم `/bedrock_test`

## Quick production checklist

Railway Variables المطلوبة (الحد الأدنى للعمل):

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=...
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
AWS_BEARER_TOKEN_BEDROCK=...  # أو AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
OPENROUTER_API_KEY=...        # موصى به كـ primary
AI_MODEL_PROVIDER=auto
AI_CLINICAL_PROVIDER=bedrock
OPENROUTER_FALLBACK_BEDROCK=1
```

للتحقق الحي:

- `/time` — يثبت أن worker حي حتى لو Bedrock معطل
- `/ai_status` — يعرض الحالة + فحص حي OpenRouter و Bedrock مع تلميحات عربية
- `/bedrock_test` — اختبار مصغر لـ Claude و Nova Micro
- `/storage_status` — فحص Google Sheets

## What was fixed in code (2026-09-18)

- `model_gateway.py`: added `_explain_bedrock_error` and `_explain_openrouter_error` to map raw AWS errors to actionable Arabic hints. `ask()` now combines OpenRouter + Bedrock failures instead of hiding the first error.
- `bedrock_team.py`: wrapped Converse calls with same humanizer, probe now returns `detail` with hint.
- `telegram_webhook.py`: `_friendly_error_message()` now sends Arabic guidance instead of raw `AccessDeniedException`.
- `telegram_bot_legacy.py`: same humanizer for polling mode.
- `telegram_bot.py`: `/ai_status` now runs live probe and shows both providers.

After deploying, the user will no longer see only `❌ تعذر تنفيذ الطلب: An error occurred (AccessDeniedException)...` but also:

```
🔑 Bedrock API Key غير صالح...
⛔ IAM المستخدم ليس لديه صلاحية...
⏳ حساب AWS قيد التحقق...
```

with steps to fix.
