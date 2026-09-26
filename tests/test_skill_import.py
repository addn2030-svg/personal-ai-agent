# -*- coding: utf-8 -*-
"""اختبارات استيراد المهارات الخارجية (ECC) — الحارس بين كتالوج غريب وذاكرتنا الإجرائية.

القاعدة المُختبَرة: **مصدر خارجي لا يمنح ثقة.** كل مستورد يدخل CANDIDATE،
ولا ينزل إلى طبقة `low`، ولا يُحمَّل في السياق قبل اعتماد بشري — والنص المشبوه يُرفض.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

# وحدات engine تستورد بعضها باسم مجرد (`from skill_registry import ...`).
# نستوردها هنا بالطريقة نفسها كي تكون نسخة الوحدة **واحدة**؛ خلط
# `engine.skill_registry` مع `skill_registry` ينتج كائنين منفصلين
# فترقيع أحدهما لا يمس الآخر — والاختبار حينها يكتب في السجل الحقيقي.
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE, os.path.join(BASE, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import skill_import  # noqa: E402
import skill_registry  # noqa: E402
import skill_runtime  # noqa: E402

SKILL_OK = """---
name: context-budget
description: Manage context window budget across agent turns.
---

# Context Budget

Keep the working set small and evict by age.
"""

SKILL_SECRET = """---
name: leaky
description: Example integration guide.
---

Use this key: sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345
"""

SKILL_NO_DESC = """---
name: nameless
---

