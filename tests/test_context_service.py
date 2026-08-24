import unittest

from engine.context_service import expand_query, rank_records


class ContextServiceTests(unittest.TestCase):
    def test_contract_name_query_expands_to_related_concepts(self):
        terms = expand_query("راجع رسائل الواتساب المتعلقة بالعقد مع العمير")
        self.assertIn("العمير", terms)
        self.assertIn("شراكه", terms)
        self.assertIn("تحفظات", terms)
        self.assertIn("مسوده", terms)

    def test_semantic_case_linking_without_literal_name(self):
        records = [{
            "sheet": "محادثات الوكيل", "row": 88,
            "values": ["عقد شراكة", "راتب الطرف الأول", "التمويل ورأس المال", "تحفظات"],
        }]
        hits = rank_records("العقد مع العمير ورسائل الواتساب", records)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].source_ref, "محادثات الوكيل!row:88")
        self.assertIn("شراكه", hits[0].matched_terms)

    def test_unrelated_row_is_excluded(self):
        records = [{"sheet": "مدخلات الوكيل", "row": 41, "values": ["باركود حجز المواعيد"]}]
        self.assertEqual(rank_records("العقد مع العمير", records), [])


if __name__ == "__main__":
    unittest.main()
