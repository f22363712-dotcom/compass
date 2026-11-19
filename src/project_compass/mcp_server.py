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


_ROUTING_PROPERTIES = {
    "project_path": {
        "type": "string",
        "description": "Optional target project workspace directory path (routes to that project's .project-memory/ when dynamic routing is enabled).",
    },
    "session_id": {
        "type": "string",
        "description": "Optional current agent session identifier for isolating parallel sessions.",
    },
}

TOOL_DEFINITIONS = [
    {
        "name": "project_context",
        "description": "Read the bound ProjectCompass project context (compact inline & spill cached view).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh": {"type": "boolean", "description": "Refresh compact context cache"},
                **_ROUTING_PROPERTIES,
            },
        },
    },
    {
        "name": "append_evidence",
        "description": "Append one public Agent evidence event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event": {"type": "object", "description": "Public Agent evidence event object."},
                **_ROUTING_PROPERTIES,
            },
            "required": ["event"],
        },
    },
    {
        "name": "query_state",
        "description": "Read evidence-backed project state or expand spilled evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question or evidence ID to expand (e.g. 'ev-xxx')"},
                "evidence_id": {"type": "string"},
                "project_id": {"type": "string"},
                **_ROUTING_PROPERTIES,
            },
            "required": ["question"],
        },
    },
    {
        "name": "propose_fact",
        "description": "Submit a candidate fact with an exact source quote.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposals": {"type": "array"},
                "project_id": {"type": "string"},
                **_ROUTING_PROPERTIES,
            },
            "required": ["proposals"],
        },
    },
    {
        "name": "record_note",
        "description": "Record a goal, pending decision, unverified assumption, or todo pitfall in 1 step with a concise 15-20 char human title.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Full thought, decision, assumption, pitfall, or goal text"},
                "kind": {"type": "string", "enum": ["decision", "assumption", "task", "goal"], "description": "Category (default: decision)"},
                "title": {"type": "string", "description": "Concise 15-20 char human-readable summary title for the mindmap"},
                "client_nonce": {"type": "string", "description": "Optional idempotency key"},
                "project_id": {"type": "string"},
                **_ROUTING_PROPERTIES,
            },
            "required": ["text"],
        },
    },
    {
        "name": "verify_completion",
        "description": "Run pre-completion deterministic check against confirmed baselines, open pitfalls, and verification evidence before claiming done.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary of what was implemented and verified"},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "Modified file paths"},
                "test_evidence_ids": {"type": "array", "items": {"type": "string"}, "description": "Verification/test evidence IDs"},
                "project_id": {"type": "string"},
                **_ROUTING_PROPERTIES,
            },
            "required": ["summary"],
        },
    },
]
METHODS = {
    "project_context": "project.context",
    "append_evidence": "evidence.append",
    "query_state": "state.query",
    "propose_fact": "fact.propose",
    "record_note": "note.record",
    "verify_completion": "completion.verify",
}


