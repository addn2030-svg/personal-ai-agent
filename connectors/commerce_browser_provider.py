# -*- coding: utf-8 -*-
"""HTTP checkout provider for Commerce Agent.

Deploy this as a separate Railway service. It accepts only requests carrying the
configured commerce shared secret, enforces idempotency, delegates to the
fail-closed browser executor, and never accepts raw card data.

Pilot safety adds a hard 375 SAR per-order cap and 375 SAR total exposure per
Asia/Riyadh day (USD 100 equivalent at the SAR 3.75/USD peg).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

# Support both execution modes:
# 1) package import in CI/tests: connectors.commerce_browser_provider
# 2) direct Railway startup: python connectors/commerce_browser_provider.py
try:
    from .commerce_browser_checkout import execute
except ImportError:
    from commerce_browser_checkout import execute

PORT = int(os.environ.get("PORT", "8080") or "8080")
DATA_DIR = Path(os.environ.get("COMMERCE_BROWSER_DATA_DIR", "/data"))
RECEIPTS = DATA_DIR / "commerce-browser-receipts.json"
_LOCK = threading.RLock()
_PILOT_TZ = ZoneInfo("Asia/Riyadh")
PILOT_MAX_ORDER_SAR = Decimal("375.00")
PILOT_MAX_DAILY_SAR = Decimal("375.00")


def _d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _pilot_now() -> datetime:
    return datetime.now(_PILOT_TZ)


def _pilot_day() -> str:
    return _pilot_now().date().isoformat()


def _pilot_now_iso() -> str:
    return _pilot_now().isoformat(timespec="seconds")


def _timestamp_day(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(_PILOT_TZ).date().isoformat()
    except Exception as exc:
        raise RuntimeError("PILOT_DAILY_LEDGER_INCOMPLETE") from exc


def _daily_total(receipts: dict, day: str) -> Decimal:
    total = Decimal("0.00")
    for receipt in receipts.values():
        if not isinstance(receipt, dict) or not receipt.get("order_id"):
            continue
        executed_at = receipt.get("executed_at")
        if not executed_at:
            raise RuntimeError("PILOT_DAILY_LEDGER_INCOMPLETE")
        if _timestamp_day(executed_at) == day:
            total += _d(receipt.get("total_sar", "0"))
    return _d(total)


def _load() -> dict:
    with _LOCK:
        if not RECEIPTS.exists():
            return {}
        try:
            return json.loads(RECEIPTS.read_text(encoding="utf-8"))
        except Exception:
            return {}


def _save(data: dict) -> None:
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="commerce-", suffix=".json", dir=str(DATA_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, RECEIPTS)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _provider_secret() -> str:
    """Use the canonical shared credential, with legacy fallback."""
    return (
        os.environ.get("COMMERCE_SHARED_SECRET", "").strip()
        or os.environ.get("COMMERCE_BROWSER_PROVIDER_SECRET", "").strip()
    )


def checkout_payload(body: dict) -> dict:
    expected = _provider_secret()
    if not expected or str(body.get("secret") or "") != expected:
        raise PermissionError("UNAUTHORIZED")
    if body.get("action") != "checkout":
        raise ValueError("UNSUPPORTED_ACTION")
    key = str(body.get("idempotency_key") or "").strip()
    if not key:
        raise ValueError("MISSING_IDEMPOTENCY_KEY")
    order = body.get("order") or {}
    delivery = body.get("delivery") or {}
    payment_profile = str(body.get("payment_profile") or "").strip()
    if any(k in body for k in ("card", "card_number", "cvc", "cvv")):
        raise ValueError("RAW_CARD_DATA_FORBIDDEN")

    try:
        max_total = _d(order.get("max_total_sar"))
    except Exception as exc:
        raise ValueError("INVALID_MAX_TOTAL_SAR") from exc
    if max_total <= 0:
        raise ValueError("INVALID_MAX_TOTAL_SAR")
    if max_total > PILOT_MAX_ORDER_SAR:
        raise ValueError(f"PILOT_ORDER_LIMIT_EXCEEDED: max {PILOT_MAX_ORDER_SAR} SAR")

    # Serialize the idempotency check, daily-limit check, browser checkout, and
    # receipt commit within one provider process. Railway pilot uses one replica.
    with _LOCK:
        receipts = _load()
        if key in receipts:
            return receipts[key]

        day = _pilot_day()
        spent_today = _daily_total(receipts, day)
        if spent_today + max_total > PILOT_MAX_DAILY_SAR:
            remaining = max(Decimal("0.00"), PILOT_MAX_DAILY_SAR - spent_today)
            raise ValueError(
                f"PILOT_DAILY_LIMIT_EXCEEDED: remaining {remaining} SAR of {PILOT_MAX_DAILY_SAR} SAR"
            )

        plan = {
            "retailer": order.get("retailer"),
            "title": order.get("title"),
            "quantity": int(order.get("quantity") or 1),
            "url": order.get("url"),
            "max_total_sar": str(max_total),
        }
        result = execute(plan, delivery, payment_profile)
        final_total = _d((result or {}).get("total_sar", max_total))
        if final_total > max_total:
            raise ValueError("PRICE_CEILING_VIOLATION")
        if final_total > PILOT_MAX_ORDER_SAR:
            raise ValueError("PILOT_ORDER_LIMIT_EXCEEDED")
        receipt = {
            "ok": True,
            **result,
            "total_sar": str(final_total),
            "idempotency_key": key,
            "executed_at": _pilot_now_iso(),
            "pilot_mode": True,
            "pilot_max_order_sar": str(PILOT_MAX_ORDER_SAR),
            "pilot_max_daily_sar": str(PILOT_MAX_DAILY_SAR),
        }
        receipts[key] = receipt
        _save(receipts)
        return receipt


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path in {"/", "/health", "/ready"}:
            self._send(200, {
                "ok": True,
                "service": "commerce-browser-checkout",
                "real_purchase_capable": True,
                "payment_modes": ["PAYMENT_LINK", "COD"],
                "raw_card_storage": False,
                "pilot_mode": True,
                "pilot_max_order_sar": str(PILOT_MAX_ORDER_SAR),
                "pilot_max_daily_sar": str(PILOT_MAX_DAILY_SAR),
            })
            return
        self._send(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self):  # noqa: N802
        if self.path != "/checkout":
            self._send(404, {"ok": False, "error": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            self._send(200, checkout_payload(body))
        except PermissionError as exc:
            self._send(401, {"ok": False, "error": str(exc)})
        except Exception as exc:  # fail closed; no receipt without confirmed order id
            self._send(422, {"ok": False, "error": str(exc)[:400]})

    def log_message(self, fmt: str, *args):
        print("commerce-browser:", fmt % args, flush=True)


def run():
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    run()
