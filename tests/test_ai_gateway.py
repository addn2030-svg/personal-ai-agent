import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import ai_gateway
from engine import unified_inbox
from engine.store import Store


class AIGatewayTests(unittest.TestCase):
    def test_authentication_uses_source_specific_key(self):
        with patch.dict(os.environ, {"AI_GATEWAY_CLAUDE_KEY": "secret-claude"}, clear=False):
            self.assertEqual(
                ai_gateway.authenticate({
                    "X-AI-Source": "claude",
                    "Authorization": "Bearer secret-claude",
                }),
                "claude",
            )
            self.assertIsNone(ai_gateway.authenticate({
                "X-AI-Source": "gemini",
                "Authorization": "Bearer secret-claude",
            }))

    def test_update_is_attributed_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")

            def factory():
                return Store(state_path)

            payload = {
                "event_id": "claude-001",
                "type": "RISK",
                "summary": "Railway volume may be missing",
                "project": "personal-ai-agent",
                "confidence": 0.91,
                "urgency": "HIGH",
                "proposed_action": "Verify the persistent volume",
            }
            with patch.object(ai_gateway, "Store", factory), \
                 patch.object(unified_inbox, "Store", factory), \
                 patch.object(ai_gateway, "log_event", lambda *a, **k: None), \
                 patch.object(unified_inbox, "log_event", lambda *a, **k: None), \
                 patch.object(ai_gateway, "_wake_manager_async", lambda reason: None):
                first = ai_gateway.ingest("claude", payload)
                second = ai_gateway.ingest("claude", dict(payload, summary="retry text changed"))

            self.assertFalse(first["duplicate"])
            self.assertTrue(first["manager_wake"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["inbox_id"], second["inbox_id"])

            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(len(data["unified_inbox"]), 1)
            item = data["unified_inbox"][0]
            self.assertEqual(item["classification"], "RISK")
            self.assertEqual(item["metadata"]["ai_source"], "claude")
            self.assertEqual(item["external_id"], "claude-001")
            self.assertEqual(len(data["ai_sources"]), 1)
            self.assertEqual(data["ai_sources"][0]["events_received"], 1)

    def test_payload_validation_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            ai_gateway.validate_payload({
                "event_id": "x-1",
                "type": "DELETE_EVERYTHING",
                "summary": "bad",
            })


if __name__ == "__main__":
    unittest.main()
