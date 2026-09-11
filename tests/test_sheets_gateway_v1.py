# -*- coding: utf-8 -*-

import unittest
from unittest import mock

from connectors import sheet_intelligence as si


class SheetsGatewayV1Tests(unittest.TestCase):
    def test_update_records_approval_then_updates_with_same_id(self):
        calls = []

        def fake_webhook(action, **kw):
            calls.append((action, kw))
            return {"ok": True, "before": "10%", "after": "20%"} if action == "update" else {"ok": True}

        with mock.patch.object(si, "metadata", return_value=[{"title": "Projects"}]), \
             mock.patch.object(si, "_webhook_ready", return_value=True), \
             mock.patch.object(si, "_direct_ready", return_value=True), \
             mock.patch.object(si, "APPROVAL_SECRET", "appr"), \
             mock.patch.object(si, "_webhook", side_effect=fake_webhook), \
             mock.patch.object(si, "_direct_update_cell") as direct:
            result = si.update_cell("Projects", "C5", "20%", approved_by="telegram:1", approval_ref="ACT-1")

        direct.assert_not_called()
        self.assertEqual([c[0] for c in calls], ["record_approval", "update"])
        self.assertEqual(calls[0][1]["approval_id"], calls[1][1]["approval_id"])
        self.assertTrue(calls[0][1]["approval_id"].startswith("AP-ACT-1-"))
        self.assertNotIn("approved", calls[1][1])
        self.assertEqual(result["route"], "webhook")

    def test_update_fails_closed_without_approval_secret(self):
        with mock.patch.object(si, "metadata", return_value=[{"title": "Projects"}]), \
             mock.patch.object(si, "_webhook_ready", return_value=True), \
             mock.patch.object(si, "APPROVAL_SECRET", ""), \
             mock.patch.object(si, "_webhook") as hook:
            with self.assertRaises(RuntimeError):
                si.update_cell("Projects", "C5", "x")
        hook.assert_not_called()

    def test_formula_injection_is_neutralised(self):
        self.assertEqual(si._safe_cell('=IMPORTXML("http://x","//a")'), '\'=IMPORTXML("http://x","//a")')
        self.assertEqual(si._safe_cell("@evil"), "'@evil")
        self.assertEqual(si._safe_cell("-5"), "-5")
        self.assertEqual(si._safe_cell("20%"), "20%")
        self.assertEqual(si._safe_cell(7), 7)

    def test_upsert_metrics_prefers_webhook_when_direct_is_also_ready(self):
        with mock.patch.object(si, "_webhook_ready", return_value=True), \
             mock.patch.object(si, "_direct_ready", return_value=True), \
             mock.patch.object(si, "_webhook", return_value={"ok": True, "updated": 1}) as hook, \
             mock.patch.object(si, "_direct_upsert_metrics") as direct:
            result = si.upsert_metrics({"ملخص المدير الشخصي": "مرور gateway"})

        direct.assert_not_called()
        hook.assert_called_once_with(
            "upsert_metrics",
            sheet="Executive_Brief",
            metrics={"ملخص المدير الشخصي": "مرور gateway"},
        )
        self.assertEqual(result["updated"], 1)

    def test_add_tab_prefers_webhook_when_direct_is_also_ready(self):
        with mock.patch.object(si, "_webhook_ready", return_value=True), \
             mock.patch.object(si, "_direct_ready", return_value=True), \
             mock.patch.object(si, "_webhook", return_value={"ok": True, "tab": "DEV_Verify"}) as hook, \
             mock.patch.object(si, "_direct_add_tab") as direct:
            result = si.add_tab("DEV_Verify", rows=12, cols=7)

        direct.assert_not_called()
        hook.assert_called_once_with("addtab", title="DEV_Verify", rows=12, cols=7)
        self.assertEqual(result["tab"], "DEV_Verify")


if __name__ == "__main__":
    unittest.main()
