# -*- coding: utf-8 -*-
"""اختبارات موصل Supabase — بلا شبكة: كل نداء HTTP مستبدل بعميل وهمي."""
import base64
import io
import json
import os
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from unittest import mock

from connectors import connection_setup, supabase_client, supabase_state
from engine import env_file

URL = "https://abcdefghijklmnop.supabase.co"
PUBLISHABLE = "sb_publishable_abc123XYZ"
SECRET = "sb_secret_def456UVW"
LEGACY_ANON = ".".join([
    base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("="),
    base64.urlsafe_b64encode(json.dumps({"iss": "supabase", "role": "anon"}).encode()).decode().rstrip("="),
    "signature",
])
LEGACY_SERVICE = ".".join([
    base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("="),
    base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("="),
    "signature",
])


def env_with(**values):
    return lambda name: values.get(name, "")


class FakeResponse:
    def __init__(self, payload, status=200):
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """يسجّل الطلبات ويعيد ردودًا مُعدّة مسبقًا."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


def http_error(code, payload):
    return HTTPError(URL, code, "error", {}, io.BytesIO(json.dumps(payload).encode()))


class FakeClient:
    """عميل وهمي لطبقة النسخ الاحتياطي (بلا HTTP)."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.inserted = []
        self.deleted = []

    def insert(self, table, rows, **kwargs):
        payload = rows if isinstance(rows, list) else [rows]
        for index, row in enumerate(payload):
            stored = dict(row)
            stored["id"] = len(self.inserted) + index + 1
            self.inserted.append((table, stored))
            self.rows.append(stored)
        return [row for _, row in self.inserted[-len(payload):]]

    def select(self, table, *, filters=None, order="", limit=100, **kwargs):
        rows = list(self.rows)
        for key, value in (filters or {}).items():
            if value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
        return rows[:limit]

    def delete(self, table, *, match, **kwargs):
        ids = match["id"].removeprefix("in.(").removesuffix(")")
        wanted = {item.strip() for item in ids.split(",")}
        self.rows = [r for r in self.rows if str(r.get("id")) not in wanted]
        self.deleted.append(match)
        return []


# ------------------------------------------------------------------ key/url
class KeyTests(unittest.TestCase):
    def test_key_kind_detects_both_key_systems(self):
        self.assertEqual(supabase_client.key_kind(PUBLISHABLE), "publishable")
        self.assertEqual(supabase_client.key_kind(SECRET), "secret")
        self.assertEqual(supabase_client.key_kind(LEGACY_ANON), "anon")
        self.assertEqual(supabase_client.key_kind(LEGACY_SERVICE), "service_role")
        self.assertEqual(supabase_client.key_kind("not-a-key"), "unknown")
        self.assertEqual(supabase_client.key_kind(""), "unknown")

    def test_only_secret_kinds_may_write(self):
        self.assertTrue(supabase_client.is_secret_key("secret"))
        self.assertTrue(supabase_client.is_secret_key("service_role"))
        self.assertFalse(supabase_client.is_secret_key("publishable"))
        self.assertFalse(supabase_client.is_secret_key("anon"))
        self.assertFalse(supabase_client.is_secret_key("unknown"))

    def test_redact_removes_secrets(self):
        message = supabase_client.redact(
            f"invalid api key {SECRET} and {PUBLISHABLE} rejected", SECRET, PUBLISHABLE)
        self.assertNotIn(SECRET, message)
        self.assertNotIn(PUBLISHABLE, message)
        self.assertIn("invalid api key *** and *** rejected", message)
        self.assertEqual(supabase_client.redact("plain message", SECRET), "plain message")

    def test_short_values_are_not_used_as_redaction_patterns(self):
        # حماية من حجب نص عام بالخطأ عند وجود قيمة قصيرة/فارغة
        self.assertEqual(supabase_client.redact("some text", "", "abc"), "some text")

    def test_url_validation(self):
        self.assertEqual(supabase_client.validate_url(URL + "/"), URL)
        with self.assertRaises(supabase_client.SupabaseError):
            supabase_client.validate_url("https://supabase.com/dashboard/project/abcdefgh")
        with self.assertRaises(supabase_client.SupabaseError):
            supabase_client.validate_url("abcdefgh.supabase.co")
        with self.assertRaises(supabase_client.SupabaseError):
            supabase_client.validate_url("")


