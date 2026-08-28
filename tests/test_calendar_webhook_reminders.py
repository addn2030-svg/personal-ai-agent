import threading
import time
import unittest
from unittest.mock import patch

from connectors import telegram_webhook as webhook


class CalendarWebhookReminderTests(unittest.TestCase):
    def test_worker_checks_calendar_alerts_until_stop(self):
        stop = threading.Event()
        calls = []

        def fake_check():
            calls.append(time.time())
            stop.set()

        with patch.object(webhook.bot, "_maybe_send_calendar_alerts", side_effect=fake_check):
            webhook._calendar_alert_worker(stop_event=stop, sleep_seconds=0.01)

        self.assertEqual(len(calls), 1)

    def test_worker_survives_transient_errors(self):
        stop = threading.Event()
        calls = {"n": 0}

        def flaky_check():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("temporary calendar failure")
            stop.set()

        with patch.object(webhook.bot, "_maybe_send_calendar_alerts", side_effect=flaky_check):
            webhook._calendar_alert_worker(stop_event=stop, sleep_seconds=0.01)

        self.assertGreaterEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
