# -*- coding: utf-8 -*-
"""موصل دفع رملي (sandbox) للتحقق من مسار الدفع التلقائي دون أموال حقيقية.

يقلّد عقد المزوّد الإنتاجي الذي تتوقعه `connectors/payment_gateway.py`:

  POST {"action":"pay",   "idempotency_key":..., "amount_sar":..., "max_amount_sar":...}
    → {"ok":true,"payment_id":"PAY-...","amount_sar":"90.00","status":"executed"}
  POST {"action":"refund","payment_id":...}
    → {"ok":true,"refund_id":"REF-...","status":"refunded"}

ويطبّق نفس القيود: سر مشترك، سقف 375 ريال للعملية، سقف يومي تراكمي، وعدم تكرار
الدفع للمفتاح الواحد (idempotency).

التشغيل:
  python3 connectors/payment_sandbox.py --port 8731 [--daily-max 375] [--fail-once]

عند `--port 0` يُطبع المنفذ الفعلي في stdout بصيغة `LISTENING <port>` ليقرأه
سكربت التحقق (scripts/verify_money_threshold.sh).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

HARD_MAX_SAR = Decimal("375.00")
TZ = ZoneInfo(os.environ.get("MANAGER_TIMEZONE", "Asia/Riyadh"))

STATE_LOCK = threading.Lock()
ORDERS: dict[str, dict] = {}
REFUNDS: dict[str, dict] = {}
COUNTER = {"pay": 0, "refund": 0}
CONFIG = {"secret": "sandbox-secret", "daily_max": HARD_MAX_SAR,
          "order_max": HARD_MAX_SAR, "fail_once": False}


def _d(value) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return None


def _today() -> str:
    return dt.datetime.now(TZ).date().isoformat()


def _spent_today() -> Decimal:
    day = _today()
    total = Decimal("0.00")
    for order in ORDERS.values():
        if order["day"] == day and order["status"] != "refunded":
            total += _d(order["amount_sar"]) or Decimal("0.00")
    return total


def handle(payload: dict) -> tuple[int, dict]:
    """نقطة القرار الوحيدة — تُختبر مباشرة دون شبكة."""
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "bad_payload"}
    if str(payload.get("secret", "")) != CONFIG["secret"]:
        return 403, {"ok": False, "error": "bad_secret"}
    action = str(payload.get("action", ""))
    key = str(payload.get("idempotency_key", "")).strip()

    if action == "pay":
        if not key:
            return 400, {"ok": False, "error": "idempotency_key_required"}
        amount = _d(payload.get("amount_sar"))
        if amount is None or amount <= 0:
            return 400, {"ok": False, "error": "amount_invalid"}
        ceiling = min(_d(payload.get("max_amount_sar")) or CONFIG["order_max"],
                      CONFIG["order_max"])
        if amount > ceiling:
            return 422, {"ok": False, "error": f"PILOT_ORDER_LIMIT_EXCEEDED:{ceiling}"}
        with STATE_LOCK:
            prior = ORDERS.get(key)
            if prior:                       # عدم التكرار: نفس المفتاح ← نفس النتيجة
                return 200, dict(prior)
            if CONFIG["fail_once"]:
                CONFIG["fail_once"] = False
                return 502, {"ok": False, "error": "SANDBOX_TRANSIENT_FAILURE"}
            spent = _spent_today()
            if spent + amount > CONFIG["daily_max"]:
                return 422, {"ok": False, "error": f"DAILY_CAP_EXCEEDED:{spent}"}
            COUNTER["pay"] += 1
            receipt = {"ok": True, "payment_id": f"PAY-{COUNTER['pay']:04d}",
                       "status": "executed", "amount_sar": str(amount),
                       "idempotency_key": key, "day": _today(),
                       "payee": str(payload.get("payee", ""))[:160],
                       "provider": "payment-sandbox"}
            ORDERS[key] = receipt
            return 200, dict(receipt)

    if action == "refund":
        pid = str(payload.get("payment_id", "")).strip()
        with STATE_LOCK:
            target = next((o for o in ORDERS.values() if o["payment_id"] == pid), None)
            if not target:
                return 404, {"ok": False, "error": "payment_not_found"}
            if target["status"] == "refunded":
                return 200, {"ok": True, "refund_id": REFUNDS[pid]["refund_id"],
                             "status": "refunded",
                             "amount_sar": target["amount_sar"]}
            COUNTER["refund"] += 1
            refund_id = f"REF-{COUNTER['refund']:04d}"
            REFUNDS[pid] = {"refund_id": refund_id, "amount_sar": target["amount_sar"],
                            "at": dt.datetime.now(TZ).isoformat(timespec="seconds")}
            target["status"] = "refunded"
            return 200, {"ok": True, "refund_id": refund_id, "status": "refunded",
                         "amount_sar": target["amount_sar"],
                         "payment_id": pid}

    if action == "ledger":
        with STATE_LOCK:
            return 200, {"ok": True, "orders": list(ORDERS.values()),
                         "refunds": list(REFUNDS.values())}
    return 400, {"ok": False, "error": f"unknown_action:{action}"}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            self._send(400, {"ok": False, "error": "invalid_json"})
            return
        code, body = handle(payload)
        self._send(code, body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._send(200, {"ok": True, "service": "payment-sandbox",
                             "orders": len(ORDERS)})
        else:
            self._send(404, {"ok": False, "error": "not_found"})

    def log_message(self, fmt, *args):  # إخراج أنظف للتحقق
        sys.stderr.write("[sandbox] " + (fmt % args) + "\n")


def serve(port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser(description="موصل دفع رملي لاختبار عتبة 375 ريال")
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--secret", default="sandbox-secret")
    ap.add_argument("--daily-max", default="375.00")
    ap.add_argument("--order-max", default="375.00")
    ap.add_argument("--fail-once", action="store_true",
                    help="أول طلب دفع يفشل (502) لاختبار مسار التراجع الآمن")
    args = ap.parse_args()

    CONFIG["secret"] = args.secret
    CONFIG["daily_max"] = min(_d(args.daily_max) or HARD_MAX_SAR, HARD_MAX_SAR)
    CONFIG["order_max"] = min(_d(args.order_max) or HARD_MAX_SAR, HARD_MAX_SAR)
    CONFIG["fail_once"] = args.fail_once

    httpd = serve(args.port, args.host)
    bound = httpd.server_address[1]
    print(f"LISTENING {bound}", flush=True)
    print(f"PAYMENT_GATEWAY_WEBHOOK_URL=http://127.0.0.1:{bound}/pay", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
