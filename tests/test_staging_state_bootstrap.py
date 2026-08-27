import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import bootstrap_staging_state


class StagingStateBootstrapTests(unittest.TestCase):
    def test_creates_valid_empty_state_only_when_telegram_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            with patch.dict(os.environ, {
                "AI_OS_BOOTSTRAP_EMPTY_STATE": "1",
                "AI_OS_DISABLE_TELEGRAM": "1",
            }, clear=False):
                result = bootstrap_staging_state.bootstrap(path)

            self.assertTrue(result["ok"])
            self.assertTrue(result["created"])
            self.assertEqual(result["records"], 0)
            self.assertTrue(Path(path).exists())
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["meta"]["schema"], "state/1")
            self.assertEqual(data["meta"]["last_mutator"], "staging_bootstrap")

    def test_rejects_bootstrap_when_telegram_is_not_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            with patch.dict(os.environ, {
                "AI_OS_BOOTSTRAP_EMPTY_STATE": "1",
                "AI_OS_DISABLE_TELEGRAM": "0",
            }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "requires AI_OS_DISABLE_TELEGRAM=1"):
                    bootstrap_staging_state.bootstrap(path)
            self.assertFalse(Path(path).exists())

    def test_railway_entrypoint_runs_bootstrap_as_package_module(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "start_production.sh").read_text(encoding="utf-8")
        self.assertIn("python3 -m engine.bootstrap_staging_state", script)
        self.assertNotIn("python3 engine/bootstrap_staging_state.py", script)


if __name__ == "__main__":
    unittest.main()
