# -*- coding: utf-8 -*-
"""Morning Briefing Mode (وضع التوجيه الصباحي) tests — no network, no model calls."""
import datetime as dt
import unittest
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
        self.handle_message = lambda message: self.calls.append(("handle_message", message))
        self.configure_commands = lambda: self.calls.append(("configure_commands",))
        self.command_start = lambda chat_id: self.sent.append(("start", chat_id))

    def api(self, method, payload=None, timeout=60):
        self.calls.append((method, payload))
        if method == "getMyCommands":
            return [{"command": "start"}]
        return {}

    def send(self, chat_id, text):
        self.sent.append((chat_id, str(text)))

    def _authorized(self, chat_id, chat_type):
        return str(chat_id) == "42"

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


EMPTY_PAYLOAD = {
    "overdue": [], "clinics": [], "today_events": [], "errors": [],
    "generated_at": "2026-09-09T07:30:00+03:00",
}


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


class RenderAndKeyboardTests(unittest.TestCase):
    def test_keyboard_has_three_buttons_with_short_callback_data(self):
        keyboard = mb.morning_keyboard()
        buttons = [btn for row in keyboard["inline_keyboard"] for btn in row]
        self.assertEqual(len(buttons), 3)
        labels = [btn["text"] for btn in buttons]
        self.assertIn("🎙️ إفراغ ذهني سريع", labels)
        self.assertIn("📢 إرسال توجيه المشرفين", labels)
        self.assertIn("📊 فتح شيت المهام", labels)
        for btn in buttons:
            self.assertLessEqual(len(btn["callback_data"].encode("utf-8")), 64)

    def test_dashboard_renders_sections(self):
        mb.install(FakeBot())
        payload = {
            "overdue": mb.overdue_tasks(tasks_sheet_data(), today=TODAY),
            "clinics": mb.clinic_readiness(supervisor_sheet_data()),
            "today_events": [
                {"title": "عيادة الدوخة — جولة", "start": "2026-09-09T09:00:00+03:00", "is_clinic": True},
                {"title": "اجتماع الإدارة", "start": "2026-09-09T13:00:00+03:00", "is_clinic": False},
            ],
            "errors": [],
            "generated_at": "2026-09-09T07:30:00+03:00",
        }
        text = mb.render_morning_dashboard(payload)
        self.assertIn("وضع التوجيه الصباحي", text)
        self.assertIn("مهام متأخرة: 3", text)
        self.assertIn("جاهزية العيادات", text)
        self.assertIn("عيادة الدوخة والدهليزي", text)
        self.assertIn("مواعيد اليوم: 2", text)
        self.assertIn("(منها 1 للعيادات)", text)

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


class CallbackQueryHandlerTests(unittest.TestCase):
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

    def test_valid_button_answers_and_dispatches(self):
        seen = []
        with patch.dict(mb._CALLBACK_ACTIONS, {mb.CB_OPEN_TASKS: lambda cid: seen.append(cid)}):
            mb.handle_callback_query(make_callback(mb.CB_OPEN_TASKS))
        self.assertEqual(seen, [42])
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertIn("جارٍ التنفيذ", answered[0]["text"])

    def test_answers_callback_exactly_once_and_reports_failure(self):
        calls = []

        def flaky(chat_id):
            calls.append(chat_id)
            raise RuntimeError("boom")

        with patch.dict(mb._CALLBACK_ACTIONS, {mb.CB_OPEN_TASKS: flaky}):
            mb.handle_callback_query(make_callback(mb.CB_OPEN_TASKS))
        self.assertEqual(len(calls), 1)
        # answerCallbackQuery is sent exactly once (the ack); the failure detail
        # reaches the chat as a normal message instead of a second answer.
        answered = self.api_calls("answerCallbackQuery")
        self.assertEqual(len(answered), 1)
        self.assertTrue(any("تعذر" in text for _cid, text in self.fake.sent))

    def test_brain_dump_button_opens_session(self):
        mb.handle_callback_query(make_callback(mb.CB_BRAIN_DUMP))
        self.assertIn("42", mb._PENDING_BRAIN_DUMPS)
        self.assertTrue(any("الإفراغ الذهني" in text for _cid, text in self.fake.sent))

    def test_supervisor_brief_button_creates_pending_token(self):
        with patch.object(mb, "morning_payload", return_value=dict(EMPTY_PAYLOAD)):
            mb.handle_callback_query(make_callback(mb.CB_SUPERVISOR_BRIEF))
        self.assertEqual(len(mb._PENDING_SUPERVISOR_BRIEFS), 1)
        self.assertTrue(any("مسودة توجيه المشرفين" in text for _cid, text in self.fake.sent))

    def test_open_tasks_button_sends_link(self):
        with patch.object(mb, "tasks_sheet_link", return_value="https://example.com/edit#gid=1"), patch.object(
            mb, "_sheets_snapshot", return_value=tasks_sheet_data()
        ), patch.object(mb, "_today", return_value=TODAY):
            mb.handle_callback_query(make_callback(mb.CB_OPEN_TASKS))
        self.assertTrue(any("شيت المهام" in text and "المهام المتأخرة الآن: 3" in text
                            for _cid, text in self.fake.sent))


class CommandAndBrainDumpFlowTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        self.bot_module = mb.install(self.fake)
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()

    def tearDown(self):
        mb._PENDING_BRAIN_DUMPS.clear()
        mb._PENDING_SUPERVISOR_BRIEFS.clear()

    def test_morning_command_sends_dashboard_with_keyboard(self):
        with patch.object(mb, "morning_payload", return_value=dict(EMPTY_PAYLOAD)):
            self.bot_module.command_morning(42)
        sent = [payload for method, payload in self.fake.calls
                if method == "sendMessage" and "reply_markup" in payload]
        self.assertEqual(len(sent), 1)
        self.assertIn("inline_keyboard", sent[0]["reply_markup"])
        self.assertIn("وضع التوجيه الصباحي", sent[0]["text"])

    def test_morning_message_intercepted_before_legacy_pipeline(self):
        intercepted = []
        fake = FakeBot()
        fake.handle_message = lambda message: intercepted.append(message)
        mb.install(fake)  # fresh install: the wrap chains onto the recording stub
        with patch.object(mb, "morning_payload", return_value=dict(EMPTY_PAYLOAD)):
            fake.handle_message(make_message("/morning"))
            fake.handle_message(make_message("صباح الخير"))
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

    def test_supervisor_brief_rejects_wrong_token_or_chat(self):
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


class MorningPayloadTests(unittest.TestCase):
    def test_sheets_failure_is_fail_soft(self):
        mb.install(FakeBot())
        with patch.object(mb, "_sheets_snapshot", side_effect=RuntimeError("sheets down")), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ):
            payload = mb.morning_payload()
        self.assertEqual(payload["overdue"], [])
        self.assertEqual(payload["clinics"], [])
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("Google Sheets", payload["errors"][0])

    def test_healthy_payload(self):
        mb.install(FakeBot())
        data = {**tasks_sheet_data(), **supervisor_sheet_data()}
        with patch.object(mb, "_sheets_snapshot", return_value=data), patch.object(
            mb, "today_clinic_events", return_value=([], None)
        ), patch.object(mb, "_today", return_value=TODAY):
            payload = mb.morning_payload()
        self.assertEqual(len(payload["overdue"]), 3)
        self.assertEqual(len(payload["clinics"]), 2)
        self.assertEqual(payload["errors"], [])


if __name__ == "__main__":
    unittest.main()
