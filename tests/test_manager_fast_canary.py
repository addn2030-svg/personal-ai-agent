import os
import unittest
from unittest.mock import Mock, patch

from connectors import manager_fast_canary as canary


class ManagerFastCanaryTests(unittest.TestCase):
    def test_default_is_off_and_does_not_start_thread(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(canary.threading, "Thread") as thread:
            worker = canary.start_if_enabled()
        self.assertIsNone(worker)
        thread.assert_not_called()

    def test_enabled_starts_one_daemon_thread(self):
        fake_thread = Mock()
        with patch.dict(os.environ, {canary.ENABLED_ENV: "1"}, clear=True), patch.object(
            canary.threading, "Thread", return_value=fake_thread
        ) as thread:
            worker = canary.start_if_enabled()
        self.assertIs(worker, fake_thread)
        fake_thread.start.assert_called_once_with()
        kwargs = thread.call_args.kwargs
        self.assertEqual(kwargs["name"], "manager-fast-canary")
        self.assertTrue(kwargs["daemon"])
        self.assertIs(kwargs["target"], canary._worker)

    def test_cycle_once_calls_fast_only_and_persists_heartbeat(self):
        with patch.object(canary.manager, "fast_cycle", return_value={"overdue": 0}) as fast, patch.object(
            canary.manager, "full_cycle"
        ) as full, patch.object(
            canary.manager, "_update_markers"
        ) as markers, patch.object(
            canary.manager, "log_event"
        ) as log_event, patch.object(
            canary.manager, "now"
        ) as now:
            now.return_value.isoformat.return_value = "2026-08-30T20:00:00+03:00"
            result = canary.cycle_once()

        self.assertEqual(result, {"overdue": 0})
        fast.assert_called_once_with()
        full.assert_not_called()
        markers.assert_called_once_with(last_fast_canary="2026-08-30T20:00:00+03:00")
        log_event.assert_called_once()

    def test_worker_can_stop_after_single_fast_cycle(self):
        stop_event = Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = True
        with patch.object(canary, "cycle_once", return_value={}) as cycle, patch.object(
            canary.manager, "log_event"
        ):
            canary._worker(stop_event=stop_event, sleep_seconds=0.01)
        cycle.assert_called_once_with()

    def test_invalid_interval_falls_back_and_minimum_is_enforced(self):
        with patch.dict(os.environ, {canary.INTERVAL_ENV: "bad"}, clear=True):
            self.assertEqual(canary.interval_seconds(), canary.DEFAULT_INTERVAL_SECONDS)
        with patch.dict(os.environ, {canary.INTERVAL_ENV: "1"}, clear=True):
            self.assertEqual(canary.interval_seconds(), 60)


if __name__ == "__main__":
    unittest.main()
