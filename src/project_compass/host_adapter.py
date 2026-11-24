"""Cross-agent MCP host detection, GUI/SSH environment probing, and single-instance web daemon helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen
import webbrowser


_VALID_TIERS = frozenset({
    "antigravity_sidecar",
    "ide_builtin_browser",
    "external_browser",
    "headless_terminal",
    "mcp_app_inline",
})
_IDE_BUILTIN_BROWSER_MARKERS = (
    "codex",
    "cursor",
    "windsurf",
    "vscode",
    "visual studio code",
    "cline",
    "roo",
    "trae",
    "zed",
)
_MCP_APP_CLIENT_NAMES = frozenset({"claude-ai", "claude-desktop", "claude ai", "claude desktop"})
_LIVE_SERVER_FILENAME = "live_web_server.json"


def parse_workspace_uri(raw: str | Path) -> Path:
    """Resolve either a local directory path or a file:// URI (POSIX/Windows) into a canonical Path."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("workspace path cannot be empty")
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        path_part = unquote(parsed.path or "")
        netloc = unquote(parsed.netloc or "")
        if netloc and netloc.lower() != "localhost":
            raise ValueError(f"remote workspace URI not supported: {text}")
        if (sys.platform == "win32" or re.match(r"^/[A-Za-z]:", path_part)) and re.match(r"^/[A-Za-z]:", path_part):
            local_path = path_part[1:]
        else:
            local_path = path_part
        if not local_path:
            raise ValueError(f"invalid workspace URI: {text}")
        return Path(local_path).expanduser().resolve()
    return Path(text).expanduser().resolve()


