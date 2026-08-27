# -*- coding: utf-8 -*-
"""Telegram runtime command for explicit multi-model council review."""
from __future__ import annotations

import re


def install(bot):
    if getattr(bot, "_AI_OS_COUNCIL_COMMAND", False):
        return

    original = bot.handle_message
    council_re = re.compile(r"^/council(?:@\w+)?(?:\s+(.+))?$", re.I | re.S)

    def handle_message(message: dict):
        text = message.get("text") or ""
        match = council_re.match(text.strip())
        if not match:
            return original(message)

        chat_id = ((message.get("chat") or {}).get("id"))
        if chat_id is None:
            return None
        question = (match.group(1) or "").strip()
        if not question:
            bot.send(chat_id, "استخدم: /council ثم اكتب القرار أو السؤال الذي تريد من Claude + GPT + Gemini مراجعته.")
            return None
        if bot._clinical_hint(question):
            bot.send(chat_id, "🔐 AI Council غير مفعّل للمحتوى السريري/الحساس. سيبقى هذا النوع على المسار المحمي الحالي.")
            return None

        try:
            from engine.ai_council import consult, format_for_telegram
            bot.send(chat_id, "🧠 أشغّل AI Council: Claude + GPT + Gemini ثم Judge...")
            record = consult(question, sensitive=False, persist=True)
            bot.send(chat_id, format_for_telegram(record))
        except Exception as exc:  # noqa: BLE001 - user-visible command boundary
            print(f"AI Council command error: {str(exc)[:300]}", flush=True)
            bot.send(chat_id, f"❌ تعذر تشغيل AI Council: {str(exc)[:180]}")
        return None

    bot.handle_message = handle_message
    bot._AI_OS_COUNCIL_COMMAND = True
