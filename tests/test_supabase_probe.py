# -*- coding: utf-8 -*-
"""فحص المشروع عن بُعد: بالمفتاح العام فقط، والتصنيف صحيح.

الردود المستخدمة هنا **منقولة حرفيًا** من ردود PostgREST الحقيقية التي رصدناها
على مشروع فعلي، لا من تخيّل: `PGRST205` لجدول مفقود · `PGRST202` لدالة مفقودة ·
«permission denied» لكائن موجود ومحجوب.
"""
import json
import unittest
import urllib.error

from connectors import supabase_probe as probe_mod

URL = "https://exampleprojectref.supabase.co"
PUBLISHABLE = "sb_publishable_abc123"
SECRET = "sb_secret_xyz789"
SERVICE_JWT = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
               "eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaXNzIjoic3VwYWJhc2UifQ."
               "signature")


class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body

    def read(self):
        return self._body.encode("utf-8")


def scripted(routes: dict):
    """يفتح ردًّا حسب اسم الكائن في الرابط (جدول أو دالة)."""
    calls = []

    def opener(url, timeout=None):
        calls.append(url)
        for name, response in routes.items():
            if f"/{name}" in url or f"/{name}?" in url or url.rstrip("/").endswith(f"/{name}"):
                if isinstance(response, Exception):
                    raise response
                return FakeResponse(response[0], response[1])
        return FakeResponse('{"code":"PGRST205","message":"Could not find the table"}', 404)

    opener.calls = calls
    return opener


class SecretKeyIsRefused(unittest.TestCase):
    """قاعدة أمنية في الكود لا في التوثيق: المسار الممنوع لا يعمل أصلًا."""

    def test_modern_secret_key_is_refused(self):
        self.assertIn("سري", probe_mod.reject_secret_key(SECRET))

    def test_service_role_jwt_is_refused(self):
        self.assertIn("service_role", probe_mod.reject_secret_key(SERVICE_JWT))

    def test_publishable_key_is_accepted(self):
        self.assertEqual(probe_mod.reject_secret_key(PUBLISHABLE), "")

    def test_anon_jwt_is_accepted(self):
        anon = ("eyJhbGciOiJIUzI1NiJ9."
                "eyJyb2xlIjoiYW5vbiJ9.sig")
        self.assertEqual(probe_mod.reject_secret_key(anon), "")

    def test_load_settings_points_to_the_public_variable(self):
        _, _, problem = probe_mod.load_settings({"SUPABASE_URL": URL, "SUPABASE_ANON_KEY": SECRET})
        self.assertIn("SUPABASE_ANON_KEY", problem)

    def test_settings_prefer_the_public_key_variable(self):
        url, key, problem = probe_mod.load_settings(
            {"SUPABASE_URL": URL, "SUPABASE_ANON_KEY": PUBLISHABLE})
        self.assertEqual((url, key, problem), (URL, PUBLISHABLE, ""))


class UrlValidation(unittest.TestCase):
    def test_dashboard_link_is_rejected_with_a_clear_reason(self):
        _, _, problem = probe_mod.load_settings(
            {"SUPABASE_URL": "https://supabase.com/dashboard/project/x",
             "SUPABASE_ANON_KEY": PUBLISHABLE})
        self.assertIn("لوحة التحكم", problem)

    def test_plain_http_is_rejected(self):
        self.assertEqual(probe_mod.normalize_url("http://x.supabase.co"), "")

    def test_valid_url_is_normalized(self):
        self.assertEqual(probe_mod.normalize_url(URL + "/"), URL)


