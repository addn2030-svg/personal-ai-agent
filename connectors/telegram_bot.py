# -*- coding: utf-8 -*-
"""Secure Telegram interface for Abdulrahman AI OS.

Commands use local deterministic handlers. Normal text is captured in the
Unified Inbox and answered by Claude through Amazon Bedrock.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "engine"))

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1").strip()
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
).strip()
OWNER_FILE = BASE / "data" / ".telegram-owner-chat-id"
API_BASE = f"https://api.telegram.org/bot{TOKEN}"

SYSTEM_PROMPT = """You are Abdulrahman AI OS, the private Chief of Staff for
Abdulrahman Bakor Howsawy, Senior Physical Therapist and Head of Rehabilitation.
Answer in Arabic by default; answer in English when the user writes in English.
Be concise, practical, and distinguish confirmed facts from assumptions.
Never claim autonomous self-learning: durable changes require review and approval.
Never reveal credentials, tokens, private contact details, or patient identities.
For clinical questions, provide decision support only, identify red flags, and
state that final clinical decisions require professional review. External actions
and sensitive decisions always require Abdulrahman's approval.
"""


def api(method: str, payload: dict | None = None, timeout: int = 60):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    body = urllib.parse.urlencode(payload or {}).encode("utf-8")
    request = urllib.request.Request(f"{API_BASE}/{method}", data=body)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data.get("result")


def send(chat_id: int, text: str):
    text = str(text)
    for start in range(0, len(text), 3800):
        api("sendMessage", {"chat_id": chat_id, "text": text[start:start + 3800]})


def _owner_id():
    if ALLOWED_CHAT_ID:
        return ALLOWED_CHAT_ID
    try:
        return OWNER_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authorized(chat_id: int, chat_type: str):
    owner = _owner_id()
    if owner:
        return str(chat_id) == owner
    if chat_type != "private":
        return False
    OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
    return True


def command_start(chat_id: int):
    send(
        chat_id,
        "أهلًا عبدالرحمن، وكيلك الشخصي متصل ويستقبل الأسئلة ✅\n\n"
        "يمكنك كتابة أي سؤال مباشرة بالعربية أو الإنجليزية.\n\n"
        "الأوامر:\n"
        "/profile — ملفك المهني المختصر\n"
        "/sources — مصادر معرفة الوكيل\n"
        "/selftest — فحص الاتصال والمكونات\n"
        "/ai_status — فحص إعداد Claude على AWS\n"
        "/help — المساعدة\n\n"
        f"Telegram Chat ID: {chat_id}",
    )


def command_profile(chat_id: int):
    send(
        chat_id,
        "👤 الملف المهني\n"
        "الاسم: عبدالرحمن بكر هوساوي\n"
        "الدور: رئيس قسم التأهيل وأخصائي علاج طبيعي أول\n"
        "التخصص: التقييم المتقدم للحركة والألم وإعادة التأهيل\n"
        "المنهج: IMTAF مع NKT والعلاج اليدوي والإبر الجافة\n"
        "النظام: Abdulrahman AI OS — Chief of Staff ومهارات سريرية وإدارية وتعليمية\n"
        "الخصوصية: المرضى برموز مجهلة، والقرار السريري والإرسال الخارجي يتطلبان مراجعة بشرية.",
    )


def _source_summary():
    groups = [
        ("المعرفة", BASE / "knowledge"),
        ("المهارات", BASE / "skills"),
        ("المحفزات", BASE / "prompts"),
        ("المواد التعليمية", BASE / "materials"),
        ("الوثائق", BASE / "docs"),
    ]
    lines = ["📚 مصادر الوكيل"]
    total = 0
    for label, path in groups:
        count = 0
        if path.exists():
            count = sum(
                1
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
            )
        total += count
        lines.append(f"• {label}: {count} ملف")
    lines.append(f"\nالإجمالي القابل للفهرسة: {total} ملف")
    lines.append("المصدر التشغيلي: مستودع personal-ai-agent، الفرع main")
    return "\n".join(lines)


def command_sources(chat_id: int):
    send(chat_id, _source_summary())


def _bedrock_configured():
    auth = bool(
        os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        or (
            os.environ.get("AWS_ACCESS_KEY_ID")
            and os.environ.get("AWS_SECRET_ACCESS_KEY")
        )
    )
    return auth and bool(AWS_REGION) and bool(BEDROCK_MODEL_ID)


def command_ai_status(chat_id: int):
    if _bedrock_configured():
        send(
            chat_id,
            "🤖 Claude on AWS Bedrock: configured ✅\n"
            f"Region: {AWS_REGION}\nModel: {BEDROCK_MODEL_ID}\n"
            "أرسل سؤالًا عاديًا لاختبار الإجابة.",
        )
    else:
        send(
            chat_id,
            "❌ إعداد AWS Bedrock غير مكتمل. تحقق من Railway Variables: "
            "AWS_BEARER_TOKEN_BEDROCK أو AWS credentials، وAWS_REGION، وBEDROCK_MODEL_ID.",
        )


def _selftest():
    checks = []
    try:
        me = api("getMe", timeout=20)
        checks.append(("Telegram API", True, "@" + str(me.get("username", ""))))
    except Exception as exc:
        checks.append(("Telegram API", False, str(exc)[:120]))
    for name, path in [
        ("Manager", BASE / "engine" / "manager.py"),
        ("Chief of Staff", BASE / "engine" / "chief_of_staff.py"),
        ("Store", BASE / "engine" / "store.py"),
        ("Knowledge", BASE / "knowledge"),
        ("Skills", BASE / "skills"),
    ]:
        checks.append((name, path.exists(), "موجود" if path.exists() else "مفقود"))
    checks.append(
        ("Claude / Bedrock", _bedrock_configured(), "مهيأ" if _bedrock_configured() else "غير مهيأ")
    )
    ok = sum(1 for _, passed, _ in checks if passed)
    lines = [f"🩺 Self-test: {ok}/{len(checks)} ناجح"]
    lines.extend(
        f"{'✅' if passed else '❌'} {name}: {detail}"
        for name, passed, detail in checks
    )
    lines.append(
        "\n🔐 الحماية: TELEGRAM_ALLOWED_CHAT_ID مفعّل."
        if ALLOWED_CHAT_ID
        else "\n🔐 الحماية: المالك مثبت تلقائيًا لأول محادثة خاصة."
    )
    return "\n".join(lines)


def command_selftest(chat_id: int):
    send(chat_id, _selftest())


def _clinical_hint(text: str):
    return bool(
        re.search(
            r"patient|مريض|mrn|medical record|رقم الملف|diagnosis|تشخيص|"
            r"clinical|سريري|pain|ألم|علاج|دواء|عملية",
            text,
            re.I,
        )
    )


def _capture(text: str, message: dict):
    try:
        from unified_inbox import add, classify

        ref = f"telegram:{message.get('message_id', '')}"
        iid = add(
            "TELEGRAM",
            text,
            kind="TEXT",
            source_ref=ref,
            sensitive=_clinical_hint(text),
            metadata={"chat_id": str((message.get("chat") or {}).get("id", ""))},
        )
        if _clinical_hint(text):
            classify(iid, "CLINICAL_PRIVATE", "Specialist review required")
        return iid
    except Exception as exc:
        print(f"Telegram intake capture error: {exc}", flush=True)
        return ""


def ask_bedrock(text: str):
    if not _bedrock_configured():
        raise RuntimeError("AWS Bedrock variables are not configured")
    import boto3

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": 1200, "temperature": 0.2},
    )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    answer = "\n".join(block.get("text", "") for block in blocks if block.get("text"))
    if not answer:
        raise RuntimeError("Claude returned an empty response")
    return answer


def handle_message(message: dict):
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = (message.get("text") or "").strip()
    command = text.split()[0].split("@")[0].lower() if text else ""
    if not _authorized(chat_id, chat.get("type", "")):
        send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
        return

    handlers = {
        "/start": command_start,
        "/help": command_start,
        "/profile": command_profile,
        "/sources": command_sources,
        "/selftest": command_selftest,
        "/ai_status": command_ai_status,
    }
    handler = handlers.get(command)
    if handler:
        handler(chat_id)
    elif command.startswith("/"):
        send(chat_id, "أمر غير معروف. استخدم /help")
    elif text:
        _capture(text, message)
        api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        send(chat_id, ask_bedrock(text))
    else:
        send(chat_id, "أرسل سؤالًا نصيًا أو استخدم /help. دعم الصوت والملفات يأتي في المرحلة التالية.")


def configure_commands():
    commands = json.dumps(
        [
            {"command": "start", "description": "تشغيل الوكيل"},
            {"command": "profile", "description": "عرض الملف المهني"},
            {"command": "sources", "description": "عرض مصادر المعرفة"},
            {"command": "selftest", "description": "فحص المكونات والاتصال"},
            {"command": "ai_status", "description": "فحص Claude على AWS"},
            {"command": "help", "description": "المساعدة"},
        ],
        ensure_ascii=False,
    )
    api("setMyCommands", {"commands": commands})


def run():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    me = api("getMe", timeout=20)
    configure_commands()
    print(f"Telegram polling enabled for @{me.get('username')}", flush=True)
    offset = 0
    while True:
        try:
            updates = api(
                "getUpdates",
                {
                    "timeout": 45,
                    "offset": offset,
                    "allowed_updates": json.dumps(["message"]),
                },
                timeout=55,
            )
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                if update.get("message"):
                    try:
                        handle_message(update["message"])
                    except Exception as exc:
                        chat_id = (update["message"].get("chat") or {}).get("id")
                        if chat_id is not None:
                            send(chat_id, f"❌ تعذر تنفيذ الطلب: {str(exc)[:220]}")
        except KeyboardInterrupt:
            print("Telegram polling stopped.", flush=True)
            return
        except Exception as exc:
            print(f"Telegram polling error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