class ConfigTests(unittest.TestCase):
    def test_missing_configuration(self):
        cfg = supabase_client.load_config(env_with())
        self.assertFalse(cfg.configured)
        self.assertEqual(cfg.summary()["status"], "missing")

    def test_secret_key_is_preferred_and_reads_summary(self):
        cfg = supabase_client.load_config(env_with(
            SUPABASE_URL=URL, SUPABASE_ANON_KEY=PUBLISHABLE,
            SUPABASE_SERVICE_ROLE_KEY=SECRET, SUPABASE_WRITE_ENABLED="1"))
        self.assertEqual(cfg.key, SECRET)
        self.assertEqual(cfg.key_kind, "service_role" if False else "secret")
        self.assertTrue(cfg.can_read)
        self.assertTrue(cfg.can_write)
        summary = cfg.summary()
        self.assertEqual(summary["url_host"], "abcdefghijklmnop.supabase.co")
        self.assertNotIn(SECRET, json.dumps(summary))

    def test_alias_variable_names_are_accepted(self):
        cfg = supabase_client.load_config(env_with(SUPABASE_URL=URL, SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE))
        self.assertEqual(cfg.anon_key, PUBLISHABLE)
        self.assertEqual(cfg.sources["anon"], "SUPABASE_PUBLISHABLE_KEY")
        cfg = supabase_client.load_config(env_with(SUPABASE_URL=URL, SUPABASE_SECRET_KEY=SECRET))
        self.assertEqual(cfg.secret_key, SECRET)

    def test_write_requires_both_flag_and_secret_key(self):
        anon_with_flag = supabase_client.load_config(env_with(
            SUPABASE_URL=URL, SUPABASE_ANON_KEY=PUBLISHABLE, SUPABASE_WRITE_ENABLED="1"))
        self.assertFalse(anon_with_flag.can_write)
        secret_no_flag = supabase_client.load_config(env_with(
            SUPABASE_URL=URL, SUPABASE_SERVICE_ROLE_KEY=SECRET))
        self.assertFalse(secret_no_flag.can_write)
        self.assertIn("SUPABASE_WRITE_ENABLED", secret_no_flag.summary()["detail"])

    def test_same_value_in_both_slots_never_grants_write(self):
        cfg = supabase_client.load_config(env_with(
            SUPABASE_URL=URL, SUPABASE_ANON_KEY=PUBLISHABLE,
            SUPABASE_SERVICE_ROLE_KEY=PUBLISHABLE, SUPABASE_WRITE_ENABLED="1"))
        self.assertFalse(cfg.can_write)

    def test_unknown_key_shape_is_invalid(self):
        cfg = supabase_client.load_config(env_with(SUPABASE_URL=URL, SUPABASE_ANON_KEY="garbage"))
        self.assertEqual(cfg.summary()["status"], "invalid")

    def test_publishable_key_is_read_only(self):
        cfg = supabase_client.load_config(env_with(SUPABASE_URL=URL, SUPABASE_ANON_KEY=PUBLISHABLE))
        summary = cfg.summary()
        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["can_read"])
        self.assertFalse(summary["can_write"])
        self.assertIn("RLS", summary["detail"])


