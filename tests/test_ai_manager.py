import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import ai_manager, unified_inbox
from engine.store import Store


class AIManagerTests(unittest.TestCase):
    def test_contradiction_is_escalated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")

            def factory():
                return Store(state_path)

            metadata = {
                "origin": "external_ai",
                "ai_source": "gemini",
                "event_id": "gemini-42",
                "update_type": "CONTRADICTION",
                "project": "personal-ai-agent",
                "urgency": "NORMAL",
                "evidence": ["gateway result differs from another adviser"],
                "proposed_action": "Verify before merge",
                "requires_confirmation": False,
            }
            with patch.object(unified_inbox, "Store", factory), \
                 patch.object(unified_inbox, "log_event", lambda *a, **k: None):
                iid = unified_inbox.add(
                    "AI:gemini",
                    "PR readiness conflicts with another AI assessment",
                    kind="AI_UPDATE",
                    source_ref="gemini-42",
                    external_id="gemini-42",
                    metadata=metadata,
                )
                unified_inbox.classify(iid, "CONTRADICTION", "Verify before merge")

            with patch.object(ai_manager, "Store", factory), \
                 patch.object(ai_manager, "log_event", lambda *a, **k: None):
                first = ai_manager.review_external_updates()
                second = ai_manager.review_external_updates()

            self.assertEqual(first["reviewed"], 1)
            self.assertEqual(first["escalated"], 1)
            self.assertEqual(first["contradictions"], 1)
            self.assertEqual(second["reviewed"], 0)

            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            item = next(x for x in data["unified_inbox"] if x["id"] == iid)
            self.assertEqual(item["status"], "ESCALATED")
            self.assertEqual(len(data["contradictions"]), 1)
            ai_drs = [d for d in data["decision_requests"] if str(d.get("id", "")).startswith("DR-AI-")]
            self.assertEqual(len(ai_drs), 1)
            self.assertEqual(ai_drs[0]["source_item"], iid)


if __name__ == "__main__":
    unittest.main()
