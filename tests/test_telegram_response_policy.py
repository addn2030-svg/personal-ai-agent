# -*- coding: utf-8 -*-
"""Offline regressions for concise replies at the actual Railway entrypoint."""
import os
import sys
import unittest
from unittest.mock import Mock, call, patch

from connectors import action_executor, capability_truth, model_gateway
from connectors import telegram_webhook_runtime as runtime


class TelegramResponsePolicyTests(unittest.TestCase):
    def setUp(self):
        self.bot = runtime.bot
        self.message = {
            "chat": {"id": 123, "type": "private"},
            "message_id": 7,
            "text": "اكتب رسالة اعتذار قصيرة.",
        }
        self.answer = "أعتذر عن التأخير.\nسأرسل المسودة اليوم."
        self.usage = {"inputTokens": 10, "outputTokens": 20}
        self.enterContext(patch.dict(os.environ, {"AI_SUPER_MANAGER_DEFAULT": "0"}))
        self.enterContext(patch.object(self.bot, "_authorized", return_value=True))
        self.enterContext(patch.object(self.bot, "_local_capture", return_value="TG-1"))
        self.enterContext(patch.object(self.bot, "api", return_value={}))
        self.send = self.enterContext(patch.object(self.bot, "send"))
        self.append = self.enterContext(patch.object(self.bot, "_append"))
        self.intake = self.enterContext(patch.object(self.bot, "_save_intake", return_value=True))
        self.remember = self.enterContext(patch("agent_runtime.remember"))
        self.route = self.enterContext(patch.object(
            model_gateway, "last_route", return_value={"provider": "bedrock"}
        ))
        self.ask = self.enterContext(patch.object(
            self.bot, "ask_bedrock",
            return_value=(self.answer, self.usage, 5, ["knowledge/private.md"]),
        ))
        self.lookup = self.enterContext(patch.object(
            self.bot, "_needs_memory_lookup", return_value=False
        ))
        self.memory = self.enterContext(patch.object(self.bot, "_memory_sheet_context"))
        self.needs_sheet = self.enterContext(patch.object(
            self.bot, "_needs_sheet_context", return_value=False
        ))
        self.sheet = self.enterContext(patch.object(
            self.bot, "_sheet_context", return_value="LIVE SHEET EVIDENCE"
        ))

    def test_normal_replies_have_no_footer_and_still_persist(self):
        for provider in ("bedrock", "openrouter"):
            for sources in ([], ["knowledge/private.md", "prompts/chief-of-staff.md"]):
                with self.subTest(provider=provider, sources=sources):
                    for mock in (self.send, self.append, self.intake, self.remember):
                        mock.reset_mock()
                    self.route.return_value = {"provider": provider}
                    self.ask.return_value = self.answer, self.usage, 5, sources

                    self.bot.handle_message(self.message)

                    self.send.assert_called_once_with(123, self.answer)
                    self.append.assert_called_once()
                    tab, row = self.append.call_args.args
                    self.assertEqual(tab, self.bot.CONVERSATION_TAB)
                    self.assertEqual(row[:2], ["CV-123-7", "TG-1"])
                    self.assertEqual(row[5:7], [self.message["text"], self.answer])
                    self.assertEqual(row[7:11], [10, 20, 5, "COMPLETED"])
                    self.intake.assert_called_once_with(
                        "TG-1", self.message, self.message["text"], "TEXT", "",
                        "COMPLETED", response_id="CV-123-7",
                    )
                    self.assertEqual(self.remember.call_args_list, [
                        call(123, "user", self.message["text"], 7, "GENERAL"),
                        call(123, "assistant", self.answer, 7, "GENERAL"),
                    ])

    def test_memory_evidence_is_used_without_lookup_notice(self):
        self.lookup.return_value = True
        for found in (True, False):
            with self.subTest(found=found):
                self.send.reset_mock()
                evidence = "PERSONAL CONTEXT EVIDENCE: " + str(found)
                self.memory.return_value = evidence, found
                self.bot.handle_message(self.message)
                self.ask.assert_called_with(123, self.message["text"], sheet_context=evidence)
                self.send.assert_called_once_with(123, self.answer)

    def test_memory_lookup_failure_keeps_uncertainty_without_a_footer(self):
        self.lookup.return_value = True
        self.memory.side_effect = RuntimeError("lookup offline")
        with patch("builtins.print") as log:
            self.bot.handle_message(self.message)
        self.assertIn("lookup failed", self.ask.call_args.kwargs["sheet_context"])
        log.assert_any_call("Memory context error: lookup offline", flush=True)
        self.send.assert_called_once_with(123, self.answer)

    def test_live_sheet_context_still_reaches_model(self):
        self.needs_sheet.return_value = True
        self.bot.handle_message(self.message)
        self.sheet.assert_called_once_with()
        self.ask.assert_called_once_with(
            123, self.message["text"], sheet_context="LIVE SHEET EVIDENCE"
        )
        self.send.assert_called_once_with(123, self.answer)

    def test_failed_routine_save_is_logged_without_a_footer(self):
        self.append.side_effect = RuntimeError("storage offline")
        for provider in ("bedrock", "openrouter"):
            with self.subTest(provider=provider):
                self.send.reset_mock()
                self.intake.reset_mock()
                self.route.return_value = {"provider": provider}
                with patch("builtins.print") as log:
                    self.bot.handle_message(self.message)
                log.assert_any_call("Google conversation save error: storage offline", flush=True)
                self.send.assert_called_once_with(123, self.answer)
                self.intake.assert_called_once()

    def test_explicit_sources_request_still_works(self):
        self.bot.handle_message({**self.message, "text": "/sources"})
        self.send.assert_called_once_with(123, self.bot._source_summary())
        self.ask.assert_not_called()

    def test_explicit_storage_diagnostics_request_still_works(self):
        with patch.object(self.bot, "command_storage_status") as diagnostics:
            self.bot.handle_message({**self.message, "text": "/storage_status"})
        diagnostics.assert_called_once_with(123)
        self.ask.assert_not_called()

    def test_approved_action_receipts_are_not_hidden(self):
        receipt = "✅ تم التحديث: Projects!B2\nرقم العملية: ACT-1"
        result = {"action_id": "ACT-1", "status": "EXECUTED", "receipts": []}
        with patch.object(action_executor, "execute", return_value=result) as execute, \
             patch.object(action_executor, "render_receipt", return_value=receipt):
            self.bot.handle_message({**self.message, "text": "/approve_action ACT-1 CODE"})
        execute.assert_called_once_with("ACT-1", "CODE")
        self.send.assert_called_once_with(123, receipt)
        self.ask.assert_not_called()


