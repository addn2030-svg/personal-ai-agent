import unittest
from unittest.mock import patch

from connectors import telegram_bot_legacy


class SourceNoteFormatTests(unittest.TestCase):
    def test_empty_sources_give_empty_note(self):
        self.assertEqual(telegram_bot_legacy.format_source_note([]), "")
        self.assertEqual(telegram_bot_legacy.format_source_note(None), "")

    def test_md_paths_are_code_wrapped_not_linkifiable(self):
        note = telegram_bot_legacy.format_source_note([
            "knowledge/master-professional-profile.yaml",
            "prompts/negotiation.md",
            "prompts/meeting-to-execution.md",
            "materials/lp-001-lean-six-sigma-ilpc.md",
        ])
        self.assertIn("📚 ملفات المعرفة:", note)
        for path in (
            "knowledge/master-professional-profile.yaml",
            "prompts/negotiation.md",
            "prompts/meeting-to-execution.md",
            "materials/lp-001-lean-six-sigma-ilpc.md",
        ):
            self.assertIn(f"`{path}`", note)
        # No bare .md token outside backticks that a renderer could linkify.
        import re

        outside_code = re.sub(r"`[^`]*`", "", note)
        self.assertNotIn(".md", outside_code)

    def test_note_is_capped_at_four_sources(self):
        note = telegram_bot_legacy.format_source_note([f"f{i}.md" for i in range(10)])
        self.assertEqual(note.count("`"), 8)
        self.assertNotIn("f4.md", note)

    def test_backticks_inside_paths_are_neutralized(self):
        note = telegram_bot_legacy.format_source_note(["we`ird.md"])
        self.assertIn("`we'ird.md`", note)

    def test_send_disables_link_previews(self):
        with patch.object(telegram_bot_legacy, "api") as fake_api:
            telegram_bot_legacy.send(123, "see prompts/negotiation.md")
        payload = fake_api.call_args[0][1]
        self.assertEqual(payload["chat_id"], 123)
        self.assertTrue(payload["disable_web_page_preview"])


if __name__ == "__main__":
    unittest.main()
