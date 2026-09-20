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
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = "connectors.telegram_webhook_runtime_memory"
MODULE_FILE = ROOT / "connectors" / "telegram_webhook_runtime_memory.py"

def webhook_boot_marker() -> str:
    """علامة الإقلاع من وحدة الخدمة نفسها (لا نص مكرّر يتفرّق عنها لاحقًا)."""
    from connectors.telegram_webhook import BOOT_MARKER
    return BOOT_MARKER


# Reaching this banner proves every import succeeded and startup ran to the point
# of configuring Telegram — i.e. the crash-loop class of bug is absent.
#
# ملاحظة مهمة: كان هذا الاختبار يعتمد على رسالة خطأ الاستيراد/الإعداد، ثم صار
# الإقلاع **غير قاتل** عمدًا (متغير ناقص يجب أن يُعلن في /health لا أن يُسقط
# الحاوية على Render). فانتقلنا إلى علامة إقلاع صريحة، والأهم: صار التشغيل عبر
# Popen مع إنهاء صريح — لأن الخدمة الآن تُقلع وتبقى حيّة، وsubprocess.run كان
# سينتظر انتهاءها عبثًا (180 ثانية لكل حالة، ويترك عمليات يتيمة تحجز المنفذ).
STARTUP_REACHED = webhook_boot_marker()
IMPORT_FAILURE = "No module named 'connectors'"
# سبب عطل الإعداد المتوقع في هذه الاختبارات (لا توكن): يُعلَن ولا يُسقط العملية
CONFIG_REPORTED = "Webhook not registered at boot"


class BootResult:
    def __init__(self, marker_seen, stdout, stderr, exit_code, still_running):
        self.marker_seen = marker_seen
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.still_running = still_running

    @property
    def output(self):
        return self.stdout + self.stderr


def _run(command, *, cwd=ROOT, data_dir=None, deadline=20):
    """يُقلع نقطة الدخول فعليًا، يجمع المخرجات حتى علامة الإقلاع، ثم يُنهيه.

    الإنهاء في `finally` مقصود: بلا ذلك يترك كل اختبار خدمة تعمل في الخلفية
    تحجز المنفذ وتُفسد الاختبارات التالية.
    """
    env = {**os.environ, "TELEGRAM_BOT_TOKEN": "", "PYTHONUNBUFFERED": "1"}
    if data_dir:
        env["AI_OS_DATA_DIR"] = data_dir
    proc = subprocess.Popen(
        command, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    stdout_lines, stderr_lines = [], []
    wanted = (STARTUP_REACHED, CONFIG_REPORTED)
    seen = set()
    deadline_at = time.time() + deadline
    try:
        # ننتظر حتى تظهر **كل** العلامات المطلوبة أو تنتهي المهلة: التوقف عند
        # أول سطر كان يخفي السطر التالي (إعلان الإعداد الناقص) ويُفسد التحقق.
        while time.time() < deadline_at:
            line = proc.stdout.readline()
            if line:
                stdout_lines.append(line)
                seen.update(marker for marker in wanted if marker in line)
                if all(marker in seen for marker in wanted):
                    break
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
        marker_seen = STARTUP_REACHED in seen
        exit_code, still_running = proc.poll(), proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        for stream, sink in ((proc.stdout, stdout_lines), (proc.stderr, stderr_lines)):
            try:
                sink.append(stream.read() or "")
            except (OSError, ValueError):
                pass
    return BootResult(marker_seen, "".join(stdout_lines), "".join(stderr_lines),
                      exit_code, still_running)


class ProductionEntrypointTests(unittest.TestCase):
    def test_module_invocation_imports(self):
        """The form the Dockerfile CMD now uses."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", "-m", ENTRYPOINT], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.output)
        self.assertTrue(proc.marker_seen, f"لم تصل نقطة الدخول إلى الإقلاع:\n{proc.output}")
        self.assertIn(CONFIG_REPORTED, proc.output)   # الإعداد الناقص يُعلَن ولا يُسقط العملية

    def test_script_invocation_imports(self):
        """The form that crash-looped: running the file directly as a script."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(MODULE_FILE)], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.output)
        self.assertTrue(proc.marker_seen, f"لم تصل نقطة الدخول إلى الإقلاع:\n{proc.output}")
        self.assertIn(CONFIG_REPORTED, proc.output)

    def test_script_invocation_from_another_working_directory(self):
        """sys.path bootstrap must come from __file__, not from the cwd."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(MODULE_FILE)], cwd=tmp, data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.output)
        self.assertTrue(proc.marker_seen, f"لم تصل نقطة الدخول إلى الإقلاع:\n{proc.output}")
        self.assertIn(CONFIG_REPORTED, proc.output)

    def test_canonical_runtime_still_imports_as_a_script(self):
        """Guard the sibling entrypoint against the same regression."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run([sys.executable, "-u", str(ROOT / "connectors" / "telegram_webhook_runtime.py")], data_dir=tmp)
        self.assertNotIn(IMPORT_FAILURE, proc.output)
        self.assertTrue(proc.marker_seen, f"لم تصل نقطة الدخول إلى الإقلاع:\n{proc.output}")
        self.assertIn(CONFIG_REPORTED, proc.output)

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
