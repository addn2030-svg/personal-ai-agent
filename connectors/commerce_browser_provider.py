# -*- coding: utf-8 -*-
"""HTTP checkout provider for Commerce Agent.

Deploy this as a separate Railway service. It accepts only requests carrying
COMMERCE_BROWSER_PROVIDER_SECRET, enforces idempotency, delegates to the
fail-closed browser executor, and never accepts raw card data.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from connectors.commerce_browser_checkout import execute

PORT = int(os.environ.get("PORT", "8080") or "8080")
DATA_DIR = Path(os.environ.get("COMMERCE_BROWSER_DATA_DIR", "/data"))
RECEIPTS = DATA_DIR / "commerce-browser-receipts.json"
_LOCK = threading.RLock()


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


def checkout_payload(body: dict) -> dict:
    expected = os.environ.get("COMMERCE_BROWSER_PROVIDER_SECRET", "").strip()
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

    receipts = _load()
    if key in receipts:
        return receipts[key]

    plan = {
        "retailer": order.get("retailer"),
        "title": order.get("title"),
        "quantity": int(order.get("quantity") or 1),
        "url": order.get("url"),
        "max_total_sar": order.get("max_total_sar"),
    }
    result = execute(plan, delivery, payment_profile)
    receipt = {"ok": True, **result, "idempotency_key": key}
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
