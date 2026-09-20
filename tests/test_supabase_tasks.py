# -*- coding: utf-8 -*-
"""اختبارات مرآة المهام + الجدولة اليومية + ملفات SQL — بلا شبكة."""
import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

from connectors import supabase_client, supabase_state, supabase_tasks

TODAY = dt.date(2026, 9, 20)


def state_with(tasks, version=5):
    return {
        "meta": {"version": version, "schema": "state/1"},
        "tasks": tasks, "projects": [], "decisions": [], "waiting_for": [], "action_queue": [],
    }


def real_task(**overrides):
    """صف مهمة بنفس أسماء الحقول التي يكتبها import_inbox.py فعلًا."""
    row = {
        "العنوان": "مراجعة خطة الوحدة", "النوع": "قسم", "الأولوية": "عالية",
        "الموعد النهائي": "2026-09-25", "الحالة": "لم تبدأ",
        "السياق/المشروع": "مشروع التطوير", "المصدر": "صندوق الصوت", "ملاحظات": "بند إضافي",
    }
    row.update(overrides)
    return row


class MappingTests(unittest.TestCase):
    def test_reads_real_arabic_field_names(self):
        rows = supabase_tasks.task_rows(state_with([real_task()]), today=TODAY)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["title"], "مراجعة خطة الوحدة")
        self.assertEqual(row["priority"], "عالية")
        self.assertEqual(row["project"], "مشروع التطوير")
        self.assertEqual(row["source"], "صندوق الصوت")
        self.assertEqual(row["notes"], "بند إضافي")
        self.assertEqual(row["due_date"], "2026-09-25")
        self.assertEqual(row["state_version"], 5)
        self.assertTrue(row["is_open"])
        self.assertFalse(row["is_overdue"])

    def test_tolerates_english_keys_and_alternate_names(self):
        rows = supabase_tasks.task_rows(state_with([
            {"title": "Task A", "priority": "عالية", "status": "in_progress", "due_date": "2026-09-19"},
        ]), today=TODAY)
        self.assertEqual(rows[0]["title"], "Task A")
        self.assertEqual(rows[0]["status_norm"], "in_progress")
        self.assertTrue(rows[0]["is_overdue"])

    def test_skips_rows_without_a_title(self):
        rows = supabase_tasks.task_rows(state_with([
            {"الأولوية": "عالية"}, "ليس قاموسًا", real_task(),
        ]), today=TODAY)
        self.assertEqual(len(rows), 1)

    def test_status_normalization_covers_the_real_vocabulary(self):
        cases = {"لم تبدأ": "not_started", "قيد التنفيذ": "in_progress", "منجزة": "done",
                 "مكتملة": "done", "معلقة": "paused", "ملغاة": "cancelled", "": "not_started",
                 "شيء غريب": "unknown"}
        for raw, expected in cases.items():
            self.assertEqual(supabase_tasks.normalize_status(raw), expected, raw)

    def test_closed_tasks_are_not_open_or_overdue(self):
        rows = supabase_tasks.task_rows(state_with([
            real_task(**{"الحالة": "منجزة", "الموعد النهائي": "2020-01-01"}),
            real_task(**{"الحالة": "ملغاة", "الموعد النهائي": "2020-01-01", "العنوان": "ملغاة"}),
        ]), today=TODAY)
        for row in rows:
            self.assertFalse(row["is_open"])
            self.assertFalse(row["is_overdue"])

    def test_bad_or_missing_due_date_becomes_none_not_a_guess(self):
        rows = supabase_tasks.task_rows(state_with([
            real_task(**{"الموعد النهائي": "قريبًا", "العنوان": "أ"}),
            real_task(**{"الموعد النهائي": "", "العنوان": "ب"}),
            real_task(**{"الموعد النهائي": dt.date(2026, 10, 1), "العنوان": "ج"}),
        ]), today=TODAY)
        by_title = {row["title"]: row for row in rows}
        self.assertIsNone(by_title["أ"]["due_date"])
        self.assertIsNone(by_title["ب"]["due_date"])
        self.assertEqual(by_title["ج"]["due_date"], "2026-10-01")

    def test_ids_are_deterministic_and_unique_per_identity(self):
        first = supabase_tasks.task_rows(state_with([real_task()]), today=TODAY)[0]["id"]
        again = supabase_tasks.task_rows(state_with([real_task()]), today=TODAY)[0]["id"]
        self.assertEqual(first, again, "نفس المهمة يجب أن تعطي نفس المعرّف (idempotent)")

        # نفس العنوان والموعد لكن مصدر مختلف ⇒ مهمة مختلفة
        other = supabase_tasks.task_rows(state_with([
            real_task(**{"المصدر": "بريد"})]), today=TODAY)[0]["id"]
        self.assertNotEqual(first, other)

    def test_duplicate_titles_get_distinct_ids(self):
        rows = supabase_tasks.task_rows(state_with([real_task(), real_task()]), today=TODAY)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["id"], rows[1]["id"], "التكرارات لا تتشارك معرّفًا")

    def test_identity_is_stable_while_status_changes(self):
        """إغلاق مهمة يجب أن يحدّث صفّها لا أن ينشئ صفًا آخر."""
        before = supabase_tasks.task_rows(state_with([real_task()]), today=TODAY)[0]
        after = supabase_tasks.task_rows(
            state_with([real_task(**{"الحالة": "منجزة"})]), today=TODAY)[0]
        self.assertEqual(before["id"], after["id"])
        self.assertNotEqual(before["is_open"], after["is_open"])


