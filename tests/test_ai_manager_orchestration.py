import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connectors import ai_gateway
from engine import ai_manager, unified_inbox
from engine.store import Store


class AIManagerOrchestrationTests(unittest.TestCase):
    def test_sensitive_external_update_redacts_all_free_text_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")

            def factory():
                return Store(state_path)

            payload = {
                "event_id": "claude-sensitive-1",
                "type": "RISK",
                "summary": "private patient detail",
                "project": "private clinical project",
                "urgency": "CRITICAL",
                "evidence": ["private evidence"],
                "proposed_action": "private action",
                "sensitive": True,
            }
            with patch.object(ai_gateway, "Store", factory), \
                 patch.object(unified_inbox, "Store", factory), \
                 patch.object(ai_gateway, "log_event", lambda *a, **k: None), \
                 patch.object(unified_inbox, "log_event", lambda *a, **k: None), \
                 patch.object(ai_gateway, "_wake_manager_async", lambda reason: None):
                result = ai_gateway.ingest("claude", payload)

            self.assertFalse(result["duplicate"])
            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            item = data["unified_inbox"][0]
            self.assertEqual(item["content"], ai_gateway.PRIVATE_PLACEHOLDER)
            self.assertTrue(item["sensitive"])
            self.assertEqual(item["metadata"]["project"], "")
            self.assertEqual(item["metadata"]["evidence"], [])
            self.assertEqual(item["metadata"]["proposed_action"], ai_gateway.PRIVATE_PLACEHOLDER)
            self.assertEqual(item["next_action"], ai_gateway.PRIVATE_PLACEHOLDER)

    def test_auto_council_candidates_are_narrow_and_never_sensitive(self):
        state = {
            "unified_inbox": [
                {
                    "id": "IN-HIGH",
                    "status": "CLASSIFIED",
                    "classification": "RISK",
                    "content": "high but not critical",
                    "sensitive": False,
                    "metadata": {
                        "origin": "external_ai",
                        "ai_source": "claude",
                        "urgency": "HIGH",
                        "project": "p",
                        "evidence": [],
                        "proposed_action": "check",
                    },
                },
                {
                    "id": "IN-CRIT",
                    "status": "CLASSIFIED",
                    "classification": "RISK",
                    "content": "critical issue",
                    "sensitive": False,
                    "metadata": {
                        "origin": "external_ai",
                        "ai_source": "gemini",
                        "urgency": "CRITICAL",
                        "project": "p",
                        "evidence": ["e"],
                        "proposed_action": "verify",
                    },
                },
                {
                    "id": "IN-PRIVATE",
                    "status": "CLASSIFIED",
                    "classification": "CONTRADICTION",
                    "content": "[REDACTED_FROM_PERSONAL_OS]",
                    "sensitive": True,
                    "metadata": {
                        "origin": "external_ai",
                        "ai_source": "chatgpt",
                        "urgency": "CRITICAL",
                        "project": "",
                        "evidence": [],
                        "proposed_action": "[REDACTED_FROM_PERSONAL_OS]",
                    },
                },
            ],
            "decision_requests": [],
            "contradictions": [],
        }

        changed, result = ai_manager._review_mutation(state)
        self.assertTrue(changed)
        candidates = result["council_candidates"]
        self.assertEqual([x["source_item"] for x in candidates], ["IN-CRIT"])


if __name__ == "__main__":
    unittest.main()
