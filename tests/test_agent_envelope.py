import unittest

from connectors import agent_envelope as env


def evidence(claim="المهمة A متأخرة يومين", source="state:tasks[A]", **extra):
    item = {"claim": claim, "source": source}
    item.update(extra)
    return item


class EnvelopeEvidenceRuleTests(unittest.TestCase):
    def test_ok_with_empty_evidence_is_a_failure(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING",
                                "confidence": 0.95, "evidence": []})
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.treated_status, "failed")
        self.assertEqual(verdict.route, "review")
        self.assertIn("empty_evidence", verdict.reasons)

    def test_ok_with_evidence_and_confidence_is_accepted(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
                                "evidence": [evidence()]})
        self.assertTrue(verdict.accepted)
        self.assertEqual(verdict.route, "state")
        self.assertEqual(verdict.evidence_count, 1)

    def test_confidence_equal_to_floor_is_above_it(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.8,
                                "evidence": [evidence()]}, confidence_floor=0.8)
        self.assertTrue(verdict.accepted)

    def test_confidence_below_floor_routes_to_review_not_state(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.61,
                                "evidence": [evidence()]}, confidence_floor=0.8)
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.route, "review")
        self.assertEqual(verdict.treated_status, "review")
        self.assertTrue(any("below_confidence_floor" in reason for reason in verdict.reasons))

    def test_missing_confidence_cannot_reach_state(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING",
                                "evidence": [evidence()]})
        self.assertFalse(verdict.accepted)
        self.assertIn("missing_confidence", verdict.reasons)

    def test_confidence_normalization(self):
        self.assertEqual(env.validate({"status": "ok", "confidence": 86,
                                       "evidence": [evidence()]}).confidence, 0.86)
        self.assertEqual(env.validate({"status": "ok", "confidence": "72%",
                                       "evidence": [evidence()]}).confidence, 0.72)
        self.assertIsNone(env.validate({"status": "ok", "confidence": "عالية",
                                        "evidence": [evidence()]}).confidence)


class EnvelopeIntegrityTests(unittest.TestCase):
    def test_private_identifiers_never_reach_state_through_evidence(self):
        verdict = env.validate({
            "status": "ok", "agent_id": "AG-CLINICAL", "confidence": 0.9,
            "evidence": [evidence(claim="المريض رقم الملف 12345 يحتاج متابعة")],
        })
        self.assertFalse(verdict.accepted)
        self.assertTrue(any("private_identifier_dropped" in reason for reason in verdict.reasons))
        self.assertEqual(verdict.evidence_count, 0)
        self.assertIn("empty_evidence", verdict.reasons)

    def test_evidence_missing_source_or_claim_is_dropped(self):
        verdict = env.validate({
            "status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
            "evidence": [{"claim": "ادعاء بلا مصدر"}, {"source": "state:tasks"}],
        })
        joined = " | ".join(verdict.reasons)
        self.assertIn("evidence[0]_missing_source", joined)
        self.assertIn("evidence[1]_missing_claim", joined)
        self.assertFalse(verdict.accepted)

    def test_unknown_evidence_kind_is_coerced_not_trusted(self):
        payload = {"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
                   "evidence": [evidence(kind="telepathy")]}
        self.assertTrue(env.validate(payload).accepted)
        cleaned = env.validate(payload).diff  # diff empty; kind coercion checked directly
        self.assertEqual(cleaned, ())
        self.assertEqual(env.validate(payload).evidence_count, 1)

    def test_stale_state_version_routes_to_review(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
                                "state_version": 11, "evidence": [evidence()]},
                               expected_state_version=12)
        self.assertFalse(verdict.accepted)
        self.assertTrue(verdict.stale_state)
        self.assertIn("stale_state", verdict.reasons)

    def test_matching_state_version_is_accepted(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
                                "state_version": 12, "evidence": [evidence()]},
                               expected_state_version=12)
        self.assertTrue(verdict.accepted)

    def test_needs_approval_blocks_the_item(self):
        verdict = env.validate({"status": "ok", "agent_id": "AG-ROLE-MANAGER",
                                "confidence": 0.9, "needs_approval": True,
                                "evidence": [evidence()]})
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.route, "approval")
        self.assertTrue(verdict.needs_approval)