class StatsTests(unittest.TestCase):
    def test_stats_counts_open_overdue_and_today(self):
        data = supabase_tasks.stats(state_with([
            real_task(**{"العنوان": "متأخرة", "الموعد النهائي": "2026-09-15"}),
            real_task(**{"العنوان": "اليوم", "الموعد النهائي": "2026-09-20"}),
            real_task(**{"العنوان": "منجزة", "الحالة": "منجزة", "الموعد النهائي": "2026-09-15"}),
            real_task(**{"العنوان": "بلا موعد", "الموعد النهائي": ""}),
        ]), today=TODAY)
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["open"], 3)
        self.assertEqual(data["overdue"], 1)
        self.assertEqual(data["due_today"], 1)
        self.assertEqual(data["no_due_date"], 1)
        self.assertEqual(data["by_status"]["done"], 1)

    def test_stats_and_render_work_without_supabase(self):
        state = state_with([
            real_task(**{"العنوان": "متأخرة منذ أمس", "الموعد النهائي": "2026-09-19"}),
            real_task(**{"العنوان": "تستحق اليوم", "الموعد النهائي": "2026-09-20"}),
        ])
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(supabase_tasks, "read_state", lambda path=None: state):
                data = supabase_tasks.stats(today=TODAY)
        text = supabase_tasks.render_stats(data)
        self.assertIn("المهام", text)
        self.assertIn("متأخرة منذ أمس", text)
        self.assertIn("تستحق اليوم", text)
        self.assertIn("متأخرة: 1", text)

    def test_stats_handles_an_empty_state(self):
        data = supabase_tasks.stats(state_with([]), today=TODAY)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["overdue"], 0)


class SyncTests(unittest.TestCase):
    class Client:
        def __init__(self):
            self.upserts = []
            self.deletes = []

        def upsert(self, table, rows, on_conflict=""):
            self.upserts.append((table, rows, on_conflict))
            return rows

        def delete(self, table, match, returning=True):
            self.deletes.append((table, match))
            return [{"id": "stale-1"}, {"id": "stale-2"}]

    def test_sync_upserts_by_id_and_removes_stale_rows(self):
        client = self.Client()
        summary = supabase_tasks.sync(client=client, state=state_with([real_task()]), owner="owner")
        table, rows, conflict = client.upserts[0]
        self.assertEqual(table, "tasks_mirror")
        self.assertEqual(conflict, "id")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["sync_run"] == summary["run"])
        # كل الصفوف تحمل بصمة هذه الدورة ⇒ الحذف يستهدف ما عداها فقط
        self.assertEqual(client.deletes[0][1], {"sync_run": f"neq.{summary['run']}"})
        self.assertEqual(summary["stale_removed"], 2)

    def test_dry_run_writes_nothing(self):
        client = self.Client()
        summary = supabase_tasks.sync(client=client, state=state_with([real_task()]), dry_run=True)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(client.upserts, [])
        self.assertEqual(client.deletes, [])

    def test_empty_state_clears_the_mirror_without_upserting(self):
        client = self.Client()
        summary = supabase_tasks.sync(client=client, state=state_with([]))
        self.assertEqual(client.upserts, [])
        self.assertEqual(len(client.deletes), 1)
        self.assertIn("تُفرَّغ المرآة", summary["note"])

    def test_owner_comes_from_the_telegram_owner_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
            with open(os.path.join(tmp, "data", ".telegram-owner"), "w", encoding="utf-8") as handle:
                handle.write("123456789\n")
            with mock.patch.object(supabase_tasks, "BASE", tmp), \
                    mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(supabase_tasks.owner_id(), "123456789")
        with mock.patch.object(supabase_tasks, "BASE", "/nonexistent"), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(supabase_tasks.owner_id(), "owner")

    def test_explicit_owner_env_wins(self):
        with mock.patch.dict(os.environ, {"SUPABASE_TASKS_OWNER": "boss"}, clear=False):
            self.assertEqual(supabase_tasks.owner_id(), "boss")


