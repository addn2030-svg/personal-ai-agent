# -*- coding: utf-8 -*-
"""Offline acceptance tests for Smart Agent build steps ST-01 and ST-02."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from connectors import model_gateway, model_router
from engine import agent_contract


class SmartAgentContractTests(unittest.TestCase):
    def test_st01_persona_memory_and_escalation_contract_is_valid(self):
        prompt = agent_contract.load_prompt_contract()
        self.assertTrue(prompt["agent"]["name"])
        self.assertTrue(prompt["agent"]["role"])
        self.assertGreater(prompt["memory"]["working_turns_verbatim"], 0)
        self.assertGreaterEqual(
            prompt["memory"]["session_turns_persisted"],
            prompt["memory"]["working_turns_verbatim"],
        )
        self.assertIn("destructive_write", prompt["escalation"]["confirm_when"])
        self.assertIn("Never invent facts", "\n".join(prompt["agent"]["hard_rules"]))

    def test_st01_contract_is_attached_to_the_live_telegram_system_prompt(self):
        from connectors import telegram_bot_legacy

        rendered = agent_contract.render_system_contract()
        self.assertIn(rendered, telegram_bot_legacy.SYSTEM_PROMPT)
        self.assertIn("VERSIONED AGENT CONTRACT", telegram_bot_legacy.SYSTEM_PROMPT)
        self.assertIn("Never claim an external action", telegram_bot_legacy.SYSTEM_PROMPT)

    def test_st01_memory_defaults_are_read_by_runtime(self):
        from engine import agent_runtime

        limits = agent_contract.memory_limits()
        self.assertEqual(agent_runtime.MAX_MEMORY_TURNS, limits["working_turns_verbatim"])
        self.assertEqual(agent_runtime.MAX_SESSION_MESSAGES, limits["session_turns_persisted"])

    def test_st02_model_budget_contract_is_valid(self):
        config = agent_contract.load_runtime_config()
        self.assertGreater(config["budget"]["max_daily_spend_usd"], 0)
        self.assertGreater(config["budget"]["max_tokens_per_turn"], 0)
        self.assertGreater(config["budget"]["max_tool_calls_per_turn"], 0)
        self.assertTrue(config["budget"]["hard_stop_on_budget"])
        self.assertFalse(config["runtime"]["mock_tools"])
        for profile in config["models"].values():
            self.assertLessEqual(profile["max_output_tokens"], config["budget"]["max_tokens_per_turn"])

    def test_st02_router_uses_general_contract_defaults_when_not_overridden(self):
        expected_tokens, expected_temperature = agent_contract.inference_defaults("general")
        response = model_router.RouterResponse(text="ok", model="test", usage={})
        with patch.object(model_gateway, "desired_provider", return_value="gemini"), patch.object(
            model_router, "_gemini_converse", return_value=response
        ) as converse:
            result = model_router.call(domain="general", prompt="hello", system="policy")
        self.assertIs(result, response)
        self.assertEqual(converse.call_args.kwargs["max_tokens"], expected_tokens)
        self.assertEqual(converse.call_args.kwargs["temperature"], expected_temperature)

    def test_st02_router_uses_manager_tier_and_keeps_explicit_limits(self):
        default_tokens, default_temperature = agent_contract.inference_defaults("manager")
        response = model_router.RouterResponse(text="ok", model="test", usage={})
        with patch.object(model_gateway, "desired_provider", return_value="gemini"), patch.object(
            model_router, "_gemini_converse", return_value=response
        ) as converse:
            model_router.call(domain="manager", prompt="plan", system="policy")
            self.assertEqual(converse.call_args.kwargs["max_tokens"], default_tokens)
            self.assertEqual(converse.call_args.kwargs["temperature"], default_temperature)

            model_router.call(
                domain="manager", prompt="tiny", system="policy", max_tokens=17, temperature=0.0
            )
            self.assertEqual(converse.call_args.kwargs["max_tokens"], 17)
            self.assertEqual(converse.call_args.kwargs["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
