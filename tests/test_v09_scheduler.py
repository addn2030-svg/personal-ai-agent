# -*- coding: utf-8 -*-
"""Offline tests for v0.9 automation scheduler (Riyadh time windows,
daily/weekly/monthly due rules, idempotent dispatch, approval queue only)."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store
import scheduler

TZ = ZoneInfo("Asia/Riyadh")
JOBS = {j["job_id"]: j for j in scheduler.JOB_SPECS}


def ref(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        scheduler.REPORTS = os.path.join(self.tmp.name, "reports")
        os.makedirs(scheduler.REPORTS, exist_ok=True)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))

    # ------------------------- قواعد الاستحقاق -------------------------
    def test_daily_windows(self):
        # الخميس 16:00 (بعد الإغلاق) → مستحق
        self.assertTrue(scheduler.is_due(JOBS["daily.supervisor_close_1600"],
                                         ref(2026, 9, 17, 16, 0)))
        # قبل الموعد → غير مستحق
        self.assertFalse(scheduler.is_due(JOBS["daily.supervisor_close_1600"],
                                          ref(2026, 9, 17, 15, 59)))
        # الجمعة (عطلة) → غير مستحق رغم الوقت
        self.assertFalse(scheduler.is_due(JOBS["daily.supervisor_close_1600"],
                                          ref(2026, 9, 18, 16, 0)))
        # البريف الصباحي في أي يوم بعد 06:45
        self.assertTrue(scheduler.is_due(JOBS["daily.morning_brief_0645"],
                                         ref(2026, 9, 13, 7, 0)))  # أحد
        self.assertTrue(scheduler.is_due(JOBS["daily.morning_brief_0645"],
                                         ref(2026, 9, 18, 7, 0)))  # جمعة

    def test_weekly_windows(self):
        # الأحد 07:15
        self.assertTrue(scheduler.is_due(JOBS["weekly.ops_sunday_0715"],
                                         ref(2026, 9, 13, 7, 15)))
        self.assertFalse(scheduler.is_due(JOBS["weekly.ops_sunday_0715"],
                                          ref(2026, 9, 14, 7, 15)))  # الاثنين
        # الثلاثاء 14:00 DHS
        self.assertTrue(scheduler.is_due(JOBS["weekly.dhs_tuesday_1400"],
                                         ref(2026, 9, 15, 14, 0)))
        # الخميس 07:00 مالية
        self.assertTrue(scheduler.is_due(JOBS["weekly.finance_thursday_0700"],
                                         ref(2026, 9, 17, 7, 0)))
        # الجمعة 16:00 خريطة الأسبوع
        self.assertTrue(scheduler.is_due(JOBS["weekly.weekly_mindmap_friday_1600"],
                                         ref(2026, 9, 18, 16, 0)))

    def test_monthly_windows(self):
        # يوم 28
        self.assertTrue(scheduler.is_due(JOBS["monthly.monthly_prod_28"],
                                         ref(2026, 9, 28, 7, 0)))
        self.assertFalse(scheduler.is_due(JOBS["monthly.monthly_prod_28"],
                                          ref(2026, 9, 27, 7, 0)))
        # أول الشهر
        self.assertTrue(scheduler.is_due(JOBS["monthly.monthly_finance_health_1st"],
                                         ref(2026, 10, 1, 7, 30)))
        # آخر يوم في الشهر
        self.assertTrue(scheduler.is_due(JOBS["monthly.monthly_context_archive_end"],
                                         ref(2026, 9, 30, 23, 30)))
        self.assertFalse(scheduler.is_due(JOBS["monthly.monthly_context_archive_end"],
                                          ref(2026, 9, 29, 23, 30)))

    # ------------------------- التنفيذ الآمن -------------------------
    def test_dispatch_enqueues_draft_only_and_is_idempotent(self):
        # الخميس 16:30: إغلاق الوحدات مستحق
        n1, s1 = scheduler.dispatch_due(ref(2026, 9, 17, 16, 30), store=self.store)
        self.assertGreaterEqual(n1, 1)
        S = self.store.rows_all()
        drafts = [a for a in S["action_queue"]
                  if a.get("origin", "").startswith("scheduler:")]
        self.assertTrue(drafts)
        self.assertTrue(all(a["status"] == "PENDING_APPROVAL" for a in drafts))
        # نفس الدقيقة مرة ثانية → لا تكرار (idempotent)
        n2, s2 = scheduler.dispatch_due(ref(2026, 9, 17, 16, 31), store=self.store)
        self.assertEqual(n2, 0)
        S2 = self.store.reload().rows_all()
        drafts2 = [a for a in S2["action_queue"]
                   if a.get("origin", "").startswith("scheduler:")]
        self.assertEqual(len(drafts2), len(drafts))

    def test_dispatch_nothing_due_at_0300(self):
        n, s = scheduler.dispatch_due(ref(2026, 9, 17, 3, 0), store=self.store)
        self.assertEqual((n, s), (0, 0))

    def test_dispatch_sunday_morning_weekly_ops(self):
        n, _s = scheduler.dispatch_due(ref(2026, 9, 13, 7, 20), store=self.store)
        self.assertGreaterEqual(n, 1)
        S = self.store.reload().rows_all()
        content = "\n".join(a["content"] for a in S["action_queue"])
        self.assertIn("التوجيه التشغيلي الأسبوعي", content)

    def test_monthly_prod_generates_file_then_draft(self):
        n, _s = scheduler.dispatch_due(ref(2026, 9, 28, 8, 0), store=self.store)
        self.assertGreaterEqual(n, 1)
        f = os.path.join(scheduler.REPORTS, "monthly-executive-2026-09.md")
        self.assertTrue(os.path.exists(f))

    def test_today_actions_seeded_once(self):
        n1 = scheduler.today_actions(store=self.store)
        self.assertEqual(n1, 3)
        S = self.store.rows_all()
        actions = [a for a in S["action_queue"]
                   if a.get("origin") == "scheduler:today-actions"]
        self.assertEqual(len(actions), 3)
        joined = " ".join(a["content"] for a in actions)
        self.assertIn("17 سبتمبر 2026", joined)   # تكليف DHS
        self.assertIn("NEEDS_INPUT", joined)      # شيت خطة الإنجاز
        n2 = scheduler.today_actions(store=self.store)
        self.assertEqual(n2, 0)  # لا ازدواج
        self.assertEqual(len(self.store.reload().rows_all()["action_queue"]), 3)

    def test_schedule_sync_creates_eleven_jobs(self):
        rows = scheduler.sync_schedule_to_state(store=self.store)
        self.assertEqual(len(rows), 11)


if __name__ == "__main__":
    unittest.main()
