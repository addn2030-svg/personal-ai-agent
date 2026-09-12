import tempfile
import unittest
from pathlib import Path

from connectors import agent_registry as registry
from engine.store import Store


def card(**overrides):
    base = {
        "agent_id": "AG-TEST",
        "name": "Test Agent",
        "role": "وكيل اختبار",
        "capabilities": ["draft_test_note"],
        "input_schema": {"required": ["subject"], "properties": {"subject": "string"}},
        "confidence_floor": 0.8,
        "cost_class": "low",
    }
    base.update(overrides)
    return base


class RegistryVocabularyTests(unittest.TestCase):
    def test_prose_capability_is_rejected(self):
        message = registry.validate_capability("clinical documentation")
        self.assertIsNotNone(message)
        self.assertIn("snake_case", message)

    def test_noun_first_capability_is_rejected(self):
        # The overlap root cause: a domain noun matches several agents equally well.
        self.assertIsNotNone(registry.validate_capability("clinical_documentation"))
        self.assertIsNotNone(registry.validate_capability("operations_report"))

    def test_verb_first_capability_is_accepted(self):
        self.assertIsNone(registry.validate_capability("draft_ops_directive"))
        self.assertIsNone(registry.validate_capability("track_supervisor_close"))
        self.assertIsNone(registry.validate_capability("verify_claims"))

    def test_card_requires_capabilities_schema_floor_and_cost(self):
        errors = registry.validate_card({
            "agent_id": "AG-X", "name": "n", "role": "r",
            "capabilities": [], "cost_class": "cheap",
        })
        joined = " | ".join(errors)
        self.assertIn("capabilities", joined)
        self.assertIn("input_schema", joined)
        self.assertIn("confidence_floor", joined)
        self.assertIn("cost_class", joined)

    def test_input_schema_rejects_unknown_property_type_and_undeclared_required(self):
        errors = registry.validate_input_schema({
            "required": ["a", "b"], "properties": {"a": "string", "b": "uuid"}, "extra": 1,
        })
        joined = " | ".join(errors)
        self.assertIn("مفتاح غير مدعوم", joined)
        self.assertIn("uuid", joined)

    def test_validate_input_type_and_required(self):
        schema = {"required": ["subject"], "properties": {"subject": "string", "count": "int"}}
        self.assertEqual(registry.validate_input(schema and {"input_schema": schema}, {"subject": "x", "count": 2}), [])
        errors = registry.validate_input({"input_schema": schema}, {"count": "2"})
        self.assertIn("حقل مطلوب ناقص: subject", errors)
        self.assertIn("count يجب أن يكون int", errors)

    def test_undeclared_payload_field_is_refused(self):
        schema = {"required": ["subject"], "properties": {"subject": "string"}}
        errors = registry.validate_input({"input_schema": schema}, {"subject": "x", "sneaky": 1})
        self.assertIn("حقل غير معلن في input_schema: sneaky", errors)


class RegistryOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))
        registry.register(card(), self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_capability_across_agents_is_rejected(self):
        with self.assertRaises(registry.CapabilityConflict) as ctx:
            registry.register(card(agent_id="AG-OTHER", name="Other"), self.store)
        self.assertIn("draft_test_note", str(ctx.exception))
        # The refusal must state the fix, not just the error.
        self.assertIn("reassign_from", str(ctx.exception))

    def test_capability_only_duplicated_inside_one_card_is_rejected(self):
        with self.assertRaises(registry.RegistryError):
            registry.register(card(agent_id="AG-DUP",
                                   capabilities=["draft_test_note", "draft_test_note"]), self.store)

    def test_explicit_reassign_transfers_ownership(self):
        registry.register(card(agent_id="AG-OTHER", name="Other",
                               capabilities=["draft_test_note"]),
                          self.store, reassign_from="AG-TEST")
        self.assertEqual(registry.resolve("draft_test_note", self.store), "AG-OTHER")
        self.assertEqual(registry.get_card("AG-TEST", self.store)["capabilities"], [])

    def test_reassign_from_wrong_owner_is_refused(self):
        # AG-THIRD wants a capability owned by AG-TEST but blames AG-OTHER: refused.
        registry.register(card(agent_id="AG-OTHER", name="Other",
                               capabilities=["draft_other_note"]), self.store)
        with self.assertRaises(registry.CapabilityConflict):
            registry.register(card(agent_id="AG-THIRD", name="Third"),
                              self.store, reassign_from="AG-OTHER")
        self.assertEqual(registry.resolve("draft_test_note", self.store), "AG-TEST")

    def test_losing_the_last_capability_retires_the_former_owner(self):
        registry.register(card(agent_id="AG-OTHER", name="Other",
                               capabilities=["draft_test_note"]),
                          self.store, reassign_from="AG-TEST")
        former = registry.get_card("AG-TEST", self.store)
        self.assertEqual(former["status"], "retired")
        self.assertEqual(former["capabilities"], [])
        self.assertIn("AG-OTHER", former["status_note"])

    def test_unknown_capability_names_the_available_set(self):
        with self.assertRaises(registry.UnknownCapability) as ctx:
            registry.resolve("publish_anything", self.store)
        self.assertIn("draft_test_note", str(ctx.exception))
        self.assertIn("لا تخترع", str(ctx.exception))

    def test_unknown_agent_lists_known_agents(self):
        with self.assertRaises(registry.UnknownAgent) as ctx:
            registry.get_card("AG-GHOST", self.store)
        self.assertIn("AG-TEST", str(ctx.exception))

    def test_pausing_an_agent_frees_its_capability(self):
        registry.set_status("AG-TEST", "paused", self.store, note="تحت المراجعة")
        self.assertIsNone(registry.owner_of("draft_test_note", self.store))
        registry.register(card(agent_id="AG-OTHER", name="Other"), self.store)
        self.assertEqual(registry.resolve("draft_test_note", self.store), "AG-OTHER")

    def test_rows_without_cards_are_told_to_run_upgrade(self):
        store = Store(str(Path(self.tmp.name) / "plain.json"))
        state = store.rows_all()
        state["sub_agents"] = [{"agent_id": "AG-PLAIN", "role": "بلا بطاقة"}]
        store.commit(state, "seed_plain")
        with self.assertRaises(registry.RegistryError) as ctx:
            registry.get_card("AG-PLAIN", store)
        self.assertIn("upgrade", str(ctx.exception))


class RegistrySeedAndDriftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "state.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_upgrade_registers_seed_cards_once(self):
        first = registry.upgrade(self.store)
        self.assertEqual(len(first["added"]), len(registry.SEED_CARDS))
        second = registry.upgrade(self.store)
        self.assertEqual(second, {"added": [], "updated": []})
        self.assertEqual(len(registry.cards(self.store)), len(registry.SEED_CARDS))

    def test_upgrade_preserves_operational_row_fields(self):
        state = self.store.rows_all()
        state["sub_agents"] = [{"agent_id": "AG-MORNING", "seq": 1, "seed": "sub-agents-matrix",
                                "cadence_jobs": ["daily.morning_brief_0645"]}]
        self.store.commit(state, "seed_rows")
        registry.upgrade(self.store)
        row = registry.get_card("AG-MORNING", self.store)
        self.assertEqual(row["seq"], 1)
        self.assertEqual(row["cadence_jobs"], ["daily.morning_brief_0645"])
        self.assertTrue(row["capabilities"])

    def test_seed_capabilities_are_global_unique(self):
        registry.upgrade(self.store)
        seen = {}
        for row in registry.cards(self.store):
            for capability in row["capabilities"]:
                self.assertNotIn(capability, seen,
                                 f"capability duplicated: {capability}")
                seen[capability] = row["agent_id"]

    def test_clean_install_has_no_drift(self):
        registry.upgrade(self.store)
        self.assertEqual(registry.drift(self.store), [])

    def test_drift_flags_duplicate_owners(self):
        registry.upgrade(self.store)
        state = self.store.rows_all()
        for row in state["sub_agents"]:
            if row["agent_id"] == "AG-FINANCE":
                row["capabilities"] = list(row["capabilities"]) + ["render_morning_brief"]
        self.store.commit(state, "inject_duplicate")
        findings = registry.drift(self.store)
        self.assertTrue(any("مملوكة مرتين" in f and "render_morning_brief" in f for f in findings))

    def test_drift_flags_scheduled_agent_without_card(self):
        # The integration hazard: JOB_SPECS[].agent is load-bearing, so a scheduled agent
        # without a card must be visible before anyone re-splits the taxonomy.
        findings = registry.drift(self.store)
        self.assertTrue(any("AG-CLINICAL" in f and "بلا بطاقة" in f for f in findings))

    def test_drift_flags_card_claiming_scheduler_but_absent_from_specs(self):
        registry.register(card(agent_id="AG-GHOST-SCHED", name="Ghost",
                               capabilities=["draft_ghost_note"], invoked_by="scheduler"),
                          self.store)
        findings = registry.drift(self.store)
        self.assertTrue(any("AG-GHOST-SCHED" in f and "JOB_SPECS" in f for f in findings))

    def test_status_text_reports_registry_and_drift(self):
        registry.upgrade(self.store)
        text = registry.status_text(self.store)
        self.assertIn("قدرات معلنة", text)
        self.assertIn("AG-ROLE-CRITIC", text)


if __name__ == "__main__":
    unittest.main()
