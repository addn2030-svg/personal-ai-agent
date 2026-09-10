# T3 — تثبيت هوية مالك Telegram (حزمة قرار — لم يُنفَّذ شيء)

**الحالة:** NEEDS_DECISION — بانتظار قرار د. عبدالرحمن. لا كود نُفِّذ في الفرع.
**الملفات:** `connectors/telegram_bot_legacy.py` + `connectors/telegram_webhook_runtime.py`
(الاختبار: `python3 -m unittest $(ls tests/test_*.py | sed 's#/#.#; s#\.py$##')` → 232 OK مع كل خيار مطبَّقاً في نسخة مؤقتة).

## المشكلة

مسار التفويض كله (رسائل، أوامر، أزرار callbacks، المسار القديم والمسار الجديد) يمر عبر
`_authorized()` في `telegram_bot_legacy.py`. عندما يغيب `TELEGRAM_ALLOWED_CHAT_ID`:

1. يُقرأ المالك من `data/.telegram-owner-chat-id`.
2. إذا لم يوجد الملف تُمنح الملكية تلقائياً لأول محادثة خاصة، ويكتبها البوت في الملف.

في Railway لا يوجد persistent volume لـ `data/` (انظر `Dockerfile`: نسخة جديدة = نسخة جديدة تماماً).
إذن: إعادة نشر/إعادة تشغيل الحاوية بدون المتغير = **أول شخص يراسل البوت يصبح المالك**،
ولديه `/confirm` (تحديث خلايا) و `/approve` و `/run` وكل الصلاحيات.
كما أن `_authorized` لا يفرض انتهاء صلاحية ولا إعادة ربط؛ الملف هو الضمانة الوحيدة.

## الخيار A — فشل مغلق (Fail-closed)

البوت لا يقلع إطلاقاً في بيئة Railway بدون `TELEGRAM_ALLOWED_CHAT_ID`، وأيضاً لا يربط
الملكية تلقائياً حتى لو اكْتُرم الإقلاع عبر مسار آخر. محلياً (بلا متغيرات Railway) يسلك
مسلك التطوير الطبيعي.

**الأثر:** انقطاع كامل للبوت إذا فُقد المتغير — لكن الانقطاع ظاهر فوراً في صفحة Railway
(failed deploy / crash loop) بدل استيلاء صامت. الكتابة على الشيت تصبح مستحيلة للمهاجم لأنه
لا توجد جلسة أصلاً.

```diff
diff --git a/connectors/telegram_bot_legacy.py b/connectors/telegram_bot_legacy.py
index b5df3b7..4a35a71 100644
--- a/connectors/telegram_bot_legacy.py
+++ b/connectors/telegram_bot_legacy.py
@@ -111,6 +111,18 @@ def send(chat_id: int, text: str, reply_markup: dict | None = None):
         api("sendMessage", payload)
 
 
+def _production_runtime() -> bool:
+    """True when running on a managed production host (Railway).
+
+    T3-OptionA: production identity must be pinned by TELEGRAM_ALLOWED_CHAT_ID;
+    the local dev flow (file capture) is kept for non-production runs only.
+    """
+    return any(os.environ.get(key, "").strip() for key in (
+        "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME",
+        "RAILWAY_PROJECT_ID", "RAILWAY_PUBLIC_DOMAIN",
+    ))
+
+
 def _owner_id():
     if ALLOWED_CHAT_ID:
         return ALLOWED_CHAT_ID
@@ -126,6 +138,12 @@ def _authorized(chat_id: int, chat_type: str):
         return str(chat_id) == owner
     if chat_type != "private":
         return False
+    if _production_runtime():
+        # T3-OptionA fail-closed: never hand ownership to whoever messages first.
+        print("SECURITY: TELEGRAM_ALLOWED_CHAT_ID is unset in production and no owner "
+              "file exists; refusing to auto-bind the first private chat as owner.",
+              flush=True)
+        return False
     OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
     OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
     return True
diff --git a/connectors/telegram_webhook_runtime.py b/connectors/telegram_webhook_runtime.py
index f44ad8f..ac55e57 100644
--- a/connectors/telegram_webhook_runtime.py
+++ b/connectors/telegram_webhook_runtime.py
@@ -482,6 +482,15 @@ bot.command_brief = _command_brief_v21
 
 
 def run():
+    # T3-OptionA fail-closed boot: Railway must never serve the bot with an
+    # unpinned owner identity. Losing the volume (or a fresh container) would
+    # otherwise hand /confirm rights to the first private chat that messages.
+    # (bot here is the telegram_bot_legacy module, via telegram_webhook.bot.)
+    if bot._production_runtime() and not bot.ALLOWED_CHAT_ID:
+        raise RuntimeError(
+            "Refusing to start: TELEGRAM_ALLOWED_CHAT_ID must be set in Railway so the "
+            "owner identity is pinned. (T3-OptionA fail-closed)"
+        )
     state = google_credentials.status()
     print(
         "Sheets production route: "
```

