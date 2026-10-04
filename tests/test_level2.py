# -*- coding: utf-8 -*-
"""اختبارات المدير الشخصي — Level 2 (حوار حي + استشارة).

تغطي:
  - المخزن المحلي: كتابة ذرّية، أولويات، متأخرات، انتظار متعفن، طاقة، مراجعة.
  - العقل الحتمي: كل النوايا (بريف/مهام/قرار/ضعف/طاقة/تأمل/عبارات/فكرة/مراجعة).
  - قواعد المصفوفة: خياران فقط، 70% يقين، 48 ساعة، لا تخمين، L2 بلا أثر خارجي.
  - الخادم: API كامل عبر HTTP حقيقي على منفذ عشوائي.
  - الاستقلال: صفر استيراد من connectors/ أو engine/ القديمة.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from level2 import agent, protocols, state  # noqa: E402
from level2.state import Level2Store, parse_date  # noqa: E402


def fresh_store() -> Level2Store:
    """مخزن معزول بملف مؤقت لكل اختبار — لا يلمس بيانات المستخدم."""
    state._store = None
    tmp = tempfile.mkdtemp(prefix="l2test-")
    os.environ["LEVEL2_STATE_PATH"] = os.path.join(tmp, "state.json")
    return Level2Store(os.environ["LEVEL2_STATE_PATH"])


class TestStore(unittest.TestCase):
    def setUp(self):
        self.st = fresh_store()

    def test_atomic_create_and_reload(self):
        t = self.st.add_task("مهمة اختبار", due="2026-10-10")
        other = Level2Store(self.st.path)  # إعادة فتح من القرص
        self.assertEqual(len(other.tasks_open()), 1)
        self.assertEqual(other.tasks_open()[0]["id"], t["id"])

    def test_overdue_and_priorities(self):
        self.st.add_task("قديمة متأخرة", due="2026-01-01", importance="عالي")
        self.st.add_task("قادمة", due="2026-12-01", importance="عالي")
        self.assertEqual(len(self.st.tasks_overdue()), 1)
        top = self.st.top_priorities(1)[0]
        self.assertEqual(top["title"], "قديمة متأخرة")

    def test_waiting_stale_escalation(self):
        self.st.add_waiting("عنصر قديم", who="طرف خارجي", expected=None)
        w = self.st.waiting_open()[0]
        self.st._state["waiting_for"][0]["requested"] = "2026-08-01"
        self.st.commit()
        open_w, stale = self.st.waiting_open()
        self.assertEqual(len(open_w), 1)
        self.assertEqual(len(stale), 1)

    def test_decision_close(self):
        d = self.st.add_decision("قرار تجريبي")
        self.assertEqual(len(self.st.decisions_pending()), 1)
        self.st.close_decision(d["id"], option="(أ)", action="خطوة مادية")
        self.assertEqual(self.st.decisions_pending(), [])
        closed = self.st._state["decisions"][0]
        self.assertEqual(closed["first_physical_action"], "خطوة مادية")

    def test_corrupt_file_safe_fallback(self):
        with open(self.st.path, "w", encoding="utf-8") as f:
            f.write("{ هذا ليس JSON ")
        revived = Level2Store(self.st.path)
        self.assertEqual(revived.tasks_open(), [])  # لا استثناء، لا ضياع (corrupt محفوظ بجواره)

    def test_parse_date_forms(self):
        self.assertIsNotNone(parse_date("2026-10-12"))
        self.assertIsNotNone(parse_date("12/10"))
        self.assertIsNotNone(parse_date("غدًا"))


class TestAgentBrain(unittest.TestCase):
    def setUp(self):
        fresh_store()

    def handle(self, text):
        return agent.handle(text, channel="test")

    def test_brief_two_priorities_one_decision(self):
        self.handle("مهمة: أولوية أولى قبل 2026-10-01")
        self.handle("مهمة: أولوية ثانية")
        r = self.handle("قرار: هل أبدأ بمشروع العيادة")
        self.assertIn("70%", r["reply"])  # قاعدة M2
        b = self.handle("بريف")
        self.assertIn("أولوية أولى", b["reply"])
        self.assertIn("قرار واحد معلق", b["reply"])  # قاعدة M3

    def test_task_add_and_complete_by_title(self):
        r = self.handle("مهمة: استكمال الملفات قبل 2026-10-12")
        self.assertEqual(r["intent"], "task_add")
        self.assertIn("48 ساعة", r["reply"])  # قاعدة M5
        d = self.handle("أنجزت استكمال الملفات")
        self.assertIn("✓", d["reply"])
        self.assertIn("الدليل", d["reply"])

    def test_decision_two_options_rule(self):
        r = self.handle("قرار: فتح حساب ادخار منفصل")
        self.assertIn("خياران", r["reply"])          # قاعدة M1
        self.assertIn("24 ساعة", r["reply"])         # مهلة الحسم
        self.assertEqual(len(agent.get_store().decisions_pending()), 1)

    def test_weakness_protocol(self):
        r = self.handle("أعاني من الكمالية")
        self.assertEqual(r["intent"], "weakness")
        self.assertIn("80%", r["reply"])
        self.assertIn("مؤشر النجاح", r["reply"])

    def test_energy_low_activates_exhaustion_protocol(self):
        r = self.handle("طاقتي 3")
        self.assertEqual(r["intent"], "energy")
        self.assertIn("بروتوكول الإرهاق", r["reply"])
        self.assertEqual(agent.get_store().last_energy()["energy"], 3)

    def test_calm_and_phrase(self):
        r = self.handle("تأمل")
        self.assertEqual(r["intent"], "calm")
        p = self.handle("عبارة لطلب مساعدة مفاجئ")
        self.assertEqual(p["intent"], "phrase")
        self.assertIn("حماية الحدود", p["reply"])

    def test_idea_filtered_to_possibilities(self):
        r = self.handle("فكرة: منصة بحث عن الأطباء")
        self.assertIn("صندوق الاحتمالات", r["reply"])  # قاعدة M6

    def test_no_guessing_rule(self):
        r = self.handle("ما لون السماء على المريخ")
        self.assertIn("لا أخمّن", r["reply"])  # قاعدة M4

    def test_review_saved(self):
        self.handle("مراجعة أسبوعية")
        snap = agent.get_store().snapshot()
        self.assertEqual(len(snap["reviews"]), 1)


class TestProtocolData(unittest.TestCase):
    def test_matrix_complete(self):
        self.assertEqual(len(protocols.AGENT_MATRIX), 10)
        self.assertEqual(len(protocols.DECISION_PROTOCOL), 7)
        self.assertEqual(len(protocols.WEAKNESSES), 29)
        self.assertGreaterEqual(len(protocols.PHRASES), 20)
        self.assertGreaterEqual(len(protocols.CALM_TECHNIQUES), 10)

    def test_weakness_lookup(self):
        w = protocols.find_weakness("مشكلتي التسويف المزمن")
        self.assertEqual(w["name"], "التسويف")


class TestNoExternalDeps(unittest.TestCase):
    def test_zero_imports_from_legacy(self):
        """Level 2 مستقل تمامًا — بلا أي استيراد من connectors/ أو engine/ القديمة."""
        for fname in os.listdir(os.path.join(BASE, "level2")):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(BASE, "level2", fname), encoding="utf-8") as f:
                src = f.read()
            for pattern in ("from connectors", "import connectors", "from engine", "import engine"):
                self.assertNotIn(
                    pattern, src,
                    f"level2/{fname} يستورد من النظام القديم: {pattern}",
                )

    def test_offline_default(self):
        from level2 import llm
        saved = os.environ.pop("LLM_BASE_URL", None)
        try:
            self.assertFalse(llm.enabled())
            r = agent.handle("بريف", channel="test")
            self.assertEqual(r["mode"], "offline")  # يعمل بلا أي API
        finally:
            if saved:
                os.environ["LLM_BASE_URL"] = saved


class TestServerHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_store()
        from level2 import server as srv
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path, obj):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(obj).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_status_endpoint(self):
        d = self._get("/api/status")
        self.assertIn("llm", d)
        self.assertIn("L2", d["autonomy"])

    def test_brief_endpoint(self):
        d = self._get("/api/brief")
        self.assertIn("brief", d)
        self.assertIn("priorities", d["brief"])

    def test_chat_endpoint_roundtrip(self):
        agent.handle("مهمة: مهمة الخادم", channel="test")
        d = self._post("/api/chat", {"text": "بريف", "channel": "web"})
        self.assertEqual(d["intent"], "brief")
        self.assertIn("مهمة الخادم", d["reply"])
        self.assertIn("session", d)

    def test_energy_endpoint(self):
        d = self._post("/api/energy", {"level": 5})
        self.assertEqual(d["logged"]["energy"], 5)

    def test_index_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as r:
            html = r.read().decode("utf-8")
        self.assertIn("المدير الشخصي", html)
        self.assertIn("SpeechRecognition", html)


if __name__ == "__main__":
    unittest.main()
