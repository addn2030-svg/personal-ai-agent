# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from unittest import mock

from connectors import brief_discovery
from connectors import executive_signals


class ExecutiveSignalsTests(unittest.TestCase):
    def test_college_arrival_rule_is_detected_without_task_keyword(self):
        text = "الذهاب: الوصول للكلية قبل 06:45؛ يحدد الانطلاق حسب مدة الطريق."
        rows = executive_signals.detect_signals(
            text,
            source_ref="telegram:123",
            evidence_status="USER_INPUT",
        )
        self.assertEqual(len(rows), 1)
        signal = rows[0]
        self.assertIn("LOGISTICS_RULE", signal["categories"])
        self.assertIn("HARD_CONSTRAINT", signal["categories"])
        self.assertEqual(signal["logistics"]["arrival_target"], "06:45")
        self.assertTrue(signal["logistics"]["requires_live_route_duration"])
        self.assertEqual(
            signal["logistics"]["departure_rule"],
            "departure_time = 06:45 - live_route_duration",
        )

    def test_arrival_rule_calculates_departure_when_duration_is_in_evidence(self):
        rows = executive_signals.detect_signals(
            "الوصول للكلية قبل 06:45، مدة الطريق 35 دقيقة"
        )
        logistics = rows[0]["logistics"]
        self.assertEqual(logistics["travel_minutes"], 35)
        self.assertEqual(logistics["departure_time"], "06:10")
        self.assertFalse(logistics["requires_live_route_duration"])

    def test_departure_calculation_uses_only_confirmed_route_duration(self):
        result = executive_signals.calculate_departure("06:45", 35)
        self.assertEqual(result["time"], "06:10")
        self.assertEqual(result["day_offset"], 0)
        self.assertEqual(result["travel_minutes"], 35)

    def test_departure_can_cross_previous_day(self):
        result = executive_signals.calculate_departure("00:20", 45)
        self.assertEqual(result["time"], "23:35")
        self.assertEqual(result["day_offset"], -1)

    def test_financial_boundary_is_executive_signal(self):
        rows = executive_signals.detect_signals("الحد المالي للشراء 500 ريال ولا يتجاوزه الوكيل")
        self.assertEqual(len(rows), 1)
        self.assertIn("FINANCIAL_BOUNDARY", rows[0]["categories"])

    def test_generic_chat_is_not_promoted(self):
        self.assertEqual(executive_signals.detect_signals("كيف حالك اليوم؟"), [])

    def test_private_clinical_input_is_excluded(self):
        self.assertEqual(
            executive_signals.detect_signals("مريض لديه تشخيص ويجب الوصول قبل 06:45"),
            [],
        )

    def test_sheet_discovery_includes_non_task_signal(self):
        data = {
            "Family_Logistics": [
                ["البند", "التفاصيل"],
                ["الكلية", "الوصول للكلية قبل 06:45 والانطلاق حسب مدة الطريق"],
            ]
        }
        with mock.patch.object(brief_discovery, "load_previous", return_value={"rows": {}, "generated_at": ""}):
            report = brief_discovery.discover(data, persist=False)
        self.assertEqual(report["stats"]["logistics_rules"], 1)
        self.assertTrue(report["executive_signals"])
        self.assertEqual(report["executive_signals"][0]["sheet"], "Family_Logistics")
        self.assertEqual(report["executive_signals"][0]["row"], 2)

    def test_state_scan_preserves_user_input_status(self):
        fake_state = {
            "fact_registry": [],
            "unified_inbox": [
                {
                    "id": "IN-1",
                    "source": "TELEGRAM",
                    "source_ref": "telegram:77",
                    "content": "الوصول للكلية قبل 06:45 والانطلاق حسب مدة الطريق",
                    "sensitive": False,
                }
            ],
        }

        class FakeStore:
            def rows_all(self):
                return fake_state

        with mock.patch.object(executive_signals, "Store", return_value=FakeStore()):
            rows = executive_signals.state_signals()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence_status"], "USER_INPUT")
        self.assertEqual(rows[0]["source_ref"], "telegram:77")


if __name__ == "__main__":
    unittest.main()
