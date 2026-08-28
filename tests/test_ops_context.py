import unittest
from unittest.mock import patch

from connectors import bedrock_team
from connectors import lean_missions as lean
from connectors import ops_context as ops
from connectors import sheet_intelligence


def br(text="DECISION", model="claude"):
    return bedrock_team.BedrockTeamResult(
        text=text,
        model=model,
        usage={"inputTokens": 10, "outputTokens": 5},
        latency_ms=1,
    )


class OpsContextTests(unittest.TestCase):
    def test_context_is_only_triggered_for_operational_time_queries(self):
        self.assertTrue(ops.needs_ops_context("Give me three priorities for tomorrow"))
        self.assertTrue(ops.needs_ops_context("ما هي أولويات غدا؟"))
        self.assertFalse(ops.needs_ops_context("Explain the difference between two strategies"))

    def test_context_is_bounded_and_reports_sources(self):
        with patch.object(ops, "_calendar_lines", return_value=["CAL " + "A" * 500]), patch.object(
            ops, "_sheet_lines", return_value=["SHEET " + "B" * 500]
        ):
            packet = ops.build_ops_context("priorities tomorrow", limit_chars=500)
        self.assertLessEqual(len(packet.text), 500)
        self.assertIn("OPS_CONTEXT_TRUNCATED", packet.text)
        self.assertEqual(packet.sources, ("calendar", "sheets"))

    def test_sheet_context_skips_clinical_or_identifier_rows(self):
        snapshot = {
            "Projects": [
                ["Project", "Status"],
                ["Automation", "Pending"],
                ["Patient Ahmed", "MRN 12345"],
            ]
        }
        with patch.object(sheet_intelligence, "configured", return_value=True), patch.object(
            sheet_intelligence, "snapshot", return_value=snapshot
        ):
            lines = ops._sheet_lines()
        joined = "\n".join(lines)
        self.assertIn("Automation", joined)
        self.assertNotIn("Patient Ahmed", joined)
        self.assertNotIn("12345", joined)

    def test_simple_priority_mission_stays_one_model_call_with_ops_capsule(self):
        packet = ops.OpsContextPacket(
            text="CAL 2026-08-29 09:00 | Team meeting\nSHEET Projects r2 | Agent | Pending",
            sources=("calendar", "sheets"),
        )
        with patch.object(ops, "build_ops_context", return_value=packet), patch.object(
            lean.bedrock_team, "manager", return_value=br()
        ) as manager, patch.object(lean.bedrock_team, "lean_specialist") as specialist:
            result = ops.mission(1, "Give me three priorities for tomorrow")

        self.assertIn("Calls: 1", result)
        self.assertIn("Context: ops-mini | sources=calendar+sheets", result)
        specialist.assert_not_called()
        manager.assert_called_once()
        prompt = manager.call_args.args[0]
        self.assertIn("OPS_CONTEXT_CAPSULE", prompt)
        self.assertIn("Team meeting", prompt)


if __name__ == "__main__":
    unittest.main()
