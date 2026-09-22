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
    "GEMINI_API_KEY": "gemini-test",
    "GEMINI_MODEL": "google/gemini-3.7-flash",
    "BUFFER_API_KEY": "buffer-test",
}

ALL_KEYS = ["telegram", "sheets", "drive", "docs", "calendar", "github", "gemini",
            "openrouter", "bedrock", "kimi", "buffer", "supabase"]
# Optional integrations: unset is a valid, non-blocking state (never a "missing" failure).
OPTIONAL_KEYS = ["kimi", "supabase", "openrouter", "bedrock"]
REQUIRED_KEYS = [key for key in ALL_KEYS if key not in OPTIONAL_KEYS]


class EnvIsolation(unittest.TestCase):
    """يمنع أي `.env` حقيقي على جهاز المطوّر من التأثير على الاختبارات."""

    def setUp(self):
        patcher = mock.patch.object(connection_setup, "load_local_env", lambda: [])
        patcher.start()
        self.addCleanup(patcher.stop)


class ConfigCheckTests(EnvIsolation):
    def test_empty_env_reports_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            results = connection_setup.run()
        self.assertEqual([r["key"] for r in results], ALL_KEYS)
        by_key = {r["key"]: r for r in results}
        self.assertTrue(all(by_key[key]["status"] == "missing" for key in REQUIRED_KEYS))
        for key in OPTIONAL_KEYS:
            self.assertEqual(by_key[key]["status"], "optional", key)
        self.assertFalse(any("live" in r for r in results))

    def test_full_env_reports_ok(self):
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            results = connection_setup.run()
        by_key = {r["key"]: r for r in results}
        self.assertTrue(all(by_key[key]["status"] == "ok" for key in REQUIRED_KEYS))
        for key in OPTIONAL_KEYS:
            self.assertEqual(by_key[key]["status"], "optional", key)

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


class LiveProbeTests(EnvIsolation):
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


class OutputTests(EnvIsolation):
    def test_render_shows_next_steps_in_priority_order(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            output = connection_setup.render(connection_setup.run())
        self.assertIn("calendar → docs → github", output)
        self.assertIn("Gemini API", output)
        self.assertNotIn("Voice / Transcribe", output)
        for key in REQUIRED_KEYS:
            self.assertIn(f"--guide {key}", output)
        self.assertIn("Kimi API", output)
        self.assertIn("Supabase", output)

    def test_render_all_ok(self):
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            output = connection_setup.render(connection_setup.run())
        self.assertIn("All integrations configured", output)

    def test_main_exit_codes(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connection_setup.main([]), 2)
        with mock.patch.dict(os.environ, FULL_ENV, clear=True):
            self.assertEqual(connection_setup.main([]), 0)

    def test_kimi_key_reports_ok(self):
        env = {**FULL_ENV, "KIMI_API_KEY": "sk-kimi-test"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["kimi"]["status"], "ok")
        self.assertIn("kimi-k2.5", results["kimi"]["detail"])

    def test_openrouter_key_reports_ok_with_both_roles(self):
        """One key, two providers: the manager (Claude) and critic (GPT) models
        must both be visible in the status detail."""
        env = {**FULL_ENV, "OPENROUTER_API_KEY": "sk-or-test"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["openrouter"]["status"], "ok")
        self.assertIn("anthropic/claude-sonnet-4.6", results["openrouter"]["detail"])
        self.assertIn("openai/gpt-5.6-sol", results["openrouter"]["detail"])

    def test_openrouter_model_overrides_are_surfaced(self):
        env = {**FULL_ENV, "OPENROUTER_API_KEY": "sk-or-test",
               "AI_MANAGER_MODEL": "anthropic/claude-fable-5",
               "AI_CRITIC_MODEL": "openai/gpt-5.6-pro"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertIn("claude-fable-5", results["openrouter"]["detail"])
        self.assertIn("gpt-5.6-pro", results["openrouter"]["detail"])

    def test_bedrock_bearer_token_reports_ok(self):
        env = {**FULL_ENV, "AWS_BEARER_TOKEN_BEDROCK": "bedrock-test-token"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["bedrock"]["status"], "ok")
        self.assertIn("us.anthropic.claude-sonnet-4.6", results["bedrock"]["detail"])

    def test_bedrock_iam_pair_counts_as_configured(self):
        env = {**FULL_ENV, "AWS_ACCESS_KEY_ID": "AKIATEST", "AWS_SECRET_ACCESS_KEY": "sekret"}
        with mock.patch.dict(os.environ, env, clear=True):
            results = {r["key"]: r for r in connection_setup.run()}
        self.assertEqual(results["bedrock"]["status"], "ok")

    def test_model_probes_registered_for_new_channels(self):
        """--live must reach the Claude/GPT routes when their config is present."""
        for key in ("openrouter", "bedrock"):
            self.assertIn(key, connection_setup.PROBES,
                          f"live probe missing for {key}")

    def test_openrouter_live_probe_covers_claude_and_gpt(self):
        from connectors import model_gateway
        fake = mock.Mock(side_effect=lambda model=None: {"ok": True, "model": model})
        with mock.patch.object(model_gateway, "probe_openrouter", fake):
            out = connection_setup._probe_openrouter()
        self.assertEqual({"claude", "gpt"}, set(out))
        self.assertIn("claude", out["claude"]["model"])
        self.assertIn("gpt", out["gpt"]["model"])
        self.assertEqual(2, fake.call_count)  # one tiny inference per role

    def test_guide_lookup(self):
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "calendar"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("GOOGLE_CALENDAR_ID", text)
        self.assertIn("Make changes to events", text)
        self.assertEqual(connection_setup.main(["--guide", "unknown"]), 1)
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "kimi"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("KIMI_API_KEY", text)
        self.assertIn("platform.moonshot.ai", text)
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "openrouter"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("OPENROUTER_API_KEY", text)
        self.assertIn("openrouter.ai", text)
        self.assertIn("OPENROUTER_REQUIRE_ZDR", text)
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "bedrock"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("AWS_BEARER_TOKEN_BEDROCK", text)
        self.assertIn("BEDROCK_MODEL_ID", text)


if __name__ == "__main__":
    unittest.main()