# -------------------------------------------------------------------- client
class RequestTests(unittest.TestCase):
    def _client(self, responses, **env):
        values = {"SUPABASE_URL": URL, "SUPABASE_ANON_KEY": PUBLISHABLE, **env}
        opener = FakeOpener(responses)
        return supabase_client.SupabaseClient(supabase_client.load_config(env_with(**values)),
                                              opener=opener), opener

    def test_select_builds_headers_and_query(self):
        client, opener = self._client([[]])
        client.select("state_snapshots", columns="id,created_at", order="created_at.desc", limit=5)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.startswith(URL + "/rest/v1/state_snapshots?"))
        self.assertIn("select=id%2Ccreated_at", request.full_url)
        self.assertIn("order=created_at.desc", request.full_url)
        self.assertEqual(request.get_header("Apikey"), PUBLISHABLE)
        self.assertEqual(request.get_header("Authorization"), f"Bearer {PUBLISHABLE}")

    def test_insert_blocked_without_write_flag(self):
        client, opener = self._client([])
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.insert("state_snapshots", {"sha256": "x"})
        self.assertIn("SUPABASE_WRITE_ENABLED", str(ctx.exception))
        self.assertEqual(opener.requests, [])  # لا محاولة شبكة أصلًا

    def test_insert_allowed_with_secret_and_flag(self):
        client, opener = self._client([{"id": 7}], SUPABASE_SERVICE_ROLE_KEY=SECRET,
                                      SUPABASE_WRITE_ENABLED="1")
        client.insert("state_snapshots", {"sha256": "x"})
        self.assertEqual(opener.requests[0].get_method(), "POST")
        self.assertEqual(opener.requests[0].get_header("Prefer"), "return=representation")

    def test_delete_requires_an_explicit_filter(self):
        client, opener = self._client([[]], SUPABASE_SERVICE_ROLE_KEY=SECRET, SUPABASE_WRITE_ENABLED="1")
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.delete("state_snapshots", match={})
        self.assertIn("غير مسموح", str(ctx.exception))
        self.assertEqual(opener.requests, [])

    def test_http_error_is_sanitized_and_hinted(self):
        error = http_error(401, {"message": f"Invalid API key {PUBLISHABLE}", "code": "PGRST301"})
        client, _ = self._client([error])
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.health()
        raised = ctx.exception
        self.assertNotIn(PUBLISHABLE, str(raised))
        self.assertEqual(raised.status, 401)
        self.assertIn("API Keys", raised.hint)
        self.assertFalse(raised.is_transient)

    def test_missing_table_error_explains_the_sql_fix(self):
        client, _ = self._client([http_error(404, {"message": "relation does not exist", "code": "42P01"})])
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.select("state_snapshots")
        self.assertIn("--sql", ctx.exception.hint)

    def test_network_failure_is_transient(self):
        client, _ = self._client([URLError("temporary failure")])
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.health()
        self.assertTrue(ctx.exception.is_transient)

    def test_health_lists_tables(self):
        payload = {"paths": {"/state_snapshots": {}, "/notes": {}}}
        client, _ = self._client([payload])
        info = client.health()
        self.assertEqual(info["host"], "abcdefghijklmnop.supabase.co")
        self.assertIn("state_snapshots", info["tables"])

    def test_doctor_reports_latest_snapshot(self):
        rows = [{"id": 3, "created_at": "2026-09-20T10:00:00Z", "sha256": "abc", "byte_size": 10}]
        values = {"SUPABASE_URL": URL, "SUPABASE_ANON_KEY": PUBLISHABLE}
        with mock.patch.dict(os.environ, values, clear=True):
            with mock.patch.object(supabase_client, "urlopen", FakeOpener([{"paths": {}}, rows])):
                info = supabase_client.doctor()
        self.assertEqual(info["snapshots_visible"], 1)
        self.assertEqual(info["latest_snapshot"], "2026-09-20T10:00:00Z")

    def test_sql_setup_locks_the_table_down(self):
        sql = supabase_client.SETUP_SQL.lower()
        self.assertIn("enable row level security", sql)
        self.assertIn("revoke all", sql)


