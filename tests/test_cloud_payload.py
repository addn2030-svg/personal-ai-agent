# -*- coding: utf-8 -*-
"""العقد الأمني للنسخة السحابية: ما لا يجوز أن يغادر الجهاز.

هذه ليست اختبارات «شكل» بل اختبارات منع تسريب. البيانات المستخدمة هنا مأخوذة من
الشيت الرئيسي الفعلي (`data/master-sheet.xlsx`) — وهي أول بيانات حقيقية تُرحَّل
إلى SQL، ومحتواها السريري مختلط بأقسام غير سريرية عن قصد.
"""
import json
import os
import unittest
from unittest import mock

from connectors import cloud_payload, supabase_state

# حالة مصغّرة تحاكي الواقع: قسم سريري + تسرّب سريري داخل قسمَي المهام والصوت
# + بيانات إدارية مشروعة يجب ألّا تُمسّ.
STATE = {
    "meta": {"schema": "state/1", "version": 3},
    "tasks": [{"العنوان": "إرسال التقرير", "ملاحظات": "راسل ahmed@example.com"}],
    "projects": [
        {"المشروع": "تطبيق HEP للمرضى", "ملاحظات": "تنبيه ذكي لحالة المريض عند تغير القياسات"},
        {"المشروع": "Life Pulse", "ملاحظات": "لا محتوى سريري"},
    ],
    "kpis": [{"التاريخ": "2026-07-11", "المرضى": 32, "الجلسات": 45}],
    "voice": [{"النص": "والمريض أحمد يحتاج مراجعة للخطة", "الوجهة": "متابعة مرضى P-102"}],
    "followups": [
        {"الرمز": "P-101", "الحالة السريرية (مجهلة)": "ألم كتف متكرر",
         "الموعد القادم": "2026-08-23", "ملاحظات": "طلب المريض مراجعة الخطة"},
        {"الرمز": "P-102", "الحالة السريرية (مجهلة)": "ميلان قطني مزمن"},
    ],
    "decisions": [],
    "waiting_for": [],
    "action_queue": [],
}


class ClinicalSectionsAreWithheld(unittest.TestCase):
    def test_clinical_rows_never_leave_the_host(self):
        payload, report = cloud_payload.sanitize(STATE)
        self.assertEqual(payload["followups"], [])
        self.assertEqual(report["withheld"]["followups"], 2)

    def test_the_key_survives_so_restore_still_works(self):
        """الاسترجاع يحتاج الأقسام الأساسية كاملة — نُفرغ ولا نحذف."""
        payload, _ = cloud_payload.sanitize(STATE)
        for section in supabase_state.REQUIRED_SECTIONS:
            self.assertIn(section, payload)

    def test_withholding_is_announced_inside_the_snapshot(self):
        """الحجب الصامت يوهم أن النسخة كاملة."""
        payload, _ = cloud_payload.sanitize(STATE)
        self.assertEqual(payload["meta"]["cloud_withheld"], "followups: 2")

    def test_original_state_is_not_mutated(self):
        before = json.dumps(STATE, ensure_ascii=False, sort_keys=True)
        cloud_payload.sanitize(STATE)
        self.assertEqual(json.dumps(STATE, ensure_ascii=False, sort_keys=True), before)


