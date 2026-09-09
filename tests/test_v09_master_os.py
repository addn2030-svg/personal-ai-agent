# -*- coding: utf-8 -*-
"""Offline smoke tests for v0.9 Master OS — canonical tree, sub-agent matrix,
demo seeding (merge-if-missing), drive folder checklist."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store
import master_os
import drive_tree


class MasterOSTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Store(path=str(Path(tmp.name) / "state.json"))

    def test_canonical_tree_has_five_domains(self):
        self.assertEqual(len(master_os.MASTER_TREE), 5)
        names = [f["name"] for f in master_os.MASTER_TREE]
        self.assertIn("01_Executive_Briefings", names)
        self.assertIn("05_Personal_Finance_Life", names)
        # مجلدان معرفيان داخل Knowledge Hub
        kinds = [k for f in master_os.MASTER_TREE for (k, _n, _p) in f["children"]]
        self.assertEqual(kinds.count("folder"), 2)

    def test_sub_agents_matrix_four_agents_with_schedule_refs(self):
        self.assertEqual(len(master_os.SUB_AGENTS), 4)
        ids = {a["agent_id"] for a in master_os.SUB_AGENTS}
        self.assertEqual(ids, {"AG-MORNING", "AG-CLINICAL", "AG-KNOWLEDGE", "AG-FINANCE"})
        for a in master_os.SUB_AGENTS:
            self.assertTrue(a["cadence_jobs"])

    def test_demo_seed_merge_if_missing(self):
        store = self.make_store()
        # بيانات تشغيل حقيقية موجودة مسبقًا يجب ألا تُلمس
        S = store.rows_all()
        S["tasks"].append({"العنوان": "مهمة حقيقية", "الحالة": "جارية"})
        store.commit(S, "seed")

        first = master_os.seed_demo(store=store)
        self.assertTrue(any(first.values()))
        S = store.reload().rows_all()
        self.assertEqual(len([t for t in S["tasks"] if t["العنوان"] == "مهمة حقيقية"]), 1)
        self.assertEqual(len(S["sub_agents"]), 4)
        self.assertEqual(len(S["content_sources"]), 9)
        self.assertEqual(len(S["drive_tree"]), 1)
        self.assertGreaterEqual(len(S["mind_maps"]), 1)

        # التشغيل الثاني لا يكرر شيئًا (idempotent)
        second = master_os.seed_demo(store=store)
        self.assertFalse(any(second.values()))
        self.assertEqual(len(store.reload().rows_all()["sub_agents"]), 4)

        # القسم التجريبي يُستبدل فقط مع --force
        added = master_os.seed_demo(store=store, force=True)
        self.assertTrue(any(added.values()))
        self.assertEqual(len(store.reload().rows_all()["sub_agents"]), 4)

    def test_drive_checklist_and_tree_spec(self):
        paths = drive_tree.folder_paths()
        self.assertEqual(paths[0][0], "Abdulrahman_Master_OS")
        # 5 مجلدات نطاقات + مجلدان معرفيان + الجذر
        self.assertEqual(len(paths), 8)
        digest1 = drive_tree._tree_digest()
        digest2 = drive_tree._tree_digest()
        self.assertEqual(digest1, digest2)
        tree_text = drive_tree._tree_text()
        self.assertIn("MindMaps_Library", tree_text)
        self.assertIn("DHS_Training_Tracker", tree_text)

    def test_status_output_mentions_architecture(self):
        store = self.make_store()
        master_os.seed_demo(store=store)
        lines = master_os.status(store=store)
        joined = "\n".join(lines)
        self.assertIn("Abdulrahman_Master_OS", joined)
        self.assertIn("الوكلاء الفرعيون", joined)


if __name__ == "__main__":
    unittest.main()
