from datetime import datetime, timezone
import unittest

from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import FactProposal, ProjectContext, StateQuery


class PluginProtocolTests(unittest.TestCase):
    def setUp(self):
        self.context = ProjectContext(
            project_id="project-123",
            project_path="C:/Projects/demo",
            member_id="alice",
            session_id="session-1",
            agent="codex",
        )

    def test_context_and_requests_round_trip_with_protocol_version(self):
        restored = ProjectContext.from_dict(self.context.to_dict())
        query = StateQuery(self.context, "下一步做什么？", scopes=("team", "evidence"))
        proposal = FactProposal("proposal-1", self.context, "source-1", "task", "deploy", "Deploy the demo", "pending")

        self.assertEqual(restored, self.context)
        self.assertEqual(query.to_payload()["schema_version"], 1)
        self.assertEqual(query.to_payload()["project_id"], "project-123")
        self.assertEqual(proposal.to_payload()["proposals"][0]["quote"], "Deploy the demo")

    def test_evidence_event_serializes_context_without_hidden_metadata(self):
        event = EvidenceEvent(
            "e-1", "session-1", "alice", "assistant_message", "Public decision",
            datetime(2026, 10, 30, 8, tzinfo=timezone.utc),
            {"secret": "must stay internal", "source_ref": "chat:1"},
        )

        payload = event.to_protocol_dict(self.context)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["project_id"], "project-123")
        self.assertEqual(payload["event"]["id"], "e-1")
        self.assertNotIn("metadata", payload["event"])

    def test_protocol_rejects_wrong_version_and_project_context(self):
        with self.assertRaises(ValueError):
            ProjectContext.from_dict({**self.context.to_dict(), "schema_version": 2})
        with self.assertRaises(ValueError):
            ProjectContext("", "C:/Projects/other", "alice", "s", "codex")


if __name__ == "__main__":
    unittest.main()
