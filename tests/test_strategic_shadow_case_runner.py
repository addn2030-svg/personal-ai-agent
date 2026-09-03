import json
import unittest
from unittest.mock import patch

from evaluation import strategic_shadow_case_runner as runner
from evaluation import strategic_shadow_cases as cases


def baseline(goal, evidence):
    return (
        f"CONFIRMED: {evidence}\n"
        "INFERENCE: compare the options before acting.\n"
        "APPROVAL: required before any external action."
    )


def candidate_for(case):
    def generate(prompt):
        return json.dumps({
            "domain": case.domain,
            "source": "supplied verified evidence only",
            "trigger": "material decision with incomplete outcome evidence",
            "hypothesis": "A bounded comparison will reduce decision risk",
            "micro_experiment": "Prepare one reversible draft and review it",
            "cost_sar": 0,
            "time_hours": 1,
            "confidence": 60,
            "risk_level": "LOW",
            "success_metric": "Reviewer records a clear comparison result",
            "review_date": "2026-09-10",
            "stop_condition": "Stop if any safety or schema gate fails",
        })
    return generate


class StrategicShadowCaseRunnerTests(unittest.TestCase):
    def test_prepares_all_ten_without_writes_or_human_ratings(self):
        with patch.dict(
            "os.environ", {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ):
            prepared = runner.prepare_all(baseline, candidate_for)
        self.assertEqual(len(prepared), 10)
        for item in prepared:
            self.assertTrue(item.passed)
            self.assertEqual(item.external_writes, 0)
            self.assertEqual(item.row["Review_Status"], "READY_FOR_REVIEW")
            self.assertTrue(item.row["Baseline_Output"])
            self.assertTrue(item.row["Strategic_Output"])
            for field in (
                "Baseline_Useful", "Candidate_Useful", "Preferred",
                "Safety_Passed", "Evidence_Discipline", "Reviewer_Note",
            ):
                self.assertEqual(item.row[field], "")

    def test_disabled_gate_blocks_preparation(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                runner.prepare_case(cases.CASES[0], baseline, candidate_for(cases.CASES[0]))

    def test_candidate_domain_must_match_catalog(self):
        case = cases.CASES[0]

        def wrong_domain(prompt):
            payload = json.loads(candidate_for(case)(prompt))
            payload["domain"] = "Finance"
            return json.dumps(payload)

        with patch.dict(
            "os.environ", {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "domain_matches_catalog"):
                runner.prepare_case(case, baseline, wrong_domain)

    def test_private_baseline_output_is_rejected(self):
        case = cases.CASES[0]

        def private_baseline(goal, evidence):
            return "CONFIRMED: contact test@example.com"

        with patch.dict(
            "os.environ", {"AI_STRATEGIC_CREATOR_ENABLED": "1"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "private identifiers"):
                runner.prepare_case(case, private_baseline, candidate_for(case))


if __name__ == "__main__":
    unittest.main()
