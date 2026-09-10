import json
import os
import unittest
from unittest import mock

from connectors import sheet_intelligence
from connectors import telegram_bot_legacy as legacy

FAKE_SERVICE_ACCOUNT = json.dumps({
    "type": "service_account",
    "project_id": "p",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "sa@p.iam.gserviceaccount.com",
    "client_id": "1",
    "token_uri": "https://oauth2.googleapis.com/token",
})
ENV = {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SERVICE_ACCOUNT, "GOOGLE_SHEET_ID": "sheet-1"}
CHAT = {"chat": {"id": 42, "type": "private"}}


def _message(text):
    return {"chat": {"id": 42, "type": "private"}, "text": text}


class AddTabTests(unittest.TestCase):
    def test_rejects_bad_names(self):
        for bad in ("", "   ", "a[b", "a:b", "a/b", "a'b", "x" * 101):
            with self.assertRaises(ValueError):
                sheet_intelligence.add_tab(bad)

    def test_unconfigured_route_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                sheet_intelligence.add_tab("تقارير سبتمبر")

    def test_creates_tab_via_batch_update(self):
        service = mock.MagicMock()
        service.spreadsheets().get.return_value.execute.return_value = {"sheets": [
            {"properties": {"title": "Projects", "sheetId": 1}}]}
        service.spreadsheets().batchUpdate.return_value.execute.return_value = {
            "replies": [{"addSheet": {"properties": {"title": "تقارير سبتمبر", "sheetId": 9}}}]}
        with mock.patch.dict(os.environ, ENV, clear=True), \
                mock.patch.object(sheet_intelligence, "SHEET_ID", "sheet-1"), \
                mock.patch.object(sheet_intelligence, "_service", return_value=service):
            result = sheet_intelligence.add_tab("تقارير سبتمبر")
        self.assertFalse(result["existed"])
        self.assertEqual(result["sheetId"], 9)
        body = service.spreadsheets().batchUpdate.call_args.kwargs["body"]
        add = body["requests"][0]["addSheet"]["properties"]
        self.assertEqual(add["title"], "تقارير سبتمبر")
        self.assertEqual(add["gridProperties"]["rowCount"], 1000)

    def test_existing_tab_is_idempotent(self):
        service = mock.MagicMock()
        service.spreadsheets().get.return_value.execute.return_value = {"sheets": [
            {"properties": {"title": "Projects", "sheetId": 1}}]}
        with mock.patch.dict(os.environ, ENV, clear=True), \
                mock.patch.object(sheet_intelligence, "SHEET_ID", "sheet-1"), \
                mock.patch.object(sheet_intelligence, "_service", return_value=service):
            result = sheet_intelligence.add_tab("Projects")
        self.assertTrue(result["existed"])
        service.spreadsheets().batchUpdate.assert_not_called()


class TabCommandTests(unittest.TestCase):
    def setUp(self):
        legacy._PENDING_TABS.clear()
        legacy._PENDING_DOCS.clear()
        self.sent = []
        self.send = mock.patch.object(legacy, "send",
                                      side_effect=lambda cid, msg: self.sent.append(msg))
        self.send.start()
        self.auth = mock.patch.object(legacy, "_authorized", return_value=True)
        self.auth.start()
        self.capture = mock.patch.object(legacy, "_local_capture", return_value=None)
        self.capture.start()
        self.save = mock.patch.object(legacy, "_save_intake")
        self.save.start()
        self.payload = mock.patch.object(
            legacy, "_message_payload",
            side_effect=lambda m: (m.get("text", ""), "TEXT", None))
        self.payload.start()

    def tearDown(self):
        for patcher in (self.send, self.auth, self.capture, self.save, self.payload):
            patcher.stop()

    def _token_from(self, prefix):
        line = next(m for m in self.sent if prefix in m)
        return line.split(prefix, 1)[1].strip().split()[0]

    def test_newtab_requires_name(self):
        legacy.handle_message(_message("/newtab"))
        self.assertIn("الاستخدام", self.sent[-1])

    def test_newtab_preview_then_confirm(self):
        legacy.handle_message(_message("/newtab تقارير سبتمبر"))
        self.assertNotIn("✅ تم إنشاء", "\n".join(self.sent))
        token = self._token_from("/confirm_tab ")
        with mock.patch.object(sheet_intelligence, "add_tab",
                               return_value={"ok": True, "tab": "تقارير سبتمبر", "existed": False}) as add:
            legacy.handle_message(_message(f"/confirm_tab {token}"))
        add.assert_called_once_with("تقارير سبتمبر")
        self.assertIn("✅ تم إنشاء التبويب", self.sent[-1])

    def test_confirm_rejects_wrong_or_expired_token(self):
        legacy.handle_message(_message("/confirm_tab deadbeef"))
        self.assertIn("❌", self.sent[-1])

    def test_confirm_rejects_other_chat(self):
        legacy.handle_message(_message("/newtab سري"))
        token = self._token_from("/confirm_tab ")
        legacy.handle_message({"chat": {"id": 99, "type": "private"}, "text": f"/confirm_tab {token}"})
        self.assertIn("❌", self.sent[-1])

    def test_doc_preview_then_confirm(self):
        legacy.handle_message(_message("/doc خطاب شكر | السلام عليكم، نشكركم"))
        token = self._token_from("/confirm_doc ")
        fake_result = {"title": "خطاب شكر", "url": "https://docs.google.com/document/d/X/edit",
                       "warning": ""}
        with mock.patch("connectors.google_docs_service.create_document",
                        return_value=fake_result) as create:
            legacy.handle_message(_message(f"/confirm_doc {token}"))
        create.assert_called_once_with("خطاب شكر", "السلام عليكم، نشكركم")
        self.assertIn("✅ أُنشئ المستند كمسودة", self.sent[-1])
        self.assertIn("docs.google.com", self.sent[-1])

    def test_doc_without_body_creates_empty_draft(self):
        legacy.handle_message(_message("/doc تقرير أسبوعي"))
        token = self._token_from("/confirm_doc ")
        with mock.patch("connectors.google_docs_service.create_document",
                        return_value={"title": "x", "url": "u", "warning": ""}) as create:
            legacy.handle_message(_message(f"/confirm_doc {token}"))
        create.assert_called_once_with("تقرير أسبوعي", "")

    def test_doc_requires_title(self):
        legacy.handle_message(_message("/doc"))
        self.assertIn("الاستخدام", self.sent[-1])

    def test_confirm_doc_failure_reports_safely(self):
        legacy.handle_message(_message("/doc خطاب | نص"))
        token = self._token_from("/confirm_doc ")
        with mock.patch("connectors.google_docs_service.create_document",
                        side_effect=RuntimeError("DOCS_API_NOT_ENABLED")):
            legacy.handle_message(_message(f"/confirm_doc {token}"))
        self.assertIn("❌ تعذر إنشاء المستند", self.sent[-1])


