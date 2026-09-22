#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ABH-Memory hub tests — routing, provenance envelope and governance gates.

Run:
    python3 tests/test_memory_hub.py
    python3 -m pytest tests/test_memory_hub.py -q
"""
from __future__ import annotations

import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
sys.path.insert(0, os.path.join(str(BASE), "engine"))

import memory_hub  # noqa: E402


class TestHubMap(unittest.TestCase):
    """V1 — the root map must parse and carry the registered projects."""

    def setUp(self):
        self.hub = memory_hub.parse_hub_map()

    def test_root_declaration(self):
        self.assertIn("ABH-Memory", self.hub["root"])

    def test_branches_parsed(self):
        names = [b["name"] for b in self.hub["branches"]]
        for expected in ("Active Projects", "Routing Rules", "Governance",
                         "Storage Boundaries", "Memory Layers", "Validation"):
            self.assertIn(expected, names)

    def test_three_active_projects_present(self):
        flat = " ".join(
            node
            for b in self.hub["branches"]
            for node in (
                [b["name"], *b["leaves"]]
                + [s["name"] for s in b.get("sub_branches", [])]
                + [leaf for s in b.get("sub_branches", []) for leaf in s["leaves"]]
            )
        )
        for pid in ("P1", "P2", "P3"):
            self.assertIn(pid, flat)

    def test_referenced_paths_resolve(self):
        """V2 — versioned references must resolve; runtime state is a warning.

        ``data/`` holds git-ignored runtime state that legitimately does not exist
        on a fresh clone, so it is exempted from the hard gate — but only when git
        also ignores it. A runtime path that is *not* ignored fails V2.
        """
        refs = memory_hub.referenced_paths(self.hub)
        self.assertTrue(refs, "hub map references no paths — routing would be useless")
        versioned = [r for r in refs if not r.startswith(memory_hub.RUNTIME_PREFIXES)]
        self.assertTrue(versioned, "hub references no versioned artefacts")
        missing = [r for r in versioned
                   if not os.path.exists(os.path.join(memory_hub.BASE, r))]
        self.assertEqual([], missing, f"dangling hub references: {missing}")

    def test_runtime_references_are_git_ignored(self):
        """A runtime path that is NOT git-ignored would fail V2 — assert the
        exemption is real rather than accidental."""
        refs = memory_hub.referenced_paths(self.hub)
        runtime = [r for r in refs if r.startswith(memory_hub.RUNTIME_PREFIXES)]
        self.assertTrue(runtime, "hub should reference runtime state locations")
        for rel in runtime:
            self.assertTrue(
                memory_hub._git_ignored(rel),
                f"runtime path {rel!r} is not git-ignored — personal state could "
                f"be committed. Add it to .gitignore.")

    def test_malformed_map_fails_closed(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("graph TD\n  A --> B\n")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                memory_hub.parse_hub_map(path)
        finally:
            os.unlink(path)

    def test_missing_map_raises(self):
        with self.assertRaises(FileNotFoundError):
            memory_hub.parse_hub_map(os.path.join(BASE, "does-not-exist.mmd"))


class TestRouting(unittest.TestCase):
    def test_route_by_id(self):
        self.assertEqual("P3", memory_hub.route("P3")["id"])
        self.assertEqual("P3", memory_hub.route("p3")["id"])

    def test_route_by_number(self):
        self.assertEqual("P2", memory_hub.route("2")["id"])

    def test_route_by_name_fragment(self):
        self.assertEqual("P3", memory_hub.route("pulse")["id"])
        self.assertEqual("P1", memory_hub.route("personal ai")["id"])
        self.assertEqual("P2", memory_hub.route("course")["id"])

    def test_route_unknown_returns_none(self):
        self.assertIsNone(memory_hub.route("P9"))
        self.assertIsNone(memory_hub.route(""))
        self.assertIsNone(memory_hub.route(None))

    def test_registry_shape(self):
        for proj in memory_hub.routing_table():
            for field in ("id", "name", "status", "domain", "charter", "owner",
                          "sensitivity", "clinical"):
                self.assertIn(field, proj)

    def test_p3_is_flagged_clinical(self):
        self.assertTrue(memory_hub.route("P3")["clinical"])
        self.assertEqual("clinical-adjacent", memory_hub.route("P3")["sensitivity"])

    def test_p1_and_p2_are_not_clinical(self):
        self.assertFalse(memory_hub.route("P1")["clinical"])
        self.assertFalse(memory_hub.route("P2")["clinical"])

    def test_every_active_project_has_a_charter_file(self):
        for proj in memory_hub.routing_table():
            if proj["status"] == "active":
                path = os.path.join(memory_hub.BASE, proj["charter"])
                self.assertTrue(os.path.exists(path),
                                f"{proj['id']} charter missing: {proj['charter']}")


class TestCharters(unittest.TestCase):
    """V5 — charters must declare the four required sections."""

    REQUIRED = ["Scope", "Guardrails", "Current state", "Next actions"]

    def test_charters_declare_required_sections(self):
        import re
        for proj in memory_hub.routing_table():
            path = os.path.join(memory_hub.BASE, proj["charter"])
            text = memory_hub._read(path)
            headings = re.findall(r"^#{1,4}\s+(.+?)\s*$", text, re.M)
            for section in self.REQUIRED:
                self.assertTrue(
                    any(section.lower() in h.lower() for h in headings),
                    f"{proj['id']} charter is missing section {section!r}")

    def test_charters_label_assumptions(self):
        for proj in memory_hub.routing_table():
            path = os.path.join(memory_hub.BASE, proj["charter"])
            text = memory_hub._read(path)
            self.assertIn("ASSUMPTION-", text,
                          f"{proj['id']} charter has no labelled assumptions (G6)")

    def test_charters_carry_risk_notes(self):
        for proj in memory_hub.routing_table():
            path = os.path.join(memory_hub.BASE, proj["charter"])
            text = memory_hub._read(path)
            self.assertIn("Risk notes", text,
                          f"{proj['id']} charter has no risk register (G4)")


class TestEveryRegisteredProjectInHubMap(unittest.TestCase):
    """V3 from the other side: registry ↔ map consistency is checked both ways."""

    def test_every_registered_project_in_hub_map(self):
        hub = memory_hub.parse_hub_map()
        flat = " ".join(
            node
            for b in hub["branches"]
            for node in (
                [b["name"], *b["leaves"]]
                + [s["name"] for s in b.get("sub_branches", [])]
                + [leaf for s in b.get("sub_branches", []) for leaf in s["leaves"]]
            )
        )
        for pid, proj in memory_hub.PROJECTS.items():
            self.assertIn(pid, flat,
                          f"{pid} · {proj['name']} missing from root_memory.mmd")
            self.assertIn(proj["charter"], flat,
                          f"{pid} charter path missing from root_memory.mmd")


class TestP4HubSelfRegistration(unittest.TestCase):
    """P4 · ABH-Memory Hub — the hub governs itself as a tracked project."""

    def test_registry_record(self):
        proj = memory_hub.PROJECTS.get("P4")
        self.assertIsNotNone(proj, "P4 must be registered in PROJECTS")
        self.assertEqual("active", proj["status"])
        self.assertEqual("ABH-Memory Hub", proj["name"])
        self.assertEqual("internal", proj["sensitivity"])
        self.assertFalse(proj["clinical"], "the hub is not a clinical project; "
                         "P3 keeps full custody of the clinical boundary")

    def test_charter_on_disk(self):
        path = os.path.join(memory_hub.BASE, memory_hub.PROJECTS["P4"]["charter"])
        self.assertTrue(os.path.exists(path))

    def test_charter_passes_guardrail_scans(self):
        """V6/V7 materialise over memory/projects/*.md — P4's own charter must
        come back with zero findings, exemptions included."""
        path = os.path.join(memory_hub.BASE, memory_hub.PROJECTS["P4"]["charter"])
        self.assertEqual([], memory_hub.scan_file(path))

    def test_route_to_p4(self):
        self.assertEqual("P4", memory_hub.route("P4")["id"])
        self.assertEqual("P4", memory_hub.route("4")["id"])
        self.assertEqual("P4", memory_hub.route("hub")["id"])

    def test_existing_fragments_still_resolve(self):
        """Regression: adding P4 must not steal P1–P3 fragment routes."""
        self.assertEqual("P1", memory_hub.route("personal ai")["id"])
        self.assertEqual("P2", memory_hub.route("course")["id"])
        self.assertEqual("P3", memory_hub.route("pulse")["id"])

    def test_envelope_for_hub_decisions(self):
        rec = memory_hub.envelope("P4", "DECISION", "owner brief 2026-09-22",
                                  "register the hub as a tracked project")
        self.assertTrue(rec["record_id"].startswith("P4-DEC-"))
        self.assertEqual("P4", rec["related_project"])


class TestEnvelope(unittest.TestCase):
    def test_envelope_required_fields(self):
        rec = memory_hub.envelope("P3", "DECISION", "regulatory check 2026-09-23",
                                 "home delivery position", "VERIFY")
        for field in ("record_id", "record_type", "source_ref", "captured_at",
                      "effective_date", "last_verified", "confidence", "owner",
                      "related_project", "status", "sensitivity"):
            self.assertIn(field, rec)
        self.assertTrue(rec["record_id"].startswith("P3-DEC-"))

    def test_record_type_vocabulary_is_closed(self):
        with self.assertRaises(ValueError):
            memory_hub.envelope("P1", "GUESS", "src", "summary")

    def test_confidence_vocabulary_is_closed(self):
        with self.assertRaises(ValueError):
            memory_hub.envelope("P1", "FACT", "src", "summary", "MAYBE")

    def test_unknown_project_rejected(self):
        with self.assertRaises(ValueError):
            memory_hub.envelope("P99", "FACT", "src", "summary")

    def test_record_id_is_deterministic(self):
        a = memory_hub.envelope("P2", "RECOMMENDATION", "s", "same summary")
        b = memory_hub.envelope("P2", "RECOMMENDATION", "s", "same summary")
        self.assertEqual(a["record_id"], b["record_id"])

    def test_different_summary_gives_different_id(self):
        a = memory_hub.envelope("P2", "RECOMMENDATION", "s", "summary one")
        b = memory_hub.envelope("P2", "RECOMMENDATION", "s", "summary two")
        self.assertNotEqual(a["record_id"], b["record_id"])

    def test_owner_defaults_to_project_owner(self):
        rec = memory_hub.envelope("P1", "FACT", "s", "x")
        self.assertEqual(rec["owner"], memory_hub.PROJECTS["P1"]["owner"])


class TestClaimGuardrail(unittest.TestCase):
    """V6 — GLOBAL_RULES §2: zero medical guarantees, zero exaggeration."""

    def assert_flagged(self, text, rule=None):
        hits = memory_hub.scan_text(text)
        self.assertTrue(hits, f"expected a finding for: {text!r}")
        if rule:
            self.assertIn(rule, [h["rule"] for h in hits])

    def assert_clean(self, text):
        hits = memory_hub.scan_text(text)
        self.assertEqual([], hits, f"unexpected finding in: {text!r} -> {hits}")

    def test_cure_promise_flagged(self):
        self.assert_flagged("This programme cures chronic back pain.", "CLM-1")

    def test_guarantee_flagged(self):
        self.assert_flagged("Guaranteed pain relief after the first session.", "CLM-2")

    def test_absolute_percentage_flagged(self):
        self.assert_flagged("100% effective treatment.", "CLM-2")

    def test_proven_to_heal_flagged(self):
        self.assert_flagged("Proven to heal rotator cuff tears.", "CLM-2")

    def test_fixed_timeline_flagged(self):
        self.assert_flagged("You will be pain free in 6 sessions.", "CLM-3")
        self.assert_flagged("Full recovery in 3 weeks.", "CLM-3")

    def test_superiority_flagged(self):
        self.assert_flagged("The best home rehab service in Jubail.", "CLM-4")
        self.assert_flagged("Better than hospital care.", "CLM-4")
        self.assert_flagged("The best home rehab in Jubail.", "CLM-4")
        self.assert_flagged("The most advanced clinic in the Kingdom.", "CLM-4")

    def test_policy_nouns_are_not_flagged(self):
        """Governance text must be able to NAME the forbidden classes without
        tripping the guardrail it exists to enforce."""
        self.assert_clean("Zero medical guarantees. Zero exaggerated claims.")
        self.assert_clean("No cure language, no certainty language.")
        self.assert_clean("Do not promise employment, income or certification.")
        self.assert_clean("No guarantees about learner outcomes.")
        self.assert_clean("Prohibited: fixed recovery timelines.")

    def test_cited_counter_examples_are_not_flagged(self):
        """A guardrail table cell quoting forbidden phrasing is exempt."""
        self.assert_clean('| "Guaranteed pain relief" | "A structured assessment" |')
        self.assert_clean('| "Cures chronic back pain" | "Commonly used for" |')

    def test_privacy_is_never_exempted_by_quoting(self):
        """An identifier is a breach wherever it appears, including in a table."""
        hits = memory_hub.scan_text('| "Prohibited" | Patient MRN: 99123 |')
        self.assertTrue(any(h["category"] == "privacy" for h in hits))

    def test_prohibition_exemption_cannot_smuggle_a_real_claim(self):
        """The prohibition heuristic must not become a bypass: an actual promise
        written without a prohibition marker is still caught."""
        self.assert_flagged("Our home programme delivers guaranteed results.", "CLM-2")
        self.assert_flagged("This protocol cures chronic back pain.", "CLM-1")

    def test_reversal_claim_flagged(self):
        self.assert_flagged("This therapy reverses nerve damage.", "CLM-5")

    def test_unverified_endorsement_flagged(self):
        self.assert_flagged("We are a CBAHI-accredited home service.", "CLM-6")
        self.assert_flagged("MOH-approved home physiotherapy.", "CLM-6")
        self.assert_flagged("RCJY-endorsed packages.", "CLM-6")

    def test_condition_outcome_promise_flagged(self):
        self.assert_flagged("Stroke patients will recover fully.", "CLM-7")

    def test_compliant_hedged_language_passes(self):
        self.assert_clean(
            "A structured assessment followed by an individualised plan. "
            "A typical course is 6 sessions; individual response varies. "
            "Home-based rehabilitation delivered in Jubail Industrial City, "
            "with documented infection-control and safety procedures. "
            "Commonly used in the management of persistent low back pain.")

    def test_findings_carry_location_and_context(self):
        hits = memory_hub.scan_text("line one\nGuaranteed results here\n")
        self.assertEqual(2, hits[0]["line"])
        self.assertEqual("FAIL", hits[0]["severity"])
        self.assertTrue(hits[0]["context"])

    def test_every_match_on_a_line_is_reported(self):
        """Regression: scan_text used .search(), so a SECOND violation on the same
        line was silently missed. Two endorsements on one line must both surface."""
        hits = memory_hub.scan_text(
            "RCJY-approved and CBAHI-accredited home service.")
        matches = [h["match"] for h in hits if h["rule"] == "CLM-6"]
        self.assertIn("RCJY-approved", matches)
        self.assertIn("CBAHI-accredited", matches)
        self.assertEqual(2, len(matches))

    def test_multiple_rules_fire_on_one_line(self):
        hits = memory_hub.scan_text(
            "Guaranteed relief — we cure back pain, the best service in Jubail.")
        rules = {h["rule"] for h in hits}
        for expected in ("CLM-1", "CLM-2", "CLM-4"):
            self.assertIn(expected, rules)

    def test_risk_free_treatment_flagged(self):
        self.assert_flagged("A risk-free treatment for neck pain.", "CLM-2")

    def test_per_line_cap_prevents_flooding(self):
        line = " ".join(["CBAHI-accredited"] * 50)
        hits = [h for h in memory_hub.scan_text(line) if h["rule"] == "CLM-6"]
        self.assertEqual(memory_hub.MAX_FINDINGS_PER_RULE_PER_LINE, len(hits))

    def test_privacy_multiple_matches_all_reported(self):
        hits = memory_hub.scan_text("MRN: 111 and MRN: 222")
        self.assertEqual(2, len([h for h in hits if h["rule"] == "PRV-1"]))


class TestPrivacyGuardrail(unittest.TestCase):
    """V7 — GLOBAL_RULES §3: no identifiers, no secrets."""

    def test_mrn_flagged(self):
        hits = memory_hub.scan_text("Patient MRN: 123456")
        self.assertTrue(any(h["rule"] == "PRV-1" for h in hits))

    def test_national_id_flagged(self):
        hits = memory_hub.scan_text("national id 1098765432")
        self.assertTrue(any(h["rule"] == "PRV-2" for h in hits))

    def test_named_patient_flagged(self):
        hits = memory_hub.scan_text("patient: Mohammed Alharbi")
        self.assertTrue(any(h["rule"] == "PRV-3" for h in hits))

    def test_client_mobile_flagged(self):
        hits = memory_hub.scan_text("client contact +966 54 568 4917")
        self.assertTrue(any(h["rule"] == "PRV-4" for h in hits))

    def test_secret_literal_flagged(self):
        hits = memory_hub.scan_text("api_key = 'sk_live_abcdefghijkl123456'")
        self.assertTrue(any(h["rule"] == "PRV-5" for h in hits))

    def test_case_code_passes(self):
        hits = memory_hub.scan_text("Case POL-HV-001 scheduled for assessment.")
        self.assertEqual([], hits)

    def test_exempt_files_are_not_scanned(self):
        self.assertEqual([], memory_hub.scan_file(memory_hub.GLOBAL_RULES))
        self.assertEqual([], memory_hub.scan_file(os.path.abspath(memory_hub.__file__)))


class TestValidate(unittest.TestCase):
    def test_full_validation_passes(self):
        report = memory_hub.validate()
        failed = [c for c in report["checks"] if not c["ok"]]
        self.assertEqual([], failed,
                         "hub validation failed:\n" + "\n".join(
                             f"  {c['id']} {c['label']}: {c['detail']} {c['items']}"
                             for c in failed))
        self.assertTrue(report["passed"])

    def test_all_eight_gates_present(self):
        report = memory_hub.validate()
        ids = [c["id"] for c in report["checks"]]
        for gate in ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"):
            self.assertIn(gate, ids)

    def test_report_is_serialisable(self):
        import json
        report = memory_hub.validate()
        json.dumps(report)  # must not raise

    def test_report_lists_scanned_artefacts(self):
        report = memory_hub.validate()
        self.assertTrue(report["artefacts_scanned"])
        self.assertIn("memory/GLOBAL_RULES.md", report["artefacts_scanned"])

    def test_sprint_file_is_scanned_and_clean(self):
        report = memory_hub.validate()
        sprint = "memory/sprints/2026-W39-pulse-of-life-home-visit.md"
        self.assertIn(sprint, report["artefacts_scanned"])
        claim_hits = [f for f in report["findings"] if f["category"] == "claim"]
        self.assertEqual([], claim_hits, f"claim findings: {claim_hits}")


class TestCLI(unittest.TestCase):
    def test_route_command(self):
        self.assertEqual(0, memory_hub.main(["route"]))

    def test_validate_command_passes(self):
        self.assertEqual(0, memory_hub.main(["validate"]))

    def test_validate_json_command(self):
        self.assertEqual(0, memory_hub.main(["validate", "--json"]))

    def test_no_command_prints_help(self):
        self.assertEqual(0, memory_hub.main([]))

    def test_scan_command_on_clean_file(self):
        target = os.path.join(BASE, "memory", "sprints",
                              "2026-W39-pulse-of-life-home-visit.md")
        self.assertEqual(0, memory_hub.main(["scan", target]))

    def test_scan_command_flags_bad_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8", dir=BASE) as fh:
            fh.write("# Bad copy\nGuaranteed cure for back pain in 2 weeks.\n")
            path = fh.name
        try:
            self.assertEqual(1, memory_hub.main(["scan", path]))
        finally:
            os.unlink(path)

    def test_scan_missing_file_errors(self):
        self.assertEqual(2, memory_hub.main(["scan", "no/such/file.md"]))

    def test_envelope_command(self):
        self.assertEqual(0, memory_hub.main([
            "envelope", "--project", "P3", "--type", "DECISION",
            "--source", "test", "--summary", "test summary"]))

    def test_envelope_command_rejects_bad_type(self):
        self.assertEqual(2, memory_hub.main([
            "envelope", "--project", "P3", "--type", "GUESS",
            "--source", "test", "--summary", "x"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
