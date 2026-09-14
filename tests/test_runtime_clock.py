# -*- coding: utf-8 -*-
"""The agent must know what day it is — and prove it is alive on demand.

Covering two production failures:
1. the model answered date questions from training data because no prompt ever
   carried the server clock;
2. "the agent is not responding" was undiagnosable because every command routes
   through the model or Google, so a broken provider looks identical to a dead
   process.
"""
import datetime as dt
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

from engine import runtime_clock as clock  # noqa: E402


class RuntimeClockTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(clock)

    def test_default_timezone_is_riyadh(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(clock.tz_name(), "Asia/Riyadh")
        with patch.dict(os.environ, {clock.TZ_ENV: "UTC"}, clear=False):
            self.assertEqual(clock.tz_name(), "UTC")

    def test_now_uses_configured_timezone(self):
        with patch.dict(os.environ, {clock.TZ_ENV: "UTC"}, clear=False):
            self.assertEqual(clock.now().utcoffset(), dt.timedelta(0))

    def test_missing_tzdata_falls_back_to_riyadh_offset(self):
        """A slim container without tzdata must never crash the entrypoint."""
        with patch.dict(os.environ, {clock.TZ_ENV: "Asia/Riyadh"}, clear=False):
            with patch("zoneinfo.ZoneInfo", side_effect=Exception("no tz database")):
                moment = clock.now()
        self.assertEqual(moment.utcoffset(), dt.timedelta(hours=3))
        self.assertIn("Asia/Riyadh", clock.runtime_time_context(moment))

    def test_context_block_states_today_from_the_server(self):
        moment = dt.datetime(2026, 9, 14, 7, 35, tzinfo=dt.timezone(dt.timedelta(hours=3)))
        block = clock.runtime_time_context(moment)
        self.assertIn("RUNTIME CLOCK", block)
        self.assertIn("2026-09-14", block)
        self.assertIn("07:35", block)
        self.assertIn("Monday", block)
        self.assertIn("الإثنين", block)
        self.assertIn("UTC+03:00", block)
        self.assertIn("2026-09-14T07:35:00+03:00", block)
        # The block must instruct the model not to fall back on training data.
        self.assertIn("training data", block.lower())

    def test_context_survives_truncation_position(self):
        """Clock goes first in build_context, so it is never trimmed away."""
        from engine import agent_runtime

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"AI_OS_DATA_DIR": tmp}, clear=False):
                context, _sources = agent_runtime.build_context(1, "ما اليوم؟")
        self.assertTrue(context.startswith("RUNTIME CLOCK"))
        self.assertIn(dt.datetime.now(clock.tz()).strftime("%Y-%m-%d"), context)

    def test_status_text_is_arabic_and_instant(self):
        moment = dt.datetime(2026, 9, 14, 7, 35, tzinfo=dt.timezone(dt.timedelta(hours=3)))
        text = clock.status_text(moment)
        self.assertIn("2026-09-14", text)
        self.assertIn("الإثنين", text)
        self.assertIn("07:35", text)


class TimeCommandTests(unittest.TestCase):
    """`/time` must answer without the model, Google, or any outbound call."""

    def _reply(self, **env):
        from connectors import telegram_bot_legacy as legacy

        with patch.dict(os.environ, env, clear=False), \
             patch.object(legacy, "send") as send, \
             patch.object(legacy, "api", side_effect=AssertionError("no network in /time")):
            legacy.command_time(123)
        self.assertEqual(send.call_count, 1)
        return send.call_args[0][1]

    def test_reports_server_time_and_never_calls_the_model(self):
        reply = self._reply()
        self.assertIn(dt.datetime.now(clock.tz()).strftime("%Y-%m-%d"), reply)
        self.assertIn("المنطقة الزمنية", reply)
        self.assertIn("مدة تشغيل العملية", reply)

    def test_reports_missing_proactive_heartbeat_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            reply = self._reply(AI_OS_DATA_DIR=tmp)
        self.assertIn("آخر دورة استباقية", reply)

    def test_command_is_registered_for_telegram(self):
        from connectors import telegram_bot_legacy as legacy

        self.assertIn("/time", _registered_commands(legacy))


def _registered_commands(legacy):
    """Read the command table the way the production menu does."""
    source = Path(legacy.__file__).read_text(encoding="utf-8")
    commands = set()
    for chunk in source.split('{"command":"')[1:]:
        commands.add("/" + chunk.split('"')[0])
    return commands


if __name__ == "__main__":
    unittest.main()
