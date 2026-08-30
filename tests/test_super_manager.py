import unittest
from unittest.mock import Mock, patch

from connectors import super_manager as sm
from connectors import telegram_bot as bot


class SuperManagerTests(unittest.TestCase):
    def test_prompt_contract_enforces_grounding_and_c1_to_c6(self):
        context = sm.ManagerContext(
            text="STATE waiting_for | task=Hospital approval | status=WAITING",
            sources=("state",),
            state_rows=1,
        )
        prompt = sm.build_prompt("Should we launch Sunday or postpone?", context)
        self.assertIn("Never invent a date", prompt)
        self.assertIn("NEEDS_INPUT", prompt)
        self.assertIn("C1 LINK BEFORE ANSWERING", prompt)
        self.assertIn("C5 RECOMMEND", prompt)
        self.assertIn("at least three comparable historical records", prompt)
        self.assertIn("Hospital approval", prompt)

    def test_manager_uses_protected_manager_route_and_reports_context(self):
        context = sm.ManagerContext(
            text="SHEET Waiting_For | approval pending",
            sources=("sheets", "calendar"),
            state_rows=2,
            ops_rows=4,
        )
        with patch.object(sm, "build_context", return_value=context), patch.object(
            sm.lean,
            "_bedrock_manager",
            return_value=("RECOMMENDATION: proceed only if approved", "bedrock", "claude", {"inputTokens": 10}),
        ) as manager:
            result = sm.manager(7, "Should we launch Sunday?", bedrock_fallback=Mock())

        self.assertIn("Super Manager v1.0", result)
        self.assertIn("Context: sheets+calendar", result)
        self.assertIn("RECOMMENDATION", result)
        prompt = manager.call_args.args[0]
        self.assertIn("SUPPLIED_EVIDENCE", prompt)
        self.assertIn("approval pending", prompt)

    def test_private_identifiers_are_rejected_before_model(self):
        with patch.object(sm.lean, "_bedrock_manager") as manager:
            with self.assertRaisesRegex(ValueError, "معرّفات خاصة"):
                sm.manager(1, "راجع المريض رقم الملف 12345")
        manager.assert_not_called()

    def test_shadow_compares_legacy_and_candidate_without_action_api(self):
        with patch.object(sm.base, "mission", return_value="LEGACY_RESULT"), patch.object(
            sm, "manager", return_value="SUPER_RESULT"
        ):
            result = sm.shadow(1, "Decide the next step")
        self.assertIn("MANAGER SHADOW", result)
        self.assertIn("LEGACY_RESULT", result)
        self.assertIn("SUPER_RESULT", result)
        self.assertIn("no external actions", result)

    def test_telegram_manager_command_routes_to_super_manager(self):
        message = {"text": "/manager Decide whether to launch Sunday", "chat": {"id": 9, "type": "private"}}
        with patch.object(bot, "_authorized", return_value=True), patch.object(
            bot, "_message_payload", return_value=(message["text"], "TEXT", None)
        ), patch.object(bot, "_local_capture", return_value="I-1"), patch.object(
            bot, "_save_intake"
        ), patch.object(bot, "api"), patch.object(bot, "send") as send, patch.object(
            sm, "manager", return_value="SUPER_MANAGER_OK"
        ) as manager:
            bot.handle_message(message)

        manager.assert_called_once()
        self.assertTrue(any("SUPER_MANAGER_OK" in str(call.args[1]) for call in send.call_args_list))

    def test_natural_manager_prefix_routes_without_enabling_global_default(self):
        message = {"text": "مدير رتب أولوياتي", "chat": {"id": 9, "type": "private"}}
        with patch.dict("os.environ", {"AI_SUPER_MANAGER_DEFAULT": "0"}, clear=False), patch.object(
            bot, "_authorized", return_value=True
        ), patch.object(bot, "_message_payload", return_value=(message["text"], "TEXT", None)), patch.object(
            bot, "_local_capture", return_value="I-2"
        ), patch.object(bot, "_save_intake"), patch.object(bot, "api"), patch.object(
            bot, "send"
        ), patch.object(sm, "manager", return_value="OK") as manager:
            bot.handle_message(message)
        self.assertEqual(manager.call_args.args[1], "رتب أولوياتي")


if __name__ == "__main__":
    unittest.main()
