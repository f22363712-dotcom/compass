"""Tests for Slice 1: MCP project_context Inline & Spill compact context cache."""
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from project_compass.investigator import investigate
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import (
    ProjectContext,
    build_compact_project_context,
)
from project_compass.project_workspace import ProjectWorkspace


class SuperagentCompactContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project_path = self.root / "demo_proj"
        self.project_path.mkdir()

        self.context = ProjectContext.for_project(
            project_path=self.project_path,
            member_id="alice",
            session_id="session-1",
            agent="codex",
        )

    def test_compact_context_inline_and_spill(self):
        # Create a state payload with goals, accepted facts, conflicts, and long outputs
        state = {
            "handoff_brief": {"goal": "Build Superagent Architecture"},
            "team": {
                "facts": [
                    {
                        "id": "fact-1",
                        "kind": "goal",
                        "subject_key": "project.goal",
                        "value": "Build Superagent Architecture",
                        "status": "accepted",
                    },
                    {
                        "id": "fact-2",
                        "kind": "decision",
                        "subject_key": "arch.mcp",
                        "value": "Adopt MCP Stdio interface with Inline & Spill cache",
                        "status": "accepted",
                    },
                    {
                        "id": "fact-3",
                        "kind": "task",
                        "subject_key": "task.mcp",
                        "value": "Implement compact context schema",
                        "status": "accepted",
                    },
                ],
                "conflicts": [
                    {
                        "subject_key": "task.mcp",
                        "sides": [
                            {"author": "alice", "value": "Implement compact context schema"},
                            {"author": "bob", "value": "Use legacy verbose context schema"},
                        ],
                    }
                ],
            },
            "evidence": [
                {
                    "id": "ev-long-log",
                    "kind": "command_execution",
                    "content": "ERROR: Stack trace:\n" + ("line of verbose execution output...\n" * 50),
                    "content_preview": "ERROR: Stack trace...",
                },
                {
                    "id": "ev-short",
                    "kind": "assistant_message",
                    "content": "Short message",
                    "content_preview": "Short message",
                },
            ],
            "derived_context": {
                "evidence_source_refs": ["src/mcp_server.py", "src/plugin_protocol.py"],
            },
        }

        compact = build_compact_project_context(self.context, state)

        # 1. Inline checks
        self.assertEqual(compact["project_id"], self.context.project_id)
        self.assertEqual(compact["core_goal"], "Build Superagent Architecture")
        self.assertEqual(len(compact["accepted_facts"]), 3)
        self.assertEqual(compact["accepted_facts"][0]["id"], "fact-1")
        self.assertTrue(len(compact["accepted_facts"][0]["summary"]) <= 50)

        # 2. Conflict summary checks
        self.assertEqual(len(compact["conflicts"]), 1)
        self.assertEqual(compact["conflicts"][0]["subject_key"], "task.mcp")
        self.assertEqual(compact["conflicts"][0]["side_count"], 2)
        self.assertIn("alice", compact["conflicts"][0]["summary"])

        # 3. Entity checks
        self.assertTrue(any(e["kind"] == "task" for e in compact["entities"]))
        self.assertTrue(any(e["kind"] == "source_ref" for e in compact["entities"]))

        # 4. Spill checks (long logs should be spilled into a reference pointer)
        self.assertTrue(len(compact["spills"]) >= 1)
        spill = next(s for s in compact["spills"] if s["id"] == "ev-long-log")
        self.assertEqual(spill["kind"], "command_execution")
        self.assertIn('[ev-long-log:', spill["pointer"])
        self.assertIn('call query_state("ev-long-log")', spill["pointer"])

        # 5. Token size comparison
        raw_size = len(json.dumps(state))
        compact_size = len(json.dumps(compact))
        self.assertLess(compact_size, raw_size)

    def test_project_workspace_compact_context(self):
        workspace = ProjectWorkspace(self.root / "state", self.project_path)
        events = [
            EvidenceEvent(
                "e-goal",
                "session-1",
                "alice",
                "assistant_message",
                "Project Goal: Ship Compact MCP",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"facts": [{"kind": "goal", "subject_key": "project.goal", "value": "Ship Compact MCP"}]},
            ),
            EvidenceEvent(
                "e-test-stack",
                "session-1",
                "alice",
                "test_result",
                "FAILED (failures=1)\n" + ("Traceback: File test.py, line 10 in test_foo\n" * 30),
                datetime(2026, 10, 24, 1, tzinfo=timezone.utc),
                {"exit_code": 1},
            ),
        ]
        workspace.save(events)

        compact = workspace.compact_context("alice", "session-1", "codex")
        self.assertEqual(compact["project_id"], workspace.project_id)
        self.assertEqual(compact["core_goal"], "Ship Compact MCP")
        # Test result should be spilled
        self.assertTrue(any(s["id"] == "e-test-stack" for s in compact["spills"]))
        pointer = next(s["pointer"] for s in compact["spills"] if s["id"] == "e-test-stack")
        self.assertIn('call query_state("e-test-stack")', pointer)

    def test_query_state_expands_spilled_reference(self):
        long_content = "FATAL ERROR AT COMPILATION:\n" + ("x" * 2000)
        events = [
            EvidenceEvent(
                "ev-spill-target",
                "session-1",
                "bob",
                "command_execution",
                long_content,
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"exit_code": 2, "source_ref": "build.log"},
            )
        ]
        # Query specifically with the spilled evidence id
        answer = investigate(events, "ev-spill-target")
        self.assertIn("ev-spill-target", answer.evidence_ids)
        self.assertEqual(len(answer.findings), 1)
        self.assertEqual(answer.findings[0]["quote"], long_content)
        self.assertEqual(answer.findings[0]["exit_code"], 2)

    def test_spill_pointer_variations_expand_correctly(self):
        long_content = "FATAL ERROR AT COMPILATION:\n" + ("x" * 2000)
        events = [
            EvidenceEvent(
                "ev-spill-target",
                "session-1",
                "bob",
                "command_execution",
                long_content,
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"exit_code": 2, "source_ref": "build.log"},
            )
        ]
        variations = [
            'call query_state("ev-spill-target")',
            "query_state('ev-spill-target')",
            '[ev-spill-target: 2.0KB] -> call query_state("ev-spill-target")',
            "evidence:ev-spill-target",
            "展开证据 ev-spill-target",
            "查看证据: ev-spill-target",
        ]
        for query in variations:
            answer = investigate(events, query)
            self.assertIn("ev-spill-target", answer.evidence_ids, f"Failed for query: {query}")
            self.assertEqual(answer.findings[0]["quote"], long_content)

    def test_project_context_is_hashable_with_compact_dicts(self):
        compact_ctx = ProjectContext(
            project_id="proj-1",
            project_path="/tmp/p",
            member_id="m1",
            session_id="s1",
            agent="codex",
            accepted_facts=({"id": "f1", "val": "v1"},),
            conflicts=({"key": "k1"},),
        )
        # Should not raise TypeError: unhashable type: 'dict'
        h = hash(compact_ctx)
        self.assertIsInstance(h, int)
        s = {compact_ctx}
        self.assertIn(compact_ctx, s)

    def test_mcp_server_compact_caching_and_default_project_id(self):
        from project_compass.mcp_server import ProjectCompassMCPServer

        class DummyAdapter:
            def __init__(self, ctx):
                self.context = ctx
                self.call_count = {"project.context": 0, "state.query": 0}

            def dispatch(self, method, params):
                self.call_count[method] = self.call_count.get(method, 0) + 1
                if method == "project.context":
                    return {"project_id": self.context.project_id, "cached": True}
                if method == "state.query":
                    # verify project_id was passed/injected
                    return {"project_id": params.get("project_id"), "result": "ok"}
                if method == "evidence.append":
                    return {"appended": 1}
                return {}

        adapter = DummyAdapter(self.context)
        server = ProjectCompassMCPServer(adapter)

        # 1. First call to project_context populates cache
        res1 = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "project_context", "arguments": {}}})
        self.assertEqual(adapter.call_count["project.context"], 1)

        # 2. Second call to project_context hits cache
        res2 = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "project_context", "arguments": {}}})
        self.assertEqual(adapter.call_count["project.context"], 1)

        # 3. Call with refresh forces re-fetch
        res3 = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_context", "arguments": {"refresh": True}}})
        self.assertEqual(adapter.call_count["project.context"], 2)

        # 4. query_state without explicit project_id auto-fills project_id
        q_res = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "query_state", "arguments": {"question": "ev-123"}}})
        self.assertFalse(q_res["result"]["isError"])
        payload = json.loads(q_res["result"]["content"][0]["text"])
        self.assertEqual(payload["project_id"], self.context.project_id)


if __name__ == "__main__":
    unittest.main()
