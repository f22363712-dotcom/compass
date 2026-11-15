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
        self.assertEqual(tool_names, ["project_context", "append_evidence", "query_state", "propose_fact"])

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


if __name__ == "__main__":
    unittest.main()

