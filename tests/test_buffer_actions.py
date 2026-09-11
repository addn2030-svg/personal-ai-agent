# -*- coding: utf-8 -*-
"""Tests for Buffer post actions behind the human approval gate (C2).

Covers: /buffer_post payload parsing, queue records (PENDING_APPROVAL +
content hash + 48h expiry), idempotency, channel resolution, execution on
approval with receipts, failure reverting to PENDING_APPROVAL (retryable),
the legacy bot commands, and the production approve-callback wiring.
No network calls: buffer_publisher is mocked everywhere.
"""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from connectors import buffer_actions
from connectors import buffer_publisher
from connectors import telegram_bot_legacy as legacy
from engine.store import Store

import connectors.telegram_bot  # noqa: F401  (يجهّط handle_callback على legacy)

CHAT_ID = 7001


class ParseTests(unittest.TestCase):
    def test_full_payload(self):
        p = buffer_actions.parse_request(
            "instagram | نص المنشور | https://raw.githubusercontent.com/x/cover.jpg | 2026-09-12 18:00 | مسودة"
        )
        self.assertEqual(p["channel"], "instagram")
        self.assertEqual(p["text"], "نص المنشور")
        self.assertEqual(p["image_url"], "https://raw.githubusercontent.com/x/cover.jpg")
        self.assertEqual(p["due_at"], "2026-09-12 18:00")
        self.assertTrue(p["draft"])

    def test_extras_in_any_order(self):
        p = buffer_actions.parse_request("linkedin | نص | draft | 2026-10-01T09:30 | http://img.example/a.png")
        self.assertEqual(p["due_at"], "2026-10-01T09:30")
        self.assertEqual(p["image_url"], "http://img.example/a.png")
        self.assertTrue(p["draft"])

    def test_minimal_payload(self):
        p = buffer_actions.parse_request("twitter | مرحبا بالعالم")
        self.assertEqual(p["channel"], "twitter")
        self.assertEqual(p["text"], "مرحبا بالعالم")
        self.assertIsNone(p["image_url"])
        self.assertIsNone(p["due_at"])
        self.assertFalse(p["draft"])

    def test_missing_text_or_channel_raises(self):
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("instagram")
        with self.assertRaises(ValueError):
            buffer_actions.parse_request(" | نص بلا قناة")
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("")

    def test_unknown_extra_raises(self):
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("instagram | نص | حقل غريب")

    def test_invalid_date_raises(self):
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("instagram | نص | 2026-13-45 10:00")

    def test_second_image_raises(self):
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("instagram | نص | http://a/1.jpg | http://a/2.jpg")

    def test_oversized_text_raises(self):
        with self.assertRaises(ValueError):
            buffer_actions.parse_request("instagram | " + "أ" * 5001)


class QueueTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        audit = mock.patch("engine.store.AUDIT_PATH", str(Path(self.tmp.name) / "audit.jsonl"))
        audit.start()
        self.addCleanup(audit.stop)

    def payload(self, **kw):
        base = {"channel": "instagram", "text": "نص المنشور", "image_url": None, "due_at": None, "draft": False}
        base.update(kw)
        return base


