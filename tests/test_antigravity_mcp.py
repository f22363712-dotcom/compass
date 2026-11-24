"""Test ProjectCompass MCP Server compatibility with Antigravity agent environment."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from project_compass.local_plugin import LocalPluginAdapter
from project_compass.mcp_server import ProjectCompassMCPServer
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_workspace import ProjectWorkspace


class FakeLocalAdapter:
    """Mock adapter simulating the loopback ProjectCompass server responses."""

    def __init__(self, context: ProjectContext):
        self.context = context
        self.appended_events: list[dict] = []

    def dispatch(self, method: str, arguments: dict) -> dict:
        if method == "project.context":
            return {
                "project_id": "test-project-id",
                "project_path": self.context.project_path,
                "member_id": self.context.member_id,
                "session_id": self.context.session_id,
                "agent": self.context.agent,
            }
        if method == "state.query":
            return {
                "project_id": arguments.get("project_id"),
                "question": arguments.get("question"),
                "answer": "Project is proceeding on Stage E with Antigravity integration.",
                "evidence_ids": ["agy-1"],
            }
        if method == "evidence.append":
            event = arguments.get("event")
            self.appended_events.append(event)
            return {"appended": 1, "id": event.get("id")}
        if method == "fact.propose":
            return {"accepted": False, "proposed": len(arguments.get("proposals", []))}
        if method == "note.record":
            return {"recorded": True, "note": {"kind": arguments.get("kind", "decision")}}
        if method == "completion.verify":
            return {"passed": True, "verdict": "pass", "blockers": [], "warnings": []}
        raise ValueError(f"unknown method {method}")


class AntigravityMCPTest(unittest.TestCase):
    def setUp(self):
        self.context = ProjectContext.for_project(
            project_path=str(Path(".").resolve()),
            member_id="developer",
            session_id="43b1c7ad-67d5-45b4-876f-55201ebe8c83",
            agent="antigravity",
        )
        self.adapter = FakeLocalAdapter(self.context)
        self.server = ProjectCompassMCPServer(self.adapter)

    def test_mcp_initialize_handshake_and_tools_list(self):
        # 1. initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "antigravity", "version": "1.0.0"}},
        }
        init_res = self.server.handle(init_req)
        self.assertEqual(init_res["id"], 1)
        self.assertEqual(init_res["result"]["serverInfo"]["name"], "project-compass")
        self.assertIn("tools", init_res["result"]["capabilities"])

        # 2. tools/list
        tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        tools_res = self.server.handle(tools_req)
        self.assertEqual(tools_res["id"], 2)
        tool_names = [t["name"] for t in tools_res["result"]["tools"]]
        self.assertEqual(
            tool_names,
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

    def test_mcp_call_project_context_and_query_state(self):
        call_ctx = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "project_context", "arguments": {}},
        }
        res_ctx = self.server.handle(call_ctx)
        self.assertFalse(res_ctx["result"]["isError"])
        structured = res_ctx["result"]["structuredContent"]
        self.assertEqual(structured["agent"], "antigravity")
        self.assertEqual(structured["session_id"], "43b1c7ad-67d5-45b4-876f-55201ebe8c83")

        call_query = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "query_state",
                "arguments": {
                    "project_id": "test-project-id",
                    "question": "What is the current status?",
                },
            },
        }
        res_query = self.server.handle(call_query)
        self.assertFalse(res_query["result"]["isError"])
        self.assertIn("Antigravity integration", res_query["result"]["structuredContent"]["answer"])

    def test_mcp_call_append_evidence_from_antigravity(self):
        call_append = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "append_evidence",
                "arguments": {
                    "event": {
                        "id": "agy-test-ev-1",
                        "session_id": "43b1c7ad-67d5-45b4-876f-55201ebe8c83",
                        "author": "antigravity",
                        "kind": "assistant_message",
                        "content": "Stage E completed with 409 tests.",
                        "observed_at": "2026-11-04T15:00:00+08:00",
                    }
                },
            },
        }
        res_append = self.server.handle(call_append)
        self.assertFalse(res_append["result"]["isError"])
        self.assertEqual(res_append["result"]["structuredContent"]["id"], "agy-test-ev-1")
        self.assertEqual(len(self.adapter.appended_events), 1)

    def test_mcp_rejects_unknown_tool_and_invalid_jsonrpc(self):
        unknown_call = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "delete_project_history", "arguments": {}},
        }
        res_unknown = self.server.handle(unknown_call)
        self.assertEqual(res_unknown["error"]["code"], -32601)

        invalid_rpc = {"method": "tools/list"}
        res_invalid = self.server.handle(invalid_rpc)
        self.assertEqual(res_invalid["error"]["code"], -32600)

    def test_global_mcp_server_routes_dynamic_project_path_and_multi_session(self):
        from project_compass.local_plugin import WorkspaceMCPAdapter

        with tempfile.TemporaryDirectory() as tmp:
            proj_a = Path(tmp) / "project-alpha"
            proj_b = Path(tmp) / "project-beta"
            proj_a.mkdir()
            proj_b.mkdir()

            ctx_a = ProjectContext.for_project(proj_a, "fang", "sess-default", "antigravity")
            ws_a = ProjectWorkspace(proj_a / ".project-memory", proj_a)
            server = ProjectCompassMCPServer(
                WorkspaceMCPAdapter(ws_a, ctx_a),
                allow_dynamic_project=True,
            )

            # Every exposed tool advertises optional project_path and session_id routing fields
            tools_res = server.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            for tool in tools_res["result"]["tools"]:
                props = tool["inputSchema"]["properties"]
                self.assertIn("project_path", props)
                self.assertIn("session_id", props)

            # Prime cache on proj_b session b1, then mutate via session b1 and b2
            ctx_b1_before = server.handle({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"project_path": str(proj_b), "session_id": "sess-b1"}},
            })
            self.assertFalse(ctx_b1_before["result"]["isError"])

            note_b1 = server.handle({
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "record_note",
                    "arguments": {
                        "project_path": str(proj_b),
                        "session_id": "sess-b1",
                        "kind": "decision",
                        "title": "漫剧主线分镜协议定案",
                        "text": "统一采用横屏分镜节奏并保留角色色卡。",
                    },
                },
            })
            self.assertFalse(note_b1["result"]["isError"])

            note_b2 = server.handle({
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "record_note",
                    "arguments": {
                        "project_path": str(proj_b),
                        "session_id": "sess-b2",
                        "kind": "task",
                        "title": "补齐主角三视图色卡",
                        "text": "待补齐主角正面侧面背面三视图提示词。",
                    },
                },
            })
            self.assertFalse(note_b2["result"]["isError"])

            # proj_a stays completely isolated from proj_b's records
            q_a = server.handle({
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {"name": "query_state", "arguments": {"question": "漫剧主线分镜"}},
            })
            self.assertFalse(q_a["result"]["isError"])
            self.assertNotIn("漫剧主线分镜协议定案", json.dumps(q_a["result"]["structuredContent"], ensure_ascii=False))

            # Querying proj_b sees records written across concurrent sessions and refreshes cache
            q_b = server.handle({
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "query_state", "arguments": {"project_path": str(proj_b), "session_id": "sess-b2", "question": "分镜"}},
            })
            self.assertFalse(q_b["result"]["isError"])
            self.assertIn("漫剧主线分镜协议定案", json.dumps(q_b["result"]["structuredContent"], ensure_ascii=False))

            ctx_b1_after = server.handle({
                "jsonrpc": "2.0",
                "id": 16,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"project_path": str(proj_b), "session_id": "sess-b1"}},
            })
            self.assertFalse(ctx_b1_after["result"]["isError"])
            self.assertEqual(ctx_b1_after["result"]["structuredContent"]["project_path"], str(proj_b.resolve()))

            # Nonexistent project_path returns MCP error envelope instead of crashing
            bad_proj = server.handle({
                "jsonrpc": "2.0",
                "id": 17,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"project_path": str(Path(tmp) / "missing-dir")}},
            })
            self.assertTrue(bad_proj["result"]["isError"])

            # Bound server (allow_dynamic_project=False) blocks foreign project_path
            bound_server = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws_a, ctx_a), allow_dynamic_project=False)
            rejected = bound_server.handle({
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"project_path": str(proj_b)}},
            })
            self.assertTrue(rejected["result"]["isError"])


if __name__ == "__main__":
    unittest.main()