Body without a description.
"""


def write_skill(root, slug, text):
    folder = os.path.join(root, slug)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write(text)


class SkillImportTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "ecc-skills")
        os.makedirs(self.src)

        data_dir = os.path.join(self.tmp.name, "self_improvement")
        skills_dir = os.path.join(self.tmp.name, "generated")
        os.makedirs(data_dir); os.makedirs(skills_dir)
        for attr, value in (("DATA_DIR", data_dir), ("SKILLS_DIR", skills_dir),
                            ("REGISTRY", os.path.join(data_dir, "skills.json"))):
            patcher = mock.patch.object(skill_registry, attr, value)
            patcher.start(); self.addCleanup(patcher.stop)
        # المسارات في السجل نسبية لجذر المشروع؛ نثبّت الجذر على المجلد المؤقت
        patcher = mock.patch.object(skill_registry, "BASE", self.tmp.name)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = mock.patch.object(skill_runtime, "BASE", self.tmp.name)
        patcher.start(); self.addCleanup(patcher.stop)

    # ------------------------------------------------------------ parsing

    def test_frontmatter_splits_metadata_from_body(self):
        meta, body = skill_import._frontmatter(SKILL_OK)
        self.assertEqual(meta["name"], "context-budget")
        self.assertIn("Manage context window budget", meta["description"])
        self.assertTrue(body.startswith("# Context Budget"))
        self.assertNotIn("---", body.splitlines()[0])

    def test_frontmatter_ignores_nested_keys(self):
        meta, _ = skill_import._frontmatter("---\nname: x\nmetadata:\n  origin: ECC\n---\nbody\n")
        self.assertEqual(meta["name"], "x")
        self.assertNotIn("origin", meta)

    def test_body_without_frontmatter_is_preserved(self):
        meta, body = skill_import._frontmatter("# Plain\n\ntext\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "# Plain\n\ntext\n")

    # ------------------------------------------------------------ classification

    def test_engineering_skill_defaults_to_review_tier(self):
        self.assertEqual(skill_import.classify("api-connector-builder", "Build connectors."),
                         ("projects", "review"))

    def test_healthcare_slug_is_locked_clinical(self):
        self.assertEqual(skill_import.classify("healthcare-phi-compliance", "PHI rules."),
                         ("clinical", "locked"))

    def test_security_slug_is_locked(self):
        _, tier = skill_import.classify("django-security", "Harden Django apps.")
        self.assertEqual(tier, "locked")

    def test_deployment_slug_is_locked_external_execution(self):
        self.assertEqual(skill_import.classify("deployment-patterns", "Ship services."),
                         ("external_execution", "locked"))

    def test_description_prose_does_not_hijack_clinical_domain(self):
        """وصف هندسي يذكر diagnostics/health يجب ألا يلوّث النطاق السريري."""
        domain, _ = skill_import.classify(
            "agent-introspection-debugging",
            "Diagnose agent health and run diagnostics on failing loops.")
        self.assertNotEqual(domain, "clinical")
        self.assertEqual(domain, "projects")

    def test_ambiguous_budget_is_not_money(self):
        """«context-budget» ميزانية سياق لا ميزانية مال — لا تُصنَّف finance."""
        domain, _ = skill_import.classify("context-budget", "Manage context window budget.")
        self.assertEqual(domain, "projects")

    def test_strong_description_phrase_still_locks(self):
        domain, tier = skill_import.classify("record-sync", "Sync patient data between systems.")
        self.assertEqual((domain, tier), ("clinical", "locked"))

    def test_no_external_skill_ever_lands_in_low_tier(self):
        for slug in ("formatting-helper", "summarization-tricks", "report-layout-kit",
                     "personal-organization", "accessibility", "slides-deck"):
            _, tier = skill_import.classify(slug, "Format and summarize reports nicely.")
            self.assertIn(tier, {"review", "locked"}, slug)

    # ------------------------------------------------------------ guards

    def test_secret_scanner_flags_inline_key(self):
        self.assertIn("openai-style-key", skill_import.scan_secrets(SKILL_SECRET))

    def test_clean_skill_has_no_secret_findings(self):
        self.assertEqual(skill_import.scan_secrets(SKILL_OK), [])

    def test_skill_with_secret_is_blocked_and_not_written(self):
        write_skill(self.src, "leaky", SKILL_SECRET)
        result = skill_import.import_skills(self.src)
        self.assertEqual(result["created"], [])
        self.assertEqual(result["skipped"][0]["action"], "blocked")
        self.assertEqual(skill_registry.list_skills(), [])

    def test_skill_without_description_is_blocked(self):
        write_skill(self.src, "nameless", SKILL_NO_DESC)
        result = skill_import.import_skills(self.src)
        self.assertEqual(result["created"], [])
        self.assertIn("بلا وصف", result["skipped"][0]["reason"])

    def test_oversized_skill_is_blocked_for_context_budget(self):
        write_skill(self.src, "huge",
                    "---\nname: huge\ndescription: Very long guide.\n---\n" + ("x" * 30000))
        result = skill_import.import_skills(self.src)
        self.assertEqual(result["created"], [])
        self.assertIn("ميزانية السياق", result["skipped"][0]["reason"])

    # ------------------------------------------------------------ import behaviour

    def test_import_creates_candidate_with_provenance(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        created = skill_import.import_skills(self.src)["created"]
        self.assertEqual(len(created), 1)
        rec = skill_registry.list_skills()[0]
        self.assertEqual(rec["status"], "CANDIDATE")
        self.assertEqual(rec["source"]["system"], "ecc")
        self.assertEqual(rec["source"]["slug"], "context-budget")
        self.assertEqual(len(rec["source"]["sha256"]), 64)
        self.assertTrue(rec["evidence_ids"][0].startswith("ECC:context-budget@"))

    def test_imported_body_reaches_disk(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        skill_import.import_skills(self.src)
        rec = skill_registry.list_skills()[0]
        with open(os.path.join(self.tmp.name, rec["file"]), encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("Keep the working set small", body)

    def test_plan_writes_nothing(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        report = skill_import.plan(self.src)
        self.assertEqual(len(report["new"]), 1)
        self.assertEqual(skill_registry.list_skills(), [])

    def test_reimport_is_idempotent(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        skill_import.import_skills(self.src)
        again = skill_import.import_skills(self.src)
        self.assertEqual(again["created"], [])
        self.assertEqual(again["skipped"][0]["action"], "unchanged")
        self.assertEqual(len(skill_registry.list_skills()), 1)

    def test_changed_upstream_creates_new_version(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        skill_import.import_skills(self.src)
        write_skill(self.src, "context-budget", SKILL_OK + "\nNew upstream paragraph.\n")
        result = skill_import.import_skills(self.src)
        self.assertEqual(result["created"][0]["action"], "update")
        versions = sorted(x["version"] for x in skill_registry.list_skills())
        self.assertEqual(versions, [1, 2])

    def test_drift_reports_changed_upstream(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        skill_import.import_skills(self.src)
        self.assertEqual(skill_import.drift(self.src), [])
        write_skill(self.src, "context-budget", SKILL_OK + "\nchanged\n")
        self.assertEqual(skill_import.drift(self.src)[0]["slug"], "context-budget")

    def test_filter_and_limit_narrow_selection(self):
        for slug in ("alpha-eval", "beta-eval", "gamma-loop"):
            write_skill(self.src, slug, SKILL_OK.replace("context-budget", slug))
        self.assertEqual(len(skill_import.select(skill_import.discover(self.src), text_filter="eval")), 2)
        self.assertEqual(len(skill_import.select(skill_import.discover(self.src), limit=1)), 1)
        self.assertEqual(len(skill_import.select(skill_import.discover(self.src), slugs=["gamma-loop"])), 1)

    def test_missing_source_directory_is_not_an_error(self):
        self.assertEqual(skill_import.discover(os.path.join(self.tmp.name, "absent")), [])

    # ------------------------------------------------------------ governance

    def test_imported_skill_is_not_loaded_into_context(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        skill_import.import_skills(self.src)
        self.assertEqual(skill_runtime.context_for("projects")["skill_ids"], [])

    def test_imported_skill_cannot_activate_without_approval(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        sid = skill_import.import_skills(self.src)["created"][0]["id"]
        with self.assertRaises(PermissionError):
            skill_registry.set_status(sid, "ACTIVE")

    def test_approved_then_active_is_loadable(self):
        """المسار الشرعي يبقى مفتوحًا: اعتماد بشري ثم تفعيل ثم تحميل."""
        write_skill(self.src, "context-budget", SKILL_OK)
        sid = skill_import.import_skills(self.src)["created"][0]["id"]
        skill_registry.set_status(sid, "APPROVED")
        skill_registry.set_status(sid, "ACTIVE")
        self.assertEqual(skill_runtime.context_for("projects")["skill_ids"], [sid])

    def test_annotate_cannot_touch_protected_fields(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        sid = skill_import.import_skills(self.src)["created"][0]["id"]
        for field in ("status", "risk_tier", "domain", "version", "file"):
            with self.assertRaises(PermissionError, msg=field):
                skill_registry.annotate(sid, **{field: "x"})

    def test_annotate_records_metadata(self):
        write_skill(self.src, "context-budget", SKILL_OK)
        sid = skill_import.import_skills(self.src)["created"][0]["id"]
        rec = skill_registry.annotate(sid, note="مراجَعة يدويًا")
        self.assertEqual(rec["note"], "مراجَعة يدويًا")
        self.assertEqual(rec["status"], "CANDIDATE")


if __name__ == "__main__":
    unittest.main()
