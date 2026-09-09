# -*- coding: utf-8 -*-
"""Offline tests for v0.9 mind-map generator (Mermaid mindmap + text tree)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store
import mindmap

SAMPLE_MD = """# دورة العلاج اليدوي

## مبادئ موليجان
- Mobilisation with Movement
- لا ألم أثناء الحركة
- إعادة التقييم الفوري

## بروتوكول NKT
### مراحل التقييم
- اختبار قوة العضلات
- مقارنة ثنائية

## الأدوات المساعدة
- أشرطة لاصقة
- حزام موليجان
"""


class MindMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        mindmap.MAP_DIR = self.tmp.name  # كتابة الملفات داخل temp لا reports/
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))

    def test_parse_markdown_headings(self):
        title, sections = mindmap.parse_markdown(SAMPLE_MD, "افتراضي")
        self.assertEqual(title, "دورة العلاج اليدوي")
        self.assertEqual(len(sections), 3)
        self.assertIn("Mobilisation with Movement", sections[0]["leaves"])
        # فرع فرعي (###) داخل NKT
        self.assertEqual(len(sections[1]["sub_branches"]), 1)
        self.assertEqual(sections[1]["sub_branches"][0]["name"], "مراحل التقييم")

    def test_mermaid_and_tree_output(self):
        title, sections = mindmap.parse_markdown(SAMPLE_MD, "افتراضي")
        mm = mindmap.mermaid_of(title, sections)
        self.assertTrue(mm.startswith("mindmap"))
        self.assertIn("root((دورة العلاج اليدوي))", mm)
        tree = mindmap.tree_of(title, sections)
        self.assertIn("مبادئ موليجان", tree)

    def test_register_is_idempotent_by_content(self):
        title, sections = mindmap.parse_markdown(SAMPLE_MD, "افتراضي")
        row1, created1 = mindmap.register(title, sections, topic="clinical",
                                          source_kind="lecture",
                                          source_ref="demo", store=self.store)
        self.assertTrue(created1)
        row2, created2 = mindmap.register(title, sections, topic="clinical",
                                          source_kind="lecture",
                                          source_ref="demo", store=self.store)
        self.assertFalse(created2)
        self.assertEqual(row1["map_id"], row2["map_id"])
        # الملفات وُجدت في temp
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, row1["file_mmd"])))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, row1["file_md"])))

    def test_weekly_map_is_idempotent_per_week(self):
        _, sections = mindmap.parse_markdown(SAMPLE_MD, "افتراضي")
        row1, created1 = mindmap.register("عنوان أ", sections, topic="weekly",
                                          source_kind="book", source_ref="r1",
                                          store=self.store, weekly=True,
                                          week_key="2026-09-13_W38")
        self.assertTrue(created1)
        # نفس الأسبوع بمحتوى مختلف لا ينشئ خريطة جديدة
        row2, created2 = mindmap.register("عنوان ب", sections, topic="weekly",
                                          source_kind="book", source_ref="r2",
                                          store=self.store, weekly=True,
                                          week_key="2026-09-13_W38")
        self.assertFalse(created2)
        self.assertEqual(row1["map_id"], row2["map_id"])
        # أسبوع جديد = خريطة جديدة
        row3, created3 = mindmap.register("عنوان ب", sections, topic="weekly",
                                          source_kind="book", source_ref="r2",
                                          store=self.store, weekly=True,
                                          week_key="2026-09-20_W39")
        self.assertTrue(created3)
        self.assertNotEqual(row1["map_id"], row3["map_id"])

    def test_sun_of_week_start(self):
        # الجمعة 2026-09-18 → أحد الأسبوع 2026-09-13
        self.assertEqual(mindmap.sun_of(__import__("datetime").date(2026, 9, 18)),
                         __import__("datetime").date(2026, 9, 13))


if __name__ == "__main__":
    unittest.main()
