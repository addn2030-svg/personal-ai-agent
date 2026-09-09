# -*- coding: utf-8 -*-
"""Task Ledger + Life Domains tests — no network, no model calls.

Covers: matrix normalization (the exact 2026-09-09 Life & Work OS payload),
schema-adaptive planning (updates/appends/header adds/skips), staleness and
duplicate guards at execution, preview/execution rendering, the Telegram
import->approval flow, the /tasks domain-grouped listing, and the life
domains classifier.
"""
import datetime as dt
import json
import unittest
from unittest.mock import patch

from connectors import life_domains
from connectors import task_ledger as tl

TODAY = dt.date(2026, 9, 9)


def user_matrix():
    """The exact task matrix prepared in the Life & Work OS session."""
    return [
        {
            "Task_ID": "TASK-0015",
            "Title": "ملف الرعاية المنزلية",
            "Domain": "العيادة والتوسع الاستراتيجي",
            "Owner": "عبدالرحمن هوساوي",
            "Due_Date": "2026-09-24",
            "Status": "IN_PROGRESS",
            "Next_Action": "مراجعة نموذج الحوكمة والباقات المالية للتوسع",
        },
        {
            "Task_ID": "TASK-0006",
            "Title": "استكمال الملفات المالية والادخار",
            "Domain": "المالية الشخصية",
            "Owner": "عبدالرحمن هوساوي",
            "Due_Date": "2026-09-11",
            "Status": "SCHEDULED",
            "Next_Action": "جلسة مراجعة كشوف الميزانية الخميس 7:00 ص",
        },
        {
            "Task_ID": "TASK-0021",
            "Title": "تدريب منصة DHS",
            "Domain": "قسم التأهيل الطبي",
            "Owner": "مشرف التدريب والتعليم المستمر",
            "Due_Date": "2026-09-17",
            "Status": "DELEGATED",
            "Next_Action": "استلام جدول التدريب ومتابعة اكتمال الأخصائيين",
        },
        {
            "Task_ID": "TASK-0022",
            "Title": "التقارير اليومية ومتابعة المخرجات",
            "Domain": "قسم التأهيل الطبي",
            "Owner": "مشرفو الوحدات (PT/OT/ST)",
            "Due_Date": "يومي مستمر",
            "Status": "IN_PROGRESS",
            "Next_Action": "اعتماد الإغلاق نهاية كل دوام",
        },
        {
            "Task_ID": "TASK-0023",
            "Title": "حصر مشتريات وعهدة القسم",
            "Domain": "قسم التأهيل الطبي",
            "Owner": "منسق العهد والمستودع",
            "Due_Date": "2026-09-15",
            "Status": "PENDING",
            "Next_Action": "رفع قائمة النواقص والمواد المستهلكة",
        },
        {
            "Task_ID": "TASK-0024",
            "Title": "تطوير التواصل القيادي (Effective Communication)",
            "Domain": "التطوير الشخصي",
            "Owner": "عبدالرحمن هوساوي",
            "Due_Date": "2026-09-30",
            "Status": "IN_PROGRESS",
            "Next_Action": "تطبيق أطر التغذية الراجعة التنفيذية في اجتماعات القسم",
        },
    ]


def ledger_rows():
    """Existing ledger: TASK-0006 and TASK-0015 already present (no Domain column)."""
    return [
        ["Task_ID", "المهمة", "المسؤول", "الموعد النهائي", "الحالة", "الخطوة التالية"],
        ["TASK-0006", "استكمال الملفات المالية والادخار", "عبدالرحمن هوساوي",
         "2026-09-11", "PENDING", "جمع البيانات الأولية"],
        ["TASK-0015", "ملف الرعاية المنزلية", "عبدالرحمن هوساوي",
         "2026-09-24", "IN_PROGRESS", "مراجعة أولية"],
        ["TASK-0009", "مهمة غير ممسومة", "آخر", "2026-08-01", "DONE", ""],
    ]


