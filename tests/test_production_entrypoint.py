# -*- coding: utf-8 -*-
"""The container entrypoint must import under every invocation form.

Production crash-looped with::

    File "/app/connectors/telegram_webhook_runtime_memory.py", line 12
    ModuleNotFoundError: No module named 'connectors'

Cause: ``python3 connectors/telegram_webhook_runtime_memory.py`` puts
``/app/connectors`` on ``sys.path`` (the script's own directory) instead of
``/app``, so ``from connectors import project_memory`` failed before any
bootstrap could run. These tests execute the real entrypoint as a subprocess in
both forms so the bug cannot come back silently.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = "connectors.telegram_webhook_runtime_memory"
MODULE_FILE = ROOT / "connectors" / "telegram_webhook_runtime_memory.py"

# Reaching this error proves every import succeeded and startup ran to the point
# of configuring Telegram — i.e. the crash-loop class of bug is absent.
STARTUP_REACHED = "TELEGRAM_BOT_TOKEN is not set"
IMPORT_FAILURE = "No module named 'connectors'"


def _run(command, *, cwd=ROOT, data_dir=None):
    env = {**os.environ, "TELEGRAM_BOT_TOKEN": "", "PYTHONUNBUFFERED": "1"}
    if data_dir:
        env["AI_OS_DATA_DIR"] = data_dir
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


class ProductionEntrypointTests(unittest.TestCase):
    def test_module_invocation_imports(self):
        """The form the Dockerfile CMD now uses."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", "-m", ENTRYPOINT], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.stderr)
        self.assertIn(STARTUP_REACHED, proc.stderr)

    def test_script_invocation_imports(self):
        """The form that crash-looped: running the file directly as a script."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(MODULE_FILE)], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.stderr)
        self.assertIn(STARTUP_REACHED, proc.stderr)

    def test_script_invocation_from_another_working_directory(self):
        """sys.path bootstrap must come from __file__, not from the cwd."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(MODULE_FILE)], cwd=tmp, data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.stderr)
        self.assertIn(STARTUP_REACHED, proc.stderr)

    def test_canonical_runtime_still_imports_as_a_script(self):
        """Guard the sibling entrypoint against the same regression."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(ROOT / "connectors" / "telegram_webhook_runtime.py")], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.stderr)
        self.assertIn(STARTUP_REACHED, proc.stderr)

    def test_background_system_exit_is_reported_instead_of_killing_update(self):
        """CLI-oriented helpers must not silently terminate a webhook update thread."""
        from connectors import telegram_webhook as webhook

        message = {"chat": {"id": 42, "type": "private"}}
        with patch.object(webhook.bot, "handle_message", side_effect=SystemExit("review unavailable")), \
             patch.object(webhook.bot, "send") as send, \
             patch.object(webhook, "_complete_update") as complete, \
             patch("builtins.print"):
            webhook._process_update(123, message)

        send.assert_called_once_with(42, "❌ تعذر تنفيذ الطلب: review unavailable")
        complete.assert_called_once_with(123)


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_cmd_runs_the_entrypoint_as_a_module(self):
        self.assertIn('CMD ["python3", "-u", "-m", "connectors.telegram_webhook_runtime_memory"]', self.text)

    def test_pythonpath_includes_app_root(self):
        self.assertIn("PYTHONPATH=/app", self.text)


if __name__ == "__main__":
    unittest.main()
