# -*- coding: utf-8 -*-
"""Offline tests for the v1.0 Proactive Chief of Staff engine.

Covers: open-loops ledger, autonomy ladder lanes (green/yellow/red/info),
confidence gate, quiet hours, daily alert cap, pause switch, standing orders,
missed-action recovery, undo, feedback learning (good/much/never), idempotency
(write-on-change), and the hard governance rule: no external effect is ever
executed — everything external waits in PENDING_APPROVAL.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store  # noqa: E402
import proactive  # noqa: E402

TZ = ZoneInfo("Asia/Riyadh")
DAY = dt.date(2026, 9, 11)  # جمعة


def at(hh, mm=0):
    return dt.datetime(DAY.year, DAY.month, DAY.day, hh, mm, tzinfo=TZ)


def task(title, prio="عالية", due=DAY, status="لم تبدأ", **kw):
    row = {"العنوان": title, "النوع": "أعمال", "الأولوية": prio,
           "الموعد النهائي": due, "الحالة": status, "السياق/المشروع": "x",
           "المصدر": "اختبار", "ملاحظات": ""}
    row.update(kw)
    return row


class ProactiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        self.reports = str(Path(self.tmp.name) / "reports")
        os.makedirs(self.reports, exist_ok=True)

    def seed(self, **sections):
        S = self.store.rows_all()
        for k, v in sections.items():
            S[k] = v
        self.store.commit(S, "seed")

    def sweep(self, when=None, cfg=None):
        return proactive.sweep(store=self.store, now_dt=when or at(9), cfg=cfg,
                               verbose=False)

    def ledger(self):
        return self.store.rows_all()["proactive_actions"]

    def by_kind(self, kind):
        return [a for a in self.ledger() if a["kind"] == kind]

    # ---------------------------------------------------------- التأسيس والحلقات
    def test_first_sweep_seeds_standing_orders_and_is_idempotent(self):
        self.sweep()
        orders = self.store.rows_all()["standing_orders"]
        self.assertEqual(len(orders), len(proactive.DEFAULT_STANDING_ORDERS))
        self.assertEqual({o["order_id"] for o in orders},
                         {"SO-001", "SO-002", "SO-003", "SO-004",
                          "SO-005", "SO-006", "SO-007", "SO-008"})
        v1 = self.store.rows_all()["meta"]["version"]
        self.sweep(at(9, 30))  # لا جديد ← write-on-change: بلا كتابة
        v2 = self.store.rows_all()["meta"]["version"]
        self.assertEqual(v1, v2)

    def test_open_loops_ledger_built_and_closed_from_sources(self):
        self.seed(tasks=[task("مهمة أ", due=DAY - dt.timedelta(days=1)),
                         task("مهمة ب", status="منجزة")],
                  waiting_for=[{"task": "رد المورد", "expected_from": "المورد",
                                "expected_by": (DAY + dt.timedelta(days=2)).isoformat(),
                                "status": "WAITING"}])
        self.sweep()
        loops = {l["title"]: l for l in self.store.rows_all()["open_loops"]}
        self.assertEqual(loops["مهمة أ"]["kind"], "i_promised")
        self.assertEqual(loops["مهمة ب"]["status"], "CLOSED")
        self.assertEqual(loops["رد المورد"]["kind"], "they_promised")
        # إنجاز مهمة أ ← تُغلق حلقتها في الدورة التالية
        S = self.store.rows_all()
        S["tasks"][0]["الحالة"] = "منجزة"
        self.store.commit(S, "done")
        self.sweep(at(10))
        loops = {l["title"]: l for l in self.store.rows_all()["open_loops"]}
        self.assertEqual(loops["مهمة أ"]["status"], "CLOSED")

    # ---------------------------------------------------------- السلم والمسارات
    def test_green_act_creates_reversible_task_with_undo_payload(self):
        self.seed(tasks=[task("تسليم العرض", due=DAY + dt.timedelta(days=1))])
        self.sweep()
        acts = [a for a in self.by_kind("deadline_48h") if a["decision"] == "ACT"]
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["lane"], "GREEN")
        self.assertEqual(acts[0]["undo"]["op"], "remove_task")
        titles = [t["العنوان"] for t in self.store.rows_all()["tasks"]]
        self.assertIn("نافذة تركيز: تسليم العرض", titles)

    def test_meeting_within_30min_gets_prep_note_once(self):
        self.seed(meetings=[{"التاريخ": DAY, "الوقت": "09:20", "الموضوع": "لجنة الجودة",
                             "الحضور": "اللجنة", "الهدف": "اعتماد النموذج",
                             "التحضير المطلوب": "مسودة", "حالة التحضير": "ينقص: مسودة"}])
        self.sweep(at(9))
        acts = [a for a in self.by_kind("meeting_prep") if a["decision"] == "ACT"]
        self.assertEqual(len(acts), 1)
        self.sweep(at(9, 10))  # ضمن النافذة نفسها ← لا تكرار
        self.assertEqual(len(self.by_kind("meeting_prep")), 1)

    def test_external_comms_is_yellow_draft_pending_approval_never_sent(self):
        self.seed(waiting_for=[{"task": "رد المشتري", "expected_from": "المشتري",
                                "expected_by": (DAY + dt.timedelta(days=5)).isoformat(),
                                "since": (DAY - dt.timedelta(days=4)).isoformat(),
                                "status": "WAITING", "follow_up_draft": "متابعة لطيفة"}])
        self.sweep()
        rows = self.by_kind("aging_followup")
        self.assertEqual(rows[0]["decision"], "PREPARE")
        self.assertEqual(rows[0]["lane"], "YELLOW")
        queue = self.store.rows_all()["action_queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["status"], "PENDING_APPROVAL")
        self.assertIn("المشتري", queue[0]["content"])

    def test_money_is_red_alert_and_draft_but_never_executed(self):
        self.seed(finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=2)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep()
        rows = self.by_kind("bill_due")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "ALERT_DRAFT")
        self.assertEqual(rows[0]["lane"], "RED")
        queue = self.store.rows_all()["action_queue"]
        self.assertTrue(all(a["status"] == "PENDING_APPROVAL" for a in queue))
        self.assertFalse(any(a.get("executed_at") for a in queue))

    def test_confidence_below_threshold_prepares_instead_of_acting(self):
        cand = proactive._cand("k|1", "deadline_48h", "x", "y", "internal_sched",
                               3, 3, 0.5, "low", "reversible", "create_task")
        S = self.store.rows_all()
        S["standing_orders"] = [dict(o) for o in proactive.DEFAULT_STANDING_ORDERS]
        decision, lane, note = proactive.decide(
            cand, S, at(9), proactive.DEFAULT_CFG, proactive._feedback_rules(S))
        self.assertEqual((decision, lane), ("PREPARE", "YELLOW"))
        self.assertIn("ثقة", note)
        cand["confidence"] = 0.95
        decision, lane, _ = proactive.decide(
            cand, S, at(9), proactive.DEFAULT_CFG, proactive._feedback_rules(S))
        self.assertEqual((decision, lane), ("ACT", "GREEN"))

    def test_l0_category_only_suggests(self):
        cand = proactive._cand("k|2", "health_hint", "x", "y", "health", 2, 2, 0.9,
                               "low", "reversible", "create_task")
        S = self.store.rows_all()
        decision, lane, _ = proactive.decide(
            cand, S, at(9), proactive.DEFAULT_CFG, proactive._feedback_rules(S))
        self.assertEqual((decision, lane), ("SUGGEST", "INFO"))

    # ---------------------------------------------------------- الحواجز
    def test_quiet_hours_batch_noncritical_alerts(self):
        self.seed(finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=2)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep(at(23, 15))
        rows = self.by_kind("bill_due")
        self.assertEqual(rows[0]["decision"], "BATCHED")
        self.assertIn("هدوء", rows[0]["note"])

    def test_quiet_hours_critical_deadline_bypasses_and_is_logged(self):
        self.seed(finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=1)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep(at(23, 15))
        rows = self.by_kind("bill_due")
        self.assertEqual(rows[0]["decision"], "ALERT_DRAFT")

    def test_daily_alert_cap_batches_overflow(self):
        finance = [{"البند": f"اشتراك {i}", "النوع": "اشتراك",
                    "التكلفة (ريال/شهر)": 10,
                    "تاريخ التجديد": (DAY + dt.timedelta(days=1)).isoformat(),
                    "آخر استخدام": None, "ملاحظة": ""} for i in range(4)]
        self.seed(finance=finance)
        self.sweep(cfg={"max_alerts": 2})
        decisions = [a["decision"] for a in self.by_kind("bill_due")]
        self.assertEqual(decisions.count("ALERT_DRAFT"), 2)
        self.assertEqual(decisions.count("BATCHED"), 2)

    def test_pause_switch_halts_and_resume_restores(self):
        self.seed(tasks=[task("تسليم العرض", due=DAY + dt.timedelta(days=1))])
        proactive.pause(hours=4, store=self.store)
        summary = self.sweep(at(9))
        self.assertTrue(summary["paused"])
        self.assertEqual(self.ledger(), [])
        self.assertEqual(len(self.store.rows_all()["tasks"]), 1)  # لا مهام جديدة
        proactive.resume(store=self.store)
        summary = self.sweep(at(9))
        self.assertFalse(summary["paused"])
        self.assertGreater(len(self.ledger()), 0)
        self.assertIsNone(proactive.status(store=self.store)["paused_until"])

    def test_disabled_standing_order_skips_its_trigger(self):
        self.seed(meetings=[{"التاريخ": DAY, "الوقت": "09:20", "الموضوع": "اجتماع",
                             "الحضور": "", "الهدف": "", "التحضير المطلوب": "",
                             "حالة التحضير": "جاهز"}])
        self.sweep(at(7))  # خارج النافذة — بلا مرشحين بعد
        self.assertEqual(self.by_kind("meeting_prep"), [])
        proactive.set_order("SO-001", False, store=self.store)
        summary = self.sweep(at(9))  # داخل النافذة لكن الأمر موقوف ← لا ينطلق
        self.assertEqual(self.by_kind("meeting_prep"), [])
        self.assertEqual(summary["act"], 0)
        proactive.set_order("SO-001", True, store=self.store)
        self.sweep(at(9, 5))
        self.assertEqual(len(self.by_kind("meeting_prep")), 1)

    # ---------------------------------------------------------- الاستدراك
    def test_missed_commitment_triggers_recovery_with_report(self):
        self.seed(tasks=[task("عقد متأخر", due=DAY - dt.timedelta(days=2))])
        self.sweep()
        rec = self.by_kind("missed_recovery")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["decision"], "ACT")  # استدراك داخلي قابل للعكس
        loops = {l["title"]: l for l in self.store.rows_all()["open_loops"]}
        self.assertEqual(loops["عقد متأخر"]["status"], "RECOVERING")
        # تقرير الاستدراك بالصيغة المطلوبة داخل جسم مهمة الاستدراك
        task_notes = [t for t in self.store.rows_all()["tasks"]
                      if str(t.get("المصدر", "")).startswith("proactive")]
        self.assertTrue(task_notes)
        self.assertIn("ما فات", task_notes[0]["ملاحظات"])
        self.assertIn("خيارات الاستدراك", task_notes[0]["ملاحظات"])
        self.sweep(at(12))  # لا استدراك مكرر في اليوم نفسه
        self.assertEqual(len(self.by_kind("missed_recovery")), 1)

    def test_missed_waiting_recovery_is_draft_not_send(self):
        self.seed(waiting_for=[{"task": "رد العميل", "expected_from": "العميل",
                                "expected_by": (DAY - dt.timedelta(days=1)).isoformat(),
                                "since": (DAY - dt.timedelta(days=6)).isoformat(),
                                "status": "OVERDUE"}])
        self.sweep()
        rec = self.by_kind("missed_recovery")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["decision"], "PREPARE")
        queue = self.store.rows_all()["action_queue"]
        self.assertEqual(queue[0]["status"], "PENDING_APPROVAL")
        self.assertEqual(queue[0]["type"], "recovery_they_promised")

    # ---------------------------------------------------------- تعلّم
    def test_undo_reverts_green_act_and_blocks_refire(self):
        self.seed(tasks=[task("تسليم العرض", due=DAY + dt.timedelta(days=1))])
        self.sweep()
        pa = self.by_kind("deadline_48h")[0]["pa_id"]
        changed, removed = proactive.undo(pa, store=self.store)
        self.assertTrue(changed)
        self.assertEqual(removed, 1)
        titles = [t["العنوان"] for t in self.store.rows_all()["tasks"]]
        self.assertNotIn("نافذة تركيز: تسليم العرض", titles)
        row = self.by_kind("deadline_48h")[0]
        self.assertEqual(row["status"], "UNDONE")
        self.sweep(at(10))  # المحرك لا يعيد ما تراجعت عنه
        self.assertEqual(len(self.by_kind("deadline_48h")), 1)

    def test_feedback_never_suppresses_trigger_kind(self):
        self.seed(waiting_for=[{"task": "رد المشتري", "expected_from": "المشتري",
                                "expected_by": (DAY + dt.timedelta(days=6)).isoformat(),
                                "since": (DAY - dt.timedelta(days=4)).isoformat(),
                                "status": "WAITING"}])
        self.sweep()
        pa = self.by_kind("aging_followup")[0]["pa_id"]
        proactive.add_feedback(pa, "never", store=self.store)
        # دورة يوم جديد (مفتاح مختلف لكن النوع محظور الآن) ← حجب موثَّق لا تنفيذ
        proactive.sweep(store=self.store, now_dt=at(9) + dt.timedelta(days=1),
                        verbose=False)
        skipped = [a for a in self.ledger() if a["decision"] == "SKIPPED_FEEDBACK"]
        self.assertTrue(skipped)
        self.assertEqual(skipped[0]["kind"], "aging_followup")
        prepares = [a for a in self.by_kind("aging_followup")
                    if a["decision"] == "PREPARE"]
        self.assertEqual(len(prepares), 1)  # المسودة الأولى فقط — لا ثانية بعد «أبدًا»

    def test_feedback_much_demotes_to_brief_for_two_weeks(self):
        proactive.add_feedback("free_slot", "much", store=self.store)
        rules = proactive._feedback_rules(self.store.rows_all())
        cand = proactive._cand("k|3", "free_slot", "x", "y", "internal_sched",
                               2, 2, 0.8, "low", "reversible", "suggest")
        S = self.store.rows_all()
        decision, lane, note = proactive.decide(cand, S, at(9),
                                                proactive.DEFAULT_CFG, rules)
        self.assertEqual((decision, lane), ("SUGGEST", "INFO"))

    def test_red_alert_overrides_never_feedback_for_safety(self):
        proactive.add_feedback("bill_due", "never", store=self.store)
        self.seed(finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=1)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep()
        rows = self.by_kind("bill_due")
        self.assertIn(rows[0]["decision"], ("ALERT", "ALERT_DRAFT", "BATCHED"))
        self.assertIn("يتجاوزه", rows[0]["note"])

    # ---------------------------------------------------------- البريف
    def test_brief_renders_all_sections_and_registers_row(self):
        self.seed(tasks=[task("تسليم العرض", due=DAY + dt.timedelta(days=1))],
                  finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=1)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep()
        path = proactive.render_brief(store=self.store, now_dt=at(9, 30),
                                      reports_dir=self.reports)
        md = Path(path).read_text(encoding="utf-8")
        for marker in ("أهم 3", "ما فعلته دون أن تطلب", "تنبيهات",
                       "مسودات تنتظر اعتمادك", "حالة الحواجز", "undo"):
            self.assertIn(marker, md)
        briefs = self.store.rows_all()["proactive_briefs"]
        self.assertEqual(len(briefs), 1)
        v = self.store.rows_all()["meta"]["version"]
        proactive.render_brief(store=self.store, now_dt=at(10),
                               reports_dir=self.reports)  # نفس اليوم ← استبدال لا تكرار
        self.assertEqual(len(self.store.rows_all()["proactive_briefs"]), 1)

    # ---------------------------------------------------------- الحوكمة الصلبة
    def test_nothing_external_is_ever_executed_by_engine(self):
        self.seed(tasks=[task("عقد متأخر", due=DAY - dt.timedelta(days=2)),
                         task("تسليم العرض", due=DAY + dt.timedelta(days=1))],
                  waiting_for=[{"task": "رد", "expected_from": "عميل",
                                "expected_by": (DAY - dt.timedelta(days=1)).isoformat(),
                                "since": (DAY - dt.timedelta(days=5)).isoformat(),
                                "status": "OVERDUE"}],
                  finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=1)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep()
        queue = self.store.rows_all()["action_queue"]
        self.assertTrue(queue, "متوقع مسودات في الطابور")
        for a in queue:
            self.assertEqual(a["status"], "PENDING_APPROVAL")
            self.assertIsNone(a["approved_at"])
            self.assertIsNone(a["executed_at"])

    # ---------------------------------------------------------- قناة تيليجرام المستعجلة
    PUSH_ENV_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID",
                     "PROACTIVE_TELEGRAM_PUSH")

    def _isolate_env(self):
        saved = {v: os.environ.get(v) for v in self.PUSH_ENV_VARS}

        def restore():
            for v, val in saved.items():
                if val is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = val

        self.addCleanup(restore)

    def _enable_push(self, record):
        self._isolate_env()
        os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
        os.environ["TELEGRAM_ALLOWED_CHAT_ID"] = "12345"
        os.environ.pop("PROACTIVE_TELEGRAM_PUSH", None)
        original = proactive._telegram_send

        def fake_send(text, chat_id=None, token=None, timeout=15):
            record.append((chat_id, token, text))
            return True

        proactive._telegram_send = fake_send
        self.addCleanup(setattr, proactive, "_telegram_send", original)

    def _seed_bill(self, days=1):
        self.seed(finance=[{"البند": "اشتراك", "النوع": "اشتراك",
                            "التكلفة (ريال/شهر)": 100,
                            "تاريخ التجديد": (DAY + dt.timedelta(days=days)).isoformat(),
                            "آخر استخدام": None, "ملاحظة": ""}])

    def test_red_alert_is_pushed_to_telegram_once(self):
        pushed = []
        self._enable_push(pushed)
        self._seed_bill(days=1)
        summary = self.sweep()
        self.assertEqual(summary["pushed"], 1)
        chat, token, text = pushed[0]
        self.assertEqual((chat, token), ("12345", "test-token"))
        self.assertIn("⛔", text)
        self.assertIn("استحقاق مالي وشيك: اشتراك", text)
        self.assertIn("undo PA-", text)
        pushed.clear()
        self.sweep(at(10))  # نفس المفتاح ← لا دفع مكرر
        self.assertEqual(pushed, [])

    def test_batched_alerts_are_not_pushed(self):
        pushed = []
        self._enable_push(pushed)
        self._seed_bill(days=2)  # دون عتبة اليوم الواحد ← ساعات الهدوء تحجبه
        self.sweep(at(23, 15))
        self.assertEqual(self.by_kind("bill_due")[0]["decision"], "BATCHED")
        self.assertEqual(pushed, [])

    def test_quiet_override_alert_still_pushes_with_note(self):
        pushed = []
        self._enable_push(pushed)
        self._seed_bill(days=1)  # override_quiet — يتجاوز الهدوء موثَّقًا
        self.sweep(at(23, 15))
        self.assertEqual(len(pushed), 1)
        self.assertIn("الهدوء", pushed[0][2])

    def test_push_disabled_by_env(self):
        pushed = []
        self._enable_push(pushed)
        os.environ["PROACTIVE_TELEGRAM_PUSH"] = "0"
        self._seed_bill(days=1)
        summary = self.sweep()
        self.assertEqual(summary["pushed"], 0)
        self.assertEqual(pushed, [])
        self.assertEqual(proactive.telegram_push_status(), "disabled_env")

    def test_push_unconfigured_is_safe_and_reported(self):
        self._isolate_env()
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_ALLOWED_CHAT_ID", None)
        os.environ.pop("PROACTIVE_TELEGRAM_PUSH", None)
        self._seed_bill(days=1)
        summary = self.sweep()  # لا قناة ← الدورة تكمل بلا دفع ولا خطأ
        self.assertEqual(summary["pushed"], 0)
        self.assertEqual(proactive.telegram_push_status(), "no_token")
        self.assertEqual(proactive.status(store=self.store)["telegram_push"], "no_token")

    def test_push_network_failure_never_breaks_sweep(self):
        self._enable_push([])
        proactive._telegram_send = lambda *a, **k: (_ for _ in ()).throw(
            ConnectionError("الشبكة مقطوعة"))
        self._seed_bill(days=1)
        summary = self.sweep()
        self.assertEqual(summary["pushed"], 0)
        self.assertEqual(self.by_kind("bill_due")[0]["decision"], "ALERT_DRAFT")

    def test_push_test_command_paths(self):
        pushed = []
        self._enable_push(pushed)
        code, why = proactive.push_test()
        self.assertEqual((code, why), (0, "sent"))
        self.assertTrue(pushed)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        code, why = proactive.push_test()
        self.assertEqual((code, why), (1, "no_token"))

    # ---------------------------------------------------------- مراجعة الأسبوع والعتبات
    def _pa_row(self, pa_id, kind, decision, day, action_id=None, status="DONE"):
        row = {"pa_id": pa_id, "ts": dt.datetime(day.year, day.month, day.day, 9,
                                                 tzinfo=TZ).isoformat(timespec="seconds"),
               "key": f"{kind}|x|{day}", "kind": kind, "title": "x",
               "category": "money", "impact": 4, "urgency": 4, "confidence": 0.9,
               "reversibility": "irreversible", "risk": "high", "score": 10.0,
               "lane": "RED", "decision": decision, "note": "",
               "standing_order": None, "result": {}, "undo": None, "status": status}
        if action_id:
            row["result"] = {"action_id": action_id}
        return row

    def _aq_row(self, aq_id, qstatus):
        return {"action_id": aq_id, "type": "payment_instruction", "channel": "wa/email",
                "content": "x", "content_hash": "h" + aq_id, "status": qstatus,
                "created_at": DAY.isoformat(),
                "expires_at": (DAY + dt.timedelta(days=2)).isoformat(),
                "approved_at": None, "executed_at": None}

    def _seed_ledger(self, pa_rows, q_rows, feedback=None):
        S = self.store.rows_all()
        S["proactive_actions"] = pa_rows
        S["action_queue"] = q_rows
        S["proactive_feedback"] = feedback or []
        self.store.commit(S, "seed_ledger")

    def test_acceptance_report_math_and_window(self):
        d = lambda n: DAY - dt.timedelta(days=n)
        pa = [self._pa_row("PA-1", "bill_due", "ALERT_DRAFT", d(1), "A-001"),
              self._pa_row("PA-2", "bill_due", "ALERT_DRAFT", d(2), "A-002"),
              self._pa_row("PA-3", "renewal_watch", "PREPARE", d(3), "A-003"),
              self._pa_row("PA-4", "renewal_watch", "PREPARE", d(4), "A-004"),
              self._pa_row("PA-5", "missed_recovery", "ACT", d(2)),
              self._pa_row("PA-6", "missed_recovery", "ACT", d(1), None, "UNDONE"),
              self._pa_row("PA-OLD", "bill_due", "ALERT_DRAFT", d(30), "A-OLD")]
        aq = [self._aq_row("A-001", "EXECUTED"), self._aq_row("A-002", "REJECTED"),
              self._aq_row("A-003", "EXPIRED"), self._aq_row("A-004", "PENDING_APPROVAL"),
              self._aq_row("A-OLD", "EXECUTED")]
        fb = [{"target": "free_slot", "pa_id": None, "signal": "never", "scope": "kind",
               "until": None, "at": dt.datetime(DAY.year, DAY.month, DAY.day, 8,
                                                tzinfo=TZ).isoformat(timespec="seconds")}]
        self._seed_ledger(pa, aq, fb)
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        self.assertEqual(rep["flow"], {"accepted": 1, "rejected": 1, "expired": 1,
                                       "pending": 1, "missing": 0})  # القديم خارج النافذة
        self.assertEqual(rep["decided"], 3)
        self.assertAlmostEqual(rep["approval_rate"], 1 / 3, places=2)
        self.assertEqual(rep["acts"], 2)
        self.assertAlmostEqual(rep["undone_rate"], 0.5, places=2)
        self.assertEqual(rep["per_kind"]["bill_due"]["accepted"], 1)
        self.assertEqual(rep["per_kind"]["renewal_watch"]["expired"], 1)
        self.assertEqual(rep["feedback"], {"good": 0, "much": 0, "never": 1})
        txt = proactive.review_text(store=self.store, days=7, today=DAY)
        self.assertIn("معدل القبول", txt)
        # 3 قرارات فقط < الحد الأدنى 5 ← عرض بلا تعديل (الحماية من التسرّب المبكر)
        self.assertIn("بيانات غير كافية", txt)

    def test_review_insufficient_data_blocks_tuning(self):
        self._seed_ledger([self._pa_row("PA-1", "bill_due", "PREPARE", DAY, "A-001")],
                          [self._aq_row("A-001", "EXECUTED")])
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        recs, notes = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs, {})
        self.assertIn("بيانات غير كافية", notes[0])
        self.assertEqual(proactive.apply_tuning(recs, store=self.store), {})
        markers = self.store.rows_all()["manager_markers"]
        self.assertNotIn("proactive_cfg", markers)

    def test_high_acceptance_lowers_threshold_and_apply_persists(self):
        d = lambda n: DAY - dt.timedelta(days=n)
        pa = [self._pa_row(f"PA-{i}", "bill_due", "ALERT_DRAFT", d(i % 3), f"A-0{i:02d}")
              for i in range(1, 7)]
        aq = [self._aq_row(f"A-0{i:02d}", "EXECUTED") for i in range(1, 7)]
        self._seed_ledger(pa, aq)
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        self.assertEqual(rep["approval_rate"], 1.0)
        recs, _ = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs, {"confidence_act": 0.75})
        applied = proactive.apply_tuning(recs, store=self.store)
        self.assertEqual(applied, {"confidence_act": 0.75})
        self.assertEqual(proactive.resolve_cfg(self.store)["confidence_act"], 0.75)
        # الحد الأدنى يمنع الانحدار دون 0.70 مهما تكرر التطبيق
        proactive.apply_tuning({"confidence_act": 0.40}, store=self.store)
        self.assertEqual(proactive.resolve_cfg(self.store)["confidence_act"], 0.70)

    def test_rejections_or_undos_raise_threshold(self):
        d = lambda n: DAY - dt.timedelta(days=n)
        pa = [self._pa_row("PA-1", "bill_due", "PREPARE", d(1), "A-001"),
              self._pa_row("PA-2", "bill_due", "PREPARE", d(1), "A-002"),
              self._pa_row("PA-3", "bill_due", "PREPARE", d(1), "A-003"),
              self._pa_row("PA-4", "bill_due", "PREPARE", d(1), "A-004"),
              self._pa_row("PA-5", "bill_due", "PREPARE", d(1), "A-005")]
        aq = [self._aq_row("A-001", "EXECUTED")] + \
             [self._aq_row(f"A-00{i}", "REJECTED") for i in (2, 3, 4, 5)]
        self._seed_ledger(pa, aq)
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        recs, _ = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs, {"confidence_act": 0.9})
        # تراجع ≥30% أيضًا يشدّد حتى مع قبول مرتفع (عينة ≥5 إجراءات لتجاوز الحارس)
        pa2 = ([self._pa_row(f"PX-{i}", "missed_recovery", "ACT", d(1)) for i in range(3)]
               + [self._pa_row(f"PX-9{i}", "missed_recovery", "ACT", d(1), None, "UNDONE")
                  for i in range(2)])
        self._seed_ledger(pa2, [])
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        self.assertGreaterEqual(rep["undone_rate"], 0.30)
        recs, _ = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs.get("confidence_act"), 0.9)

    def test_cap_hit_with_happy_user_raises_max_alerts(self):
        d = lambda n: DAY - dt.timedelta(days=n)
        pa, aq = [], []
        for day_i in range(3):  # ثلاثة أيام امتلأ فيها السقف 6/6
            for i in range(6):
                pid = f"PA-{day_i}{i}"
                pa.append(self._pa_row(pid, "bill_due", "ALERT_DRAFT", d(day_i), f"A-{day_i}{i}"))
                aq.append(self._aq_row(f"A-{day_i}{i}", "EXECUTED"))
        self._seed_ledger(pa, aq)
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        self.assertEqual(rep["cap_hit_days"], 3)
        recs, _ = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs["max_alerts"], 8)
        applied = proactive.apply_tuning({"max_alerts": 99}, store=self.store)
        self.assertEqual(applied["max_alerts"], 12)  # السقف الأقصى مضبوط

    def test_never_feedback_lowers_max_alerts(self):
        fb = [{"target": "x", "pa_id": None, "signal": "never", "scope": "kind",
               "until": None, "at": dt.datetime(DAY.year, DAY.month, DAY.day, 8,
                                                tzinfo=TZ).isoformat(timespec="seconds")}
              for _ in range(2)]
        pa = [self._pa_row(f"PA-{i}", "bill_due", "PREPARE", DAY, f"A-00{i}")
              for i in range(1, 7)]
        aq = [self._aq_row(f"A-00{i}", "EXECUTED") for i in range(1, 7)]
        self._seed_ledger(pa, aq, fb)
        rep = proactive.acceptance_report(store=self.store, days=7, today=DAY)
        recs, notes = proactive.tuning_recommendations(rep, proactive.DEFAULT_CFG)
        self.assertEqual(recs["max_alerts"], 5)
        self.assertIn("أبدًا", " ".join(notes))

    def test_stored_override_changes_sweep_behavior(self):
        # عتبة 0.95 المخزنة تجعل مرشح 0.9 يجهّز بدل أن ينفّذ
        proactive.apply_tuning({"confidence_act": 0.95}, store=self.store)
        self.seed(tasks=[task("تسليم العرض", due=DAY + dt.timedelta(days=1))])
        self.sweep()
        rows = self.by_kind("deadline_48h")
        self.assertEqual(rows[0]["decision"], "PREPARE")
        self.assertIn("0.95", rows[0]["note"])

    def test_review_text_reports_effective_settings(self):
        proactive.apply_tuning({"max_alerts": 8}, store=self.store)
        self._seed_ledger([self._pa_row("PA-1", "bill_due", "PREPARE", DAY, "A-001")],
                          [self._aq_row("A-001", "EXECUTED")])
        txt = proactive.review_text(store=self.store, days=7, today=DAY)
        self.assertIn("max_alerts=8", txt)
        self.assertIn("(بيئة 6)", txt)

    def test_collision_and_travel_and_renewal_candidates(self):
        self.seed(meetings=[
            {"التاريخ": DAY, "الوقت": "10:00", "الموضوع": "أ", "الحضور": "",
             "الهدف": "", "التحضير المطلوب": "", "حالة التحضير": "جاهز"},
            {"التاريخ": DAY, "الوقت": "10:30", "الموضوع": "سفر إلى الدمام",
             "الحضور": "", "الهدف": "", "التحضير المطلوب": "",
             "حالة التحضير": "جاهز"}],
            finance=[{"البند": "أداة", "النوع": "اشتراك", "التكلفة (ريال/شهر)": 30,
                      "تاريخ التجديد": (DAY + dt.timedelta(days=6)).isoformat(),
                      "آخر استخدام": None, "ملاحظة": ""}])
        self.sweep(at(8))
        kinds = {a["kind"] for a in self.ledger()}
        self.assertIn("calendar_conflict", kinds)
        self.assertIn("travel_24h", kinds)
        self.assertIn("renewal_watch", kinds)
        # التجديد البعيد تجهيز فقط (لا تنبيه أحمر بعد 7 أيام)
        rw = self.by_kind("renewal_watch")[0]
        self.assertEqual(rw["decision"], "PREPARE")


class ProactiveConfigStoreTests(unittest.TestCase):
    """طبقة الإعدادات في v1.1: ساعات الهدوء والسقف تُخزَّن في الحالة وتعلو البيئة."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        saved = {k: os.environ.get(k) for k in
                 ("PROACTIVE_QUIET_START", "PROACTIVE_QUIET_END", "PROACTIVE_MAX_ALERTS",
                  "PROACTIVE_CONFIDENCE_THRESHOLD")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        for k in saved:
            os.environ.pop(k, None)

    def seed_bill(self, days=2):
        S = self.store.rows_all()
        S["finance"] = [{"البند": "اشتراك", "النوع": "اشتراك", "التكلفة (ريال/شهر)": 100,
                         "تاريخ التجديد": (DAY + dt.timedelta(days=days)).isoformat(),
                         "آخر استخدام": None, "ملاحظة": ""}]
        self.store.commit(S, "seed")

    def sweep(self, when):
        return proactive.sweep(store=self.store, now_dt=when, verbose=False)

    # ------------------------- الحدود والتحقق -------------------------
    def test_quiet_hours_and_cap_are_now_storable(self):
        self.assertEqual(set(proactive.CFG_OVERRIDABLE),
                         {"confidence_act", "max_alerts", "quiet_start", "quiet_end"})

    def test_sanitize_clamps_numbers_and_normalizes_times(self):
        clean, notes = proactive.sanitize_cfg({"max_alerts": 99, "confidence_act": 0.2,
                                               "quiet_start": "9:5", "quiet_end": "10:30"})
        self.assertEqual(clean["max_alerts"], 12)
        self.assertEqual(clean["confidence_act"], 0.7)
        self.assertEqual(clean["quiet_start"], "09:05")   # تُهيّأ إلى HH:MM
        self.assertEqual(len(notes), 2)          # ملاحظة لكل قيمة جُهزت إلى الحد

    def test_sanitize_rejects_garbage_and_a_silencing_window(self):
        for bad in ({"quiet_start": "25:70"}, {"quiet_start": "ليل"}, {"unknown": 1}):
            clean, errors = proactive.sanitize_cfg(bad)
            self.assertEqual(clean, {})
            self.assertTrue(errors)
        # نافذة صفرية، ونافذة تبتلع اليوم كله ← رفض لا تطبيق
        for pair in (({"quiet_start": "06:30", "quiet_end": "06:30"}),
                     ({"quiet_start": "06:31", "quiet_end": "06:30"})):
            clean, errors = proactive.sanitize_cfg(pair)
            self.assertEqual({k for k in clean if k.startswith("quiet")}, set())
            self.assertTrue(errors)

    def test_long_quiet_window_needs_an_explicit_permission(self):
        # قلب الساعات سهوًا شائع (07:00–23:00 بدل 23:00–07:00) ← لا يُقبل بصمت
        clean, errors = proactive.sanitize_cfg({"quiet_start": "07:00", "quiet_end": "23:00"})
        self.assertEqual({k for k in clean if k.startswith("quiet")}, set())
        self.assertIn("--force", errors[0])
        clean2, errors2 = proactive.sanitize_cfg({"quiet_start": "07:00", "quiet_end": "23:00"},
                                                 allow_long=True)
        self.assertEqual((clean2["quiet_start"], clean2["quiet_end"]), ("07:00", "23:00"))
        self.assertEqual(errors2, [])
        # لكن >22 ساعة مرفوض مطلقًا — لا رخصة فيه
        clean3, errors3 = proactive.sanitize_cfg({"quiet_start": "06:31", "quiet_end": "06:30"},
                                                 allow_long=True)
        self.assertEqual({k for k in clean3 if k.startswith("quiet")}, set())
        self.assertTrue(errors3)

    def test_quiet_span_wraps_midnight(self):
        self.assertEqual(proactive.quiet_span_hours("22:00", "06:30"), 8.5)
        self.assertEqual(proactive.quiet_span_hours("23:00", "05:00"), 6.0)

    # ------------------------- التخزين والأولوية -------------------------
    def test_set_cfg_persists_to_state_and_survives_reload(self):
        stored, applied, errors = proactive.set_cfg(
            {"quiet_start": "23:30", "quiet_end": "05:45", "max_alerts": 4}, store=self.store)
        self.assertEqual(errors, [])
        markers = Store(path=self.store.path).rows_all()["manager_markers"]
        self.assertEqual(markers["proactive_cfg"], {"quiet_start": "23:30", "quiet_end": "05:45",
                                                    "max_alerts": 4})
        self.assertEqual(proactive.resolve_cfg(self.store)["quiet_start"], "23:30")
        st = proactive.status(self.store)
        self.assertEqual(st["quiet_window"], "23:30–05:45")
        self.assertEqual(st["cfg_overrides"]["max_alerts"], 4)

    def test_state_override_beats_environment(self):
        os.environ["PROACTIVE_QUIET_START"] = "00:00"
        os.environ["PROACTIVE_QUIET_END"] = "01:00"
        proactive.set_cfg({"quiet_start": "20:00", "quiet_end": "07:00"}, store=self.store)
        eff = proactive.resolve_cfg(self.store)
        self.assertEqual((eff["quiet_start"], eff["quiet_end"]), ("20:00", "07:00"))
        sources = proactive.cfg_sources(self.store)
        self.assertEqual(sources["quiet_start"]["source"], "state")
        self.assertEqual(sources["aging_days"]["source"], "default")

    def test_clear_cfg_falls_back_off_the_stored_value(self):
        # البيئة تُقرأ عند الاستيراد (DEFAULT_CFG)، فالعبرة هنا: الحذف يُسقط التجاوز
        proactive.set_cfg({"max_alerts": 9, "quiet_start": "20:00"}, store=self.store)
        self.assertEqual(proactive.resolve_cfg(self.store)["max_alerts"], 9)
        kept = proactive.clear_cfg(["max_alerts"], store=self.store)
        self.assertEqual(kept, {"quiet_start": "20:00"})     # الباقي لم يُمسّ
        self.assertEqual(proactive.resolve_cfg(self.store)["max_alerts"],
                         proactive.DEFAULT_CFG["max_alerts"])
        self.assertEqual(proactive.resolve_cfg(self.store)["quiet_start"], "20:00")
        self.assertEqual(proactive.clear_cfg(store=self.store), {})
        self.assertEqual(proactive.resolve_cfg(self.store)["quiet_start"],
                         proactive.DEFAULT_CFG["quiet_start"])

    def test_set_cfg_rejects_everything_when_all_keys_invalid(self):
        with self.assertRaises(ValueError):
            proactive.set_cfg({"quiet_start": "بالمساء"}, store=self.store)
        self.assertNotIn("proactive_cfg", self.store.rows_all()["manager_markers"])

    # ------------------------- الأثر السلوكي -------------------------
    def test_stored_quiet_window_changes_the_lane_in_the_same_sweep(self):
        # 09:00 ليس هدوءًا افتراضيًا ← تنبيه؛ ثم نفس التوقيت بعد تخزين نافذة هدوء ← تأجيل
        self.seed_bill(days=2)
        self.sweep(at(9))
        self.assertEqual(self.by_kind("bill_due")[0]["decision"], "ALERT_DRAFT")

        fresh = Store(path=str(Path(self.tmp.name) / "state2.json"))
        S = fresh.rows_all()
        S["finance"] = self.store.rows_all()["finance"]
        fresh.commit(S, "seed2")
        proactive.set_cfg({"quiet_start": "08:00", "quiet_end": "10:00"}, store=fresh)
        proactive.sweep(store=fresh, now_dt=at(9), verbose=False)
        row = [a for a in fresh.rows_all()["proactive_actions"] if a["kind"] == "bill_due"][0]
        self.assertEqual(row["decision"], "BATCHED")
        self.assertIn("هدوء", row["note"])

    def by_kind(self, kind):
        return [a for a in self.store.rows_all()["proactive_actions"] if a["kind"] == kind]

    # ------------------------- العرض -------------------------
    def test_config_text_shows_source_of_truth(self):
        proactive.set_cfg({"quiet_start": "21:00"}, store=self.store)
        text = proactive.config_text(store=self.store)
        self.assertIn("21:00–06:30 (9.5 س)", text)     # النافذة محسوبة بالالتفاف
        self.assertIn("← state", text)
        self.assertIn("← default", text)
        self.assertIn("engine/proactive.py config", text)

    def test_review_reports_the_stored_source(self):
        def seed(S):
            S["proactive_actions"] = [{"pa_id": "PA-0001", "kind": "bill_due",
                                       "ts": at(9).isoformat(), "decision": "ALERT_DRAFT",
                                       "title": "فاتورة", "category": "money", "key": "k1"}]
            return True, None
        self.store.transaction(seed, "seed_ledger")
        proactive.set_cfg({"max_alerts": 3, "quiet_start": "21:00"}, store=self.store)
        text = proactive.review_text(store=self.store, days=7, today=DAY)
        self.assertIn("من الحالة", text)
        self.assertIn("ساعات الهدوء: 21:00–06:30", text)
        self.assertIn("(تجاوز مخزّن)", text)

if __name__ == "__main__":
    unittest.main()
