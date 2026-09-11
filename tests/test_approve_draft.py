# -*- coding: utf-8 -*-
"""مسودة بوابة الاعتماد (approve.py draft): أي نص ← PENDING_APPROVAL بالبصمة، لا إرسال."""
import datetime as dt
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "engine"))

from store import Store  # noqa: E402
import approve  # noqa: E402


class ApproveDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))

    def body(self):
        return "السلام عليكم،\n\nأحتاج تأكيدًا على أربع نقاط بخصوص المجدول."

    def test_draft_is_enqueued_as_pending_approval_with_hash(self):
        body = self.body()
        state, row = approve._enqueue_draft(self.store, body, "note_for_developer",
                                            "telegram/email", 2, "manual:approve.py")
        self.assertEqual(state, "created")
        self.assertEqual(row["status"], "PENDING_APPROVAL")
        self.assertEqual(row["type"], "note_for_developer")
        self.assertEqual(row["channel"], "telegram/email")
        self.assertEqual(row["content"], body)
        self.assertEqual(row["content_hash"],
                         hashlib.sha256(body.encode("utf-8")).hexdigest()[:16])
        self.assertEqual(row["origin"], "manual:approve.py")
        self.assertEqual(dt.date.fromisoformat(row["expires_at"]) -
                         dt.date.fromisoformat(row["created_at"]), dt.timedelta(days=2))
        # لا أثر خارجي: المسودة وحدها في الطابور، ولا تنفيذ ولا إرسال
        q = self.store.rows_all()["action_queue"]
        self.assertEqual(len(q), 1)
        self.assertIsNone(q[0]["executed_at"])

    def test_same_text_is_not_enqueued_twice(self):
        body = self.body()
        approve._enqueue_draft(self.store, body, "note", "email", 2, "x")
        before = self.store.rows_all()["meta"]["version"]
        state, row = approve._enqueue_draft(self.store, body, "note", "email", 2, "x")
        self.assertEqual(state, "exists")
        self.assertEqual(row["action_id"], "A-001")
        self.assertEqual(len(self.store.rows_all()["action_queue"]), 1)
        # write-on-change: لا نسخة جديدة من الحالة عند التطابق
        self.assertEqual(self.store.rows_all()["meta"]["version"], before)

    def test_edited_text_gets_its_own_draft_and_its_own_hash(self):
        body = self.body()
        approve._enqueue_draft(self.store, body, "note", "email", 2, "x")
        state, row = approve._enqueue_draft(self.store, body + "\n\n.وأضيف سطرًا", "note",
                                           "email", 2, "x")
        self.assertEqual(state, "created")
        self.assertNotEqual(row["content_hash"],
                            self.store.rows_all()["action_queue"][0]["content_hash"])

    def test_expiry_floor_keeps_a_draft_from_being_born_expired(self):
        _, row = approve._enqueue_draft(self.store, self.body(), "note", "email", 0, "x")
        self.assertGreaterEqual(dt.date.fromisoformat(row["expires_at"]),
                                dt.date.fromisoformat(row["created_at"]))


class ApproveDraftCliTests(unittest.TestCase):
    """المسار الذي يراه المستخدم فعليًا: أمر الطرفية + idempotency + حالة فارغة."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self.note = Path(self.tmp.name) / "note.md"
        self.note.write_text("نص المسودة للمطور\n", encoding="utf-8")

    def run_cli(self, *args):
        import subprocess
        env = dict(os.environ, AI_OS_DATA_DIR=str(self.data), PYTHONPATH=BASE)
        return subprocess.run([sys.executable, os.path.join(BASE, "engine", "approve.py")]
                              + list(args), capture_output=True, text=True, env=env, cwd=BASE)

    def test_cli_enqueues_then_reports_the_existing_draft(self):
        first = self.run_cli("draft", str(self.note), "--type", "note_for_developer",
                             "--channel", "telegram/email")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("A-001", first.stdout)
        self.assertIn("لا إرسال تلقائي", first.stdout)
        second = self.run_cli("draft", str(self.note))
        self.assertIn("موجودة", second.stdout)
        self.assertIn("A-001", second.stdout)
        listing = self.run_cli("list")
        self.assertIn("note_for_developer", listing.stdout)
        self.assertIn("بانتظار الاعتماد", listing.stdout)

    def test_cli_rejects_empty_input(self):
        empty = Path(self.tmp.name) / "empty.md"
        empty.write_text("   \n", encoding="utf-8")
        bad = self.run_cli("draft", str(empty))
        self.assertEqual(bad.returncode, 1)
        self.assertIn("فارغة", bad.stdout + bad.stderr)
        missing = self.run_cli("draft")
        self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
