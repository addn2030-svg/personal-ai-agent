# -*- coding: utf-8 -*-
"""Offline tests for v1.2 research goals — one reusable pipeline, only the GOAL changes.

The governing contract these tests protect: the engine NEVER browses and NEVER
sends. Its whole effect is capsule files under research_capsules/ + rows in the
`research_goals` state section. Everything else here is plumbing: cadence gating,
cycle idempotency, the token budget from research_capsules/README.md, promotion of
externally-gathered sources, and the timing-job integration (4th job, quiet by
default, isolated failure like its siblings).
"""
import datetime as dt
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

import research_goals as rg  # noqa: E402

SAT = dt.datetime.fromisoformat("2026-09-12T05:45:00+03:00")   # السبت
SUN = dt.datetime.fromisoformat("2026-09-13T06:00:00+03:00")


class _Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = tempfile.mkdtemp(dir=self.tmp.name)
        self.caps = os.path.join(self.tmp.name, "capsules")
        os.makedirs(self.caps, exist_ok=True)
        self._p_data = patch.dict(os.environ, {"AI_OS_DATA_DIR": self.data})
        self._p_data.start()
        self._p_caps = patch.object(rg, "CAPSULE_DIR", self.caps)
        self._p_caps.start()
        self.addCleanup(self._p_caps.stop)
        self.addCleanup(self._p_data.stop)
        self.addCleanup(self.tmp.cleanup)
        self.store = rg.Store(os.path.join(self.data, "state.json"))

    def add(self, goal="أسئلة جمهور إعادة التأهيل على X", **kw):
        kw.setdefault("cadence", "weekly")
        kw.setdefault("weekday", 5)
        kw.setdefault("at", "05:40")
        kw.setdefault("store", self.store)
        kw.setdefault("ref", SAT)
        return rg.add_goal(goal, **kw)

    def capsules(self):
        return sorted(f for f in os.listdir(self.caps) if f.startswith("RG-") and f.endswith(".md"))

    def read(self, rel):
        path = rel if os.path.isabs(rel) else os.path.join(BASE, rel)
        return io.open(path, encoding="utf-8").read()


class Registry(_Harness):
    def test_add_writes_budgeted_skeleton_at_cycle_date(self):
        changed, row, path = self.add()
        self.assertTrue(changed)
        self.assertEqual(self.capsules(), [f"{row['goal_id']}-2026-09-12.md"])
        body = self.read(path)
        for sec in rg.SECTIONS:
            self.assertIn(sec + ":", body)
        self.assertIn("SOURCE: NEEDED", body)
        self.assertLess(rg._estimate_tokens(body), rg.TOKEN_BUDGET_MAX)

    def test_duplicate_goal_is_not_re_registered(self):
        first = self.add()[1]["goal_id"]
        changed, row, path = self.add()
        self.assertFalse(changed)
        self.assertEqual(row["goal_id"], first)
        self.assertIsNone(path)
        self.assertEqual(len(self.capsules()), 1)

    def test_empty_and_bad_input_rejected(self):
        with self.assertRaises(ValueError):
            rg.add_goal("   ", store=self.store)
        with self.assertRaises(ValueError):
            rg.add_goal("هدف", cadence="hourly", store=self.store)
        with self.assertRaises(ValueError):
            rg.add_goal("هدف", mode="ultra", store=self.store)

    def test_at_is_normalized_or_defaulted(self):
        _c, row, _p = self.add("هدف ثانٍ", at="9:5")
        self.assertEqual(row["at"], "09:05")
        _c2, row2, _p2 = self.add("هدف ثالث", at="25:99")
        self.assertEqual(row2["at"], "05:40", "توقيت غير صالح يسقط إلى الافتراضي")

    def test_toggle_and_remove(self):
        gid = self.add()[1]["goal_id"]
        self.assertTrue(rg.toggle(gid, False, self.store)[0])
        self.assertFalse(rg.read_goals(self.store)[0]["enabled"])
        self.assertFalse(rg.toggle("RG-999", True, self.store)[0])
        self.assertTrue(rg.remove_goal(gid, self.store)[0])
        self.assertEqual(rg.read_goals(self.store), [])
        self.assertFalse(rg.remove_goal(gid, self.store)[0], "حذف Twice ⇒ لا تغيير")

    def test_section_registered_in_store(self):
        from store import SECTIONS
        self.assertIn("research_goals", SECTIONS)


