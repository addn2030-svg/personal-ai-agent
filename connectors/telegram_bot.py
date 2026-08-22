# -*- coding: utf-8 -*-
"""Telegram command bot for Abdulrahman AI OS.

Uses Telegram long polling and only Python's standard library.
Required environment variable: TELEGRAM_BOT_TOKEN
Optional: TELEGRAM_ALLOWED_CHAT_ID (recommended for a fixed owner).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
OWNER_FILE = BASE / "data" / ".telegram-owner-chat-id"
API_BASE = f"https://api.telegram.org/bot{TOKEN}"


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
    # First private chat to use the bot becomes its local owner.
    if chat_type != "private":
        return False
    OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    OWNER_FILE.write_text(str(chat_id), encoding="utf-8")
    return True


def command_start(chat_id: int):
    send(
        chat_id,
        "أهلًا عبدالرحمن، وكيلك الشخصي متصل ✅\n\n"
        "الأوامر المتاحة:\n"
        "/profile — ملفك المهني المختصر\n"
        "/sources — مصادر معرفة الوكيل\n"
        "/selftest — فحص الاتصال والمكونات\n"
        "/help — عرض المساعدة\n\n"
        f"Telegram Chat ID: {chat_id}"
    )


def command_profile(chat_id: int):
    send(
        chat_id,
        "👤 الملف المهني\n"
        "الاسم: عبدالرحمن بكر هوساوي\n"
        "الدور: رئيس قسم التأهيل وأخصائي علاج طبيعي أول\n"
        "التخصص: التقييم المتقدم للحركة والألم وإعادة التأهيل\n"
        "المنهج: IMTAF مع NKT والعلاج اليدوي والإبر الجافة\n"
        "النظام: Abdulrahman AI OS — وكيل Chief of Staff ومهارات سريرية وإدارية وتعليمية\n"
        "الخصوصية: المرضى برموز مجهلة، والقرارات السريرية والإرسال الخارجي تتطلب مراجعة بشرية."
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
                1 for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
            )
        total += count
        lines.append(f"• {label}: {count} ملف")
    lines.append(f"\nالإجمالي القابل للفهرسة: {total} ملف")
    lines.append("المصدر التشغيلي: مستودع personal-ai-agent، الفرع main")
    return "\n".join(lines)


def command_sources(chat_id: int):
    send(chat_id, _source_summary())


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
    ok = sum(1 for _, passed, _ in checks if passed)
    lines = [f"🩺 Self-test: {ok}/{len(checks)} ناجح"]
    lines.extend(f"{'✅' if passed else '❌'} {name}: {detail}" for name, passed, detail in checks)
    if not ALLOWED_CHAT_ID:
        lines.append("\n🔐 الحماية: المالك مثبت تلقائيًا لأول محادثة خاصة.")
    else:
        lines.append("\n🔐 الحماية: TELEGRAM_ALLOWED_CHAT_ID مفعّل.")
    return "\n".join(lines)


def command_selftest(chat_id: int):
    send(chat_id, _selftest())


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
    }
    handler = handlers.get(command)
    if handler:
        handler(chat_id)
    elif text:
        send(chat_id, "أرسل أحد الأوامر: /profile /sources /selftest /help")


def configure_commands():
    commands = json.dumps([
        {"command": "start", "description": "تشغيل الوكيل"},
        {"command": "profile", "description": "عرض الملف المهني"},
        {"command": "sources", "description": "عرض مصادر المعرفة"},
        {"command": "selftest", "description": "فحص المكونات والاتصال"},
        {"command": "help", "description": "المساعدة"},
    ], ensure_ascii=False)
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
                {"timeout": 45, "offset": offset, "allowed_updates": json.dumps(["message"])},
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
                            send(chat_id, f"❌ تعذر تنفيذ الأمر: {str(exc)[:180]}")
        except KeyboardInterrupt:
            print("Telegram polling stopped.", flush=True)
            return
        except Exception as exc:
            print(f"Telegram polling error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