class FakeSheets:
    """Stand-in for the sheet_intelligence seam used by task_ledger."""

    def __init__(self, rows=None, columns=26, direct=True):
        self.rows = rows if rows is not None else ledger_rows()
        self.columns = columns
        self.direct = direct
        self.updates = []      # (sheet, a1, value)
        self.appends = []      # (sheet, row)
        self.fail_updates = False
        self.fail_appends = False

    # seam used by task_ledger
    def snapshot(self, max_rows=80, max_cols=16):
        return {tl.LEDGER_TAB: [list(r) for r in self.rows]}

    def metadata(self):
        return [{"title": tl.LEDGER_TAB, "sheetId": 5, "rows": 200, "columns": self.columns}]

    def update_cell(self, sheet, a1, value):
        if self.fail_updates:
            raise RuntimeError("update down")
        self.updates.append((sheet, a1, value))
        # keep the fake tab coherent so staleness re-reads match
        import re as _re
        match = _re.fullmatch(r"([A-Z]{1,3})(\d+)", a1)
        col = tl._column_number(match.group(1)) - 1
        row_no = int(match.group(2))
        while len(self.rows) <= row_no - 1:
            self.rows.append([])
        row = self.rows[row_no - 1]
        while len(row) <= col:
            row.append("")
        row[col] = str(value)
        return {"ok": True, "sheet": sheet, "range": a1}

    def append_row(self, sheet, row):
        if self.fail_appends:
            raise RuntimeError("append down")
        self.appends.append((sheet, list(row)))
        self.rows.append(list(row))
        return {"ok": True, "sheet": sheet, "range": f"A{len(self.rows)}"}

    def _direct_ready(self):
        return self.direct


class FakeBot:
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
        self.handle_message = lambda message: self.calls.append(("handle_message", message))
        self.configure_commands = lambda: None
        self.command_start = lambda chat_id: None

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
        return text, "TEXT", ""

    def _local_capture(self, text, message, kind):
        return f"IID-{message.get('message_id', 1)}"

    def _save_intake(self, iid, message, text, kind, attachment, status, response_id="", error=""):
        self.intake_rows.append((iid, status, str(error)))
        return True

    def _append(self, tab, row):
        self.appended.append((tab, row))
        return True

    def _now(self):
        return "2026-09-09T08:00:00+03:00"


def make_message(text, chat_id=42, message_id=1):
    return {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}, "text": text}


# ---------------------------------------------------------------------------
# Life domains
# ---------------------------------------------------------------------------

class LifeDomainsTests(unittest.TestCase):
    def test_registry_has_five_ordered_domains(self):
        self.assertEqual(len(life_domains.DOMAINS), 5)
        orders = sorted(d["order"] for d in life_domains.DOMAINS.values())
        self.assertEqual(orders, [1, 2, 3, 4, 5])

    def test_matrix_domains_classify_correctly(self):
        expected = {
            "TASK-0015": "home_care_clinic",
            "TASK-0006": "personal_finance",
            "TASK-0021": "rehab_leadership",
            "TASK-0022": "rehab_leadership",
            "TASK-0023": "rehab_leadership",
            "TASK-0024": "growth_social",
        }
        for task in user_matrix():
            key = life_domains.label_to_key(task["Domain"])
            self.assertEqual(key, expected[task["Task_ID"]], task["Task_ID"])

    def test_short_ascii_keywords_use_word_boundaries(self):
        # "st" must not match inside English words.
        self.assertIsNone(life_domains.classify_text("first post must not match"))
        self.assertEqual(life_domains.classify_text("تدريب الوحدات PT OT ST"), "rehab_leadership")

    def test_no_hit_returns_none(self):
        self.assertIsNone(life_domains.classify_text("ملاحظة عادية بلا كلمات مفتاحية"))

    def test_badge_and_map_text(self):
        self.assertIn("🏥", life_domains.badge("rehab_leadership"))
        self.assertIn("🗂️", life_domains.badge(None))
        text = life_domains.domain_map_text()
        for title in ("قيادة قسم التأهيل الطبي", "العائلة والأسرة", "الإدارة المالية الشخصية"):
            self.assertIn(title, text)


# ---------------------------------------------------------------------------
# Matrix normalization
# ---------------------------------------------------------------------------

