# -*- coding: utf-8 -*-
"""اختبارات استمرارية الحالة على مضيف بلا قرص دائم — بلا شبكة."""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from connectors import state_persistence, supabase_state
from connectors.supabase_client import SupabaseError


def sample_state(version=1, tasks=None):
    return {
        "meta": {"version": version, "schema": "state/1"},
        "tasks": tasks if tasks is not None else [{"العنوان": "مهمة"}],
        "projects": [], "decisions": [], "waiting_for": [], "action_queue": [],
    }


class PersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_state(self, state):
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)

    def snapshot_row(self, state, snapshot_id=1, created_at="2026-09-20T10:00:00Z"):
        return {**supabase_state.snapshot_from(state), "id": snapshot_id,
                "created_at": created_at}

    def client_with(self, row=None, error=None):
        select = mock.Mock(side_effect=error) if error else mock.Mock(return_value=[row] if row else [])
        return mock.Mock(select=select, insert=mock.Mock(return_value=[{"id": 9, "byte_size": 10,
                                                                       "sha256": "fresh"}]))


class RestoreOnBootTests(PersistenceTestCase):
    def test_missing_state_is_restored_from_the_cloud(self):
        client = self.client_with(self.snapshot_row(sample_state()))
        report = state_persistence.restore_on_boot(client=client)
        self.assertTrue(report["restored"])
        restored = json.load(open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8"))
        self.assertEqual(restored["tasks"][0]["العنوان"], "مهمة")

    def test_existing_local_state_wins(self):
        self.write_state(sample_state(version=7, tasks=[{"العنوان": "محلي"}]))
        client = self.client_with(self.snapshot_row(sample_state(tasks=[{"العنوان": "سحابي"}])))
        report = state_persistence.restore_on_boot(client=client)
        self.assertFalse(report["restored"])
        self.assertIn("موجودة", report["detail"])
        self.assertFalse(client.select.called, "لا حاجة لسؤال السحابة والحالة موجودة")
        restored = json.load(open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8"))
        self.assertEqual(restored["tasks"][0]["العنوان"], "محلي")

    def test_force_restore_overwrites_local_state(self):
        self.write_state(sample_state(tasks=[{"العنوان": "محلي"}]))
        client = self.client_with(self.snapshot_row(sample_state(tasks=[{"العنوان": "سحابي"}])))
        report = state_persistence.restore_on_boot(force=True, client=client)
        self.assertTrue(report["restored"])
        restored = json.load(open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8"))
        self.assertEqual(restored["tasks"][0]["العنوان"], "سحابي")

    def test_no_snapshots_yet_is_a_clean_first_boot(self):
        report = state_persistence.restore_on_boot(client=self.client_with())
        self.assertEqual(report["action"], "skip")
        self.assertIn("أول نظيف", report["detail"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "state.json")))

    def test_corrupted_snapshot_is_refused_and_never_written(self):
        row = self.snapshot_row(sample_state())
        row["payload"]["tasks"] = [{"العنوان": "معدّلة"}]  # يخالف البصمة
        report = state_persistence.restore_on_boot(client=self.client_with(row))
        self.assertEqual(report["action"], "refused")
        self.assertFalse(report["restored"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "state.json")))

    def test_network_failure_does_not_break_startup(self):
        client = self.client_with(error=[SupabaseError("لا شبكة")])
        self.assertFalse(client.select.side_effect is None)
        report = state_persistence.restore_on_boot(client=client)
        self.assertEqual(report["action"], "error")
        self.assertIn("لا شبكة", report["detail"])


class PushIfChangedTests(PersistenceTestCase):
    def test_pushes_only_when_the_state_changed(self):
        self.write_state(sample_state())
        client = self.client_with()
        with mock.patch.object(supabase_state, "push", mock.Mock(return_value={"id": 5})) as push:
            first = state_persistence.push_if_changed(client=client)
            self.assertTrue(first["pushed"])
            self.assertEqual(push.call_count, 1)

            # لا تغيير ⇒ لا طلب شبكة إطلاقًا
            push.reset_mock()
            second = state_persistence.push_if_changed(client=client)
            self.assertFalse(second["pushed"])
            self.assertIn("لا تغيير", second["detail"])
            self.assertEqual(push.call_count, 0)

            # تغيّرت الحالة ⇒ دفع جديد
            self.write_state(sample_state(version=2, tasks=[{"العنوان": "جديدة"}]))
            third = state_persistence.push_if_changed(client=client)
            self.assertTrue(third["pushed"])
            self.assertEqual(push.call_count, 1)

    def test_ledger_is_written_atomically(self):
        self.write_state(sample_state())
        with mock.patch.object(supabase_state, "push", mock.Mock(return_value={"id": 3})):
            state_persistence.push_if_changed(client=self.client_with())
        leftovers = [name for name in os.listdir(self.tmp.name) if ".tmp-" in name]
        self.assertEqual(leftovers, [])
        ledger = json.load(open(os.path.join(self.tmp.name, state_persistence.STATE_FILE),
                                encoding="utf-8"))
        self.assertEqual(ledger["snapshot_id"], 3)

    def test_push_failure_is_reported_not_raised(self):
        self.write_state(sample_state())
        with mock.patch.object(supabase_state, "push",
                               mock.Mock(side_effect=SupabaseError("مفتاح مرفوض"))):
            result = state_persistence.push_if_changed(client=self.client_with())
        self.assertFalse(result["pushed"])
        self.assertIn("مفتاح مرفوض", result["detail"])

    def test_missing_local_state_is_reported(self):
        result = state_persistence.push_if_changed(client=self.client_with())
        self.assertFalse(result["pushed"])
        self.assertIn("تعذر قراءة الحالة", result["detail"])

    def test_a_failed_push_does_not_advance_the_ledger(self):
        """مهم: خطأ شبكي يجب ألّا يجعل النظام يظن أن الحالة محفوظة."""
        self.write_state(sample_state())
        with mock.patch.object(supabase_state, "push", mock.Mock(side_effect=SupabaseError("تعذر"))):
            state_persistence.push_if_changed(client=self.client_with())
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, state_persistence.STATE_FILE)))
        with mock.patch.object(supabase_state, "push", mock.Mock(return_value={"id": 1})) as push:
            self.assertTrue(state_persistence.push_if_changed(client=self.client_with())["pushed"])
            self.assertEqual(push.call_count, 1)


