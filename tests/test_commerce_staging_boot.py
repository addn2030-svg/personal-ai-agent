from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from connectors import commerce_staging_server as staging


class CommerceStagingBootTests(unittest.TestCase):
    def test_script_path_boot_stays_alive(self):
        repo = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["AI_OS_DISABLE_TELEGRAM"] = "1"
        env["PORT"] = "0"
        proc = subprocess.Popen(
            [sys.executable, "connectors/commerce_staging_server.py"],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.time() + 1.5
            while time.time() < deadline:
                code = proc.poll()
                if code is not None:
                    output = proc.stdout.read() if proc.stdout else ""
                    self.fail(f"staging server exited during boot with {code}: {output}")
                time.sleep(0.05)
            self.assertIsNone(proc.poll(), "staging server should remain alive after boot")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    def test_checkout_link_selftest_passes_only_after_provider_auth(self):
        body = json.dumps({"ok": False, "error": "UNSUPPORTED_ACTION"}).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://provider.example/checkout",
            422,
            "Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(body),
        )
        env = {
            "COMMERCE_CHECKOUT_WEBHOOK_URL": "https://provider.example/checkout",
            "COMMERCE_CHECKOUT_SECRET": "shared-secret",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(staging.urllib.request, "urlopen", side_effect=error) as mocked:
            result = staging.checkout_link_selftest()
        self.assertTrue(result["ok"])
        self.assertTrue(result["provider_reachable"])
        self.assertTrue(result["provider_auth"])
        self.assertFalse(result["real_purchase"])
        sent = json.loads(mocked.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["action"], "selftest")
        self.assertNotIn("order", sent)

    def test_checkout_link_selftest_fails_closed_on_unauthorized(self):
        body = json.dumps({"ok": False, "error": "UNAUTHORIZED"}).encode("utf-8")
        error = urllib.error.HTTPError(
            "https://provider.example/checkout",
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(body),
        )
        env = {
            "COMMERCE_CHECKOUT_WEBHOOK_URL": "https://provider.example/checkout",
            "COMMERCE_CHECKOUT_SECRET": "wrong-secret",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(staging.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "CHECKOUT_PROVIDER_AUTH_FAILED"):
                staging.checkout_link_selftest()


if __name__ == "__main__":
    unittest.main()
