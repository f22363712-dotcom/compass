import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.request import urlopen
import tempfile
import unittest

from project_compass.derived_context import DerivedContext, fingerprint_file
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


class DerivedContextHttpSmokeTest(unittest.TestCase):
    def _payload(self, project_id: str, source_fingerprint: str) -> dict:
        return {
            "schema_version": 1,
            "project_id": project_id,
            "source_ref": "src/main.py",
            "source_fingerprint": source_fingerprint,
            "observed_at": "2026-11-04T09:00:00+08:00",
            "nodes": [
                {
                    "id": "file:src/main.py",
                    "kind": "file",
                    "label": "src/main.py",
                    "source_ref": "src/main.py",
                },
                {
                    "id": "fn:main",
                    "kind": "function",
                    "label": "main",
                    "source_ref": "src/main.py",
                    "summary": "Project entry point.",
                },
            ],
            "edges": [
                {
                    "id": "edge-main",
                    "from_id": "file:src/main.py",
                    "to_id": "fn:main",
                    "kind": "contains",
                }
            ],
        }

    def _state(self, server):
        with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state") as response:
            return json.loads(response.read().decode("utf-8"))

    def _server(self, project, state_root, context):
        server = create_dashboard_server(
            [],
            host="127.0.0.1",
            port=0,
            project_path=str(project),
            workspace_root=state_root,
            derived_context=context,
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_project_bound_context_reports_current_stale_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "demo"
            source = project / "src" / "main.py"
            graph = project / ".ua" / "knowledge-graph.json"
            source.parent.mkdir(parents=True)
            graph.parent.mkdir(parents=True)
            source.write_text("def main(): return 1\n", encoding="utf-8")

            state_root = root / "state"
            workspace = ProjectWorkspace(state_root, project)
            workspace.save([])
            graph.write_text(
                json.dumps(self._payload(workspace.project_id, fingerprint_file(source))),
                encoding="utf-8",
            )
            context = DerivedContext.load(graph, project_id=workspace.project_id, project_root=project)
            server, thread = self._server(project, state_root, context)
            try:
                current = self._state(server)
                self.assertTrue(current["derived_context"]["enabled"])
                self.assertTrue(current["derived_context"]["current"])
                self.assertEqual(current["derived_context"]["origin"], "derived_context")
                self.assertEqual([node["id"] for node in current["derived_context"]["nodes"]], ["file:src/main.py", "fn:main"])

                source.write_text("def main(): return 2\n", encoding="utf-8")
                stale = self._state(server)
                self.assertFalse(stale["derived_context"]["current"])
                self.assertEqual(stale["derived_context"]["nodes"][0]["origin"], "derived_context")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            reopened_context = DerivedContext.load(graph, project_id=workspace.project_id, project_root=project)
            reopened_server, reopened_thread = self._server(project, state_root, reopened_context)
            try:
                reopened = self._state(reopened_server)
                self.assertFalse(reopened["derived_context"]["current"])
                self.assertEqual(reopened["project"]["path"], str(project.resolve()))
                self.assertEqual(reopened["derived_context"]["project_id"], workspace.project_id)
            finally:
                reopened_server.shutdown()
                reopened_server.server_close()
                reopened_thread.join(timeout=2)

    def test_cli_web_entrypoint_exposes_bound_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "demo"
            source = project / "src" / "main.py"
            graph = project / ".ua" / "knowledge-graph.json"
            source.parent.mkdir(parents=True)
            graph.parent.mkdir(parents=True)
            source.write_text("def main(): return 1\n", encoding="utf-8")
            state_root = root / "state"
            workspace = ProjectWorkspace(state_root, project)
            workspace.save([])
            graph.write_text(
                json.dumps(self._payload(workspace.project_id, fingerprint_file(source))),
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "project_compass.cli",
                    "--open",
                    str(project),
                    "--workspace-root",
                    str(state_root),
                    "--derived-context",
                    str(graph),
                    "--web",
                    "--port",
                    "0",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                line = process.stdout.readline().strip()
                self.assertTrue(line.startswith("http://127.0.0.1:"), line)
                with urlopen(line + "/api/state") as response:
                    state = json.loads(response.read().decode("utf-8"))
                self.assertTrue(state["derived_context"]["current"])
                self.assertEqual(state["derived_context"]["project_id"], workspace.project_id)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    def test_real_project_understand_anything_graph_cli_web_preserves_team_truth(self):
        from project_compass.dashboard import build_dashboard_state
        from project_compass.fact_engine import derive_facts
        from project_compass.sample_data import sample_events

        repo_root = Path(__file__).resolve().parents[1]
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "understand_anything_project_compass.json"
        raw_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory) / "state"
            workspace = ProjectWorkspace(state_root, repo_root)
            events = sample_events()
            workspace.save(events)
            accepted_fact = derive_facts(events)[0]
            review_entry = {
                "action": "accept_fact",
                "fact_id": accepted_fact.id,
                "subject_key": accepted_fact.subject_key,
                "kind": accepted_fact.kind.value,
                "value": accepted_fact.value,
                "evidence_ids": list(accepted_fact.evidence_ids),
                "source_ref": accepted_fact.source_ref,
                "reviewer": "owner",
                "observed_at": "2026-11-04T14:00:00+08:00",
            }
            workspace.save_review_state([], [review_entry], [review_entry])
            baseline = build_dashboard_state(
                workspace.load(),
                project_path=str(repo_root),
                review_history=[review_entry],
                fact_reviews=[review_entry],
            )

            bound_graph = Path(directory) / "understand-anything-bound.json"
            raw_fixture["projectId"] = workspace.project_id
            raw_fixture["sourceHash"] = fingerprint_file(repo_root / raw_fixture["entryFile"])
            bound_graph.write_text(json.dumps(raw_fixture), encoding="utf-8")

            context = DerivedContext.load(bound_graph, project_id=workspace.project_id, project_root=repo_root)
            for node in context.nodes:
                self.assertTrue((repo_root / node.source_ref).is_file(), node.source_ref)

            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(repo_root / "src")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "project_compass.cli",
                    "--open",
                    str(repo_root),
                    "--workspace-root",
                    str(state_root),
                    "--derived-context",
                    str(bound_graph),
                    "--web",
                    "--port",
                    "0",
                ],
                cwd=repo_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                line = process.stdout.readline().strip()
                self.assertTrue(line.startswith("http://127.0.0.1:"), line)
                with urlopen(line + "/api/state") as response:
                    state = json.loads(response.read().decode("utf-8"))
                dc = state["derived_context"]
                self.assertTrue(dc["enabled"])
                self.assertTrue(dc["current"])
                self.assertEqual(dc["origin"], "derived_context")
                self.assertEqual(dc["project_id"], workspace.project_id)
                self.assertEqual(len(dc["nodes"]), 9)
                self.assertEqual(len(dc["edges"]), 8)
                self.assertTrue(all(node["origin"] == "derived_context" and "status" not in node for node in dc["nodes"]))
                self.assertTrue(all(edge["origin"] == "derived_context" and "status" not in edge for edge in dc["edges"]))
                self.assertEqual(state["team"]["facts"], baseline["team"]["facts"])
                self.assertEqual(state["fact_reviews"], baseline["fact_reviews"])
                self.assertEqual(state["review_history"], baseline["review_history"])
                self.assertEqual(state["confirmed_relations"], baseline["confirmed_relations"])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
