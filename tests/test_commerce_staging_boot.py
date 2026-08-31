from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