class Classification(unittest.TestCase):
    MISSING_TABLE = ('{"code":"PGRST205","details":null,"hint":null,'
                     '"message":"Could not find the table \'public.x\' in the schema cache"}')
    MISSING_RPC = ('{"code":"PGRST202","details":"Searched for the function",'
                   '"message":"Could not find the function"}')
    DENIED = '{"code":"42501","message":"permission denied for table x"}'

    def test_missing_table_is_reported_as_not_created(self):
        state, detail = probe_mod._classify(404, self.MISSING_TABLE, "table")
        self.assertEqual(state, "missing")
        self.assertIn("لم يُنفَّذ", detail)

    def test_missing_function_is_reported_as_not_created(self):
        state, _ = probe_mod._classify(404, self.MISSING_RPC, "function")
        self.assertEqual(state, "missing")

    def test_permission_denied_means_it_exists(self):
        """الحجب صفة الكائن الموجود — وهذا هو الوضع الصحيح أمنيًا."""
        state, detail = probe_mod._classify(403, self.DENIED, "table")
        self.assertEqual(state, "exists")
        self.assertIn("محجوب", detail)

    def test_empty_array_is_flagged_as_open(self):
        state, detail = probe_mod._classify(200, "[]", "table")
        self.assertEqual(state, "open")
        self.assertIn("REVOKE", detail)

    def test_bad_key_is_not_confused_with_a_missing_table(self):
        state, _ = probe_mod._classify(401, '{"message":"No API key found in request"}', "table")
        self.assertEqual(state, "unknown")

    def test_network_error_does_not_raise(self):
        opener = scripted({name: ConnectionError("boom")
                           for name in probe_mod.TABLES + probe_mod.FUNCTIONS})
        report = probe_mod.probe(URL, PUBLISHABLE, opener=opener)
        self.assertEqual(report["present"], 0)
        self.assertEqual(len(report["unknown"]), 10)


class FullProbe(unittest.TestCase):
    def _routes(self, table_body, table_status, fn_body, fn_status):
        routes = {}
        for name in probe_mod.TABLES:
            routes[name] = (table_body, table_status)
        for name in probe_mod.FUNCTIONS:
            routes[name] = (fn_body, fn_status)
        return routes

    def test_fresh_project_reports_nothing_started(self):
        routes = self._routes(Classification.MISSING_TABLE, 404,
                              Classification.MISSING_RPC, 404)
        report = probe_mod.probe(URL, PUBLISHABLE, opener=scripted(routes))
        self.assertEqual(report["present"], 0)
        self.assertEqual(len(report["missing"]), 10)
        self.assertIn("لم يبدأ الإعداد", report["verdict"])

    def test_configured_project_reports_complete(self):
        routes = self._routes(Classification.DENIED, 403, Classification.DENIED, 403)
        report = probe_mod.probe(URL, PUBLISHABLE, opener=scripted(routes))
        self.assertEqual(report["present"], 10)
        self.assertEqual(report["missing"], [])
        self.assertIn("مكتمل", report["verdict"])

    def test_half_configured_project_reports_what_is_missing(self):
        routes = {name: (Classification.DENIED, 403) for name in probe_mod.TABLES}
        routes.update({name: (Classification.MISSING_RPC, 404)
                       for name in probe_mod.FUNCTIONS})
        report = probe_mod.probe(URL, PUBLISHABLE, opener=scripted(routes))
        self.assertEqual(report["present"], 5)
        self.assertIn("brain_recall", report["missing"])
        self.assertIn("ناقص", report["verdict"])

    def test_probe_never_calls_a_write_endpoint(self):
        """الفحص قراءة فقط — وهذا مضمون ببنية الروابط نفسها."""
        routes = self._routes(Classification.DENIED, 403, Classification.DENIED, 403)
        opener = scripted(routes)
        probe_mod.probe(URL, PUBLISHABLE, opener=opener)
        for url in opener.calls:
            self.assertNotIn("insert", url)
            self.assertNotIn("upsert", url)
            self.assertTrue(url.startswith(URL + "/rest/v1/"), url)

    def test_secret_key_never_reaches_the_network(self):
        """لو مُرِّر مفتاح سري عن طريق الخطأ، لا يخرج في أي رابط."""
        _, _, problem = probe_mod.load_settings({"SUPABASE_URL": URL,
                                                 "SUPABASE_ANON_KEY": SECRET})
        self.assertTrue(problem)          # يرفض قبل أي اتصال


