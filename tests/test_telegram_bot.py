import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import telegram_bot


class TelegramBotTests(unittest.TestCase):
    def test_source_summary_has_expected_sections(self):
        text = telegram_bot._source_summary()
        self.assertIn("مصادر الوكيل", text)
        self.assertIn("المهارات", text)
        self.assertIn("الإجمالي", text)

    def test_first_private_chat_claims_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner_file = Path(tmp) / "owner"
            with patch.object(telegram_bot, "ALLOWED_CHAT_ID", ""), patch.object(
                telegram_bot, "OWNER_FILE", owner_file
            ):
                self.assertTrue(telegram_bot._authorized(12345, "private"))
                self.assertFalse(telegram_bot._authorized(99999, "private"))
                self.assertEqual(owner_file.read_text(encoding="utf-8"), "12345")

    def test_group_cannot_claim_unconfigured_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner_file = Path(tmp) / "owner"
            with patch.object(telegram_bot, "ALLOWED_CHAT_ID", ""), patch.object(
                telegram_bot, "OWNER_FILE", owner_file
            ):
                self.assertFalse(telegram_bot._authorized(-1001, "group"))
                self.assertFalse(owner_file.exists())

    def test_fixed_allowed_chat_id(self):
        with patch.object(telegram_bot, "ALLOWED_CHAT_ID", "42"):
            self.assertTrue(telegram_bot._authorized(42, "private"))
            self.assertFalse(telegram_bot._authorized(43, "private"))


if __name__ == "__main__":
    unittest.main()