class ClinicalContentIsCaughtOutsideClinicalSections(unittest.TestCase):
    def test_pseudonym_code_is_removed_everywhere(self):
        payload, _ = cloud_payload.sanitize(STATE)
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("P-101", blob)
        self.assertNotIn("P-102", blob)

    def test_patient_name_is_removed_but_business_text_stays(self):
        payload, _ = cloud_payload.sanitize(STATE)
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("أحمد", blob)
        self.assertIn("Life Pulse", blob)

    def test_administrative_kpi_columns_are_not_touched(self):
        payload, _ = cloud_payload.sanitize(STATE)
        self.assertEqual(payload["kpis"], STATE["kpis"])

    def test_pii_is_scrubbed(self):
        payload, report = cloud_payload.sanitize(STATE)
        self.assertNotIn("ahmed@example.com", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(report["redacted_cells"], 1)

    def test_report_separates_the_two_kinds(self):
        _, report = cloud_payload.sanitize(STATE)
        self.assertEqual(report["withheld"], {"followups": 2})
        self.assertEqual(report["redacted_cells"], 1)
        self.assertGreaterEqual(report["clinical_redactions"], 2)


class GuardsCanFail(unittest.TestCase):
    """اختبار لا يستطيع أن يفشل ليس اختبارًا: نُثبت أن الفحص ذو أثر."""

    def test_including_clinical_explicitly_does_let_codes_through(self):
        with mock.patch.dict(os.environ, {"SUPABASE_INCLUDE_CLINICAL": "1"}, clear=False):
            payload, report = cloud_payload.sanitize(STATE)
        # القسم يعود كاملًا (4 صفوف محليًا) — إذًا الحجب الافتراضي هو ما منعه
        self.assertEqual(len(payload["followups"]), len(STATE["followups"]))
        self.assertEqual(report["withheld"], {})

    def test_extra_sections_can_be_excluded(self):
        payload, report = cloud_payload.sanitize(STATE, sections=("followups", "voice"))
        self.assertEqual(payload["voice"], [])
        self.assertEqual(report["withheld"]["voice"], 1)

    def test_env_can_extend_the_exclusion_list(self):
        with mock.patch.dict(os.environ, {"SUPABASE_EXCLUDED_SECTIONS": "followups,projects"},
                             clear=False):
            self.assertEqual(cloud_payload.excluded_sections(), ("followups", "projects"))


class SnapshotPathUsesTheFilter(unittest.TestCase):
    """الفلتر ليس وحدة معزولة — يجب أن يكون على مسار الرفع نفسه."""

    def test_snapshot_payload_is_sanitized(self):
        snapshot = supabase_state.snapshot_from(STATE, reason="اختبار")
        blob = json.dumps(snapshot["payload"], ensure_ascii=False)
        self.assertEqual(snapshot["payload"]["followups"], [])
        self.assertNotIn("P-101", blob)
        self.assertNotIn("أحمد", blob)

    def test_snapshot_still_verifies_against_its_own_hash(self):
        """البصمة تُحسب على المحمول السحابي نفسه — فيبقى التحقق متسقًا."""
        row = {**supabase_state.snapshot_from(STATE, reason="اختبار"), "id": 1}
        verdict = supabase_state.verify_row(row)
        self.assertTrue(verdict["ok"], verdict["problems"])

    def test_verify_row_catches_tampering_after_the_filter(self):
        row = {**supabase_state.snapshot_from(STATE, reason="اختبار"), "id": 1}
        row["payload"]["followups"] = [{"الرمز": "P-103"}]     # عُدِّل بعد البصمة
        self.assertFalse(supabase_state.verify_row(row)["ok"])


class PreviewCLI(unittest.TestCase):
    """أداة المعاينة: يراها المستخدم قبل أي رفع."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "state.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(STATE, handle, ensure_ascii=False)

    def _run(self, *args):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cloud_payload.main(["--preview", "--state", self.path, *args])
        return code, buffer.getvalue()

    def test_preview_reports_what_will_be_withheld(self):
        code, out = self._run()
        self.assertEqual(code, 0)
        self.assertIn("followups", out)
        self.assertIn("'followups': 2", out)               # صفان في الحالة المصغّرة

    def test_preview_json_is_parseable(self):
        code, out = self._run("--json")
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload["withheld_sections"], ["followups"])
        self.assertEqual(payload["report"]["withheld"], {"followups": 2})
        self.assertIn("kpis", payload["payload_sections"])   # الإحصاء الإداري مسموح

    def test_preview_fails_clearly_without_state(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cloud_payload.main(["--preview", "--state",
                                       os.path.join(self.tmp, "missing.json")])
        self.assertEqual(code, 2)
        self.assertIn("لا يوجد ملف حالة", buffer.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