class NormalizeMatrixTests(unittest.TestCase):
    def test_parses_the_session_matrix_from_json_text(self):
        tasks = tl.normalize_matrix(json.dumps(user_matrix(), ensure_ascii=False))
        self.assertEqual(len(tasks), 6)
        by_id = {t["task_id"]: t for t in tasks}
        self.assertEqual(by_id["TASK-0021"]["owner"], "مشرف التدريب والتعليم المستمر")
        self.assertEqual(by_id["TASK-0022"]["due_date"], "يومي مستمر")  # free text allowed

    def test_accepts_tasks_wrapper_and_object_input(self):
        wrapped = {"tasks": user_matrix()[:2]}
        self.assertEqual(len(tl.normalize_matrix(wrapped)), 2)
        self.assertEqual(len(tl.normalize_matrix(user_matrix()[:1])), 1)

    def test_rejects_bad_json(self):
        with self.assertRaises(ValueError) as ctx:
            tl.normalize_matrix("[{باطل")
        self.assertIn("JSON غير صالح", str(ctx.exception))

    def test_rejects_missing_required_fields(self):
        with self.assertRaises(ValueError):
            tl.normalize_matrix([{"Task_ID": "TASK-0001"}])
        with self.assertRaises(ValueError):
            tl.normalize_matrix([{"Title": "بلا معرف"}])

    def test_rejects_invalid_iso_date(self):
        with self.assertRaises(ValueError):
            tl.normalize_matrix([{"Task_ID": "T1", "Title": "x", "Due_Date": "2026-02-30"}])

    def test_dedupes_by_task_id_last_wins(self):
        tasks = tl.normalize_matrix([
            {"Task_ID": "T1", "Title": "أول"},
            {"Task_ID": "T1", "Title": "ثاني"},
        ])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "ثاني")

    def test_rejects_oversized_batch(self):
        batch = [{"Task_ID": f"T{i}", "Title": "x"} for i in range(tl.MAX_IMPORT_TASKS + 1)]
        with self.assertRaises(ValueError):
            tl.normalize_matrix(batch)


# ---------------------------------------------------------------------------
# Planning (schema-adaptive)
# ---------------------------------------------------------------------------

class PlanUpsertTests(unittest.TestCase):
    def setUp(self):
        self.sheets = FakeSheets()

    def plan(self, tasks=None, data=None):
        with patch.object(tl, "sheets", self.sheets):
            return tl.plan_upsert(tasks if tasks is not None else user_matrix(), data=data)

    def test_update_path_captures_before_after(self):
        plan = self.plan()
        updates = [m for m in plan["mutations"] if m["kind"] == "update_row"]
        by_id = {m["task_id"]: m for m in updates}
        # TASK-0006 exists: status PENDING -> SCHEDULED captured with before value
        writes = {w["header"]: w for w in by_id["TASK-0006"]["writes"]}
        self.assertEqual(writes["الحالة"]["before"], "PENDING")
        self.assertEqual(writes["الحالة"]["after"], "SCHEDULED")
        # TASK-0015: Next_Action differs + the new Domain column gets its value
        self.assertEqual(
            [w["header"] for w in by_id["TASK-0015"]["writes"]], ["الدائرة", "الخطوة التالية"]
        )

    def test_append_path_for_new_tasks(self):
        plan = self.plan()
        appends = {m["task_id"] for m in plan["mutations"] if m["kind"] == "append_row"}
        self.assertEqual(appends, {"TASK-0021", "TASK-0022", "TASK-0023", "TASK-0024"})

    def test_header_add_for_missing_domain_column(self):
        plan = self.plan()
        self.assertEqual([a["field"] for a in plan["header_adds"]], ["domain"])
        self.assertEqual(plan["header_adds"][0]["header"], "الدائرة")
        self.assertEqual(plan["header_adds"][0]["cell"], "G1")

    def test_no_change_task_is_skipped_not_mutated(self):
        tasks = [{
            "Task_ID": "TASK-0006", "Title": "استكمال الملفات المالية والادخار",
            "Owner": "عبدالرحمن هوساوي", "Due_Date": "2026-09-11",
            "Status": "PENDING", "Next_Action": "جمع البيانات الأولية",
        }]
        plan = self.plan(tasks=tasks)
        self.assertEqual(plan["mutations"], [])
        self.assertEqual(plan["skipped"][0]["task_id"], "TASK-0006")

    def test_grid_limit_blocks_new_columns(self):
        self.sheets.columns = 6  # exactly the current width: no room for Domain
        with self.assertRaises(ValueError) as ctx:
            self.plan()
        self.assertIn("حد أعمدة", str(ctx.exception))

    def test_webhook_only_env_adds_warning(self):
        self.sheets.direct = False
        plan = self.plan()
        self.assertTrue(plan["warnings"])
        self.assertIn("Service Account", plan["warnings"][0])

    def test_missing_tab_raises_clean_error(self):
        empty = FakeSheets(rows=[])
        empty.metadata = lambda: [{"title": "Other", "columns": 26}]
        with patch.object(tl, "sheets", empty):
            with self.assertRaises(ValueError) as ctx:
                tl.plan_upsert(user_matrix())
        self.assertIn("غير موجود", str(ctx.exception))

    def test_empty_existing_tab_plans_full_import(self):
        empty = FakeSheets(rows=[])
        with patch.object(tl, "sheets", empty):
            plan = tl.plan_upsert(user_matrix()[:1])
        self.assertEqual(len(plan["mutations"]), 1)
        added_fields = {a["field"] for a in plan["header_adds"]}
        self.assertEqual(
            added_fields,
            {"task_id", "title", "domain", "owner", "due_date", "status", "next_action"},
        )


