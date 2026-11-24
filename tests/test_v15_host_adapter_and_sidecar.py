"""Integration & unit tests for cross-agent MCP host routing, single-instance web daemon, and Antigravity sidecar."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from project_compass.host_adapter import (
    deliver_ui_for_host,
    detect_host_profile,
    ensure_project_web_daemon,
    has_local_gui_display,
    parse_workspace_uri,
)
from project_compass.local_plugin import WorkspaceMCPAdapter
from project_compass.mcp_server import ProjectCompassMCPServer
from project_compass.mcp_setup import (
    default_config_path,
    generate_config,
    install_antigravity_plugin,
    main as setup_main,
)
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_workspace import ProjectWorkspace
from project_compass.sample_data import sample_events
from project_compass.web_server import create_dashboard_server


def _terminate_pid(pid: int | None) -> None:
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=5)
        else:
            os.kill(int(pid), 15)
    except Exception:
        pass


class HostAdapterAndSidecarTests(unittest.TestCase):
    def test_parse_workspace_uri_handles_windows_and_posix_uris(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolved = Path(tmp).resolve()
            posix_uri = "file:///" + str(resolved).replace("\\", "/").lstrip("/")
            self.assertEqual(parse_workspace_uri(posix_uri), resolved)
            self.assertEqual(parse_workspace_uri(str(resolved)), resolved)

    def test_detect_host_profile_across_four_tiers_and_ssh_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            clean_env = {"PATH": os.environ.get("PATH", "")}

            # 1a. Antigravity without plugin installed yet -> graceful ide_builtin_browser fallback
            prof_ag_no_plugin = detect_host_profile(
                {"name": "antigravity", "version": "2.0"},
                {},
                env=clean_env,
                home=fake_home,
                platform="win32",
            )
            self.assertEqual(prof_ag_no_plugin["tier"], "ide_builtin_browser")
            self.assertFalse(prof_ag_no_plugin["sidecar_installed"])

            # 1b. Antigravity after installing sidecar manifest -> antigravity_sidecar
            sidecar_json = (
                fake_home / ".gemini" / "config" / "plugins" / "compass" / "sidecars" / "compass_board" / "sidecar.json"
            )
            sidecar_json.parent.mkdir(parents=True, exist_ok=True)
            sidecar_json.write_text('{"has_web_ui": true}', encoding="utf-8")
            prof_ag_ready = detect_host_profile(
                {"name": "antigravity", "version": "2.0"},
                {},
                env=clean_env,
                home=fake_home,
                platform="win32",
            )
            self.assertEqual(prof_ag_ready["tier"], "antigravity_sidecar")
            self.assertEqual(prof_ag_ready["sidecar_uri"], "sidecar://compass/compass_board/")

            # 2. Codex / Cursor -> ide_builtin_browser locally, headless_terminal over SSH
            prof_codex = detect_host_profile(
                {"name": "codex-mcp-client", "version": "1.0"},
                {},
                env=clean_env,
                home=fake_home,
                platform="darwin",
            )
            self.assertEqual(prof_codex["tier"], "ide_builtin_browser")

            prof_codex_ssh = detect_host_profile(
                {"name": "codex-mcp-client", "version": "1.0"},
                {},
                env={**clean_env, "SSH_TTY": "/dev/pts/1"},
                home=fake_home,
                platform="linux",
            )
            self.assertEqual(prof_codex_ssh["tier"], "headless_terminal")

            # 3. Hermes CLI -> external_browser with local GUI, headless_terminal on SSH / no DISPLAY
            prof_hermes_gui = detect_host_profile(
                {"name": "hermes-agent", "version": "0.9"},
                {},
                env={**clean_env, "DISPLAY": ":0"},
                home=fake_home,
                platform="linux",
            )
            self.assertEqual(prof_hermes_gui["tier"], "external_browser")
            self.assertTrue(has_local_gui_display({**clean_env, "DISPLAY": ":0"}, platform="linux"))

            prof_hermes_headless = detect_host_profile(
                {"name": "hermes-agent", "version": "0.9"},
                {},
                env=clean_env,
                home=fake_home,
                platform="linux",
            )
            self.assertEqual(prof_hermes_headless["tier"], "headless_terminal")
            self.assertFalse(has_local_gui_display(clean_env, platform="linux"))

            # 4. Sandboxed MCP App host -> mcp_app_inline
            prof_mcp_app = detect_host_profile(
                {"name": "custom-host", "version": "1.0"},
                {"extensions": {"io.modelcontextprotocol/ui": {}}},
                env=clean_env,
                home=fake_home,
                platform="win32",
            )
            self.assertEqual(prof_mcp_app["tier"], "mcp_app_inline")
            self.assertEqual(prof_mcp_app["resource_uri"], "ui://compass/workbench.html")

    def test_mcp_server_silent_on_initialize_and_returns_ui_delivery_on_open_compass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj_hermes"
            proj.mkdir()
            (proj / "README.md").write_text("# Demo Project\nBuild a clean workflow engine.", encoding="utf-8")
            ws = ProjectWorkspace(proj / ".project-memory", proj)
            ctx = ProjectContext.for_project(proj, "fang", "sess-hermes", "hermes")
            server = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx), allow_dynamic_project=True)

            with patch("project_compass.host_adapter.webbrowser.open") as mock_open:
                init_res = server.handle({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "hermes-agent", "version": "1.0"}, "capabilities": {}},
                })
                self.assertEqual(init_res["result"]["serverInfo"]["name"], "project-compass")
                mock_open.assert_not_called()

                res_open = server.handle({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "open_compass",
                        "arguments": {"project_path": str(proj), "session_id": "sess-hermes"},
                    },
                })
                payload = res_open["result"]["structuredContent"]
                self.assertIn("ui_delivery", payload)
                self.assertEqual(payload["ui_delivery"]["client_name"], "hermes-agent")
                mock_open.assert_not_called()

    def test_daemon_starts_once_reuses_port_and_opens_browser_only_once_for_hermes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = Path(tmp) / "proj_daemon"
            proj.mkdir()
            (proj / "README.md").write_text("# Daemon Proj\n核心目标：验证单实例守护。", encoding="utf-8")
            ws = ProjectWorkspace(proj / ".project-memory", proj)
            ctx = ProjectContext.for_project(proj, "fang", "sess-d", "codex")

            clean_env = {
                k: v for k, v in os.environ.items()
                if not k.startswith(("ANTIGRAVITY_", "SSH_", "SAMPLE_MODE", "COMPASS_"))
            }
            clean_env["DISPLAY"] = ":0"
            server = ProjectCompassMCPServer(
                WorkspaceMCPAdapter(ws, ctx),
                allow_dynamic_project=True,
                enable_ui_daemon=True,
            )

            started_pid = None
            try:
                with patch("project_compass.mcp_server.os.environ", clean_env), \
                     patch("project_compass.host_adapter.os.environ", clean_env), \
                     patch("project_compass.host_adapter.webbrowser.open", return_value=True) as mock_browser:
                    first = ensure_project_web_daemon(
                        proj,
                        preferred_port=18787,
                        workspace_root=proj / ".project-memory",
                        env=clean_env,
                        idle_timeout=30,
                    )
                    started_pid = first.get("pid")
                    self.assertTrue(first["started"], first)
                    self.assertFalse(first["reused"])
                    url1 = first["url"]
                    self.assertTrue(url1.startswith("http://127.0.0.1:"))

                    second = ensure_project_web_daemon(
                        proj,
                        preferred_port=18787,
                        workspace_root=proj / ".project-memory",
                        env=clean_env,
                        idle_timeout=30,
                    )
                    self.assertFalse(second["started"])
                    self.assertTrue(second["reused"])
                    self.assertEqual(second["url"], url1)

                    # Verify browser open deduplication for external_browser tier via server.handle
                    server._client_info = {"name": "hermes-agent", "version": "1.0"}
                    with patch("project_compass.host_adapter.has_local_gui_display", return_value=True):
                        d1 = deliver_ui_for_host(
                            proj,
                            client_info={"name": "hermes-agent"},
                            preferred_port=int(first["port"]),
                            workspace_root=proj / ".project-memory",
                            allow_daemon=True,
                            opened_urls=server._opened_browser_urls,
                            env=clean_env,
                            platform="win32",
                        )
                        d2 = deliver_ui_for_host(
                            proj,
                            client_info={"name": "hermes-agent"},
                            preferred_port=int(first["port"]),
                            workspace_root=proj / ".project-memory",
                            allow_daemon=True,
                            opened_urls=server._opened_browser_urls,
                            env=clean_env,
                            platform="win32",
                        )
                    self.assertEqual(d1["tier"], "external_browser")
                    self.assertTrue(d1["browser_opened"])
                    self.assertFalse(d2["browser_opened"])
                    self.assertEqual(mock_browser.call_count, 1)
            finally:
                _terminate_pid(started_pid)

    def test_sidecar_child_exits_cleanly_on_stdin_eof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "proj_eof"
            proj.mkdir()
            (proj / "README.md").write_text("# EOF Check\nEnsure clean child exit.", encoding="utf-8")
            env = dict(os.environ)
            src_root = str(Path(__file__).resolve().parents[1] / "src")
            env["PYTHONPATH"] = os.pathsep.join([src_root, env.get("PYTHONPATH", "")]) if env.get("PYTHONPATH") else src_root
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "project_compass.sidecar_backend", "--sidecar-child", "--project-path", str(proj)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding="utf-8",
            )
            try:
                line = proc.stdout.readline().strip()
                info = json.loads(line)
                self.assertGreater(int(info["port"]), 0)
                with urlopen(f"http://127.0.0.1:{info['port']}/api/health", timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    health = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(health["ok"])
                proc.stdin.close()
                rc = proc.wait(timeout=5)
                self.assertEqual(rc, 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)

    def test_sidecar_secret_guard_and_workspace_activation_switch_and_sample_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj_a = Path(tmp) / "proj_a"
            proj_b = Path(tmp) / "proj_b"
            proj_a.mkdir()
            proj_b.mkdir()
            (proj_a / "README.md").write_text("# Project Alpha\n核心目标：Alpha 工作区。", encoding="utf-8")
            (proj_b / "README.md").write_text("# Project Beta\n核心目标：Beta 动态切换工作区。", encoding="utf-8")

            ws_a = ProjectWorkspace(proj_a / ".project-memory", proj_a)
            ws_a.save([
                EvidenceEvent(
                    id="ev-alpha-1",
                    session_id="sess-alpha",
                    author="fang",
                    kind="user_message",
                    content="Alpha 项目基准任务：保持 Alpha 独立记忆。",
                    observed_at=datetime.now(timezone.utc),
                    metadata={"source_ref": "chat://alpha"},
                )
            ])
            events = ws_a.load()
            srv = create_dashboard_server(
                events,
                port=0,
                project_path=str(proj_a),
                workspace_root=proj_a / ".project-memory",
                sidecar_internal_secret="sidecar-secret-xyz-12345",
            )
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{srv.server_address[1]}"
            self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(3)))

            # 1. Forged Origin: null without valid sidecar secret must still be rejected 403
            bad_req = Request(
                base_url + "/api/notes",
                data=json.dumps({"text": "untrusted frame"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "null"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as err_ctx:
                urlopen(bad_req, timeout=5)
            self.assertEqual(err_ctx.exception.code, 403)

            # 2. Valid loopback request carrying matching X-Compass-Sidecar-Secret switches workspace to proj_b
            uri_b = "file:///" + str(proj_b).replace("\\", "/").lstrip("/")
            switch_req = Request(
                base_url + "/api/projects/activate",
                data=json.dumps({"project_path": uri_b}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Origin": "null",
                    "X-Compass-Sidecar-Secret": "sidecar-secret-xyz-12345",
                },
                method="POST",
            )
            with urlopen(switch_req, timeout=5) as sw_resp:
                self.assertEqual(sw_resp.status, 200)
                sw_state = json.loads(sw_resp.read().decode("utf-8"))
            self.assertEqual(Path(sw_state["project"]["path"]).resolve(), proj_b.resolve())
            self.assertTrue((proj_b / ".project-memory").exists())

            # 3. Sample mode strictly blocks workspace switching
            sample_srv = create_dashboard_server(sample_events(), port=0, sample_mode=True)
            sample_thread = threading.Thread(target=sample_srv.serve_forever, daemon=True)
            sample_thread.start()
            sample_url = f"http://127.0.0.1:{sample_srv.server_address[1]}"
            self.addCleanup(lambda: (sample_srv.shutdown(), sample_srv.server_close(), sample_thread.join(3)))
            sample_sw = Request(
                sample_url + "/api/projects/activate",
                data=json.dumps({"project_path": str(proj_b)}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": sample_url},
                method="POST",
            )
            with self.assertRaises(HTTPError) as sample_err:
                urlopen(sample_sw, timeout=5)
            self.assertEqual(sample_err.exception.code, 403)

    def test_mcp_setup_antigravity_codex_hermes_and_plugin_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp) / "home"
            fake_home.mkdir()
            proj = Path(tmp) / "proj"
            proj.mkdir()

            # Codex & Hermes config skeletons
            codex_cfg = generate_config("codex", project_path=proj, zero_config=True)
            self.assertEqual(codex_cfg["format"], "toml")
            self.assertIn("[mcp_servers.compass]", codex_cfg["toml"])
            hermes_cfg = generate_config("hermes", project_path=proj, zero_config=True)
            self.assertEqual(hermes_cfg["format"], "yaml")
            self.assertIn("compass:", hermes_cfg["yaml"])

            with patch("project_compass.mcp_setup.Path.home", return_value=fake_home):
                self.assertEqual(default_config_path("codex"), fake_home / ".codex" / "config.toml")
                self.assertEqual(default_config_path("hermes"), fake_home / ".hermes" / "config.yaml")

                # Install Antigravity plugin & sidecar bundle into isolated fake_home
                (fake_home / ".gemini" / "config").mkdir(parents=True, exist_ok=True)
                ret_ag = setup_main([
                    "--client", "antigravity",
                    "--zero-config",
                    "--project-path", str(proj),
                    "--member-id", "fang",
                    "--write",
                ])
                self.assertEqual(ret_ag, 0)
                plugin_root = fake_home / ".gemini" / "config" / "plugins" / "compass"
                self.assertTrue((plugin_root / "plugin.json").is_file())
                self.assertTrue((plugin_root / "assets" / "logo.svg").is_file())
                self.assertTrue((plugin_root / "skills" / "compass" / "SKILL.md").is_file())
                self.assertTrue((plugin_root / "sidecars" / "compass_board" / "sidecar.json").is_file())
                self.assertTrue((plugin_root / "sidecars" / "compass_board" / "main.mjs").is_file())
                self.assertTrue((plugin_root / "sidecars" / "compass_board" / "runtime_config.json").is_file())
                self.assertTrue((fake_home / ".gemini" / "config" / "skills" / "compass" / "SKILL.md").is_file())

                # Verify codex & hermes --write merging preserves sibling sections
                codex_path = fake_home / ".codex" / "config.toml"
                codex_path.parent.mkdir(parents=True, exist_ok=True)
                codex_path.write_text('model = "gpt-5"\n', encoding="utf-8")
                self.assertEqual(setup_main(["--client", "codex", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                codex_text = codex_path.read_text(encoding="utf-8")
                self.assertIn('model = "gpt-5"', codex_text)
                self.assertIn("[mcp_servers.compass]", codex_text)

                hermes_path = fake_home / ".hermes" / "config.yaml"
                hermes_path.parent.mkdir(parents=True, exist_ok=True)
                hermes_path.write_text("model: hermes-3\nmcp_servers:\n", encoding="utf-8")
                self.assertEqual(setup_main(["--client", "hermes", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                hermes_text = hermes_path.read_text(encoding="utf-8")
                self.assertIn("model: hermes-3", hermes_text)
                self.assertIn("# compass-mcp:begin compass", hermes_text)

                # Edge cases for Hermes YAML merge: empty dict + comment, 4-space indent, sibling section with same child key
                hermes_path.write_text(
                    "mcp_servers: {} # empty initially\n\npresets:\n  compass:\n    enabled: true\n",
                    encoding="utf-8",
                )
                self.assertEqual(setup_main(["--client", "hermes", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                h_empty = hermes_path.read_text(encoding="utf-8")
                self.assertIn("mcp_servers: # empty initially", h_empty)
                self.assertNotIn("{}", h_empty.splitlines()[0])
                self.assertIn("presets:\n  compass:\n    enabled: true", h_empty)

                hermes_path.write_text(
                    "mcp_servers:\n    other:\n        command: \"npx\"\n    compass:\n        command: \"old\"\n\npresets:\n  compass:\n    keep: true\n",
                    encoding="utf-8",
                )
                self.assertEqual(setup_main(["--client", "hermes", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                h_four = hermes_path.read_text(encoding="utf-8")
                self.assertIn('    other:\n        command: "npx"', h_four)
                self.assertIn("    # compass-mcp:begin compass\n    compass:\n      command:", h_four)
                self.assertIn("presets:\n  compass:\n    keep: true", h_four)
                self.assertNotIn('command: "old"', h_four)

                # Edge case for Codex TOML nested subtables + Claude/Cursor merge preservation
                codex_path.write_text(
                    'model = "gpt-5"\n\n[mcp_servers.compass]\ncommand = "old"\n\n[mcp_servers.compass.env]\nFOO = "1"\n\n[mcp_servers.compass.headers]\nX = "2"\n\n[mcp_servers.other]\ncommand = "keep"\n',
                    encoding="utf-8",
                )
                self.assertEqual(setup_main(["--client", "codex", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                c_nested = codex_path.read_text(encoding="utf-8")
                self.assertIn('[mcp_servers.other]\ncommand = "keep"', c_nested)
                self.assertNotIn('[mcp_servers.compass.headers]', c_nested)
                self.assertEqual(c_nested.count('[mcp_servers.compass]'), 1)

                claude_path = default_config_path("claude")
                claude_path.parent.mkdir(parents=True, exist_ok=True)
                claude_path.write_text('{"mcpServers": {"other-tool": {"command": "node"}}}', encoding="utf-8")
                self.assertEqual(setup_main(["--client", "claude", "--zero-config", "--project-path", str(proj), "--write"]), 0)
                claude_data = json.loads(claude_path.read_text(encoding="utf-8"))
                self.assertIn("other-tool", claude_data["mcpServers"])
                self.assertIn("project-compass", claude_data["mcpServers"])

    def test_security_csrf_unc_rejection_and_explicit_client_precedence(self) -> None:
        from project_compass.sidecar_backend import build_sidecar_server

        with self.assertRaises(ValueError):
            parse_workspace_uri("file://remote-host.invalid/share/proj")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            (fake_home / ".gemini" / "config" / "plugins" / "compass" / "sidecars" / "compass_board").mkdir(
                parents=True, exist_ok=True
            )
            (fake_home / ".gemini" / "config" / "plugins" / "compass" / "sidecars" / "compass_board" / "sidecar.json").write_text(
                '{"has_web_ui": true}', encoding="utf-8"
            )
            amb_env = {
                "PATH": os.environ.get("PATH", ""),
                "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:42100",
            }
            prof_codex = detect_host_profile(
                {"name": "codex-mcp-client", "version": "1.0"},
                {},
                env=amb_env,
                home=fake_home,
                platform="win32",
            )
            self.assertEqual(prof_codex["tier"], "ide_builtin_browser")
            prof_hermes = detect_host_profile(
                {"name": "hermes-agent", "version": "1.0"},
                {},
                env=amb_env,
                home=fake_home,
                platform="win32",
            )
            self.assertEqual(prof_hermes["tier"], "external_browser")

            missing_dir = tmp_path / "does_not_exist"
            with self.assertRaises(ValueError):
                ensure_project_web_daemon(missing_dir)
            with self.assertRaises(ValueError):
                build_sidecar_server(missing_dir)

            proj = tmp_path / "proj"
            proj.mkdir()
            (proj / "README.md").write_text("# Security\nGoal: keep POST guarded.\n", encoding="utf-8")
            ws = ProjectWorkspace(tmp_path / "state", proj)
            ev = EvidenceEvent(
                id="sec-ev-1",
                session_id="sess-sec",
                author="fang",
                kind="user_message",
                content="Goal: keep POST guarded.",
                observed_at=datetime.now(timezone.utc),
                metadata={"member_id": "fang"},
            )
            ws.save([ev])
            srv = create_dashboard_server(
                ws.load(),
                port=0,
                project_path=str(proj),
                workspace_root=tmp_path / "state",
                sidecar_internal_secret="ascii-secret-123",
            )
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{srv.server_address[1]}"
            self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(3)))

            csrf_cases = [
                ({"Content-Type": "application/json", "Origin": "https://evil.example"}, 403),
                ({"Content-Type": "application/json", "Origin": "null", "X-Compass-Sidecar-Secret": "non-ascii-\xe9"}, 403),
                ({"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403),
                ({"Content-Type": "text/plain"}, 415),
                ({"Content-Type": "application/x-www-form-urlencoded", "Origin": base_url}, 415),
            ]
            for extra_headers, expected_code in csrf_cases:
                req = Request(
                    base_url + "/api/review",
                    data=json.dumps({"action": "accept_fact", "fact_id": "missing", "reviewer": "fang"}).encode("utf-8"),
                    headers=extra_headers,
                    method="POST",
                )
                with self.assertRaises(HTTPError) as err_ctx:
                    urlopen(req, timeout=5)
                self.assertEqual(err_ctx.exception.code, expected_code)
                err_ctx.exception.close()

            # Non-blocking /api/state returns latest snapshot cleanly even when another thread holds state_lock
            with urlopen(base_url + "/api/state", timeout=5) as first_resp:
                first_state = json.loads(first_resp.read().decode("utf-8"))
            self.assertEqual(first_state["project"]["evidence_count"], 1)

            lock_held = threading.Event()
            release_lock = threading.Event()
            def _hold_state_lock() -> None:
                with srv.state_lock:
                    lock_held.set()
                    release_lock.wait(timeout=3)
            holder = threading.Thread(target=_hold_state_lock, daemon=True)
            holder.start()
            self.addCleanup(lambda: (release_lock.set(), holder.join(timeout=2)))
            self.assertTrue(lock_held.wait(timeout=2))

            t_snap = time.perf_counter()
            with urlopen(base_url + "/api/state", timeout=2) as snap_resp:
                snap_state = json.loads(snap_resp.read().decode("utf-8"))
            snap_elapsed = time.perf_counter() - t_snap
            release_lock.set()
            holder.join(timeout=2)
            self.assertEqual(snap_state["project"]["evidence_count"], 1)
            self.assertLess(snap_elapsed, 1.2)

            # Querying /api/state?project_id=<active_id> must remain writable (not read_only)
            active_id = first_state["project"]["project_id"]
            with urlopen(f"{base_url}/api/state?project_id={active_id}", timeout=5) as active_resp:
                active_by_id = json.loads(active_resp.read().decode("utf-8"))
            self.assertFalse(bool(active_by_id["project"].get("read_only")))

            # Dynamic MCP file:// URI routing & Antigravity sidecar clickable verify_completion link
            proj_dyn = tmp_path / "dyn-target"
            proj_dyn.mkdir()
            sidecar_manifest = fake_home / ".gemini" / "config" / "plugins" / "compass" / "sidecars" / "compass_board" / "sidecar.json"
            sidecar_manifest.parent.mkdir(parents=True, exist_ok=True)
            sidecar_manifest.write_text('{"has_web_ui": true}', encoding="utf-8")
            mcp_srv = ProjectCompassMCPServer(
                WorkspaceMCPAdapter(ws, ProjectContext.for_project(proj, "fang", "s-main", "antigravity")),
                allow_dynamic_project=True,
                enable_ui_daemon=False,
            )
            with patch("project_compass.host_adapter.Path.home", return_value=fake_home):
                mcp_srv.handle({
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "initialize",
                    "params": {"clientInfo": {"name": "antigravity", "version": "2.0"}},
                })
                dyn_uri = "file:///" + str(proj_dyn.resolve()).replace("\\", "/").lstrip("/")
                res_gate = mcp_srv.handle({
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "verify_completion",
                        "arguments": {"project_path": dyn_uri, "summary": "跨项目测试"},
                    },
                })
            gate_out = res_gate["result"]["structuredContent"]
            self.assertIn("sidecar://compass/compass_board/", gate_out.get("board_action_markdown", ""))
            self.assertTrue(any("sidecar://compass/compass_board/" in line for line in gate_out.get("nudge_lines") or []))

            # Dynamic MCP must reject filesystem root and bound _dynamic_adapters size
            root_path = str(proj_dyn.resolve().anchor)
            res_root = mcp_srv.handle({
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"project_path": root_path}},
            })
            self.assertTrue(res_root["result"]["isError"])
            mcp_srv._max_dynamic_adapters = 3
            for idx in range(5):
                sub_proj = tmp_path / f"dyn-cap-{idx}"
                sub_proj.mkdir()
                res_cap = mcp_srv.handle({
                    "jsonrpc": "2.0",
                    "id": 20 + idx,
                    "method": "tools/call",
                    "params": {"name": "project_context", "arguments": {"project_path": str(sub_proj), "session_id": f"s-{idx}"}},
                })
                self.assertFalse(res_cap["result"]["isError"])
            self.assertLessEqual(len(mcp_srv._dynamic_adapters), 3)


if __name__ == "__main__":
    unittest.main()
