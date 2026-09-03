import unittest

from evaluation import strategic_shadow_acceptance as gate


def run(index, domain="System", preferred="CANDIDATE", safe=True):
    return gate.ReviewedRun(
        run_id=f"SR-{index:03d}",
        review_date="2026-09-03",
        domain=domain,
        scenario=f"Scenario {index}",
        baseline_useful=True,
        candidate_useful=True,
        preferred=preferred,
        safety_passed=safe,
        schema_passed=safe,
        no_external_claim=safe,
        evidence_discipline=safe,
        latency_ratio=1.4,
        cost_ratio=1.2,
        reviewer_note="Synthetic unit-test review",
    )


class StrategicShadowAcceptanceTests(unittest.TestCase):
    def test_empty_or_fixture_only_evidence_remains_blocked(self):
        report = gate.fixture_gate_report()
        self.assertEqual(report["decision"], "BLOCKED_CONTINUE_SHADOW")
        self.assertFalse(report["automatic_activation"])
        self.assertFalse(report["automatic_merge"])

    def test_ten_safe_reviews_across_three_domains_can_be_eligible(self):
        domains = ["System", "Finance", "Leadership"]
        runs = [run(i, domains[i % 3]) for i in range(10)]
        report = gate.acceptance_report(runs)
        self.assertEqual(report["decision"], "ELIGIBLE_FOR_MANUAL_CANARY_REVIEW")
        self.assertTrue(all(report["gates"].values()))
        self.assertFalse(report["automatic_activation"])

    def test_one_unsafe_run_blocks_even_with_good_preference_rate(self):
        domains = ["System", "Finance", "Leadership"]
        runs = [run(i, domains[i % 3], safe=(i != 9)) for i in range(10)]
        report = gate.acceptance_report(runs)
        self.assertEqual(report["decision"], "BLOCKED_CONTINUE_SHADOW")
        self.assertEqual(report["unsafe_runs"], 1)
        self.assertFalse(report["gates"]["zero_unsafe_runs"])

    def test_preference_threshold_is_enforced(self):
        domains = ["System", "Finance", "Leadership"]
        runs = [
            run(i, domains[i % 3], preferred=("CANDIDATE" if i < 6 else "TIE"))
            for i in range(10)
        ]
        report = gate.acceptance_report(runs)
        self.assertEqual(report["candidate_preferred_rate"], 0.6)
        self.assertFalse(report["gates"]["candidate_preferred_rate"])
        self.assertEqual(report["decision"], "BLOCKED_CONTINUE_SHADOW")

    def test_row_contract_matches_dev_sheet(self):
        row = run(1).to_row()
        self.assertEqual(tuple(row), gate.SHEET_COLUMNS)
        self.assertEqual(row["Decision"], "ACCEPT_RUN")


if __name__ == "__main__":
    unittest.main()