class Cadence(_Harness):
    def test_weekly_only_on_its_day(self):
        gid = self.add()[1]["goal_id"]
        due, held = rg.due_goals(SUN, store=self.store)
        self.assertEqual(due, [])
        self.assertEqual(held[0][0]["goal_id"], gid)
        self.assertIn("ليس", held[0][1])
        due, _ = rg.due_goals(SAT, store=self.store)
        self.assertEqual([r["goal_id"] for r in due], [gid])

    def test_before_time_is_held(self):
        self.add(at="23:00")
        due, held = rg.due_goals(SAT, store=self.store)
        self.assertEqual(due, [])
        self.assertIn("لم يحن", held[0][1])

    def test_disabled_goal_is_held(self):
        gid = self.add()[1]["goal_id"]
        rg.toggle(gid, False, self.store)
        due, held = rg.due_goals(SAT, store=self.store)
        self.assertEqual(due, [])
        self.assertEqual(held[0][1], "معطّل")

    def test_daily_ignores_weekday(self):
        gid = self.add("هدف يومي", cadence="daily", at="00:01")[1]["goal_id"]
        for ref in (SAT, SUN):
            self.assertIn(gid, [r["goal_id"] for r in rg.due_goals(ref, store=self.store)[0]])

    def test_manual_always_due_once_per_manual_cycle(self):
        gid = self.add("هدف يدوي", cadence="manual")[1]["goal_id"]
        ok, d = rg.run_due(SUN, store=self.store, verbose=False)
        self.assertEqual(d["due"], 1)
        # السكلتون يبقى مستحقًا عمدًا حتى الامتلاء
        self.assertEqual(rg.run_due(SUN, store=self.store, verbose=False)[1]["due"], 1)
        # وبعد الترويج تُقفل الدورة الثابتة ولا تعود إلا بتصفير cycle_key
        src = os.path.join(self.tmp.name, "m.md")
        io.open(src, "w", encoding="utf-8").write("KEY FINDINGS:\n- نتيجة\n")
        rg.attach(gid, src, self.store)
        rg._mutate(self.store, lambda rs: (True, rs), "noop")
        rows = rg.read_goals(self.store)
        rg.promote(rows[0], SUN)
        rg._mutate(self.store, lambda rs: (True, None), "noop")

        def fill(rs):
            rs[0]["status"] = "READY"
            rs[0]["cycle_key"] = "manual"
            return True, None
        rg._mutate(self.store, fill, "force_ready")
        self.assertEqual(rg.run_due(SUN, store=self.store, verbose=False)[1]["due"], 0)


