import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import ai_council
from engine.store import Store


class AICouncilTests(unittest.TestCase):
    def _store_factory(self, path):
        return lambda: Store(path)

    def test_three_models_are_labelled_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")
            calls = []

            def fake_chat(*, model, messages, sensitive=False, max_tokens=0, temperature=0, response_format=None):
                calls.append((model, bool(response_format)))
                if response_format:
                    return json.dumps({
                        "consensus": ["Deploy only after staging"],
                        "disagreements": [],
                        "blind_spots": ["Live Railway state is not in supplied evidence"],
                        "recommendation": "Run staging gates first",
                        "confidence": 0.9,
                        "material_conflict": False,
                        "requires_owner_decision": False,
                        "next_checks": ["Check /ready"],
                    }), {"inputTokens": 10, "outputTokens": 20}, 50
                return f"Advice from {model}", {"inputTokens": 5, "outputTokens": 7}, 25

            with patch.object(ai_council.model_gateway, "configured", lambda: True), \
                 patch.object(ai_council.model_gateway, "openrouter_chat", fake_chat), \
                 patch.object(ai_council, "Store", self._store_factory(state_path)), \
                 patch.object(ai_council, "log_event", lambda *args, **kwargs: None):
                record = ai_council.consult("Should we deploy PR 13?", project="personal-ai-agent")

            self.assertEqual(len(record["participants"]), 3)
            self.assertEqual({x["role"] for x in record["participants"]}, {"manager", "critic", "google"})
            self.assertEqual(record["synthesis"]["recommendation"], "Run staging gates first")
            self.assertEqual(len(calls), 4)  # 3 advisers + 1 judge
            self.assertEqual(sum(1 for _, structured in calls if structured), 1)

            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            saved = [x for x in data["trust_snapshots"] if x.get("kind") == "AI_COUNCIL"]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["id"], record["id"])

    def test_material_conflict_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = str(Path(tmp) / "state.json")

            def fake_chat(*, model, messages, sensitive=False, max_tokens=0, temperature=0, response_format=None):
                if response_format:
                    return json.dumps({
                        "consensus": [],
                        "disagreements": ["One adviser recommends merge; another recommends blocking"],
                        "blind_spots": [],
                        "recommendation": "Verify the disputed deployment evidence",
                        "confidence": 0.7,
                        "material_conflict": True,
                        "requires_owner_decision": True,
                        "next_checks": ["Inspect staging logs"],
                    }), {}, 10
                return f"{model} opinion", {}, 10

            with patch.object(ai_council.model_gateway, "configured", lambda: True), \
                 patch.object(ai_council.model_gateway, "openrouter_chat", fake_chat), \
                 patch.object(ai_council, "Store", self._store_factory(state_path)), \
                 patch.object(ai_council, "log_event", lambda *args, **kwargs: None):
                record = ai_council.consult("Merge now?")

            self.assertTrue(record["synthesis"]["material_conflict"])
            self.assertEqual(record["status"], "OWNER_DECISION_REQUIRED")
            data = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(len(data["contradictions"]), 1)
            self.assertEqual(data["contradictions"][0]["origin"], record["id"])

    def test_sensitive_content_is_rejected_before_fanout(self):
        with self.assertRaisesRegex(ValueError, "sensitive/clinical"):
            ai_council.consult("private clinical case", sensitive=True, persist=False)


if __name__ == "__main__":
    unittest.main()