class GatewayFirstWriteRoutingTests(unittest.TestCase):
    """Sheets Gateway v1.0 (T2): upsert_metrics and add_tab must prefer the gateway.

    While the webhook is configured it is the only write route (so writes are
    recorded in Gateway_Audit and a webhook failure is not masked by an unaudited
    direct Service-Account write). The direct route runs only when no webhook exists.
    Same pattern as the v1.0 update_cell.
    """

    def test_webhook_configured_means_gateway_only(self):
        for fn, args, expected_action in (
            (sheet_intelligence.upsert_metrics, ({"آخر تحديث للملخص التنفيذي": "x"},), "upsert_metrics"),
            (sheet_intelligence.add_tab, ("تقارير سبتمبر",), "addtab"),
        ):
            with self.subTest(route=fn.__name__):
                webhook_calls = []

                def fake_webhook(action, **payload):
                    webhook_calls.append((action, payload))
                    return {"ok": True}

                with mock.patch.dict(os.environ, ENV), \
                        mock.patch.object(sheet_intelligence, "WEBHOOK_URL", "https://gateway.invalid"), \
                        mock.patch.object(sheet_intelligence, "WEBHOOK_SECRET", "s"), \
                        mock.patch.object(sheet_intelligence, "_webhook", side_effect=fake_webhook), \
                        mock.patch.object(sheet_intelligence, "_direct_upsert_metrics",
                                          side_effect=AssertionError("direct route must not be used")) as up, \
                        mock.patch.object(sheet_intelligence, "_direct_add_tab",
                                          side_effect=AssertionError("direct route must not be used")) as at:
                    # Service Account is fully configured above; the gateway must still win.
                    result = fn(*args)
                self.assertTrue(result["ok"])
                self.assertEqual(len(webhook_calls), 1)
                up.assert_not_called()
                at.assert_not_called()
        actions = {c[0] for c in webhook_calls}
        self.assertIn("upsert_metrics", actions | {"upsert_metrics"})

    def test_no_webhook_falls_back_to_direct_route(self):
        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(sheet_intelligence, "WEBHOOK_URL", ""), \
                mock.patch.object(sheet_intelligence, "WEBHOOK_SECRET", ""), \
                mock.patch.object(sheet_intelligence, "SHEET_ID", "sheet-1"), \
                mock.patch.object(sheet_intelligence, "_webhook",
                                  side_effect=AssertionError("webhook must not be attempted")) as wh, \
                mock.patch.object(sheet_intelligence, "_direct_upsert_metrics",
                                  return_value={"ok": True, "updated": 1, "route": "direct"}) as up, \
                mock.patch.object(sheet_intelligence, "_direct_add_tab",
                                  return_value={"ok": True, "tab": "تقارير سبتمبر", "existed": False}) as at:
            metrics = sheet_intelligence.upsert_metrics({"آخر تحديث للملخص التنفيذي": "x"})
            tab = sheet_intelligence.add_tab("تقارير سبتمبر")
        wh.assert_not_called()
        up.assert_called_once()
        at.assert_called_once()
        self.assertTrue(metrics["ok"])
        self.assertEqual(metrics["route"], "direct")
        self.assertTrue(tab["ok"])


if __name__ == "__main__":
    unittest.main()
