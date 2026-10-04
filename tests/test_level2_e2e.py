# -*- coding: utf-8 -*-
"""اختبار سير العمل الكامل — Level 2 End-to-End عبر HTTP حقيقي.

يحاكي يومًا كاملًا مع المدير الشخصي كما يفعل المستخدم من المتصفح/تيليجرام:
  بريف ← التقاط مهام ← استشارة قرار ← نقطة ضعف ← طاقة منخفضة ← عبارة ← فكرة ←
  إنجاز ← مراجعة أسبوعية ← **إعادة تشغيل الخادم** ← التحقق من استمرارية كل شيء.

يعتمد على: خادم HTTP فعلي على منفذ عشوائي + حالة معزولة في مجلد مؤقت.
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

from level2 import state as state_mod  # noqa: E402


def _post(port, path, obj):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


class TestFullDayWorkflow(unittest.TestCase):
    """يوم كامل مع المدير — كل الخطوات عبر API حي، ثم إعادة تشغيل وتمحيص."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="l2e2e-")
        cls.state_path = os.path.join(cls.tmp, "state.json")
        os.environ["LEVEL2_STATE_PATH"] = cls.state_path
        state_mod._store = None
        cls._start_server()

    @classmethod
    def _start_server(cls):
        from level2 import server as srv
        state_mod._store = None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    # ── أدوات ──
    def chat(self, text, session=None):
        return _post(self.port, "/api/chat", {"text": text, "session": session, "channel": "web"})

    # ── سير اليوم ──

    def test_01_morning_brief_empty_state(self):
        d = self.chat("بريف")
        self.assertEqual(d["intent"], "brief")
        self.assertIn("بريف مركز", d["reply"])
        self.assertIn("لا مهام مفتوحة", d["reply"])  # بداية نظيفة

    def test_02_capture_two_tasks_by_voice(self):
        d1 = self.chat("مهمة: تجهيز عرض العيادة المنزلية قبل 2026-10-08")
        self.assertEqual(d1["intent"], "task_add")
        self.assertIn("48 ساعة", d1["reply"])  # قاعدة M5 فور التقاط الالتزام
        d2 = self.chat("مهمة: مراجعة ملفات الأطباء قبل 12/10")
        self.assertIn("2026-10-12", d2["reply"])  # حل تاريخ يوم/شهر
        b = _get(self.port, "/api/brief")["brief"]
        self.assertEqual(b["tasks_open"], 2)

    def test_03_brief_shows_two_priorities_plus_decision_slot(self):
        self.chat("قرار: هل أطلق خدمة العيادة المنزلية هذا الشهر")
        d = self.chat("بريف")
        self.assertIn("تجهيز عرض العيادة المنزلية", d["reply"])   # أولوية 1
        self.assertIn("قرار واحد معلق", d["reply"])                # M3: قرار واحد فقط
        self.assertIn("70%", d["reply"])                            # M2: قاعدة اليقين

    def test_04_weakness_consult_even_with_decision_word(self):
        d = self.chat("أعاني من بطء الحسم في هذا القرار")
        self.assertEqual(d["intent"], "weakness")
        self.assertIn("بطء الحسم", d["reply"])
        self.assertIn("مؤشر النجاح", d["reply"])

    def test_05_low_energy_activates_exhaustion_protocol(self):
        d = self.chat("طاقتي 3")
        self.assertEqual(d["intent"], "energy")
        self.assertIn("بروتوكول الإرهاق", d["reply"])
        self.assertIn("Box Breathing", d["reply"])  # تقنية فورية من مكتبة الهدوء
        logged = _post(self.port, "/api/energy", {"level": 5})
        self.assertEqual(logged["logged"]["energy"], 5)

    def test_06_phrase_library(self):
        d = self.chat("عبارة لرفض التزام جديد")
        self.assertEqual(d["intent"], "phrase")
        self.assertIn("حماية الطاقة", d["reply"])
        self.assertIn("تجنّب", d["reply"])

    def test_07_new_idea_filtered_not_project(self):
        d = self.chat("فكرة: تطبيق توثيق الحالات السريرية")
        self.assertEqual(d["intent"], "idea")
        self.assertIn("صندوق الاحتمالات", d["reply"])  # M6: لا مشروع جديد قبل إغلاق المفتوح

    def test_08_no_guessing_on_unknown_question(self):
        d = self.chat("ما هو وزن المريض الأخير؟")
        self.assertIn("لا أخمّن", d["reply"])  # M4: الشفافية وعدم التخمين

    def test_09_complete_task_by_title_and_ask_evidence(self):
        d = self.chat("أنجزت عرض العيادة المنزلية")
        self.assertEqual(d["intent"], "task_done")
        self.assertIn("✓", d["reply"])
        self.assertIn("الدليل", d["reply"])  # طلب دليل الإنجاز
        b = _get(self.port, "/api/brief")["brief"]
        self.assertEqual(b["tasks_open"], 1)

    def test_10_weekly_review_measures_process(self):
        d = self.chat("مراجعة أسبوعية")
        self.assertEqual(d["intent"], "review")
        self.assertIn("مهام أُنجزت هذا الأسبوع: 1", d["reply"])
        self.assertIn("الحكم", d["reply"])

    def test_11_restart_server_and_verify_persistence(self):
        """أهم اختبار: إيقاف الخادم وإعادة تشغيله — كل شيء كما هو (لا سحابة)."""
        before = _get(self.port, "/api/brief")["brief"]
        self.httpd.shutdown()  # إيقاف
        self._start_server()   # إعادة تشغيل على منفذ جديد بنفس ملف الحالة
        after = _get(self.port, "/api/brief")["brief"]
        self.assertEqual(before["tasks_open"], after["tasks_open"])
        self.assertEqual(before["decisions_pending"], after["decisions_pending"])
        self.assertEqual(after["tasks_open"], 1)
        self.assertEqual(after["decisions_pending"], 1)
        # والاستمرار في العمل بعد الإعادة طبيعي
        d = self.chat("مهامي")
        self.assertIn("مراجعة ملفات الأطباء", d["reply"])

    def test_12_offline_mode_all_along(self):
        """كل ما سبق عمل بلا أي مفتاح أو شبكة خارجية — الوضع الحتمي."""
        d = self.chat("حالة النظام")
        self.assertIn("OFFLINE_DETERMINISTIC", d["reply"])

    def test_13_state_file_is_valid_json_on_disk(self):
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["tasks"]), 2)          # واحدة مفتوحة + واحدة مكتملة
        self.assertEqual(len(data["decisions"]), 1)
        self.assertEqual(len(data["possibilities"]), 1)
        self.assertGreaterEqual(len(data["sessions"]), 1)
        self.assertEqual(len(data["energy_log"]), 2)


if __name__ == "__main__":
    unittest.main()
