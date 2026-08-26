import unittest
from types import SimpleNamespace

from connectors.brief_runtime import install


class RuntimeHardeningTests(unittest.TestCase):
    def fake_bot(self):
        seen = []

        def original_category(text, kind="TEXT"):
            if "patient" in (text or "").lower():
                return "CLINICAL_PRIVATE"
            return "GENERAL"

        def clinical_hint(text):
            return "patient" in (text or "").lower()

        def handle_message(message):
            seen.append(message.get("text"))

        bot = SimpleNamespace(
            GOOGLE_SHEETS_WEBHOOK_URL="",
            GOOGLE_SHEETS_WEBHOOK_SECRET="",
            _append=lambda tab, row: None,
            _category=original_category,
            _clinical_hint=clinical_hint,
            handle_message=handle_message,
            send=lambda *args, **kwargs: None,
            ask_bedrock=lambda *args, **kwargs: ("ok", {}, 0, []),
            _now=lambda: "2026-08-26T23:00:00+03:00",
        )
        return bot, seen

    def test_b_alias_routes_to_brief(self):
        bot, seen = self.fake_bot()
        install(bot)
        bot.handle_message({"text": "/b"})
        self.assertEqual(seen, ["/brief"])

    def test_appointment_is_classified_without_calendar_side_effect(self):
        bot, _ = self.fake_bot()
        install(bot)
        self.assertEqual(bot._category("لدي موعد غدًا"), "APPOINTMENT")
        self.assertEqual(bot._category("appointment next week"), "APPOINTMENT")

    def test_clinical_privacy_precedes_appointment(self):
        bot, _ = self.fake_bot()
        install(bot)
        self.assertEqual(bot._category("patient appointment tomorrow"), "CLINICAL_PRIVATE")


if __name__ == "__main__":
    unittest.main()