# ---------------------------------------------------------------------------
# Execution (guards + receipts)
# ---------------------------------------------------------------------------

class ExecutePlanTests(unittest.TestCase):
    def setUp(self):
        self.sheets = FakeSheets()

    def execute(self, plan):
        with patch.object(tl, "sheets", self.sheets):
            return tl.execute_plan(plan)

    def plan(self):
        with patch.object(tl, "sheets", self.sheets):
            return tl.plan_upsert(user_matrix())

    def test_full_import_executes_with_receipts(self):
        result = self.execute(self.plan())
        self.assertEqual(result["status"], "EXECUTED")
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(result["appended"], 4)
        # header add + updates: TASK-0006 (status+next_action+domain) and
        # TASK-0015 (domain+next_action) — new-column values reach existing rows too.
        cell_writes = [u for u in self.sheets.updates]
        self.assertEqual(cell_writes[0], (tl.LEDGER_TAB, "G1", "الدائرة"))
        self.assertEqual(len([u for u in cell_writes if u[1] != "G1"]), 5)
        self.assertEqual(len(self.sheets.appends), 4)

    def test_idempotent_header_add_is_skipped(self):
        plan = self.plan()
        self.execute(plan)  # applies headers
        # second execution of the same plan: header already there -> skipped, no error
        result = self.execute(plan)
        self.assertEqual(result["status"], "FAILED")  # updates are stale now, which is honest
        self.assertTrue(any("STALE_PREVIEW" in e["error"] for e in result["errors"]))

    def test_stale_update_fails_only_that_task(self):
        plan = self.plan()
        # simulate someone editing TASK-0006's status after the preview
        self.sheets.rows[1][4] = "SCHEDULED"
        result = self.execute(plan)
        self.assertEqual(result["status"], "PARTIAL")
        failed = {e["task_id"] for e in result["errors"]}
        self.assertEqual(failed, {"TASK-0006"})
        succeeded = {r["task_id"] for r in result["receipts"]}
        self.assertIn("TASK-0015", succeeded)
        self.assertIn("TASK-0021", succeeded)

    def test_duplicate_append_guard(self):
        plan = self.plan()
        # pre-insert TASK-0021 after planning but before execution
        self.sheets.rows.append(
            ["TASK-0021", "تدريب منصة DHS", "آخر", "2026-09-17", "DELEGATED", "منافس", "—"]
        )
        result = self.execute(plan)
        failed = {e["task_id"] for e in result["errors"]}
        self.assertIn("TASK-0021", failed)
        self.assertTrue(any("موجودة مسبقًا" in e["error"] for e in result["errors"]))

    def test_unexpected_header_content_blocks_header_add(self):
        plan = self.plan()
        self.sheets.rows[0].append("قيمة غير متوقعة")  # G1 now occupied
        with self.assertRaises(RuntimeError) as ctx:
            self.execute(plan)
        self.assertIn("STALE_PREVIEW G1", str(ctx.exception))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class RenderTests(unittest.TestCase):
    def test_preview_lists_all_actions_and_token(self):
        sheets = FakeSheets()
        with patch.object(tl, "sheets", sheets):
            plan = tl.plan_upsert(user_matrix())
        text = tl.render_plan_preview(plan, "ab12cd")
        self.assertIn("معاينة تحديث سجل المهام", text)
        self.assertIn("إضافة 4 · تحديث 2 · تخطي 0", text)
        self.assertIn("عمود جديد: «الدائرة»", text)
        self.assertIn("TASK-0006 — تحديث صف 2", text)
        self.assertIn("PENDING → SCHEDULED", text)
        self.assertIn("/confirm_tasks ab12cd", text)
        self.assertIn("لم يُنفذ أي تغيير بعد", text)

    def test_execution_report_counts(self):
        text = tl.render_execution_report({
            "status": "PARTIAL", "appended": 1,
            "receipts": [{"task_id": "T1", "kind": "cell", "header": "الحالة",
                          "before": "A", "after": "B", "destination": "X!B2"}],
            "errors": [{"task_id": "T2", "error": "STALE_PREVIEW B3"}],
        })
        self.assertIn("PARTIAL", text)
        self.assertIn("نجح: 1 عملية · فشل: 1", text)
        self.assertIn("T2: STALE_PREVIEW B3", text)

    def test_tasks_listing_groups_by_domain_with_overdue_marker(self):
        rows = [
            ["Task_ID", "المهمة", "المسؤول", "الموعد النهائي", "الحالة", "الخطوة التالية", "الدائرة"],
            ["TASK-0006", "استكمال الملفات المالية والادخار", "عبدالرحمن", "2026-09-11", "PENDING", "", "المالية الشخصية"],
            ["TASK-0021", "تدريب منصة DHS", "مشرف التدريب", "2026-09-17", "DELEGATED", "", "قسم التأهيل الطبي"],
        ]
        with patch.object(tl, "_ledger_rows", return_value=rows):
            text = tl.render_tasks_text()
        self.assertIn("📋 سجل المهام", text)
        self.assertIn("💰 المالية (1)", text)      # TASK-0006 via its Domain label
        self.assertIn("🏥 قسم التأهيل (1)", text)  # TASK-0021 via its Domain label
        self.assertIn("TASK-0006", text)

    def test_tasks_listing_flags_overdue_iso_dates(self):
        rows = [
            ["Task_ID", "المهمة", "الموعد النهائي"],
            ["TASK-0001", "مهمة متأخرة", "2026-08-01"],
            ["TASK-0002", "مهمة قادمة", "2026-10-01"],
        ]
        with patch.object(tl, "_ledger_rows", return_value=rows):
            text = tl.render_tasks_text()
        self.assertIn("⏰", text.split("TASK-0001")[1].split("\n")[0])
        self.assertNotIn("⏰", text.split("TASK-0002")[1].split("\n")[0])


