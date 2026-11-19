"""One-click MCP configuration generator and environment diagnostics.

Provides configuration templates for Claude Desktop, Cursor, and Antigravity,
allowing external agents to connect to Project Compass seamlessly.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import sysconfig
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TOKEN_ENV = "PROJECT_COMPASS_AGENT_TOKEN"
RULES_BEGIN_MARKER = "<!-- compass-mcp-rules:begin -->"
RULES_END_MARKER = "<!-- compass-mcp-rules:end -->"


def render_agent_rules_snippet(member_id: str = "developer") -> str:
    """Render concise Beads-style onboarding rules so coding agents reliably call Compass MCP."""
    owner = str(member_id or "developer").strip() or "developer"
    return "\n".join([
        RULES_BEGIN_MARKER,
        "## Compass MCP 实时协作守则",
        "",
        f"- **默认署名身份**：`{owner}`（所有记录与提案归入可追溯个人会话轨道，绝不篡改用户已定案基准）。",
        "- **开局与上下文压缩后先对齐基准**：开始新任务或经历长对话压缩后，先调用 `project_context(refresh=true)`；严格区分 `accepted_facts`（已拍板圣旨）与 `pending_proposals`（未拍板备选，严禁当作正式需求直接实现）。",
        "- **跨项目与多并发会话路由**：若通过全局 Compass MCP 服务处理多个仓库或并行会话，调用工具时请显式传入当前工作区路径 `project_path` 与当前会话标识 `session_id`，确保不同项目与并行会话各自隔离写入对应记忆目录并互不串线。",
        "- **思路分叉/未验证前提/坑位随时一步记账**：当讨论中出现关键目标、备选方案、待验证假设或待填坑位时，调用一步工具 `record_note(text=..., kind=\"decision|assumption|task|goal\", title=...)`，顺手把 `title` 浓缩成 **15~20 字人话短标题**。",
        "- **对话内零切屏预警**：若工具返回值中存在 `nudge_lines`，请在关键回复结尾简洁附带提醒，让用户无需切换浏览器即可感知偏离与遗漏。",
        "- **报完工前必过核对门禁**：准备告诉用户已完成前，必须调用 `verify_completion(summary=..., changed_files=...)` 核验改动证据、测试通过状态与遗留坑位。",
        RULES_END_MARKER,
    ])


def install_agent_rules(
    project_path: str | Path,
    *,
    member_id: str = "developer",
    filename: str = "AGENTS.md",
) -> Path:
    """Idempotently install or update Compass MCP workflow rules inside the target project's AGENTS.md."""
    root = Path(project_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    snippet = render_agent_rules_snippet(member_id=member_id)
    pattern = re.compile(
        re.escape(RULES_BEGIN_MARKER) + r".*?" + re.escape(RULES_END_MARKER),
        re.DOTALL,
    )
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if pattern.search(existing):
            updated = pattern.sub(lambda _m: snippet, existing, count=1)
        else:
            sep = "\n\n" if existing.strip() else ""
            updated = existing.rstrip() + sep + snippet + "\n"
    else:
        updated = snippet + "\n"
    target.write_text(updated, encoding="utf-8")
    return target


def _find_compass_mcp_executable() -> str | None:
    on_path = shutil.which("compass-mcp")
    if on_path:
        return on_path
    exe_name = "compass-mcp.exe" if sys.platform == "win32" else "compass-mcp"
    schemes = ["nt" if os.name == "nt" else "posix_prefix", "nt_user" if os.name == "nt" else "posix_user"]
    for scheme in schemes:
        try:
            scripts_dir = sysconfig.get_path("scripts", scheme=scheme)
        except KeyError:
            continue
        if scripts_dir:
            candidate = Path(scripts_dir) / exe_name
            if candidate.is_file():
                return str(candidate)
    return None


def generate_config(
    client: str = "claude",
    *,
    project_path: str | Path,
    base_url: str | None = DEFAULT_BASE_URL,
    member_id: str = "agent-collaborator",
    session_id: str = "session-mcp-01",
    python_path: str = "python",
    token_env: str = DEFAULT_TOKEN_ENV,
    zero_config: bool = False,
) -> dict[str, Any]:
    """Generate ready-to-use MCP configuration dictionary for the specified agent client."""
    client_key = (client or "claude").strip().lower()
    resolved_proj = str(Path(project_path).expanduser().resolve())
    compass_bin = _find_compass_mcp_executable() if (zero_config and python_path == "python") else None
    if compass_bin:
        command = compass_bin
        args: list[str] = []
    else:
        command = sys.executable if (zero_config and python_path == "python") else python_path
        args = ["-m", "project_compass.mcp_server"]
    env: dict[str, str] = {}
    if not zero_config and base_url:
        args.extend(["--base-url", base_url])
        env[token_env] = os.environ.get(token_env, "fill-your-token-here")
    args.extend([
        "--project-path",
        resolved_proj,
        "--member-id",
        member_id,
        "--session-id",
        session_id,
    ])
    server_entry: dict[str, Any] = {
        "command": command,
        "args": args,
    }
    if env:
        server_entry["env"] = env

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


def merge_mcp_servers_file(
    config_path: str | Path,
    server_name: str,
    server_entry: dict[str, Any],
) -> Path:
    """Safely insert or update a single entry inside an existing ``mcpServers`` JSON file."""
    target = Path(config_path).expanduser().resolve()
    payload: dict[str, Any] = {}
    if target.exists():
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"existing MCP config must be a JSON object: {target}")
        payload = loaded
    servers = payload.get("mcpServers")
    if servers is None:
        servers = {}
    elif not isinstance(servers, dict):
        raise ValueError(f"existing mcpServers field must be a JSON object: {target}")
    clean_entry = {
        key: value
        for key, value in server_entry.items()
        if key not in {"name", "protocol"}
    }
    updated_servers = dict(servers)
    updated_servers[server_name] = clean_entry
    payload["mcpServers"] = updated_servers
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


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
    elif client_key == "antigravity":
        return home / ".gemini" / "antigravity" / "mcp_config.json"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and diagnose Project Compass MCP configurations")
    parser.add_argument("--client", choices=["claude", "cursor", "antigravity"], default="claude", help="Target agent client")
    parser.add_argument("--project-path", default=".", help="Bound project root directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Dashboard base URL")
    parser.add_argument("--zero-config", action="store_true", help="Connect directly to local ProjectWorkspace without --base-url/token")
    parser.add_argument("--member-id", default="claude-agent", help="Agent member identity")
    parser.add_argument("--session-id", default="session-mcp-01", help="Agent session identity")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostic check")
    parser.add_argument("--write", action="store_true", help="Write configuration to default host path")
    parser.add_argument("--init-rules", action="store_true", help="Install or update Compass MCP onboarding rules in project AGENTS.md")
    parser.add_argument("--rules-file", default="AGENTS.md", help="Target instruction filename relative to --project-path")
    args = parser.parse_args(argv)

    if args.doctor:
        diag = diagnose_environment(args.project_path)
        print(json.dumps(diag, ensure_ascii=False, indent=2))
        return 0 if diag["healthy"] else 1

    if args.init_rules:
        rules_path = install_agent_rules(args.project_path, member_id=args.member_id, filename=args.rules_file)
        print(f"Successfully wrote Compass MCP rules to {rules_path}")
        if not args.write:
            return 0

    config = generate_config(
        args.client,
        project_path=args.project_path,
        base_url=None if args.zero_config else args.base_url,
        member_id=args.member_id,
        session_id=args.session_id,
        zero_config=args.zero_config,
    )

    if args.write:
        target_path = default_config_path(args.client)
        if target_path is None:
            print(f"Error: automatic config path unknown for client {args.client}", file=sys.stderr)
            return 2
        if args.client == "antigravity":
            merge_mcp_servers_file(target_path, "compass", config)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Successfully wrote {args.client} configuration to {target_path}")
        return 0

    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
