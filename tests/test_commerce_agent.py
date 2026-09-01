import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from connectors import commerce_agent as c
from connectors import commerce_sandbox


class CommerceAgentTests(unittest.TestCase):
    def test_rank_prefers_known_delivered_total(self):
        a = c.make_offer(retailer="A", title="10 boxes", pack_count=10, item_count_each=180, price_sar=8, shipping_sar=12, url="https://a", in_stock=True, shipping_verified=True)
        b = c.make_offer(retailer="B", title="10 boxes", pack_count=10, item_count_each=180, price_sar=14.75, shipping_sar=None, url="https://b", in_stock=True)
        self.assertEqual(c.best_offer([b, a]).retailer, "A")
        self.assertEqual(a.total_sar, Decimal("20.00"))

    def test_wrong_pack_or_out_of_stock_is_excluded(self):
        good = c.make_offer(retailer="A", title="good", pack_count=10, item_count_each=180, price_sar=20, shipping_sar=0, url="https://a", in_stock=True)
        wrong = c.make_offer(retailer="B", title="wrong", pack_count=5, item_count_each=180, price_sar=1, shipping_sar=0, url="https://b", in_stock=True)
        out = c.make_offer(retailer="C", title="out", pack_count=10, item_count_each=180, price_sar=1, shipping_sar=0, url="https://c", in_stock=False)
        self.assertEqual(c.rank_offers([wrong, out, good]), [good])

    def test_private_delivery_data_is_redacted(self):
        text = "الجوال +966545684917، حي مثال، طريق الاختبار، عمارة 3، شقة 12"
        cleaned = c.redact_private(text)
        self.assertNotIn("545684917", cleaned)
        self.assertIn("[PHONE_REDACTED]", cleaned)
        self.assertNotIn("طريق الاختبار", cleaned)

    def test_natural_order_query_excludes_address_and_phone(self):
        raw = "ابدأ واطلب كيس منديل فئة ١٠ حبات بأفضل سعر، ارسل الى العنوان: حي مثال، طريق الاختبار، عمارة 3، شقة 12، جوال +966545684917"
        query = c.natural_order_product_query(raw)
        self.assertIn("كيس منديل", query)
        self.assertIn("١٠", query)
        self.assertNotIn("العنوان", query)
        self.assertNotIn("حي مثال", query)
        self.assertNotIn("طريق الاختبار", query)
        self.assertNotIn("545684917", query)
        self.assertNotIn("أفضل سعر", query)

    def test_preview_never_persists_address_or_phone(self):
        offer = c.make_offer(retailer="R", title="10 boxes", pack_count=10, item_count_each=180, price_sar=8, shipping_sar=12, url="https://r", in_stock=True, shipping_verified=True)
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.side_effect = lambda fn, *a, **k: fn({"action_queue": []})[1]
        with patch.object(c, "Store", return_value=fake_store), patch.dict(os.environ, {"COMMERCE_DELIVERY_ADDRESS":"secret address","COMMERCE_DELIVERY_PHONE":"0500000000","COMMERCE_PAYMENT_PROFILE":"PAYMENT_LINK"}, clear=False):
            row = c.create_order_preview(offer)
        payload = str(row)
        self.assertNotIn("secret address", payload)
        self.assertNotIn("0500000000", payload)
        self.assertEqual(row["plan"]["delivery_profile_ref"], "env:commerce_delivery_profile")
        self.assertEqual(row["plan"]["idempotency_key"], row["action_id"])
        self.assertTrue(row["plan"]["pilot_mode"])
        self.assertEqual(row["plan"]["pilot_max_order_sar"], "375.00")
        self.assertEqual(row["plan"]["pilot_max_daily_sar"], "375.00")

    def test_preview_rejects_order_above_100_usd_equivalent(self):
        offer = c.make_offer(retailer="R", title="too much", pack_count=10, item_count_each=180, price_sar=376, shipping_sar=0, url="https://r", in_stock=True)
        with self.assertRaisesRegex(RuntimeError, "PILOT_ORDER_LIMIT_EXCEEDED"):
            c.create_order_preview(offer)

    def test_preview_allows_exact_375_sar_ceiling(self):
        offer = c.make_offer(retailer="R", title="exact cap", pack_count=10, item_count_each=180, price_sar=375, shipping_sar=0, url="https://r", in_stock=True)
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.side_effect = lambda fn, *a, **k: fn({"action_queue": []})[1]
        with patch.object(c, "Store", return_value=fake_store):
            row = c.create_order_preview(offer)
        self.assertEqual(row["plan"]["delivered_total_sar"], "375.00")

    def test_daily_limit_rejects_total_above_375_sar(self):
        state = {
            "action_queue": [
                {
                    "action_id": "SHOP-OLD",
                    "type": "COMMERCE_ORDER",
                    "status": "EXECUTED",
                    "receipts": [{"total_sar": "300.00", "executed_at": "2026-09-01T09:00:00+03:00"}],
                },
                {
                    "action_id": "SHOP-NEW",
                    "type": "COMMERCE_ORDER",
                    "status": "PENDING_APPROVAL",
                    "approval_code": "CODE",
                    "plan": {"delivered_total_sar": "100.00"},
                    "receipts": [],
                },
            ]
        }
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.side_effect = lambda fn, *a, **k: fn(state)[1]
        with patch.object(c, "Store", return_value=fake_store), patch.object(c, "_pilot_day", return_value="2026-09-01"):
            with self.assertRaisesRegex(RuntimeError, "PILOT_DAILY_LIMIT_EXCEEDED"):
                c._claim("SHOP-NEW", "CODE")

    def test_daily_limit_counts_inflight_reservation(self):
        state = {
            "action_queue": [
                {
                    "action_id": "SHOP-INFLIGHT",
                    "type": "COMMERCE_ORDER",
                    "status": "EXECUTING",
                    "pilot_reserved_day": "2026-09-01",
                    "pilot_reserved_total_sar": "300.00",
                    "plan": {"delivered_total_sar": "300.00"},
                    "receipts": [],
                },
                {
                    "action_id": "SHOP-NEW",
                    "type": "COMMERCE_ORDER",
                    "status": "PENDING_APPROVAL",
                    "approval_code": "CODE",
                    "plan": {"delivered_total_sar": "100.00"},
                    "receipts": [],
                },
            ]
        }
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.side_effect = lambda fn, *a, **k: fn(state)[1]
        with patch.object(c, "Store", return_value=fake_store), patch.object(c, "_pilot_day", return_value="2026-09-01"):
            with self.assertRaisesRegex(RuntimeError, "PILOT_DAILY_LIMIT_EXCEEDED"):
                c._claim("SHOP-NEW", "CODE")

    def test_shared_secret_marks_checkout_configured(self):
        with patch.dict(os.environ, {"COMMERCE_CHECKOUT_WEBHOOK_URL":"https://checkout.example/checkout", "COMMERCE_SHARED_SECRET":"shared", "COMMERCE_CHECKOUT_SECRET":""}, clear=False):
            self.assertTrue(c.checkout_configured())

    def test_execute_requires_checkout_receipt(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True,"idempotency_key":"SHOP-1"}}
        with patch.object(c, "_claim", return_value=action):
            with self.assertRaisesRegex(RuntimeError, "رقم طلب"):
                c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"ok":True})

    def test_execute_rejects_price_above_approved_ceiling(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True,"idempotency_key":"SHOP-1"}}
        with patch.object(c, "_claim", return_value=action):
            with self.assertRaisesRegex(RuntimeError, "PRICE_CEILING_VIOLATION"):
                c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"order_id":"ORD-1","total_sar":"21.00"})

    def test_payment_link_receipt_keeps_only_safe_https_url(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True,"idempotency_key":"SHOP-1"}}
        fake_store = unittest.mock.MagicMock()
        def transact(fn, *a, **k):
            state = {"action_queue":[{"action_id":"SHOP-1"}]}
            return fn(state)[1]
        fake_store.transaction.side_effect = transact
        with patch.object(c, "_claim", return_value=action), patch.object(c, "Store", return_value=fake_store), patch.object(c, "_pilot_now_iso", return_value="2026-09-01T12:00:00+03:00"):
            result = c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"order_id":"ORD-1","total_sar":"20.00","status":"payment_required","payment_url":"https://pay.example/abc"})
        receipt = result["receipts"][0]
        self.assertEqual(receipt["status"], "payment_required")
        self.assertEqual(receipt["payment_url"], "https://pay.example/abc")
        self.assertEqual(receipt["executed_at"], "2026-09-01T12:00:00+03:00")

    def test_sandbox_is_explicit_and_never_real_purchase(self):
        with patch.dict(os.environ, {
            "COMMERCE_DELIVERY_ADDRESS":"must-not-be-read",
            "COMMERCE_DELIVERY_PHONE":"0500000000",
            "COMMERCE_PAYMENT_PROFILE":"PAYMENT_LINK",
        }, clear=False):
            result = commerce_sandbox.run_smoke_test()
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "SANDBOX")
        self.assertFalse(result["real_purchase"])
        self.assertFalse(result["private_profile_used"])
        self.assertTrue(result["order_id"].startswith("SANDBOX-"))
        rendered = commerce_sandbox.render_smoke_test(result)
        self.assertIn("لا يوجد شراء حقيقي", rendered)
        self.assertNotIn("0500000000", rendered)
        self.assertNotIn("must-not-be-read", rendered)


if __name__ == "__main__":
    unittest.main()
