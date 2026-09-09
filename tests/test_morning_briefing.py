# -*- coding: utf-8 -*-
"""Morning Briefing Mode v2 (وضع التوجيه الصباحي) tests — no network, no model calls.

Covers every code path: data adapters (overdue/clinics/staff pulse/sheet
intelligence), the spec dashboard builder, all callback branches, the focus
block Calendar proposal, the proactive daily sender, brain dump capture, the
supervisor brief approval flow, and installation/wrapping.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import morning_briefing as mb

TODAY = dt.date(2026, 9, 9)


def tasks_sheet_data():
    return {
        "خطة الإنجاز والمهام": [
            ["المهمة", "المسؤول", "الموعد النهائي", "الحالة", "ملاحظات"],
            ["تقرير الأداء الشهري", "عبدالرحمن", "2026-09-05", "قيد التنفيذ", ""],
            ["تحديث سياسة العيادة", "سمية", "2026-10-01", "قيد التنفيذ", ""],
            ["توريد أجهزة قديم", "عبدالمجيد", "2026-08-20", "منجز", ""],
            ["مراجعة عقود التشغيل", "", "", "", "متأخرة — بانتظار رد الجهة"],
            ["متابعة الغياب", "شهد", "2026-09-01", "متأخرة", ""],
        ],
    }


def supervisor_sheet_data():
    return {
        "تقارير المشرفين": [
            ["وقت الإرسال", "نوع التقرير", "المشرف", "القسم / العيادة", "بداية الأسبوع",
             "نهاية الأسبوع", "الجاهزية", "المجدولون", "تمت خدمتهم", "إلغاء / عدم حضور",
             "المعلومات المهمة", "التعثرات", "مستوى القرار", "القرار والتوصية", "أولوية البلاغ", "الملخص"],
            ["2026-09-01", "أسبوعي", "عبدالمجيد", "العلاج الطبيعي", "2026-08-24", "2026-08-30",
             "🟢 جاهز بالكامل", "40", "38", "2", "لا يوجد", "لا يوجد", "لا", "", "عادية", "مستقر"],
            ["2026-09-08", "أسبوعي", "عبدالمجيد", "العلاج الطبيعي", "2026-08-31", "2026-09-06",
             "🟡 جاهز جزئيًا — توجد ملاحظة", "41", "35", "6", "زيادة الإلغاءات", "نقص مستلزمات", "لا", "", "عادية", "متابعة"],
            ["2026-09-08", "أسبوعي", "شهد", "عيادة الدوخة والدهليزي", "2026-08-31", "2026-09-06",
             "🔴 غير جاهز — يحتاج تدخل", "20", "12", "8", "ضغط مرتفع", "تعطل جهاز", "عاجل", "صيانة فورية", "عالية", "يحتاج تدخل"],
        ],
    }


def full_sheet_data():
    return {**tasks_sheet_data(), **supervisor_sheet_data()}


class FakeBot:
    """Minimal stand-in for the live telegram bot module."""

    INTAKE_TAB = "مدخلات الوكيل"
    STATUS_TAB = "حالة الوكيل"
    GOOGLE_SHEET_ID = "sheet-123"
    AWS_REGION = "us-east-1"
    BEDROCK_MODEL_ID = "test-model"

    def __init__(self):
        self.calls = []
        self.sent = []
        self.appended = []
        self.intake_rows = []
        self.append_should_fail = False
        self.alert_heartbeats = []
        self._PENDING_CALENDAR_EVENTS = {}
        self.handle_message = lambda message: self.calls.append(("handle_message", message))
        self.configure_commands = lambda: self.calls.append(("configure_commands",))
        self.command_start = lambda chat_id: self.sent.append(("start", chat_id))
        self._maybe_send_calendar_alerts = lambda: self.alert_heartbeats.append("tick")

    def api(self, method, payload=None, timeout=60):
        self.calls.append((method, payload))
        if method == "getMyCommands":
            return [{"command": "start"}]
        return {}

    def send(self, chat_id, text):
        self.sent.append((chat_id, str(text)))

    def _authorized(self, chat_id, chat_type):
        return str(chat_id) == "42"

    def _owner_id(self):
        return "42"

    def _message_payload(self, message):
        text = (message.get("text") or message.get("caption") or "").strip()
        if message.get("voice"):
            return text, "VOICE", message["voice"].get("file_id", "")
        return text, "TEXT", ""

    def _local_capture(self, text, message, kind):
        return f"IID-{message.get('message_id', 1)}"

    def _save_intake(self, iid, message, text, kind, attachment, status, response_id="", error=""):
        self.intake_rows.append((iid, status, str(error)))
        return True

    def _append(self, tab, row):
        if self.append_should_fail:
            raise RuntimeError("sheets down")
        self.appended.append((tab, row))
        return True

    def _transcribe_telegram(self, file_id, kind):
        return "مهمة صوتية: متابعة توريد الأجهزة"

    def _now(self):
        return "2026-09-09T07:30:00+03:00"

    def _redact(self, text):
        return str(text or "").replace("0551234567", "[PHONE_REDACTED]")

    def _language(self, text):
        return "ar"


def make_message(text, chat_id=42, message_id=1):
    return {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}, "text": text}


def make_callback(data, chat_id=42):
    return {
        "id": "cb-1",
        "data": data,
        "message": {"message_id": 99, "chat": {"id": chat_id, "type": "private"}},
    }


def healthy_intel():
    return {
        "pending_tasks": ["خطة الإنجاز والمهام — صف 2: تقرير الأداء الشهري"],
        "pending_count": 1,
        "staff_coverage": "🔴 تحتاج تدخل الآن: عيادة الدوخة والدهليزي",
        "overdue": [{
            "sheet": "خطة الإنجاز والمهام", "row": 2,
            "values": ["تقرير الأداء الشهري", "عبدالرحمن", "2026-09-05", "قيد التنفيذ", ""],
            "reason": "تجاوز الموعد (2026-09-05)", "deadline": "2026-09-05",
        }],
        "clinics": [{
            "clinic": "عيادة الدوخة والدهليزي", "readiness": "🔴 غير جاهز — يحتاج تدخل",
            "supervisor": "شهد", "note": "تعطل جهاز", "row": 4, "sheet": "تقارير المشرفين",
        }],
    }


EMPTY_PAYLOAD = {
    "overdue": [], "clinics": [], "staff_coverage": "لا توجد تقارير جاهزية حديثة مؤكدة",
    "today_events": [], "errors": [], "generated_at": "2026-09-09T07:30:00+03:00",
}


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

class OverdueTasksTests(unittest.TestCase):
    def test_overdue_by_deadline_column(self):
        rows = mb.overdue_tasks(tasks_sheet_data(), today=TODAY)
        self.assertEqual(len(rows), 3)
        by_label = {row["values"][0]: row for row in rows}
        self.assertIn("تجاوز الموعد (2026-09-05)", by_label["تقرير الأداء الشهري"]["reason"])
        self.assertIn("تجاوز الموعد (2026-09-01)", by_label["متابعة الغياب"]["reason"])
        self.assertEqual(by_label["مراجعة عقود التشغيل"]["reason"], "موسومة كمتأخرة")

    def test_done_and_future_rows_excluded(self):
        rows = mb.overdue_tasks(tasks_sheet_data(), today=TODAY)
        labels = [row["values"][0] for row in rows]
        self.assertNotIn("تحديث سياسة العيادة", labels)  # deadline in the future
        self.assertNotIn("توريد أجهزة قديم", labels)      # already done

    def test_old_update_dates_do_not_create_false_overdue(self):
        data = {
            "Projects": [
                ["ID", "المشروع", "آخر تحديث", "الحالة"],
                ["PRJ-001", "منصة التعليم", "2026-08-01", "قيد التنفيذ"],
            ],
        }
        self.assertEqual(mb.overdue_tasks(data, today=TODAY), [])

    def test_missing_tab_is_tolerated(self):
        self.assertEqual(mb.overdue_tasks({}, today=TODAY), [])

    def test_provenance_present(self):
        row = mb.overdue_tasks(tasks_sheet_data(), today=TODAY)[0]
        self.assertEqual(row["sheet"], "خطة الإنجاز والمهام")
        self.assertEqual(row["row"], 2)


class ClinicReadinessTests(unittest.TestCase):
    def test_latest_report_per_clinic_wins(self):
        clinics = mb.clinic_readiness(supervisor_sheet_data())
        by_clinic = {c["clinic"]: c for c in clinics}
        self.assertEqual(len(clinics), 2)
        self.assertIn("جزئي", by_clinic["العلاج الطبيعي"]["readiness"])
        self.assertEqual(by_clinic["العلاج الطبيعي"]["supervisor"], "عبدالمجيد")

    def test_severity_sorting_red_first(self):
        clinics = mb.clinic_readiness(supervisor_sheet_data())
        self.assertEqual(clinics[0]["clinic"], "عيادة الدوخة والدهليزي")
        self.assertIn("غير جاهز", clinics[0]["readiness"])

    def test_missing_tab_returns_empty(self):
        self.assertEqual(mb.clinic_readiness({}), [])


class StaffPulseTests(unittest.TestCase):
    def test_red_pulse(self):
        clinics = mb.clinic_readiness(supervisor_sheet_data())
        self.assertIn("🔴", mb.staff_pulse(clinics))
        self.assertIn("عيادة الدوخة والدهليزي", mb.staff_pulse(clinics))

    def test_yellow_pulse(self):
        clinics = [{"clinic": "العلاج الطبيعي", "readiness": "🟡 جاهز جزئيًا"}]
        self.assertIn("🟡", mb.staff_pulse(clinics))

    def test_green_pulse(self):
        clinics = [{"clinic": "العلاج الطبيعي", "readiness": "🟢 جاهز بالكامل"}]
        self.assertIn("🟢", mb.staff_pulse(clinics))

    def test_empty_pulse(self):
        self.assertEqual(mb.staff_pulse([]), "لا توجد تقارير جاهزية حديثة مؤكدة")


class GetSheetIntelligenceTests(unittest.TestCase):
    """The spec adapter must run on the real sheet_intelligence.snapshot() API."""

    def test_adapter_shape(self):
        mb.install(FakeBot())
        with patch.object(mb, "_sheets_snapshot", return_value=full_sheet_data()), patch.object(
            mb, "_today", return_value=TODAY
        ):
            intel = mb.get_sheet_intelligence()
        self.assertEqual(intel["pending_count"], 3)
        self.assertEqual(len(intel["pending_tasks"]), 3)
        self.assertIn("🔴", intel["staff_coverage"])
        self.assertEqual(len(intel["clinics"]), 2)
        self.assertIn("خطة الإنجاز والمهام", intel["pending_tasks"][0])

    def test_adapter_raises_on_hard_sheets_failure(self):
        mb.install(FakeBot())
        with patch.object(mb, "_sheets_snapshot", side_effect=RuntimeError("sheets down")):
            with self.assertRaises(RuntimeError):
                mb.get_sheet_intelligence()


# ---------------------------------------------------------------------------
# Rendering + spec dashboard builder
# ---------------------------------------------------------------------------

class RenderAndKeyboardTests(unittest.TestCase):
    def test_keyboard_is_2x2_with_short_callback_data(self):
        fake = FakeBot()
        mb.install(fake)
        keyboard = mb.morning_keyboard()
        rows = keyboard["inline_keyboard"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 2)
        buttons = [btn for row in rows for btn in row]
        labels = [btn["text"] for btn in buttons]
        self.assertIn("🎙️ إفراغ ذهني سريع", labels)
        self.assertIn("📢 بث توجيه المشرفين", labels)
        self.assertIn("📊 فتح شيت العمليات", labels)
        self.assertIn("⏱️ حجز وقت التركيز العميق", labels)
        for btn in buttons:
            if "callback_data" in btn:
                self.assertLessEqual(len(btn["callback_data"].encode("utf-8")), 64)

    def test_sheet_button_is_url_when_resolvable(self):
        fake = FakeBot()
        mb.install(fake)
        with patch.object(mb, "_safe_tasks_link", return_value="https://docs.google.com/spreadsheets/d/x/edit#gid=1"):
            button = mb.morning_keyboard()["inline_keyboard"][1][0]
        self.assertEqual(button["url"], "https://docs.google.com/spreadsheets/d/x/edit#gid=1")
        self.assertNotIn("callback_data", button)

    def test_sheet_button_falls_back_to_callback(self):
        fake = FakeBot()
        mb.install(fake)
        with patch.object(mb, "_safe_tasks_link", return_value=""):
            button = mb.morning_keyboard()["inline_keyboard"][1][0]
        self.assertEqual(button["callback_data"], mb.CB_OPEN_TASKS)
        self.assertNotIn("url", button)

    def test_dashboard_renders_spec_sections(self):
        mb.install(FakeBot())
        payload = {
            "overdue": mb.overdue_tasks(tasks_sheet_data(), today=TODAY),
            "clinics": mb.clinic_readiness(supervisor_sheet_data()),
            "staff_coverage": "🔴 تحتاج تدخل الآن: عيادة الدوخة والدهليزي",
            "today_events": [
                {"title": "عيادة الدوخة — جولة", "start": "2026-09-09T09:00:00+03:00", "is_clinic": True},
                {"title": "اجتماع الإدارة", "start": "2026-09-09T13:00:00+03:00", "is_clinic": False},
            ],
            "errors": [],
            "generated_at": "2026-09-09T07:30:00+03:00",
        }
        text = mb.render_morning_dashboard(payload)
        self.assertIn("لوحة الفرز والتوجيه التنفيذي الصباحي", text)
        self.assertIn("نبض الكوادر والعيادات", text)
        self.assertIn("أبرز المهام المتأخرة المعلقة (3)", text)
        self.assertIn("عيادة الدوخة والدهليزي", text)
        self.assertIn("مواعيد اليوم: 2", text)
        self.assertIn("(منها 1 للعيادات)", text)
        self.assertIn("المسار 1: النبض السريري وتغطية العيادات (PT / OT / ST)", text)
        self.assertIn("المسار 2: القرارات الإدارية السريعة (قاعدة الدقيقتين)", text)
        self.assertIn("المسار 3: العمل الاستراتيجي العميق (الرعاية المنزلية / MyoMentor)", text)
        self.assertIn("المسار 4: التنسيق وبث التوجيهات للمشرفين", text)

    def test_delegation_hint_appears_when_team_available(self):
        mb.install(FakeBot())
        text = mb.render_morning_dashboard(dict(EMPTY_PAYLOAD))
        if mb._team is not None:
            self.assertIn("/delegate auto", text)
        else:
            self.assertNotIn("/delegate auto", text)

    def test_supervisor_brief_is_deterministic(self):
        payload = {
            "overdue": mb.overdue_tasks(tasks_sheet_data(), today=TODAY),
            "clinics": mb.clinic_readiness(supervisor_sheet_data()),
            "errors": [],
            "generated_at": "2026-09-09T07:30:00+03:00",
        }
        brief = mb.build_supervisor_brief(payload)
        self.assertIn("📢 توجيه المشرفين — 2026-09-09", brief)
        self.assertIn("عيادة الدوخة والدهليزي", brief)
        self.assertIn("معالجة عوائق الجاهزية", brief)
        self.assertIn("تحديث حالة المهام المتأخرة", brief)
        self.assertIn("بدون أي بيانات مرضى", brief)


class BuildDashboardTests(unittest.TestCase):
    """Spec entry point: build_morning_briefing_dashboard()."""

    def setUp(self):
        self.fake = FakeBot()
        mb.install(self.fake)

    def test_success_shape(self):
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            dashboard = mb.build_morning_briefing_dashboard()
        self.assertIn("لوحة الفرز والتوجيه التنفيذي الصباحي", dashboard["text"])
        self.assertIn("تقرير الأداء الشهري", dashboard["text"])
        self.assertIn("reply_markup", dashboard)
        self.assertEqual(len(dashboard["reply_markup"]["inline_keyboard"]), 2)
        self.assertIn("🔴", dashboard["text"])  # staff pulse surfaced

    def test_data_failure_renders_degraded_dashboard_with_keyboard(self):
        """A Sheets/Calendar failure must not kill the dashboard: it renders
        with the failing sources listed and the buttons still usable."""
        with patch.object(mb, "get_sheet_intelligence", side_effect=RuntimeError("boom")), patch.object(
            mb, "today_clinic_events", return_value=([], "Google Calendar: down")
        ):
            dashboard = mb.build_morning_briefing_dashboard()
        self.assertIn("لوحة الفرز والتوجيه التنفيذي الصباحي", dashboard["text"])
        self.assertIn("مصادر متعذرة", dashboard["text"])
        self.assertIn("Google Sheets: boom", dashboard["text"])
        self.assertEqual(len(dashboard["reply_markup"]["inline_keyboard"]), 2)

    def test_unexpected_bug_never_raises(self):
        with patch.object(mb, "morning_payload", side_effect=RuntimeError("unexpected")):
            dashboard = mb.build_morning_briefing_dashboard()
        self.assertIn("تعذر تجهيز التوجيه الصباحي", dashboard["text"])
        self.assertEqual(dashboard["reply_markup"], {"inline_keyboard": []})

    def test_uses_real_snapshot_seam(self):
        with patch.object(mb, "_sheets_snapshot", return_value=full_sheet_data()), patch.object(
            mb, "_today", return_value=TODAY
        ), patch.object(mb, "today_clinic_events", return_value=([], None)):
            dashboard = mb.build_morning_briefing_dashboard()
        self.assertIn("مراجعة عقود التشغيل", dashboard["text"])


class TasksSheetLinkTests(unittest.TestCase):
    def test_link_resolves_gid(self):
        with patch.object(
            mb.sheets, "metadata",
            return_value=[{"title": "خطة الإنجاز والمهام", "sheetId": 12345}],
        ), patch.object(mb.sheets, "SHEET_ID", "abc123"):
            self.assertEqual(
                mb.tasks_sheet_link(),
                "https://docs.google.com/spreadsheets/d/abc123/edit#gid=12345",
            )

    def test_link_falls_back_to_workbook_on_metadata_failure(self):
        with patch.object(mb.sheets, "metadata", side_effect=RuntimeError("down")), patch.object(
            mb.sheets, "SHEET_ID", "abc123"
        ):
            self.assertEqual(
                mb.tasks_sheet_link(),
                "https://docs.google.com/spreadsheets/d/abc123/edit",
            )

    def test_safe_link_empty_when_not_http(self):
        with patch.object(mb, "tasks_sheet_link", return_value="⚠️ غير مضبوط"):
            self.assertEqual(mb._safe_tasks_link(), "")


# ---------------------------------------------------------------------------
# Callback handling — handle_briefing_callback + handle_callback_query
# ---------------------------------------------------------------------------

class BriefingCallbackTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        mb.install(self.fake)
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()
        self.fake._PENDING_CALENDAR_EVENTS.clear()

    def tearDown(self):
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()
        self.fake._PENDING_CALENDAR_EVENTS.clear()

    def test_brain_dump_returns_await_input_and_opens_session(self):
        result = mb.handle_briefing_callback(42, mb.CB_BRAIN_DUMP)
        self.assertEqual(result["status"], "await_input")
        self.assertIn("42", mb._PENDING_BRAIN_DUMPS)
        self.assertTrue(any("الإفراغ الذهني" in text for _cid, text in self.fake.sent))

    def test_broadcast_returns_needs_approval_with_token(self):
        with patch.object(mb, "morning_payload", return_value=dict(EMPTY_PAYLOAD)):
            result = mb.handle_briefing_callback(42, mb.CB_SUPERVISOR_BRIEF)
        self.assertEqual(result["status"], "needs_approval")
        self.assertIn("/confirm_supervisor_brief", result["message"])
        self.assertEqual(len(mb._PENDING_SUPERVISOR_BRIEFS), 1)
        self.assertTrue(any("مسودة توجيه المشرفين" in text for _cid, text in self.fake.sent))

    def test_focus_block_returns_needs_approval_with_real_proposal(self):
        now = dt.datetime(2026, 9, 9, 7, 31, 20)
        with patch.object(mb, "_now_local", return_value=now):
            result = mb.handle_briefing_callback(42, mb.CB_FOCUS_BLOCK)
        self.assertEqual(result["status"], "needs_approval")
        self.assertEqual(len(self.fake._PENDING_CALENDAR_EVENTS), 1)
        token = next(iter(self.fake._PENDING_CALENDAR_EVENTS))
        proposal = self.fake._PENDING_CALENDAR_EVENTS[token]["proposal"]
        self.assertEqual(proposal["title"], "⏱️ تركيز عميق — التوجيه الصباحي")
        self.assertEqual(proposal["start"], dt.datetime(2026, 9, 9, 7, 35))  # next 5-min boundary
        self.assertEqual(proposal["end"], dt.datetime(2026, 9, 9, 8, 35))    # 60 minutes later
        self.assertEqual(self.fake._PENDING_CALENDAR_EVENTS[token]["chat_id"], "42")
        # Honest messaging: nothing is claimed before approval.
        self.assertTrue(any("لم يُضف بعد" in text and "/confirm_event" in text
                            for _cid, text in self.fake.sent))

    def test_open_tasks_returns_success(self):
        with patch.object(mb, "tasks_sheet_link", return_value="https://example.com/edit"), patch.object(
            mb, "_sheets_snapshot", return_value=tasks_sheet_data()
        ), patch.object(mb, "_today", return_value=TODAY):
            result = mb.handle_briefing_callback(42, mb.CB_OPEN_TASKS)
        self.assertEqual(result["status"], "success")
        self.assertTrue(any("شيت العمليات" in text and "المهام المتأخرة الآن: 3" in text
                            for _cid, text in self.fake.sent))

    def test_unknown_data(self):
        result = mb.handle_briefing_callback(42, "action_nonsense")
        self.assertEqual(result["status"], "unknown")

    def test_legacy_callback_names_still_accepted(self):
        result = mb.handle_briefing_callback(42, "morning:brain_dump")
        self.assertEqual(result["status"], "await_input")
        result = mb.handle_briefing_callback(42, "morning:open_tasks")
        self.assertEqual(result["status"], "success")

    def test_action_failure_returns_error_not_exception(self):
        with patch.object(mb, "_cb_open_tasks", side_effect=RuntimeError("boom")):
            result = mb.handle_briefing_callback(42, mb.CB_OPEN_TASKS)
        self.assertEqual(result["status"], "error")


class HandleCallbackQueryTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        mb.install(self.fake)
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()

    def tearDown(self):
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()

    def api_calls(self, method):
        return [payload for m, payload in self.fake.calls if m == method]

    def test_unauthorized_chat_is_refused(self):
        mb.handle_callback_query(make_callback(mb.CB_BRAIN_DUMP, chat_id=999))
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertIn("غير مصرح", answered[0]["text"])
        self.assertTrue(answered[0]["show_alert"])

    def test_unknown_callback_data(self):
        mb.handle_callback_query(make_callback("morning:unknown"))
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertIn("زر غير معروف", answered[0]["text"])

    def test_valid_button_answers_once_and_dispatches(self):
        with patch.object(mb, "handle_briefing_callback", return_value={"status": "success", "message": "ok"}) as spy:
            mb.handle_callback_query(make_callback(mb.CB_FOCUS_BLOCK))
        spy.assert_called_once_with(42, mb.CB_FOCUS_BLOCK)
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertIn("جارٍ التنفيذ", answered[0]["text"])

    def test_legacy_button_data_is_mapped_then_dispatched(self):
        with patch.object(mb, "handle_briefing_callback", return_value={"status": "success", "message": "ok"}) as spy:
            mb.handle_callback_query(make_callback("morning:supervisor_brief"))
        spy.assert_called_once_with(42, mb.CB_SUPERVISOR_BRIEF)

    def test_handler_failure_never_escapes_and_answers_once(self):
        with patch.object(mb, "handle_briefing_callback", side_effect=RuntimeError("boom")):
            mb.handle_callback_query(make_callback(mb.CB_OPEN_TASKS))  # must not raise
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertTrue(any("تعذر" in text for _cid, text in self.fake.sent))

    def test_missing_callback_id_is_ignored(self):
        mb.handle_callback_query({"id": "", "data": mb.CB_BRAIN_DUMP})
        self.assertEqual(self.api_calls("answerCallbackQuery"), [])


# ---------------------------------------------------------------------------
# Focus block time math
# ---------------------------------------------------------------------------

class FocusStartRoundingTests(unittest.TestCase):
    def test_rounds_up_to_next_five_minutes(self):
        now = dt.datetime(2026, 9, 9, 7, 31, 20)
        self.assertEqual(mb._next_focus_start(now), dt.datetime(2026, 9, 9, 7, 35))

    def test_exact_boundary_moves_to_next(self):
        now = dt.datetime(2026, 9, 9, 7, 30, 0)
        self.assertEqual(mb._next_focus_start(now), dt.datetime(2026, 9, 9, 7, 35))

    def test_rolls_over_the_hour(self):
        now = dt.datetime(2026, 9, 9, 7, 58, 59)
        self.assertEqual(mb._next_focus_start(now), dt.datetime(2026, 9, 9, 8, 0))


# ---------------------------------------------------------------------------
# Commands + brain dump flow + supervisor approval
# ---------------------------------------------------------------------------

class CommandAndBrainDumpFlowTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        self.bot_module = mb.install(self.fake)
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()
        self.fake._PENDING_CALENDAR_EVENTS.clear()

    def tearDown(self):
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()
        self.fake._PENDING_CALENDAR_EVENTS.clear()

    def test_morning_command_sends_dashboard_with_keyboard(self):
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            self.bot_module.command_morning(42)
        sent = [payload for method, payload in self.fake.calls
                if method == "sendMessage" and "reply_markup" in payload]
        self.assertEqual(len(sent), 1)
        markup = sent[0]["reply_markup"]
        self.assertIn("inline_keyboard", markup)
        self.assertIn("لوحة الفرز والتوجيه التنفيذي الصباحي", sent[0]["text"])

    def test_morning_message_intercepted_before_legacy_pipeline(self):
        intercepted = []
        fake = FakeBot()
        fake.handle_message = lambda message: intercepted.append(message)
        mb.install(fake)  # fresh install: the wrap chains onto the recording stub
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            fake.handle_message(make_message("/morning"))
            fake.handle_message(make_message("صباح الخير"))
            fake.handle_message(make_message("لوحة الفرز"))
            fake.handle_message(make_message("وش رأيك بمشروع جديد؟"))
        self.assertEqual(len(intercepted), 1)  # only the non-morning text reached legacy
        self.assertIn("مشروع جديد", intercepted[0]["text"])
        self.assertTrue(any(intake[1] == "COMPLETED" for intake in fake.intake_rows))

    def test_brain_dump_capture_and_close(self):
        mb._cb_brain_dump(42)
        self.fake.handle_message(make_message("متابعة توريد الأجهزة هذا الأسبوع", message_id=2))
        self.fake.handle_message(make_message("مراجعة عقد 0551234567 مع المورد", message_id=3))
        self.fake.handle_message(make_message("تم", message_id=4))

        dumps = [row for tab, row in self.fake.appended if tab == "مدخلات الوكيل"]
        self.assertEqual(len(dumps), 2)
        self.assertEqual(dumps[0][7], "BRAIN_DUMP")
        self.assertEqual(dumps[0][9], "COMPLETED")
        self.assertIn("[PHONE_REDACTED]", dumps[1][5])  # privacy redaction applied
        self.assertNotIn("42", mb._PENDING_BRAIN_DUMPS)
        self.assertTrue(any("أُغلقت جلسة الإفراغ الذهني" in text for _cid, text in self.fake.sent))
        self.assertTrue(any("عدد ما التُقط: 2" in text for _cid, text in self.fake.sent))

    def test_brain_dump_close_offers_delegation_when_team_available(self):
        mb._cb_brain_dump(42)
        self.fake.handle_message(make_message("ملاحظة", message_id=2))
        self.fake.handle_message(make_message("تم", message_id=3))
        closing = [text for _cid, text in self.fake.sent if "أُغلقت جلسة" in text]
        self.assertTrue(closing)
        if mb._team is not None:
            self.assertIn("/delegate auto", closing[0])

    def test_brain_dump_capture_survives_sheets_failure(self):
        mb._cb_brain_dump(42)
        self.fake.append_should_fail = True
        self.fake.handle_message(make_message("ملاحظة مهمة", message_id=5))
        self.assertTrue(any("لم يصدر إيصال حفظ" in text for _cid, text in self.fake.sent))
        # Session stays open: the next message is still captured (not sent to the AI).
        self.assertIn("42", mb._PENDING_BRAIN_DUMPS)
        self.fake.append_should_fail = False
        self.fake.handle_message(make_message("ملاحظة ثانية", message_id=6))
        self.assertEqual(len([r for t, r in self.fake.appended if t == "مدخلات الوكيل"]), 1)

    def test_brain_dump_voice_transcribed_then_saved(self):
        mb._cb_brain_dump(42)
        voice_message = {
            "message_id": 7,
            "chat": {"id": 42, "type": "private"},
            "voice": {"file_id": "file-1"},
        }
        self.fake.handle_message(voice_message)
        dumps = [row for tab, row in self.fake.appended if tab == "مدخلات الوكيل"]
        self.assertEqual(len(dumps), 1)
        self.assertEqual(dumps[0][4], "VOICE")
        self.assertIn("متابعة توريد الأجهزة", dumps[0][5])
        self.assertTrue(any("التفريغ" in text for _cid, text in self.fake.sent))

    def test_brain_dump_expires_and_falls_back_to_normal_pipeline(self):
        mb._PENDING_BRAIN_DUMPS["42"] = {"expires": time_expired(), "count": 1, "captures": []}
        intercepted = []
        fake = FakeBot()
        fake.handle_message = lambda message: intercepted.append(message)
        mb.install(fake)
        fake.handle_message(make_message("رسالة عادية بعد انتهاء الجلسة", message_id=8))
        self.assertEqual(len(intercepted), 1)
        self.assertNotIn("42", mb._PENDING_BRAIN_DUMPS)

    def test_supervisor_brief_confirm_flow(self):
        mb._PENDING_SUPERVISOR_BRIEFS["tok1"] = {
            "chat_id": "42",
            "draft": "📢 توجيه المشرفين — تجربة",
            "expires": dt.datetime.now().timestamp() + 600,
        }
        self.bot_module.command_confirm_supervisor_brief(42, "tok1")
        self.assertEqual(len(mb._PENDING_SUPERVISOR_BRIEFS), 0)
        status_rows = [row for tab, row in self.fake.appended if tab == "حالة الوكيل"]
        self.assertEqual(status_rows[0][1], "MORNING_SUPERVISOR_BRIEF")
        self.assertEqual(status_rows[0][2], "APPROVED")
        self.assertTrue(any("تم اعتماد توجيه المشرفين وتوثيقه" in text for _cid, text in self.fake.sent))

    def test_supervisor_brief_receipt_is_honest_when_sheets_fail(self):
        mb._PENDING_SUPERVISOR_BRIEFS["tok3"] = {
            "chat_id": "42",
            "draft": "📢 توجيه المشرفين — تجربة",
            "expires": dt.datetime.now().timestamp() + 600,
        }
        self.fake.append_should_fail = True
        self.bot_module.command_confirm_supervisor_brief(42, "tok3")
        # Never claim a Sheets write succeeded without a concrete receipt.
        self.assertTrue(any("تعذر توثيقه" in text for _cid, text in self.fake.sent))
        self.assertFalse(any("وتوثيقه في Google Sheets" in text for _cid, text in self.fake.sent))

    def test_supervisor_brief_rejects_expired_token(self):
        mb._PENDING_SUPERVISOR_BRIEFS["tok4"] = {
            "chat_id": "42", "draft": "d", "expires": dt.datetime.now().timestamp() - 1,
        }
        self.bot_module.command_confirm_supervisor_brief(42, "tok4")
        self.assertEqual(len(mb._PENDING_SUPERVISOR_BRIEFS), 0)  # expired token is consumed
        self.assertTrue(any("انتهت مدة" in text for _cid, text in self.fake.sent))

    def test_supervisor_brief_rejects_wrong_chat_and_keeps_token(self):
        mb._PENDING_SUPERVISOR_BRIEFS["tok2"] = {
            "chat_id": "42",
            "draft": "d",
            "expires": dt.datetime.now().timestamp() + 600,
        }
        self.bot_module.command_confirm_supervisor_brief(43, "tok2")  # wrong chat
        self.assertTrue(any("لا يخص هذه المحادثة" in text for _cid, text in self.fake.sent))
        self.assertEqual(len(mb._PENDING_SUPERVISOR_BRIEFS), 1)  # token stays valid for its chat

    def test_install_is_idempotent(self):
        first = mb.install(self.fake)
        second = mb.install(self.fake)
        self.assertIs(first, second)


def time_expired():
    return dt.datetime.now().timestamp() - 1


# ---------------------------------------------------------------------------
# Proactive daily send
# ---------------------------------------------------------------------------

class ProactiveMorningTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        mb.install(self.fake)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(mb, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent_dashboards(self):
        return [payload for method, payload in self.fake.calls
                if method == "sendMessage" and "reply_markup" in payload]

    def test_sends_inside_window_once_then_dedupes(self):
        morning = dt.datetime(2026, 9, 9, 7, 0)
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            self.assertTrue(mb._maybe_send_morning_briefing(now=morning))
            self.assertFalse(mb._maybe_send_morning_briefing(now=morning + dt.timedelta(minutes=5)))
            self.assertFalse(mb._maybe_send_morning_briefing(now=morning + dt.timedelta(minutes=10)))
        self.assertEqual(len(self.sent_dashboards()), 1)

    def test_no_send_outside_window(self):
        evening = dt.datetime(2026, 9, 9, 17, 0)
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()):
            self.assertFalse(mb._maybe_send_morning_briefing(now=evening))
        self.assertEqual(self.sent_dashboards(), [])

    def test_kill_switch_disables_proactive_mode(self):
        morning = dt.datetime(2026, 9, 9, 7, 0)
        with patch.dict(os_environ(), {"MORNING_BRIEFING_AUTO": "0"}), patch.object(
            mb, "get_sheet_intelligence", return_value=healthy_intel()
        ):
            self.assertFalse(mb._maybe_send_morning_briefing(now=morning))
        self.assertEqual(self.sent_dashboards(), [])

    def test_force_bypasses_window_but_not_dedupe(self):
        evening = dt.datetime(2026, 9, 9, 17, 0)
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            self.assertTrue(mb._maybe_send_morning_briefing(now=evening, force=True))
            self.assertFalse(mb._maybe_send_morning_briefing(now=evening, force=True))
        self.assertEqual(len(self.sent_dashboards()), 1)

    def test_send_failure_still_marks_sent_to_avoid_spam(self):
        """A Telegram send failure is retried at most once per day: the ledger
        is written even on failure so the heartbeat cannot spam retries."""
        morning = dt.datetime(2026, 9, 9, 7, 0)
        original_api = self.fake.api
        attempts = []

        def failing_api(method, payload=None, timeout=60):
            if method == "sendMessage":
                attempts.append(payload)
                raise RuntimeError("telegram down")
            return original_api(method, payload, timeout)

        with patch.object(self.fake, "api", side_effect=failing_api), patch.object(
            mb, "get_sheet_intelligence", return_value=healthy_intel()
        ), patch.object(mb, "today_clinic_events", return_value=([], None)):
            self.assertFalse(mb._maybe_send_morning_briefing(now=morning))
            self.assertFalse(mb._maybe_send_morning_briefing(now=morning + dt.timedelta(minutes=1)))
        self.assertEqual(len(attempts), 1)  # second heartbeat: deduped, no retry

    def test_heartbeat_chain_triggers_proactive_send(self):
        # install() wrapped the calendar heartbeat; ticking it inside the window
        # must send the dashboard exactly once.
        morning = dt.datetime(2026, 9, 9, 7, 0)
        with patch.object(mb, "_now_local", return_value=morning), patch.object(
            mb, "get_sheet_intelligence", return_value=healthy_intel()
        ), patch.object(mb, "today_clinic_events", return_value=([], None)):
            self.fake._maybe_send_calendar_alerts()
            self.fake._maybe_send_calendar_alerts()
        self.assertEqual(len(self.fake.alert_heartbeats), 2)  # original heartbeat preserved
        self.assertEqual(len(self.sent_dashboards()), 1)

    def test_ledger_persists_across_instances(self):
        morning = dt.datetime(2026, 9, 9, 7, 0)
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            mb._maybe_send_morning_briefing(now=morning)
        # A "restart": fresh check reads the same ledger file.
        self.assertTrue(mb._already_sent_today(dt.date(2026, 9, 9)))
        self.assertFalse(mb._already_sent_today(dt.date(2026, 9, 10)))


def os_environ():
    import os

    return os.environ


class MorningPayloadTests(unittest.TestCase):
    def test_sheets_failure_is_fail_soft(self):
        mb.install(FakeBot())
        with patch.object(mb, "get_sheet_intelligence", side_effect=RuntimeError("sheets down")), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            payload = mb.morning_payload()
        self.assertEqual(payload["overdue"], [])
        self.assertEqual(payload["clinics"], [])
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("Google Sheets", payload["errors"][0])

    def test_calendar_failure_is_reported_not_fatal(self):
        mb.install(FakeBot())
        with patch.object(mb, "get_sheet_intelligence", return_value=healthy_intel()), patch.object(
            mb, "today_clinic_events", return_value=([], "Google Calendar: down")
        ):
            payload = mb.morning_payload()
        self.assertEqual(len(payload["overdue"]), 1)
        self.assertIn("Google Calendar", payload["errors"][0])

    def test_healthy_payload(self):
        mb.install(FakeBot())
        with patch.object(mb, "_sheets_snapshot", return_value=full_sheet_data()), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ), patch.object(mb, "_today", return_value=TODAY):
            payload = mb.morning_payload()
        self.assertEqual(len(payload["overdue"]), 3)
        self.assertEqual(len(payload["clinics"]), 2)
        self.assertIn("🔴", payload["staff_coverage"])
        self.assertEqual(payload["errors"], [])


if __name__ == "__main__":
    unittest.main()
