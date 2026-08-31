import datetime as dt
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from connectors import action_deadline_report as ext


TZ = ZoneInfo("Asia/Riyadh")


class NaturalActionDeadlineReportTests(unittest.TestCase):
    def test_simple_tomorrow_deadline_has_human_phrase(self):
        base = dt.datetime(2026, 8, 31, 8, 0, tzinfo=TZ)
        deadline = ext._parse_deadline(
            "الموعد النهائي غدا الساعة 10:00 صباحا",
            base_now=base,
        )
        self.assertEqual(deadline, dt.datetime(2026, 9, 1, 10, 0, tzinfo=TZ))
        self.assertEqual(
            ext.format_deadline(deadline),
            "الثلاثاء 1 سبتمبر 2026، الساعة 10:00 صباحًا",
        )

    def test_deadline_fails_closed_on_multiple_dates(self):
        base = dt.datetime(2026, 8, 31, 8, 0, tzinfo=TZ)
        with self.assertRaisesRegex(ValueError, "أكثر من تاريخ"):
            ext._parse_deadline(
                "الموعد النهائي اليوم أو 2026-09-02 الساعة 10:00",
                base_now=base,
            )

    def test_deadline_requires_explicit_time(self):
        base = dt.datetime(2026, 8, 31, 8, 0, tzinfo=TZ)
        with self.assertRaisesRegex(ValueError, "حدد وقت"):
            ext._parse_deadline("الموعد النهائي 2026-09-02", base_now=base)

    def test_reminder_simple_phrases(self):
        self.assertEqual(ext._parse_reminder_minutes("ذكرني قبل ساعة", deadline_present=True), 60)
        self.assertEqual(ext._parse_reminder_minutes("ذكرني قبل ساعتين", deadline_present=True), 120)
        self.assertEqual(ext._parse_reminder_minutes("ذكرني قبل 30 دقيقة", deadline_present=True), 30)
        self.assertIsNone(ext._parse_reminder_minutes("لا يوجد تذكير", deadline_present=True))

    def test_preview_is_simple_and_does_not_claim_execution(self):
        record = {
            "action_id": "NA-1234",
            "approval_code": "ABC123",
            "plan": {
                "project": {"project_id": "PRJ-001", "name": "Personal AI Agent"},
                "mutations": [
                    {"kind": "sheet_cell", "label": "PRJ-001 نسبة الإنجاز", "before": "35%", "after": "50%"},
                    {"kind": "deadline_cell", "deadline_human": "الثلاثاء 1 سبتمبر 2026، الساعة 10:00 صباحًا"},
                    {"kind": "calendar_deadline_reminder", "reminder_minutes": 60},
                ],
            },
        }
        answer = ext._extended_render_preview(record)
        self.assertIn("35% → 50%", answer)
        self.assertIn("الموعد النهائي", answer)
        self.assertIn("قبل الموعد بـ ساعة", answer)
        self.assertIn("لم يتم تنفيذ أي تغيير بعد", answer)
        self.assertIn("/approve_action NA-1234 ABC123", answer)

    def test_execute_writes_deadline_and_calendar_only_after_claim(self):
        deadline = dt.datetime(2026, 9, 1, 10, 0, tzinfo=TZ)
        action = {
            "plan": {
                "project": {"project_id": "PRJ-001", "name": "Personal AI Agent"},
                "mutations": [
                    {
                        "kind": "deadline_cell",
                        "sheet": "Projects",
                        "cell": "M2",
                        "before": "",
                        "after": "2026-09-01 10:00",
                        "deadline_iso": deadline.isoformat(),
                        "deadline_human": ext.format_deadline(deadline),
                    },
                    {
                        "kind": "calendar_deadline_reminder",
                        "project_id": "PRJ-001",
                        "project_name": "Personal AI Agent",
                        "deadline_iso": deadline.isoformat(),
                        "reminder_minutes": 60,
                    },
                ],
            }
        }
        fake_store = MagicMock()
        fake_store.transaction.return_value = None
        with patch.object(ext.base, "_claim", return_value=action) as claim, \
             patch.object(ext.base, "_fresh_project_value", return_value=("", "M2")), \
             patch.object(ext.sheets, "update_cell", return_value={"ok": True}), \
             patch.object(ext.calendar_actions, "create_event", return_value={"id": "EV-1", "link": "x"}), \
             patch.object(ext, "Store", return_value=fake_store):
            result = ext._extended_execute("NA-1", "CODE")
        claim.assert_called_once_with("NA-1", "CODE")
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(result["receipts"][0]["kind"], "deadline_cell")
        self.assertEqual(result["receipts"][1]["kind"], "calendar_reminder")

    def test_live_project_report_format_from_verified_schema(self):
        headers = [
            "Project_ID", "اسم المشروع", "المجال", "الهدف", "النتيجة المطلوبة",
            "الحالة", "الأولوية", "المرحلة الحالية", "نسبة الإنجاز", "الخطوة التالية",
            "العائق الرئيسي", "القرار المطلوب", "الموعد النهائي", "آخر تحديث", "معيار النجاح",
        ]
        row = [
            "PRJ-001", "Personal AI Agent", "AI", "goal", "result", "قيد التنفيذ", "عالي",
            "ربط Sheet Intelligence", "35%", "إكمال الاختبار", "", "", "", "8/22/2026", "success",
        ]
        project = {"headers": headers, "row": row, "row_no": 2, "project_id": "PRJ-001", "name": "Personal AI Agent"}
        waiting = [["Waiting_ID", "العنصر", "بانتظار من؟"], ["WAIT-0003", "PRJ-001 — Personal AI Agent", "عبدالمجيد"]]
        with patch.object(ext.base, "_find_project", return_value=project), \
             patch.object(ext.sheets, "snapshot", return_value={"Waiting_For": waiting}):
            report = ext.project_report("PRJ-001")
        self.assertIn("تقرير PRJ-001", report)
        self.assertIn("الإنجاز: 35%", report)
        self.assertIn("الموعد النهائي: غير محدد", report)
        self.assertIn("عبدالمجيد", report)

    def test_natural_report_request(self):
        ok, query = ext.report_request("ارسل تقرير PRJ-001")
        self.assertTrue(ok)
        self.assertEqual(query, "PRJ-001")


if __name__ == "__main__":
    unittest.main()
