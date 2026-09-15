# -*- coding: utf-8 -*-
"""BUG-002 regression tests: bare numbered replies must map to the presented menu.

Covers three layers:
1. Message builders must not duplicate the current user message (the "1" -> "11" bug).
2. engine.choice_resolver maps bare digits (Latin + Arabic-Indic) to menu options.
3. Super Manager injects the deterministic resolution into its evidence context.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

import agent_runtime  # noqa: E402  (bare layout used by the Telegram pipeline)
import engine.agent_runtime as pkg_agent_runtime  # noqa: E402
from connectors import model_gateway as mg  # noqa: E402
from connectors import super_manager as sm  # noqa: E402
from connectors import telegram_bot_legacy as legacy  # noqa: E402
from engine import choice_resolver as cr  # noqa: E402
from engine.store import Store  # noqa: E402

MENU = "✅ API Invoice — سندفعها يدويًا.\n1) ندفعها اليوم\n2) ندفعها بكرة"


class IsolatedMemoryTestCase(unittest.TestCase):
    """Route every Store() call to a throwaway state.json — never repo data."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state_path = str(Path(tmp.name) / "state.json")
        # The bare and package layouts are distinct module objects that share the
        # same disk state in production; patch Store in both for isolation.
        for module in (agent_runtime, pkg_agent_runtime):
            p = patch.object(module, "Store", lambda: Store(state_path))
            p.start()
            self.addCleanup(p.stop)


class BedrockMessagesDedupeTests(IsolatedMemoryTestCase):
    def test_current_user_message_is_not_duplicated_the_11_bug(self):
        agent_runtime.remember(111, "user", "وش وضع فاتورة API؟", "101")
        agent_runtime.remember(111, "assistant", MENU, "102")
        # handle_message persists the reply BEFORE ask_bedrock:
        agent_runtime.remember(111, "user", "1", "103")

        msgs = agent_runtime.bedrock_messages(111, "1")
        texts = [m["content"][0]["text"] for m in msgs]

        self.assertEqual(texts.count("1"), 1, "the live query must appear exactly once")
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertIn(MENU, texts)

    def test_genuine_repeated_reply_is_kept_once_in_history(self):
        agent_runtime.remember(222, "user", "نعم", "201")
        agent_runtime.remember(222, "user", "نعم", "202")

        msgs = agent_runtime.bedrock_messages(222, "نعم")
        texts = [m["content"][0]["text"] for m in msgs]

        self.assertEqual(texts, ["نعم", "نعم"], "history turn + live query, never three")

    def test_whitespace_difference_still_deduplicates(self):
        agent_runtime.remember(333, "user", " 2 ", "301")

        msgs = agent_runtime.bedrock_messages(333, "2")
        texts = [m["content"][0]["text"] for m in msgs]

        self.assertEqual(texts.count("2"), 1)


class OpenAiMessagesDedupeTests(unittest.TestCase):
    def test_current_user_message_is_not_duplicated(self):
        rows = [
            {"role": "user", "content": "وش وضع فاتورة API؟"},
            {"role": "assistant", "content": MENU},
            {"role": "user", "content": "1"},  # already remembered by the caller
        ]
        with patch.object(agent_runtime, "recent_messages", return_value=rows):
            msgs = mg._openai_messages(444, "1", "SYS", "CTX")

        bodies = [m["content"] for m in msgs[1:]]  # skip the system message
        self.assertEqual(bodies, ["وش وضع فاتورة API؟", MENU, "1"])
        self.assertEqual(msgs[0]["role"], "system")


