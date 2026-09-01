# -*- coding: utf-8 -*-
"""Commerce Agent v0.5 — deal ranking + approval-gated checkout adapter.

Safety invariants:
- personal delivery data is never persisted in StateStore/Sheets/log output;
- personal delivery data is stripped before any product search query;
- offers must carry verified price + pack count; unknown shipping is not treated as cheapest;
- purchase requires explicit approval;
- every approved order carries a stable idempotency key to prevent duplicate purchase;
- checkout success requires a concrete provider order id;
- the provider must not exceed the approved delivered-total ceiling;
- pilot purchases are hard-capped at 375 SAR per order and 375 SAR total per Riyadh day.
"""
from __future__ import annotations

import hashlib, json, os, re, secrets
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from engine.store import Store

_PHONE_RE = re.compile(r"(?:\+?966|0)?5\d{8}")
_ADDRESS_HINT_RE = re.compile(r"(?:حي|شارع|طريق|عمارة|شقة|منزل|building|apartment|address)\s*[^,،\n]{2,80}", re.I)
_PRIVATE_TAIL_RE = re.compile(r"(?:،|,)?\s*(?:أرسل|ارسل)\s+(?:إلى|الى)\s+العنوان|(?:،|,)?\s*(?:العنوان|الجوال|جوال|الهاتف|هاتف)\s*[:：]", re.I)
_ORDER_START_RE = re.compile(r"(?:^|\s)(?:اطلب|أطلب|اشتري|اشترِ)\s+", re.I)
_PRICE_WORDS_RE = re.compile(r"\s*(?:ب|في)?\s*(?:أفضل|افضل)\s+سعر(?:\s+نهائي)?\s*", re.I)

# Approved pilot ceiling: USD 100 at the SAR 3.75/USD peg.
# These are code-level hard limits, not environment variables, so a runtime typo
# cannot silently raise the approved financial exposure.
PILOT_MAX_ORDER_SAR = Decimal("375.00")
PILOT_MAX_DAILY_SAR = Decimal("375.00")
_PILOT_TZ = ZoneInfo("Asia/Riyadh")


def _pilot_now() -> datetime:
    return datetime.now(_PILOT_TZ)


def _pilot_now_iso() -> str:
    return _pilot_now().isoformat(timespec="seconds")


def _pilot_day() -> str:
    return _pilot_now().date().isoformat()


