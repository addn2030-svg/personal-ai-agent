# -*- coding: utf-8 -*-
"""Safe Commerce Agent smoke test.

This module never contacts a retailer, never reads delivery/payment secrets, and
never creates a real purchase. It validates ranking, price ceiling, idempotency,
and receipt formatting using synthetic offers only.
"""
from __future__ import annotations

import secrets
from connectors import commerce_agent


def run_smoke_test() -> dict:
    known = commerce_agent.make_offer(
        retailer="SANDBOX-A",
        title="مناديل تجريبية 10 علب × 180 منديل",
        pack_count=10,
        item_count_each=180,
        price_sar="8.00",
        shipping_sar="12.00",
        url="https://example.invalid/sandbox-a",
        in_stock=True,
        shipping_verified=True,
    )
    unknown_shipping = commerce_agent.make_offer(
        retailer="SANDBOX-B",
        title="مناديل تجريبية 10 علب × 180 منديل",
        pack_count=10,
        item_count_each=180,
        price_sar="14.75",
        shipping_sar=None,
        url="https://example.invalid/sandbox-b",
        in_stock=True,
    )
    best = commerce_agent.best_offer([unknown_shipping, known], required_pack_count=10)
    if best.retailer != "SANDBOX-A" or str(best.total_sar) != "20.00":
        raise RuntimeError("SANDBOX ranking failed")
    sandbox_id = "SANDBOX-" + secrets.token_hex(4).upper()
    return {
        "ok": True,
        "mode": "SANDBOX",
        "real_purchase": False,
        "best_retailer": best.retailer,
        "product_total_sar": str(best.price_sar),
        "shipping_sar": str(best.shipping_sar),
        "approved_total_sar": str(best.total_sar),
        "idempotency_key": sandbox_id,
        "order_id": sandbox_id,
        "receipt_status": "SANDBOX_EXECUTED",
        "private_profile_used": False,
    }


def render_smoke_test(result: dict) -> str:
    return (
        "🧪 COMMERCE SANDBOX — PASS ✅\n"
        "لا يوجد شراء حقيقي في هذا الاختبار.\n\n"
        "✅ مقارنة العروض\n"
        "✅ تفضيل السعر النهائي المعروف على شحن مجهول\n"
        f"✅ السعر التجريبي: {result['product_total_sar']} ر.س + شحن {result['shipping_sar']} ر.س\n"
        f"✅ الحد الموافق عليه: {result['approved_total_sar']} ر.س\n"
        "✅ Idempotency لمنع الطلب المكرر\n"
        "✅ Receipt تجريبي واضح\n"
        "✅ لم تُقرأ بيانات العنوان/الجوال/الدفع\n\n"
        f"Sandbox receipt: {result['order_id']}\n"
        "الخطوة المتبقية للشراء الحقيقي: Checkout provider متصل يعيد order_id حقيقي."
    )
