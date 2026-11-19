import asyncio
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from project_compass.agent_inbox import AgentInbox
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import FactProposal, ProjectContext, StateQuery
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


@unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP Python SDK is required for the real-client smoke test")
class RealMCPClientTests(unittest.TestCase):
    def test_real_client_runs_full_tool_chain_and_reopen_keeps_state(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / "project"; project.mkdir(); state_root = root / "state"
            workspace = ProjectWorkspace(state_root, project); workspace.save([]); events = []
            token = "g" * 40; session_id = "mcp-real-session"
            inbox = AgentInbox({"schema_version": 1, "project_path": str(project), "owner_id": "owner", "clients": [
                {"client_id": "mcp-real", "member_id": "developer-a", "session_id": session_id, "agent": "codex", "token": token}
            ]}, workspace, events)
            server = create_dashboard_server(events, port=0, project_path=str(project), agent_inbox=inbox)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            context = ProjectContext.for_project(project, "developer-a", session_id, "codex")
            try:
                env = os.environ.copy(); env["PROJECT_COMPASS_AGENT_TOKEN"] = token
                source_root = str(Path(__file__).resolve().parents[1] / "src")
                existing_path = env.get("PYTHONPATH")
                env["PYTHONPATH"] = source_root if not existing_path else source_root + os.pathsep + existing_path
                params = StdioServerParameters(command=sys.executable, args=["-m", "project_compass.mcp_server",
                    "--base-url", f"http://127.0.0.1:{server.server_address[1]}", "--project-path", str(project),
                    "--member-id", "developer-a", "--session-id", session_id], env=env, cwd=str(project))

                async def run_client():
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as client:
                            await client.initialize()
                            tools = await client.list_tools()
                            event = EvidenceEvent("mcp-real-event", session_id, "developer-a", "assistant_message",
                                "The MCP host smoke test is ready.", datetime(2026, 10, 31, 9, tzinfo=timezone.utc))
                            append = await client.call_tool("append_evidence", {"event": event.to_protocol_dict(context)})
                            state = await client.call_tool("query_state", StateQuery(context, "阶段 A 下一步？").to_payload())
                            self_query = await client.call_tool("query_state", StateQuery(context, "我刚才做了什么？").to_payload())
                            # The adapter returns the stable server event id; use the persisted event id from state.
                            state_payload = json.loads(state.content[0].text)
                            source_id = state_payload["evidence"][0]["id"]
                            proposal = FactProposal("mcp-real-proposal", context, source_id, "task", "mcp-smoke", event.content, "pending")
                            proposed = await client.call_tool("propose_fact", proposal.to_payload())
                            return tools, append, state, self_query, proposed

                tools, append, state, self_query, proposed = asyncio.run(run_client())
                self.assertEqual(
                    {tool.name for tool in tools.tools},
                    {"project_context", "append_evidence", "query_state", "propose_fact", "record_note", "verify_completion"},
                )
                def is_error(result):
                    return getattr(result, "is_error", getattr(result, "isError", False))
                self.assertFalse(is_error(append)); self.assertFalse(is_error(state)); self.assertFalse(is_error(self_query)); self.assertFalse(is_error(proposed))
                self.assertEqual(json.loads(self_query.content[0].text)["answer"]["scope"]["member_id"], "developer-a")
                self.assertTrue(any(event.kind == "fact_proposal" for event in workspace.load()))
            finally:
                server.shutdown(); thread.join(3); server.server_close()
            reopened = ProjectWorkspace(state_root, project).load()
            self.assertEqual(len(reopened), 2)
            reopened_events = reopened
            reopened_inbox = AgentInbox({"schema_version": 1, "project_path": str(project), "owner_id": "owner", "clients": [
                {"client_id": "mcp-reopen", "member_id": "developer-a", "session_id": session_id, "agent": "codex", "token": token}
            ]}, ProjectWorkspace(state_root, project), reopened_events)
            reopened_server = create_dashboard_server(reopened_events, port=0, project_path=str(project), agent_inbox=reopened_inbox)
            reopened_thread = threading.Thread(target=reopened_server.serve_forever, daemon=True); reopened_thread.start()
            try:
                with urlopen(Request(f"http://127.0.0.1:{reopened_server.server_address[1]}/api/state"), timeout=5) as response:
                    board = json.loads(response.read().decode("utf-8"))
                self.assertEqual(board["project"]["evidence_count"], 1)
                self.assertIn("developer-a", board["personal"])
            finally:
                reopened_server.shutdown(); reopened_thread.join(3); reopened_server.server_close()


if __name__ == "__main__":
    unittest.main()