def _timestamp_day(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(_PILOT_TZ).date().isoformat()
    except Exception as exc:
        raise RuntimeError("PILOT_DAILY_LEDGER_INCOMPLETE: executed commerce receipt lacks a valid timestamp") from exc


def _pilot_exposure_for_day(state: dict, day: str) -> Decimal:
    """Return executed + in-flight Commerce exposure for one Riyadh day.

    EXECUTING reservations are included so two approvals cannot race past the
    daily pilot ceiling while checkout is still in progress.
    """
    total = Decimal("0.00")
    for row in state.get("action_queue", []):
        if row.get("type") != "COMMERCE_ORDER":
            continue
        status = row.get("status")
        if status == "EXECUTED":
            receipts = row.get("receipts") or []
            if not receipts:
                raise RuntimeError("PILOT_DAILY_LEDGER_INCOMPLETE: executed commerce order has no receipt")
            receipt = receipts[0]
            if _timestamp_day(receipt.get("executed_at")) == day:
                total += _d(receipt.get("total_sar", "0"))
        elif status == "EXECUTING" and row.get("pilot_reserved_day") == day:
            total += _d(row.get("pilot_reserved_total_sar", "0"))
    return _d(total)


def redact_private(text: str) -> str:
    value = _PHONE_RE.sub("[PHONE_REDACTED]", str(text or ""))
    return _ADDRESS_HINT_RE.sub("[ADDRESS_REDACTED]", value)


def natural_order_product_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    m = _ORDER_START_RE.search(raw)
    candidate = raw[m.end():] if m else raw
    candidate = _PRIVATE_TAIL_RE.split(candidate, maxsplit=1)[0]
    candidate = _PHONE_RE.sub(" ", candidate)
    candidate = _ADDRESS_HINT_RE.sub(" ", candidate)
    candidate = _PRICE_WORDS_RE.sub(" ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ،,.-")
    return candidate[:240]


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
    return {
        "address_configured": bool(os.environ.get("COMMERCE_DELIVERY_ADDRESS", "").strip()),
        "phone_configured": bool(os.environ.get("COMMERCE_DELIVERY_PHONE", "").strip()),
        "payment_profile_configured": bool(os.environ.get("COMMERCE_PAYMENT_PROFILE", "").strip()),
    }


def checkout_configured() -> bool:
    secret = (
        os.environ.get("COMMERCE_SHARED_SECRET", "").strip()
        or os.environ.get("COMMERCE_CHECKOUT_SECRET", "").strip()
    )
    return bool(os.environ.get("COMMERCE_CHECKOUT_WEBHOOK_URL", "").strip() and secret)


def create_order_preview(offer: Offer, quantity: int = 1, *, source_ref: str = "") -> dict:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    total = offer.total_sar
    if total is None:
        raise ValueError("NEEDS_INPUT: تكلفة الشحن غير مؤكدة؛ لا يمكن وصف العرض بأنه أفضل سعر نهائي.")
    approved_total = _d(total * quantity)
    if approved_total > PILOT_MAX_ORDER_SAR:
        raise RuntimeError(
            f"PILOT_ORDER_LIMIT_EXCEEDED: الحد الأقصى للعملية الواحدة {PILOT_MAX_ORDER_SAR} ر.س."
        )
    profile = delivery_profile_status()
    action_id = "SHOP-" + secrets.token_hex(4).upper()
    content = {
        "retailer": offer.retailer,
        "title": offer.title,
        "pack_count": offer.pack_count,
        "item_count_each": offer.item_count_each,
        "unit_offer_price_sar": str(offer.price_sar),
        "shipping_sar": str(offer.shipping_sar),
        "delivered_total_sar": str(approved_total),
        "url": offer.url,
        "quantity": quantity,
        "idempotency_key": action_id,
        "delivery_profile_ref": "env:commerce_delivery_profile",
        "delivery_profile_ready": profile["address_configured"] and profile["phone_configured"],
        "payment_profile_ready": profile["payment_profile_configured"],
        "source_ref": source_ref,
        "pilot_mode": True,
        "pilot_max_order_sar": str(PILOT_MAX_ORDER_SAR),
        "pilot_max_daily_sar": str(PILOT_MAX_DAILY_SAR),
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    row = {
        "action_id": action_id,
        "type": "COMMERCE_ORDER",
        "status": "PENDING_APPROVAL",
        "approval_code": digest[:10].upper(),
        "content_hash": digest,
        "created_at": _pilot_now_iso(),
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
        f"{profile_line}\n{payment_line}\n"
        f"🛡️ Pilot: ≤ {PILOT_MAX_ORDER_SAR} ر.س للعملية و≤ {PILOT_MAX_DAILY_SAR} ر.س لليوم\n\n"
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
        approved_total = _d((row.get("plan") or {}).get("delivered_total_sar", "0"))
        if approved_total > PILOT_MAX_ORDER_SAR:
            raise RuntimeError(
                f"PILOT_ORDER_LIMIT_EXCEEDED: الحد الأقصى للعملية الواحدة {PILOT_MAX_ORDER_SAR} ر.س."
            )
        day = _pilot_day()
        current_exposure = _pilot_exposure_for_day(state, day)
        if current_exposure + approved_total > PILOT_MAX_DAILY_SAR:
            remaining = max(Decimal("0.00"), PILOT_MAX_DAILY_SAR - current_exposure)
            raise RuntimeError(
                f"PILOT_DAILY_LIMIT_EXCEEDED: المتاح اليوم {remaining} ر.س من حد {PILOT_MAX_DAILY_SAR} ر.س."
            )
        row["status"] = "EXECUTING"
        row["pilot_reserved_day"] = day
        row["pilot_reserved_total_sar"] = str(approved_total)
        row["pilot_approved_at"] = _pilot_now_iso()
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
    approved_total = _d(p["delivered_total_sar"])
    receipt_total = _d((receipt or {}).get("total_sar", approved_total))
    if receipt_total > approved_total:
        raise RuntimeError("PRICE_CEILING_VIOLATION: مزود Checkout أعاد إجماليًا أعلى من السعر الموافق عليه.")
    if receipt_total > PILOT_MAX_ORDER_SAR:
        raise RuntimeError("PILOT_ORDER_LIMIT_EXCEEDED: مزود Checkout أعاد إجماليًا أعلى من حد الـPilot.")
    clean = {
        "order_id": order_id,
        "retailer": p["retailer"],
        "total_sar": str(receipt_total),
        "status": str((receipt or {}).get("status") or "EXECUTED"),
        "idempotency_key": p.get("idempotency_key", action_id),
        "executed_at": _pilot_now_iso(),
    }
    payment_url = str((receipt or {}).get("payment_url") or "").strip()
    if payment_url.startswith("https://"):
        clean["payment_url"] = payment_url

    def finish(state):
        target = next(x for x in state["action_queue"] if x.get("action_id") == action_id)
        target["status"] = "EXECUTED"
        target.pop("pilot_reserved_day", None)
        target.pop("pilot_reserved_total_sar", None)
        target["executed_at"] = clean["executed_at"]
        target["receipts"] = [clean]
        return True, target

    return Store().transaction(finish, "commerce_order_executed", action_id=action_id, order_id=order_id)
