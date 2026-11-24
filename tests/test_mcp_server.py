import json
import unittest

from project_compass.mcp_server import ProjectCompassMCPServer


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def dispatch(self, method, params):
        self.calls.append((method, params))
        return {"method": method, "ok": True}


class MCPServerTests(unittest.TestCase):
    def test_initialize_and_tools_list_expose_project_compass_tools(self):
        server = ProjectCompassMCPServer(FakeAdapter())

        initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        self.assertEqual(initialized["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("resources", initialized["result"]["capabilities"])
        self.assertEqual({tool["name"] for tool in listed["result"]["tools"]}, {
            "project_context",
            "append_evidence",
            "query_state",
            "propose_fact",
            "record_note",
            "verify_completion",
            "open_compass",
            "compass_app_action",
        })

    def test_tools_call_dispatches_to_local_adapter_and_returns_mcp_content(self):
        adapter = FakeAdapter()
        server = ProjectCompassMCPServer(adapter)

        response = server.handle({"jsonrpc": "2.0", "id": "x", "method": "tools/call",
                                  "params": {"name": "query_state", "arguments": {"question": "下一步？"}}})

        self.assertEqual(adapter.calls, [("state.query", {"question": "下一步？"})])
        self.assertEqual(response["result"]["isError"], False)
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["ok"], True)

    def test_unknown_method_returns_json_rpc_error_and_notification_has_no_response(self):
        server = ProjectCompassMCPServer(FakeAdapter())

        error = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/unknown", "params": {}})
        notification = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        self.assertEqual(error["error"]["code"], -32601)
        self.assertIsNone(notification)
