# -*- coding: utf-8 -*-
"""اختبارات عتبة التفويض المالي (375 ريال) — money L1 → L3.

تغطي:
  - سياسة العتبة: <375 ← L3 مفوَّض، ≥375 ← L1 أحمر (تنبيه + مسودة).
  - القرار في المحرك: ACT_PAY/GREEN مقابل ALERT_DRAFT/RED.
  - السلوك المحافظ عند غياب أي حاجز (البيئة مطفأة/إقرار ناقص/موصل غير مضبوط).
  - تنفيذ فعلي عبر موصل رملي حي: إيصال حقيقي، عدم تكرار، سقف يومي، تراجع/استرداد.
  - فشل المزوّد ← توثيق + مسودة احتياطية (لا سقوط صامت لالتزام مالي).
  - سقف الكود 375: البيئة تخفضه ولا ترفعه أبدًا.
"""
import datetime as dt
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))
sys.path.insert(0, BASE)

from store import Store  # noqa: E402
import proactive as P  # noqa: E402
from connectors import payment_gateway as PG  # noqa: E402
from connectors import payment_sandbox as SBX  # noqa: E402

TZ = ZoneInfo("Asia/Riyadh")
DAY = dt.date(2026, 9, 17)  # الخميس
ACK = PG.ACK_PHRASE


def at(hh, mm=0):
    return dt.datetime(DAY.year, DAY.month, DAY.day, hh, mm, tzinfo=TZ)


def finance_row(item, cost, due_days=2, last_use_days=0):
    return {"البند": item, "النوع": "اشتراك",
            "التكلفة (ريال/شهر)": cost,
            "تاريخ التجديد": (DAY + dt.timedelta(days=due_days)).isoformat(),
            "آخر استخدام": (DAY - dt.timedelta(days=last_use_days)).isoformat()}


ENV_KEYS = ("MONEY_AUTOPAY_ENABLED", "MONEY_AUTOPAY_ACK",
            "MONEY_AUTOPAY_MAX_SAR", "MONEY_AUTOPAY_DAILY_MAX_SAR",
            "PAYMENT_GATEWAY_WEBHOOK_URL", "PAYMENT_GATEWAY_SHARED_SECRET",
            "TELEGRAM_BOT_TOKEN")