class CreateActionTests(QueueTestBase):
    def test_record_shape_and_gate(self):
        record = buffer_actions.create_action(self.payload(), chat_id=CHAT_ID, store=self.store)
        self.assertEqual(record["type"], "BUFFER_POST")
        self.assertEqual(record["status"], "PENDING_APPROVAL")
        self.assertTrue(record["action_id"].startswith("BP-"))
        self.assertEqual(len(record["content_hash"]), 64)
        self.assertEqual(record["payload"]["text"], "نص المنشور")
        self.assertIn("instagram", record["content"])
        rows = self.store.rows_all()
        self.assertEqual(rows["action_queue"][0]["action_id"], record["action_id"])

    def test_idempotent_for_same_payload(self):
        first = buffer_actions.create_action(self.payload(), store=self.store)
        second = buffer_actions.create_action(self.payload(), store=self.store)
        self.assertEqual(first["action_id"], second["action_id"])
        self.assertEqual(len(self.store.rows_all()["action_queue"]), 1)

    def test_different_text_creates_new_record(self):
        buffer_actions.create_action(self.payload(), store=self.store)
        other = buffer_actions.create_action(self.payload(text="نص آخر"), store=self.store)
        queue = self.store.rows_all()["action_queue"]
        self.assertEqual(len(queue), 2)
        self.assertNotEqual(queue[0]["content_hash"], queue[1]["content_hash"])
        self.assertEqual(other["payload"]["text"], "نص آخر")

    def test_expired_or_rejected_allows_recreate(self):
        first = buffer_actions.create_action(self.payload(), store=self.store)

        def reject(state):
            row = next(a for a in state["action_queue"] if a["action_id"] == first["action_id"])
            row["status"] = "REJECTED"
            return True, row

        self.store.transaction(reject, "test_reject")
        again = buffer_actions.create_action(self.payload(), store=self.store)
        self.assertNotEqual(first["action_id"], again["action_id"])
        self.assertEqual(len(self.store.rows_all()["action_queue"]), 2)

    def test_preview_keyboard_binds_content_hash(self):
        record = buffer_actions.create_action(self.payload(), store=self.store)
        kb = buffer_actions.preview_keyboard(record)
        button = kb["inline_keyboard"][0][0]
        self.assertEqual(button["callback_data"],
                         f"ap:{record['action_id']}:{record['content_hash'][:8]}")
        text = buffer_actions.preview_text(record)
        self.assertIn("لم يُنشر بعد", text)
        self.assertIn(record["action_id"], text)


class ResolveChannelTests(unittest.TestCase):
    CHANNELS = [
        {"id": "ch-1", "service": "instagram", "displayName": "الحساب الرئيسي"},
        {"id": "ch-2", "service": "linkedin", "displayName": "لينكدإن", "isQueuePaused": True},
    ]

    def test_by_explicit_id(self):
        with mock.patch.object(buffer_publisher, "get_channels", return_value=self.CHANNELS):
            cid, label = buffer_actions.resolve_channel("ch-1")
        self.assertEqual(cid, "ch-1")
        self.assertIn("instagram", label)

    def test_by_service_name_prefers_active(self):
        with mock.patch.object(buffer_publisher, "get_channels", return_value=self.CHANNELS):
            cid, _ = buffer_actions.resolve_channel("LinkedIn")
        self.assertEqual(cid, "ch-2")

    def test_unknown_service_lists_available(self):
        with mock.patch.object(buffer_publisher, "get_channels", return_value=self.CHANNELS):
            with self.assertRaises(RuntimeError) as ctx:
                buffer_actions.resolve_channel("tiktok")
        self.assertIn("instagram", str(ctx.exception))

    def test_systemexit_wrapped(self):
        with mock.patch.object(buffer_publisher, "get_channels", side_effect=SystemExit("HTTP 401")):
            with self.assertRaises(RuntimeError) as ctx:
                buffer_actions.resolve_channel("instagram")
        self.assertIn("401", str(ctx.exception))


