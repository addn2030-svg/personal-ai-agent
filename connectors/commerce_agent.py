# -*- coding: utf-8 -*-
"""Commerce Agent v0.1 — deal ranking + approval-gated checkout adapter.

Safety invariants:
- personal delivery data is never persisted in StateStore/Sheets/log output;
- offers must carry verified price + pack count; unknown shipping is not treated as cheapest;
- purchase requires explicit approved action OR an already-approved policy supplied by caller;
- checkout success requires a provider receipt/order id; otherwise status is not EXECUTED.
"""
from __future__ import annotations

import hashlib, json, os, re, secrets
from dataclasses import dataclass, asdict
from decimal import Decimal

from engine.store import Store

_PHONE_RE = re.compile(r"(?:\+?966|0)?5\d{8}")
_ADDRESS_HINT_RE = re.compile(r"(?:حي|شارع|طريق|عمارة|شقة|منزل|building|apartment|address)\s*[^,،\n]{2,80}", re.I)


def redact_private(text: str) -> str:
    value = _PHONE_RE.sub("[PHONE_REDACTED]", str(text or ""))
    return _ADDRESS_HINT_RE.sub("[ADDRESS_REDACTED]", value)


@dataclass(frozen=True)
class Offer:
    retailer: str
    title: str
    pack_count: int
    item_count_each: int | None
    price_sar: Decimal
    shipping_sar: Decimal | None
    url: str
    in_stock: bool
    price_verified: bool = True
    shipping_verified: bool = False

    @property
    def total_sar(self) -> Decimal | None:
        if self.shipping_sar is None:
            return None
        return self.price_sar + self.shipping_sar


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def make_offer(**kwargs) -> Offer:
    kwargs["price_sar"] = _d(kwargs["price_sar"])
    if kwargs.get("shipping_sar") is not None:
        kwargs["shipping_sar"] = _d(kwargs["shipping_sar"])
    return Offer(**kwargs)


def rank_offers(offers: list[Offer], required_pack_count: int = 10) -> list[Offer]:
    """Rank only comparable offers. Known delivered total outranks unknown shipping."""
    valid = [o for o in offers if o.in_stock and o.price_verified and o.pack_count == required_pack_count]
    return sorted(
        valid,
        key=lambda o: (
            o.total_sar is None,
            o.total_sar if o.total_sar is not None else o.price_sar,
            -int(o.item_count_each or 0),
            o.retailer.lower(),
        ),
    )


def best_offer(offers: list[Offer], required_pack_count: int = 10) -> Offer:
    ranked = rank_offers(offers, required_pack_count)
    if not ranked:
        raise ValueError("NEEDS_INPUT: لا يوجد عرض موثّق ومتوفر يطابق العدد المطلوب.")
    return ranked[0]


def delivery_profile_status() -> dict:
    # Values are intentionally never returned.
    return {
        "address_configured": bool(os.environ.get("COMMERCE_DELIVERY_ADDRESS", "").strip()),
        "phone_configured": bool(os.environ.get("COMMERCE_DELIVERY_PHONE", "").strip()),
        "payment_profile_configured": bool(os.environ.get("COMMERCE_PAYMENT_PROFILE", "").strip()),
    }


def checkout_configured() -> bool:
    return bool(os.environ.get("COMMERCE_CHECKOUT_WEBHOOK_URL", "").strip() and os.environ.get("COMMERCE_CHECKOUT_SECRET", "").strip())


