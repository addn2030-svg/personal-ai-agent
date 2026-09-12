import datetime as dt
import tempfile
import unittest
from pathlib import Path

from connectors import agent_dispatch as dispatch_mod
from connectors import agent_registry as registry
from engine.store import SECTIONS, Store


def envelope(agent_id, *, status="ok", confidence=0.9, evidence=None, state_version=None,
             diff=None, needs_approval=False):
    body = {
        "status": status,
        "agent_id": agent_id,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else [
            {"claim": "دليل من الحالة", "source": "state:tasks[A]"}
        ],
        "needs_approval": needs_approval,
    }
    if state_version is not None:
        body["state_version"] = state_version
    if diff is not None:
        body["diff"] = diff
    return body


class DispatchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_knows_the_fleet_sections(self):
        self.assertIn("dispatches", SECTIONS)
        self.assertIn("dispatch_cycles", SECTIONS)

    def test_dispatch_key_is_stable_and_scoped(self):
        first = dispatch_mod.dispatch_key("AG-MORNING", "render_morning_brief", "بريف", "C-1")
        self.assertEqual(first, dispatch_mod.dispatch_key("AG-MORNING", "render_morning_brief", "بريف", "C-1"))
        self.assertNotEqual(first, dispatch_mod.dispatch_key("AG-MORNING", "render_morning_brief", "بريف", "C-2"))
        self.assertNotEqual(first, dispatch_mod.dispatch_key("AG-FINANCE", "render_morning_brief", "بريف", "C-1"))

    def test_dispatch_records_a_queued_row(self):
        row = dispatch_mod.dispatch("AG-MORNING", "بريف الصباح", capability="render_morning_brief",
                                    payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        self.assertEqual(row["status"], "queued")
        self.assertTrue(row["dispatch_id"].startswith("D-"))
        self.assertEqual(row["capability_matched"], True)
        self.assertEqual(len(dispatch_mod.ledger(self.store, cycle_id="C-1")), 1)

    def test_identical_dispatch_in_the_same_cycle_is_not_executed_twice(self):
        first = dispatch_mod.dispatch("AG-MORNING", "بريف الصباح", capability="render_morning_brief",
                                      payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        second = dispatch_mod.dispatch("AG-MORNING", "بريف الصباح", capability="render_morning_brief",
                                       payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        self.assertTrue(second.get("deduped"))
        self.assertEqual(second["dispatch_id"], first["dispatch_id"])
        self.assertEqual(len(dispatch_mod.ledger(self.store)), 1)

    def test_same_task_in_a_new_cycle_is_a_new_dispatch(self):
        dispatch_mod.dispatch("AG-MORNING", "بريف الصباح", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        dispatch_mod.dispatch("AG-MORNING", "بريف الصباح", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-2", store=self.store)
        self.assertEqual(len(dispatch_mod.ledger(self.store)), 2)

    def test_ledger_keeps_a_digest_not_the_payload(self):
        row = dispatch_mod.dispatch("AG-MORNING", "بريف يتضمن تفاصيل تشغيلية",
                                    capability="render_morning_brief",
                                    payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        self.assertEqual(row["task_preview"], "")
        self.assertEqual(len(row["task_digest"]), 16)
        self.assertNotIn("بريف", str(row))

    def test_preview_is_opt_in_and_bounded(self):
        row = dispatch_mod.dispatch("AG-MORNING", "س" * 400, capability="render_morning_brief",
                                    payload={"date": "2026-09-12"}, cycle_id="C-1",
                                    preview=True, store=self.store)
        self.assertEqual(len(row["task_preview"]), dispatch_mod.TASK_PREVIEW_CHARS)


class DispatchGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_agent_is_refused(self):
        with self.assertRaises(registry.UnknownAgent):
            dispatch_mod.dispatch("AG-GHOST", "مهمة", store=self.store)

    def test_capability_not_declared_by_the_agent_is_refused(self):
        with self.assertRaises(registry.CapabilityMismatch):
            dispatch_mod.dispatch("AG-MORNING", "مهمة", capability="prepare_finance_review",
                                  payload={"period": "2026-09"}, store=self.store)

    def test_suspended_agent_is_not_dispatched(self):
        registry.set_status("AG-MORNING", "retired", self.store)
        with self.assertRaises(dispatch_mod.AgentSuspended):
            dispatch_mod.dispatch("AG-MORNING", "مهمة", capability="render_morning_brief",
                                  payload={"date": "2026-09-12"}, store=self.store)

    def test_input_schema_violation_is_recorded_for_misroute_measurement(self):
        with self.assertRaises(dispatch_mod.InputRejected) as ctx:
            dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                                  payload={"period": "2026-09"}, store=self.store)
        self.assertIn("حقل مطلوب ناقص: date", ctx.exception.errors)
        rows = dispatch_mod.ledger(self.store)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertFalse(rows[0]["executed"])
        # A refused dispatch must not consume a cycle slot.
        self.assertEqual(dispatch_mod.cycle_state(self.store, cycle_id=rows[0]["cycle_id"])["executed"], 0)

    def test_plan_reports_before_anything_is_written(self):
        decision = dispatch_mod.plan("AG-MORNING", capability="render_morning_brief",
                                     payload={"date": "2026-09-12"}, store=self.store)
        self.assertEqual(decision["confidence_floor"], 0.8)
        self.assertEqual(decision["input_errors"], [])
        self.assertEqual(dispatch_mod.ledger(self.store), [])


class DispatchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_cap_halts_the_cycle_and_reports_partial_results(self):
        budget = dispatch_mod.Budget(max_agents_per_cycle=1)
        dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-CAP",
                              store=self.store, budget=budget)
        with self.assertRaises(dispatch_mod.CycleCapReached) as ctx:
            dispatch_mod.dispatch("AG-FINANCE", "مراجعة", capability="prepare_finance_review",
                                  payload={"period": "2026-09"}, cycle_id="C-CAP",
                                  store=self.store, budget=budget)
        self.assertIn("max_agents_per_cycle=1", ctx.exception.reason)
        self.assertEqual(ctx.exception.summary["executed"], 1)
        self.assertEqual(len(dispatch_mod.ledger(self.store)), 1)

    def test_halted_cycle_stays_halted(self):
        budget = dispatch_mod.Budget(max_agents_per_cycle=1)
        dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-CAP",
                              store=self.store, budget=budget)
        with self.assertRaises(dispatch_mod.CycleCapReached):
            dispatch_mod.dispatch("AG-FINANCE", "مراجعة", capability="prepare_finance_review",
                                  payload={"period": "2026-09"}, cycle_id="C-CAP",
                                  store=self.store, budget=budget)
        with self.assertRaises(dispatch_mod.CycleCapReached):
            dispatch_mod.dispatch("AG-KNOWLEDGE", "ملخص", capability="digest_source_material",
                                  payload={"source_ref": "doc:1"}, cycle_id="C-CAP",
                                  store=self.store, budget=dispatch_mod.Budget(max_agents_per_cycle=9))
        self.assertEqual(len(dispatch_mod.ledger(self.store)), 1)
        self.assertEqual(dispatch_mod.metrics(self.store)["cycle_halts"], 1)

    def test_token_cap_counts_reservations(self):
        budget = dispatch_mod.Budget(max_agents_per_cycle=5, max_tokens_per_cycle=500)
        dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-TOK",
                              store=self.store, budget=budget, reserve_tokens=400)
        with self.assertRaises(dispatch_mod.CycleCapReached) as ctx:
            dispatch_mod.dispatch("AG-FINANCE", "مراجعة", capability="prepare_finance_review",
                                  payload={"period": "2026-09"}, cycle_id="C-TOK",
                                  store=self.store, budget=budget, reserve_tokens=200)
        self.assertIn("max_tokens_per_cycle", ctx.exception.reason)

    def test_wall_clock_cap_halts_a_cycle_that_dragged(self):
        budget = dispatch_mod.Budget(max_wall_clock_s=60)
        dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                              payload={"date": "2026-09-12"}, cycle_id="C-SLOW",
                              store=self.store, budget=budget)

        def backdate(state):
            for marker in state.setdefault("dispatch_cycles", []):
                if marker.get("cycle_id") == "C-SLOW":
                    marker["started_at"] = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat(timespec="seconds")
                    return True, marker
            return False, None

        self.store.transaction(backdate, "test_backdate")
        with self.assertRaises(dispatch_mod.CycleCapReached) as ctx:
            dispatch_mod.dispatch("AG-FINANCE", "مراجعة", capability="prepare_finance_review",
                                  payload={"period": "2026-09"}, cycle_id="C-SLOW",
                                  store=self.store, budget=budget)
        self.assertIn("max_wall_clock_s", ctx.exception.reason)

    def test_budget_bounds_and_validation(self):
        self.assertEqual(dispatch_mod.Budget(max_agents_per_cycle=999).clamped().max_agents_per_cycle, 20)
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.Budget(max_agents_per_cycle=0).clamped()
        self.assertIn("سقوف دورة الإرسال", dispatch_mod.budget_text())


class DispatchSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)
        self.row = dispatch_mod.dispatch(
            "AG-ROLE-CRITIC", "راجع الخطة", capability="review_plan_risks",
            payload={"subject_ref": "plan:W37"}, cycle_id="C-1", store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def settle(self, payload, **kwargs):
        return dispatch_mod.settle(self.row["dispatch_id"], payload, store=self.store, **kwargs)

    def test_accepted_settlement_writes_the_ledger_only(self):
        before = self.store.rows_all()
        result = self.settle(envelope("AG-ROLE-CRITIC", state_version=self.row["state_version"]),
                             latency_ms=820, tokens=340, cost_sar=0.21)
        self.assertTrue(result["verdict"].accepted)
        self.assertEqual(result["row"]["status"], "accepted")
        self.assertEqual(result["row"]["tokens"], 340)
        self.assertEqual(self.store.rows_all()["tasks"], before["tasks"])

    def test_empty_evidence_failure_is_recorded_and_retried_once(self):
        # ok + empty evidence is recorded as a failure (the rule), routed to review,
        # and earns exactly one retry before it must be reported as a RISK item.
        result = self.settle(envelope("AG-ROLE-CRITIC", evidence=[]))
        self.assertEqual(result["row"]["status"], "failed")
        self.assertEqual(result["row"]["route"], "review")
        self.assertIn("empty_evidence", result["row"]["verdict_reasons"])
        self.assertTrue(result["retry_allowed"])
        dispatch_mod.retry(self.row["dispatch_id"], store=self.store)
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.retry(dispatch_mod.ledger(self.store)[-1]["dispatch_id"], store=self.store)

    def test_settlement_is_idempotent(self):
        self.settle(envelope("AG-ROLE-CRITIC", state_version=self.row["state_version"]))
        again = self.settle(envelope("AG-ROLE-CRITIC", confidence=0.2))
        self.assertTrue(again.get("deduped"))
        self.assertEqual(again["row"]["status"], "accepted")

    def test_agent_cannot_answer_as_another_agent(self):
        result = self.settle(envelope("AG-MORNING", state_version=self.row["state_version"]))
        self.assertEqual(result["row"]["status"], "review")
        self.assertIn("agent_id_mismatch", result["row"]["verdict_reasons"])

    def test_state_moving_under_the_agent_forces_review(self):
        def touch(state):
            state.setdefault("tasks", []).append({"العنوان": "تغيّر بعد الإرسال"})
            return True, None

        self.store.transaction(touch, "test_state_moved")
        result = self.settle(envelope("AG-ROLE-CRITIC", state_version=self.row["state_version"]))
        self.assertEqual(result["row"]["status"], "review")
        self.assertIn("state_moved_since_dispatch", result["row"]["verdict_reasons"])

    def test_ledger_writes_alone_do_not_make_work_stale(self):
        # The dispatch itself bumps meta.version; that must not invalidate the agent's read.
        result = self.settle(envelope("AG-ROLE-CRITIC", state_version=self.row["state_version"]))
        self.assertEqual(result["row"]["status"], "accepted")

    def test_needs_approval_blocks_without_an_approval_id(self):
        result = self.settle(envelope("AG-ROLE-MANAGER" and "AG-ROLE-CRITIC", needs_approval=True,
                                      state_version=self.row["state_version"]))
        self.assertEqual(result["row"]["status"], "approval_pending")
        self.assertTrue(result["row"]["route"] == "approval")

    def test_confidence_floor_comes_from_the_registry_card(self):
        # AG-CLINICAL declares 0.85, so 0.80 is below its floor while above the default.
        row = dispatch_mod.dispatch("AG-CLINICAL", "تقرير القسم", capability="report_section_kpis",
                                    payload={"period": "2026-09"}, cycle_id="C-2", store=self.store)
        result = dispatch_mod.settle(row["dispatch_id"],
                                     envelope("AG-CLINICAL", confidence=0.80,
                                              state_version=row["state_version"]),
                                     store=self.store)
        self.assertEqual(result["row"]["status"], "review")


class StateWriteGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)
        self.row = dispatch_mod.dispatch(
            "AG-ROLE-MANAGER", "وفّق الخطة", capability="synthesize_mission_plan",
            payload={"objective": "خطة"}, cycle_id="C-1", store=self.store)
        dispatch_mod.settle(self.row["dispatch_id"],
                            envelope("AG-ROLE-MANAGER", state_version=self.row["state_version"]),
                            store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_from_a_reviewed_dispatch_is_refused(self):
        row = dispatch_mod.dispatch("AG-ROLE-RESEARCHER", "مسح", capability="scan_external_sources",
                                    payload={"question": "q"}, cycle_id="C-2", store=self.store)
        dispatch_mod.settle(row["dispatch_id"],
                            envelope("AG-ROLE-RESEARCHER", confidence=0.2,
                                     state_version=row["state_version"]), store=self.store)
        with self.assertRaises(dispatch_mod.UnverifiedSource):
            dispatch_mod.state_apply([{"section": "tasks", "op": "append", "values": {"x": 1}}],
                                     source_ref=row["dispatch_id"], store=self.store)

    def test_write_from_an_unknown_source_is_refused(self):
        with self.assertRaises(dispatch_mod.UnknownDispatch):
            dispatch_mod.state_apply([{"section": "tasks", "op": "append", "values": {"x": 1}}],
                                     source_ref="D-9999", store=self.store)

    def test_external_effect_sections_can_never_be_written(self):
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.state_apply([{"section": "action_queue", "op": "append",
                                       "values": {"type": "send_message"}}],
                                     source_ref="user_statement", store=self.store)

    def test_empty_batch_is_refused(self):
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.state_apply([], source_ref="user_statement", store=self.store)

    def test_verified_write_is_atomic_and_recorded_as_inverse(self):
        result = dispatch_mod.state_apply(
            [{"section": "tasks", "op": "append", "values": {"العنوان": "خطوة من الوكيل"}}],
            source_ref=self.row["dispatch_id"], store=self.store)
        self.assertEqual(result["applied"], 1)
        self.assertTrue(any(t.get("العنوان") == "خطوة من الوكيل" for t in self.store.rows_all()["tasks"]))
        stored = dispatch_mod.find(self.row["dispatch_id"], self.store)
        self.assertEqual(len(stored["inverse"]), 1)

    def test_failed_operation_rolls_back_the_whole_batch(self):
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.state_apply(
                [{"section": "tasks", "op": "append", "values": {"العنوان": "يجب ألا يُكتب"}},
                 {"section": "projects", "op": "update", "match": {"المشروع": "غير موجود"},
                  "values": {"الحالة": "نشط"}}],
                source_ref=self.row["dispatch_id"], store=self.store)
        self.assertFalse(any(t.get("العنوان") == "يجب ألا يُكتب"
                             for t in self.store.rows_all()["tasks"]))

    def test_revert_undoes_exactly_one_write(self):
        dispatch_mod.state_apply(
            [{"section": "projects", "op": "append",
              "values": {"المشروع": "مشروع من الوكيل", "الحالة": "نشط"}}],
            source_ref=self.row["dispatch_id"], store=self.store)
        dispatch_mod.revert(self.row["dispatch_id"], store=self.store)
        self.assertFalse(any(p.get("المشروع") == "مشروع من الوكيل"
                             for p in self.store.rows_all()["projects"]))
        with self.assertRaises(dispatch_mod.DispatchError):
            dispatch_mod.revert(self.row["dispatch_id"], store=self.store)

    def test_user_statement_writes_are_allowed(self):
        result = dispatch_mod.state_apply(
            [{"section": "tasks", "op": "append", "values": {"العنوان": "قرار من عبدالرحمن"}}],
            source_ref="user_statement", store=self.store)
        self.assertEqual(result["applied"], 1)


class DispatchMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.upgrade(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_metrics_are_undefined_rather_than_invented_when_there_is_no_data(self):
        data = dispatch_mod.metrics(self.store)
        self.assertEqual(data["dispatches"], 0)
        self.assertIsNone(data["autonomy_rate"])
        self.assertIsNone(data["misroute_rate"])
        self.assertIsNone(data["cost_per_accepted"])

    def test_misroute_rate_counts_only_measured_dispatches(self):
        good = dispatch_mod.dispatch("AG-ROLE-CRITIC", "راجع", capability="review_plan_risks",
                                     payload={"subject_ref": "x"}, cycle_id="C-1", store=self.store)
        dispatch_mod.settle(good["dispatch_id"],
                            envelope("AG-ROLE-CRITIC", state_version=good["state_version"]),
                            store=self.store, human_edited=False, cost_sar=0.5)
        wrong = dispatch_mod.dispatch("AG-ROLE-CRITIC", "راجع", capability="review_plan_risks",
                                      payload={"subject_ref": "y"}, cycle_id="C-2", store=self.store)
        dispatch_mod.settle(wrong["dispatch_id"],
                            envelope("AG-ROLE-CRITIC", state_version=wrong["state_version"]),
                            store=self.store, human_edited=True, human_reassigned=True)
        # A dispatch with no declared capability is unmeasured, never assumed correct.
        blind = dispatch_mod.dispatch("AG-MORNING", "بريف", cycle_id="C-3", store=self.store)
        dispatch_mod.settle(blind["dispatch_id"],
                            envelope("AG-MORNING", state_version=blind["state_version"]),
                            store=self.store)

        data = dispatch_mod.metrics(self.store)
        self.assertEqual(data["misroute_measured"], 2)
        self.assertEqual(data["misroute_unmeasured"], 1)
        self.assertEqual(data["misroute_rate"], 0.5)
        self.assertEqual(data["autonomy_rate"], 0.5)
        # Three accepted items share the 0.5 SAR spent on the first one.
        self.assertEqual(data["cost_per_accepted"], round(0.5 / 3, 4))

    def test_metrics_text_reports_the_fleet(self):
        row = dispatch_mod.dispatch("AG-MORNING", "بريف", capability="render_morning_brief",
                                    payload={"date": "2026-09-12"}, cycle_id="C-1", store=self.store)
        dispatch_mod.settle(row["dispatch_id"], envelope("AG-MORNING", evidence=[]), store=self.store)
        text = dispatch_mod.metrics_text(self.store)
        self.assertIn("مقاييس الأسطول", text)
        self.assertIn("فشل بدليل فارغ: 1", text)


class DispatchDemoTests(unittest.TestCase):
    def test_demo_walks_the_whole_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "state.json"))
            result = dispatch_mod.demo(store=store, quiet=True)
            text = result["text"]
            self.assertIn("رُفض تسجيل قدرة مملوكة", text)
            self.assertIn("deduped=True", text)
            self.assertIn("status=ok بدليل فارغ", text)
            self.assertIn("سقف الدورة أوقف الإرسال", text)
            self.assertGreaterEqual(result["rows"], 4)


if __name__ == "__main__":
    unittest.main()
