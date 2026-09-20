# -*- coding: utf-8 -*-
"""اختبار حي كامل لمسار Supabase — خادم PostgREST مصغّر على المضيف المحلي.

يفحص الطبقات كلها معًا كما تعمل في الواقع: بناء الطلب وترويساته، القراءة
والكتابة، التحقق من sha256، الاستعادة الذرّية، والتنقية عند رفض المفتاح.
لا يلمس الشبكة الخارجية ولا أي مشروع حقيقي.
"""
import datetime as dt
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
        for column in ("created_at", "id"):
            if order.startswith(column):
                desc = order.endswith("desc")
                if column == "id":
                    rows.sort(key=lambda row: int(row.get("id") or 0), reverse=desc)
                else:
                    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=desc)
                break
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
                record.setdefault("created_at", f"2026-09-20T10:00:{len(table):02d}Z")
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


class GradualRolloutE2ETests(unittest.TestCase):
    """إثبات «بلا توقف»: الطبقة الجديدة تعمل تدريجيًا، والقديم لا يتأثر، والتراجع فوري."""

    def setUp(self):
        _Handler.tables = {"state_snapshots": [], "tasks_mirror": []}
        _Handler.expected_keys = (SECRET_KEY,)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"AI_OS_DATA_DIR": self.tmp.name, "SUPABASE_URL": self.url,
               "SUPABASE_SERVICE_ROLE_KEY": SECRET_KEY, "SUPABASE_WRITE_ENABLED": "1",
               "SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

        from engine import rollout
        self.rollout = rollout
        rollout.kill(reason="بداية الاختبار")

        self.state = {
            "meta": {"version": 1, "schema": "state/1"},
            "tasks": [{"العنوان": "مهمة قديمة", "الحالة": "لم تبدأ", "الأولوية": "عالية"}],
            "projects": [], "decisions": [], "waiting_for": [], "action_queue": [],
        }
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False)

    def _client(self, key=SECRET_KEY):
        env = {"SUPABASE_URL": self.url, "SUPABASE_SERVICE_ROLE_KEY": key, "SUPABASE_WRITE_ENABLED": "1"}
        return supabase_client.SupabaseClient(supabase_client.load_config(lambda n: env.get(n, "")))

    def _write_audit(self, events):
        import datetime as dt2
        stamp = dt2.datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(self.tmp.name, "audit.jsonl"), "a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps({**event, "ts": stamp}) + "\n")

    def test_phase_0_dormant_touches_nothing(self):
        from connectors import supabase_tasks
        self.assertEqual(self.rollout.current_phase(), "dormant")
        # حتى مع الراية والمرحلة مُهيّأة، الأتمتة لا تعمل في dormant
        self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))
        self.assertEqual(_Handler._table("state_snapshots"), [])
        self.assertEqual(_Handler._table("tasks_mirror"), [])

    def test_phase_1_shadow_reads_but_never_writes(self):
        from connectors import supabase_tasks
        self.rollout.set_phase("shadow")
        report = self.rollout.reconcile(state=self.state, client=self._client())
        # المرآة فارغة والحالة فيها مهمة ⇒ انحراف متوقع، والأهم: لا كتابة
        self.assertEqual(report["local_rows"], 1)
        self.assertEqual(report["remote_rows"], 0)
        self.assertEqual(_Handler._table("tasks_mirror"), [])
        self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

    def test_phase_2_canary_writes_only_when_a_human_asks(self):
        from connectors import supabase_tasks
        self.rollout.set_phase("shadow")
        self.rollout.set_phase("canary")
        self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))
        supabase_tasks.sync(client=self._client(), state=self.state)   # أمر بشري
        self.assertEqual(len(_Handler._table("tasks_mirror")), 1)
        report = supabase_tasks.reconcile(client=self._client(), state=self.state)
        self.assertEqual(report["drift"], 0, "بعد المزامنة اليدوية يجب أن تطابق المرآة الحالة")

    def test_phase_3_dual_runs_alongside_and_old_workflow_is_untouched(self):
        from connectors import supabase_tasks
        from connectors import supabase_state
        self.rollout.set_phase("shadow")
        self.rollout.set_phase("canary")
        self.rollout.set_phase("dual")
        self.assertTrue(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

        # الحالة الأصلية قبل الدورة
        before = open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read()
        outcome = supabase_tasks.run_daily(state=self.state)
        self.assertEqual(outcome["errors"], [])
        self.assertIsNotNone(outcome["snapshot"])
        self.assertIsNotNone(outcome["mirror"])
        # state.json لم يُلمس: الطبقة الجديدة تقرأ منه فقط
        self.assertEqual(before, open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8").read())
        self.assertEqual(len(_Handler._table("state_snapshots")), 1)
        self.assertEqual(len(_Handler._table("tasks_mirror")), 1)
        self.assertEqual(supabase_state.list_snapshots(client=self._client())[0]["id"], 1)

    def test_rollback_mid_flight_stops_automation_instantly(self):
        from connectors import supabase_tasks
        self.rollout.set_phase("shadow")
        self.rollout.set_phase("canary")
        self.rollout.set_phase("dual")
        self.assertTrue(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

        self.rollout.kill(reason="انحراف اكتُشف")
        self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))
        # لا شيء يُحذف عند التراجع: أي نسخة أو صف سابق يبقى مكانه
        supabase_tasks.sync(client=self._client(), state=self.state)
        self.assertEqual(len(_Handler._table("tasks_mirror")), 1)
        self.rollout.kill(reason="تراجع ثانٍ")
        self.assertEqual(len(_Handler._table("tasks_mirror")), 1,
                         "التراجع لا يمحو بيانات — النسخ تبقى")

    def test_full_progression_to_primary_with_evidence(self):
        from connectors import supabase_tasks
        client = self._client()
        # نشاط موثّق: كل دورة تنتج دليلًا في ملف التدقيق
        self.rollout.set_phase("shadow")
        for _ in range(3):
            self.rollout.reconcile(state=self.state, client=client)
        self.assertTrue(self.rollout.gate("canary")["ok"])
        self.rollout.advance()

        for _ in range(3):
            supabase_tasks.sync(client=client, state=self.state)
            self.rollout.log_event("supabase_backup_done", mirror_rows=1)
        self.rollout.reconcile(state=self.state, client=client)   # دليل التطابق بعد الكتابة
        self.assertTrue(self.rollout.gate("dual")["ok"])
        self.rollout.advance()

        for _ in range(6):
            self.rollout.log_event("supabase_backup_done", mirror_rows=1)
        with mock.patch.dict(os.environ, {self.rollout.ACK_ENV: self.rollout.PRIMARY_ACK}, clear=False):
            self.assertTrue(self.rollout.gate("primary")["ok"])
            result = self.rollout.advance(reason="تحقق كامل")
        self.assertEqual(result["phase"], "primary")

    def test_corrupt_phase_file_during_operation_halts_automation_without_crash(self):
        from connectors import supabase_tasks
        self.rollout.set_phase("shadow")
        self.rollout.set_phase("canary")
        self.rollout.set_phase("dual")
        with open(self.rollout.path(), "w", encoding="utf-8") as handle:
            handle.write("{ نصف مكتوب")
        # لا استثناء، والأتمتة تتوقف (فشل ينغلق على الأأمن)
        self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))
        self.assertEqual(self.rollout.current_phase(), "dormant")