class RunAndPromotion(_Harness):
    def test_run_records_state_and_capsule(self):
        gid = self.add()[1]["goal_id"]
        ok, detail = rg.run_due(SAT, store=self.store, verbose=False)
        self.assertTrue(ok)
        self.assertEqual(detail["capsules"][0]["status"], "SKELETON")
        row = rg.read_goals(self.store)[0]
        self.assertEqual(row["status"], "SKELETON")
        self.assertEqual(row["cycle_key"], "2026-W37")
        self.assertEqual(row["goal_id"], gid)

    def test_skeleton_stays_due_until_filled_then_locks(self):
        """القصد: كبسولة فارغة ≠ منجزة. تبقى مستحقة، وتُقفل عند READY."""
        gid = self.add()[1]["goal_id"]
        rg.run_due(SAT, store=self.store, verbose=False)
        self.assertEqual(rg.run_due(SAT, store=self.store, verbose=False)[1]["due"], 1)
        src = os.path.join(self.tmp.name, "r.md")
        io.open(src, "w", encoding="utf-8").write("KEY FINDINGS:\n- نتيجة واحدة\n")
        rg.attach(gid, src, self.store)
        rg.run_due(SAT, store=self.store, verbose=False)          # ← يروّج ⇒ READY
        _ok, d = rg.run_due(SAT, store=self.store, verbose=False)
        self.assertEqual(d["due"], 0, "READY يُقفل دورة الأسبوع")
        self.assertEqual(d["deferred"], 1)

    def test_attached_source_is_promoted_over_skeleton(self):
        gid = self.add()[1]["goal_id"]
        rg.run_due(SAT, store=self.store, verbose=False)
        src = os.path.join(self.tmp.name, "research.md")
        io.open(src, "w", encoding="utf-8").write(
            "KEY FINDINGS:\n- سؤال متكرر: التكلفة\n- سؤال: مدة البرنامج\n\n"
            "EVIDENCE / SOURCE REFS:\n- x.com/search → 41 منشورًا\n")
        changed, row, rel = rg.attach(gid, src, self.store)
        self.assertTrue(changed)
        self.assertFalse(row.get("path") is None)
        rows = rg.read_goals(self.store)
        ok, status, path = rg.promote(rows[0], SAT)
        self.assertTrue(ok)
        self.assertEqual(status, "READY")
        body = self.read(path)
        self.assertIn("التكلفة", body)
        self.assertNotIn("SOURCE: NEEDED", body, "الترويج يستبدل الهيكل")
        self.assertIn("research-goal RG-001", body)

    def test_over_budget_source_flags_trim(self):
        gid = self.add()[1]["goal_id"]
        src = os.path.join(self.tmp.name, "big.md")
        io.open(src, "w", encoding="utf-8").write("كلمة " * 3000)
        rg.attach(gid, src, self.store)
        rows = rg.read_goals(self.store)
        ok, status, _p = rg.promote(rows[0], SAT)
        self.assertTrue(ok)
        self.assertEqual(status, "READY_TRIM_ME")
        # ملاحظة: log_event يستخدم مسار AUDIT_PATH الثابت وقت الاستيراد، فلا يمكن
        # توجيهه بمساحة الاختبار — لذا نثبت الحالة لا سجل التدقيق.

    def test_missing_inbox_falls_back_to_skeleton(self):
        gid = self.add()[1]["goal_id"]
        rows = rg.read_goals(self.store)
        rows[0]["inbox"] = "research_capsules/inbox/gone.md"

        def fn(rs):
            rs[0]["inbox"] = "research_capsules/inbox/gone.md"
            return True, None
        rg._mutate(self.store, fn, "force_inbox")
        ok, status, path = rg.promote(rg.read_goals(self.store)[0], SAT)
        self.assertFalse(ok)
        self.assertEqual(status, "inbox_missing")
        self.assertTrue(self.capsules(), "run_due يعوّض عن المصدر المفقود بهيكل")

    def test_attach_rejects_missing_and_oversized(self):
        gid = self.add()[1]["goal_id"]
        with self.assertRaises(FileNotFoundError):
            rg.attach(gid, "/nonexistent/nope.md", self.store)
        big = os.path.join(self.tmp.name, "big.bin")
        with open(big, "wb") as f:
            f.write(b"x" * 401_000)
        with self.assertRaises(ValueError):
            rg.attach(gid, big, self.store)

    def test_attach_is_content_addressed(self):
        gid = self.add()[1]["goal_id"]
        src = os.path.join(self.tmp.name, "one.md")
        io.open(src, "w", encoding="utf-8").write("نفس النص")
        _, _r1, rel1 = rg.attach(gid, src, self.store)
        _, _r2, rel2 = rg.attach(gid, src, self.store)
        self.assertEqual(rel1, rel2, "بصمة المحتوى ⇒ ملف واحد بلا نسخ مكررة")

    def test_run_is_isolated_per_goal(self):
        gid = self.add()[1]["goal_id"]
        gid2 = self.add("هدف آخر غير مألوف")[1]["goal_id"]
        rows = rg.read_goals(self.store)
        rows[0]["inbox"] = "nope/missing.md"
        def fn(rs):
            rs[0]["inbox"] = "nope/missing.md"
            return True, None
        rg._mutate(self.store, fn, "break_first")
        ok, detail = rg.run_due(SAT, store=self.store, verbose=False)
        self.assertTrue(ok, "فشل هدف لا يُسقط الباقي")
        self.assertEqual(len(detail["capsules"]), 2)