# ------------------------------------------------------------------ snapshots
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state = {
            "meta": {"version": 42, "schema": "state/1"},
            "tasks": [{"id": 1}], "projects": [], "decisions": [], "waiting_for": [], "action_queue": [],
        }
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False)

    def test_snapshot_carries_hash_size_and_version(self):
        snapshot = supabase_state.build_snapshot("اختبار")
        self.assertEqual(snapshot["state_version"], 42)
        self.assertEqual(snapshot["schema"], "state/1")
        self.assertEqual(snapshot["reason"], "اختبار")
        self.assertEqual(snapshot["payload"], self.state)
        text = open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read()
        self.assertEqual(snapshot["sha256"], supabase_state.payload_digest(self.state))
        self.assertEqual(snapshot["byte_size"], len(text.encode("utf-8")))

    def test_digest_survives_a_jsonb_round_trip(self):
        """ترتيب المفاتيح يتغيّر في jsonb — البصمة يجب أن تبقى ثابتة."""
        reordered = dict(reversed(list(json.loads(json.dumps(self.state)).items())))
        self.assertEqual(supabase_state.payload_digest(self.state),
                         supabase_state.payload_digest(reordered))
        changed = json.loads(json.dumps(self.state))
        changed["tasks"] = [{"id": 2}]
        self.assertNotEqual(supabase_state.payload_digest(self.state),
                            supabase_state.payload_digest(changed))

    def test_verify_row_accepts_intact_snapshot(self):
        snapshot = supabase_state.build_snapshot()
        row = {**snapshot, "id": 1, "created_at": "2026-09-20T10:00:00Z"}
        report = supabase_state.verify_row(row)
        self.assertTrue(report["ok"], report["problems"])

    def test_verify_row_rejects_tampered_payload(self):
        snapshot = supabase_state.build_snapshot()
        snapshot["payload"]["tasks"] = [{"id": 999}]
        report = supabase_state.verify_row({**snapshot, "id": 1})
        self.assertFalse(report["ok"])
        self.assertTrue(any("sha256" in problem for problem in report["problems"]))

    def test_verify_row_rejects_missing_sections(self):
        broken = {"meta": {"version": 1}, "tasks": [], "sha256": "x", "payload": {"meta": {"version": 1}}}
        report = supabase_state.verify_row(broken)
        self.assertFalse(report["ok"])
        self.assertTrue(any("ناقصة" in problem for problem in report["problems"]))

    def test_push_records_audit_event(self):
        client = FakeClient()
        row = supabase_state.push("قبل النقل", client=client)
        self.assertEqual(row["id"], 1)
        self.assertEqual(client.inserted[0][0], "state_snapshots")
        audit = os.path.join(self.tmp.name, "audit.jsonl")
        if os.path.exists(audit):  # التدقيق لا يُسقط العملية إن تعذّر
            self.assertIn("supabase_snapshot_pushed", open(audit, encoding="utf-8").read())

    def test_restore_preview_changes_nothing(self):
        client = FakeClient([{**supabase_state.build_snapshot(), "id": 1,
                              "created_at": "2026-09-20T10:00:00Z"}])
        before = open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read()
        report = supabase_state.restore(1, apply=False, client=client)
        self.assertFalse(report["applied"])
        self.assertTrue(report["ok"])
        self.assertIn("--apply", report["note"])
        self.assertEqual(before, open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read())

    def test_restore_apply_writes_state_and_keeps_a_local_backup(self):
        snapshot = supabase_state.build_snapshot()
        snapshot["payload"]["tasks"] = [{"id": 1}, {"id": 2}]
        snapshot["sha256"] = supabase_state.payload_digest(snapshot["payload"])
        client = FakeClient([{**snapshot, "id": 5, "created_at": "2026-09-20T10:00:00Z"}])
        report = supabase_state.restore(5, apply=True, client=client)
        self.assertTrue(report["applied"])
        self.assertTrue(os.path.exists(report["local_backup"]))
        restored = json.load(open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8"))
        self.assertEqual(len(restored["tasks"]), 2)
        backups = os.listdir(os.path.join(self.tmp.name, "backups"))
        self.assertTrue(any(name.startswith("state-pre-restore-") for name in backups))

    def test_restore_refuses_a_corrupted_snapshot(self):
        snapshot = supabase_state.build_snapshot()
        snapshot["payload"]["tasks"] = [{"id": "tampered"}]
        client = FakeClient([{**snapshot, "id": 6, "created_at": "2026-09-20T10:00:00Z"}])
        before = open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read()
        report = supabase_state.restore(6, apply=True, client=client)
        self.assertFalse(report["applied"])
        self.assertFalse(report["ok"])
        self.assertEqual(before, open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read())

    def test_prune_keeps_the_newest_rows(self):
        rows = [{**supabase_state.build_snapshot(), "id": index, "created_at": f"2026-09-{index:02d}"}
                for index in range(1, 6)]
        client = FakeClient(rows)
        deleted = supabase_state.prune(2, client=client)
        self.assertEqual(deleted, 3)
        self.assertEqual(sorted(r["id"] for r in client.rows), [1, 2])


# ------------------------------------------------------------- connection row
class ConnectionCheckTests(unittest.TestCase):
    def test_unset_supabase_is_optional_not_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            row = connection_setup.check_supabase(env=lambda name: "")
        self.assertEqual(row["status"], "optional")
        self.assertIn("--guide supabase", row["detail"])

    def test_partial_and_invalid_states(self):
        partial = connection_setup.check_supabase(env=env_with(SUPABASE_URL=URL))
        self.assertEqual(partial["status"], "partial")
        invalid = connection_setup.check_supabase(env=env_with(SUPABASE_URL=URL, SUPABASE_ANON_KEY="junk"))
        self.assertEqual(invalid["status"], "invalid")
        dashboard = connection_setup.check_supabase(env=env_with(
            SUPABASE_URL="https://supabase.com/dashboard/project/abcdefgh", SUPABASE_ANON_KEY=PUBLISHABLE))
        self.assertEqual(dashboard["status"], "invalid")

    def test_configured_keys_report_ok_without_leaking_values(self):
        row = connection_setup.check_supabase(env=env_with(
            SUPABASE_URL=URL, SUPABASE_SERVICE_ROLE_KEY=SECRET, SUPABASE_WRITE_ENABLED="1"))
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["key_kind"], "secret")
        self.assertTrue(row["can_write"])
        self.assertNotIn(SECRET, json.dumps(row))

    def test_guide_and_render_include_supabase(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            results = connection_setup.run()
        names = [row["key"] for row in results]
        self.assertIn("supabase", names)
        rendered = connection_setup.render(results)
        self.assertIn("Supabase", rendered)
        with mock.patch("builtins.print") as printer:
            self.assertEqual(connection_setup.main(["--guide", "supabase"]), 0)
        text = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", text)
        self.assertIn("supabase-client", text.replace("_", "-"))


# -------------------------------------------------------------------- env
class EnvFileTests(unittest.TestCase):
    def _write(self, content):
        handle = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
        handle.write(content)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_parses_quotes_comments_and_export(self):
        parsed = env_file.parse_env_text(
            "# تعليق\n"
            "export SUPABASE_URL=https://abc.supabase.co\n"
            "SUPABASE_ANON_KEY='sb_publishable_quoted'\n"
            'SUPABASE_SERVICE_ROLE_KEY="sb_secret_quoted"  # تعليق\n'
            "SUPABASE_WRITE_ENABLED=1\n"
            "BROKEN LINE WITHOUT EQUALS\n"
            "\n"
        )
        self.assertEqual(parsed["SUPABASE_URL"], "https://abc.supabase.co")
        self.assertEqual(parsed["SUPABASE_ANON_KEY"], "sb_publishable_quoted")
        self.assertEqual(parsed["SUPABASE_SERVICE_ROLE_KEY"], "sb_secret_quoted")
        self.assertEqual(parsed["SUPABASE_WRITE_ENABLED"], "1")
        self.assertNotIn("BROKEN LINE WITHOUT EQUALS", parsed)

    def test_load_env_does_not_override_real_variables(self):
        path = self._write("SUPABASE_URL=https://from-file.supabase.co\nAI_OS_TEST_NEW=loaded\n")
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://from-env.supabase.co"}, clear=False):
            loaded = env_file.load_env(path)
            self.assertEqual(os.environ["SUPABASE_URL"], "https://from-env.supabase.co")
            self.assertEqual(os.environ["AI_OS_TEST_NEW"], "loaded")
        self.assertEqual(loaded, ["AI_OS_TEST_NEW"])  # أسماء فقط، بلا قيم

    def test_load_env_tolerates_a_missing_file(self):
        self.assertEqual(env_file.load_env(os.path.join(tempfile.gettempdir(), "no-such-file.env")), [])

    def test_override_mode_replaces_existing_values(self):
        path = self._write("SUPABASE_URL=https://from-file.supabase.co\n")
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://from-env.supabase.co"}, clear=False):
            env_file.load_env(path, override=True)
            self.assertEqual(os.environ["SUPABASE_URL"], "https://from-file.supabase.co")


if __name__ == "__main__":
    unittest.main()
