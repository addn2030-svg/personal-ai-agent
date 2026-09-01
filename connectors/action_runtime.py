# -*- coding: utf-8 -*-
"""Install Natural Action Executor onto the existing Telegram runtime."""
from __future__ import annotations

import json

from connectors import action_executor
from connectors import capability_truth

_INSTALLED = False


def install():
    global _INSTALLED
    if _INSTALLED:
        return

    from connectors import telegram_bot_legacy as legacy

    original_handle = legacy.handle_message
    original_start = legacy.command_start
    original_configure = legacy.configure_commands

    def command_start(chat_id: int):
        original_start(chat_id)
        legacy.send(
            chat_id,
            "\n🛠 التنفيذ الطبيعي\n"
            "/act الطلب — جهّز Preview بدون تنفيذ\n"
            "/approve_action ID CODE — وافق ونفّذ مع إيصال\n"
            "/reject_action ID — ارفض التغيير\n"
            "/action_status — آخر إجراءات الوكيل\n"
            "/capabilities — القدرات الفعلية المتصلة\n"
            "أو اكتب: نفذ تحديث المشروع إلى 50% ... وسيبقى التنفيذ خلف موافقتك.",
        )

    def configure_commands():
        original_configure()
        try:
            commands = legacy.api("getMyCommands") or []
            existing = {str(item.get("command", "")) for item in commands}
            additions = [
                {"command": "act", "description": "معاينة إجراء طبيعي قبل التنفيذ"},
                {"command": "approve_action", "description": "اعتماد وتنفيذ Action مع إيصال"},
                {"command": "reject_action", "description": "رفض Action معلق"},
                {"command": "action_status", "description": "حالة آخر Actions"},
                {"command": "capabilities", "description": "القدرات الفعلية للوكيل"},
            ]
            commands.extend(x for x in additions if x["command"] not in existing)
            legacy.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:
            print(f"Natural action command menu warning: {exc}", flush=True)

    def handle_message(message: dict):
        raw = (message.get("text") or message.get("caption") or "").strip()
        command = raw.split()[0].split("@")[0].lower() if raw else ""
        natural, objective = action_executor.natural_request(raw)
        supported = command in {
            "/act", "/approve_action", "/reject_action", "/action_status", "/capabilities"
        }
        if not supported and not natural:
            return original_handle(message)

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        if not legacy._authorized(chat_id, chat.get("type", "")):
            legacy.send(chat_id, "⛔ هذه المحادثة غير مصرح لها باستخدام الوكيل.")
            return

        text, kind, attachment = legacy._message_payload(message)
        iid = legacy._local_capture(text, message, kind)
        if kind != "TEXT":
            legacy.send(chat_id, "ميزة التنفيذ الطبيعي تبدأ من النص/النص المفرغ؛ لا تنفذ ملفًا خامًا مباشرة.")
            legacy._save_intake(iid, message, text, kind, attachment, "ERROR", error="ACTION_TEXT_ONLY")
            return

        try:
            legacy.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            if command == "/capabilities":
                answer = capability_truth.capability_summary_response(raw)
            elif command == "/action_status":
                answer = action_executor.status_text()
            elif command == "/approve_action":
                parts = raw.split()
                if len(parts) != 3:
                    raise ValueError("الاستخدام: /approve_action ACTION_ID CODE")
                result = action_executor.execute(parts[1], parts[2])
                answer = action_executor.render_receipt(result)
            elif command == "/reject_action":
                parts = raw.split()
                if len(parts) != 2:
                    raise ValueError("الاستخدام: /reject_action ACTION_ID")
                row = action_executor.reject(parts[1])
                answer = f"🚫 تم رفض {row.get('action_id')} — لا توجد تغييرات خارجية جديدة."
            else:
                value = objective if natural else raw[len(command):].strip()
                if not value:
                    raise ValueError("NEEDS_INPUT: اكتب التغيير المطلوب بعد /act")
                preview = action_executor.create_preview(
                    value,
                    chat_id=chat_id,
                    message_id=message.get("message_id", ""),
                )
                answer = action_executor.render_preview(preview)
            legacy.send(chat_id, answer)
            legacy._save_intake(iid, message, text, kind, attachment, "COMPLETED")
        except Exception as exc:
            legacy.send(chat_id, "❌ " + str(exc)[:1200])
            legacy._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)

    legacy.handle_message = handle_message
    legacy.command_start = command_start
    legacy.configure_commands = configure_commands
    _INSTALLED = True
