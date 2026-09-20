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
    """PostgREST مصغّر: جداول في الذاكرة تكفي لفحص المسار الكامل.

    يدعم ما يستخدمه الموصل فعليًا: select بأعمدة ومرشّحات وترتيب وحد،
    upsert بدمج الصفوف على المفتاح الأساسي، وحذف بمرشّح neq/in.
    """

    tables: dict = {}
    expected_keys: tuple = (SECRET_KEY,)
    primary_keys: dict = {"state_snapshots": "id", "tasks_mirror": "id"}

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

    @classmethod
    def _table(cls, name):
        return cls.tables.setdefault(name, [])

    @staticmethod
    def _match(row, query):
        """يطبّق مرشّحات PostgREST المدعومة: eq / neq / in."""
        for key, values in query.items():
            if key in ("select", "limit", "order", "on_conflict"):
                continue
            raw = values[0]
            actual = str(row.get(key))
            if raw.startswith("eq.") and actual != raw[3:]:
                return False
            if raw.startswith("neq.") and actual == raw[4:]:
                return False
            if raw.startswith("in.(") and actual not in {
                    item.strip() for item in raw[4:].rstrip(")").split(",")}:
                return False
        return True

    @staticmethod
    def _project(rows, columns):
        if not columns or "*" in columns:  # select=* ⇒ كل الأعمدة
            return rows
        fields = [field.strip() for field in columns.split(",")]
        return [{field: row.get(field) for field in fields} for row in rows]

    def _filtered(self, name, query):
        rows = [row for row in self._table(name) if self._match(row, query)]
        order = (query.get("order") or [""])[0]
        if order.startswith("created_at"):
            desc = order.endswith("desc")
            rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=desc)
        limit = int((query.get("limit") or ["100"])[0])
        return rows[:limit]

    # -- verbs -----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "/rest/v1":
            if not self._authorized():
                return
            paths = {f"/{name}": {} for name in self.tables}
            return self._send(200, {"paths": paths}, content_type="application/openapi+json")
        if not path.startswith("/rest/v1/"):
            return self._send(404, {"message": "not found"})
        if not self._authorized():
            return
        name = path[len("/rest/v1/"):]
        if name not in self.tables:
            return self._send(404, {"message": "relation does not exist", "code": "42P01"})
        query = parse_qs(parsed.query)
        rows = self._project(self._filtered(name, query), (query.get("select") or [""])[0])
        return self._send(200, rows)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if not path.startswith("/rest/v1/"):
            return self._send(404, {"message": "not found"})
        if not self._authorized():
            return
        name = path[len("/rest/v1/"):]
        if name not in self.tables:
            return self._send(404, {"message": "relation does not exist", "code": "42P01"})
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"[]")
        payload = payload if isinstance(payload, list) else [payload]
        prefer = self.headers.get("Prefer") or ""
        merge = "merge-duplicates" in prefer
        table = self._table(name)
        pk = self.primary_keys.get(name, "id")
        stored = []
        for index, row in enumerate(payload):
            record = dict(row)
            existing = None
            if merge and record.get(pk) is not None:
                for current in table:
                    if str(current.get(pk)) == str(record.get(pk)):
                        existing = current
                        break
            if existing is not None:
                existing.update(record)          # دمج: تحديث الصف القائم
                stored.append(existing)
            else:
                if record.get(pk) is None:
                    record[pk] = len(table) + index + 1
                record.setdefault("created_at", f"2026-09-20T10:0{index}:00Z")
                table.append(record)
                stored.append(record)
        return self._send(201, stored)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path.startswith("/rest/v1/"):
            return self._send(404, {"message": "not found"})
        if not self._authorized():
            return
        name = path[len("/rest/v1/"):]
        if name not in self.tables:
            return self._send(404, {"message": "relation does not exist", "code": "42P01"})
        query = parse_qs(parsed.query)
        table = self._table(name)
        removed = [row for row in table if self._match(row, query)]
        self.tables[name] = [row for row in table if not self._match(row, query)]
        return self._send(200, removed)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        # الجداول التي أنشأها SQL الإعداد (01 + 02) — أي جدول غيرها يعطي 404 كما في الواقع
        _Handler.tables = {"state_snapshots": [], "tasks_mirror": []}
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
        self.assertEqual(_Handler._table("state_snapshots"), [])  # لم يصل أي صف إلى "السحابة"

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
        self.assertEqual(len(_Handler._table("state_snapshots")), 3)
        deleted = supabase_state.prune(keep=1, client=client)
        self.assertEqual(deleted, 2)
        self.assertEqual(len(_Handler._table("state_snapshots")), 1)

    # ---------------------------------------------------------- مرآة المهام
    def test_tasks_mirror_sync_is_idempotent_over_real_http(self):
        from connectors import supabase_tasks

        state = {
            **self.state,
            "tasks": [
                {"العنوان": "متأخرة", "الأولوية": "عالية", "الحالة": "لم تبدأ",
                 "الموعد النهائي": "2020-01-01", "المصدر": "صندوق الصوت"},
                {"العنوان": "منجزة", "الحالة": "منجزة", "الموعد النهائي": "2020-01-01"},
            ],
        }
        client = self._client()
        first = supabase_tasks.sync(client=client, state=state)
        self.assertEqual(first["rows"], 2)
        self.assertEqual(first["overdue"], 1)
        self.assertEqual(len(_Handler._table("tasks_mirror")), 2)
        rows = {row["title"]: row for row in _Handler._table("tasks_mirror")}
        self.assertEqual(rows["متأخرة"]["status_norm"], "not_started")
        self.assertTrue(rows["متأخرة"]["is_overdue"])
        self.assertFalse(rows["منجزة"]["is_open"])

        # إعادة المزامنة بلا تغيير: لا صفوف مكرّرة (المعرّف حتمي)
        supabase_tasks.sync(client=client, state=state)
        self.assertEqual(len(_Handler._table("tasks_mirror")), 2)

        # إغلاق مهمة يحدّث صفّها نفسه ولا ينشئ صفًا جديدًا
        closed = json.loads(json.dumps(state, ensure_ascii=False))
        closed["tasks"][0]["الحالة"] = "منجزة"
        summary = supabase_tasks.sync(client=client, state=closed)
        self.assertEqual(len(_Handler._table("tasks_mirror")), 2)
        self.assertEqual(summary["open"], 0)
        self.assertEqual(len(_Handler._table("tasks_mirror")[0].get("sync_run")), len(summary["run"]))

        # مهمة أُلغيت من الحالة تختفي من المرآة (لا صفوف يتيمة)
        trimmed = {**state, "tasks": [state["tasks"][1]]}
        supabase_tasks.sync(client=client, state=trimmed)
        remaining = _Handler._table("tasks_mirror")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["title"], "منجزة")

    def test_tasks_mirror_requires_a_secret_key(self):
        from connectors import supabase_tasks

        anon_client = self._client(PUBLISHABLE_KEY)
        with self.assertRaises(supabase_client.SupabaseError):
            supabase_tasks.sync(client=anon_client, state=self.state)
        self.assertEqual(_Handler._table("tasks_mirror"), [])

    def test_loopback_http_is_allowed_but_remote_http_is_rejected(self):
        self.assertEqual(supabase_client.validate_url(self.url), self.url)
        with self.assertRaises(supabase_client.SupabaseError) as ctx:
            supabase_client.validate_url("http://my-project.supabase.co")
        self.assertIn("غير مشفّر", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
