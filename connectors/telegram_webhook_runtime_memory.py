# -*- coding: utf-8 -*-
"""Production runtime wrapper that adds guarded Google Drive project memory.

This keeps telegram_webhook_runtime.py as the canonical production runtime and
only intercepts the four memory commands before delegating every other update to
the existing handler.
"""
from __future__ import annotations

import re

from connectors import project_memory
from connectors import telegram_webhook_runtime as runtime

bot = runtime.bot
_original_handle_message = bot.handle_message

_MEMORY_COMMANDS = {"/memory", "/memory_status", "/update_memory", "/confirm_memory"}
_NATURAL_UPDATE = re.compile(r"^(?:حدث|حدّث|تحديث)\s+ذاكرة\s+المشروع\s*[:：-]?\s*(.+)$", re.I | re.S)


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


def handle_message(message: dict):
    if _memory_message(message):
        return
    return _original_handle_message(message)


# telegram_webhook._process_update resolves bot.handle_message at runtime, so this
# patch is installed before runtime.run() configures the webhook and starts serving.
bot.handle_message = handle_message


def run():
    print(
        "Project Memory runtime: active | "
        f"service_account={project_memory.service_account_email()} | "
        "commands=/memory,/memory_status,/update_memory,/confirm_memory",
        flush=True,
    )
    runtime.run()


if __name__ == "__main__":
    run()
