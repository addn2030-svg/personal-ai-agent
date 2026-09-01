import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import commerce_browser_checkout as browser
from connectors import commerce_browser_provider as provider


class CommerceBrowserCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(os.environ)
        os.environ["COMMERCE_BROWSER_ALLOWED_DOMAINS"] = "riyal1.com"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)

    def test_rejects_unapproved_domain(self):
        with self.assertRaisesRegex(RuntimeError, "UNSUPPORTED_RETAILER_DOMAIN"):
            browser.execute(
                {"url": "https://evil.example/p", "max_total_sar": "20.00"},
                {"address": "x", "phone": "y"},
                "PAYMENT_LINK",
                driver=object(),
            )

    def test_rejects_raw_card_profile(self):
        with self.assertRaisesRegex(RuntimeError, "PAYMENT_PROFILE_UNSUPPORTED"):
            browser.execute(
                {"url": "https://riyal1.com/products/x", "max_total_sar": "20.00"},
                {"address": "x", "phone": "y"},
                "4111111111111111",
                driver=object(),
            )

    def test_provider_rejects_raw_card_payload(self):
        os.environ["COMMERCE_BROWSER_PROVIDER_SECRET"] = "s"
        body = {
            "secret": "s",
            "action": "checkout",
            "idempotency_key": "k1",
            "order": {"url": "https://riyal1.com/products/x", "quantity": 1, "max_total_sar": "20.00"},
            "delivery": {"address": "a", "phone": "p"},
            "payment_profile": "PAYMENT_LINK",
            "card_number": "4111111111111111",
        }
        with self.assertRaisesRegex(ValueError, "RAW_CARD_DATA_FORBIDDEN"):
            provider.checkout_payload(body)

    def test_provider_rejects_order_above_pilot_cap_before_browser(self):
        os.environ["COMMERCE_BROWSER_PROVIDER_SECRET"] = "s"
        body = {
            "secret": "s",
            "action": "checkout",
            "idempotency_key": "too-large",
            "order": {"url": "https://riyal1.com/products/x", "quantity": 1, "max_total_sar": "376.00"},
            "delivery": {"address": "a", "phone": "p"},
            "payment_profile": "PAYMENT_LINK",
        }
        with patch("connectors.commerce_browser_provider.execute") as ex:
            with self.assertRaisesRegex(ValueError, "PILOT_ORDER_LIMIT_EXCEEDED"):
                provider.checkout_payload(body)
            ex.assert_not_called()

    def test_provider_daily_limit_blocks_second_order_before_browser(self):
        os.environ["COMMERCE_BROWSER_PROVIDER_SECRET"] = "s"
        body = {
            "secret": "s",
            "action": "checkout",
            "idempotency_key": "new-key",
            "order": {
                "retailer": "Riyal1",
                "title": "Tissues",
                "url": "https://riyal1.com/products/x",
                "quantity": 1,
                "max_total_sar": "100.00",
            },
            "delivery": {"address": "a", "phone": "p"},
            "payment_profile": "PAYMENT_LINK",
        }
        with tempfile.TemporaryDirectory() as td:
            provider.DATA_DIR = Path(td)
            provider.RECEIPTS = provider.DATA_DIR / "receipts.json"
            provider._save({
                "old-key": {
                    "ok": True,
                    "order_id": "ORD-OLD",
                    "total_sar": "300.00",
                    "executed_at": "2026-09-01T09:00:00+03:00",
                }
            })
            with patch.object(provider, "_pilot_day", return_value="2026-09-01"), patch("connectors.commerce_browser_provider.execute") as ex:
                with self.assertRaisesRegex(ValueError, "PILOT_DAILY_LIMIT_EXCEEDED"):
                    provider.checkout_payload(body)
                ex.assert_not_called()

    def test_provider_idempotency_reuses_receipt(self):
        os.environ["COMMERCE_BROWSER_PROVIDER_SECRET"] = "s"
        body = {
            "secret": "s",
            "action": "checkout",
            "idempotency_key": "same-key",
            "order": {
                "retailer": "Riyal1",
                "title": "Tissues",
                "url": "https://riyal1.com/products/x",
                "quantity": 1,
                "max_total_sar": "20.00",
            },
            "delivery": {"address": "a", "phone": "p"},
            "payment_profile": "PAYMENT_LINK",
        }
        with tempfile.TemporaryDirectory() as td:
            provider.DATA_DIR = Path(td)
            provider.RECEIPTS = provider.DATA_DIR / "receipts.json"
            with patch("connectors.commerce_browser_provider.execute") as ex, patch.object(provider, "_pilot_now_iso", return_value="2026-09-01T12:00:00+03:00"):
                ex.return_value = {
                    "order_id": "ORD-12345",
                    "status": "payment_required",
                    "total_sar": "20.00",
                    "payment_url": "https://riyal1.com/o/abc/inv",
                }
                first = provider.checkout_payload(body)
                second = provider.checkout_payload(body)
                self.assertEqual(first, second)
                self.assertEqual(ex.call_count, 1)
                self.assertEqual(first["order_id"], "ORD-12345")
                self.assertEqual(first["executed_at"], "2026-09-01T12:00:00+03:00")
                self.assertEqual(first["pilot_max_order_sar"], "375.00")
                self.assertEqual(first["pilot_max_daily_sar"], "375.00")


if __name__ == "__main__":
    unittest.main()
