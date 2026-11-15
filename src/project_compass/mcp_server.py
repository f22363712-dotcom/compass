from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, TextIO

from . import __version__
from .local_plugin import LocalPluginAdapter, WorkspaceMCPAdapter
from .plugin_protocol import ProjectContext
from .project_workspace import ProjectWorkspace


TOOL_DEFINITIONS = [
    {"name": "project_context", "description": "Read the bound ProjectCompass project context (compact inline & spill cached view).", "inputSchema": {"type": "object", "properties": {"refresh": {"type": "boolean", "description": "Refresh compact context cache"}}}},
    {"name": "append_evidence", "description": "Append one public Agent evidence event.", "inputSchema": {"type": "object", "required": ["event"]}},
    {"name": "query_state", "description": "Read evidence-backed project state or expand spilled evidence.", "inputSchema": {"type": "object", "properties": {"question": {"type": "string", "description": "Question or evidence ID to expand (e.g. 'ev-xxx')"}, "evidence_id": {"type": "string"}, "project_id": {"type": "string"}}, "required": ["question"]}},
    {"name": "propose_fact", "description": "Submit a candidate fact with an exact source quote.", "inputSchema": {"type": "object", "properties": {"proposals": {"type": "array"}, "project_id": {"type": "string"}}, "required": ["proposals"]}},
]
METHODS = {"project_context": "project.context", "append_evidence": "evidence.append",
           "query_state": "state.query", "propose_fact": "fact.propose"}


class ProjectCompassMCPServer:
    def __init__(self, adapter):
        self.adapter = adapter
        self._cached_context: dict[str, Any] | None = None

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                    "error": {"code": -32600, "message": "Invalid Request"}}
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "project-compass", "version": __version__}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_DEFINITIONS}}
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if name not in METHODS:
                return self._error(request_id, -32601, "Unknown tool")
            args = params.get("arguments") or {}
            if isinstance(args, str):
                args = {"question": args}
            elif not isinstance(args, dict):
                args = {}
            else:
                args = dict(args)

            if name == "query_state":
                if "question" not in args:
                    if "evidence_id" in args:
                        args["question"] = args["evidence_id"]
                    elif "id" in args:
                        args["question"] = args["id"]
                if hasattr(self.adapter, "context") and hasattr(self.adapter.context, "project_id"):
                    if "project_id" not in args:
                        args["project_id"] = self.adapter.context.project_id
            elif name == "propose_fact":
                if hasattr(self.adapter, "context") and hasattr(self.adapter.context, "project_id"):
                    if "project_id" not in args:
                        args["project_id"] = self.adapter.context.project_id

            if name == "project_context":
                if not args.get("refresh") and self._cached_context is not None:
                    result = self._cached_context
                    return {"jsonrpc": "2.0", "id": request_id, "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                        "structuredContent": result, "isError": False}}

            try:
                result = self.adapter.dispatch(METHODS[name], args)
                if name == "project_context":
                    self._cached_context = result
                elif name in {"append_evidence", "propose_fact"}:
                    self._cached_context = None
                return {"jsonrpc": "2.0", "id": request_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "structuredContent": result, "isError": False}}
            except (ValueError, OSError, RuntimeError):
                return {"jsonrpc": "2.0", "id": request_id, "result": {
                    "content": [{"type": "text", "text": "ProjectCompass tool call failed; check protocol fields and project access."}],
                    "isError": True}}
        return self._error(request_id, -32601, "Method not found")

    @staticmethod
    def _error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(server: ProjectCompassMCPServer, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = server._error(None, -32700, "Parse error")
        else:
            response = server.handle(request)
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ProjectCompass MCP server over stdio")
    parser.add_argument("--base-url", default=os.environ.get("PROJECT_COMPASS_BASE_URL"))
    parser.add_argument("--project-path", default=os.environ.get("PROJECT_COMPASS_PROJECT_PATH", "."))
    parser.add_argument("--workspace-root", default=os.environ.get("PROJECT_COMPASS_WORKSPACE_ROOT"))
    parser.add_argument("--member-id", default=os.environ.get("PROJECT_COMPASS_MEMBER_ID", "mcp-agent"))
    parser.add_argument("--session-id", default=os.environ.get("PROJECT_COMPASS_SESSION_ID", "mcp-local"))
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--token-env", default="PROJECT_COMPASS_AGENT_TOKEN")
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env)
    context = ProjectContext.for_project(args.project_path, args.member_id, args.session_id, args.agent)
    if args.base_url:
        if not token:
            parser.error(f"--base-url requires a token in {args.token_env}")
        adapter = LocalPluginAdapter(args.base_url, context, token)
    else:
        workspace_root = Path(args.workspace_root) if args.workspace_root else (Path(context.project_path) / ".project-memory")
        workspace = ProjectWorkspace(workspace_root, context.project_path)
        adapter = WorkspaceMCPAdapter(workspace, context)
    serve_stdio(ProjectCompassMCPServer(adapter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
