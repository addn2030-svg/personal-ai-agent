# -*- coding: utf-8 -*-
"""اختبار وظيفي حي لعتبة 375 ريال — يُشغّل المحرك ضد موصل دفع رملي في العملية نفسها.

يُستخدم من scripts/verify_money_threshold.sh. يطبع سطري الحالتين ويعيد:
  0 ← نجح (90 → ACT_PAY/GREEN · 500 → ALERT_DRAFT/RED)
  1 ← فشل أي حالة.
"""
import datetime as dt
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))
sys.path.insert(0, BASE)


def _silence_stderr():
    """يكتم ضجيج خادم HTTP الرملي حتى يبقى خرج التحقق نظيفًا."""
    sys.stderr = open(os.devnull, "w")


def main() -> int:
    from connectors import payment_sandbox as SBX
    from connectors import payment_gateway as PG

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SBX._Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    os.environ["MONEY_AUTOPAY_ENABLED"] = "1"
    os.environ["MONEY_AUTOPAY_ACK"] = PG.ACK_PHRASE
    os.environ["PAYMENT_GATEWAY_WEBHOOK_URL"] = f"http://127.0.0.1:{port}/pay"
    os.environ["PAYMENT_GATEWAY_SHARED_SECRET"] = "sandbox-secret"
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)

    import proactive as P
    from store import Store

    TZ = ZoneInfo("Asia/Riyadh")
    DAY = dt.date(2026, 9, 17)  # الخميس

    def run_case(amount_sar):
        tmp = tempfile.TemporaryDirectory()
        store = Store(path=str(Path(tmp.name) / "state.json"))
        S = store.rows_all()
        S["finance"] = [{"البند": "بند اختبار", "النوع": "اشتراك",
                         "التكلفة (ريال/شهر)": amount_sar,
                         "تاريخ التجديد": (DAY + dt.timedelta(days=2)).isoformat(),
                         "آخر استخدام": DAY.isoformat()}]
        S["standing_orders"] = [dict(o) for o in P.DEFAULT_STANDING_ORDERS]
        store.commit(S, "seed")
        _silence_stderr()
        P.sweep(store=store, now_dt=dt.datetime(DAY.year, DAY.month, DAY.day, 9, 0,
                                                tzinfo=TZ), verbose=False)
        rows = [r for r in store.rows_all()["proactive_actions"]
                if r.get("category") == "money" and r.get("kind") == "bill_due"]
        led = store.rows_all()["autopay_executions"]
        tmp.cleanup()
        return (rows[0] if rows else None), led

    ok = True
    for amount, want_dec, want_lane in ((90, "ACT_PAY", "GREEN"),
                                        (500, "ALERT_DRAFT", "RED")):
        row, led = run_case(amount)
        usd = PG.usd(amount)
        dec = row["decision"] if row else "—"
        lane = row["lane"] if row else "—"
        executed = any(p["status"] == "EXECUTED" for p in led)
        good = (dec == want_dec and lane == want_lane
                and (executed if want_dec == "ACT_PAY" else not executed))
        ok = ok and good
        if want_dec == "ACT_PAY":
            detail = "دفع تلقائي <375 ريال — L3 مصرّح" + (" ✅" if good else " ❌")
        else:
            detail = "لا تنفيذ + مسودة للاعتماد" + (" ✅" if good else " ❌")
        print(f"{amount} SAR ({usd}$) → {dec} {lane} : {detail}")

    httpd.shutdown()
    httpd.server_close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
