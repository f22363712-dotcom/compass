"""One-click MCP configuration generator and environment diagnostics.

Provides configuration templates for Claude Desktop, Cursor, and Antigravity,
allowing external agents to connect to Project Compass seamlessly.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import sysconfig
from typing import Any

from .team_templates import build_team_config, list_team_templates


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
        f"- **默认署名身份**：`{owner}`（所有记录与提案归入可追溯个人会话轨道，绝不篡改用户已确认事项）。",
        "- **开局与上下文压缩后先对齐基准**：开始新任务或经历长对话压缩后，先调用 `project_context(refresh=true)`；严格区分 `accepted_facts`（已确认事项）与 `pending_proposals`（待确认备选，严禁当作正式需求直接实现）。",
        "- **优先处理人工排队派活**：检查 `project_context` 返回的 `priority_dispatches`，若有未处理的人工排队派发事项应优先领走落地。",
        "- **跨项目与多并发会话路由**：若通过全局 Compass MCP 服务处理多个仓库或并行会话，调用工具时请显式传入当前工作区路径 `project_path` 与当前会话标识 `session_id`，确保不同项目与并行会话各自隔离写入对应记忆目录并互不串线。",
        "- **思路分叉/未验证前提/待办事项随时一步记账**：当讨论中出现关键目标、备选方案、待验证假设或待办事项时，调用一步工具 `record_note(text=..., kind=\"decision|assumption|task|goal\", title=...)`，顺手把 `title` 浓缩成 **15~20 字人话短标题**。",
        "- **日常静默随行与按需拉起看板**：常规问答与编码回合保持后台静默（仅调用 `project_context` / `record_note` 记账校对）；**仅当**用户显式触发 `/compass`、要求查看看板，或遇到待确认分歧 / `verify_completion` 门禁拦截时，才调用 `open_compass` 打开面板。",
        "- **对话内必带可点击看板直达链接**：若工具返回值中存在 `nudge_lines` 或 `board_action_markdown` 并提示用户查看或确认看板，回复中必须原样保留可点击入口（例如 `[打开 Compass 实时掌控台](sidecar://compass/compass_board/)` 或本地看板地址），若未返回链接则先调用 `open_compass` 获取入口，严禁只写“去看板点确认”而不给链接。",
        "- **报完工前必过核对门禁**：准备告诉用户已完成前，必须调用 `verify_completion(summary=..., changed_files=...)` 核验改动证据、测试通过状态与遗留待办。",
        RULES_END_MARKER,
    ])


def _ensure_gitignore_entry(root: Path, entry: str = ".project-memory/") -> None:
    """Idempotently ignore Compass's local workspace memory folder in the target repo .gitignore."""
    gitignore = root / ".gitignore"
    normalized = entry.strip().rstrip("/")
    if gitignore.exists():
        raw = gitignore.read_text(encoding="utf-8")
        existing_lines = {line.strip().rstrip("/") for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")}
        if normalized in existing_lines:
            return
        sep = "\n\n" if raw.strip() else ""
        if raw and not raw.endswith("\n") and not sep:
            sep = "\n"
        gitignore.write_text(raw.rstrip() + sep + "# Project Compass local memory\n" + entry.strip() + "\n", encoding="utf-8")
    else:
        gitignore.write_text("# Project Compass local memory\n" + entry.strip() + "\n", encoding="utf-8")


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
    _ensure_gitignore_entry(root, ".project-memory/")
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
    elif client_key == "codex":
        return {
            "mcp_servers": {
                "compass": server_entry,
            },
            "format": "toml",
            "toml": _format_codex_toml("compass", server_entry),
        }
    elif client_key == "hermes":
        return {
            "mcp_servers": {
                "compass": server_entry,
            },
            "format": "yaml",
            "yaml": _format_hermes_yaml("compass", server_entry),
        }
    else:
        raise ValueError(f"unsupported MCP client: {client}. Choose from 'claude', 'cursor', 'antigravity', 'codex', 'hermes'")


def _toml_quote(value: str) -> str:
    return json.dumps(str(value))


def _format_codex_toml(server_name: str, server_entry: dict[str, Any]) -> str:
    lines = [
        f"[mcp_servers.{server_name}]",
        f"command = {_toml_quote(server_entry['command'])}",
        "args = [" + ", ".join(_toml_quote(a) for a in server_entry.get("args", [])) + "]",
    ]
    env_map = server_entry.get("env")
    if isinstance(env_map, dict) and env_map:
        lines.append("")
        lines.append(f"[mcp_servers.{server_name}.env]")
        for k, v in env_map.items():
            lines.append(f"{k} = {_toml_quote(v)}")
    return "\n".join(lines) + "\n"


def _format_hermes_yaml(server_name: str, server_entry: dict[str, Any], *, indent: int = 2) -> str:
    pad = " " * max(2, int(indent))
    child_pad = pad + "  "
    grand_pad = child_pad + "  "
    lines = [
        f"{pad}# compass-mcp:begin {server_name}",
        f"{pad}{server_name}:",
        f"{child_pad}command: {_toml_quote(server_entry['command'])}",
        f"{child_pad}args:",
    ]
    for arg in server_entry.get("args", []):
        lines.append(f"{grand_pad}- {_toml_quote(arg)}")
    env_map = server_entry.get("env")
    if isinstance(env_map, dict) and env_map:
        lines.append(f"{child_pad}env:")
        for k, v in env_map.items():
            lines.append(f"{grand_pad}{k}: {_toml_quote(v)}")
    lines.append(f"{pad}# compass-mcp:end {server_name}")
    return "\n".join(lines) + "\n"


def merge_codex_toml_file(
    config_path: str | Path,
    server_name: str,
    server_entry: dict[str, Any],
) -> Path:
    """Safely insert or update a single ``[mcp_servers.<name>]`` section in Codex config.toml."""
    target = Path(config_path).expanduser().resolve()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    section_re = re.compile(
        rf"(?ms)^\[mcp_servers\.{re.escape(server_name)}(?:\.[^.\]\r\n]+)*\]\r?\n.*?(?=^\[|\Z)"
    )
    cleaned = section_re.sub("", existing).rstrip()
    block = _format_codex_toml(server_name, server_entry).strip()
    updated = (cleaned + "\n\n" + block + "\n") if cleaned else (block + "\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return target


def merge_hermes_yaml_file(
    config_path: str | Path,
    server_name: str,
    server_entry: dict[str, Any],
) -> Path:
    """Safely insert or update a single entry under ``mcp_servers:`` in Hermes config.yaml."""
    target = Path(config_path).expanduser().resolve()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = existing.replace("\r\n", "\n").splitlines()

    header_re = re.compile(r"^mcp_servers:[ \t]*(?:\{\}[ \t]*)?(#.*)?$")
    hdr_idx = next((idx for idx, line in enumerate(lines) if header_re.match(line)), None)

    if hdr_idx is None:
        base_lines = list(lines)
        while base_lines and not base_lines[-1].strip():
            base_lines.pop()
        new_block = ["mcp_servers:", *_format_hermes_yaml(server_name, server_entry, indent=2).splitlines()]
        merged_lines = ([*base_lines, "", *new_block] if base_lines else new_block)
        updated = "\n".join(merged_lines) + "\n"
    else:
        hdr_match = header_re.match(lines[hdr_idx])
        comment_suffix = f" {hdr_match.group(1)}" if (hdr_match and hdr_match.group(1)) else ""
        updated_hdr = f"mcp_servers:{comment_suffix}"

        sec_end = len(lines)
        for idx in range(hdr_idx + 1, len(lines)):
            line = lines[idx]
            if line.strip() == "" or line.startswith((" ", "\t")):
                continue
            sec_end = idx
            break
        while sec_end > hdr_idx + 1 and not lines[sec_end - 1].strip():
            sec_end -= 1

        block = lines[hdr_idx + 1 : sec_end]

        child_indent = 2
        for line in block:
            m_child = re.match(r"^([ ]+)([^#\s-][^:]*):", line)
            if m_child:
                child_indent = len(m_child.group(1))
                break

        begin_marker = f"# compass-mcp:begin {server_name}"
        end_marker = f"# compass-mcp:end {server_name}"
        entry_re = re.compile(rf"^([ ]+){re.escape(server_name)}:[ \t]*(?:#.*)?$")

        cleaned_block: list[str] = []
        in_marker = False
        removing_entry_indent: int | None = None
        for line in block:
            stripped = line.strip()
            if stripped == begin_marker:
                in_marker = True
                removing_entry_indent = None
                continue
            if in_marker:
                if stripped == end_marker:
                    in_marker = False
                continue
            if removing_entry_indent is not None:
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    lead = len(line) - len(line.lstrip(" "))
                    if lead > removing_entry_indent:
                        continue
                else:
                    lead = len(line) - len(line.lstrip(" "))
                    if lead > removing_entry_indent:
                        continue
                removing_entry_indent = None
            m_entry = entry_re.match(line)
            if m_entry:
                removing_entry_indent = len(m_entry.group(1))
                continue
            cleaned_block.append(line)

        while cleaned_block and not cleaned_block[-1].strip():
            cleaned_block.pop()

        new_entry = _format_hermes_yaml(server_name, server_entry, indent=child_indent).splitlines()
        merged_lines = [
            *lines[:hdr_idx],
            updated_hdr,
            *cleaned_block,
            *new_entry,
            *lines[sec_end:],
        ]
        while merged_lines and not merged_lines[-1].strip():
            merged_lines.pop()
        updated = ("\n".join(merged_lines) + "\n") if merged_lines else ""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(updated, encoding="utf-8")
    return target


def install_antigravity_plugin(
    project_path: str | Path,
    *,
    home: Path | None = None,
    python_executable: str | None = None,
) -> dict[str, str]:
    """Install the packaged Compass Antigravity Sidecar plugin & skill under ~/.gemini/config/."""
    bundle_root = Path(__file__).resolve().parent / "antigravity_plugin" / "compass"
    if not bundle_root.is_dir():
        raise FileNotFoundError(f"packaged Antigravity plugin bundle missing: {bundle_root}")
    base_home = Path(home).expanduser() if home is not None else Path.home()
    target_plugin = (base_home / ".gemini" / "config" / "plugins" / "compass").resolve()
    resolved_proj = str(Path(project_path).expanduser().resolve())

    for src_path in sorted(bundle_root.rglob("*")):
        if src_path.is_dir() or "__pycache__" in src_path.parts:
            continue
        rel = src_path.relative_to(bundle_root)
        dest_path = target_plugin / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(src_path.read_bytes())

    runtime_cfg_path = target_plugin / "sidecars" / "compass_board" / "runtime_config.json"
    runtime_cfg = {
        "python": str(python_executable or sys.executable),
        "pythonpath": str(Path(__file__).resolve().parents[1]),
        "default_project_path": resolved_proj,
    }
    runtime_cfg_path.write_text(json.dumps(runtime_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Sync the global /compass slash skill alongside the plugin copy.
    skill_src = bundle_root / "skills" / "compass" / "SKILL.md"
    global_skill_path = (base_home / ".gemini" / "config" / "skills" / "compass" / "SKILL.md").resolve()
    if skill_src.is_file():
        global_skill_path.parent.mkdir(parents=True, exist_ok=True)
        global_skill_path.write_bytes(skill_src.read_bytes())

    return {
        "plugin_dir": str(target_plugin),
        "sidecar_manifest": str(target_plugin / "sidecars" / "compass_board" / "sidecar.json"),
        "runtime_config_path": str(runtime_cfg_path),
        "skill_path": str(global_skill_path),
    }


def merge_mcp_servers_file(
    config_path: str | Path,
    server_name: str,
    server_entry: dict[str, Any],
) -> Path:
    """Safely insert or update a single entry inside an existing ``mcpServers`` JSON file."""
    target = Path(config_path).expanduser().resolve()
    payload: dict[str, Any] = {}
    if target.exists():
        raw_text = target.read_text(encoding="utf-8").strip()
        if raw_text:
            loaded = json.loads(raw_text)
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

    # 4. compass-mcp console entrypoint check (optional)
    mcp_bin = _find_compass_mcp_executable()
    checks.append({
        "name": "compass_mcp_cli",
        "passed": bool(mcp_bin),
        "optional": True,
        "detail": mcp_bin or "compass-mcp script not on PATH (python -m project_compass.mcp_server still works)",
    })

    # 5. Node.js availability for Antigravity sidecar / browser tests (optional)
    node_bin = shutil.which("node")
    checks.append({
        "name": "node_runtime",
        "passed": bool(node_bin),
        "optional": True,
        "detail": node_bin or "node not detected in PATH (optional unless using Antigravity Sidecar)",
    })

    # 6. Antigravity Sidecar plugin installation (optional)
    sidecar_manifest = Path.home() / ".gemini" / "config" / "plugins" / "compass" / "plugin.json"
    checks.append({
        "name": "antigravity_sidecar_plugin",
        "passed": sidecar_manifest.is_file(),
        "optional": True,
        "detail": str(sidecar_manifest) if sidecar_manifest.is_file() else "Sidecar plugin not installed (web browser UI fallback still works)",
    })

    # 7. Token environment variable check (optional in --zero-config mode)
    has_token = bool(os.environ.get(DEFAULT_TOKEN_ENV))
    checks.append({
        "name": "agent_token_env",
        "passed": has_token,
        "optional": True,
        "detail": f"{DEFAULT_TOKEN_ENV} is set" if has_token else f"{DEFAULT_TOKEN_ENV} not set (not needed for --zero-config)",
    })

    required_checks = {"python_version", "project_directory", "compass_package"}
    all_passed = all(c["passed"] for c in checks if c["name"] in required_checks)
    return {
        "healthy": all_passed,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        modern = home / ".gemini" / "config" / "mcp_config.json"
        if modern.parent.is_dir():
            return modern
        return home / ".gemini" / "antigravity" / "mcp_config.json"
    elif client_key == "codex":
        return home / ".codex" / "config.toml"
    elif client_key == "hermes":
        return home / ".hermes" / "config.yaml"
    return None


def _parse_role_seat(spec: str) -> dict[str, str]:
    parts = str(spec or "").split(":", 2)
    if len(parts) < 2:
        raise ValueError(f"invalid --role-seat '{spec}'; expected 'member_id:role_label:role_brief'")
    member_id = parts[0].strip()
    role_label = parts[1].strip()
    role_brief = parts[2].strip() if len(parts) == 3 else ""
    if not member_id or not role_label:
        raise ValueError(f"invalid --role-seat '{spec}'; member_id and role_label cannot be blank")
    seat = {"member_id": member_id, "role_label": role_label}
    if role_brief:
        seat["role_brief"] = role_brief
    return seat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and diagnose Project Compass MCP configurations")
    parser.add_argument("--client", choices=["claude", "cursor", "antigravity", "codex", "hermes"], default="claude", help="Target agent client")
    parser.add_argument("--project-path", default=".", help="Bound project root directory")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Dashboard base URL")
    parser.add_argument("--zero-config", action="store_true", help="Connect directly to local ProjectWorkspace without --base-url/token")
    parser.add_argument("--member-id", default="claude-agent", help="Agent member identity")
    parser.add_argument("--session-id", default="session-mcp-01", help="Agent session identity")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostic check")
    parser.add_argument("--write", action="store_true", help="Write configuration to default host path")
    parser.add_argument("--init-rules", action="store_true", help="Install or update Compass MCP onboarding rules in project AGENTS.md")
    parser.add_argument("--rules-file", default="AGENTS.md", help="Target instruction filename relative to --project-path")
    parser.add_argument("--list-templates", action="store_true", help="List available built-in solo and team role templates")
    parser.add_argument("--team-template", help="Generate clean JSON config skeleton for a team template (or 'custom')")
    parser.add_argument("--owner-id", default=None, help="Optional project owner ID override for --team-template")
    parser.add_argument(
        "--role-seat",
        action="append",
        default=[],
        help="Repeatable seat override in 'member_id:role_label:role_brief' format (used with --team-template)",
    )
    args = parser.parse_args(argv)

    if args.list_templates:
        print(json.dumps({"templates": list_team_templates()}, ensure_ascii=False, indent=2))
        return 0

    if args.role_seat and not args.team_template:
        print("Error: --role-seat requires --team-template", file=sys.stderr)
        return 2

    if args.team_template:
        try:
            custom_seats = [_parse_role_seat(item) for item in args.role_seat] if args.role_seat else None
            team_cfg = build_team_config(
                args.team_template,
                args.project_path,
                owner_id=args.owner_id,
                custom_seats=custom_seats,
                base_url=args.base_url,
                client=args.client,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(team_cfg, ensure_ascii=False, indent=2))
        return 0

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
            plugin_info = install_antigravity_plugin(args.project_path)
            print(f"Successfully wrote {args.client} configuration to {target_path}")
            print(f"Successfully installed Antigravity sidecar plugin to {plugin_info['plugin_dir']}")
            return 0
        if args.client == "codex":
            merge_codex_toml_file(target_path, "compass", config["mcp_servers"]["compass"])
        elif args.client == "hermes":
            merge_hermes_yaml_file(target_path, "compass", config["mcp_servers"]["compass"])
        else:
            servers_map = config.get("mcpServers") if isinstance(config, dict) else None
            if isinstance(servers_map, dict) and "project-compass" in servers_map:
                merge_mcp_servers_file(target_path, "project-compass", servers_map["project-compass"])
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Successfully wrote {args.client} configuration to {target_path}")
        return 0

    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
