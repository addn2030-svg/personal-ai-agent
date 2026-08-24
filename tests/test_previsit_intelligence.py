import unittest

import previsit_intelligence as p


class PreVisitTests(unittest.TestCase):
    def test_diagnosis_selects_specific_questions(self):
        q = p.questionnaire("Lumbar disc with sciatica")
        self.assertEqual(q["module"], "LUMBAR_RADICULAR")
        self.assertGreater(len(q["questions"]), len(p.MODULES["GENERAL_MSK"]))

    def test_urgent_signal_never_generates_technique(self):
        result = p.analyse({"new_bowel_bladder_change": "نعم", "pain_worst": 9})
        self.assertEqual(result["status"], "URGENT_CLINICIAN_REVIEW")
        self.assertEqual(result["techniques"], [])
        self.assertIn("new_bowel_bladder_change", result["urgent_signals"])

    def test_high_irritability_is_not_diagnosis(self):
        result = p.analyse({"pain_worst": 8, "sleep_disturbed": "نعم"})
        self.assertEqual(result["irritability"], "HIGH")
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(result["patient_message_status"], "DRAFT_REQUIRES_CLINICIAN_APPROVAL")


if __name__ == "__main__":
    unittest.main()