class MissingStateSafetyTests(unittest.TestCase):
    """التمييز الأهم في الموصل: «لا مهام» ≠ «لا أستطيع قراءة الحالة»."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sync_refuses_when_state_is_missing_instead_of_wiping_the_mirror(self):
        client = SyncTests.Client()
        with self.assertRaises(supabase_tasks.StateUnavailable):
            supabase_tasks.sync(client=client)
        # لم يُرسل ولم يُحذف شيء: المرآة سليمة كما كانت
        self.assertEqual(client.upserts, [])
        self.assertEqual(client.deletes, [])

    def test_sync_refuses_on_a_corrupted_state_file(self):
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            handle.write('{"meta": {"version": 1}, "tasks": [')  # JSON مقطوع
        client = SyncTests.Client()
        with self.assertRaises(supabase_tasks.StateUnavailable):
            supabase_tasks.sync(client=client)
        self.assertEqual(client.deletes, [])

    def test_stats_degrades_gracefully_without_state(self):
        data = supabase_tasks.stats()
        self.assertFalse(data["available"])
        self.assertEqual(data["total"], 0)
        text = supabase_tasks.render_stats(data)
        self.assertIn("غير متاحة", text)
        self.assertNotIn("Traceback", text)

    def test_genuinely_empty_state_still_clears_the_mirror(self):
        """حالة سليمة بلا مهام = واقع مشروع ⇒ يُسمح بالتفريغ."""
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(state_with([]), handle, ensure_ascii=False)
        client = SyncTests.Client()
        summary = supabase_tasks.sync(client=client)
        self.assertEqual(summary["rows"], 0)
        self.assertEqual(len(client.deletes), 1)

    def test_run_daily_reports_state_problems_without_raising(self):
        outcome = supabase_tasks.run_daily()
        self.assertTrue(any(error.startswith("state:") for error in outcome["errors"]),
                        outcome["errors"])
        # لا نسخة ولا مزامنة عند تعذّر الحالة — ولا مساس بالمرآة
        self.assertIsNone(outcome["snapshot"])
        self.assertIsNone(outcome["mirror"])


class DailyScheduleTests(unittest.TestCase):
    """جدولة الدفعة اليومية — بوابتان معًا: المرحلة (rollout) + الراية (env)."""

    BASE_ENV = {"SUPABASE_URL": "https://demo.supabase.co", "SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}

    @property
    def env(self):
        """BASE_ENV + مجلد البيانات المؤقت — أي patch بـclear=True يجب أن يحتفظ
        بـAI_OS_DATA_DIR وإلا قُرئ ملف المرحلة من مكان آخر (نظام الاختبار كله يختل)."""
        return {**self.BASE_ENV, "AI_OS_DATA_DIR": os.environ["AI_OS_DATA_DIR"]}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": tmp.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        from engine import rollout
        self.rollout = rollout
        self.addCleanup(lambda: rollout.kill(reason="تنظيف"))

    def _at_dual(self):
        """يرفع المرحلة إلى dual عبر مسار الترقية الطبيعي (لا قفز)."""
        self.rollout.set_phase("shadow")
        self.rollout.set_phase("canary")
        self.rollout.set_phase("dual")

    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://demo.supabase.co"}, clear=True):
            self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

    def test_needs_a_configured_project(self):
        env = {"SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

    def test_below_dual_the_schedule_stays_off_even_with_the_flag(self):
        """المرحلة وحدها أو الراية وحدها لا تكفيان — لا أتمتة قبل dual."""
        for phase in ("dormant", "shadow", "canary"):
            self.rollout.kill(reason="فحص")
            while self.rollout.current_phase() != phase:
                self.rollout.advance(force=True)
            with mock.patch.dict(os.environ, self.env, clear=True):
                self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}), phase)

    def test_runs_once_per_day_after_the_configured_hour(self):
        self._at_dual()
        with mock.patch.dict(os.environ, self.env, clear=True):
            too_early = dt.datetime(2026, 9, 20, 5, 0)
            self.assertFalse(supabase_tasks.daily_due(too_early, {}, hour=6))
            ready = dt.datetime(2026, 9, 20, 6, 30)
            self.assertTrue(supabase_tasks.daily_due(ready, {}, hour=6))
            self.assertFalse(supabase_tasks.daily_due(ready, {"supabase_backup_day": "2026-09-20"}, hour=6))
            self.assertTrue(supabase_tasks.daily_due(ready, {"supabase_backup_day": "2026-09-19"}, hour=6))

    def test_rollback_stops_the_schedule_immediately(self):
        self._at_dual()
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertTrue(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))
            self.rollout.kill(reason="تراجع فوري")
            self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

    def test_run_daily_reports_errors_without_raising(self):
        from connectors.supabase_client import SupabaseError
        with mock.patch.object(supabase_state, "push",
                               mock.Mock(side_effect=SupabaseError("لا شبكة"))):
            with mock.patch.object(supabase_tasks, "sync", lambda **kwargs: {"rows": 3}):
                outcome = supabase_tasks.run_daily(state=state_with([real_task()]))
        self.assertEqual(outcome["mirror"], {"rows": 3})
        self.assertEqual(len(outcome["errors"]), 1)
        self.assertIn("snapshot", outcome["errors"][0])


class SqlFileTests(unittest.TestCase):
    def test_files_exist_and_enforce_the_safety_rules(self):
        available = supabase_client.sql_files()
        self.assertIn("01_state_snapshots.sql", available)
        self.assertIn("02_tasks_mirror.sql", available)

        tasks_sql = supabase_client.read_sql("02_tasks_mirror.sql").lower()
        self.assertIn("create table if not exists public.tasks_mirror", tasks_sql)
        self.assertIn("enable row level security", tasks_sql)
        self.assertIn("revoke all", tasks_sql)
        # لا سياسات متساهلة: الشرط الأساسي الذي يمنع كشف المهام للمفتاح العام
        self.assertNotIn("create policy", tasks_sql.split("-- 6)")[0].replace("--   create policy", ""))
        self.assertIn("tasks_dashboard", tasks_sql)
        self.assertIn("security_invoker", tasks_sql)

        snapshots_sql = supabase_client.SETUP_SQL.lower()
        self.assertIn("state_snapshots", snapshots_sql)
        self.assertIn("enable row level security", snapshots_sql)

    def test_sql_cli_prints_the_requested_files(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(supabase_client.main(["--sql", "tasks"]), 0)
        self.assertIn("tasks_mirror", buffer.getvalue())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(supabase_client.main(["--sql", "all"]), 0)
        out = buffer.getvalue()
        self.assertIn("state_snapshots", out)
        self.assertIn("tasks_mirror", out)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(supabase_client.main(["--sql", "nonsense"]), 2)

    def test_missing_file_is_reported_not_crashed(self):
        with mock.patch.object(supabase_client, "SQL_DIR", "/nonexistent"):
            self.assertEqual(supabase_client.read_sql("02_tasks_mirror.sql"), "")
            import contextlib
            import io
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(supabase_client.main(["--sql"]), 2)


class PullTests(unittest.TestCase):
    """pull يقفل الدائرة: تنزيل نسخة محلية موقّعة من السحابة."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = state_with([real_task()])
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False)

    def _client(self, payload):
        """نسخة «سحابية»: البصمة تعود للحالة الأصلية، والحمولة قد تكون مبدَّلة."""
        snapshot = supabase_state.build_snapshot()          # بصمة الحالة السليمة
        snapshot["payload"] = payload                        # قد تكون حمولة معدّلة
        return mock.Mock(select=mock.Mock(return_value=[{**snapshot, "id": 4,
                                                          "created_at": "2026-09-20T10:00:00Z"}]))

    def test_pull_writes_a_verified_local_file(self):
        target = os.path.join(self.tmp.name, "pulled")
        report = supabase_state.pull(4, client=self._client(self.state), target_dir=target)
        self.assertTrue(report["ok"], report["problems"])
        path = report["written"]
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.startswith(target))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["tasks"][0]["العنوان"], "مراجعة خطة الوحدة")

    def test_pull_refuses_a_corrupted_snapshot(self):
        tampered = json.loads(json.dumps(self.state))
        tampered["tasks"] = []
        report = supabase_state.pull(4, client=self._client(tampered),
                                     target_dir=os.path.join(self.tmp.name, "pulled"))
        self.assertFalse(report["ok"])
        self.assertIsNone(report["written"])

    def test_pull_defaults_to_the_backups_folder(self):
        report = supabase_state.pull(4, client=self._client(self.state))
        self.assertEqual(os.path.dirname(report["written"]),
                         os.path.join(self.tmp.name, "backups"))


if __name__ == "__main__":
    unittest.main()
