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


if __name__ == "__main__":
    unittest.main()
