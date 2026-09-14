# -*- coding: utf-8 -*-
"""The container entrypoint must import, and must survive a startup failure.

Two production outages are pinned here:

1. ``ModuleNotFoundError: No module named 'connectors'`` — running
   ``python3 connectors/telegram_webhook_runtime_memory.py`` puts
   ``/app/connectors`` on ``sys.path`` instead of ``/app``, so the entrypoint
   died at import and the deploy crash-looped forever.
2. A startup error (missing token, Telegram unreachable) used to propagate out
   of ``run()`` and kill the process. It is now reported and retried in the
   background while the server keeps serving.

Because (2), these tests no longer wait for the process to exit — they wait for
it to reach the HTTP server, which is the signal that import and startup
succeeded.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = "connectors.telegram_webhook_runtime_memory"
MODULE_FILE = ROOT / "connectors" / "telegram_webhook_runtime_memory.py"
CANONICAL_FILE = ROOT / "connectors" / "telegram_webhook_runtime.py"

STARTUP_MARKER = "HTTP webhook server listening"
IMPORT_FAILURE = "No module named 'connectors'"
# With no token configured, a healthy boot registers nothing but keeps serving.
EXPECTED_WARNING = "Telegram webhook NOT registered"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _spawn(command, *, cwd=ROOT, data_dir=None):
    env = {
        **os.environ,
        "TELEGRAM_BOT_TOKEN": "",
        "PYTHONUNBUFFERED": "1",
        "PORT": str(_free_port()),
    }
    if data_dir:
        env["AI_OS_DATA_DIR"] = data_dir
    handle, path = tempfile.mkstemp(prefix="entrypoint-", suffix=".log")
    os.close(handle)
    with open(path, "w+") as log:
        proc = subprocess.Popen(
            command, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            yield proc, path
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
    try:
        os.unlink(path)
    except OSError:
        pass


def _wait_for_startup(path: str, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if STARTUP_MARKER in Path(path).read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


class ProductionEntrypointTests(unittest.TestCase):
    def _boot(self, command, **kwargs):
        """Boot the real entrypoint and assert it survived import and startup."""
        with tempfile.TemporaryDirectory() as tmp:
            with _spawn(command, data_dir=tmp, **kwargs) as (proc, path):
                reached = _wait_for_startup(path)
                alive = proc.poll() is None  # still serving, not exited on the failure
                text = Path(path).read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(IMPORT_FAILURE, text, f"entrypoint failed to import:\n{text}")
        self.assertTrue(reached, f"startup never reached the HTTP server:\n{text[-2000:]}")
        # Registration must degrade, not terminate: this is the crash-loop guard.
        self.assertIn(EXPECTED_WARNING, text)
        self.assertTrue(alive, f"process exited instead of serving:\n{text[-2000:]}")

    def test_module_invocation_imports(self):
        """The form the Dockerfile CMD uses."""
        self._boot([sys.executable, "-u", "-m", ENTRYPOINT])

    def test_script_invocation_imports(self):
        """The form that crash-looped: running the file directly as a script."""
        self._boot([sys.executable, "-u", str(MODULE_FILE)])

    def test_script_invocation_from_another_working_directory(self):
        """sys.path bootstrap must come from __file__, not from the cwd."""
        with tempfile.TemporaryDirectory() as tmp:
            with _spawn([sys.executable, "-u", str(MODULE_FILE)], cwd=tmp, data_dir=tmp) as (proc, path):
                reached = _wait_for_startup(path)
                text = Path(path).read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(IMPORT_FAILURE, text)
        self.assertTrue(reached, f"startup never reached the HTTP server:\n{text[-2000:]}")

    def test_canonical_runtime_still_imports_as_a_script(self):
        """Guard the sibling entrypoint against the same regression."""
        self._boot([sys.executable, "-u", str(CANONICAL_FILE)])


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_cmd_runs_the_entrypoint_as_a_module(self):
        self.assertIn(
            'CMD ["python3", "-u", "-m", "connectors.telegram_webhook_runtime_memory"]',
            self.text,
        )

    def test_pythonpath_includes_app_root(self):
        self.assertIn("PYTHONPATH=/app", self.text)


if __name__ == "__main__":
    unittest.main()
