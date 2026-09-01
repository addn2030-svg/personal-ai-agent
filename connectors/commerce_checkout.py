# -*- coding: utf-8 -*-
"""Trusted production checkout adapter.

The retailer/browser executor is external to this repo. This module sends only an
approved order plan plus delivery/payment profile values from runtime secrets.
Those values are never persisted in StateStore or returned in receipts.

Provider contract:
- must honor idempotency_key (same key => same purchase result, never duplicate);
- must refuse checkout when final_total_sar would exceed max_total_sar;
- must return a concrete order_id only after the retailer accepted the order.
"""
from __future__ import annotations

import json, os, urllib.request
from decimal import Decimal

PILOT_MAX_ORDER_SAR = Decimal("375.00")


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _checkout_secret() -> str:
    return (
        os.environ.get("COMMERCE_SHARED_SECRET", "").strip()
        or os.environ.get("COMMERCE_CHECKOUT_SECRET", "").strip()
    )


def checkout(plan: dict) -> dict:
    url = os.environ.get("COMMERCE_CHECKOUT_WEBHOOK_URL", "").strip()
    secret = _checkout_secret()
    address = os.environ.get("COMMERCE_DELIVERY_ADDRESS", "").strip()
    phone = os.environ.get("COMMERCE_DELIVERY_PHONE", "").strip()
    payment_profile = os.environ.get("COMMERCE_PAYMENT_PROFILE", "").strip()
    if not all([url, secret, address, phone, payment_profile]):
        raise RuntimeError("Commerce checkout environment is incomplete")
    idempotency_key = str(plan.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise RuntimeError("Checkout plan is missing idempotency_key")
    max_total = _d(plan["delivered_total_sar"])
    if max_total > PILOT_MAX_ORDER_SAR:
        raise RuntimeError(
            f"PILOT_ORDER_LIMIT_EXCEEDED: checkout adapter limit is {PILOT_MAX_ORDER_SAR} SAR"
        )
    payload = {
        "secret": secret,
        "action": "checkout",
        "idempotency_key": idempotency_key,
        "order": {
            "retailer": plan["retailer"],
            "title": plan["title"],
            "quantity": int(plan["quantity"]),
            "url": plan["url"],
            "max_total_sar": str(max_total),
        },
        "delivery": {"address": address, "phone": phone},
        "payment_profile": payment_profile,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Commerce-Idempotency-Key": idempotency_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Checkout provider failed: " + str(result.get("error", "unknown"))[:240])
    order_id = str(result.get("order_id") or result.get("id") or "").strip()
    if not order_id:
        raise RuntimeError("Checkout provider did not return order_id")
    final_total = _d(result.get("total_sar", max_total))
    if final_total > max_total:
        raise RuntimeError("PRICE_CEILING_VIOLATION: provider total exceeds approved ceiling")
    if final_total > PILOT_MAX_ORDER_SAR:
        raise RuntimeError("PILOT_ORDER_LIMIT_EXCEEDED: provider total exceeds pilot ceiling")
    receipt = {
        "order_id": order_id,
        "status": str(result.get("status") or "submitted"),
        "total_sar": str(final_total),
        "idempotency_key": idempotency_key,
    }
    payment_url = str(result.get("payment_url") or "").strip()
    if payment_url.startswith("https://"):
        receipt["payment_url"] = payment_url
    return receipt
