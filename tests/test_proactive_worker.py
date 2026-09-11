import os
import threading
import unittest
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

    def test_cycle_records_heartbeat_after_sweep(self):
        summary = {"alerts": 1}
        with patch.object(worker.proactive, "sweep", return_value=summary) as sweep, patch.object(
            worker.manager, "now"
        ) as now, patch.object(worker.manager, "_update_markers") as markers, patch.object(
            worker.manager, "log_event"
        ) as log:
            now.return_value.isoformat.return_value = "2026-09-11T20:00:00+03:00"
            self.assertEqual(worker.cycle_once(), summary)
            sweep.assert_called_once_with(verbose=False)
            markers.assert_called_once_with(last_proactive_worker="2026-09-11T20:00:00+03:00")
            log.assert_called_once()

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