class ExecutivePromptTests(unittest.TestCase):
    def test_default_is_short_and_task_first_not_a_capability_catalogue(self):
        prompt = runtime.bot.SYSTEM_PROMPT
        self.assertIn("one or two short sentences", prompt)
        self.assertIn("Lead with the requested result", prompt)
        self.assertIn("unsolicited skill or capability inventories", prompt)
        self.assertIn("at most one blocking question", prompt)
        self.assertIn("Do not append knowledge-file lists", prompt)

    def test_brevity_preserves_requested_detail_and_safety(self):
        prompt = runtime.bot.SYSTEM_PROMPT
        self.assertIn("explicitly requested deliverable or essential safety detail", prompt)
        self.assertIn("External actions\nand sensitive decisions always require Abdulrahman's approval", prompt)
        self.assertIn("Never reveal credentials", prompt)
        self.assertIn("write succeeded unless a concrete receipt", prompt)
        self.assertIn("CONFIRMED FACT (with source_ref)", prompt)

    def test_all_provider_routes_receive_the_same_policy(self):
        for provider, fallback in (("openrouter", False), ("bedrock", False), ("openrouter", True)):
            with self.subTest(provider=provider, fallback=fallback):
                client = Mock()
                client.converse.return_value = {
                    "output": {"message": {"content": [{"text": "result"}]}},
                    "usage": {},
                }
                with patch.object(model_gateway, "desired_provider", return_value=provider), \
                     patch.object(model_gateway, "OPENROUTER_FALLBACK_BEDROCK", True), \
                     patch.object(model_gateway, "openrouter_chat", return_value=("result", {}, 1)) as chat, \
                     patch.object(capability_truth, "prompt_context", return_value=""), \
                     patch.object(capability_truth, "guard_response", side_effect=lambda text, answer: answer), \
                     patch.object(runtime.bot, "_bedrock_configured", return_value=True), \
                     patch.dict(sys.modules, {"boto3": Mock(client=Mock(return_value=client))}), \
                     patch("agent_runtime.build_context", return_value=("EVIDENCE", [])), \
                     patch("agent_runtime.recent_messages", return_value=[]), \
                     patch("agent_runtime.bedrock_messages", return_value=[]):
                    if fallback:
                        chat.side_effect = RuntimeError("provider unavailable")
                    result = runtime.bot.ask_bedrock(123, "Write a short apology.")
                self.assertEqual(result[0], "result")
                expected = runtime.bot.SYSTEM_PROMPT + "\n\nEVIDENCE"
                if provider == "bedrock" or fallback:
                    client.converse.assert_called_once()
                    self.assertEqual(client.converse.call_args.kwargs["system"], [{"text": expected}])
                else:
                    client.converse.assert_not_called()
                    self.assertEqual(chat.call_args.kwargs["messages"][0], {
                        "role": "system", "content": expected,
                    })


if __name__ == "__main__":
    unittest.main()
