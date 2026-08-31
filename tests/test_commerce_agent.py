import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from connectors import commerce_agent as c


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

    def test_execute_requires_checkout_receipt(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True}}
        with patch.object(c, "_claim", return_value=action):
            with self.assertRaisesRegex(RuntimeError, "رقم طلب"):
                c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"ok":True})

    def test_execute_accepts_receipt_and_stores_non_sensitive_fields(self):
        action = {"plan":{"retailer":"R","title":"x","quantity":1,"url":"https://r","delivered_total_sar":"20.00","delivery_profile_ready":True,"payment_profile_ready":True}}
        fake_store = unittest.mock.MagicMock()
        fake_store.transaction.return_value = {"status":"EXECUTED","receipts":[{"order_id":"ORD-1"}]}
        with patch.object(c, "_claim", return_value=action), patch.object(c, "Store", return_value=fake_store):
            result = c.execute_order("SHOP-1", "CODE", checkout_call=lambda plan: {"order_id":"ORD-1"})
        self.assertEqual(result["status"], "EXECUTED")


if __name__ == "__main__":
    unittest.main()
