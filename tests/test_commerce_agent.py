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
        with patch.object(c, "Store", return_value=fake_store), patch.dict(os.environ, {"COMMERCE_DELIVERY_ADDRESS":"secret address","COMMERCE_DELIVERY_PHONE":"0500000000","COMMERCE_PAYMENT_PROFILE":"vault:1"}, clear=False):
            row = c.create_order_preview(offer)
        payload = str(row)
        self.assertNotIn("secret address", payload)
        self.assertNotIn("0500000000", payload)
        self.assertEqual(row["plan"]["delivery_profile_ref"], "env:commerce_delivery_profile")
        self.assertEqual(row["plan"]["idempotency_key"], row["action_id"])

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

    def test_execute_accepts_receipt_and_stores_non_sensitive_fields(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True,"idempotency_key":"SHOP-1"}}
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.return_value = {"status":"EXECUTED","receipts":[{"order_id":"ORD-1"}]}
        with patch.object(c, "_claim", return_value=action), patch.object(c, "Store", return_value=fake_store):
            result = c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"order_id":"ORD-1","total_sar":"20.00"})
        self.assertEqual(result["status"], "EXECUTED")

    def test_sandbox_is_explicit_and_never_real_purchase(self):
        with patch.dict(os.environ, {
            "COMMERCE_DELIVERY_ADDRESS":"must-not-be-read",
            "COMMERCE_DELIVERY_PHONE":"0500000000",
            "COMMERCE_PAYMENT_PROFILE":"vault:real",
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