## الخيار B — تحذير فقط + ظهور الحالة في أسطح الحالة

السلوك الحالي يبقى (ربط تلقائي عند أول محادثة خاصة) لكن:
- سطر تحذير صريح في اللوج لحظة الربط التلقائي.
- سطر حالة ملوّن في `/selftest` وفي رأس `/storage_status` بثلاث حالات:
  مثبّت بالمتغير ✅ / مثبّت بملف فقط ⚠️ / لا مالك 🚨. (ملاحظة: لا يوجد أمر `/status` حرفي
  في هذه النسخة؛ هذان هما سطح الحالة الفعلي، وأُضيف السطر إليهما.)
- تحذير عند إقلاع الـ runtime إذا غاب المتغير.

**الأثر:** صفر كسر للإقلاع، لكن نافذة الاستيلاء تبقى مفتوحة؛ التحذير يرفع احتمالية اكتشافها
فقط إذا قرأ أحد اللوج أو أمر الحالة بعد كل إعادة نشر.

```diff
diff --git a/connectors/telegram_bot_legacy.py b/connectors/telegram_bot_legacy.py
index b5df3b7..96ade27 100644
--- a/connectors/telegram_bot_legacy.py
+++ b/connectors/telegram_bot_legacy.py
@@ -30,6 +30,7 @@ INTAKE_TAB = os.environ.get("GOOGLE_INTAKE_SHEET", "مدخلات الوكيل").
 CONVERSATION_TAB = os.environ.get("GOOGLE_CONVERSATIONS_SHEET", "محادثات الوكيل").strip()
 STATUS_TAB = os.environ.get("GOOGLE_STATUS_SHEET", "حالة الوكيل").strip()
 OWNER_FILE = BASE / "data" / ".telegram-owner-chat-id"
+_OWNER_AUTOBOUND = False
 API_BASE = f"https://api.telegram.org/bot{TOKEN}"
 _SHEETS_SERVICE = None
 _PENDING_SHEET_UPDATES = {}
@@ -128,6 +129,14 @@ def _authorized(chat_id: int, chat_type: str):
         return False
     OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
     OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
+    # T3-OptionB warn-only: ownership still self-binds (kept for dev flows), but
+    # every operator sees the risk in the log, /selftest, and /storage_status.
+    global _OWNER_AUTOBOUND
+    _OWNER_AUTOBOUND = True
+    print(f"SECURITY WARNING: first private chat auto-bound as owner ({chat_id}). "
+          "If data/.telegram-owner-chat-id is lost (container rebuild, no volume), the NEXT "
+          "private chat becomes owner and can run /confirm. "
+          "Set TELEGRAM_ALLOWED_CHAT_ID in Railway now.", flush=True)
     return True
 
 
@@ -884,11 +893,23 @@ def _selftest():
     ok = sum(1 for _, passed, _ in checks if passed)
     lines = [f"🩺 Self-test: {ok}/{len(checks)} ناجح"]
     lines.extend(f"{'✅' if passed else '❌'} {name}: {detail}" for name, passed, detail in checks)
-    lines.append("\n🔐 الحماية: TELEGRAM_ALLOWED_CHAT_ID مفعّل." if ALLOWED_CHAT_ID
-                 else "\n🔐 الحماية: المالك مثبت تلقائيًا.")
+    lines.append("\n" + _owner_guard_line())
     return "\n".join(lines)
 
 
+def _owner_guard_line():
+    """T3-OptionB: one-line owner-identity status for /selftest and /storage_status."""
+    if ALLOWED_CHAT_ID:
+        return "🔐 الحماية: المالك مثبت عبر TELEGRAM_ALLOWED_CHAT_ID."
+    owner = _owner_id()
+    if owner:
+        return ("⚠️ الحماية: المالك مثبت عبر ملف فقط (" + owner + "). فقدان الملف "
+                "(إعادة بناء الحاوية بدون volume) يسلم الملكية لأول محادثة خاصة "
+                "تراسل البوت وتسمح لها بـ /confirm. اضبط TELEGRAM_ALLOWED_CHAT_ID الآن.")
+    return ("🚨 الحماية: لا يوجد مالك مثبت؛ أي محادثة خاصة أولى ستصبح المالك وتنفّذ "
+            "/confirm. اضبط TELEGRAM_ALLOWED_CHAT_ID فورًا.")
+
+
 def command_selftest(chat_id: int):
     send(chat_id, _selftest())
 
diff --git a/connectors/telegram_webhook_runtime.py b/connectors/telegram_webhook_runtime.py
index f44ad8f..857fcc1 100644
--- a/connectors/telegram_webhook_runtime.py
+++ b/connectors/telegram_webhook_runtime.py
@@ -93,6 +93,8 @@ def _direct_error_text(exc: Exception) -> str:
 
 def _command_storage_status(chat_id: int):
     """Diagnose the direct Sheets route without hiding it behind Apps Script fallback."""
+    # T3-OptionB: surface the owner-identity guard on the status surface.
+    bot.send(chat_id, bot._owner_guard_line())
     info = google_credentials.service_account_info()
     if not info or not bot.GOOGLE_SHEET_ID:
         bot.send(
@@ -489,6 +491,10 @@ def run():
         + f" | service_account={state.get('source')} valid={state.get('valid')}",
         flush=True,
     )
+    if not bot.ALLOWED_CHAT_ID:
+        print("SECURITY WARNING: TELEGRAM_ALLOWED_CHAT_ID is not set; owner identity is "
+              "bound at first contact via data/.telegram-owner-chat-id and is lost with "
+              "the container. (T3-OptionB: warn-only, no startup failure.)", flush=True)
     print("Direct Brief v2.1 Calendar override: active", flush=True)
     webhook.run()
```