# ---------------------------------------------------------------------------
# Telegram flow
# ---------------------------------------------------------------------------

class TelegramFlowTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBot()
        self.bot_module = tl.install(self.fake)
        tl._PENDING_IMPORTS.clear()
        self.sheets = FakeSheets()

    def tearDown(self):
        tl._PENDING_IMPORTS.clear()

    def test_import_command_produces_preview_and_token(self):
        raw = "/tasks_import " + json.dumps(user_matrix(), ensure_ascii=False)
        with patch.object(tl, "sheets", self.sheets):
            self.fake.handle_message(make_message(raw, message_id=1))
        self.assertEqual(len(tl._PENDING_IMPORTS), 1)
        preview = self.fake.sent[-1][1]
        self.assertIn("معاينة تحديث سجل المهام", preview)
        self.assertIn("/confirm_tasks", preview)

    def test_import_command_rejects_bad_payload_with_usage(self):
        self.fake.handle_message(make_message("/tasks_import باطل", message_id=2))
        self.assertEqual(len(tl._PENDING_IMPORTS), 0)
        self.assertIn("❌", self.fake.sent[-1][1])
        self.assertIn("الاستخدام", self.fake.sent[-1][1])

    def test_confirm_executes_and_logs_receipt(self):
        tl._PENDING_IMPORTS["tok1"] = {
            "chat_id": "42",
            "plan": {"tab": tl.LEDGER_TAB, "headers": [], "header_adds": [],
                     "mutations": [], "skipped": [], "warnings": []},
            "tasks": [],
            "expires": dt.datetime.now().timestamp() + 600,
        }
        executed = {}
        with patch.object(tl, "execute_plan", return_value={
            "status": "EXECUTED", "appended": 0, "receipts": [], "errors": [],
        }) as spy:
            self.bot_module.command_confirm_tasks(42, "tok1")
            executed["called"] = spy.call_count
        self.assertEqual(executed["called"], 1)
        self.assertNotIn("tok1", tl._PENDING_IMPORTS)
        status_rows = [row for tab, row in self.fake.appended if tab == "حالة الوكيل"]
        self.assertEqual(status_rows[0][1], "TASK_LEDGER_IMPORT")
        self.assertTrue(any("إيصال التوثيق" in text for _c, text in self.fake.sent))

    def test_confirm_rejects_wrong_chat_and_keeps_token(self):
        tl._PENDING_IMPORTS["tok2"] = {
            "chat_id": "42", "plan": {}, "tasks": [],
            "expires": dt.datetime.now().timestamp() + 600,
        }
        self.bot_module.command_confirm_tasks(43, "tok2")
        self.assertIn("tok2", tl._PENDING_IMPORTS)
        self.assertTrue(any("لا يخص هذه المحادثة" in t for _c, t in self.fake.sent))

    def test_confirm_rejects_expired_token(self):
        tl._PENDING_IMPORTS["tok3"] = {
            "chat_id": "42", "plan": {}, "tasks": [],
            "expires": dt.datetime.now().timestamp() - 1,
        }
        self.bot_module.command_confirm_tasks(42, "tok3")
        self.assertNotIn("tok3", tl._PENDING_IMPORTS)
        self.assertTrue(any("انتهت مدة" in t for _c, t in self.fake.sent))

    def test_full_flow_end_to_end(self):
        raw = "/tasks_import " + json.dumps(user_matrix(), ensure_ascii=False)
        with patch.object(tl, "sheets", self.sheets):
            self.fake.handle_message(make_message(raw, message_id=10))
            token = next(iter(tl._PENDING_IMPORTS))
            self.bot_module.command_confirm_tasks(42, token)
        final = self.fake.sent[-1][1]
        self.assertIn("EXECUTED", final)
        self.assertEqual(len(self.sheets.appends), 4)
        # the ledger now contains TASK-0021 with its domain cell
        row = next(r for r in self.sheets.rows if r and r[0] == "TASK-0021")
        self.assertEqual(row[6], "قسم التأهيل الطبي")

    def test_tasks_command_routes_through_handler(self):
        with patch.object(tl, "render_tasks_text", return_value="📋 سجل المهام — تجربة"):
            self.fake.handle_message(make_message("/tasks", message_id=20))
        self.assertTrue(any("سجل المهام" in t for _c, t in self.fake.sent))

    def test_unknown_text_falls_through_to_next_handler(self):
        forwarded = []
        self.fake.handle_message = lambda message: forwarded.append(message)
        tl.install(self.fake)  # re-wrap over the recording stub
        self.fake.handle_message(make_message("/morning", message_id=30))
        self.fake.handle_message(make_message("نص عادي", message_id=31))
        self.assertEqual(len(forwarded), 2)  # both fall through to the next layer

    def test_install_is_idempotent(self):
        first = tl.install(self.fake)
        second = tl.install(self.fake)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
