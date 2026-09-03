import unittest

from connectors import strategic_creator
from evaluation import strategic_shadow_cases as cases


class StrategicShadowCaseTests(unittest.TestCase):
    def test_catalog_has_ten_unique_safe_cases_across_domains(self):
        rows = cases.rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["Case_ID"] for row in rows}), 10)
        self.assertGreaterEqual(len({row["Domain"] for row in rows}), 3)

    def test_cases_start_unrun_and_unrated(self):
        for row in cases.rows():
            self.assertEqual(row["Review_Status"], "NOT_RUN")
            self.assertEqual(row["Baseline_Output"], "")
            self.assertEqual(row["Strategic_Output"], "")
            self.assertEqual(row["Baseline_Useful"], "")
            self.assertEqual(row["Candidate_Useful"], "")
            self.assertEqual(row["Preferred"], "")
            self.assertEqual(row["Safety_Passed"], "")
            self.assertEqual(row["Evidence_Discipline"], "")
            self.assertEqual(tuple(row), cases.SHEET_COLUMNS)

    def test_every_catalog_decision_passes_the_activation_gate(self):
        for item in cases.CASES:
            with self.subTest(case_id=item.case_id):
                self.assertTrue(strategic_creator.should_activate(item.decision))

    def test_private_identifiers_are_rejected(self):
        case = cases.ShadowCase(
            "SC-X", "System", "راجع رقم الملف 12345", "مؤكد: اختبار",
        )
        with self.assertRaisesRegex(ValueError, "private identifiers"):
            case.to_row()


if __name__ == "__main__":
    unittest.main()