## التوصية

**A** (أو A+B معاً: الحارس عند الإقلاع + سطر الحالة). القاعدة الحاكمة أن أي أثر خارجي يمر
بموافقة المالك؛ نظام يسلّم صلاحية الموافقة لأول وارد هو ثغرة حوكمة قبل أن تكون ثغرة أمنية.
تكلفة A منخفضة عملياً: المتغير مضبوط أصلاً في Railway (سطر التخصيص `🔐 الحماية: TELEGRAM_ALLOWED_CHAT_ID مفعّل`
يدل على أنه استُخدم)، والتراجع عن A سهل بإعادة المتغير.

**قرار مطلوب من المالك:** نعم — اختيار A أو B (أو رفض الاثنين مع خطة بديلة).
**المدة المقترحة:** قبل دمج أي PR يتضمن gateway v1.0، لأن `update` المعتمد على `/confirm`
يصبح أقوى بعد v1.0.

## تعليمات التركيب عند القرار

```bash
git checkout arena/01a08d85-personal-ai-agent
git apply docs/t3-optionA.diff   # أو t3-optionB.diff
python3 -m unittest $(ls tests/test_*.py | sed 's#/#.#; s#\.py$##')
```

الملفان محفوظان في هذا الدليل بجانب هذه الورقة.