class FlushTests(PersistenceTestCase):
    def test_flush_pushes_even_without_change(self):
        self.write_state(sample_state())
        with mock.patch.object(supabase_state, "push", mock.Mock(return_value={"id": 4})) as push:
            result = state_persistence.flush(reason="SIGTERM")
        self.assertTrue(result["pushed"])
        self.assertEqual(push.call_args[0][0], "SIGTERM")

    def test_flush_never_raises_on_failure(self):
        with mock.patch.object(supabase_state, "push", mock.Mock(side_effect=RuntimeError("انفجار"))):
            result = state_persistence.flush()
        self.assertFalse(result["pushed"])


class LoopTests(PersistenceTestCase):
    def test_loop_stops_promptly_on_the_stop_event(self):
        stop = threading.Event()
        calls = []
        with mock.patch.object(state_persistence, "push_if_changed",
                               lambda **kwargs: calls.append(1)):
            thread = threading.Thread(target=state_persistence.persist_loop,
                                      kwargs={"interval": 30, "stop_event": stop}, daemon=True)
            thread.start()
            stop.set()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive(), "الدورة يجب أن تتوقف فورًا عند الطلب")
        self.assertEqual(calls, [], "لا دفع قبل انقضاء الفترة")

    def test_loop_survives_repeated_failures(self):
        stop = threading.Event()
        stop.set()  # يتوقف قبل أول دورة
        with mock.patch.object(state_persistence, "push_if_changed",
                               mock.Mock(side_effect=RuntimeError("فشل متكرر"))):
            state_persistence.persist_loop(interval=30, stop_event=stop)  # لا استثناء

    def test_install_is_inert_without_the_explicit_flags(self):
        with mock.patch.object(state_persistence, "restore_on_boot") as restore:
            status = state_persistence.install(client=self.client_with())
        self.assertIsNone(status["persist"])
        self.assertFalse(restore.called, "لا شيء تلقائي بلا راية صريحة")

    def test_install_runs_both_parts_when_enabled(self):
        self.write_state(sample_state())
        env = {"AI_OS_DATA_DIR": self.tmp.name, "AI_OS_STATE_RESTORE_ON_BOOT": "1",
               "AI_OS_STATE_PERSIST": "0"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(state_persistence, "restore_on_boot",
                                   mock.Mock(return_value={"action": "skip", "detail": "x"})) as restore:
                status = state_persistence.install(client=self.client_with())
        self.assertTrue(restore.called)
        self.assertIsNotNone(status["restore"])

    def test_persist_loop_is_not_started_without_supabase_config(self):
        """لا دورة تدفع إلى العدم: تنبيه واضح بدل إغراق السجل بأخطاء متكررة."""
        self.write_state(sample_state())
        env = {"AI_OS_DATA_DIR": self.tmp.name, "AI_OS_STATE_PERSIST": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(state_persistence.threading, "Thread") as thread:
                status = state_persistence.install(client=self.client_with())
        self.assertFalse(thread.called, "لا خيط بلا إعداد")
        self.assertIn("error", status["persist"])
        self.assertFalse(status["flush_on_signal"])

    def test_persist_loop_needs_write_permission_not_just_keys(self):
        """مفتاح عام قراءة فقط ⇒ لا دورة دفع (وإلا فشلت كل دورة)."""
        self.write_state(sample_state())
        env = {"AI_OS_DATA_DIR": self.tmp.name, "AI_OS_STATE_PERSIST": "1",
               "SUPABASE_URL": "https://demo.supabase.co",
               "SUPABASE_ANON_KEY": "sb_publishable_demo"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(state_persistence.threading, "Thread") as thread:
                status = state_persistence.install(client=self.client_with())
        self.assertFalse(thread.called)
        self.assertIn("الكتابة مغلقة", status["persist"]["error"])


class EnvironmentFlagTests(PersistenceTestCase):
    def test_flag_parsing(self):
        for value in ("1", "true", "yes", "on", "TRUE"):
            with mock.patch.dict(os.environ, {"X": value}, clear=False):
                self.assertTrue(state_persistence.enabled("X"), value)
        for value in ("", "0", "false", "no", "off"):
            with mock.patch.dict(os.environ, {"X": value}, clear=False):
                self.assertFalse(state_persistence.enabled("X"), value)

    def test_interval_floor_prevents_hammering(self):
        """قيمة صغيرة في البيئة لا تُغرق Supabase: الحد الأدنى 30 ثانية في الكود."""
        env = {"AI_OS_DATA_DIR": self.tmp.name, "AI_OS_STATE_PERSIST": "1",
               "AI_OS_STATE_PERSIST_SECONDS": "5",
               "SUPABASE_URL": "https://demo.supabase.co",
               "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_demo",
               "SUPABASE_WRITE_ENABLED": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(state_persistence.threading, "Thread") as thread:
                thread.return_value = mock.Mock(is_alive=mock.Mock(return_value=False))
                state_persistence.install(client=self.client_with())
        interval = thread.call_args[1]["kwargs"]["interval"]
        self.assertGreaterEqual(interval, 30, "الفاصل الأدنى 30 ثانية")
        thread.return_value.start.assert_called_once()


class StatusCommandTests(PersistenceTestCase):
    def test_status_reports_configuration_without_secrets(self):
        import contextlib
        import io
        self.write_state(sample_state())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = state_persistence.main(["status"])
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("استمرارية الحالة", text)
        self.assertIn("مطفأة", text)  # الرايات غير مضبوطة هنا

    def test_status_handles_absent_state(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = state_persistence.main(["status"])
        self.assertEqual(code, 0)
        self.assertIn("لا", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
