import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from connectors.calendar_actions import parse_event_request
from connectors.calendar_intent import is_calendar_action, routed_text

TZ = ZoneInfo("Asia/Riyadh")


class CalendarActionsTests(unittest.TestCase):
    def setUp(self):
        self.base = dt.datetime(2026, 8, 25, 10, 0, tzinfo=TZ)

    def test_arabic_tomorrow_evening(self):
        event = parse_event_request("ذكرني غدًا الساعة 5:30 مساءً بالتمرين قبل ساعتين", self.base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 26, 17, 30, tzinfo=TZ))
        self.assertEqual(event["reminder_minutes"], 120)
        self.assertIn("بالتمرين", event["title"])

    def test_iso_date_and_am(self):
        event = parse_event_request("/remind اجتماع العمير 2026-08-27 الساعة 8 صباحًا", self.base)
        self.assertEqual(event["start"].hour, 8)
        self.assertEqual(event["start"].date(), dt.date(2026, 8, 27))

    def test_requires_date(self):
        with self.assertRaises(ValueError):
            parse_event_request("ذكرني الساعة 5 مساءً", self.base)

    def test_duration(self):
        event = parse_event_request("أضف مراجعة غدًا الساعة 4 مساءً لمدة 90 دقيقة", self.base)
        self.assertEqual(int((event["end"] - event["start"]).total_seconds() / 60), 90)

    def test_relative_english_reminder(self):
        event = parse_event_request(
            "/remind remind me in 10 minutes to meditate for 10 minutes",
            self.base,
        )
        self.assertEqual(event["start"], dt.datetime(2026, 8, 25, 10, 10, tzinfo=TZ))
        self.assertEqual(event["end"], dt.datetime(2026, 8, 25, 10, 20, tzinfo=TZ))
        self.assertEqual(event["reminder_minutes"], 0)
        self.assertEqual(event["title"].lower(), "meditate")

    def test_relative_arabic_reminder(self):
        event = parse_event_request("ذكرني بعد 15 دقيقة بالمشي لمدة 20 دقيقة", self.base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 25, 10, 15, tzinfo=TZ))
        self.assertEqual(event["end"], dt.datetime(2026, 8, 25, 10, 35, tzinfo=TZ))
        self.assertEqual(event["reminder_minutes"], 0)

    def test_calendar_action_routes_before_general_ai(self):
        text = "Add a meditation break to my calendar in 10 minutes for 10 minutes"
        self.assertTrue(is_calendar_action(text))
        self.assertTrue(routed_text(text).startswith("/remind "))
        self.assertFalse(is_calendar_action("Explain how Google Calendar works"))


if __name__ == "__main__":
    unittest.main()
