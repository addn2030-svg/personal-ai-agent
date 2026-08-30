import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from connectors.calendar_actions import NeedsInputError, parse_event_request
from connectors import telegram_bot_legacy as legacy
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

    def test_monday_from_saturday_resolves_to_august_31(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        event = parse_event_request("اجتماع الاثنين الساعة 9:30", base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 31, 9, 30, tzinfo=TZ))

    def test_multiple_date_references_fail_closed(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        text = (
            "لازم أقرر هل نبدأ الأحد القادم أو نأجلها أسبوعين. "
            "الملف مطلوب قبل الخميس، والاثنين الساعة 9:30 عندي اجتماع."
        )
        with self.assertRaisesRegex(ValueError, "NEEDS_INPUT"):
            parse_event_request(text, base)

    def test_multiple_clock_references_fail_closed(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        with self.assertRaisesRegex(ValueError, "NEEDS_INPUT"):
            parse_event_request("اجتماع الاثنين الساعة 9:30 أو الساعة 10:30", base)

    def test_bare_number_is_not_silently_used_as_clock(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        with self.assertRaisesRegex(ValueError, "حدد الوقت"):
            parse_event_request("اجتماع الاثنين رقم 9 لمراجعة الملفات", base)

    def test_invalid_explicit_date_fails_closed(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        with self.assertRaisesRegex(NeedsInputError, "NEEDS_INPUT"):
            parse_event_request("اجتماع 2026-02-30 الساعة 9:30", base)

    def test_equivalent_date_references_are_accepted(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        event = parse_event_request("اجتماع الاثنين 2026-08-31 الساعة 9:30", base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 31, 9, 30, tzinfo=TZ))

    def test_equivalent_clock_references_are_accepted(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        event = parse_event_request("اجتماع الاثنين الساعة 9 مساءً أو 21:00", base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 31, 21, 0, tzinfo=TZ))

    def test_arabic_digit_multiple_clocks_fail_closed(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        with self.assertRaisesRegex(NeedsInputError, "NEEDS_INPUT"):
            parse_event_request("اجتماع الاثنين الساعة ٩:٣٠ أو الساعة ١٠:٣٠", base)

    def test_today_plus_matching_weekday_is_one_date(self):
        base = dt.datetime(2026, 8, 31, 8, 0, tzinfo=TZ)
        event = parse_event_request("اجتماع اليوم الاثنين الساعة 9:30", base)
        self.assertEqual(event["start"], dt.datetime(2026, 8, 31, 9, 30, tzinfo=TZ))

    def test_time_range_fails_with_duration_guidance(self):
        base = dt.datetime(2026, 8, 29, 12, 0, tzinfo=TZ)
        with self.assertRaisesRegex(NeedsInputError, "وقت البداية والمدة"):
            parse_event_request("اجتماع الاثنين من الساعة 9 إلى الساعة 10", base)

    def test_needs_input_does_not_create_pending_confirmation(self):
        request = "اجتماع 2026-08-30 أو 2026-08-31 الساعة 9"
        with mock.patch.dict(legacy._PENDING_CALENDAR_EVENTS, {}, clear=True):
            with mock.patch.object(legacy, "send") as send:
                legacy.command_remind(12345, request)
            self.assertEqual(legacy._PENDING_CALENDAR_EVENTS, {})
        self.assertIn("NEEDS_INPUT", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