class _EnvGuard(unittest.TestCase):
    """يعزل متغيرات البيئة ويعيد ضبط الموصل الرملي بين الاختبارات."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        # إعادة ضبط حالة الموصل الرملي (معمارية عامة عبر الاختبارات)
        with SBX.STATE_LOCK:
            SBX.ORDERS.clear()
            SBX.REFUNDS.clear()
            SBX.COUNTER["pay"] = 0
            SBX.COUNTER["refund"] = 0
            SBX.CONFIG["fail_once"] = False
            SBX.CONFIG["secret"] = "sandbox-secret"
            SBX.CONFIG["daily_max"] = SBX.HARD_MAX_SAR
            SBX.CONFIG["order_max"] = SBX.HARD_MAX_SAR
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # --- أدوات مساعدة ---
    def seed(self, **sections):
        S = self.store.rows_all()
        for k, v in sections.items():
            S[k] = v
        S.setdefault("standing_orders", [dict(o) for o in P.DEFAULT_STANDING_ORDERS])
        self.store.commit(S, "seed")

    def sweep(self, when=None):
        return P.sweep(store=self.store, now_dt=when or at(9), verbose=False)

    def money_rows(self):
        return [r for r in self.store.rows_all()["proactive_actions"]
                if r.get("category") == "money"]

    def ledger(self):
        return self.store.rows_all()["autopay_executions"]


class ThresholdPolicyTests(_EnvGuard):
    """سياسة العتبة كدوال نقية — بلا شبكة."""

    def test_threshold_text_is_375_sar_about_100_usd(self):
        self.assertEqual(PG.threshold_text(), "375 SAR (~100$)")

    def test_below_threshold_maps_to_L3(self):
        pol = P._money_policy(90, S={}, today=DAY.isoformat())
        self.assertEqual(pol["level"], "L3")
        self.assertEqual(pol["amount_usd"], "24")

    def test_exact_threshold_is_red_L1(self):
        pol = P._money_policy(375, S={}, today=DAY.isoformat())
        self.assertFalse(pol["authorized"])
        self.assertEqual(pol["level"], "L1")
        self.assertEqual(pol["guard"], "at_or_above_threshold")

    def test_above_threshold_is_red_L1(self):
        pol = P._money_policy(500, S={}, today=DAY.isoformat())
        self.assertFalse(pol["authorized"])
        self.assertEqual(pol["guard"], "at_or_above_threshold")

    def test_unknown_amount_never_authorized(self):
        for bad in (None, "", "NEEDS_INPUT", "abc"):
            pol = P._money_policy(bad, S={}, today=DAY.isoformat())
            self.assertFalse(pol["authorized"])
            self.assertEqual(pol["guard"], "amount_unknown")

    def test_disabled_env_blocks_even_subthreshold(self):
        # بدون MONEY_AUTOPAY_ENABLED ← المستوى L3 صحيح لكن غير مفوَّض
        pol = P._money_policy(90, S={}, today=DAY.isoformat())
        self.assertFalse(pol["authorized"])
        self.assertEqual(pol["guard"], "disabled_env")

    def test_env_can_lower_but_never_raise_hard_cap(self):
        os.environ["MONEY_AUTOPAY_MAX_SAR"] = "1000"
        self.assertEqual(str(PG.threshold_sar()), "375.00")   # مُقتطع إلى سقف الكود
        os.environ["MONEY_AUTOPAY_MAX_SAR"] = "50"
        self.assertEqual(str(PG.threshold_sar()), "50.00")    # خَفض مسموح

    def test_missing_ack_blocks_execution(self):
        os.environ["MONEY_AUTOPAY_ENABLED"] = "1"
        os.environ["PAYMENT_GATEWAY_WEBHOOK_URL"] = "http://x/pay"
        os.environ["PAYMENT_GATEWAY_SHARED_SECRET"] = "s"
        pol = P._money_policy(90, S={}, today=DAY.isoformat())
        self.assertFalse(pol["authorized"])
        self.assertEqual(pol["guard"], "missing_ack")


class LiveGatewayTests(_EnvGuard):
    """تنفيذ فعلي عبر موصل رملي حي على منفذ عشوائي."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), SBX._Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def arm(self):
        os.environ["MONEY_AUTOPAY_ENABLED"] = "1"
        os.environ["MONEY_AUTOPAY_ACK"] = ACK
        os.environ["PAYMENT_GATEWAY_WEBHOOK_URL"] = f"http://127.0.0.1:{self.port}/pay"
        os.environ["PAYMENT_GATEWAY_SHARED_SECRET"] = "sandbox-secret"

    def test_subthreshold_bill_executes_with_receipt(self):
        self.arm()
        self.seed(finance=[finance_row("اشتراك أدبي", 90)])
        summary = self.sweep()
        self.assertEqual(summary["pay"], 1)
        self.assertEqual(summary["paid"], 1)
        rows = self.money_rows()
        act = [r for r in rows if r["decision"] == "ACT_PAY"]
        self.assertEqual(len(act), 1)
        self.assertEqual(act[0]["lane"], "GREEN")
        self.assertIn("L3 مصرّح", act[0]["note"])
        led = self.ledger()
        self.assertEqual(len(led), 1)
        self.assertEqual(led[0]["status"], "EXECUTED")
        self.assertTrue(led[0]["receipt"]["payment_id"])
        self.assertEqual(led[0]["amount_sar"], "90.00")
        self.assertEqual(act[0]["undo"]["op"], "refund_payment")

    def test_above_threshold_bill_alerts_and_drafts_no_execution(self):
        self.arm()
        self.seed(finance=[finance_row("تأمين سيارة", 500)])
        self.sweep()
        rows = self.money_rows()
        red = [r for r in rows if r["kind"] == "bill_due"]
        self.assertEqual(red[0]["decision"], "ALERT_DRAFT")
        self.assertEqual(red[0]["lane"], "RED")
        self.assertIn("لا تنفيذ", red[0]["note"])
        self.assertEqual(self.ledger(), [])          # لا أثر مالي
        queue = self.store.rows_all()["action_queue"]
        self.assertTrue(any(a["status"] == "PENDING_APPROVAL" for a in queue))

    def test_unarmed_env_falls_back_to_conservative_draft(self):
        # البيئة غير مسلّحة ← حتى 90 ريال يبقى مسودة (لا تنفيذ)
        self.seed(finance=[finance_row("اشتراك أدبي", 90)])
        self.sweep()
        red = [r for r in self.money_rows() if r["kind"] == "bill_due"]
        self.assertEqual(red[0]["decision"], "ALERT_DRAFT")
        self.assertEqual(red[0]["lane"], "RED")
        self.assertEqual(self.ledger(), [])

    def test_idempotent_no_double_charge_on_second_sweep(self):
        self.arm()
        self.seed(finance=[finance_row("اشتراك أدبي", 90)])
        self.sweep()
        first = self.ledger()[0]["receipt"]["payment_id"]
        self.sweep(at(10))        # دورة ثانية ← لا تكرار (المفتاح في seen)
        led = self.ledger()
        self.assertEqual(len(led), 1)
        self.assertEqual(led[0]["receipt"]["payment_id"], first)
        with SBX.STATE_LOCK:
            self.assertEqual(len(SBX.ORDERS), 1)   # المزوّد رأى عملية واحدة

    def test_daily_cap_blocks_second_subthreshold_payment(self):
        self.arm()
        self.seed(finance=[finance_row("أ", 200), finance_row("ب", 200)])
        self.sweep()
        led = self.ledger()
        executed = [r for r in led if r["status"] == "EXECUTED"]
        # 200+200=400 > 375 ← واحد يُنفَّذ والثاني يُحجب بالسقف اليومي
        self.assertEqual(len(executed), 1)
        with SBX.STATE_LOCK:
            self.assertEqual(len(SBX.ORDERS), 1)
        red_rows = [r for r in self.money_rows() if r["decision"] in ("ALERT", "ALERT_DRAFT")]
        self.assertTrue(any("السقف اليومي" in r["note"] or r["lane"] == "RED"
                            for r in red_rows))

    def test_undo_refunds_executed_payment(self):
        self.arm()
        self.seed(finance=[finance_row("اشتراك أدبي", 90)])
        self.sweep()
        pa = [r for r in self.money_rows() if r["decision"] == "ACT_PAY"][0]["pa_id"]
        changed, info = P.undo(pa, store=self.store)
        self.assertTrue(changed)
        led = self.ledger()[0]
        self.assertEqual(led["status"], "REVERSED")
        self.assertTrue(led["refund"]["refund_id"])
        with SBX.STATE_LOCK:
            self.assertEqual(SBX.ORDERS[led["idempotency_key"]]["status"], "refunded")
        # المهمة المرئية أُزيلت
        titles = [t["العنوان"] for t in self.store.rows_all()["tasks"]]
        self.assertFalse(any("دفع تلقائي" in x for x in titles))

    def test_gateway_failure_is_logged_and_enqueues_fallback_draft(self):
        self.arm()
        with SBX.STATE_LOCK:
            SBX.CONFIG["fail_once"] = True     # أول طلب دفع ← 502
        self.seed(finance=[finance_row("اشتراك أدبي", 90)])
        summary = self.sweep()
        self.assertEqual(summary["pay_failed"], 1)
        self.assertEqual(summary["paid"], 0)
        led = self.ledger()[0]
        self.assertEqual(led["status"], "FAILED")
        self.assertTrue(led["error"])
        # لا سقوط صامت ← مسودة احتياطية في طابور الاعتماد
        queue = self.store.rows_all()["action_queue"]
        self.assertTrue(any(a["origin"] == "proactive_autopay_failed"
                            and a["status"] == "PENDING_APPROVAL" for a in queue))

    def test_renewal_watch_subthreshold_is_delegated(self):
        self.arm()
        # تجديد في نافذة 7 أيام (بين 3 و7) ← pay_auto إن كان دون العتبة
        self.seed(finance=[finance_row("نطاقات", 120, due_days=5)])
        self.sweep()
        rows = [r for r in self.money_rows() if r["kind"] == "renewal_watch"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["decision"], "ACT_PAY")
        self.assertEqual(self.ledger()[0]["status"], "EXECUTED")


class MatrixAndStatusTests(_EnvGuard):
    def test_matrix_marks_money_upgrade_to_l3(self):
        st = P.money_threshold_status({})
        self.assertEqual(st["money_level_base"], "L1")
        self.assertEqual(st["money_level_at_or_above_threshold"], "L1")
        self.assertTrue(st["upgrades_to_l3"])
        self.assertEqual(st["threshold_text"], "375 SAR (~100$)")

    def test_status_includes_money_threshold_block(self):
        st = P.status(store=self.store)
        self.assertIn("money_threshold", st)
        self.assertEqual(st["money_threshold"]["threshold_text"], "375 SAR (~100$)")
        self.assertIn("autopay_today", st)


if __name__ == "__main__":
    unittest.main(verbosity=2)
