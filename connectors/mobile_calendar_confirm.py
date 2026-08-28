"""Mobile-friendly explicit Calendar confirmation runtime.

Keeps Calendar writes behind an explicit /confirm_event action while allowing the
command to omit its token when exactly one unexpired event is pending for that chat.
"""
from __future__ import annotations

import time


def install(bot):
    if getattr(bot, "_mobile_calendar_confirm_installed", False):
        return bot

    original = bot.command_confirm_event

    def command_confirm_event_mobile(chat_id: int, token: str = ""):
        supplied = (token or "").strip()
        if supplied:
            return original(chat_id, supplied)

        now = time.time()
        active = []
        for pending_token, item in list(bot._PENDING_CALENDAR_EVENTS.items()):
            if item.get("expires", 0) < now:
                bot._PENDING_CALENDAR_EVENTS.pop(pending_token, None)
                continue
            if str(item.get("chat_id", "")) == str(chat_id):
                active.append(pending_token)

        if len(active) == 1:
            return original(chat_id, active[0])
        if not active:
            bot.send(chat_id, "❌ لا يوجد موعد واحد صالح بانتظار الاعتماد. أنشئ معاينة جديدة أولًا عبر /remind.")
            return None

        bot.send(
            chat_id,
            "⚠️ يوجد أكثر من موعد بانتظار الاعتماد. حفاظًا على الأمان، أرسل أمر الاعتماد الكامل الموجود تحت المعاينة المطلوبة: /confirm_event TOKEN",
        )
        return None

    bot.command_confirm_event = command_confirm_event_mobile
    bot._mobile_calendar_confirm_installed = True
    return bot