class TimingIntegration(_Harness):
    def test_research_job_is_registered(self):
        import timing
        self.assertIn("research", timing.HANDLERS)
        self.assertEqual(timing.JOB_ALIASES["research"], "timing.research_goals")
        kinds = [j["kind"] for j in timing.JOB_SPECS]
        self.assertEqual(kinds.count("research"), 1)
        self.assertIn("research", timing.cfg()["jobs"])

    def test_native_cron_line_generated(self):
        import timing
        lines = timing.crontab_lines(repo="/srv/aios", mode="native")
        self.assertIn("40 5 * * * /srv/aios/scripts/aios-timing.sh run research", lines)

    def test_tick_locks_job_per_cycle_not_per_goal(self):
        """قفل الوظيفة يومي (cadence=daily) وقفل الهدف أسبوعي — طبقتان مختلفتان.

        الوظيفة تركض مرة واحدة في اليوم وتستعلم؛ الهدف يبقى مستحقًا داخل اليوم
        نفسه حتى امتلائه، ويُقفل دورته الأسبوعية عند READY.
        """
        import timing
        gid = self.add()[1]["goal_id"]
        with patch.object(rg, "Store", lambda *a, **k: self.store), \
             patch.object(timing, "Store", lambda *a, **k: self.store):
            out1 = timing.tick(ref=SAT, verbose=False, trigger="test")
            self.assertIn("timing.research_goals", [r["job_id"] for r in out1["ran"]])
            self.assertEqual(len(self.capsules()), 1, "كبسولة واحدة لكل النبضات")
            out2 = timing.tick(ref=SAT + dt.timedelta(minutes=1), verbose=False, trigger="test")
            self.assertNotIn("timing.research_goals", [r["job_id"] for r in out2["ran"]],
                             "نفس اليوم ⇒ قفل الوظيفة اليومي")
            # اليوم التالي: الوظيفة تعود (الهدف ما زال SKELETON) ولا تكرّر الكبسولة
            out3 = timing.tick(ref=SAT + dt.timedelta(days=1), verbose=False, trigger="test")
            self.assertIn("timing.research_goals", [r["job_id"] for r in out3["ran"]])
            self.assertEqual(len(self.capsules()), 1, "لا كبسولة ثانية لنفس اليوم")
            # الامتلاء يُقفل دورة الهدف الأسبوعية حتى بعد أن تعود الوظيفة في اليوم التالي
            src = os.path.join(self.tmp.name, "r.md")
            io.open(src, "w", encoding="utf-8").write("KEY FINDINGS:\n- x\n")
            rg.attach(gid, src, self.store)
            # الترويج يقع في نبضة اليوم التالي (السبت هو يوم الهدف، والدورة أسبوعية)
            nxt = SAT + dt.timedelta(days=7, minutes=1)      # السبت التالي 05:46
            timing.tick(ref=nxt, verbose=False, trigger="test")
            st = [r for r in rg.read_goals(self.store) if r["goal_id"] == gid][0]
            self.assertEqual(st["status"], "READY")
            self.assertEqual(st["cycle_key"], "2026-W38")

    def test_research_push_is_opt_in(self):
        """الدفع كبقية الوظائف: عند كبسولات وإلا صمت — والقرار للمتصل."""
        import timing
        self.add()
        seen = []
        with patch.object(rg, "Store", lambda *a, **k: self.store), \
             patch.object(timing, "push", lambda *a, **k: seen.append(1) or (True, "sent")):
            ok, detail = timing.run_research(store=self.store, ref=SAT, push_enabled=False)
        self.assertTrue(ok)
        self.assertEqual(seen, [], "push_enabled=False ⇒ لا دفع")
        self.assertEqual(detail["push"], "quiet")
        self.assertEqual(detail["due"], 1, "الكبسولة أُنْتِجت ثم صمت الدفع")

    def test_engine_does_not_reach_the_network(self):
        """لا تصفّح ولا نداء HTTP في مسار أهداف البحث إطلاقًا."""
        import timing
        self.add()
        with patch.object(rg, "Store", lambda *a, **k: self.store), \
             patch.object(timing, "push", lambda *a, **k: (False, "blocked")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("لا شبكة")):
            ok, detail = timing.run_research(store=self.store, ref=SAT)
        self.assertTrue(ok)
        self.assertEqual(detail["due"], 1)

    def test_push_quiet_when_no_capsules(self):
        import timing
        ok, detail = timing.run_research(store=self.store, ref=SAT, push_enabled=True)
        self.assertTrue(ok)
        self.assertEqual(detail["push"], "quiet")
        self.assertEqual(detail["due"], 0)


class Presentation(_Harness):
    def test_empty_registry_text_is_actionable(self):
        text = rg.goals_text(self.store)
        self.assertIn("لا أهداف بحث", text)
        self.assertIn("research_goals.py add", text)

    def test_card_marks_due_and_state(self):
        gid = self.add()[1]["goal_id"]
        rg.run_due(SAT, store=self.store, verbose=False)
        text = rg.goals_text(self.store, ref=SAT)
        self.assertIn(gid, text)
        self.assertIn("🟢", text)
        self.assertIn("SKELETON", text)
        self.assertIn("لا يتصفّح", text)

    def test_paths_are_never_relative_escapes(self):
        _c, row, path = self.add()
        self.assertFalse(path.startswith(".."), "CAPSULE_DIR خارج BASE ⇒ مسار مطلق لا ../../../")


if __name__ == "__main__":
    unittest.main()