class EphemeralHostTests(unittest.TestCase):
    """محاكاة مضيف بلا قرص دائم: إقلاع ← فقدان القرص ← إقلاع ثانٍ يستعيد الذاكرة.

    هذا هو السيناريو الفعلي على Render/Koyeb المجاني: الحاوية تُوقف والحالة
    تُمسح، ثم تعود الخدمة فارغة. الاختبار يثبت أن «القرص» في Supabase يكفي.
    """

    def setUp(self):
        _Handler.tables = {"state_snapshots": [], "tasks_mirror": []}
        _Handler.expected_keys = (SECRET_KEY,)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"AI_OS_DATA_DIR": self.tmp.name, "SUPABASE_URL": self.url,
               "SUPABASE_SERVICE_ROLE_KEY": SECRET_KEY, "SUPABASE_WRITE_ENABLED": "1",
               "AI_OS_STATE_RESTORE_ON_BOOT": "1", "AI_OS_STATE_PERSIST": "1"}
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def _client(self):
        env = {"SUPABASE_URL": self.url, "SUPABASE_SERVICE_ROLE_KEY": SECRET_KEY,
               "SUPABASE_WRITE_ENABLED": "1"}
        return supabase_client.SupabaseClient(supabase_client.load_config(lambda n: env.get(n, "")))

    def _write_state(self, tasks):
        with open(os.path.join(self.tmp.name, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"meta": {"version": 3, "schema": "state/1"}, "tasks": tasks,
                       "projects": [], "decisions": [], "waiting_for": [], "action_queue": []},
                      handle, ensure_ascii=False)

    def _wipe_disk(self):
        """يحاكي إيقاف الحاوية: الملفات المحلية تختفي، والسحابة تبقى."""
        for name in os.listdir(self.tmp.name):
            os.remove(os.path.join(self.tmp.name, name))

    def test_full_cycle_survives_a_container_restart(self):
        from connectors import state_persistence

        # ── إقلاع أول: لا حالة ولا نسخة ⇒ إقلاع نظيف بلا استعادة
        first = state_persistence.install(client=self._client())
        self.assertEqual(first["restore"]["action"], "skip")
        self.assertIsNotNone(first["persist"])         # دورة الدفع تنتظر ظهور الحالة
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "state.json")))

        # ── عمل المستخدم: تُكتب حالة ثم تُدفع (الدفع التفاضلي)
        self._write_state([{"العنوان": "قرار مهم", "الحالة": "لم تبدأ"}])
        pushed = state_persistence.push_if_changed(client=self._client())
        self.assertTrue(pushed["pushed"])
        self.assertEqual(len(_Handler._table("state_snapshots")), 1)

        # ── إيقاف الحاوية: القرص يُمسح بالكامل (ما يحدث مجانًا على Render)
        self._wipe_disk()
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "state.json")))

        # ── إقلاع ثانٍ: الذاكرة تعود من السحابة
        second = state_persistence.restore_on_boot(client=self._client())
        self.assertTrue(second["restored"], second)
        restored = json.load(open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8"))
        self.assertEqual(restored["tasks"][0]["العنوان"], "قرار مهم")
        self.assertEqual(len(_Handler._table("state_snapshots")), 1,
                         "الاستعادة تقرأ فقط — لا تُنشئ نسخًا إضافية")

    def test_first_boot_after_wipe_with_no_snapshot_starts_clean(self):
        from connectors import state_persistence
        self._wipe_disk()
        report = state_persistence.restore_on_boot(client=self._client())
        self.assertEqual(report["action"], "skip")
        self.assertIn("أول نظيف", report["detail"])

    def test_differential_push_avoids_duplicate_snapshots(self):
        from connectors import state_persistence
        self._write_state([{"العنوان": "أ"}])
        for _ in range(3):
            state_persistence.push_if_changed(client=self._client())
        self.assertEqual(len(_Handler._table("state_snapshots")), 1,
                         "لا تغيير ⇒ لا نسخ مكرّرة (وإلا امتلأ الجدول بلا داعٍ)")

        self._write_state([{"العنوان": "أ"}, {"العنوان": "ب"}])
        result = state_persistence.push_if_changed(client=self._client())
        self.assertTrue(result["pushed"])
        self.assertEqual(len(_Handler._table("state_snapshots")), 2)

    def test_flush_on_shutdown_captures_the_last_change(self):
        from connectors import state_persistence
        self._write_state([{"العنوان": "قبل"}])
        state_persistence.push_if_changed(client=self._client())
        # تغيير لم تلحقه دورة الدفع، ثم إنهاء العملية (SIGTERM من الاستضافة)
        self._write_state([{"العنوان": "بعد"}])
        flushed = state_persistence.flush(reason="إنهاء بإشارة 15")
        self.assertTrue(flushed["pushed"])
        latest = supabase_state.fetch("latest", client=self._client())
        self.assertEqual(latest["payload"]["tasks"][0]["العنوان"], "بعد")
        self.assertEqual(latest["reason"], "إنهاء بإشارة 15")
