# -*- coding: utf-8 -*-
"""Offline tests for v1.1 automatic timing (cron kernel + in-container worker).

Covers: env-driven schedule, daily/weekly/interval due rules, catch-up after a
missed tick, cycle-key idempotency, failure backoff, the overlap lock, the
morning-brief card, crontab line generation, the zero-external-effect rule
(morning brief never sends unless the Telegram channel is configured), and the
webhook worker's start/stop contract.
"""
import contextlib
import datetime as dt
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store  # noqa: E402
import timing  # noqa: E402 — نفس الكائن الذي يستدعيه البوت والـ webhook worker

TZ = ZoneInfo("Asia/Riyadh")
DAY = dt.date(2026, 9, 11)  # جمعة
JOB_BY_KIND = {j["kind"]: j["job_id"] for j in timing.JOB_SPECS}


def at(hh, mm=0, day=DAY):
    return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


class TimingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = Path(self.tmp.name) / "state.json"
        self.store = Store(path=str(self.state_path))
        env = {"AI_OS_DATA_DIR": self.tmp.name, "TIMING_PUSH": "0",
               "AIOS_TIMING_ENABLED": "1", "MANAGER_TIMEZONE": "Asia/Riyadh"}
        for k in ("TIMING_BRIEF_AT", "TIMING_SWEEP_INTERVAL_HOURS", "TIMING_TICK_SECONDS",
                  "TIMING_RETRY_MINUTES", "TIMING_REVIEW_AT", "TIMING_REVIEW_WEEKDAY",
                  "TIMING_BRIEF_ENABLED", "TIMING_SWEEP_ENABLED", "TIMING_REVIEW_ENABLED",
                  "TIMING_REVIEW_APPLY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
            env.setdefault(k, "")
        self._env = patch.dict(os.environ, env, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for k, v in env.items():
            if v == "":
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.lock_file = str(Path(self.tmp.name) / ".timing.lock")
        lockfix = patch.object(timing, "lock_path", lambda: self.lock_file)
        lockfix.start()
        self.addCleanup(lockfix.stop)

    # ---------------- helpers ----------------
    def runs(self):
        return self.store.rows_all().get("timing_runs", [])

    def stub_handlers(self, calls, fail_with=None):
        """يستبدل المنفّذات الثلاثة بمراقبة: يسجّل النداءات ويعيد نتيجة ناجحة/فاشلة."""
        def make(kind):
            def handler(store=None, ref=None, c=None, **kw):
                calls.append(kind)
                if fail_with and kind in fail_with:
                    raise RuntimeError(f"تعطل مصطنع في {kind}")
                return True, {"kind": kind, "at": ref.isoformat(timespec="minutes")}
            return handler
        return patch.dict(timing.HANDLERS,
                          {k: make(k) for k in ("brief", "sweep", "review")})


class ScheduleConfigTests(TimingTestCase):
    def test_defaults_match_the_agreed_schedule(self):
        c = timing.cfg()
        self.assertTrue(c["enabled"])
        self.assertEqual(c["jobs"]["brief"]["time"], "06:30")
        self.assertEqual(c["jobs"]["sweep"]["interval_hours"], 3)
        self.assertEqual(c["jobs"]["review"]["time"], "07:00")
        self.assertEqual(c["jobs"]["review"]["weekday"], 6)   # الأحد
        self.assertEqual(c["tick_seconds"], 300)

    def test_env_overrides_are_read_per_call(self):
        os.environ["TIMING_BRIEF_AT"] = "07:15"
        os.environ["TIMING_SWEEP_INTERVAL_HOURS"] = "6"
        os.environ["AIOS_TIMING_ENABLED"] = "0"
        c = timing.cfg()
        self.assertEqual(c["jobs"]["brief"]["time"], "07:15")
        self.assertEqual(c["jobs"]["sweep"]["interval_hours"], 6)
        self.assertFalse(c["enabled"])
        # قيمة فاسدة لا تكسر الجدولة — ترجع للافتراضي
        os.environ["TIMING_SWEEP_INTERVAL_HOURS"] = "ثلاث"
        self.assertEqual(timing.cfg()["jobs"]["sweep"]["interval_hours"], 3)
        os.environ["TIMING_BRIEF_AT"] = "بعد الفجر"
        self.assertEqual(timing.cfg()["jobs"]["brief"]["time"], "06:30")

    def test_disabled_job_is_excluded_from_due_list(self):
        os.environ["TIMING_BRIEF_ENABLED"] = "0"
        calls = []
        with self.stub_handlers(calls):
            out = timing.tick(store=self.store, ref=at(7, 0), verbose=False)
        self.assertNotIn("brief", calls)


class DueRuleTests(TimingTestCase):
    def job(self, kind, c=None):
        return next(j for j in timing.jobs_for(c or timing.cfg()) if j["kind"] == kind)

    def test_brief_not_due_before_0630_and_due_after(self):
        c = timing.cfg()
        job = self.job("brief", c)
        due, _ = timing.due_info(job, at(6, 29), [], c)
        self.assertFalse(due)
        due, reason = timing.due_info(job, at(6, 30), [], c)
        self.assertTrue(due, reason)

    def test_brief_catches_up_later_same_day(self):
        # الخادم كان نائمًا وقت 06:30 ← أول نبضة بعده تولّد البريف مرة واحدة
        c = timing.cfg()
        job = self.job("brief", c)
        self.assertTrue(timing.due_info(job, at(9, 5), [], c)[0])
        runs = [{"job_id": job["job_id"], "status": "ok",
                 "cycle_key": DAY.isoformat(), "finished_at": at(9, 5).isoformat()}]
        self.assertFalse(timing.due_info(job, at(9, 10), runs, c)[0])
        # اليوم التالي ← دورة جديدة
        self.assertTrue(timing.due_info(job, at(6, 31, DAY + dt.timedelta(days=1)),
                                        runs, c)[0])

    def test_sweep_interval_gate(self):
        c = timing.cfg()
        job = self.job("sweep", c)
        self.assertTrue(timing.due_info(job, at(8, 0), [], c)[0])          # أول مرة فورًا
        runs = [{"job_id": job["job_id"], "status": "ok", "cycle_key": DAY.isoformat(),
                 "finished_at": at(8, 0).isoformat()}]
        due, reason = timing.due_info(job, at(9, 0), runs, c)
        self.assertFalse(due, reason)
        self.assertTrue(timing.due_info(job, at(11, 0), runs, c)[0])

    def test_review_only_on_its_weekday_after_its_time(self):
        c = timing.cfg()
        job = self.job("review", c)
        self.assertFalse(timing.due_info(job, at(8, 0), [], c)[0])          # جمعة
        sunday = DAY + dt.timedelta(days=2)
        self.assertFalse(timing.due_info(job, at(6, 59, sunday), [], c)[0])
        self.assertTrue(timing.due_info(job, at(7, 0, sunday), [], c)[0])
        runs = [{"job_id": job["job_id"], "status": "ok",
                 "cycle_key": timing.sun_of(sunday).isoformat(),
                 "finished_at": at(7, 0, sunday).isoformat()}]
        self.assertFalse(timing.due_info(job, at(20, 0, sunday), runs, c)[0])  # مرة بالأسبوع

    def test_failed_job_retries_with_backoff_not_every_minute(self):
        c = timing.cfg()
        os.environ["TIMING_RETRY_MINUTES"] = "20"
        job = self.job("brief", c)
        runs = [{"job_id": job["job_id"], "status": "error",
                 "cycle_key": DAY.isoformat(), "finished_at": at(6, 35).isoformat()}]
        self.assertFalse(timing.due_info(job, at(6, 40), runs, c)[0])   # داخل الرجوع
        self.assertTrue(timing.due_info(job, at(7, 5), runs, c)[0])     # بعد السقف
        # فشلان متتاليان ← رجوع أطول (أُسّي) لا محاولة فورًا
        runs.append(dict(runs[0], finished_at=at(7, 5).isoformat()))
        self.assertFalse(timing.due_info(job, at(7, 25), runs, c)[0])
        self.assertTrue(timing.due_info(job, at(7, 46), runs, c)[0])


class TickTests(TimingTestCase):
    def test_tick_runs_everything_due_once_and_records_it(self):
        calls = []
        with self.stub_handlers(calls):
            first = timing.tick(store=self.store, ref=at(6, 30), verbose=False)
            second = timing.tick(store=self.store, ref=at(6, 35), verbose=False)
        self.assertEqual(first["status"], "ran")
        self.assertEqual(sorted(r["job_id"] for r in first["ran"]),
                         sorted([JOB_BY_KIND["brief"], JOB_BY_KIND["sweep"]]))
        self.assertEqual(calls, ["brief", "sweep"])
        self.assertEqual(second["status"], "idle")
        self.assertEqual(calls, ["brief", "sweep"])          # لا تكرار في نفس الدورة
        self.assertEqual(len(self.runs()), 2)
        self.assertTrue(all(r["status"] == "ok" for r in self.runs()))
        self.assertEqual({r["trigger"] for r in self.runs()}, {"cron"})

    def test_engine_disabled_writes_nothing(self):
        os.environ["AIOS_TIMING_ENABLED"] = "0"
        calls = []
        with self.stub_handlers(calls):
            out = timing.tick(store=self.store, ref=at(6, 30), verbose=False)
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(calls, [])
        self.assertEqual(self.runs(), [])

    def test_error_is_recorded_and_does_not_kill_the_tick(self):
        calls = []
        with self.stub_handlers(calls, fail_with={"brief"}):
            out = timing.tick(store=self.store, ref=at(6, 30), verbose=False)
        statuses = {r["job_id"]: r["status"] for r in out["ran"]}
        self.assertEqual(statuses[JOB_BY_KIND["brief"]], "error")
        self.assertEqual(statuses[JOB_BY_KIND["sweep"]], "ok")   # الوظيفة الأخرى أكملت
        self.assertIn("تعطل مصطنع", self.runs()[0]["detail"])

    def test_overlap_lock_makes_the_second_tick_exit_quietly(self):
        calls = []
        with self.stub_handlers(calls), timing.run_lock(blocking=False) as acquired:
            self.assertTrue(acquired)
            out = timing.tick(store=self.store, ref=at(6, 30), verbose=False)
        self.assertEqual(out["status"], "busy")
        self.assertEqual(calls, [])
        self.assertEqual(self.runs(), [])

    def test_run_job_force_bypasses_due_gate_and_logs_trigger(self):
        calls = []
        with self.stub_handlers(calls):
            res = timing.run_job("review", force=True, store=self.store, ref=at(9, 0),
                                 verbose=False, trigger="telegram")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(calls, ["review"])
        self.assertEqual(self.runs()[-1]["trigger"], "telegram")
        self.assertEqual(str(self.runs()[-1]["cycle_key"]),
                         timing.sun_of(DAY).isoformat())

    def test_unknown_job_name_is_rejected(self):
        with self.assertRaises(ValueError):
            timing.run_job("لا-شيء", force=True, store=self.store, verbose=False)


class BriefContentTests(TimingTestCase):
    def test_morning_brief_text_summarizes_today_from_state(self):
        def seed(S):
            S["proactive_actions"] = [
                {"pa_id": "PA-0001", "ts": at(6, 0).isoformat(), "decision": "ACT",
                 "title": "حُجزت نافذة تركيز للموعد", "points": 9, "kind": "deadline_48h"},
                {"pa_id": "PA-0002", "ts": at(6, 0).isoformat(), "decision": "ALERT",
                 "title": "فاتورة خلال يومين", "points": 20, "kind": "bill_due"},
                {"pa_id": "PA-0003", "ts": (at(6, 0) - dt.timedelta(days=1)).isoformat(),
                 "decision": "ACT", "title": "إجراء الأمس", "points": 5, "kind": "x"},
            ]
            S["action_queue"] = [{"action_id": "A-001", "status": "PENDING_APPROVAL"},
                                 {"action_id": "A-002", "status": "ACCEPTED"}]
            S["open_loops"] = [{"id": "OL-0001", "status": "OPEN", "title": "متابعة"},
                               {"id": "OL-0002", "status": "RECOVERING", "title": "فاتت"}]
            return True, None
        self.store.transaction(seed, "test_seed")
        text = timing.morning_brief_text(store=self.store, ref=at(6, 30))
        self.assertIn("بريف الصباح الاستباقي", text)
        self.assertIn("نُفّذ 1 · جُهّز 0 · تنبيه 1", text)   # صف الأمس غير محسوب
        self.assertIn("فاتورة خلال يومين", text)              # الأعلى نقاطًا أولًا
        self.assertIn("1 مسودة بانتظار اعتمادك", text)
        self.assertIn("proactive-brief-2026-09-11.md", text)
        self.assertNotIn("إجراء الأمس", text)

    def test_brief_never_uses_the_network_without_a_channel(self):
        sent = []
        import proactive

        def fake_send(text, chat_id=None, token=None, timeout=15):
            sent.append(text)
            return True
        with patch.object(proactive, "_telegram_send", fake_send), \
             patch.object(proactive, "render_brief",
                          return_value=str(Path(self.tmp.name) / "brief.md")), \
             patch.object(proactive, "sweep", return_value={"act": 0, "prepare": 0, "alert": 0,
                                                            "batched": 0, "suggest": 0,
                                                            "missed": 0}), \
             patch.object(proactive, "enabled", return_value=True):
            ok, detail = timing.run_brief(store=self.store, ref=at(6, 30))
        self.assertTrue(ok)
        self.assertEqual(sent, [])            # TIMING_PUSH=0 ← لا رسالة أصلًا
        self.assertEqual(detail["push"], "push_disabled")
        # مع تفعيل الدفع وقناة جاهزة ← نص البريف نفسه يمر عبر القناة
        os.environ["TIMING_PUSH"] = "1"
        with patch.object(proactive, "telegram_push_status", return_value="ready"), \
             patch.object(proactive, "_push_disabled", return_value=False), \
             patch.object(proactive, "_telegram_send",
                          side_effect=lambda text, chat_id=None, token=None, timeout=15:
                          sent.append(text) or True), \
             patch.object(proactive, "render_brief",
                          return_value=str(Path(self.tmp.name) / "brief.md")), \
             patch.object(proactive, "sweep", return_value={"act": 0, "prepare": 0, "alert": 0,
                                                            "batched": 0, "suggest": 0,
                                                            "missed": 0}):
            ok2, detail2 = timing.run_brief(store=self.store, ref=at(6, 31))
        self.assertTrue(ok2)
        self.assertEqual(detail2["push"], "sent")
        self.assertIn("بريف الصباح الاستباقي", sent[-1])


class SweepJobTests(TimingTestCase):
    def test_sweep_runs_maintenance_scheduler_and_proactive_in_order(self):
        seen = []
        store = self.store

        def seed(S):
            S["tasks"] = [{"العنوان": "تجربة", "الأولوية": "متوسطة", "الحالة": "لم تبدأ",
                           "الموعد النهائي": DAY, "النوع": "أعمال"}]
            return True, None
        store.transaction(seed, "test_seed")
        with patch("manager.fast_cycle", side_effect=lambda: seen.append("fast") or {}) as fast, \
             patch("scheduler.dispatch_due",
                   side_effect=lambda ref=None, store=None, verbose=True:
                   seen.append("scheduler") or (0, 1)) as dispatch, \
             patch("proactive.sweep",
                   side_effect=lambda store=None, now_dt=None, verbose=True:
                   seen.append("proactive") or {"act": 0, "prepare": 0, "alert": 0,
                                                "batched": 0, "suggest": 0, "missed": 0,
                                                "pushed": 0, "loops_open": 0}) as sweep, \
             patch("proactive.enabled", return_value=True):
            ok, detail = timing.run_sweep(store=store, ref=at(9, 0))
        self.assertTrue(ok)
        self.assertEqual(seen, ["fast", "scheduler", "proactive"])
        fast.assert_called_once_with()
        dispatch.assert_called_once()
        sweep.assert_called_once()
        self.assertEqual(detail["scheduler"], {"produced": 0, "nothing_new": 1})

    def test_one_failing_step_does_not_stop_the_others(self):
        with patch("manager.fast_cycle", side_effect=RuntimeError("قفل مفقود")), \
             patch("scheduler.dispatch_due", return_value=(1, 0)), \
             patch("proactive.sweep", return_value={"act": 1, "prepare": 0, "alert": 0,
                                                     "batched": 0, "suggest": 0, "missed": 0,
                                                     "pushed": 0, "loops_open": 2}), \
             patch("proactive.enabled", return_value=True):
            ok, detail = timing.run_sweep(store=self.store, ref=at(9, 0))
        self.assertFalse(ok)                       # الفشل موثَّق
        self.assertIn("fast_error", detail)
        self.assertEqual(detail["proactive"]["loops_open"], 2)


class ReviewJobTests(TimingTestCase):
    def test_review_text_is_pushed_and_apply_is_opt_in(self):
        import proactive
        calls = {"apply": 0}

        def fake_apply(recs, store=None):
            calls["apply"] += 1
            return {"confidence_act": 0.75}
        sun = at(7, 0, DAY + dt.timedelta(days=2))
        with patch.object(proactive, "review_text", return_value="📊 مراجعة: قبول 90%"), \
             patch.object(proactive, "acceptance_report", return_value={}), \
             patch.object(proactive, "tuning_recommendations",
                          return_value=({"confidence_act": 0.75}, [])), \
             patch.object(proactive, "apply_tuning", side_effect=fake_apply), \
             patch.object(proactive, "resolve_cfg", return_value=proactive.DEFAULT_CFG):
            ok, detail = timing.run_review(store=self.store, ref=sun)
        self.assertTrue(ok)
        self.assertEqual(detail["push"], "push_disabled")
        self.assertEqual(calls["apply"], 0)           # TIMING_REVIEW_APPLY مضبوط على 0
        os.environ["TIMING_REVIEW_APPLY"] = "1"
        with patch.object(proactive, "review_text", return_value="📊 مراجعة"), \
             patch.object(proactive, "acceptance_report", return_value={}), \
             patch.object(proactive, "tuning_recommendations",
                          return_value=({"confidence_act": 0.75}, [])), \
             patch.object(proactive, "apply_tuning", side_effect=fake_apply), \
             patch.object(proactive, "resolve_cfg", return_value=proactive.DEFAULT_CFG):
            ok2, detail2 = timing.run_review(store=self.store, ref=sun)
        self.assertTrue(ok2)
        self.assertEqual(calls["apply"], 1)
        self.assertEqual(detail2["applied"], {"confidence_act": 0.75})


class StatusAndCronTests(TimingTestCase):
    def test_status_card_lists_jobs_next_due_and_last_run(self):
        calls = []
        with self.stub_handlers(calls):
            timing.run_job("brief", force=True, store=self.store, ref=at(6, 30), verbose=False)
        st = timing.timing_status(store=self.store, ref=at(6, 31))
        self.assertTrue(st["enabled"])
        self.assertEqual(len(st["jobs"]), 3)
        card = {j["job_id"]: j for j in st["jobs"]}[JOB_BY_KIND["brief"]]
        self.assertEqual(card["when"], "06:30")
        self.assertEqual(card["last_status"], "ok")
        self.assertFalse(card["due_now"])                      # نُفّذت اليوم
        self.assertEqual(str(st["heartbeat_day"]), DAY.isoformat())  # دليل نبض cron
        self.assertEqual(st["push_channel"], "no_token")
        text = timing.status_text(store=self.store, ref=at(6, 31))
        self.assertIn("التوقيت التلقائي", text)
        self.assertIn("06:30", text)

    def test_crontab_lines_are_marked_and_idempotent_for_the_installer(self):
        block = timing.crontab_lines(repo="/srv/aios", python="/usr/bin/python3.12", mode="tick")
        self.assertIn(timing.CRON_MARK, block)
        self.assertIn("*/5 * * * * /srv/aios/scripts/aios-timing.sh tick", block)
        self.assertIn("@reboot", block)
        native = timing.crontab_lines(repo="/srv/aios", mode="native")
        self.assertIn("30 6 * * * /srv/aios/scripts/aios-timing.sh run brief", native)
        self.assertIn("15 */3 * * * /srv/aios/scripts/aios-timing.sh run sweep", native)
        self.assertIn("run review", native)
        # السطور المولّدة تُزال بوسمها وحده
        mixed = "0 * * * * other-job\n" + block + "\n"
        kept = [ln for ln in mixed.splitlines() if timing.CRON_MARK not in ln]
        self.assertEqual(kept, ["0 * * * * other-job"])

    def test_install_cron_print_only_does_not_touch_the_system(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = timing.install_cron(write=False)      # write=False ← لا crontab -
        self.assertIn(timing.CRON_MARK, out)
        self.assertIn(timing.CRON_MARK, buf.getvalue())
        with patch.dict(os.environ, {"AIOS_TIMING_ENABLED": "0"}):
            self.assertEqual(timing.tick(store=self.store, ref=at(6, 30), verbose=False)["status"],
                             "disabled")


class WorkerContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._env = patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name,
                                            "TIMING_PUSH": "0"}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        patcher = patch.object(timing, "Store", lambda *a, **k: self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_worker_uses_the_timing_engine_and_stays_fail_soft(self):
        from connectors import timing_worker as worker
        self.assertTrue(worker.enabled())                 # مفعّل على الخادم افتراضيًا
        os.environ["AIOS_TIMING_WORKER"] = "0"
        self.assertFalse(worker.enabled())
        os.environ["AIOS_TIMING_WORKER"] = "1"
        os.environ["TIMING_TICK_SECONDS"] = "bad"
        self.assertEqual(worker.interval_seconds(), worker.DEFAULT_INTERVAL_SECONDS)
        os.environ["TIMING_TICK_SECONDS"] = "1"
        self.assertEqual(worker.interval_seconds(), worker.MIN_INTERVAL_SECONDS)
        del os.environ["TIMING_TICK_SECONDS"]

        with patch.object(timing, "tick", return_value={"status": "idle", "ran": []}) as tick:
            res = worker.tick_once()
        self.assertEqual(res["status"], "idle")
        tick.assert_called_once_with(verbose=False, trigger="webhook-worker")
        health = worker.health()
        self.assertTrue(health["worker"])
        self.assertGreaterEqual(health["ticks"], 1)

        # tick_once نفسها قد ترمي؛ الحلقة الخلفية هي من يعزل العطل عن الـ webhook
        import threading
        with patch.object(timing, "tick", side_effect=RuntimeError("شبكة ميتة")), \
             patch.object(timing, "log_event"):
            with self.assertRaises(RuntimeError):
                worker.tick_once()
            stop = threading.Event()
            stop.wait = lambda timeout=None: True     # لفة واحدة ثم الخروج
            worker._worker(stop_event=stop, sleep_seconds=0.01)
        self.assertIn("شبكة ميتة", worker.health()["last_error"] or "")
        self.assertFalse(worker.health()["active"])

    def test_start_if_enabled_spawns_one_daemon_thread(self):
        from connectors import timing_worker as worker
        from unittest.mock import Mock
        fake = Mock()
        os.environ["AIOS_TIMING_WORKER"] = "1"
        os.environ["AIOS_TIMING_ENABLED"] = "1"
        with patch.object(worker.threading, "Thread", return_value=fake) as thread:
            started = worker.start_if_enabled()
        self.assertIs(started, fake)
        fake.start.assert_called_once_with()
        kwargs = thread.call_args.kwargs
        self.assertEqual(kwargs["name"], "automatic-timing-worker")
        self.assertTrue(kwargs["daemon"])
        os.environ["AIOS_TIMING_ENABLED"] = "0"
        with patch.object(worker.threading, "Thread") as thread:
            self.assertIsNone(worker.start_if_enabled())
            thread.assert_not_called()
        os.environ["AIOS_TIMING_WORKER"] = "0"
        with patch.object(worker.threading, "Thread") as thread:
            self.assertIsNone(worker.start_if_enabled())
            thread.assert_not_called()
        del os.environ["AIOS_TIMING_WORKER"]
        del os.environ["AIOS_TIMING_ENABLED"]


class TelegramSurfaceTests(unittest.TestCase):
    def test_timing_and_review_commands_are_handled_in_delegated_bot(self):
        from unittest.mock import patch as _patch
        import engine.telegram_bot  # noqa: F401 — يضيف engine/ إلى sys.path
        import connectors.telegram_bot as bot

        sent = []
        card = "🕰️ التوقيت التلقائي (cron)\n☀️ 06:30"
        with _patch.object(bot, "_authorized", return_value=True), \
             _patch.object(bot, "send",
                           lambda chat_id, text, reply_markup=None: sent.append(text)), \
             _patch.object(bot, "_save_intake", return_value=True), \
             _patch.object(bot, "_local_capture", return_value="TG-1"), \
             _patch.object(timing, "status_text", return_value=card), \
             _patch.object(timing, "tick",
                           return_value={"status": "ran", "ran": [
                               {"job_id": JOB_BY_KIND["sweep"], "status": "ok",
                                "reason": "لم تُنفَّذ بعد", "detail": {}}],
                                         "at": DAY.isoformat()}), \
             _patch.object(timing, "run_job",
                           return_value={"job_id": JOB_BY_KIND["brief"], "status": "ok",
                                         "detail": {}}), \
             _patch("proactive.review_text",
                    return_value="📊 مراجعة الأسبوع: معدل القبول 90%"):
            bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/timing"})
            self.assertIn("التوقيت التلقائي", sent[-1])

            bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/timing_run"})
            self.assertIn("periodic_sweep", sent[-1])

            bot.handle_message({"chat": {"id": 123, "type": "private"},
                                "text": "/timing_run brief"})
            self.assertIn("morning_brief", sent[-1])

            bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/review"})
            self.assertIn("معدل القبول", sent[-1])
            # /reviews (مراجعات التعلم) لا تزال مسارًا مستقلًا
            with _patch("proactive.review_text") as review_only:
                bot.handle_message({"chat": {"id": 123, "type": "private"}, "text": "/reviews"})
                review_only.assert_not_called()


if __name__ == "__main__":
    unittest.main()
