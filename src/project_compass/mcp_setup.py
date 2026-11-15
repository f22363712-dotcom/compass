"""One-click MCP configuration generator and environment diagnostics.

Provides configuration templates for Claude Desktop, Cursor, and Antigravity,
allowing external agents to connect to Project Compass seamlessly.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TOKEN_ENV = "PROJECT_COMPASS_AGENT_TOKEN"


def generate_config(
    client: str = "claude",
    *,
    project_path: str | Path,
    base_url: str = DEFAULT_BASE_URL,
    member_id: str = "agent-collaborator",
    session_id: str = "session-mcp-01",
    python_path: str = "python",
    token_env: str = DEFAULT_TOKEN_ENV,
) -> dict[str, Any]:
    """Generate ready-to-use MCP configuration dictionary for the specified agent client."""
    client_key = (client or "claude").strip().lower()
    resolved_proj = str(Path(project_path).expanduser().resolve())

    server_entry = {
        "command": python_path,
        "args": [
            "-m",
            "project_compass.mcp_server",
            "--base-url",
            base_url,
            "--project-path",
            resolved_proj,
            "--member-id",
            member_id,
            "--session-id",
            session_id,
        ],
        "env": {
            token_env: os.environ.get(token_env, "fill-your-token-here"),
        },
    }

    if client_key in {"claude", "cursor"}:
        return {
            "mcpServers": {
                "project-compass": server_entry,
            }
        }
    elif client_key == "antigravity":
        return {
            "name": "project-compass",
            "protocol": "mcp-stdio",
            **server_entry,
        }
    else:
        raise ValueError(f"unsupported MCP client: {client}. Choose from 'claude', 'cursor', 'antigravity'")


def diagnose_environment(project_path: str | Path | None = None) -> dict[str, Any]:
    """Run an automated environment audit for MCP and multi-agent readiness."""
    checks: list[dict[str, Any]] = []

    # 1. Python version check
    py_ver = sys.version_info
    py_ok = (py_ver.major, py_ver.minor) >= (3, 10)
    checks.append({
        "name": "python_version",
        "passed": py_ok,
        "detail": f"{sys.version.split()[0]} (required >= 3.10)",
    })

    # 2. Project path validation
    target_path = Path(project_path or ".").expanduser().resolve()
    path_exists = target_path.is_dir()
    checks.append({
        "name": "project_directory",
        "passed": path_exists,
        "detail": str(target_path),
    })

    # 3. Project Compass package presence
    has_package = (target_path / "src" / "project_compass").is_dir() or (Path(__file__).parent).is_dir()
    checks.append({
        "name": "compass_package",
        "passed": bool(has_package),
        "detail": "found src/project_compass package",
    })

    # 4. Token environment variable check
    has_token = bool(os.environ.get(DEFAULT_TOKEN_ENV))
    checks.append({
        "name": "agent_token_env",
        "passed": has_token,
        "detail": f"{DEFAULT_TOKEN_ENV} is set" if has_token else f"{DEFAULT_TOKEN_ENV} not detected in environment",
    })

    all_passed = all(c["passed"] for c in checks if c["name"] != "agent_token_env")
    return {
        "healthy": all_passed,
        "checks": checks,
        "timestamp": Path().resolve().name,
    }


def default_config_path(client: str) -> Path | None:
    """Return default client configuration path on host system."""
    client_key = client.strip().lower()
    home = Path.home()
    if client_key == "claude":
        if sys.platform == "win32":
            return home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
        elif sys.platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        else:
            return home / ".config" / "Claude" / "claude_desktop_config.json"
    elif client_key == "cursor":
        return Path(".cursor") / "mcp.json"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and diagnose Project Compass MCP configurations")
    parser.add_argument("--client", choices=["claude", "cursor", "antigravity"], default="claude", help="Target agent client")
    parser.add_argument("--project-path", default=".", help="Bound project root directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Dashboard base URL")
    parser.add_argument("--member-id", default="claude-agent", help="Agent member identity")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostic check")
    parser.add_argument("--write", action="store_true", help="Write configuration to default host path")
    args = parser.parse_args(argv)

    if args.doctor:
        diag = diagnose_environment(args.project_path)
        print(json.dumps(diag, ensure_ascii=False, indent=2))
        return 0 if diag["healthy"] else 1

    config = generate_config(
        args.client,
        project_path=args.project_path,
        base_url=args.base_url,
        member_id=args.member_id,
    )

    if args.write:
        target_path = default_config_path(args.client)
        if target_path is None:
            print(f"Error: automatic config path unknown for client {args.client}", file=sys.stderr)
            return 2
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Successfully wrote {args.client} configuration to {target_path}")
        return 0

    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