def create_order_preview(offer: Offer, quantity: int = 1, *, source_ref: str = "") -> dict:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    total = offer.total_sar
    if total is None:
        raise ValueError("NEEDS_INPUT: تكلفة الشحن غير مؤكدة؛ لا يمكن وصف العرض بأنه أفضل سعر نهائي.")
    profile = delivery_profile_status()
    action_id = "SHOP-" + secrets.token_hex(4).upper()
    content = {
        "retailer": offer.retailer,
        "title": offer.title,
        "pack_count": offer.pack_count,
        "item_count_each": offer.item_count_each,
        "unit_offer_price_sar": str(offer.price_sar),
        "shipping_sar": str(offer.shipping_sar),
        "delivered_total_sar": str(total * quantity),
        "url": offer.url,
        "quantity": quantity,
        "delivery_profile_ref": "env:commerce_delivery_profile",
        "delivery_profile_ready": profile["address_configured"] and profile["phone_configured"],
        "payment_profile_ready": profile["payment_profile_configured"],
        "source_ref": source_ref,
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    row = {
        "action_id": action_id,
        "type": "COMMERCE_ORDER",
        "status": "PENDING_APPROVAL",
        "approval_code": digest[:10].upper(),
        "content_hash": digest,
        "plan": content,
        "receipts": [],
    }
    def add(state):
        state["action_queue"].append(row)
        return True, row
    return Store().transaction(add, "commerce_order_preview", action_id=action_id)


def render_preview(row: dict) -> str:
    p = row["plan"]
    profile_line = "✅ ملف التوصيل جاهز" if p.get("delivery_profile_ready") else "⚠️ ملف التوصيل غير مضبوط في البيئة الآمنة"
    payment_line = "✅ ملف الدفع الآمن مضبوط" if p.get("payment_profile_ready") else "⚠️ ملف الدفع غير مضبوط"
    return (
        "🛒 ORDER PREVIEW\n"
        f"المتجر: {p['retailer']}\n"
        f"المنتج: {p['title']}\n"
        f"الكمية: {p['quantity']}\n"
        f"السعر: {p['unit_offer_price_sar']} ر.س\n"
        f"الشحن: {p['shipping_sar']} ر.س\n"
        f"الإجمالي المؤكد: {p['delivered_total_sar']} ر.س\n"
        f"{profile_line}\n{payment_line}\n\n"
        "لم يتم الشراء بعد.\n"
        f"للموافقة: /approve_order {row['action_id']} {row['approval_code']}"
    )


def _claim(action_id: str, code: str) -> dict:
    def claim(state):
        row = next((x for x in state["action_queue"] if x.get("action_id") == action_id), None)
        if not row or row.get("type") != "COMMERCE_ORDER":
            raise ValueError("لا يوجد طلب شراء بهذا المعرّف.")
        if row.get("status") != "PENDING_APPROVAL":
            raise ValueError("الطلب ليس بانتظار الموافقة.")
        if str(row.get("approval_code", "")).upper() != str(code or "").upper():
            raise ValueError("رمز الموافقة غير مطابق.")
        row["status"] = "EXECUTING"
        return True, row
    return Store().transaction(claim, "commerce_order_claim", action_id=action_id)


def execute_order(action_id: str, code: str, *, checkout_call=None) -> dict:
    row = _claim(action_id, code)
    p = row["plan"]
    if not p.get("delivery_profile_ready"):
        raise RuntimeError("NEEDS_INPUT: ملف التوصيل الآمن غير مضبوط في بيئة التشغيل.")
    if not p.get("payment_profile_ready"):
        raise RuntimeError("NEEDS_INPUT: ملف الدفع الآمن غير مضبوط في بيئة التشغيل.")
    if checkout_call is None:
        if not checkout_configured():
            raise RuntimeError("CHECKOUT_CONNECTOR_REQUIRED: الطلب جاهز وموافق عليه لكن لا يوجد Checkout connector متصل.")
        from connectors.commerce_checkout import checkout as checkout_call
    receipt = checkout_call(p)
    order_id = str((receipt or {}).get("order_id") or (receipt or {}).get("id") or "").strip()
    if not order_id:
        raise RuntimeError("Checkout لم يُرجع رقم طلب؛ لا أعتبر الشراء منفذًا.")
    clean = {"order_id": order_id, "retailer": p["retailer"], "total_sar": p["delivered_total_sar"], "status": "EXECUTED"}
    def finish(state):
        target = next(x for x in state["action_queue"] if x.get("action_id") == action_id)
        target["status"] = "EXECUTED"
        target["receipts"] = [clean]
        return True, target
    return Store().transaction(finish, "commerce_order_executed", action_id=action_id, order_id=order_id)