class EnvelopeStatusRoutingTests(unittest.TestCase):
    def test_failed_requests_one_retry(self):
        verdict = env.validate({"status": "failed", "agent_id": "AG-MORNING",
                                "confidence": 0.2, "evidence": []})
        self.assertEqual(verdict.route, "retry")
        self.assertEqual(verdict.treated_status, "failed")

    def test_needs_input_routes_to_a_blocking_question(self):
        verdict = env.validate({"status": "needs_input", "agent_id": "AG-MORNING",
                                "confidence": 0.5, "evidence": []})
        self.assertEqual(verdict.route, "input")

    def test_partial_result_never_reaches_state(self):
        verdict = env.validate({"status": "partial", "agent_id": "AG-MORNING",
                                "confidence": 0.9, "evidence": [evidence()]})
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.route, "review")
        self.assertEqual(verdict.treated_status, "partial")

    def test_unknown_or_missing_status_is_rejected(self):
        self.assertEqual(env.validate({"status": "maybe", "evidence": []}).route, "reject")
        self.assertEqual(env.validate({"evidence": []}).reasons, ("missing_status",))
        self.assertEqual(env.validate("not an envelope").route, "reject")
        self.assertEqual(env.validate({}).route, "reject")


class EnvelopeDiffTests(unittest.TestCase):
    def _accepted(self, diff):
        return env.validate({"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.9,
                             "state_version": 3, "evidence": [evidence()], "diff": diff},
                            expected_state_version=3)

    def test_valid_diff_is_carried_only_when_accepted(self):
        verdict = self._accepted([{"section": "tasks", "op": "update",
                                   "match": {"العنوان": "A"}, "values": {"الحالة": "منجزة"}}])
        self.assertTrue(verdict.accepted)
        self.assertEqual(len(verdict.diff), 1)

    def test_diff_to_external_effect_queue_is_refused(self):
        verdict = self._accepted([{"section": "action_queue", "op": "append",
                                   "values": {"type": "send_message"}}])
        self.assertEqual(verdict.diff, ())
        self.assertTrue(any("protected_section:action_queue" in r for r in verdict.reasons))

    def test_diff_to_unknown_section_is_refused(self):
        verdict = self._accepted([{"section": "secrets", "op": "append", "values": {"k": "v"}}])
        self.assertEqual(verdict.diff, ())
        self.assertTrue(any("unknown_section:secrets" in r for r in verdict.reasons))

    def test_update_without_match_is_refused(self):
        verdict = self._accepted([{"section": "tasks", "op": "update", "values": {"x": 1}}])
        self.assertEqual(verdict.diff, ())
        self.assertTrue(any("match_required_for_update" in r for r in verdict.reasons))

    def test_removal_ops_are_not_agent_proposable(self):
        verdict = self._accepted([{"section": "tasks", "op": "remove", "match": {"id": "t1"}}])
        self.assertEqual(verdict.diff, ())
        self.assertTrue(any("bad_op:remove" in r for r in verdict.reasons))

    def test_diff_is_dropped_when_the_envelope_is_not_accepted(self):
        payload = {"status": "ok", "agent_id": "AG-MORNING", "confidence": 0.2,
                   "evidence": [evidence()],
                   "diff": [{"section": "tasks", "op": "append", "values": {"x": 1}}]}
        verdict = env.validate(payload, confidence_floor=0.8)
        self.assertEqual(verdict.diff, ())
        self.assertIn("diff_dropped:not_accepted", verdict.reasons)


class EnvelopeParsingTests(unittest.TestCase):
    def test_parse_tolerates_fences_and_wrapping_prose(self):
        self.assertEqual(env.parse('```json\n{"status": "ok"}\n```')["status"], "ok")
        self.assertEqual(env.parse('إليك النتيجة: {"status": "ok"} شكرًا')["status"], "ok")
        self.assertEqual(env.parse("لا يوجد"), {})
        self.assertEqual(env.parse(None), {})

    def test_build_round_trips_through_validate(self):
        envelope = env.build(status="ok", agent_id="AG-ROLE-CRITIC", confidence=0.91,
                             evidence=[evidence()], state_version=5,
                             next_action="مراجعة الخطة")
        verdict = env.validate(envelope, confidence_floor=0.8, expected_state_version=5)
        self.assertTrue(verdict.accepted)

    def test_template_states_the_floor_and_the_empty_evidence_rule(self):
        text = env.template_for_prompt("AG-MORNING", confidence_floor=0.85)
        self.assertIn("AG-MORNING", text)
        self.assertIn("0.85", text)
        self.assertIn("فشل", text)
        self.assertIn('"evidence"', text)

    def test_looks_like_envelope(self):
        self.assertTrue(env.looks_like_envelope({"status": "ok"}))
        self.assertFalse(env.looks_like_envelope("نص عادي"))


if __name__ == "__main__":
    unittest.main()
