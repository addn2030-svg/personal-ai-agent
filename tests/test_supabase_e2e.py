# -*- coding: utf-8 -*-
"""اختبار حي كامل لمسار Supabase — خادم PostgREST مصغّر على المضيف المحلي.

يفحص الطبقات كلها معًا كما تعمل في الواقع: بناء الطلب وترويساته، القراءة
والكتابة، التحقق من sha256، الاستعادة الذرّية، والتنقية عند رفض المفتاح.
لا يلمس الشبكة الخارجية ولا أي مشروع حقيقي.
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

from connectors import supabase_client, supabase_state

SECRET_KEY = "sb_secret_e2e_local_key"
PUBLISHABLE_KEY = "sb_publishable_e2e_local_key"


class _Handler(BaseHTTPRequestHandler):
    """PostgREST مصغّر: صف واحد من الجداول يكفي لفحص المسار الكامل."""

    rows: list = []
    expected_keys: tuple = (SECRET_KEY,)

    def log_message(self, *args):  # امنع ضجيج السجل في مخرجات الاختبار
        pass

    # -- helpers ---------------------------------------------------------
    def _send(self, status, payload, content_type="application/json"):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        key = self.headers.get("apikey") or ""
        if key in self.expected_keys:
            return True
        # الرسالة تعيد المفتاح عمدًا لنتأكد أن الموصل ينقّيه قبل العرض
        self._send(401, {"message": f"Invalid API key {key}", "code": "PGRST301"})
        return False

    def _matching(self, query):
        rows = list(type(self).rows)
        filter_id = (query.get("id") or [""])[0]
        if filter_id.startswith("eq."):
            want = filter_id[3:]
            rows = [row for row in rows if str(row.get("id")) == want]
        if (query.get("order") or [""])[0].startswith("created_at"):
            rows.sort(key=lambda row: str(row.get("created_at")), reverse=True)
        limit = int((query.get("limit") or ["100"])[0])
        return rows[:limit]

    @staticmethod
    def _project(rows, columns):
        if not columns or "*" in columns:  # select=* ⇒ كل الأعمدة
            return rows
        fields = [field.strip() for field in columns.split(",")]
        return [{field: row.get(field) for field in fields} for row in rows]

    # -- verbs -----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") == "/rest/v1":
            if not self._authorized():
                return
            return self._send(200, {"paths": {"/state_snapshots": {}}},
                              content_type="application/openapi+json")
        if parsed.path == "/rest/v1/state_snapshots":
            if not self._authorized():
                return
            query = parse_qs(parsed.query)
            rows = self._project(self._matching(query), (query.get("select") or [""])[0])
            return self._send(200, rows)
        return self._send(404, {"message": "relation does not exist", "code": "42P01"})

    def do_POST(self):
        if self.path != "/rest/v1/state_snapshots":
            return self._send(404, {"message": "not found"})
        if not self._authorized():
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"[]")
        payload = payload if isinstance(payload, list) else [payload]
        stored = []
        for index, row in enumerate(payload):
            record = dict(row)
            record["id"] = len(type(self).rows) + index + 1
            record["created_at"] = f"2026-09-20T10:0{index}:00Z"
            stored.append(record)
        type(self).rows.extend(stored)
        return self._send(201, stored)

    def do_DELETE(self):
        if self.path.split("?")[0] != "/rest/v1/state_snapshots":
            return self._send(404, {"message": "not found"})
        if not self._authorized():
            return
        query = parse_qs(urlparse(self.path).query)
        wanted = (query.get("id") or [""])[0]
        wanted = wanted.removeprefix("in.(").removesuffix(")") if wanted.startswith("in.(") else wanted
        targets = {item.strip() for item in wanted.split(",") if item.strip()}
        removed = [row for row in type(self).rows if str(row.get("id")) in targets]
        type(self).rows = [row for row in type(self).rows if str(row.get("id")) not in targets]
        return self._send(200, removed)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        _Handler.rows = []
        _Handler.expected_keys = (SECRET_KEY,)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        self.state = {
            "meta": {"version": 7, "schema": "state/1"},
            "tasks": [{"id": 1, "title": "قبل"}], "projects": [], "decisions": [],
            "waiting_for": [], "action_queue": [],
        }
        self._write_state(self.state)

    def _write_state(self, state):
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)

    def _client(self, key=SECRET_KEY):
        env = {"SUPABASE_URL": self.url, "SUPABASE_SERVICE_ROLE_KEY": key, "SUPABASE_WRITE_ENABLED": "1"}
        if key == PUBLISHABLE_KEY:
            env = {"SUPABASE_URL": self.url, "SUPABASE_ANON_KEY": key}
        return supabase_client.SupabaseClient(supabase_client.load_config(lambda n: env.get(n, "")))

    def test_full_push_list_show_restore_cycle(self):
        client = self._client()
        pushed = supabase_state.push("اختبار حي", client=client)
        self.assertEqual(pushed["id"], 1)
        self.assertEqual(pushed["state_version"], 7)
        self.assertEqual(pushed["payload"]["tasks"][0]["title"], "قبل")

        rows = supabase_state.list_snapshots(limit=5, client=client)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1)
        self.assertNotIn("payload", rows[0])  # القائمة تجلب أعمدة وصفية فقط

        # غيّر الحالة محليًا ثم استعد النسخة من "السحابة"
        self._write_state({**self.state, "tasks": [{"id": 9, "title": "بعد"}]})
        preview = supabase_state.restore(1, apply=False, client=client)
        self.assertTrue(preview["ok"])
        self.assertFalse(preview["applied"])
        with open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["tasks"][0]["title"], "بعد")

        applied = supabase_state.restore(1, apply=True, client=client)
        self.assertTrue(applied["applied"])
        with open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["tasks"][0]["title"], "قبل")
        self.assertTrue(os.path.exists(applied["local_backup"]))

    def test_health_and_doctor_over_real_http(self):
        client = self._client()
        info = client.health()
        self.assertIn("state_snapshots", info["tables"])
        config = supabase_client.load_config(
            lambda name: {"SUPABASE_URL": self.url, "SUPABASE_SERVICE_ROLE_KEY": SECRET_KEY}.get(name, ""))
        with mock.patch.object(supabase_client, "load_config", lambda env=None: config):
            report = supabase_client.doctor()
        self.assertTrue(report["host"].startswith("127.0.0.1"))
        self.assertEqual(report["snapshots_visible"], 0)

    def test_rejected_key_is_reported_without_leaking_it(self):
        anon_client = self._client(PUBLISHABLE_KEY)
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            anon_client.select("state_snapshots")
        error = ctx.exception
        self.assertEqual(error.status, 401)
        self.assertNotIn(PUBLISHABLE_KEY, str(error))
        self.assertIn("***", str(error))
        self.assertIn("API Keys", error.hint)

    def test_anon_key_cannot_push_even_with_real_server(self):
        anon_client = self._client(PUBLISHABLE_KEY)
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            supabase_state.push("محاولة", client=anon_client)
        self.assertIn("SUPABASE_WRITE_ENABLED", str(ctx.exception))
        self.assertEqual(_Handler.rows, [])  # لم يصل أي صف إلى "السحابة"

    def test_missing_table_is_explained(self):
        client = self._client()
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            client.select("no_such_table")
        self.assertEqual(ctx.exception.status, 404)
        self.assertIn("--sql", ctx.exception.hint)

    def test_prune_removes_old_rows(self):
        client = self._client()
        for index in range(3):
            supabase_state.push(f"نسخة {index}", client=client)
        self.assertEqual(len(_Handler.rows), 3)
        deleted = supabase_state.prune(keep=1, client=client)
        self.assertEqual(deleted, 2)
        self.assertEqual(len(_Handler.rows), 1)

    def test_loopback_http_is_allowed_but_remote_http_is_rejected(self):
        self.assertEqual(supabase_client.validate_url(self.url), self.url)
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            supabase_client.validate_url("http://my-project.supabase.co")
        self.assertIn("غير مشفّر", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
