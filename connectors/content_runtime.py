# -*- coding: utf-8 -*-
"""Telegram surface for the multi-agent Content Creator."""
from __future__ import annotations

import json

from connectors import content_creator
from connectors import content_sheet
from connectors import task_delegation as team

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
        legacy.send(chat_id, "\n✍️ Content Creator Agent\n/content idea — multi-agent draft\n"
                    "/approve_content ID CODE — send approved draft to Buffer\n"
                    "/reject_content ID — reject draft\n/content_status — connection and recent drafts")
        legacy.send(chat_id, "📊 /content_sheet [Q-ID] — draft next/specific queue row\n"
                    "/content_sheet_status — verify workbook connection")

    def configure_commands():
        original_configure()
        try:
            commands = legacy.api("getMyCommands") or []
            existing = {str(x.get("command", "")) for x in commands}
            additions = [
                {"command": "content", "description": "Create a reviewed social-media draft"},
                {"command": "approve_content", "description": "Approve draft and send to Buffer"},
                {"command": "reject_content", "description": "Reject a content draft"},
                {"command": "content_status", "description": "Content Creator and Buffer status"},
                {"command": "content_sheet", "description": "Create draft from publishing queue"},
                {"command": "content_sheet_status", "description": "Content workbook connection status"},
            ]
            commands.extend(x for x in additions if x["command"] not in existing)
            legacy.api("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})
        except Exception as exc:
            print(f"Content command menu warning: {exc}", flush=True)

    def model_call(role: str, prompt: str) -> str:
        agent = {"researcher": "gemini", "critic": "gpt", "creator": "claude"}[role]
        # Content calls are intentionally compact.  Besides reducing cost, these
        # ceilings keep a low OpenRouter balance from rejecting the whole workflow
        # merely because the requested completion limit is larger than affordable.
        budgets = {"researcher": 300, "critic": 250, "creator": 600}
        budget = budgets[role]
        try:
            kwargs = {"max_tokens": budget, "temperature": 0.15}
            if role == "creator":
                kwargs["response_format"] = {"type": "json_object"}
            return team._openrouter_agent(agent, prompt, **kwargs).answer
        except RuntimeError as exc:
            if "HTTP 402" not in str(exc):
                raise
            # One smaller retry is useful when the remaining credit changes between
            # the three orchestra calls.  If it also fails, surface the real 402.
            retry_budget = {"researcher": 180, "critic": 160, "creator": 350}[role]
            kwargs = {"max_tokens": retry_budget, "temperature": 0.1}
            if role == "creator":
                kwargs["response_format"] = {"type": "json_object"}
            return team._openrouter_agent(agent, prompt, **kwargs).answer

    def handle_message(message: dict):
        raw = (message.get("text") or message.get("caption") or "").strip()
        command = raw.split()[0].split("@")[0].lower() if raw else ""
        supported = command in {"/content", "/approve_content", "/reject_content", "/content_status",
                                "/content_sheet", "/content_sheet_status"}
        if not supported:
            return original_handle(message)
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        if not legacy._authorized(chat_id, chat.get("type", "")):
            legacy.send(chat_id, "⛔ This chat is not authorized.")
            return
        text, kind, attachment = legacy._message_payload(message)
        iid = legacy._local_capture(text, message, kind)
        try:
            if command == "/content_status":
                answer = content_creator.status_text()
            elif command == "/content_sheet_status":
                answer = content_sheet.status_text()
            elif command == "/content_sheet":
                parts = raw.split(maxsplit=1)
                queue_id = parts[1].strip() if len(parts) == 2 else None
                legacy.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                row = content_sheet.create_preview(queue_id, chat_id=chat_id, model_call=model_call)
                answer = content_creator.render_preview(row) + f"\n\nSheet row: {row.get('source_queue_id')} ✅"
            elif command == "/approve_content":
                parts = raw.split()
                if len(parts) != 3:
                    raise ValueError("Usage: /approve_content CONTENT-ID CODE")
                receipt = content_creator.execute(parts[1], parts[2])
                answer = (f"✅ Buffer receipt\nPost: {receipt.get('post_id')}\n"
                          f"Status: {receipt.get('status')}\nChannel: {receipt.get('channel_id')}")
            elif command == "/reject_content":
                parts = raw.split()
                if len(parts) != 2:
                    raise ValueError("Usage: /reject_content CONTENT-ID")
                row = content_creator.reject(parts[1])
                answer = f"🚫 Rejected {row['action_id']}; nothing was sent to Buffer."
            else:
                idea = raw[len(command):].strip()
                platform = None
                first, separator, remainder = idea.partition(" ")
                if first.lower() in content_creator.ALLOWED_PLATFORMS and separator:
                    platform, idea = first.lower(), remainder.strip()
                legacy.api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                row = content_creator.create_content_preview(
                    idea, chat_id=chat_id, model_call=model_call, platform=platform
                )
                answer = content_creator.render_preview(row)
            legacy.send(chat_id, answer)
            legacy._save_intake(iid, message, text, kind, attachment, "COMPLETED")
        except Exception as exc:
            legacy.send(chat_id, "❌ " + str(exc)[:1200])
            legacy._save_intake(iid, message, text, kind, attachment, "ERROR", error=exc)

    legacy.handle_message = handle_message
    legacy.command_start = command_start
    legacy.configure_commands = configure_commands
    _INSTALLED = True
