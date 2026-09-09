import json
import os
import unittest
from unittest import mock

from connectors import connection_setup

FAKE_SERVICE_ACCOUNT = json.dumps({
    "type": "service_account",
    "project_id": "abdulrahman-ai-os",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "abdulrahman-agent@abdulrahman-ai-os.iam.gserviceaccount.com",
    "client_id": "1234567890",
    "token_uri": "https://oauth2.googleapis.com/token",
})

FULL_ENV = {
    "TELEGRAM_BOT_TOKEN": "123:telegram",
    "GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT,
    "GOOGLE_SHEET_ID": "sheet-1",
    "GOOGLE_DRIVE_FOLDER_ID": "folder-1",
    "GOOGLE_DOCS_DOCUMENT_ID": "doc-1",
    "GOOGLE_CALENDAR_ID": "abdulrahman@group.calendar.google.com",
    "GITHUB_TOKEN": "ghp_example",
    "AI_OS_GITHUB_REPO": "addn2030-svg/personal-ai-agent",
    "ELEVENLABS_API_KEY": "eleven-test",
}

ALL_KEYS = ["telegram", "sheets", "drive", "docs", "calendar", "github", "voice"]


class ConfigCheckTests(unittest.TestCase):
    def test_empty_env_reports_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            results = connection_setup.run()
        self.assertEqual([r["key"] for r in results], ALL_KEYS)
        self.assertTrue(all(r["status"] == "missing" for r in results))
        self.assertFalse(any("live" in r for r in results))

    def test_full_env_reports_ok(self):
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            results = connection_setup.run()
        self.assertTrue(all(r["status"] == "ok" for r in results))

    def test_credentials_only_reports_partial(self):
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["sheets"]["status"], "partial")
        self.assertEqual(results["drive"]["status"], "partial")
        self.assertEqual(results["docs"]["status"], "partial")
        self.assertEqual(results["calendar"]["status"], "partial")
        self.assertEqual(results["telegram"]["status"], "missing")
        self.assertEqual(results["github"]["status"], "missing")

    def test_invalid_service_account_json(self):
        env = {**FULL_ENV, "GOOGLE_SERVICE_ACCOUNT_JSON": "{bad json"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        for key in ("sheets", "drive", "docs", "calendar"):
            self.assertEqual(results[key]["status"], "invalid", key)

    def test_calendar_primary_is_not_enough(self):
        env = {**FULL_ENV, "GOOGLE_CALENDAR_ID": "primary"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["calendar"]["status"], "partial")


class LiveProbeTests(unittest.TestCase):
    def test_live_probes_ok_and_fail(self):
        probes = {key: (lambda key=key: {"key": key}) for key in ALL_KEYS}
        probes["sheets"] = mock.Mock(side_effect=Exception("403: share the sheet first"))
        with mock.patch.dict(os.environ, FULL_ENV, clear=True), \
                mock.patch.dict(connection_setup.PROBES, probes):
            results = {r["key"]: r for r in connection_setup.run(live=True)}
        self.assertEqual(results["telegram"]["live"]["result"], {"key": "telegram"})
        self.assertFalse(results["sheets"]["live"]["ok"])
        self.assertIn("share the sheet", results["sheets"]["live"]["error"])

    def test_live_skips_unconfigured(self):
        probes = {key: mock.Mock(return_value={}) for key in ALL_KEYS}
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.dict(connection_setup.PROBES, probes):
            results = connection_setup.run(live=True)
        self.assertFalse(any("live" in r for r in results))
        for probe in probes.values():
            probe.assert_not_called()


class OutputTests(unittest.TestCase):
    def test_render_shows_next_steps_in_priority_order(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            output = connection_setup.render(connection_setup.run())
        self.assertIn("calendar → docs → github", output)
        for key in ALL_KEYS:
            self.assertIn(f"--guide {key}", output)

    def test_render_all_ok(self):
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            output = connection_setup.render(connection_setup.run())
        self.assertIn("All integrations configured", output)

    def test_main_exit_codes(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connection_setup.main([]), 2)
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            self.assertEqual(connection_setup.main([]), 0)

    def test_guide_lookup(self):
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "calendar"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("GOOGLE_CALENDAR_ID", text)
        self.assertIn("Make changes to events", text)
        self.assertEqual(connection_setup.main(["--guide", "unknown"]), 1)


if __name__ == "__main__":
    unittest.main()
