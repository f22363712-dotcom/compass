from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_compass.cli import main
from project_compass.dashboard import build_dashboard_state
from project_compass.evidence_linking import build_evidence_index, confirm_relation
from project_compass.fact_engine import derive_facts
from project_compass.project_workspace import ProjectWorkspace
from project_compass.models import EvidenceEvent
from datetime import datetime, timedelta, timezone


class ProjectCliTest(unittest.TestCase):
    def test_cli_list_projects_empty_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--list-projects", "--workspace-root", str(Path(directory) / "state")])

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), [])

    def test_scan_persists_and_open_reuses_saved_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project-a"
            project.mkdir()
            (project / "README.md").write_text("# Demo", encoding="utf-8")
            session = project / "session.jsonl"
            session.write_text(
                json.dumps({"id": "session-e1", "type": "assistant_message", "session_id": "s1", "author": "alice", "content": "goal", "timestamp": "2026-10-24T08:00:00+00:00", "metadata": {"facts": [{"kind": "goal", "subject_key": "project.goal", "value": "Ship demo"}]}}),
                encoding="utf-8",
            )
            workspace_root = root / "compass-state"

            first_output = io.StringIO()
            with redirect_stdout(first_output):
                scan_result = main(["--scan", str(project), "--scan-codex-jsonl", str(session), "--workspace-root", str(workspace_root)])
            second_output = io.StringIO()
            with redirect_stdout(second_output):
                open_result = main(["--open", str(project), "--workspace-root", str(workspace_root), "--evidence-index"])

            payload = json.loads(second_output.getvalue())
            self.assertEqual(scan_result, 0)
            self.assertEqual(open_result, 0)
            self.assertTrue(ProjectWorkspace(workspace_root, project).exists())
            self.assertEqual([item["id"] for item in payload["evidence"] if item["id"] == "session-e1"], ["session-e1"])

    def test_open_missing_project_state_returns_useful_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project-missing"
            project.mkdir()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = main(["--open", str(project), "--workspace-root", str(root / "compass-state")])

        self.assertEqual(result, 2)
        self.assertIn("run --scan first", stderr.getvalue())

    def test_open_evidence_index_includes_persisted_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project-a"
            project.mkdir()
            session = project / "session.jsonl"
            session.write_text(
                json.dumps({"id": "session-e1", "type": "assistant_message", "session_id": "s1", "author": "alice", "content": "goal", "timestamp": "2026-10-24T08:00:00+00:00", "metadata": {"facts": [{"kind": "goal", "subject_key": "project.goal", "value": "Ship demo"}]}}),
                encoding="utf-8",
            )
            workspace_root = root / "compass-state"
            main(["--scan", str(project), "--scan-codex-jsonl", str(session), "--workspace-root", str(workspace_root)])
            workspace = ProjectWorkspace(workspace_root, project)
            events = workspace.load()
            relation = build_evidence_index(events, derive_facts(events)).candidate_relations[0]
            workspace.save_review_state([confirm_relation(relation, "owner")], [{"action": "confirm_relation"}])

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["--open", str(project), "--workspace-root", str(workspace_root), "--evidence-index"])

            payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(len(payload["confirmed_relations"]), 1)

    def test_web_review_callback_accepts_fact_and_persists_team_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project-a"
            project.mkdir()
            session = project / "session.jsonl"
            session.write_text(
                "\n".join([
                    json.dumps({"id": "e1", "type": "assistant_message", "session_id": "a", "author": "alice", "content": "active", "timestamp": "2026-10-24T08:00:00+00:00", "metadata": {"facts": [{"kind": "task", "subject_key": "task.demo", "value": "Build demo [active]"}]}}),
                    json.dumps({"id": "e2", "type": "assistant_message", "session_id": "b", "author": "bob", "content": "blocked", "timestamp": "2026-10-24T08:01:00+00:00", "metadata": {"facts": [{"kind": "task", "subject_key": "task.demo", "value": "Build demo [blocked]"}]}}),
                ]),
                encoding="utf-8",
            )
            workspace_root = root / "compass-state"
            with patch("project_compass.cli.run_dashboard") as run_dashboard:
                self.assertEqual(main(["--scan", str(project), "--scan-codex-jsonl", str(session), "--workspace-root", str(workspace_root), "--web"]), 0)
                callback = run_dashboard.call_args.kwargs["review_callback"]
                events = ProjectWorkspace(workspace_root, project).load()
                selected = derive_facts(events)[0].id
                state = callback("accept_fact", selected, "owner")

            team_fact = next(fact for fact in state["team"]["facts"] if fact["id"] == selected)
            self.assertEqual(team_fact["status"], "accepted")
            self.assertEqual(len(state["team"]["conflicts"]), 1)
            review = state["review_history"][-1]
            self.assertEqual(review["value"], team_fact["value"])
            self.assertEqual(review["evidence_ids"], team_fact["evidence_ids"])

    def test_web_review_callback_records_rejection_and_evidence_request_without_promoting_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project-a"; project.mkdir()
            workspace = ProjectWorkspace(Path(directory) / "state", project)
            events = [
                EvidenceEvent("e1", "s1", "alice", "assistant_message", "candidate", datetime(2026, 10, 24, tzinfo=timezone.utc), {"facts": [{"kind": "task", "subject_key": "task.demo", "value": "Build demo"}]}),
            ]
            workspace.save(events)
            from project_compass.cli import _review_callback
            callback, _, _, _ = _review_callback(events, workspace, str(project), [], [], [])
            fact = derive_facts(events)[0]
            requested = callback("request_evidence", fact.id, "owner", "缺少发布日志")
            self.assertFalse(requested["fact_reviews"])
            self.assertEqual(requested["review_history"][-1]["action"], "request_evidence")
            self.assertEqual(requested["review_history"][-1]["note"], "缺少发布日志")
            self.assertEqual(requested["team_review_queue"][0]["status"], "needs_evidence")
            events.append(EvidenceEvent("e2", "s1", "alice", "assistant_message", "new validation log", datetime.now(timezone.utc) + timedelta(seconds=1), {}))
            updated = build_dashboard_state(events, review_history=requested["review_history"])
            relation = next(item for item in updated["candidate_relations"] if item["basis"] == "requested-evidence")
            confirmed = callback("confirm_relation", relation["id"], "owner")
            self.assertEqual(confirmed["confirmed_relations"][0]["evidence_id"], relation["evidence_id"])
            self.assertTrue(confirmed["evidence_requests"], "关系确认不应关闭补证据请求")
            resolved = callback("accept_fact", fact.id, "owner", "已核对补充日志")
            resolution = resolved["review_history"][-1]
            self.assertEqual(resolution["action"], "accept_fact")
            self.assertEqual(resolution["evidence_request_id"], f"evidence-request-{fact.id}")
            self.assertEqual(resolution["resolved_relation_ids"], [confirmed["confirmed_relations"][0]["id"]])
            self.assertEqual(resolution["resolved_evidence_ids"], [relation["evidence_id"]])
            self.assertFalse(resolved["evidence_requests"])


if __name__ == "__main__":
    unittest.main()
