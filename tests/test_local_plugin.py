from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from project_compass.agent_inbox import AgentInbox
from project_compass.local_plugin import LocalPluginAdapter, PluginRequestError
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import FactProposal, ProjectContext, StateQuery
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


class LocalPluginAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.workspace = ProjectWorkspace(root / "state", self.project)
        self.workspace.save([])
        self.events = []
        self.token = "a" * 40
        self.inbox = AgentInbox({"schema_version": 1, "project_path": str(self.project), "owner_id": "owner", "clients": [
            {"client_id": "client-a", "member_id": "alice", "session_id": "session-a", "agent": "codex", "token": self.token}
        ]}, self.workspace, self.events)
        self.server = create_dashboard_server(self.events, port=0, project_path=str(self.project), agent_inbox=self.inbox)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.context = ProjectContext.for_project(self.project, "alice", "session-a", "codex")
        self.adapter = LocalPluginAdapter(f"http://127.0.0.1:{self.server.server_address[1]}", self.context, self.token)

    def stop(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()

    def test_dispatch_submits_event_reads_state_and_proposes_fact(self):
        event = EvidenceEvent("e-1", "session-a", "alice", "assistant_message", "Deploy remains pending", datetime(2026, 10, 30, 8, tzinfo=timezone.utc))
        appended = self.adapter.dispatch("evidence.append", {"event": event.to_protocol_dict(self.context)})
        state = self.adapter.dispatch("state.query", StateQuery(self.context, "下一步做什么？").to_payload())
        proposal = FactProposal("p-1", self.context, appended["ids"][0], "task", "deploy", event.content, "pending")
        proposed = self.adapter.dispatch("fact.propose", proposal.to_payload())

        self.assertEqual(appended["appended"], 1)
        self.assertEqual(state["project"]["evidence_count"], 1)
        self.assertEqual(proposed["appended"], 1)
        self.assertEqual(self.adapter.dispatch("project.context", {})["project_id"], self.context.project_id)
        self.assertEqual(state["scopes"], ["team", "personal", "evidence"])
        self.assertIn("personal", state)
        self.assertIn("evidence", state)
        self.assertIn("current_facts", state["answer"])
        self.assertIn("supporting_evidence", state["answer"])
        self.assertIn("evidence_gaps", state["answer"])
        self.assertIn("next", state["answer"])

    def test_state_query_is_member_scoped_and_rejects_unknown_scope(self):
        query = StateQuery(self.context, "只看我的任务", scopes=("personal", "requests"))
        state = self.adapter.query_state(query)
        self.assertEqual(state["scopes"], ["personal", "requests"])
        self.assertEqual(state["personal"]["member_id"], "alice")
        self.assertNotIn("team", state)
        with self.assertRaises(ValueError):
            self.adapter.dispatch("state.query", {**query.to_payload(), "scopes": ["private-admin"]})

    def test_context_mismatch_and_auth_error_are_rejected_without_secret_echo(self):
        wrong = ProjectContext("different", str(self.project), "alice", "session-a", "codex")
        broken = LocalPluginAdapter(f"http://127.0.0.1:{self.server.server_address[1]}", self.context, "b" * 40)
        with self.assertRaises(ValueError):
            LocalPluginAdapter(f"http://127.0.0.1:{self.server.server_address[1]}", wrong, self.token).dispatch(
                "state.query", StateQuery(self.context, "状态").to_payload())
        with self.assertRaises(PluginRequestError) as error:
            broken.dispatch("state.query", StateQuery(self.context, "状态").to_payload())
        self.assertNotIn("b" * 40, str(error.exception))


if __name__ == "__main__":
    unittest.main()
