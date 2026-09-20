# -*- coding: utf-8 -*-
"""اختبارات التشغيل التدريجي والتراجع — أهم ما يحمي التشغيل أثناء النقل.

القاعدة التي نختبرها: **الترقية تحتاج دليلًا، والتراجع متاح دائمًا،
وسير العمل القديم لا يتغير في أي مرحلة.**
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

from engine import rollout
from connectors import supabase_tasks

AUDIT_OK = {"event": "supabase_backup_done", "snapshot_id": 1, "mirror_rows": 3}
AUDIT_RECONCILE = {"event": "supabase_reconcile_done", "drift": 0, "remote_rows": 3, "local_rows": 3}
AUDIT_ERROR = {"event": "supabase_backup_error", "error": "network"}


class RolloutTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"AI_OS_DATA_DIR": self.tmp.name}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_audit(self, events: list, append: bool = False):
        """يكتب أدلة التدقيق. `append=True` يضيف إلى السجل بدل استبداله —
        مهم لأن البوابة تقرأ تاريخ النافذة كله (استبداله يمحو الأدلة السابقة)."""
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        mode = "a" if append else "w"
        with open(os.path.join(self.tmp.name, "audit.jsonl"), mode, encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps({**event, "ts": event.get("ts", stamp)},
                                        ensure_ascii=False) + "\n")


class DefaultSafetyTests(RolloutTestCase):
    def test_starts_dormant_with_no_capabilities(self):
        self.assertEqual(rollout.current_phase(), "dormant")
        caps = rollout.capabilities()
        self.assertFalse(caps["automation_read"])
        self.assertFalse(caps["automation_write"])

    def test_missing_file_is_dormant_not_an_error(self):
        self.assertFalse(os.path.exists(rollout.path()))
        self.assertEqual(rollout.load()["phase"], "dormant")

    def test_corrupt_file_fails_closed_to_dormant(self):
        with open(rollout.path(), "w", encoding="utf-8") as handle:
            handle.write('{"phase": "primary"')  # JSON مقطوع
        data = rollout.load()
        self.assertEqual(data["phase"], "dormant")
        self.assertTrue(data["corrupt"])

    def test_unknown_phase_fails_closed_to_dormant(self):
        with open(rollout.path(), "w", encoding="utf-8") as handle:
            json.dump({"phase": "godmode"}, handle)
        data = rollout.load()
        self.assertEqual(data["phase"], "dormant")
        self.assertTrue(data["corrupt"])

    def test_a_non_dict_file_fails_closed(self):
        with open(rollout.path(), "w", encoding="utf-8") as handle:
            json.dump(["dormant"], handle)
        self.assertEqual(rollout.load()["phase"], "dormant")


class CapabilityMatrixTests(RolloutTestCase):
    def test_capabilities_match_the_documented_matrix(self):
        expected = {
            "dormant": (False, False),
            "shadow": (True, False),
            "canary": (True, False),
            "dual": (True, True),
            "primary": (True, True),
        }
        for phase, (can_read, can_write) in expected.items():
            caps = rollout.capabilities(phase)
            self.assertEqual(caps["automation_read"], can_read, phase)
            self.assertEqual(caps["automation_write"], can_write, phase)

    def test_shadow_and_canary_never_allow_automatic_writes(self):
        for phase in ("dormant", "shadow", "canary"):
            self.assertFalse(rollout.allows("automation_write", phase), phase)

    def test_unknown_action_denied(self):
        self.assertFalse(rollout.allows("anything_else", "primary"))


class TransitionTests(RolloutTestCase):
    def test_one_step_at_a_time(self):
        with self.assertRaises(ValueError) as ctx:
            rollout.set_phase("dual")
        self.assertIn("خطوة واحدة", str(ctx.exception))
        self.assertEqual(rollout.current_phase(), "dormant")

    def test_rollback_is_always_allowed_and_can_skip_backwards(self):
        for phase in ("shadow", "canary", "dual", "primary"):
            rollout.set_phase(phase, acknowledge=(phase == "primary"))
        self.assertEqual(rollout.current_phase(), "primary")
        rollout.rollback("shadow", reason="تراجع كبير")
        self.assertEqual(rollout.current_phase(), "shadow")

    def test_rollback_needs_no_evidence(self):
        rollout.set_phase("shadow")
        self.write_audit([])  # لا دليل إطلاقًا
        result = rollout.rollback("dormant", reason="بلا أدلة")
        self.assertEqual(result["phase"], "dormant")

    def test_kill_switch_reaches_dormant_from_anywhere(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        rollout.kill(reason="طارئ")
        self.assertEqual(rollout.current_phase(), "dormant")
        self.assertFalse(rollout.allows("automation_write"))
        self.assertFalse(rollout.allows("automation_read"))

    def test_unknown_phase_rejected(self):
        with self.assertRaises(ValueError):
            rollout.set_phase("turbo")

    def test_primary_needs_the_literal_acknowledgement(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        rollout.set_phase("dual")
        with self.assertRaises(ValueError) as ctx:
            rollout.set_phase("primary")
        self.assertIn(rollout.ACK_ENV, str(ctx.exception))
        result = rollout.set_phase("primary", acknowledge=True)
        self.assertEqual(result["phase"], "primary")

    def test_history_records_direction_and_reason(self):
        rollout.set_phase("shadow", reason="بدء الظل")
        data = rollout.rollback("dormant", reason="انحراف")
        history = data["history"]
        self.assertEqual(history[-1]["direction"], "rollback")
        self.assertEqual(history[-1]["reason"], "انحراف")
        self.assertEqual(history[-1]["from"], "shadow")

    def test_writes_are_atomic(self):
        rollout.set_phase("shadow")
        leftovers = [name for name in os.listdir(self.tmp.name) if ".tmp-" in name]
        self.assertEqual(leftovers, [])
        with open(rollout.path(), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["phase"], "shadow")


class GateTests(RolloutTestCase):
    def _advance_to(self, phase):
        while rollout.current_phase() != phase:
            result = rollout.advance(force=True)
            if result.get("blocked"):
                rollout.set_phase(rollout.PHASES[rollout.index() + 1], acknowledge=True)

    def test_gate_blocks_without_evidence(self):
        self.write_audit([])
        report = rollout.gate("shadow")
        self.assertFalse(report["ok"])
        self.assertTrue(any(not check["ok"] for check in report["requirements"]))

    def test_gate_passes_with_successful_documented_runs(self):
        self.write_audit([AUDIT_RECONCILE, AUDIT_RECONCILE])
        report = rollout.gate("shadow")
        self.assertTrue(report["ok"], report["requirements"])

    def test_drift_blocks_the_gate_to_dual(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        self.write_audit([AUDIT_OK] * 3 + [{**AUDIT_RECONCILE, "drift": 3}])
        report = rollout.gate("dual")
        drift_check = next(check for check in report["requirements"] if "انحراف" in check["name"])
        self.assertFalse(drift_check["ok"])
        self.assertFalse(report["ok"])
        # ولا تُحجب الترقية بسبب انحراف قديم إذا كانت آخر مقارنة نظيفة
        self.write_audit([AUDIT_RECONCILE], append=True)
        report = rollout.gate("dual")
        self.assertTrue(report["ok"], report["requirements"])

    def test_missing_reconcile_blocks_the_dual_gate(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        self.write_audit([AUDIT_OK] * 5)   # كتابة ناجحة بلا مقارنة واحدة
        report = rollout.gate("dual")
        drift_check = next(check for check in report["requirements"] if "انحراف" in check["name"])
        self.assertFalse(drift_check["ok"])
        self.assertIn("reconcile", drift_check["detail"])

    def test_shadow_gate_does_not_require_zero_drift(self):
        """حلقة مفرغة نتجنبها: الظلّ لا يكتب، فاشتراط صفر انحراف يمنع أي تقدّم."""
        self.write_audit([{**AUDIT_RECONCILE, "drift": 5}, {**AUDIT_RECONCILE, "drift": 5}])
        report = rollout.gate("shadow")
        self.assertTrue(report["ok"], report["requirements"])
        self.assertFalse(any("انحراف" in check["name"] for check in report["requirements"]))

    def test_errors_block_the_gate_at_dual(self):
        self.write_audit([AUDIT_OK] * 3 + [AUDIT_ERROR])
        report = rollout.gate("dual")
        error_check = next(check for check in report["requirements"] if "أخطاء" in check["name"])
        self.assertFalse(error_check["ok"])

    def test_advance_refuses_when_gate_fails(self):
        self.write_audit([])
        result = rollout.advance()
        self.assertTrue(result["blocked"])
        self.assertEqual(rollout.current_phase(), "dormant")

    def test_advance_proceeds_when_gate_passes(self):
        self.write_audit([AUDIT_RECONCILE, AUDIT_RECONCILE])
        result = rollout.advance(reason="أدلة كافية")
        self.assertEqual(result["phase"], "shadow")

    def test_primary_cannot_be_forced_even_with_force_flag(self):
        self._advance_to("dual")
        self.write_audit([AUDIT_OK] * 10)
        result = rollout.advance(force=True)
        self.assertTrue(result.get("blocked"))
        self.assertEqual(rollout.current_phase(), "dual")

    def test_primary_passes_with_ack_and_evidence(self):
        self._advance_to("dual")
        self.write_audit([AUDIT_RECONCILE] * 6)
        with mock.patch.dict(os.environ, {rollout.ACK_ENV: rollout.PRIMARY_ACK}, clear=False):
            report = rollout.gate("primary")
            self.assertTrue(report["ok"], report["requirements"])
            result = rollout.advance(reason="تحقق بشري")
        self.assertEqual(result["phase"], "primary")

    def test_old_evidence_outside_the_current_phase_window_is_ignored(self):
        """أدلة من مرحلة سابقة لا تُحتسب: الترقية تحتاج دليلًا في المرحلة الحالية."""
        old = (dt.datetime.now() - dt.timedelta(days=3)).isoformat(timespec="seconds")
        self.write_audit([AUDIT_RECONCILE, AUDIT_RECONCILE])
        rollout.set_phase("shadow")           # تبدأ نافذة جديدة
        rollout.rollback("dormant")
        rollout.set_phase("shadow")
        self.write_audit([{**AUDIT_RECONCILE, "ts": old}] + [AUDIT_RECONCILE])
        report = rollout.gate("canary")
        runs = next(check for check in report["requirements"] if "تشغيلات" in check["name"])
        self.assertEqual(runs["detail"].split("/")[0].strip(), "1")

    def test_gate_for_rollback_is_always_open(self):
        rollout.set_phase("shadow")
        report = rollout.gate("dormant")
        self.assertTrue(report["ok"])
        self.assertIn("تراجع", report["detail"])

    def test_floors_cannot_be_lowered_by_environment(self):
        self.assertEqual(rollout.GATE_FLOORS["runs"], 2)
        self.write_audit([AUDIT_RECONCILE])   # تشغيل واحد فقط
        report = rollout.gate("shadow")
        self.assertFalse(report["ok"], "عتبة واحدة لا تكفي — الحد الأدنى في الكود")


class ParallelOperationTests(RolloutTestCase):
    """سير العمل القديم لا يتغير في أي مرحلة — وهذا جوهر «بلا توقف»."""

    def test_automation_is_off_below_dual_regardless_of_env_flag(self):
        env = {"SUPABASE_URL": "https://demo.supabase.co",
               "SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}
        now = dt.datetime(2026, 9, 20, 9, 0)
        for phase in ("dormant", "shadow", "canary"):
            with mock.patch.object(rollout, "current_phase", lambda phase=phase: phase):
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertFalse(supabase_tasks.daily_due(now, {}), phase)

    def test_automation_needs_both_phase_and_flag(self):
        now = dt.datetime(2026, 9, 20, 9, 0)
        with mock.patch.object(rollout, "current_phase", lambda: "dual"):
            # المرحلة وحدها لا تكفي
            with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://demo.supabase.co"}, clear=True):
                self.assertFalse(supabase_tasks.daily_due(now, {}))
            # الراية وحدها لا تكفي — مع المرحلة تعمل
            with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://demo.supabase.co",
                                              "SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}, clear=True):
                self.assertTrue(supabase_tasks.daily_due(now, {}))
                self.assertFalse(supabase_tasks.daily_due(now, {"supabase_backup_day": "2026-09-20"}))

    def test_rollout_failure_never_raises_into_the_manager_loop(self):
        with mock.patch.object(rollout, "load", side_effect=RuntimeError("boom")):
            with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://demo.supabase.co",
                                              "SUPABASE_BACKUP_SCHEDULE_ENABLED": "1"}, clear=True):
                # لا استثناء يتسرب: الأتمتة تُطفأ فقط
                self.assertFalse(supabase_tasks.daily_due(dt.datetime(2026, 9, 20, 9, 0), {}))

    def test_manual_commands_are_never_blocked_by_phase(self):
        """حتى في dormant: المالك يستطيع أخذ نسخة احتياطية بأمر صريح."""
        client = mock.Mock(select=mock.Mock(return_value=[]))
        self.assertEqual(rollout.current_phase(), "dormant")
        report = supabase_tasks.reconcile(client=client, state={
            "meta": {"version": 1}, "tasks": []})
        self.assertEqual(report["drift"], 0)   # القراءة اليدوية لم تُمنع

    def test_shadow_run_refuses_when_automation_writes_are_on(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        rollout.set_phase("dual")
        self.assertTrue(rollout.shadow_run()["skipped"])

    def test_shadow_run_is_silent_below_read_capability(self):
        self.assertTrue(rollout.shadow_run()["skipped"])  # dormant


class ReconcileTests(RolloutTestCase):
    def _state(self, tasks):
        return {"meta": {"version": 2, "schema": "state/1"}, "tasks": tasks}

    def _client(self, rows):
        return mock.Mock(select=mock.Mock(return_value=rows))

    def test_identical_layers_report_zero_drift(self):
        state = self._state([{"العنوان": "أ", "الحالة": "لم تبدأ"}])
        local = supabase_tasks.task_rows(state)
        remote = [{**local[0], "sync_run": "run-1"}]
        report = supabase_tasks.reconcile(client=self._client(remote), state=state)
        self.assertEqual(report["drift"], 0)
        self.assertEqual(report["verdict"], "مطابقة تامة")

    def test_missing_orphan_and_mismatch_are_counted_separately(self):
        state = self._state([{"العنوان": "أ", "الحالة": "لم تبدأ"},
                             {"العنوان": "ب", "الحالة": "لم تبدأ"}])
        local = supabase_tasks.task_rows(state)
        remote = [
            {**local[0], "status_norm": "done", "is_open": False},  # اختلاف حقل
            {"id": "orphan-1", "title": "يتيمة"},                    # زائدة في المرآة
        ]
        report = supabase_tasks.reconcile(client=self._client(remote), state=state)
        self.assertEqual(report["missing_in_mirror"], [local[1]["id"]])
        self.assertEqual(report["orphans_in_mirror"], ["orphan-1"])
        self.assertEqual(len(report["mismatched"]), 1)
        self.assertEqual(report["drift"], 3)

    def test_reconcile_never_writes(self):
        state = self._state([{"العنوان": "أ"}])
        client = mock.Mock(select=mock.Mock(return_value=[]))
        supabase_tasks.reconcile(client=client, state=state)
        self.assertFalse(client.upsert.called)
        self.assertFalse(client.delete.called)

    def test_reconcile_logs_evidence_for_the_gate(self):
        state = self._state([{"العنوان": "أ"}])
        rollout.reconcile(client=self._client([]), state=state)
        events = [json.loads(line) for line in
                  open(os.path.join(self.tmp.name, "audit.jsonl"), encoding="utf-8")]
        self.assertTrue(any(event["event"] == "supabase_reconcile_done" for event in events))

    def test_render_reports_differences_clearly(self):
        report = {"drift": 1, "verdict": "1 فرقًا", "local_rows": 2, "remote_rows": 1,
                  "missing_in_mirror": ["abc"], "orphans_in_mirror": [], "mismatched": []}
        text = supabase_tasks.render_reconcile(report)
        self.assertIn("⚠️", text)
        self.assertIn("abc", text)


class PlanAndReportingTests(RolloutTestCase):
    def test_plan_lists_every_phase_and_the_never_retired_items(self):
        text = rollout.plan()
        for phase in rollout.PHASES:
            self.assertIn(phase, text)
        for item in rollout.NEVER_RETIRED:
            self.assertIn(item, text)

    def test_status_renders_gate_and_history(self):
        rollout.set_phase("shadow", reason="بدء")
        text = rollout.render_status(rollout.status())
        self.assertIn("shadow", text)
        self.assertIn("rollout kill", text)   # طريق التراجع ظاهر دائمًا

    def test_simulate_changes_nothing(self):
        before = rollout.load()
        text = rollout.simulate()
        self.assertEqual(rollout.load(), before)
        self.assertIn("صفر", text)

    def test_never_retired_keeps_state_authority(self):
        joined = " ".join(rollout.NEVER_RETIRED)
        self.assertIn("state.json", joined)
        self.assertIn("action_queue", joined)

    def test_no_phase_disables_the_old_workflow(self):
        """لا مرحلة تُطفئ أي شيء من النظام القديم."""
        for phase in rollout.PHASES:
            self.assertTrue(rollout.allows("automation_read", phase) or phase == "dormant")


class CLICommandTests(RolloutTestCase):
    def run_cli(self, argv):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = rollout.main(argv)
        return code, buffer.getvalue()

    def test_status_and_plan_and_simulate(self):
        for command in ("status", "plan", "simulate"):
            code, text = self.run_cli([command])
            self.assertEqual(code, 0, command)
            self.assertTrue(text.strip(), command)

    def test_advance_blocked_without_evidence_exits_2(self):
        code, text = self.run_cli(["advance"])
        self.assertEqual(code, 2)
        self.assertIn("لم تتغير", text)
        self.assertEqual(rollout.current_phase(), "dormant")

    def test_kill_switches_off_immediately(self):
        rollout.set_phase("shadow")
        code, text = self.run_cli(["kill"])
        self.assertEqual(code, 0)
        self.assertIn("dormant", text)
        self.assertEqual(rollout.current_phase(), "dormant")

    def test_rollback_with_target(self):
        rollout.set_phase("shadow")
        rollout.set_phase("canary")
        code, _ = self.run_cli(["rollback", "--to", "shadow", "--reason", "تراجع اختباري"])
        self.assertEqual(code, 0)
        self.assertEqual(rollout.current_phase(), "shadow")

    def test_rollback_to_unknown_phase_fails_cleanly(self):
        code, text = self.run_cli(["rollback", "--to", "nowhere"])
        self.assertEqual(code, 2)
        self.assertIn("غير معروفة", text)

    def test_gate_command_prints_json(self):
        self.write_audit([AUDIT_RECONCILE, AUDIT_RECONCILE])
        code, text = self.run_cli(["gate", "--to", "shadow"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(text)["ok"])


if __name__ == "__main__":
    unittest.main()