class ProjectCompassMCPServer:
    def __init__(self, adapter, *, allow_dynamic_project: bool = False):
        self.adapter = adapter
        self.allow_dynamic_project = allow_dynamic_project
        self._cached_context: dict[str, Any] | None = None
        self._cached_contexts: dict[tuple[str, str], dict[str, Any]] = {}
        self._dynamic_adapters: dict[tuple[str, str], Any] = {}

    def _resolve_target(
        self, raw_project_path: Any, raw_session_id: Any
    ) -> tuple[Any, tuple[str, str], bool]:
        from pathlib import Path

        if raw_project_path is not None and not isinstance(raw_project_path, str):
            raise ValueError("project_path must be a string")
        if raw_session_id is not None and not isinstance(raw_session_id, str):
            raise ValueError("session_id must be a string")

        req_project = raw_project_path.strip() or None if raw_project_path is not None else None
        req_session = raw_session_id.strip() or None if raw_session_id is not None else None
        base_ctx = getattr(self.adapter, "context", None)

        if req_project is None and req_session is None:
            if base_ctx is not None:
                base_root = str(Path(base_ctx.project_path).expanduser().resolve())
                return self.adapter, (base_root, base_ctx.session_id), True
            return self.adapter, ("__default__", "__default__"), True

        if base_ctx is None or not self.allow_dynamic_project:
            if base_ctx is not None:
                base_root = Path(base_ctx.project_path).expanduser().resolve()
                if req_project is not None and Path(req_project).expanduser().resolve() != base_root:
                    raise ValueError("dynamic project_path routing is disabled for bound adapter")
                if req_session is not None and req_session != base_ctx.session_id:
                    raise ValueError("dynamic session_id routing is disabled for bound adapter")
                return self.adapter, (str(base_root), base_ctx.session_id), True
            raise ValueError("dynamic project_path/session_id routing requires a WorkspaceMCPAdapter")

        base_root = Path(base_ctx.project_path).expanduser().resolve()
        target_root = Path(req_project).expanduser().resolve() if req_project is not None else base_root
        if not target_root.exists() or not target_root.is_dir():
            raise ValueError(f"project_path does not exist or is not a directory: {target_root}")
        target_session = req_session or base_ctx.session_id
        cache_key = (str(target_root), target_session)

        if target_root == base_root and target_session == base_ctx.session_id:
            return self.adapter, cache_key, True

        cached = self._dynamic_adapters.get(cache_key)
        if cached is not None:
            return cached, cache_key, False

        from .local_plugin import WorkspaceMCPAdapter
        from .plugin_protocol import ProjectContext
        from .project_workspace import ProjectWorkspace

        target_ctx = ProjectContext.for_project(
            str(target_root),
            base_ctx.member_id,
            target_session,
            agent=getattr(base_ctx, "agent", "codex"),
        )
        if target_root == base_root and hasattr(self.adapter, "workspace"):
            target_workspace = self.adapter.workspace
        else:
            target_workspace = ProjectWorkspace(target_root / ".project-memory", target_ctx.project_path)
        adapter = WorkspaceMCPAdapter(target_workspace, target_ctx)
        self._dynamic_adapters[cache_key] = adapter
        return adapter, cache_key, False

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
                if name == "record_note":
                    args = {"text": args}
                elif name == "verify_completion":
                    args = {"summary": args}
                else:
                    args = {"question": args}
            elif not isinstance(args, dict):
                args = {}
            else:
                args = dict(args)

            try:
                raw_project_path = args.pop("project_path", None)
                raw_session_id = args.pop("session_id", None)
                target_adapter, cache_key, is_default_target = self._resolve_target(
                    raw_project_path, raw_session_id
                )

                if name == "append_evidence" and isinstance(args.get("event"), dict):
                    target_ctx = getattr(target_adapter, "context", None)
                    if target_ctx is not None and raw_session_id is not None:
                        ev_copy = dict(args["event"])
                        if isinstance(ev_copy.get("event"), dict):
                            inner = dict(ev_copy["event"])
                            inner.setdefault("session_id", target_ctx.session_id)
                            ev_copy["event"] = inner
                        else:
                            ev_copy.setdefault("session_id", target_ctx.session_id)
                        args["event"] = ev_copy
                elif name == "query_state":
                    if "question" not in args:
                        if "evidence_id" in args:
                            args["question"] = args["evidence_id"]
                        elif "id" in args:
                            args["question"] = args["id"]
                    if hasattr(target_adapter, "context") and hasattr(target_adapter.context, "project_id"):
                        if "project_id" not in args:
                            args["project_id"] = target_adapter.context.project_id
                elif name in {"propose_fact", "record_note", "verify_completion"}:
                    if name == "propose_fact":
                        args.setdefault("schema_version", 1)
                    if hasattr(target_adapter, "context") and hasattr(target_adapter.context, "project_id"):
                        if "project_id" not in args:
                            args["project_id"] = target_adapter.context.project_id

                if name == "project_context":
                    cached_result = (
                        self._cached_context
                        if is_default_target and self._cached_context is not None
                        else self._cached_contexts.get(cache_key)
                    )
                    if not args.get("refresh") and cached_result is not None:
                        return {"jsonrpc": "2.0", "id": request_id, "result": {
                            "content": [{"type": "text", "text": json.dumps(cached_result, ensure_ascii=False)}],
                            "structuredContent": cached_result, "isError": False}}

                result = target_adapter.dispatch(METHODS[name], args)
                if name == "project_context":
                    self._cached_contexts[cache_key] = result
                    if is_default_target:
                        self._cached_context = result
                elif name in {"append_evidence", "propose_fact", "record_note", "verify_completion"}:
                    for key in [k for k in self._cached_contexts if k[0] == cache_key[0]]:
                        del self._cached_contexts[key]
                    if is_default_target or cache_key[0] == getattr(getattr(self.adapter, "context", None), "project_path", None):
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
    serve_stdio(ProjectCompassMCPServer(adapter, allow_dynamic_project=not bool(args.base_url)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
