# -*- coding: utf-8 -*-
"""Offline tests for v0.9 audio digest pipeline (no network, no keys)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store
import audio_digest
import mindmap

NOTES = """# ملخص محاضرة

## نقاط أساسية
- مفهوم Mulligan: حركة مع الحركة بدون ألم
- إعادة التقييم بعد كل مجموعة
- دمج NKT مع الإبر الجافة حسب الاستجابة

## خطة التطبيق
- تجربة البروتوكول على 3 حالات هذا الأسبوع
"""


class AudioDigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        audio_digest.DIGEST_DIR = os.path.join(self.tmp.name, "audio")
        audio_digest.REPORTS = self.tmp.name
        mindmap.MAP_DIR = os.path.join(self.tmp.name, "mindmaps")
        os.makedirs(audio_digest.DIGEST_DIR, exist_ok=True)
        os.makedirs(mindmap.MAP_DIR, exist_ok=True)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))

    def test_queue_and_dedupe(self):
        d1 = audio_digest.queue("مفهوم Mulligan NKT", "lecture",
                                source_url="https://youtu.be/abc", store=self.store)
        self.assertEqual(d1["status"], "QUEUED")
        d2 = audio_digest.queue("مفهوم Mulligan NKT", "lecture",
                                source_url="https://youtu.be/abc", store=self.store)
        self.assertEqual(d1["digest_id"], d2["digest_id"])
        rows = self.store.reload().rows_all()["audio_digests"]
        self.assertEqual(len(rows), 1)

    def test_process_builds_map_script_and_md(self):
        audio_digest.queue("مفهوم Mulligan NKT", "lecture", notes_file="",
                           store=self.store)
        S = self.store.rows_all()
        S["audio_digests"][0]["note"] = NOTES
        self.store.commit(S, "attach_notes")

        done = audio_digest.process(all_items=True, store=self.store)
        self.assertEqual(len(done), 1)
        d = done[0]
        self.assertEqual(d["status"], "DIGESTED")
        self.assertTrue(d["map_id"].startswith("MM-"))
        self.assertGreaterEqual(len(d["key_points"]), 3)
        self.assertTrue(d["narrator_script"])
        report = os.path.join(audio_digest.DIGEST_DIR, f"{d['digest_id'].lower()}-report.md")
        self.assertTrue(os.path.exists(report))

        # إعادة المعالجة لا تعيد معالجة العناصر المُنجزة
        again = audio_digest.process(all_items=True, store=self.store)
        self.assertEqual(again, [])

    def test_render_audio_without_key_does_not_call_network(self):
        audio_digest.queue("عنوان تجريبي", "book", store=self.store)
        audio_digest.process(all_items=True, store=self.store)
        os.environ.pop("ELEVENLABS_API_KEY", None)
        out = audio_digest.render_audio("AD-001", store=self.store)
        self.assertIsNone(out)
        d = next(x for x in self.store.reload().rows_all()["audio_digests"]
                 if x["digest_id"] == "AD-001")
        self.assertEqual(d["status"], "DIGESTED")  # لم تتغير الحالة بلا مفتاح
        script = os.path.join(audio_digest.DIGEST_DIR, "ad-001-script.md")
        self.assertTrue(os.path.exists(script))


if __name__ == "__main__":
    unittest.main()
