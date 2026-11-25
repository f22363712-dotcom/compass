"""Verification tests for open-source readiness, zero-config MCP, AST freshness, and clean export."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 stdlib has no tomllib
    tomllib = None

from project_compass import __version__, mcp_server
from project_compass.code_index import build_code_index, iter_python_files
from project_compass.dashboard import build_dashboard_state
from project_compass.derived_context import DerivedContext
from project_compass.local_plugin import (
    FactProposal,
    ProjectContext,
    WorkspaceMCPAdapter,
    evidence_event_to_protocol_dict,
)
from project_compass.mcp_server import ProjectCompassMCPServer
from project_compass.models import EvidenceEvent
from project_compass.project_workspace import ProjectWorkspace
from project_compass.transcript_watcher import TranscriptWatcher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_exporter_module():
    script_path = REPO_ROOT / "scripts" / "export_public_release.py"
    spec = importlib.util.spec_from_file_location("export_public_release", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class OpenSourceReadinessTests(unittest.TestCase):
    def test_o1_packaging_license_and_version_alignment(self):
        license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0", license_text)

        pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        if tomllib is not None:
            pyproject_data = tomllib.loads(pyproject_text)
            pkg_globs = pyproject_data["tool"]["setuptools"]["package-data"]["project_compass"]
        else:
            match = re.search(
                r"\[tool\.setuptools\.package-data\][\s\S]*?project_compass\s*=\s*(\[[\s\S]*?\])",
                pyproject_text,
            )
            self.assertIsNotNone(match, "missing [tool.setuptools.package-data] project_compass list")
            pkg_globs = ast.literal_eval(match.group(1))
        self.assertIn('requires = ["setuptools>=68"]', pyproject_text)
        self.assertIn('license = {text = "Apache-2.0"}', pyproject_text)
        self.assertIn('dependencies = []', pyproject_text)
        self.assertIn("web/*", pkg_globs)
        self.assertIn("antigravity_plugin/compass/*", pkg_globs)
        self.assertIn("antigravity_plugin/compass/sidecars/compass_board/*", pkg_globs)
        self.assertIn('compass = "project_compass.cli:main"', pyproject_text)
        self.assertIn('compass-mcp = "project_compass.mcp_server:main"', pyproject_text)
        self.assertEqual(__version__, "1.7.1")

        html_text = (REPO_ROOT / "src" / "project_compass" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="work-mode-switch"', html_text)
        self.assertIn('data-work-mode="solo"', html_text)
        self.assertIn('data-work-mode="team"', html_text)

        server_meta = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(server_meta["license"], "Apache-2.0")
        self.assertEqual(server_meta["version"], "1.7.1")
        self.assertEqual(
            [tool["name"] for tool in server_meta["capabilities"]["tools"]],
            [
                "project_context",
                "append_evidence",
                "query_state",
                "propose_fact",
                "record_note",
                "verify_completion",
                "open_compass",
                "compass_app_action",
            ],
        )

        # MCP initialize reports package __version__
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "proj"
            project_dir.mkdir()
            ctx = ProjectContext.for_project(project_dir, "mcp-agent", "mcp-local", "codex")
            adapter = WorkspaceMCPAdapter(ProjectWorkspace(Path(tmp) / "ws", project_dir), ctx)
            server = ProjectCompassMCPServer(adapter)
            init_res = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(init_res["result"]["serverInfo"]["version"], "1.7.1")

    def test_o3_zero_config_workspace_mcp_flow_and_remote_token_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "demo-repo"
            project_dir.mkdir()
            ws = ProjectWorkspace(Path(tmp) / ".project-memory", project_dir)
            ctx = ProjectContext.for_project(project_dir, "mcp-agent", "mcp-local", "codex")
            adapter = WorkspaceMCPAdapter(ws, ctx)
            server = ProjectCompassMCPServer(adapter)

            # 1. project_context works cleanly even on empty workspace
            res_ctx = server.handle(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "project_context", "arguments": {}}}
            )
            self.assertFalse(res_ctx["result"]["isError"])

            # 2. append_evidence via protocol envelope
            ev = EvidenceEvent(
                id="ev-local-1",
                session_id="mcp-local",
                author="mcp-agent",
                kind="assistant_message",
                content="Decision: use SQLite FTS5 for local search.",
                observed_at=datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc),
            )
            res_app = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "append_evidence",
                        "arguments": {"event": evidence_event_to_protocol_dict(ev, ctx)},
                    },
                }
            )
            self.assertFalse(res_app["result"]["isError"])
            assigned_id = res_app["result"]["structuredContent"]["ids"][0]

            # 3. propose_fact with exact quote succeeds and stays proposed
            prop_valid = FactProposal(
                id="f-local-1",
                context=ctx,
                source_id=assigned_id,
                kind="decision",
                subject_key="arch.search",
                quote="Decision: use SQLite FTS5 for local search.",
            )
            res_prop = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "propose_fact", "arguments": prop_valid.to_payload()},
                }
            )
            self.assertFalse(res_prop["result"]["isError"])

            # 4. propose_fact with fabricated quote is rejected cleanly (never promoted)
            prop_fake = FactProposal(
                id="f-fake-1",
                context=ctx,
                source_id=assigned_id,
                kind="decision",
                subject_key="arch.fake",
                quote="This quote does not exist anywhere in ev-local-1.",
            )
            res_fake = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "propose_fact", "arguments": prop_fake.to_payload()},
                }
            )
            self.assertTrue(res_fake["result"]["isError"])

            # 5. query_state reflects stored candidate, never silently accepted
            res_query = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "query_state", "arguments": {"question": "search"}},
                }
            )
            self.assertFalse(res_query["result"]["isError"])
            q_payload = json.loads(res_query["result"]["content"][0]["text"])
            team_facts = q_payload["team"]["facts"]
            personal_facts = q_payload["personal"]["facts"]
            self.assertFalse(any(f["status"] == "accepted" for f in team_facts))
            self.assertTrue(any(f["subject_key"].endswith("arch.search") and f["status"] == "proposed" for f in personal_facts))
            self.assertFalse(any("arch.fake" in f["subject_key"] for f in team_facts + personal_facts))

            # 6. Remote HTTP mode (--base-url) still enforces token presence
            with patch.dict(os.environ, {}, clear=True), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    mcp_server.main(["--project-path", str(project_dir), "--base-url", "http://127.0.0.1:9999"])
                self.assertNotEqual(cm.exception.code, 0)

    def test_o3_directory_freshness_and_ast_node_prioritization(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            src_pkg = repo_dir / "src" / "pkg"
            logs_dir = repo_dir / "logs"
            src_pkg.mkdir(parents=True)
            logs_dir.mkdir(parents=True)

            core_py = src_pkg / "core.py"
            core_py.write_text("def search_facts():\n    return True\n", encoding="utf-8")

            # Generate >205 nodes under logs/ so alphabetical sorting without prioritization would drop src/pkg/core.py
            for i in range(210):
                (logs_dir / f"a_noise_{i:03d}.py").write_text(f"def noise_{i}():\n    return {i}\n", encoding="utf-8")

            code_payload = build_code_index(repo_dir, project_id="proj-ast")
            dc = DerivedContext.from_understand_anything(code_payload, project_id="proj-ast", project_root=repo_dir)
            self.assertTrue(dc.source_current(repo_dir))

            ev = EvidenceEvent(
                id="ev-core",
                session_id="s1",
                author="dev",
                kind="decision",
                content="Updated `search_facts` in src/pkg/core.py for retrieval.",
                observed_at=datetime(2026, 11, 15, 2, 10, tzinfo=timezone.utc),
                metadata={"source_ref": "src/pkg/core.py"},
            )
            state = build_dashboard_state([ev], project_path=str(repo_dir), derived_context=dc)
            projected_nodes = state["derived_context"]["nodes"]
            self.assertLessEqual(len(projected_nodes), 200)
            projected_refs = [n.get("source_ref", "") for n in projected_nodes]
            self.assertTrue(any("src/pkg/core.py" in ref for ref in projected_refs))
            self.assertTrue(state["handoff_brief"]["code_nodes"])

            # Mutating source file invalidates directory freshness
            core_py.write_text("def search_facts():\n    return False\n", encoding="utf-8")
            self.assertFalse(dc.source_current(repo_dir))

    def test_o2_public_exporter_excludes_private_files_and_blocks_leaks(self):
        exporter = _load_exporter_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_repo = root / "src_repo"
            (src_repo / "src").mkdir(parents=True)
            (src_repo / ".goal").mkdir()
            (src_repo / "docs" / "archive").mkdir(parents=True)
            (src_repo / "devpost").mkdir()

            (src_repo / "src" / "main.py").write_text("print('clean')\n", encoding="utf-8")
            (src_repo / "AGENTS.md").write_text(
                "# Rules\n\nKeep shared baseline.\n\n<!-- goal-setup:begin -->\nsecret local\n<!-- goal-setup:end -->\n",
                encoding="utf-8",
            )
            (src_repo / ".goal" / "GOAL.md").write_text("private goal\n", encoding="utf-8")
            (src_repo / "docs" / "archive" / "old.md").write_text("archived\n", encoding="utf-8")
            (src_repo / "devpost" / "note.md").write_text("competition note\n", encoding="utf-8")
            (src_repo / "docs" / ("ZETARIS_DEMO_" + "CHALLENGE_55S.md")).write_text("protected\n", encoding="utf-8")
            (src_repo / ".env").write_text("SECRET=123\n", encoding="utf-8")

            out_dir = root / "export_out"
            summary = exporter.export_public_release(src_repo, out_dir, init_git=False)
            self.assertEqual(summary["leaks_found"], 0)
            self.assertTrue((out_dir / "src" / "main.py").exists())
            exported_agents = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Rules", exported_agents)
            self.assertIn("Keep shared baseline.", exported_agents)
            self.assertNotIn("goal-setup:begin", exported_agents)
            self.assertNotIn("secret local", exported_agents)
            self.assertFalse((out_dir / ".goal").exists())
            self.assertFalse((out_dir / "docs" / "archive").exists())
            self.assertFalse((out_dir / "devpost").exists())
            self.assertFalse((out_dir / ".env").exists())
            self.assertFalse((out_dir / "docs" / ("ZETARIS_DEMO_" + "CHALLENGE_55S.md")).exists())

            # Injecting a machine-local Windows path must trigger leak blocker
            leaked_repo = root / "leaked_repo"
            (leaked_repo / "docs").mkdir(parents=True)
            (leaked_repo / "docs" / "leak.md").write_text(
                "Path: C:\\" + r"Users\alice\secret",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                exporter.export_public_release(leaked_repo, root / "export_fail", init_git=False)

    def test_o3_transcript_watcher_preserves_antigravity_channel_on_noop_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_dir = root / "ws"
            ws_dir.mkdir(parents=True, exist_ok=True)
            ws = ProjectWorkspace(ws_dir, root)
            events: list[EvidenceEvent] = []
            ws.save(events)

            transcript = root / "logs" / "transcript.jsonl"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text("", encoding="utf-8")

            watcher = TranscriptWatcher(transcript, member_id="antigravity", session_id="s-noop")

            # 1. Empty initial sync must still report channel == "antigravity"
            status_empty = watcher.sync(ws, events)
            self.assertTrue(status_empty["enabled"])
            self.assertFalse(status_empty["updated"])
            self.assertEqual(status_empty["channel"], "antigravity")
            self.assertEqual(status_empty["member_id"], "antigravity")
            self.assertEqual(status_empty["captured_messages"], 0)

            # 2. Appended message sync must report updated + channel == "antigravity"
            rec = {
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "step_index": 1,
                "created_at": "2026-11-15T01:00:00Z",
                "content": "<USER_REQUEST>goal: keep channel consistent</USER_REQUEST>",
            }
            with transcript.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

            status_appended = watcher.sync(ws, events)
            self.assertTrue(status_appended["updated"])
            self.assertEqual(status_appended["channel"], "antigravity")
            self.assertEqual(status_appended["member_id"], "antigravity")
            self.assertGreaterEqual(status_appended["captured_messages"], 1)

            # 3. Subsequent no-op sync (raw_bytes == b"") must preserve channel and captured_messages
            status_noop = watcher.sync(ws, events)
            self.assertFalse(status_noop["updated"])
            self.assertEqual(status_noop["channel"], "antigravity")
            self.assertEqual(status_noop["member_id"], "antigravity")
            self.assertEqual(status_noop["captured_messages"], status_appended["captured_messages"])

    def test_o3_iter_python_files_prunes_skipped_directories_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (
                "src/pkg/alpha.py",
                "src/pkg/beta.py",
                ".git/hooks/skip.py",
                ".venv/lib/skip.py",
                "node_modules/pkg/skip.py",
                "src/pkg/__pycache__/skip.py",
            ):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x = 1\n", encoding="utf-8")

            visited_dirs: list[str] = []
            real_walk = os.walk

            def spy_walk(top, *args, **kwargs):
                for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
                    visited_dirs.append(Path(dirpath).relative_to(root.resolve()).as_posix())
                    yield dirpath, dirnames, filenames

            with patch("project_compass.code_index.os.walk", side_effect=spy_walk):
                found = iter_python_files(root)

            rels = [path.relative_to(root.resolve()).as_posix() for path in found]
            self.assertEqual(rels, ["src/pkg/alpha.py", "src/pkg/beta.py"])
            for skipped in (".git", ".venv", "node_modules", "__pycache__"):
                self.assertFalse(any(skipped in d.split("/") for d in visited_dirs), f"Descended into {skipped}: {visited_dirs}")


if __name__ == "__main__":
    unittest.main()
