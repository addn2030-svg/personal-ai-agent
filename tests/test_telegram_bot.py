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

    def test_masteros_commands_handled_in_delegated_bot(self):
        sent_messages = []

        def fake_send(chat_id, text, reply_markup=None):
            sent_messages.append((chat_id, text, reply_markup))

        with patch.object(telegram_bot, "_authorized", return_value=True), \
             patch.object(telegram_bot, "send", fake_send), \
             patch.object(telegram_bot, "_save_intake", return_value=True), \
             patch.object(telegram_bot, "_local_capture", return_value="TG-1"):

            # Test /masteros
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/masteros"})
            self.assertTrue(len(sent_messages) > 0)
            self.assertIn("Master OS", sent_messages[-1][1])

            # Test /schedule
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/schedule"})
            self.assertIn("محرك الأتمتة", sent_messages[-1][1])

            # Test /diag
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/diag"})
            self.assertIn("حالة القنوات", sent_messages[-1][1])

            # Test /today-actions
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/today-actions"})
            self.assertTrue("إجراءات اليوم" in sent_messages[-1][1] or "أُدرجت" in sent_messages[-1][1])

            # Test /door
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/door"})
            self.assertIn("باب اليوم", sent_messages[-1][1])

            # Test energy logging
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "طاقة 8 إرهاق 2"})
            self.assertIn("تعافيك يُقاس الآن", sent_messages[-1][1])

    def test_proactive_commands_handled_in_delegated_bot(self):
        sent_messages = []

        def fake_send(chat_id, text, reply_markup=None):
            sent_messages.append((chat_id, text, reply_markup))

        import engine.telegram_bot  # noqa: F401 — يضيف engine/ إلى sys.path
        import proactive

        status_stub = {
            "enabled": True, "paused_until": None, "quiet_now": False,
            "telegram_push": "ready", "alerts_today": 1, "max_alerts": 6,
            "orders": {"SO-001": True, "SO-002": False}, "open_loops": 3,
            "recovering": 1, "ledger_rows": 9, "feedback": 2,
        }
        summary_stub = {"paused": False, "loops_open": 3, "act": 1, "prepare": 2,
                        "alert": 0, "batched": 0, "suggest": 1, "missed": 1,
                        "pushed": 0}

        with patch.object(telegram_bot, "_authorized", return_value=True), \
             patch.object(telegram_bot, "send", fake_send), \
             patch.object(telegram_bot, "_save_intake", return_value=True), \
             patch.object(telegram_bot, "_local_capture", return_value="TG-1"), \
             patch.object(proactive, "status", return_value=status_stub), \
             patch.object(proactive, "sweep", return_value=summary_stub), \
             patch.object(proactive, "push_test", return_value=(0, "sent")):

            # /proactive ← بطاقة الحالة بلا شبكة ولا حالة فعلية
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/proactive"})
            reply = sent_messages[-1][1]
            self.assertIn("محرك الاستباقية", reply)
            self.assertIn("جاهزة", reply)          # telegram_push: ready
            self.assertIn("1/6", reply)            # تنبيهات اليوم/السقف
            self.assertIn("1/2", reply)            # أوامر فعّالة 1 من 2

            # /sweep ← ملخص الدورة من الرد المختصر
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/sweep"})
            reply = sent_messages[-1][1]
            self.assertIn("دورة استباقية اكتملت", reply)
            self.assertIn("نُفّذ 1", reply)
            self.assertIn("/approve", reply)

            # /sweep أثناء الإيقاف المؤقت ← رسالة توضيحية
            with patch.object(proactive, "sweep", return_value={"paused": True}):
                telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/sweep"})
                self.assertIn("موقوفة مؤقتًا", sent_messages[-1][1])

            # /proactive_test ← نجاح القناة من المسار نفسه
            telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/proactive_test"})
            self.assertIn("نجح اختبار قناة التنبيه", sent_messages[-1][1])

            # /proactive_test مع فشل التهيئة ← سبب عملي
            with patch.object(proactive, "push_test", return_value=(1, "no_chat_id")):
                telegram_bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/proactive_test"})
                self.assertIn("TELEGRAM_ALLOWED_CHAT_ID", sent_messages[-1][1])

    def test_callback_query_handled_in_delegated_bot(self):
        answered = []
        sent_messages = []

        def fake_api(method, payload=None, timeout=60):
            if method == "answerCallbackQuery":
                answered.append(payload)
                return True
            return {}

        def fake_send(chat_id, text, reply_markup=None):
            sent_messages.append((chat_id, text, reply_markup))

        with patch.object(telegram_bot, "_authorized", return_value=True), \
             patch.object(telegram_bot, "api", fake_api), \
             patch.object(telegram_bot, "send", fake_send):

            cb = {
                "id": "cb123",
                "message": {"chat": {"id": 123, "type": "private"}},
                "data": "rj:A-NONEXISTENT",
            }
            telegram_bot.handle_callback(cb)
            self.assertTrue(len(answered) > 0)
            self.assertIn("رُفض", answered[-1].get("text", ""))


if __name__ == "__main__":
    unittest.main()
