# -*- coding: utf-8 -*-
"""اختبارات مصدر أنماط المعرّفات الواحد — ودقّة التمييز بين الإحصاء والسجل."""
import unittest

from connectors import pii


class IdentifierPatterns(unittest.TestCase):
    def test_email_phone_and_file_number_are_caught(self):
        text = "راسله على ahmed@example.com أو 0555123456، رقم الملف: A-99213"
        cleaned, hits = pii.scrub(text)
        self.assertEqual(sorted(hits), ["email", "identifier", "phone"])
        self.assertNotIn("ahmed@example.com", cleaned)
        self.assertNotIn("0555123456", cleaned)
        self.assertNotIn("A-99213", cleaned)

    def test_plain_numbers_are_not_identifiers(self):
        """لا إيجابيات كاذبة: أرقام المهام والمبالغ والسنوات تمرّ كما هي."""
        for text in ("مهمة 5 أولوية عالية", "التكلفة 120 ريال", "سنة 2026", "الرمز D-1"):
            cleaned, hits = pii.scrub(text)
            self.assertEqual(hits, [], text)
            self.assertEqual(cleaned, text)

    def test_arabic_labels_are_used(self):
        cleaned, _ = pii.scrub("a@b.com")
        self.assertEqual(cleaned, "[بريد محجوب]")


class ClinicalPrecision(unittest.TestCase):
    """التمييز الحرج: إحصاء إداري مشروع مقابل إشارة إلى فرد."""

    def test_pseudonym_code_is_caught(self):
        cleaned, count = pii.redact_clinical("متابعة P-102 الأسبوع القادم")
        self.assertEqual(count, 1)
        self.assertNotIn("P-102", cleaned)

    def test_patient_reference_with_name_is_caught(self):
        cleaned, count = pii.redact_clinical("والمريض أحمد يحتاج مراجعة للخطة")
        self.assertEqual(count, 1)
        self.assertNotIn("أحمد", cleaned)
        self.assertIn("[محتوى سريري محجوب]", cleaned)

    def test_administrative_counts_are_left_alone(self):
        """`المرضى` عمود إحصائي في 30 صفًا — حجبه يُفقد بيانات مشروعة."""
        for text in ("المرضى", "الجلسات", "متابعة المرضى", "تطبيق HEP للمرضى",
                     "ويزرد متابعة المرضى", "عدد مرضى اليوم 32"):
            cleaned, count = pii.redact_clinical(text)
            self.assertEqual(count, 0, text)
            self.assertEqual(cleaned, text)

    def test_business_sentence_survives_redaction(self):
        text = "ذكّرني أتواصل مع شركة الأجهزة، والمريض أحمد يحتاج مراجعة"
        cleaned, _ = pii.redact_clinical(text)
        self.assertIn("شركة الأجهزة", cleaned)
        self.assertNotIn("أحمد", cleaned)


class DeepScrub(unittest.TestCase):
    def test_keys_are_preserved_values_are_scrubbed(self):
        """المفاتيح مخطط لا بيانات: تغييرها يكسر الاسترجاع ومرآة المهام."""
        payload, stats = pii.scrub_deep(
            {"المرضى": 32, "بريد": "x@y.com", "ملاحظات": "المريض أحمد يحتاج مراجعة"},
            clinical=True,
        )
        self.assertIn("المرضى", payload)              # المفتاح كما هو
        self.assertEqual(payload["المرضى"], 32)       # القيمة العددية كما هي
        self.assertEqual(payload["بريد"], "[بريد محجوب]")
        self.assertEqual(stats["pii"], 1)
        self.assertEqual(stats["clinical"], 1)

    def test_counters_distinguish_pii_from_clinical(self):
        _, stats = pii.scrub_deep({"a": "a@b.com", "b": "P-101"}, clinical=True)
        self.assertEqual(stats["pii"], 1)
        self.assertEqual(stats["clinical"], 1)

    def test_clinical_off_by_default(self):
        _, stats = pii.scrub_deep({"a": "P-101"})
        self.assertEqual(stats["clinical"], 0)

    def test_non_string_values_pass_through(self):
        payload, stats = pii.scrub_deep({"n": 12, "b": True, "z": None, "f": 1.5})
        self.assertEqual(payload, {"n": 12, "b": True, "z": None, "f": 1.5})
        self.assertEqual(stats, {"pii": 0, "clinical": 0})

    def test_empty_input_does_not_raise(self):
        self.assertEqual(pii.scrub(None)[0], "")
        self.assertEqual(pii.redact_clinical("")[1], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
