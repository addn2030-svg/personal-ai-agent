# -*- coding: utf-8 -*-
"""Production runtime wrapper that adds guarded Google Drive project memory.

This keeps telegram_webhook_runtime.py as the canonical production runtime and
only intercepts the four memory commands before delegating every other update to
the existing handler.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Running this file as a script (`python3 connectors/telegram_webhook_runtime_memory.py`,
# which is what the container CMD used) puts /app/connectors — not /app — on sys.path,
# so `from connectors import ...` raised ModuleNotFoundError and crash-looped the
# deploy. Bootstrap the repo root first, exactly like connectors/telegram_webhook.py.
BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import brain
from connectors import project_memory
from connectors import telegram_webhook_runtime as runtime

bot = runtime.bot
_original_handle_message = bot.handle_message

_MEMORY_COMMANDS = {"/memory", "/memory_status", "/update_memory", "/confirm_memory"}
_NATURAL_UPDATE = re.compile(r"^(?:حدث|حدّث|تحديث)\s+ذاكرة\s+المشروع\s*[:：-]?\s*(.+)$", re.I | re.S)

# الدماغ الدائم: قراءة فقط من الجوال — لا أمر تيليجرام يكتب صفًا واحدًا.
# السبب مقصود: الرفع الجماعي (`python3 -m connectors.brain --import`) عملية
# تُراجع في الطرفية، وأوامر الجوال تبقى للتشخيص والاسترجاع.
_BRAIN_COMMANDS = {"/brain_status", "/brain", "/brain_recall"}


def _command(raw: str) -> str:
    if not raw:
        return ""
    return raw.split()[0].split("@")[0].lower()


def _memory_message(message: dict) -> bool:
    raw = str(message.get("text") or message.get("caption") or "").strip()
    command = _command(raw)
    natural = _NATURAL_UPDATE.match(raw)
    if command not in _MEMORY_COMMANDS and not natural:
        return False

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return True
    if not bot._authorized(chat_id, chat.get("type", "")):
        bot.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام ذاكرة المشروع.")
        return True

    try:
        if command == "/memory_status":
            bot.send(chat_id, project_memory.status_text())
            return True

        if command == "/memory":
            bot.send(chat_id, project_memory.read_memory())
            return True

        if command == "/confirm_memory":
            token = raw[len(raw.split()[0]):].strip()
            bot.send(chat_id, project_memory.confirm(token))
            return True

        if command == "/update_memory":
            payload = raw[len(raw.split()[0]):].strip()
        else:
            payload = natural.group(1).strip() if natural else ""
        _, preview = project_memory.prepare(payload)
        bot.send(chat_id, preview)
        return True
    except Exception as exc:  # Google/validation boundary; keep Telegram alive
        bot.send(chat_id, f"❌ Project Memory: {str(exc)[:320]}")
        return True


def _format_recall(result) -> str:
    items = (result.data or {}).get("items") or []
    if not items:
        tail = f"\n⚠️ {result.error[:200]}" if result.error else ""
        return "🧠 لا نتائج في الذاكرة الدائمة لهذه الكلمات." + tail
    source = "Supabase" if (result.data or {}).get("source") == "supabase" else "محلي"
    lines = [f"🧠 استرجاع من الذاكرة الدائمة ({source}) — {len(items)} نتيجة:"]
    for item in items[:8]:
        snippet = " ".join(str(item["snippet"]).split())[:220]
        lines.append(f"\n• [{item['item_type']}] {item['occurred_at'][:16]}\n  {snippet}")
        if item.get("source_ref"):
            lines.append(f"  ↳ {item['source_ref'][:120]}")
    if result.error:
        lines.append(f"\n⚠️ {result.error[:200]}")
    return "\n".join(lines)


def _brain_message(message: dict) -> bool:
    raw = str(message.get("text") or message.get("caption") or "").strip()
    command = _command(raw)
    if command not in _BRAIN_COMMANDS:
        return False

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return True
    if not bot._authorized(chat_id, chat.get("type", "")):
        bot.send(chat_id, "⛔ هذه المحادثة غير مصرح لها بالوصول إلى الذاكرة الدائمة.")
        return True

    try:
        if command in ("/brain_status", "/brain"):
            bot.send(chat_id, brain.status_text())
            return True
        query = raw[len(raw.split()[0]):].strip()
        if not query:
            bot.send(chat_id, "اكتب الكلمات بعد الأمر: /brain_recall العقد مع العمير")
            return True
        bot.send(chat_id, _format_recall(brain.recall(query, limit=8)))
        return True
    except Exception as exc:  # حدود الشبكة/التخزين — نُبقي تيليجرام حيًّا
        bot.send(chat_id, f"❌ الذاكرة الدائمة: {str(exc)[:320]}")
        return True


def handle_message(message: dict):
    if _brain_message(message):
        return
    if _memory_message(message):
        return
    return _original_handle_message(message)


# telegram_webhook._process_update resolves bot.handle_message at runtime, so this
# patch is installed before runtime.run() configures the webhook and starts serving.
bot.handle_message = handle_message


def run():
    cap = brain.capability()
    print(
        "Project Memory runtime: active | "
        f"service_account={project_memory.service_account_email()} | "
        "commands=/memory,/memory_status,/update_memory,/confirm_memory",
        flush=True,
    )
    # سطر واحد يمنع الحالة الغامضة: على مضيف بلا قرص دائم يجب أن يكون الدماغ
    # الدائم مفعّلًا، وإلا فُقدت الذاكرة عند أول إيقاف (Render free: /tmp فقط).
    print(
        "Durable brain: "
        + ("active" if cap.can_read else "DORMANT")
        + f" | read={cap.can_read} write={cap.can_write} recall={cap.settings.recall}"
        + (f" | {cap.problem}" if cap.problem else "")
        + " | commands=/brain_status,/brain_recall",
        flush=True,
    )
    runtime.run()


if __name__ == "__main__":
    run()
