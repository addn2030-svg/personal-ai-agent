# -*- coding: utf-8 -*-
"""Trusted checkout adapter.

The retailer/browser executor is external to this repo. This module sends only the
approved order plan plus delivery/payment profile values from runtime secrets.
Those values are never persisted in StateStore or returned in receipts.
"""
from __future__ import annotations

import json, os, urllib.request


def checkout(plan: dict) -> dict:
    url = os.environ.get("COMMERCE_CHECKOUT_WEBHOOK_URL", "").strip()
    secret = os.environ.get("COMMERCE_CHECKOUT_SECRET", "").strip()
    address = os.environ.get("COMMERCE_DELIVERY_ADDRESS", "").strip()
    phone = os.environ.get("COMMERCE_DELIVERY_PHONE", "").strip()
    payment_profile = os.environ.get("COMMERCE_PAYMENT_PROFILE", "").strip()
    if not all([url, secret, address, phone, payment_profile]):
        raise RuntimeError("Commerce checkout environment is incomplete")
    payload = {
        "secret": secret,
        "action": "checkout",
        "order": {
            "retailer": plan["retailer"],
            "title": plan["title"],
            "quantity": int(plan["quantity"]),
            "url": plan["url"],
            "max_total_sar": plan["delivered_total_sar"],
        },
        "delivery": {"address": address, "phone": phone},
        "payment_profile": payment_profile,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Checkout provider failed: " + str(result.get("error", "unknown"))[:240])
    # Return only non-sensitive receipt fields.
    return {
        "order_id": str(result.get("order_id") or result.get("id") or ""),
        "status": str(result.get("status") or "submitted"),
        "total_sar": str(result.get("total_sar") or plan["delivered_total_sar"]),
    }