def has_local_gui_display(
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> bool:
    """Return True when the current host appears to be an interactive local desktop session."""
    env_map = os.environ if env is None else env
    plat = (sys.platform if platform is None else str(platform)).strip().lower()
    if str(env_map.get("SSH_CONNECTION") or "").strip() or str(env_map.get("SSH_TTY") or "").strip():
        return False
    if str(env_map.get("COMPASS_HEADLESS") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(env_map.get("CI") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    if str(env_map.get("SAMPLE_MODE") or "").strip().lower() == "true":
        return False
    if plat.startswith("win") or plat == "darwin":
        return True
    return bool(str(env_map.get("DISPLAY") or "").strip() or str(env_map.get("WAYLAND_DISPLAY") or "").strip())


def is_antigravity_sidecar_installed(home: Path | None = None) -> bool:
    """Return True if the Compass Antigravity auxiliary-pane sidecar manifest exists on disk."""
    base = Path(home).expanduser() if home is not None else Path.home()
    candidates = (
        base / ".gemini" / "config" / "plugins" / "compass" / "sidecars" / "compass_board" / "sidecar.json",
        base / ".gemini" / "config" / "sidecars" / "compass_board" / "sidecar.json",
    )
    return any(path.is_file() for path in candidates)


def _supports_mcp_app_extension(capabilities: dict[str, Any] | None) -> bool:
    if not isinstance(capabilities, dict):
        return False
    for container_key in ("extensions", "experimental"):
        container = capabilities.get(container_key)
        if isinstance(container, dict) and "io.modelcontextprotocol/ui" in container:
            return True
    return False


def detect_host_profile(
    client_info: dict[str, Any] | None = None,
    capabilities: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Classify the connected MCP host into one of four UI delivery profiles."""
    env_map = os.environ if env is None else env
    client_name_raw = str((client_info or {}).get("name") or "").strip()
    client_name = client_name_raw.lower()
    client_version = str((client_info or {}).get("version") or "").strip()
    sidecar_installed = is_antigravity_sidecar_installed(home)
    has_gui = has_local_gui_display(env_map, platform=platform)
    supports_mcp_app = _supports_mcp_app_extension(capabilities)

    override = str(env_map.get("COMPASS_HOST_KIND") or "").strip().lower()
    has_antigravity_env = any(
        str(env_map.get(var) or "").strip()
        for var in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_EXECUTABLE_DATA_DIR", "ANTIGRAVITY_AGENTAPI_EXE")
    )
    if override in _VALID_TIERS:
        tier = override
        reason = "override:COMPASS_HOST_KIND"
    elif "antigravity" in client_name:
        if sidecar_installed:
            tier = "antigravity_sidecar"
            reason = "antigravity host with installed sidecar"
        else:
            tier = "ide_builtin_browser" if has_gui else "headless_terminal"
            reason = "antigravity host fallback (sidecar not installed)"
    elif supports_mcp_app or client_name in _MCP_APP_CLIENT_NAMES:
        tier = "mcp_app_inline"
        reason = "mcp-app UI extension host"
    elif any(marker in client_name for marker in _IDE_BUILTIN_BROWSER_MARKERS):
        if has_gui:
            tier = "ide_builtin_browser"
            reason = f"IDE built-in preview host ({client_name})"
        else:
            tier = "headless_terminal"
            reason = f"headless IDE session ({client_name})"
    elif has_antigravity_env and (not client_name or client_name in {"unknown", "mcp-client"}):
        if sidecar_installed:
            tier = "antigravity_sidecar"
            reason = "antigravity host with installed sidecar"
        else:
            tier = "ide_builtin_browser" if has_gui else "headless_terminal"
            reason = "antigravity host fallback (sidecar not installed)"
    else:
        tier = "external_browser" if has_gui else "headless_terminal"
        reason = (
            f"local desktop terminal host ({client_name or 'unknown'})"
            if has_gui
            else f"headless terminal host ({client_name or 'unknown'})"
        )

    profile: dict[str, Any] = {
        "tier": tier,
        "reason": reason,
        "client_name": client_name_raw or "unknown",
        "client_version": client_version,
        "sidecar_installed": sidecar_installed,
        "has_gui": has_gui,
        "supports_mcp_app": supports_mcp_app,
    }
    if tier == "antigravity_sidecar":
        profile["sidecar_uri"] = "sidecar://compass/compass_board/"
    elif tier == "mcp_app_inline":
        profile["resource_uri"] = "ui://compass/workbench.html"
    return profile


def _probe_health(port: int, *, timeout: float = 0.5) -> dict[str, Any] | None:
    if port <= 0:
        return None
    req = Request(f"http://127.0.0.1:{port}/api/health", method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("ok") is True:
                return payload
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None
    return None


def _activate_daemon_project(port: int, project_path: Path, *, timeout: float = 2.0) -> bool:
    req = Request(
        f"http://127.0.0.1:{port}/api/projects/activate",
        data=json.dumps({"project_path": str(project_path)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (OSError, URLError, ValueError):
        return False


def _port_has_listener(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.12):
            return True
    except OSError:
        return False


def _pick_free_port(preferred_port: int = 8787) -> int:
    candidates = list(range(int(preferred_port), int(preferred_port) + 13))
    for port in candidates:
        if port <= 0 or port > 65535:
            continue
        if _port_has_listener(port):
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_live_server_marker(ws_root: Path, *, port: int, pid: int, project_path: Path) -> None:
    ws_root.mkdir(parents=True, exist_ok=True)
    marker = ws_root / _LIVE_SERVER_FILENAME
    tmp_path = marker.with_suffix(f".json.tmp.{os.getpid()}")
    payload = {
        "pid": pid,
        "port": port,
        "url": f"http://127.0.0.1:{port}/",
        "project_path": str(project_path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, marker)


def read_live_server_url(
    project_path: str | Path,
    *,
    workspace_root: Path | None = None,
) -> str | None:
    """Return the URL of a healthy running web dashboard daemon for ``project_path``, or None."""
    try:
        target_root = parse_workspace_uri(project_path)
    except ValueError:
        return None
    ws_root = Path(workspace_root).expanduser().resolve() if workspace_root else (target_root / ".project-memory")
    marker = ws_root / _LIVE_SERVER_FILENAME
    if not marker.is_file():
        return None
    try:
        saved = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict):
        return None
    port = int(saved.get("port") or 0)
    if port <= 0 or _probe_health(port, timeout=0.25) is None:
        return None
    return f"http://127.0.0.1:{port}/"


def ensure_project_web_daemon(
    project_path: str | Path,
    *,
    preferred_port: int = 8787,
    workspace_root: Path | None = None,
    sample_mode: bool = False,
    env: Mapping[str, str] | None = None,
    idle_timeout: int = 21600,
) -> dict[str, Any]:
    """Ensure a single-instance background web dashboard serves ``project_path`` without duplicates."""
    env_map = os.environ if env is None else env
    if (
        sample_mode
        or str(env_map.get("SAMPLE_MODE") or "").strip().lower() == "true"
        or str(env_map.get("COMPASS_DISABLE_WEB_DAEMON") or "").strip().lower() in {"1", "true", "yes"}
    ):
        return {
            "started": False,
            "reused": False,
            "url": None,
            "port": None,
            "pid": None,
            "reason": "disabled_or_sample",
        }

    target_root = parse_workspace_uri(project_path)
    if not target_root.exists() or not target_root.is_dir():
        raise ValueError(f"project directory does not exist: {target_root}")
    ws_root = Path(workspace_root).expanduser().resolve() if workspace_root else (target_root / ".project-memory")
    marker = ws_root / _LIVE_SERVER_FILENAME

    # 1. Reuse existing marker server if alive.
    if marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            saved = None
        if isinstance(saved, dict):
            saved_port = int(saved.get("port") or 0)
            health = _probe_health(saved_port, timeout=0.5)
            if health is not None and not health.get("sample_mode"):
                running_proj = str(health.get("project_path") or "")
                try:
                    same_proj = bool(running_proj and Path(running_proj).resolve() == target_root)
                except OSError:
                    same_proj = False
                switched_ok = same_proj or _activate_daemon_project(saved_port, target_root)
                if switched_ok:
                    return {
                        "started": False,
                        "reused": True,
                        "url": f"http://127.0.0.1:{saved_port}/",
                        "port": saved_port,
                        "pid": health.get("pid") or saved.get("pid"),
                        "project_path": str(target_root),
                    }

    # 2. Reuse a manually started dashboard already serving this exact project on preferred_port.
    pref_health = _probe_health(int(preferred_port), timeout=0.5)
    if pref_health is not None and not pref_health.get("sample_mode"):
        running_proj = str(pref_health.get("project_path") or "")
        try:
            if running_proj and Path(running_proj).resolve() == target_root:
                return {
                    "started": False,
                    "reused": True,
                    "url": f"http://127.0.0.1:{int(preferred_port)}/",
                    "port": int(preferred_port),
                    "pid": pref_health.get("pid"),
                    "project_path": str(target_root),
                }
        except OSError:
            pass

    # 3. Spawn bounded idle-auto-exit daemon on an available loopback port.
    chosen_port = _pick_free_port(preferred_port)
    src_root = str(Path(__file__).resolve().parents[1])
    child_env = dict(os.environ)
    child_env.update({k: str(v) for k, v in env_map.items()})
    existing_pp = child_env.get("PYTHONPATH", "")
    pp_parts = [p for p in existing_pp.split(os.pathsep) if p]
    if src_root not in pp_parts:
        child_env["PYTHONPATH"] = os.pathsep.join([src_root, *pp_parts]) if pp_parts else src_root

    cmd = [
        sys.executable,
        "-m",
        "project_compass.sidecar_backend",
        "--daemon",
        "--project-path",
        str(target_root),
        "--workspace-root",
        str(ws_root),
        "--port",
        str(chosen_port),
        "--idle-timeout",
        str(max(10, int(idle_timeout))),
    ]
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": child_env,
        "close_fds": True,
    }
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    deadline = time.monotonic() + 8.0
    ready_health: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        ready_health = _probe_health(chosen_port, timeout=0.35)
        if ready_health is not None:
            break
        time.sleep(0.06)

    if ready_health is None:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            if marker.is_file():
                saved = json.loads(marker.read_text(encoding="utf-8"))
                if int(saved.get("pid") or 0) == proc.pid:
                    marker.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {
            "started": False,
            "reused": False,
            "url": None,
            "port": chosen_port,
            "pid": proc.pid,
            "reason": "daemon_start_timeout",
        }

    _write_live_server_marker(ws_root, port=chosen_port, pid=int(ready_health.get("pid") or proc.pid), project_path=target_root)
    return {
        "started": True,
        "reused": False,
        "url": f"http://127.0.0.1:{chosen_port}/",
        "port": chosen_port,
        "pid": int(ready_health.get("pid") or proc.pid),
        "project_path": str(target_root),
    }


def deliver_ui_for_host(
    project_path: str | Path,
    *,
    client_info: dict[str, Any] | None = None,
    capabilities: dict[str, Any] | None = None,
    preferred_port: int = 8787,
    workspace_root: Path | None = None,
    sample_mode: bool = False,
    open_browser: bool | None = None,
    allow_daemon: bool = False,
    opened_urls: set[str] | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Select the host-appropriate dashboard surface and ensure backing services only when triggered."""
    env_map = os.environ if env is None else env
    profile = detect_host_profile(
        client_info,
        capabilities,
        env=env_map,
        home=home,
        platform=platform,
    )
    tier = profile["tier"]

    if tier == "antigravity_sidecar":
        return {
            **profile,
            "dashboard_url": None,
            "port": None,
            "browser_opened": False,
            "daemon_reused": False,
            "user_action_hint": "点击聊天中的 Compass 胶囊按钮或右侧副栏图标，即可零秒展开完整主看板并与左侧会话联动。",
        }

    if tier == "mcp_app_inline":
        return {
            **profile,
            "dashboard_url": None,
            "port": None,
            "browser_opened": False,
            "daemon_reused": False,
            "user_action_hint": "已在宿主内嵌 MCP App 工作台中渲染当前项目看板。",
        }

    daemon_info: dict[str, Any]
    if allow_daemon:
        daemon_info = ensure_project_web_daemon(
            project_path,
            preferred_port=preferred_port,
            workspace_root=workspace_root,
            sample_mode=sample_mode,
            env=env_map,
        )
    else:
        daemon_info = {
            "started": False,
            "reused": False,
            "url": None,
            "port": None,
            "pid": None,
            "reason": "daemon_deferred",
        }

    url = daemon_info.get("url")
    port = daemon_info.get("port")
    daemon_pid = daemon_info.get("pid")
    if tier == "ide_builtin_browser":
        return {
            **profile,
            "dashboard_url": url,
            "port": port,
            "daemon_pid": daemon_pid,
            "daemon_started": bool(daemon_info.get("started")),
            "daemon_reused": bool(daemon_info.get("reused")),
            "browser_opened": False,
            "user_action_hint": (
                f"请在右侧内置预览浏览器打开 {url} 查看完整主看板；工作区定案后可直接写入优先执行列表。"
                if url
                else "后台本地网页看板未启动（当前为只读/样例或受限测试模式）。"
            ),
        }

    if tier == "external_browser":
        auto_allowed = open_browser if open_browser is not None else (str(env_map.get("COMPASS_AUTO_OPEN_BROWSER") or "1").strip() != "0")
        already_opened = bool(url and opened_urls is not None and url in opened_urls)
        opened = False
        if url and auto_allowed and not already_opened:
            try:
                opened = bool(webbrowser.open(url, new=2))
            except Exception:
                opened = False
            if opened and opened_urls is not None:
                opened_urls.add(url)
        return {
            **profile,
            "dashboard_url": url,
            "port": port,
            "daemon_pid": daemon_pid,
            "daemon_started": bool(daemon_info.get("started")),
            "daemon_reused": bool(daemon_info.get("reused")),
            "browser_opened": opened,
            "user_action_hint": (
                f"已为你保留本机完整主看板地址 {url}" + ("，并已在系统默认浏览器中打开；可拖至屏幕右侧伴随查看。" if opened else "，请在系统浏览器打开查看。")
                if url
                else "当前处于只读或受限环境，已保留完整四行状态纪要。"
            ),
        }

    # headless_terminal
    forward_port = int(port or preferred_port)
    ssh_hint = f"ssh -L {forward_port}:127.0.0.1:{forward_port} <user@host>"
    return {
        **profile,
        "dashboard_url": url,
        "port": port,
        "daemon_pid": daemon_pid,
        "daemon_started": bool(daemon_info.get("started")),
        "daemon_reused": bool(daemon_info.get("reused")),
        "browser_opened": False,
        "ssh_port_forward_hint": ssh_hint,
        "user_action_hint": (
            f"检测到无图形桌面环境（如远程 SSH/CLI），本地看板监听在 {url}；可在本地终端执行 `{ssh_hint}` 后访问 http://127.0.0.1:{forward_port}/ ，或直接阅读下方四行文字纪要。"
            if url
            else "当前为无图形桌面/受限终端环境，以下提供完整四行文字状态纪要。"
        ),
    }