class MaybeExecuteTests(QueueTestBase):
    def _approved(self):
        record = buffer_actions.create_action(self.payload(), store=self.store)

        def approve(state):
            row = next(a for a in state["action_queue"] if a["action_id"] == record["action_id"])
            row["status"] = "APPROVED"
            row["approved_at"] = "2026-09-11"
            return True, row

        self.store.transaction(approve, "test_approve")
        return record

    def test_success_executes_and_closes(self):
        record = self._approved()
        post = {"id": "post-9", "status": "scheduled"}
        with mock.patch.object(buffer_publisher, "get_channels", return_value=[
                {"id": "ch-1", "service": "instagram", "displayName": "رئيسي"}]), \
             mock.patch.object(buffer_publisher, "create_post", return_value=post) as cp:
            outcome = buffer_actions.maybe_execute(record["action_id"], store=self.store)
            cp.assert_called_once()
            self.assertEqual(cp.call_args.kwargs["channel_id"], "ch-1")
            self.assertEqual(cp.call_args.kwargs["text"], "نص المنشور")
        self.assertTrue(outcome["ok"])
        row = next(a for a in self.store.rows_all()["action_queue"]
                   if a["action_id"] == record["action_id"])
        self.assertEqual(row["status"], "EXECUTED")
        self.assertEqual(row["post_id"], "post-9")
        self.assertIn("نُشر عبر Buffer", buffer_actions.receipt_text(outcome))

    def test_scheduled_post_passes_string_due_at(self):
        record = buffer_actions.create_action(
            self.payload(due_at="2026-09-12 18:00"), store=self.store)

        def approve(state):
            row = next(a for a in state["action_queue"] if a["action_id"] == record["action_id"])
            row["status"] = "APPROVED"
            return True, row

        self.store.transaction(approve, "test_approve")
        with mock.patch.object(buffer_publisher, "get_channels", return_value=[
                {"id": "ch-1", "service": "instagram"}]), \
             mock.patch.object(buffer_publisher, "create_post",
                               return_value={"id": "p2", "status": "scheduled"}) as cp:
            outcome = buffer_actions.maybe_execute(record["action_id"], store=self.store)
        self.assertTrue(outcome["ok"])
        self.assertEqual(cp.call_args.kwargs["due_at"], "2026-09-12 18:00")
        self.assertEqual(cp.call_args.kwargs["tz_offset"], "+03:00")

    def test_failure_reverts_to_pending_with_error(self):
        record = self._approved()
        with mock.patch.object(buffer_publisher, "get_channels", side_effect=SystemExit("تعذر الوصول")):
            outcome = buffer_actions.maybe_execute(record["action_id"], store=self.store)
        self.assertFalse(outcome["ok"])
        self.assertIn("تعذر الوصول", outcome["error"])
        row = next(a for a in self.store.rows_all()["action_queue"]
                   if a["action_id"] == record["action_id"])
        self.assertEqual(row["status"], "PENDING_APPROVAL")
        self.assertIn("تعذر الوصول", row["last_error"])
        self.assertIn("أُعيد الإجراء", buffer_actions.receipt_text(outcome))

    def test_ignores_other_types_and_statuses(self):
        def add_other(state):
            state["action_queue"].append({"action_id": "A-001", "type": "send_followup_message",
                                          "status": "APPROVED", "content_hash": "x"})
            return True, None
        self.store.transaction(add_other, "test_other")
        self.assertIsNone(buffer_actions.maybe_execute("A-001", store=self.store))

        pending = buffer_actions.create_action(self.payload(), store=self.store)
        self.assertIsNone(buffer_actions.maybe_execute(pending["action_id"], store=self.store))


class LegacyCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(path=str(Path(self.tmp.name) / "state.json"))
        patches = [
            mock.patch.object(legacy, "send", side_effect=lambda cid, msg, reply_markup=None:
                              self.sent.append((msg, reply_markup))),
            mock.patch.object(legacy, "_authorized", return_value=True),
            mock.patch.object(legacy, "_local_capture", return_value=None),
            mock.patch.object(legacy, "_save_intake"),
            mock.patch.object(legacy, "_message_payload",
                              side_effect=lambda m: (m.get("text", ""), "TEXT", None)),
            mock.patch.dict(os.environ, {"BUFFER_API_KEY": "test-key"}),
            mock.patch.object(buffer_actions, "Store", lambda: self.store),
        ]
        self.sent = []
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _handle(self, text):
        legacy.handle_message({"chat": {"id": CHAT_ID, "type": "private"}, "text": text})

    def test_buffer_post_preview_with_approve_button(self):
        self._handle("/buffer_post instagram | ملخص كتاب الأسبوع")
        self.assertEqual(len(self.sent), 1)
        text, kb = self.sent[0]
        self.assertIn("لم يُنشر بعد", text)
        self.assertIsNotNone(kb)
        record = self.store.rows_all()["action_queue"][0]
        self.assertEqual(record["status"], "PENDING_APPROVAL")
        self.assertEqual(kb["inline_keyboard"][0][0]["callback_data"],
                         f"ap:{record['action_id']}:{record['content_hash'][:8]}")

    def test_buffer_post_without_key_refuses(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BUFFER_API_KEY", None)
            self._handle("/buffer_post instagram | نص")
        self.assertIn("BUFFER_API_KEY غير مضبوط", self.sent[0][0])
        self.assertEqual(self.store.rows_all()["action_queue"], [])

    def test_buffer_post_bad_usage_shows_help(self):
        self._handle("/buffer_post نص بلا فاصل")
        self.assertIn("الصيغة:", self.sent[0][0])
        self.assertEqual(self.store.rows_all()["action_queue"], [])

    def test_buffer_channels_lists_ids(self):
        channels = [{"id": "ch-9", "service": "instagram", "displayName": "رئيسي"}]
        with mock.patch.object(buffer_publisher, "get_channels", return_value=channels):
            self._handle("/buffer_channels")
        self.assertIn("ch-9", self.sent[0][0])
        self.assertIn("instagram", self.sent[0][0])


class _FakeStore:
    """Same surface as Store() for the approve-callback path (rows_all/commit)."""

    def __init__(self, state):
        self.state = state

    def rows_all(self):
        return copy.deepcopy(self.state)

    def commit(self, new_data, mutator, **details):
        self.state = new_data
        return self.state


class ApproveCallbackTests(unittest.TestCase):
    """The production webhook path: ap: button → approve → execute Buffer post."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.record = buffer_actions.create_action(
            {"channel": "instagram", "text": "نص", "image_url": None, "due_at": None, "draft": False},
            chat_id=CHAT_ID,
            store=Store(path=str(Path(self.tmp.name) / "state.json")),
        )
        self.fake = _FakeStore({"action_queue": [copy.deepcopy(self.record)],
                                "manager_markers": {}})
        import store as top_store  # الوحدة التي يستوردها مسار الاستدعاء مباشرة
        patches = [
            mock.patch.object(top_store, "Store", lambda: self.fake),
            mock.patch.object(legacy, "_authorized", return_value=True),
            mock.patch.object(legacy, "send", side_effect=lambda cid, msg, reply_markup=None:
                              self.sent.append(msg)),
            mock.patch.object(legacy, "api",
                              side_effect=lambda method, payload=None, **kw:
                              self.api_calls.append((method, payload or kw))),
        ]
        self.sent = []
        self.api_calls = []
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _callback(self):
        legacy.handle_callback({
            "id": "cb-1",
            "message": {"chat": {"id": CHAT_ID, "type": "private"}},
            "data": f"ap:{self.record['action_id']}:{self.record['content_hash'][:8]}",
        })

    def test_approved_buffer_post_executes_and_sends_receipt(self):
        with mock.patch.object(buffer_actions, "maybe_execute",
                               return_value={"ok": True, "action_id": self.record["action_id"],
                                             "post": {"id": "p1", "status": "scheduled"}}) as me:
            self._callback()
            me.assert_called_once_with(self.record["action_id"])
        self.assertTrue(any("نُشر عبر Buffer" in m for m in self.sent))
        self.assertEqual(self.fake.state["action_queue"][0]["status"], "APPROVED")

    def test_other_action_types_keep_manual_execution(self):
        self.fake.state["action_queue"][0]["type"] = "send_followup_message"
        with mock.patch.object(buffer_actions, "maybe_execute", return_value=None):
            self._callback()
        self.assertTrue(any("approve.py executed" in m for m in self.sent))

    def test_hash_mismatch_rejects(self):
        legacy.handle_callback({
            "id": "cb-2",
            "message": {"chat": {"id": CHAT_ID, "type": "private"}},
            "data": f"ap:{self.record['action_id']}:deadbeef",
        })
        self.assertEqual(self.fake.state["action_queue"][0]["status"], "REJECTED")
        answers = [p for m, p in self.api_calls if m == "answerCallbackQuery"]
        self.assertTrue(any("بصمة غير مطابقة" in str(p) for p in answers))


if __name__ == "__main__":
    unittest.main()
