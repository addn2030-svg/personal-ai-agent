import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import proactive_worker as worker


class ProactiveWorkerTests(unittest.TestCase):
    def test_enabled_by_default_and_respects_kill_switches(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(worker.proactive, "enabled", return_value=True):
            self.assertTrue(worker.enabled())
        with patch.dict(os.environ, {worker.ENABLED_ENV: "0"}, clear=True):
            self.assertFalse(worker.enabled())
        with patch.dict(os.environ, {worker.ENABLED_ENV: "1"}, clear=True), patch.object(
            worker.proactive, "enabled", return_value=False
        ):
            self.assertFalse(worker.enabled())

    def test_interval_is_bounded(self):
        with patch.dict(os.environ, {worker.INTERVAL_ENV: "2"}, clear=True):
            self.assertEqual(worker.interval_seconds(), 60)
        with patch.dict(os.environ, {worker.INTERVAL_ENV: "invalid"}, clear=True):
            self.assertEqual(worker.interval_seconds(), worker.DEFAULT_INTERVAL_SECONDS)

    def test_scheduler_dispatch_enabled_default_on_and_kill_switch(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(worker.scheduler_dispatch_enabled())
        with patch.dict(os.environ, {worker.DISPATCH_SCHED_ENV: "0"}, clear=True):
            self.assertFalse(worker.scheduler_dispatch_enabled())
        with patch.dict(os.environ, {worker.DISPATCH_SCHED_ENV: "1"}, clear=True):
            self.assertTrue(worker.scheduler_dispatch_enabled())

    def test_cycle_once_runs_scheduler_then_sweep_and_records_heartbeat(self):
        summary = {"alerts": 1}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(worker.scheduler, "dispatch_due", return_value=(1, 0)) as dispatch, \
             patch.object(worker.proactive, "sweep", return_value=summary) as sweep, \
             patch.object(worker.manager, "now") as now, \
             patch.object(worker.manager, "_update_markers") as markers, \
             patch.object(worker.manager, "log_event") as log:
            now.return_value.isoformat.return_value = "2026-09-11T20:00:00+03:00"
            out = worker.cycle_once()
            dispatch.assert_called_once_with(verbose=False)
            sweep.assert_called_once_with(verbose=False)
            markers.assert_called_once_with(last_proactive_worker="2026-09-11T20:00:00+03:00")
            self.assertEqual(log.call_count, 1)
            self.assertEqual(out["alerts"], 1)
            self.assertEqual(out["scheduler"], {"executed": 1, "skipped": 0, "error": None})

    def test_cycle_once_scheduler_kill_switch_skipped_when_disabled(self):
        summary = {"alerts": 0}
        with patch.dict(os.environ, {worker.DISPATCH_SCHED_ENV: "0"}, clear=True), \
             patch.object(worker.scheduler, "dispatch_due") as dispatch, \
             patch.object(worker.proactive, "sweep", return_value=summary) as sweep:
            out = worker.cycle_once()
            dispatch.assert_not_called()
            sweep.assert_called_once_with(verbose=False)
            self.assertTrue(out["scheduler"].get("disabled"))
            self.assertEqual(out["scheduler"]["executed"], 0)

    def test_cycle_once_scheduler_error_does_not_kill_sweep(self):
        summary = {"alerts": 0}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(worker.scheduler, "dispatch_due",
                          side_effect=RuntimeError("db locked")) as dispatch, \
             patch.object(worker.proactive, "sweep", return_value=summary) as sweep, \
             patch.object(worker.manager, "log_event") as log, \
             patch.object(worker.manager, "_update_markers"):
            out = worker.cycle_once()
            dispatch.assert_called_once()
            sweep.assert_called_once()  # sweep still ran despite scheduler boom
            self.assertIn("db locked", out["scheduler"]["error"])
            # An error event was logged for the scheduler failure.
            err_events = [c for c in log.call_args_list
                          if c.args and c.args[0] == "proactive_worker_scheduler_error"]
            self.assertEqual(len(err_events), 1)

    def test_cycle_once_sweep_error_does_not_prevent_heartbeat(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(worker.scheduler, "dispatch_due", return_value=(0, 0)), \
             patch.object(worker.proactive, "sweep",
                          side_effect=RuntimeError("proactive boom")) as sweep, \
             patch.object(worker.manager, "log_event") as log, \
             patch.object(worker.manager, "_update_markers") as markers, \
             patch.object(worker.manager, "now") as now:
            now.return_value.isoformat.return_value = "2026-09-11T07:05:00+03:00"
            out = worker.cycle_once()
            sweep.assert_called_once()
            markers.assert_called_once()  # heartbeat still recorded
            self.assertIn("proactive boom", out.get("sweep_error", ""))
            err_events = [c for c in log.call_args_list
                          if c.args and c.args[0] == "proactive_worker_sweep_error"]
            self.assertEqual(len(err_events), 1)

    def test_dispatch_fires_morning_brief_and_is_idempotent_on_fresh_store(self):
        """End-to-end on a temporary store: at 07:05 the morning brief enqueues
        a draft tagged scheduler:daily.morning_brief_0645 exactly once across
        two cycles (guards against duplicate re-delivery)."""
        import datetime as dt
        from zoneinfo import ZoneInfo
        from engine import scheduler
        from engine.store import Store
        TZ = ZoneInfo("Asia/Riyadh")
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(path=str(Path(tmp) / "state.json"))
            ref = dt.datetime(2026, 9, 12, 7, 5, tzinfo=TZ)  # after 06:45
            executed, skipped = scheduler.dispatch_due(ref=ref, store=store, verbose=False)
            self.assertGreaterEqual(executed, 1)
            queue = store.rows_all().get("action_queue", [])
            morning = [a for a in queue
                       if a.get("origin") == "scheduler:daily.morning_brief_0645"]
            self.assertEqual(len(morning), 1)
            self.assertEqual(morning[0]["status"], "PENDING_APPROVAL")
            self.assertEqual(morning[0]["type"], "telegram_brief_board")
            # Second tick 15 minutes later must NOT produce a duplicate.
            ref2 = dt.datetime(2026, 9, 12, 7, 20, tzinfo=TZ)
            executed2, _ = scheduler.dispatch_due(ref=ref2, store=store, verbose=False)
            self.assertEqual(executed2, 0)
            queue2 = store.rows_all().get("action_queue", [])
            morning2 = [a for a in queue2
                        if a.get("origin") == "scheduler:daily.morning_brief_0645"]
            self.assertEqual(len(morning2), 1)

    def test_startup_diagnostic_emits_warning_when_volume_missing_on_deploy(self):
        persistence = {
            "persistence": {
                "warning": "AI_OS_DATA_DIR غير مثبّت على Volume دائم",
                "volume_mounted": False,
                "deploy_platform": True,
            }
        }
        with patch.object(worker.proactive, "persistence_status", return_value=persistence), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(worker.manager, "log_event") as log:
            parts = worker._log_startup_diagnostic()
            joined = " | ".join(parts)
            self.assertIn("scheduler_dispatch=on", joined)
            self.assertIn("غير مثبّت", joined)
            warn_events = [c for c in log.call_args_list
                           if c.args and c.args[0] == "proactive_worker_persistence_warning"]
            self.assertEqual(len(warn_events), 1)

    def test_startup_diagnostic_stays_quiet_in_local_dev(self):
        persistence = {"persistence": {"warning": None, "volume_mounted": False,
                                       "deploy_platform": False}}
        with patch.object(worker.proactive, "persistence_status", return_value=persistence), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(worker.manager, "log_event") as log:
            parts = worker._log_startup_diagnostic()
            joined = " | ".join(parts)
            self.assertNotIn("⚠", joined)
            warn_events = [c for c in log.call_args_list
                           if c.args and c.args[0] == "proactive_worker_persistence_warning"]
            self.assertEqual(len(warn_events), 0)

    def test_worker_stops_without_running(self):
        stop = threading.Event()
        stop.set()
        with patch.object(worker, "cycle_once") as cycle:
            worker._worker(stop_event=stop, sleep_seconds=0.01)
            cycle.assert_not_called()

    def test_start_is_guarded(self):
        with patch.object(worker, "enabled", return_value=False), patch("threading.Thread") as thread:
            self.assertIsNone(worker.start_if_enabled())
            thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