class CLI(unittest.TestCase):
    def test_missing_configuration_exits_2(self):
        import contextlib
        import io
        import os as os_module
        from unittest import mock
        buffer = io.StringIO()
        with mock.patch.dict(os_module.environ, {}, clear=True), \
             contextlib.redirect_stderr(buffer):
            code = probe_mod.main([])
        self.assertEqual(code, 2)
        self.assertIn("SUPABASE_URL", buffer.getvalue())

    def test_help_prints_documentation(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = probe_mod.main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("SUPABASE_ANON_KEY", buffer.getvalue())

    def test_json_mode_is_parseable_and_exit_code_reflects_reality(self):
        import contextlib
        import io
        from unittest import mock
        buffer = io.StringIO()
        denied = ('{"code":"42501","message":"permission denied for table x"}', 403)

        def fake_open(url, timeout=15):
            return FakeResponse(denied[0], denied[1])

        with mock.patch.object(probe_mod, "load_settings",
                               lambda env=None: (URL, PUBLISHABLE, "")), \
             mock.patch.object(probe_mod, "_default_open", fake_open), \
             contextlib.redirect_stdout(buffer):
            code = probe_mod.main(["--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["present"], 10)

    def test_cli_exit_code_is_1_when_something_is_missing(self):
        import contextlib
        import io
        from unittest import mock
        buffer = io.StringIO()
        missing = ('{"code":"PGRST205","message":"Could not find the table"}', 404)

        def fake_open(url, timeout=15):
            return FakeResponse(missing[0], missing[1])

        with mock.patch.object(probe_mod, "load_settings",
                               lambda env=None: (URL, PUBLISHABLE, "")), \
             mock.patch.object(probe_mod, "_default_open", fake_open), \
             contextlib.redirect_stdout(buffer):
            code = probe_mod.main(["--json"])
        self.assertEqual(code, 1)


class RealResponsesFromAFreshProject(unittest.TestCase):
    """الحكم على مشروع حقيقي: الردود أدناه منقولة حرفيًا من مشروع Supabase قائم.

    هذا هو الفرق بين «اختبار يمر» و«اختبار يجيب على السؤال»: نفس الردود التي
    أعطاها PostgREST لمشروع لم يُنفَّذ عليه أي ملف SQL.
    """

    # نُبنى بـjson.dumps حتى لا تتعارض علامات الاقتباس داخل رسالة PostgREST
    REAL_MISSING_TABLE = json.dumps({
        "code": "PGRST205", "details": None, "hint": None,
        "message": "Could not find the table 'public.state_snapshots' in the schema cache",
    })
    REAL_MISSING_RPC = json.dumps({
        "code": "PGRST202",
        "details": ("Searched for the function public.brain_stats without parameters, "
                    "but no matches were found in the schema cache."),
        "hint": None,
        "message": ("Could not find the function public.brain_stats without parameters "
                    "in the schema cache"),
    })

    def test_real_fresh_project_verdict(self):
        routes = {}
        for name in probe_mod.TABLES:
            routes[name] = (self.REAL_MISSING_TABLE, 404)
        for name in probe_mod.FUNCTIONS:
            routes[name] = (self.REAL_MISSING_RPC, 404)
        report = probe_mod.probe(URL, PUBLISHABLE, opener=scripted(routes))
        self.assertEqual(report["present"], 0)
        self.assertEqual(sorted(report["missing"]),
                         sorted(probe_mod.TABLES + probe_mod.FUNCTIONS))
        self.assertEqual(report["unknown"], [])
        self.assertIn("لم يبدأ الإعداد", report["verdict"])

    def test_control_table_gives_the_same_code_as_our_tables(self):
        """لو كان رمز «غير موجود» يظهر لجدول وهمي أيضًا، فالاستدلال سليم."""
        _, detail = probe_mod._classify(404, self.REAL_MISSING_TABLE, "table")
        self.assertIn("لم يُنفَّذ", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