class ChoiceResolverTests(unittest.TestCase):
    def rows(self, *extra):
        base = [
            {"role": "user", "content": "وش وضع فاتورة API؟"},
            {"role": "assistant", "content": MENU},
        ]
        return base + list(extra)

    def test_bare_digit_maps_to_first_option(self):
        hit = cr.resolve_numbered_reply("1", self.rows({"role": "user", "content": "1"}))
        self.assertEqual(hit["number"], 1)
        self.assertEqual(hit["option_text"], "ندفعها اليوم")

    def test_bare_digit_maps_to_second_option(self):
        hit = cr.resolve_numbered_reply("2", self.rows({"role": "user", "content": "2"}))
        self.assertEqual(hit["option_text"], "ندفعها بكرة")

    def test_arabic_indic_digit_maps(self):
        hit = cr.resolve_numbered_reply("٢", self.rows({"role": "user", "content": "٢"}))
        self.assertEqual(hit["option_text"], "ندفعها بكرة")

    def test_prefixed_forms_map(self):
        for reply in ("الخيار 2", "رقم ١", "اختر 2", "option 2", "1.", "2)"):
            hit = cr.resolve_numbered_reply(reply, self.rows({"role": "user", "content": reply}))
            self.assertIsNotNone(hit, reply)
            self.assertIn(hit["option_text"], ("ندفعها اليوم", "ندفعها بكرة"))

    def test_menu_with_arabic_indic_option_numbers(self):
        rows = [{"role": "assistant", "content": "١) ندفع اليوم\n٢) ندفع بكرة"}]
        hit = cr.resolve_numbered_reply("١", rows)
        self.assertEqual(hit["option_text"], "ندفع اليوم")

    def test_out_of_range_number_returns_none(self):
        self.assertIsNone(cr.resolve_numbered_reply("3", self.rows()))
        self.assertIsNone(cr.resolve_numbered_reply("11", self.rows()))

    def test_non_menu_conversation_returns_none(self):
        rows = [
            {"role": "user", "content": "وش وضع فاتورة API؟"},
            {"role": "assistant", "content": "API Invoice مؤجلة لأسباب بنكية."},
        ]
        self.assertIsNone(cr.resolve_numbered_reply("1", rows))
        self.assertIsNone(cr.resolve_numbered_reply("1", []))

    def test_prose_and_years_are_not_menu_replies(self):
        self.assertIsNone(cr.parse_bare_number("وش وضع فاتورة API؟"))
        self.assertIsNone(cr.parse_bare_number("2026"))
        self.assertIsNone(cr.parse_bare_number("١٥ ريال"))

    def test_single_numbered_line_is_not_a_menu(self):
        rows = [{"role": "assistant", "content": "المطلوب: 1) مراجعة العقد فقط"}]
        self.assertIsNone(cr.resolve_numbered_reply("1", rows))

    def test_only_the_most_recent_assistant_menu_counts(self):
        older = {"role": "assistant", "content": "1) خيار قديم\n2) خيار قديم ثاني"}
        newer_no_menu = {"role": "assistant", "content": "تم إرسال التقرير."}
        self.assertIsNone(cr.resolve_numbered_reply("1", [older, newer_no_menu]))

        newer_menu = {"role": "assistant", "content": "1) الخيار الجديد\n2) بديل جديد"}
        hit = cr.resolve_numbered_reply("1", [older, newer_menu])
        self.assertEqual(hit["option_text"], "الخيار الجديد")

    def test_resolution_block_pins_the_selection(self):
        hit = cr.resolve_numbered_reply("1", self.rows())
        block = cr.resolution_context_block(hit)
        self.assertIn("NUMBERED_REPLY_RESOLUTION", block)
        self.assertIn("ندفعها اليوم", block)
        self.assertIn("never ask what the number means", block)


class SuperManagerNumberedReplyTests(IsolatedMemoryTestCase):
    def test_numbered_reply_context_resolves_from_memory(self):
        rows = [
            {"role": "user", "content": "وش وضع فاتورة API؟"},
            {"role": "assistant", "content": MENU},
        ]
        with patch.object(pkg_agent_runtime, "recent_messages", return_value=rows):
            block = sm._numbered_reply_context(555, "1")
        self.assertIn("NUMBERED_REPLY_RESOLUTION", block)
        self.assertIn("ندفعها اليوم", block)

    def test_non_numbered_goal_yields_empty_context(self):
        with patch.object(pkg_agent_runtime, "recent_messages", return_value=[]):
            self.assertEqual(sm._numbered_reply_context(555, "شنو أولويات اليوم؟"), "")

    def test_manager_injects_resolution_into_prompt_evidence(self):
        rows = [
            {"role": "user", "content": "وش وضع فاتورة API؟"},
            {"role": "assistant", "content": MENU},
        ]
        context = sm.ManagerContext(text="STATE decisions | item=invoice", sources=("state",), state_rows=1)
        with patch.object(pkg_agent_runtime, "recent_messages", return_value=rows), patch.object(
            sm, "build_context", return_value=context
        ), patch.object(
            sm.lean, "_bedrock_manager", return_value=("RECOMMENDATION: pay today", "bedrock", "claude", {})
        ) as bedrock:
            result = sm.manager(555, "1", bedrock_fallback=Mock())

        prompt = bedrock.call_args[0][0]
        self.assertIn("NUMBERED_REPLY_RESOLUTION", prompt)
        self.assertIn("ندفعها اليوم", prompt)
        self.assertIn("STATE decisions", prompt)
        self.assertIn("numbered_reply", result)


class PromptContractTests(unittest.TestCase):
    def test_system_prompt_documents_menu_reply_rule(self):
        self.assertIn("MENU REPLIES", legacy.SYSTEM_PROMPT)
        self.assertIn("Never merge adjacent digits", legacy.SYSTEM_PROMPT)
        self.assertIn("Arabic-Indic", legacy.SYSTEM_PROMPT)

    def test_thinking_contract_documents_menu_reply_rule(self):
        self.assertIn("MENU REPLIES", sm.THINKING_CONTRACT)
        self.assertIn("Never merge adjacent digits", sm.THINKING_CONTRACT)
        self.assertIn("NUMBERED_REPLY_RESOLUTION", sm.THINKING_CONTRACT)


if __name__ == "__main__":
    unittest.main()
