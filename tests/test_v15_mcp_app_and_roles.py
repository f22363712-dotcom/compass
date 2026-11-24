"""End-to-end integration tests for Compass v1.5.0 MCP App, cold-start bootstrap, priority dispatch & team roles."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from project_compass.agent_inbox import AgentInbox
from project_compass.cli import _review_callback
from project_compass.local_plugin import LocalPluginAdapter, WorkspaceMCPAdapter
from project_compass.mcp_server import (
    WORKBENCH_MIME_TYPE,
    WORKBENCH_RESOURCE_URI,
    ProjectCompassMCPServer,
)
from project_compass.mcp_setup import main as setup_main
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_workspace import ProjectWorkspace
from project_compass.sample_data import sample_events
from project_compass.team_templates import build_team_config
from project_compass.web_server import create_dashboard_server


class V15MCPAppAndRolesTests(unittest.TestCase):
    def test_mcp_resources_advertise_and_read_csp_clean_workbench(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            project.mkdir()
            ws = ProjectWorkspace(Path(tmp) / "ws", project)
            ctx = ProjectContext.for_project(project, "fang", "sess-1", "antigravity")
            server = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx), allow_dynamic_project=True)

            init_res = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            caps = init_res["result"]["capabilities"]
            self.assertIn("tools", caps)
            self.assertIn("resources", caps)

            tools_res = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tool_map = {t["name"]: t for t in tools_res["result"]["tools"]}
            self.assertIn("open_compass", tool_map)
            self.assertIn("compass_app_action", tool_map)
            self.assertEqual(tool_map["open_compass"]["_meta"]["ui"]["resourceUri"], WORKBENCH_RESOURCE_URI)
            self.assertEqual(tool_map["compass_app_action"]["_meta"]["ui"]["visibility"], ["app"])

            res_list = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
            resources = res_list["result"]["resources"]
            self.assertEqual(len(resources), 1)
            self.assertEqual(resources[0]["uri"], WORKBENCH_RESOURCE_URI)
            self.assertEqual(resources[0]["mimeType"], WORKBENCH_MIME_TYPE)

            res_read = server.handle({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": WORKBENCH_RESOURCE_URI},
            })
            contents = res_read["result"]["contents"]
            self.assertEqual(len(contents), 1)
            self.assertEqual(contents[0]["uri"], WORKBENCH_RESOURCE_URI)
            self.assertEqual(contents[0]["mimeType"], "text/html;profile=mcp-app")
            self.assertEqual(contents[0]["_meta"]["ui"]["prefersBorder"], False)

            html_text = contents[0]["text"]
            self.assertGreater(len(html_text), 10000)
            self.assertIsNone(re.search(r"<script[^>]+src=", html_text, re.IGNORECASE))
            self.assertIsNone(re.search(r"<link[^>]+href=", html_text, re.IGNORECASE))
            self.assertIsNone(re.search(r"<img[^>]+src=", html_text, re.IGNORECASE))
            self.assertIn("product_delivery", html_text)
            self.assertIn("通用产品交付组", html_text)
            self.assertIn("activeDispatch", html_text)
            self.assertNotIn("ai_drama_studio", html_text)
            self.assertNotIn("漫剧", html_text)
            for jargon in (
                "下一步共识",
                "优先施工队列",
                "拍板与分歧",
                "待拍板草案",
                "待拍板隔离",
                "已定案",
                "搁置",
                "扫描文档铺底",
                '[data-theme="dark"]',
                "⌖",
            ):
                self.assertNotIn(jargon, html_text)
            for plain_phrase in (
                "当前下一步",
                "待确认想法",
                "标记已完成",
                "更早未处理",
                "一键全部忽略",
                'viewBox="0 0 512 512"',
                "mm-branch",
                "data-toggle-branch",
                "对话已定",
                "data-withdraw-id",
            ):
                self.assertIn(plain_phrase, html_text)

            node = shutil.which("node")
            if node:
                m_script = re.search(r"<script>([\s\S]*)</script>", html_text)
                self.assertIsNotNone(m_script)
                js_path = Path(tmp) / "mcp_app.js"
                js_path.write_text(m_script.group(1), encoding="utf-8")
                chk = subprocess.run([node, "--check", str(js_path)], capture_output=True, text=True, timeout=15)
                self.assertEqual(chk.returncode, 0, chk.stderr)

                # Verify logo, theme lock, collapsible mindmap branches, dialogue-decided withdraw, and team cmd builder
                probe_js = f"""
                const fs = require("node:fs");
                const vm = require("node:vm");
                const html = fs.readFileSync({json.dumps(str(Path(__file__).parents[1] / "src" / "project_compass" / "web" / "mcp_app.html"))}, "utf8");
                const script = html.match(/<script>([\\s\\S]*)<\\/script>/)[1];
                const listeners = {{}};
                const docAttrs = {{}};
                const docVars = {{}};
                const copyBtn = {{ attrs: {{}}, setAttribute(k, v) {{ this.attrs[k] = String(v); }} }};
                const setupCodeEl = {{ textContent: "", parentElement: {{ querySelector: () => copyBtn }} }};
                const appEl = {{ innerHTML: "", addEventListener(ev, fn) {{ listeners[ev] = fn; }} }};
                const posted = [];
                let msgHandler = null;
                const ctx = vm.createContext({{
                  console, URL, atob, btoa, setTimeout, clearTimeout,
                  requestAnimationFrame: (fn) => fn(),
                  ResizeObserver: class {{ observe() {{}} disconnect() {{}} }},
                  navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
                  document: {{
                    documentElement: {{
                      style: {{
                        setProperty(k, v) {{ docVars[k] = v; }},
                        height: "",
                        colorScheme: "",
                      }},
                      setAttribute(k, v) {{ docAttrs[k] = v; }},
                      getBoundingClientRect: () => ({{ height: 400 }}),
                    }},
                    body: {{}}, activeElement: null,
                    getElementById: (id) => (id === "app" ? appEl : id === "setup-cmd-code" ? setupCodeEl : null),
                    createElement: () => ({{ style: {{}}, setAttribute() {{}}, select() {{}} }}),
                  }},
                  window: {{
                    innerWidth: 500,
                    parent: {{ postMessage(m) {{ posted.push(m); }} }},
                    addEventListener(ev, fn) {{ if (ev === "message") msgHandler = fn; }},
                    removeEventListener() {{}},
                  }},
                  addEventListener(ev, fn) {{ if (ev === "message") msgHandler = fn; }},
                  removeEventListener() {{}},
                }});
                ctx.globalThis = ctx;
                vm.runInContext(script, ctx);
                (async () => {{
                  await new Promise((r) => setTimeout(r, 15));
                  const initReq = posted.find((x) => x && x.method === "ui/initialize");
                  msgHandler({{
                    source: ctx.window.parent,
                    data: {{
                      jsonrpc: "2.0",
                      id: initReq.id,
                      result: {{
                        protocolVersion: "2026-01-26",
                        hostInfo: {{ name: "test", version: "1" }},
                        hostCapabilities: {{}},
                        hostContext: {{ theme: "dark", styles: {{ variables: {{ "--color-background-primary": "#000000" }} }} }},
                      }},
                    }},
                  }});
                  await new Promise((r) => setTimeout(r, 15));
                  const stateReq = posted.find((x) => x && x.method === "tools/call");
                  msgHandler({{
                    source: ctx.window.parent,
                    data: {{
                      jsonrpc: "2.0", id: stateReq.id,
                      result: {{
                        isError: false,
                        structuredContent: {{
                          project_path: {json.dumps(str(project))}, project_name: "Test", session_id: "s1",
                          member_id: "owner", role_mode: "owner", can_review: true, bootstrapped: false,
                          core_goal: {{ text: "Goal", status: "missing", evidence_ids: [] }},
                          next_step: {{ fact_id: "fact-next-1", text: "Next task", status: "accepted", completed: false, evidence_ids: ["ev-1"] }},
                          mindmap: {{
                            root: {{}},
                            nodes: [],
                            groups: [
                              {{
                                key: "product_ux", title: "产品与界面体验", subtitle: "界面与交互",
                                collapsed_by_default: false, count: 1, pending_count: 0,
                                items: [{{ fact_id: "fact-dlg-1", kind: "decision", title: "对话选定的界面主题", value: "使用米白亮色主题", status: "dialogue_decided", decision_origin: "dialogue_selected", evidence_ids: ["ev-dlg"] }}],
                              }},
                              {{
                                key: "archive", title: "历史里程碑与更早记录", subtitle: "往期条目",
                                collapsed_by_default: true, count: 1, pending_count: 0,
                                items: [{{ fact_id: "fact-old-1", kind: "decision", title: "旧里程碑节点", value: "v1.1 历史里程碑", status: "accepted", decision_origin: "manual_confirmed", evidence_ids: ["ev-old"] }}],
                              }},
                            ],
                          }},
                          pending_items: [{{
                            fact_id: "fact-stale-1", kind: "decision", title: "三天前的旧想法",
                            value: "三天前的旧想法详情", quote: "三天前的旧想法详情", status: "proposed",
                            is_stale: true, completed: false, evidence_ids: ["ev-1"], member_id: "fang", session_id: ".system_generated",
                          }}],
                          accepted_items: [
                            {{
                              fact_id: "fact-dlg-1", kind: "decision", title: "对话选定的界面主题",
                              value: "使用米白亮色主题", status: "dialogue_decided", decision_origin: "dialogue_selected",
                              completed: false, is_stale: false, evidence_ids: ["ev-dlg"], member_id: "fang", session_id: "s1",
                            }},
                            {{
                              fact_id: "fact-done-1", kind: "task", title: "已完成历史任务",
                              value: "已完成历史任务详情", status: "accepted", decision_origin: "manual_confirmed",
                              completed: true, is_stale: false, evidence_ids: ["ev-done"], member_id: "fang", session_id: "s1",
                            }},
                          ],
                          conflicts: [], priority_dispatches: [],
                          team: {{ enabled: false, owner_id: "owner", seats: [] }},
                        }},
                      }},
                    }},
                  }});
                  await new Promise((r) => setTimeout(r, 15));
                  const initialMindmap = appEl.innerHTML;
                  const archiveCollapsedInitially = !initialMindmap.includes("旧里程碑节点") && initialMindmap.includes("对话选定的界面主题");
                  listeners.click({{ target: {{ closest: (s) => (s === "[data-toggle-branch]" ? {{ getAttribute: () => "product_ux" }} : null) }} }});
                  const productCollapsedAfterClick = !appEl.innerHTML.includes("对话选定的界面主题");
                  listeners.click({{ target: {{ closest: (s) => (s === "[data-toggle-branch]" ? {{ getAttribute: () => "archive" }} : null) }} }});
                  const archiveExpandedAfterClick = appEl.innerHTML.includes("旧里程碑节点");
                  const hasNextComplete = initialMindmap.includes('data-complete-id="fact-next-1"');
                  listeners.click({{ target: {{ closest: (s) => (s === "[data-tab]" ? {{ getAttribute: () => "triage" }} : null) }} }});
                  const triageHtml = appEl.innerHTML;
                  listeners.click({{ target: {{ closest: (s) => (s === "[data-tab]" ? {{ getAttribute: () => "team" }} : null) }} }});
                  listeners.input({{ target: {{ id: "custom-seat-input", value: "安全:审计席" }} }});
                  const soloCmd = setupCodeEl.textContent;
                  const copiedSolo = copyBtn.attrs["data-copy-cmd"];
                  listeners.click({{ target: {{ closest: (s) => (s === "[data-select-tpl]" ? {{ getAttribute: () => "product_delivery" }} : null) }} }});
                  const m = appEl.innerHTML.match(/<code id="setup-cmd-code">([^<]+)<\\/code>/);
                  const teamCmd = m ? m[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&") : "";
                  console.log(JSON.stringify({{
                    theme: docAttrs["data-theme"],
                    overrodeBgVar: Object.prototype.hasOwnProperty.call(docVars, "--color-background-primary"),
                    hasLogoSvg: initialMindmap.includes('class="brand-logo"') && initialMindmap.includes('viewBox="0 0 512 512"'),
                    archiveCollapsedInitially,
                    productCollapsedAfterClick,
                    archiveExpandedAfterClick,
                    hasNextComplete,
                    hasStaleDrawer: triageHtml.includes('class="stale-drawer"') && triageHtml.includes("一键全部忽略"),
                    hasDialogueWithdraw: triageHtml.includes("对话已定") && triageHtml.includes('data-withdraw-id="fact-dlg-1"'),
                    hasAcceptedDoneBadge: triageHtml.includes("✓ 已完成"),
                    mappedSystemSession: triageHtml.includes("历史会话"),
                    soloCmd,
                    copiedSolo,
                    teamCmd,
                  }}));
                }})();
                """
                cmd_res = subprocess.run([node, "-e", probe_js], capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(cmd_res.returncode, 0, cmd_res.stderr)
                parsed_cmds = json.loads(cmd_res.stdout.strip().splitlines()[-1])
                self.assertEqual(parsed_cmds["theme"], "light")
                self.assertFalse(parsed_cmds["overrodeBgVar"])
                self.assertTrue(parsed_cmds["hasLogoSvg"])
                self.assertTrue(parsed_cmds["archiveCollapsedInitially"])
                self.assertTrue(parsed_cmds["productCollapsedAfterClick"])
                self.assertTrue(parsed_cmds["archiveExpandedAfterClick"])
                self.assertTrue(parsed_cmds["hasNextComplete"])
                self.assertTrue(parsed_cmds["hasStaleDrawer"])
                self.assertTrue(parsed_cmds["hasDialogueWithdraw"])
                self.assertTrue(parsed_cmds["hasAcceptedDoneBadge"])
                self.assertTrue(parsed_cmds["mappedSystemSession"])
                # Also verify message-only host capabilities (hasMessage=true, hasContext=false) route split-main to message_current
                msg_only_probe = probe_js.replace(
                    "hostCapabilities: {},",
                    "hostCapabilities: { message: {} },",
                ).replace(
                    'mappedSystemSession: triageHtml.includes("历史会话"),',
                    'mappedSystemSession: triageHtml.includes("历史会话"), hasMsgCurrentSplit: triageHtml.includes(\'class="btn btn-primary split-main" data-dispatch-id="fact-stale-1" data-dispatch-mode="message_current"\'),',
                )
                msg_res = subprocess.run([node, "-e", msg_only_probe], capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(msg_res.returncode, 0, msg_res.stderr)
                self.assertTrue(json.loads(msg_res.stdout.strip().splitlines()[-1])["hasMsgCurrentSplit"])
                self.assertEqual(parsed_cmds["soloCmd"], parsed_cmds["copiedSolo"])
                for label, cmd_str, expected_seats in (
                    ("soloCmd", parsed_cmds["soloCmd"], 1),
                    ("teamCmd", parsed_cmds["teamCmd"], 4),
                ):
                    argv = [part.strip('"') for part in shlex.split(cmd_str, posix=False)]
                    self.assertEqual(argv[0], "compass-setup", label)
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        rc = setup_main(argv[1:])
                    self.assertEqual(rc, 0, f"{label} failed: {cmd_str}")
                    cfg = json.loads(buf.getvalue())
                    self.assertEqual(len(cfg["seats"]), expected_seats)

            bad_read = server.handle({
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": "ui://compass/missing.html"},
            })
            self.assertIn("error", bad_read)
            self.assertEqual(bad_read["error"]["code"], -32602)

    def test_open_compass_empty_vs_cold_start_doc_bootstrap_and_sample_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_proj = root / "empty-proj"
            empty_proj.mkdir()
            ws_empty = ProjectWorkspace(root / "ws-empty", empty_proj)
            ctx_empty = ProjectContext.for_project(empty_proj, "fang", "sess-empty", "antigravity")
            srv_empty = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws_empty, ctx_empty))

            res_empty = srv_empty.handle({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "open_compass", "arguments": {}},
            })
            self.assertFalse(res_empty["result"]["isError"])
            payload_empty = res_empty["result"]["structuredContent"]
            self.assertFalse(payload_empty["bootstrapped"])
            self.assertEqual(payload_empty["status_note"], "暂无历史记录，可随时在左栏对话记账")
            self.assertEqual(payload_empty["core_goal"]["status"], "missing")

            # Brand-new project with README.md, DECISIONS.md, HANDOFF.md
            doc_proj = root / "doc-proj"
            doc_proj.mkdir()
            (doc_proj / "README.md").write_text(
                "# Demo Studio\n\nBuild an offline-first visual storyboard workbench for indie creators.\n",
                encoding="utf-8",
            )
            (doc_proj / "DECISIONS.md").write_text(
                "# Decisions\n\n## 2026-11-18: Keep pure Python stdlib core with zero external runtime packages.\n",
                encoding="utf-8",
            )
            (doc_proj / "HANDOFF.md").write_text(
                "# Handoff\n\n- [ ] Wire right-pane interactive mindmap bootstrap\n",
                encoding="utf-8",
            )

            # SAMPLE_MODE=true must NOT run cold-start host disk extraction
            ws_sample = ProjectWorkspace(root / "ws-sample", doc_proj)
            ctx_sample = ProjectContext.for_project(doc_proj, "fang", "sess-sample", "antigravity")
            srv_sample = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws_sample, ctx_sample))
            with patch.dict(os.environ, {"SAMPLE_MODE": "true"}):
                res_sample = srv_sample.handle({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "open_compass", "arguments": {}},
                })
            self.assertFalse(res_sample["result"]["isError"])
            self.assertFalse(res_sample["result"]["structuredContent"]["bootstrapped"])
            self.assertFalse(ws_sample.exists())

            # Real cold-start auto-bootstraps goals & branches immediately
            ws_doc = ProjectWorkspace(root / "ws-doc", doc_proj)
            ctx_doc = ProjectContext.for_project(doc_proj, "fang", "sess-doc", "antigravity")
            srv_doc = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws_doc, ctx_doc))
            with patch.dict(os.environ, {"SAMPLE_MODE": "false"}):
                res_doc = srv_doc.handle({
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "open_compass", "arguments": {}},
                })
            self.assertFalse(res_doc["result"]["isError"])
            payload_doc = res_doc["result"]["structuredContent"]
            self.assertTrue(payload_doc["bootstrapped"])
            self.assertEqual(payload_doc["role_mode"], "owner")
            self.assertTrue(payload_doc["can_review"])
            self.assertIn("offline-first visual storyboard", payload_doc["core_goal"]["full_text"])
            self.assertGreaterEqual(len(payload_doc["mindmap"]["nodes"]), 2)
            self.assertGreaterEqual(len(payload_doc["pending_items"]), 2)

            # Second open_compass on initialized workspace does not repeat cold-start bootstrap
            res_reopen = srv_doc.handle({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "open_compass", "arguments": {}},
            })
            self.assertFalse(res_reopen["result"]["isError"])
            self.assertFalse(res_reopen["result"]["structuredContent"]["bootstrapped"])

    def test_workbench_actions_persist_and_sync_across_parallel_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "multi-sess-proj"
            project.mkdir()
            ws = ProjectWorkspace(root / "ws", project)
            ctx_a = ProjectContext.for_project(project, "fang", "sess-a", "antigravity")
            srv = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx_a), allow_dynamic_project=True)

            # Prime compact context cache in session B
            ctx_b_before = srv.handle({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "project_context",
                    "arguments": {"project_path": str(project), "session_id": "sess-b"},
                },
            })
            self.assertEqual(ctx_b_before["result"]["structuredContent"]["priority_dispatches"], [])

            # Record a note via compass_app_action in session A
            res_note = srv.handle({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {
                        "action": "record_note",
                        "kind": "decision",
                        "title": "锁定纯本地优先协议",
                        "text": "所有定案基准与优先队列必须持久化在本地工作区。",
                    },
                },
            })
            self.assertFalse(res_note["result"]["isError"])
            pending = res_note["result"]["structuredContent"]["pending_items"]
            self.assertEqual(len(pending), 1)
            fact_id = pending[0]["fact_id"]

            # Also record a second note to test reject_fact
            res_note2 = srv.handle({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {
                        "action": "record_note",
                        "kind": "assumption",
                        "title": "暂缓接入外部重型数据库",
                        "text": "待评估是否需要接入重型图数据库。",
                    },
                },
            })
            pending2 = res_note2["result"]["structuredContent"]["pending_items"]
            reject_id = next(item["fact_id"] for item in pending2 if "重型" in item["title"])

            # Accept first fact, reject second fact, and dispatch first fact
            res_accept = srv.handle({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {"action": "accept_fact", "fact_id": fact_id},
                },
            })
            self.assertFalse(res_accept["result"]["isError"])
            acc_data = res_accept["result"]["structuredContent"]
            self.assertTrue(any(item["fact_id"] == fact_id for item in acc_data["accepted_items"]))

            res_reject = srv.handle({
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {"action": "reject_fact", "fact_id": reject_id},
                },
            })
            self.assertFalse(res_reject["result"]["isError"])
            rej_data = res_reject["result"]["structuredContent"]
            self.assertFalse(any(item["fact_id"] == reject_id for item in rej_data["pending_items"]))
            self.assertFalse(any(node["id"] == reject_id for node in rej_data["mindmap"]["nodes"]))

            res_dispatch = srv.handle({
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {
                        "action": "dispatch_priority",
                        "fact_id": fact_id,
                        "title": "锁定纯本地优先协议",
                        "value": "所有定案基准与优先队列必须持久化在本地工作区。",
                        "evidence_ids": pending[0]["evidence_ids"],
                        "mode": "message_new",
                    },
                },
            })
            self.assertFalse(res_dispatch["result"]["isError"])
            disp_data = res_dispatch["result"]["structuredContent"]
            self.assertEqual(len(disp_data["priority_dispatches"]), 1)
            self.assertEqual(disp_data["priority_dispatches"][0]["fact_id"], fact_id)

            # Session B immediately observes invalidated cache + new priority_dispatches
            ctx_b_after = srv.handle({
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "project_context",
                    "arguments": {"project_path": str(project), "session_id": "sess-b"},
                },
            })
            self.assertFalse(ctx_b_after["result"]["isError"])
            b_payload = ctx_b_after["result"]["structuredContent"]
            self.assertEqual(len(b_payload["priority_dispatches"]), 1)
            self.assertEqual(b_payload["priority_dispatches"][0]["title"], "锁定纯本地优先协议")
            self.assertEqual(len(b_payload["accepted_facts"]), 1)

            # scan_docs works on WorkspaceMCPAdapter when README.md added later
            (project / "README.md").write_text("# Multi Session\n\nKeep parallel sessions consistent.\n", encoding="utf-8")
            res_scan = srv.handle({
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {"action": "scan_docs"},
                },
            })
            self.assertFalse(res_scan["result"]["isError"])
            self.assertIn("parallel sessions consistent", res_scan["result"]["structuredContent"]["core_goal"]["full_text"])

            # Reverse cross-session cache invalidation: prime default session A, mutate in session B, verify A refreshes
            ctx_a_before = srv.handle({
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {}},
            })
            self.assertFalse(ctx_a_before["result"]["isError"])
            before_pending = len(ctx_a_before["result"]["structuredContent"]["pending_proposals"])

            res_b_note = srv.handle({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {
                        "project_path": str(project),
                        "session_id": "sess-b",
                        "action": "record_note",
                        "kind": "assumption",
                        "title": "跨会话同步验证前提",
                        "text": "会话 B 通过工作台记笔记后，会话 A 必须立即失效缓存并看到最新条目。",
                    },
                },
            })
            self.assertFalse(res_b_note["result"]["isError"])

            ctx_a_after = srv.handle({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {}},
            })
            self.assertFalse(ctx_a_after["result"]["isError"])
            a_after_payload = ctx_a_after["result"]["structuredContent"]
            self.assertGreater(len(a_after_payload["pending_proposals"]), before_pending)
            self.assertTrue(any("跨会话同步验证前提" in item.get("short_title", "") for item in a_after_payload["pending_proposals"]))

    def test_product_delivery_team_roles_member_isolation_and_owner_http_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "delivery-proj"
            project.mkdir()
            ws = ProjectWorkspace(root / "state", project)
            events: list[EvidenceEvent] = []
            ws.save(events)

            team_cfg = build_team_config("product_delivery", project)
            inbox_cfg = team_cfg["agent_inbox_config"]
            tokens = {
                "COMPASS_TOKEN_PLANNER": "p" * 40,
                "COMPASS_TOKEN_DEVELOPER": "d" * 40,
                "COMPASS_TOKEN_QA": "q" * 40,
            }
            for client in inbox_cfg["clients"]:
                client["token"] = tokens[client["token_env"]]
                del client["token_env"]

            inbox = AgentInbox(inbox_cfg, ws, events)
            cb, confirmed, history, reviews = _review_callback(events, ws, str(project), [], [], [])
            http_srv = create_dashboard_server(
                events,
                port=0,
                project_path=str(project),
                confirmed_relations=confirmed,
                review_history=history,
                fact_reviews=reviews,
                review_callback=cb,
                agent_inbox=inbox,
                workspace_root=root / "state",
            )
            thread = threading.Thread(target=http_srv.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{http_srv.server_address[1]}"
            self.addCleanup(lambda: (http_srv.shutdown(), http_srv.server_close(), thread.join(3)))

            # 1. Public /api/state exposes team_templates and agent_api.clients with role_label / role_brief
            with urlopen(f"{base_url}/api/state", timeout=5) as resp:
                pub_state = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(pub_state["agent_api"]["enabled"])
            self.assertEqual(pub_state["agent_api"]["owner_id"], "lead")
            self.assertEqual(len(pub_state["team_templates"]), 4)
            seat_by_id = {c["member_id"]: c for c in pub_state["agent_api"]["clients"]}
            self.assertEqual(seat_by_id["planner"]["role_label"], "产品与方案席")
            self.assertEqual(seat_by_id["developer"]["role_label"], "研发实现席")
            self.assertEqual(seat_by_id["qa"]["role_label"], "测试与验收席")
            for tok in tokens.values():
                self.assertNotIn(tok, json.dumps(pub_state, ensure_ascii=False))

            # 2. Planner member MCP seat sees role_mode="member", can_review=False, and cannot accept/reject/scan
            planner_ctx = ProjectContext.for_project(project, "planner", "session-planner", "claude-code")
            planner_adapter = LocalPluginAdapter(base_url, planner_ctx, tokens["COMPASS_TOKEN_PLANNER"])
            planner_mcp = ProjectCompassMCPServer(planner_adapter, allow_dynamic_project=False)

            res_open = planner_mcp.handle({
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "open_compass", "arguments": {}},
            })
            self.assertFalse(res_open["result"]["isError"])
            wb = res_open["result"]["structuredContent"]
            self.assertEqual(wb["role_mode"], "member")
            self.assertFalse(wb["can_review"])
            self.assertTrue(wb["team"]["enabled"])
            self.assertEqual(wb["team"]["owner_id"], "lead")
            self.assertEqual(wb["team"]["seats"][0]["role_label"], "产品与方案席")

            # Member records a personal draft note cleanly
            res_member_note = planner_mcp.handle({
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "compass_app_action",
                    "arguments": {
                        "action": "record_note",
                        "kind": "decision",
                        "title": "采用纯本地工作区优先协议",
                        "text": "所有定案基准与优先施工队列优先写入本地工作区台账。",
                    },
                },
            })
            self.assertFalse(res_member_note["result"]["isError"])
            pending_items = res_member_note["result"]["structuredContent"]["pending_items"]
            self.assertEqual(len(pending_items), 1)
            planner_fact_id = pending_items[0]["fact_id"]

            # Member attempts accept_fact / reject_fact / scan_docs -> all blocked
            for req_id, forbidden in enumerate(("accept_fact", "reject_fact", "scan_docs"), start=12):
                res_forbid = planner_mcp.handle({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {
                        "name": "compass_app_action",
                        "arguments": {"action": forbidden, "fact_id": planner_fact_id},
                    },
                })
                self.assertTrue(res_forbid["result"]["isError"], f"{forbidden} should be rejected for member seat")
                with self.assertRaises(PermissionError):
                    planner_adapter.dispatch("workbench.action", {"action": forbidden, "fact_id": planner_fact_id})

            # 3. Member HTTP token cannot call owner /api/review or /api/dispatch
            with urlopen(Request(base_url + "/"), timeout=5) as root_resp:
                cookie_header = root_resp.headers["Set-Cookie"].split(";")[0]
            owner_headers = {
                "Content-Type": "application/json",
                "Cookie": cookie_header,
                "Origin": base_url,
            }

            for endpoint in ("/api/review", "/api/dispatch"):
                member_req = Request(
                    base_url + endpoint,
                    data=json.dumps({
                        "action": "accept_fact",
                        "fact_id": planner_fact_id,
                        "title": "采用纯本地工作区优先协议",
                        "value": "所有定案基准与优先施工队列优先写入本地工作区台账。",
                        "reviewer": "planner",
                    }).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {tokens['COMPASS_TOKEN_PLANNER']}",
                        "Origin": base_url,
                    },
                    method="POST",
                )
                with self.assertRaises(HTTPError) as err_ctx:
                    urlopen(member_req, timeout=5)
                self.assertEqual(err_ctx.exception.code, 403)

            # 4. Lead owner accepts via /api/review and dispatches via /api/dispatch
            rev_req = Request(
                base_url + "/api/review",
                data=json.dumps({
                    "action": "accept_fact",
                    "fact_id": planner_fact_id,
                    "reviewer": "lead",
                }).encode("utf-8"),
                headers=owner_headers,
                method="POST",
            )
            with urlopen(rev_req, timeout=5) as rev_resp:
                self.assertEqual(rev_resp.status, 200)

            disp_req = Request(
                base_url + "/api/dispatch",
                data=json.dumps({
                    "fact_id": planner_fact_id,
                    "title": "采用纯本地工作区优先协议",
                    "value": "所有定案基准与优先施工队列优先写入本地工作区台账。",
                    "evidence_ids": pending_items[0]["evidence_ids"],
                    "reviewer": "lead",
                    "mode": "queue",
                }).encode("utf-8"),
                headers=owner_headers,
                method="POST",
            )
            with urlopen(disp_req, timeout=5) as disp_resp:
                self.assertEqual(disp_resp.status, 200)
                disp_state = json.loads(disp_resp.read().decode("utf-8"))
            self.assertEqual(len(disp_state["priority_dispatches"]), 1)
            self.assertEqual(disp_state["priority_dispatches"][0]["actor"], "lead")
            self.assertEqual(disp_state["dispatch"]["fact_id"], planner_fact_id)

            # Member's project_context sees the queued priority dispatch
            res_ctx = planner_mcp.handle({
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tools/call",
                "params": {"name": "project_context", "arguments": {"refresh": True}},
            })
            self.assertFalse(res_ctx["result"]["isError"])
            ctx_payload = res_ctx["result"]["structuredContent"]
            self.assertEqual(len(ctx_payload["priority_dispatches"]), 1)
            self.assertEqual(ctx_payload["priority_dispatches"][0]["title"], "采用纯本地工作区优先协议")

    def test_sample_mode_dispatch_does_not_write_host_workspace(self) -> None:
        events = sample_events()
        srv = create_dashboard_server(events, port=0, sample_mode=True)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{srv.server_address[1]}"
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(3)))

        before_len = len(srv.dashboard_events)
        req = Request(
            base_url + "/api/dispatch",
            data=json.dumps({
                "fact_id": "sample-f1",
                "title": "样例演练",
                "value": "验证样例模式下只返回预览不写入宿主机状态。",
                "evidence_ids": [],
                "reviewer": "sample-owner",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": base_url},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(payload["dispatch"]["sample_mode"])
        self.assertEqual(len(srv.dashboard_events), before_len)

    def test_workbench_complete_fact_noise_filtering_and_72h_stale_flagging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "noise-stale-proj"
            project.mkdir()
            ws = ProjectWorkspace(root / "ws", project)
            now = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
            older = now - timedelta(hours=90)
            events = [
                EvidenceEvent(
                    id="ev-noise-q",
                    session_id=".system_generated",
                    author="antigravity",
                    kind="user_message",
                    content="因为它是通过 GitHub 来的，前提是我们先提交才能审查，对吧？",
                    observed_at=older,
                    metadata={
                        "member_id": "antigravity",
                        "facts": [{
                            "kind": "assumption",
                            "subject_key": "premise.noise.q",
                            "value": "因为它是通过 GitHub 来的，前提是我们先提交才能审查，对吧？",
                            "quote": "因为它是通过 GitHub 来的，前提是我们先提交才能审查，对吧？",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-noise-choice",
                    session_id="sess-1",
                    author="fang",
                    kind="user_message",
                    content="A1: (Recommended) 批准上述四维方案",
                    observed_at=older,
                    metadata={
                        "member_id": "fang",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.choice.noise",
                            "value": "A1: (Recommended) 批准上述四维方案",
                            "quote": "A1: (Recommended) 批准上述四维方案",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-accepted-q",
                    session_id="sess-1",
                    author="fang",
                    kind="user_message",
                    content="已确认保留问号的历史确认前提，对吧？",
                    observed_at=older,
                    metadata={
                        "member_id": "fang",
                        "facts": [{
                            "kind": "assumption",
                            "subject_key": "premise.confirmed.exempt",
                            "value": "已确认保留问号的历史确认前提，对吧？",
                            "quote": "已确认保留问号的历史确认前提，对吧？",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-stale-valid",
                    session_id="sess-1",
                    author="fang",
                    kind="user_message",
                    content="采用统一米白高对比纸面样式，不跟随宿主强行变黑。",
                    observed_at=older,
                    metadata={
                        "member_id": "fang",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.stale.valid",
                            "value": "采用统一米白高对比纸面样式，不跟随宿主强行变黑。",
                            "quote": "采用统一米白高对比纸面样式，不跟随宿主强行变黑。",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-old-task",
                    session_id="sess-1",
                    author="fang",
                    kind="user_message",
                    content="发布前检查 README 与示例说明。",
                    observed_at=older,
                    metadata={
                        "member_id": "fang",
                        "short_title": "检查 README 与示例",
                        "facts": [{
                            "kind": "task",
                            "subject_key": "project.next_step",
                            "value": "发布前检查 README 与示例说明。",
                            "quote": "发布前检查 README 与示例说明。",
                            "claim_type": "user_statement",
                            "task_state": "pending",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-fresh-valid",
                    session_id="sess-2",
                    author="fang",
                    kind="user_message",
                    content="统一只用本地零依赖 SQLite 与 JSON 存储状态。",
                    observed_at=now,
                    metadata={
                        "member_id": "fang",
                        "short_title": "锁定零依赖本地存储",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.fresh.valid",
                            "value": "统一只用本地零依赖 SQLite 与 JSON 存储状态。",
                            "quote": "统一只用本地零依赖 SQLite 与 JSON 存储状态。",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
            ]
            ws.save(events)
            ctx = ProjectContext.for_project(project, "fang", "sess-2", "antigravity")
            srv = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx))

            # Pre-accept the confirmed question fact & old task to mirror real state
            from project_compass.fact_engine import derive_facts
            derived = derive_facts(events)
            accepted_q_id = next(f.id for f in derived if f.subject_key == "premise.confirmed.exempt")
            old_task_id = next(f.id for f in derived if f.subject_key == "project.next_step")
            srv.handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "compass_app_action", "arguments": {"action": "accept_fact", "fact_id": accepted_q_id}},
            })
            res_accept_task = srv.handle({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "compass_app_action", "arguments": {"action": "accept_fact", "fact_id": old_task_id}},
            })
            payload = res_accept_task["result"]["structuredContent"]
            self.assertGreaterEqual(payload["filtered_legacy_noise_count"], 2)
            pending_titles = [item["title"] + " " + item["value"] for item in payload["pending_items"]]
            self.assertFalse(any("对吧？" in t for t in pending_titles))
            self.assertFalse(any("批准上述四维方案" in t for t in pending_titles))
            self.assertTrue(any(item["fact_id"] == accepted_q_id for item in payload["accepted_items"]))
            self.assertEqual(len(ws.load()), 6)

            by_text = {item["value"]: item for item in payload["pending_items"]}
            self.assertTrue(by_text["采用统一米白高对比纸面样式，不跟随宿主强行变黑。"]["is_stale"])
            self.assertFalse(by_text["统一只用本地零依赖 SQLite 与 JSON 存储状态。"]["is_stale"])
            self.assertEqual(payload["next_step"]["fact_id"], old_task_id)

            # Complete the next_step task via compass_app_action
            res_complete = srv.handle({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "compass_app_action", "arguments": {"action": "complete_fact", "fact_id": old_task_id}},
            })
            self.assertFalse(res_complete["result"]["isError"])
            after = res_complete["result"]["structuredContent"]
            self.assertNotEqual(after["next_step"]["fact_id"], old_task_id)
            self.assertFalse(any(item["fact_id"] == old_task_id for item in after["pending_items"]))

            # Member seat must NOT be permitted to call complete_fact
            member_srv = create_dashboard_server(events, port=0)
            thread = threading.Thread(target=member_srv.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{member_srv.server_address[1]}"
            self.addCleanup(lambda: (member_srv.shutdown(), member_srv.server_close(), thread.join(3)))
            member_adapter = LocalPluginAdapter(base_url, ctx, "m" * 40, workspace=ws)
            with self.assertRaises(PermissionError):
                member_adapter.dispatch("workbench.action", {"action": "complete_fact", "fact_id": old_task_id})
            member_mcp = ProjectCompassMCPServer(member_adapter)
            res_member_complete = member_mcp.handle({
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "compass_app_action", "arguments": {"action": "complete_fact", "fact_id": old_task_id}},
            })
            self.assertTrue(res_member_complete["result"]["isError"])

    def test_owner_dialogue_decided_classification_withdraw_and_team_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "dlg-decided-proj"
            project.mkdir()
            ws = ProjectWorkspace(root / "ws", project)
            now = datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc)
            events = [
                EvidenceEvent(
                    id="ev-owner-dlg",
                    session_id="sess-owner",
                    author="fang",
                    kind="user_message",
                    content="A1: (Recommended) 自动区分来源：你在对话里亲手点选的方案直接记为对话已定",
                    observed_at=now,
                    metadata={
                        "member_id": "fang",
                        "role": "user",
                        "capture": "antigravity-ask-question",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.dialogue.owner",
                            "value": "自动区分来源：你在对话里亲手点选的方案直接记为对话已定",
                            "quote": "A1: (Recommended) 自动区分来源：你在对话里亲手点选的方案直接记为对话已定",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-owner-assump",
                    session_id="sess-owner",
                    author="fang",
                    kind="user_message",
                    content="假设本机端口没有被其他程序占用，仍待人工验证。",
                    observed_at=now,
                    metadata={
                        "member_id": "fang",
                        "role": "user",
                        "capture": "antigravity-ask-question",
                        "facts": [{
                            "kind": "assumption",
                            "subject_key": "premise.port.free",
                            "value": "假设本机端口没有被其他程序占用，仍待人工验证。",
                            "quote": "假设本机端口没有被其他程序占用，仍待人工验证。",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-ai-report",
                    session_id="sess-owner",
                    author="antigravity",
                    kind="assistant_message",
                    content="建议同时增加导出 Markdown 按钮。",
                    observed_at=now,
                    metadata={
                        "member_id": "antigravity",
                        "role": "assistant",
                        "capture": "antigravity-transcript",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.ai.guess",
                            "value": "建议同时增加导出 Markdown 按钮。",
                            "quote": "建议同时增加导出 Markdown 按钮。",
                            "claim_type": "assistant_report",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-conflict-a",
                    session_id="sess-a",
                    author="fang",
                    kind="user_message",
                    content="A1: 分歧主题方案一：前端用浅米白固定主题",
                    observed_at=now,
                    metadata={
                        "member_id": "fang",
                        "role": "user",
                        "capture": "antigravity-ask-question",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.shared.conflict",
                            "value": "分歧主题方案一：前端用浅米白固定主题",
                            "quote": "A1: 分歧主题方案一：前端用浅米白固定主题",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
                EvidenceEvent(
                    id="ev-conflict-b",
                    session_id="sess-b",
                    author="planner",
                    kind="user_message",
                    content="A1: 分歧主题方案二：前端保持深灰暗色主题",
                    observed_at=now,
                    metadata={
                        "member_id": "planner",
                        "role": "user",
                        "capture": "antigravity-ask-question",
                        "facts": [{
                            "kind": "decision",
                            "subject_key": "decision.shared.conflict",
                            "value": "分歧主题方案二：前端保持深灰暗色主题",
                            "quote": "A1: 分歧主题方案二：前端保持深灰暗色主题",
                            "claim_type": "user_statement",
                        }],
                    },
                ),
            ]
            ws.save(events)

            # Solo/owner workbench: only owner ask_question non-conflicted decision is dialogue_decided
            ctx = ProjectContext.for_project(project, "fang", "sess-owner", "antigravity")
            srv = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx))
            open_res = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "open_compass", "arguments": {}}})
            self.assertFalse(open_res["result"]["isError"])
            wb = open_res["result"]["structuredContent"]
            self.assertEqual(wb["dialogue_decided_count"], 1)
            acc_map = {item["value"]: item for item in wb["accepted_items"]}
            dlg_text = "自动区分来源：你在对话里亲手点选的方案直接记为对话已定"
            self.assertIn(dlg_text, acc_map)
            self.assertEqual(acc_map[dlg_text]["status"], "dialogue_decided")
            self.assertEqual(acc_map[dlg_text]["decision_origin"], "dialogue_selected")
            dlg_id = acc_map[dlg_text]["fact_id"]
            pending_vals = [item["value"] for item in wb["pending_items"]]
            self.assertNotIn(dlg_text, pending_vals)
            self.assertIn("假设本机端口没有被其他程序占用，仍待人工验证。", pending_vals)
            self.assertIn("建议同时增加导出 Markdown 按钮。", pending_vals)

            # Team mode boundary: non-owner member choice stays pending (NEVER dialogue_decided)
            inbox_cfg = build_team_config("product_delivery", project)["agent_inbox_config"]
            for idx, c in enumerate(inbox_cfg["clients"]):
                c["token"] = f"tok-{idx}-" + ("t" * 36)
                del c["token_env"]
            inbox_cfg["owner_id"] = "lead"
            inbox = AgentInbox(inbox_cfg, ws, events)
            from project_compass.local_plugin import _build_workbench_payload
            team_wb = _build_workbench_payload(
                events, project_path=project, confirmed=[], history=[], fact_reviews=[],
                context=ctx, agent_inbox=inbox, role_mode="owner", can_review=True,
            )
            self.assertEqual(team_wb["dialogue_decided_count"], 0)
            self.assertIn(dlg_text, [i["value"] for i in team_wb["pending_items"]])
            from project_compass.decision_graph import is_owner_dialogue_decided_fact
            spoofed_ev = EvidenceEvent(
                id="ev-team-spoof", session_id="s-team", author="lead", kind="user_message",
                content="A1: 代录助手机器人摘要", observed_at=now,
                metadata={"role": "assistant", "capture": "antigravity-ask-question"},
            )
            self.assertFalse(is_owner_dialogue_decided_fact(
                {"id": "fact-spoof", "kind": "decision", "status": "proposed", "author": "lead", "claim_type": "user_statement"},
                spoofed_ev, owner_id="lead", can_review=True, team_enabled=True,
            ))

            # Owner withdraws dialogue_decided item non-destructively via reject_fact
            wd_res = srv.handle({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "compass_app_action", "arguments": {"action": "reject_fact", "fact_id": dlg_id, "note": "从对话已定中撤回"}},
            })
            self.assertFalse(wd_res["result"]["isError"])
            wd_wb = wd_res["result"]["structuredContent"]
            self.assertEqual(wd_wb["status_note"], "已移出当前列表（原始记录仍保留）")
            self.assertEqual(wd_wb["dialogue_decided_count"], 0)
            self.assertFalse(any(i["fact_id"] == dlg_id for i in wd_wb["accepted_items"]))
            self.assertFalse(any(n["id"] == dlg_id for n in wd_wb["mindmap"]["nodes"]))
            self.assertEqual(len(ws.load()), 5)

    def test_mindmap_topic_grouping_and_archive_folding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "mm-groups-proj"
            project.mkdir()
            ws = ProjectWorkspace(root / "ws", project)
            now = datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc)
            older = now - timedelta(hours=96)
            events = [
                EvidenceEvent(
                    id="ev-goal", session_id="s1", author="fang", kind="user_message",
                    content="项目核心目标：做清爽好用的本地研发掌控台", observed_at=now,
                    metadata={"member_id": "fang", "facts": [{"kind": "goal", "subject_key": "project.goal", "value": "做清爽好用的本地研发掌控台"}]},
                ),
                EvidenceEvent(
                    id="ev-ux", session_id="s1", author="fang", kind="user_message",
                    content="A1: (Recommended) 统一采用清爽米白亮色界面和真指南针图标", observed_at=now,
                    metadata={"member_id": "fang", "role": "user", "capture": "antigravity-ask-question", "facts": [{"kind": "decision", "subject_key": "ux.theme", "value": "统一采用清爽米白亮色界面和真指南针图标"}]},
                ),
                EvidenceEvent(
                    id="ev-arch", session_id="s1", author="fang", kind="user_message",
                    content="A1: (Recommended) 坚持纯 Python 零依赖本地存储协议", observed_at=now,
                    metadata={"member_id": "fang", "role": "user", "capture": "antigravity-ask-question", "facts": [{"kind": "decision", "subject_key": "arch.zero", "value": "坚持纯 Python 零依赖本地存储协议"}]},
                ),
                EvidenceEvent(
                    id="ev-arch-auth", session_id="s1", author="fang", kind="user_message",
                    content="用户权限隔离与数据库锁架构", observed_at=now,
                    metadata={"member_id": "fang", "facts": [{"kind": "decision", "subject_key": "arch.auth.lock", "value": "用户权限隔离与数据库锁架构"}]},
                ),
                EvidenceEvent(
                    id="ev-open-task", session_id="s1", author="fang", kind="user_message",
                    content="发布前审阅 v1.4.0 开源演示脚本", observed_at=older,
                    metadata={"member_id": "fang", "facts": [{"kind": "task", "subject_key": "project.next_step", "value": "发布前审阅 v1.4.0 开源演示脚本", "task_state": "pending"}]},
                ),
                EvidenceEvent(
                    id="ev-stale-dec", session_id="s1", author="fang", kind="user_message",
                    content="更早的旧探索思路，超过72小时。", observed_at=older,
                    metadata={"member_id": "fang", "facts": [{"kind": "decision", "subject_key": "dec.old", "value": "更早的旧探索思路，超过72小时。"}]},
                ),
                EvidenceEvent(
                    id="ev-past-release", session_id="s1", author="fang", kind="user_message",
                    content="Compass v1.1 本机联调已接通验证通过", observed_at=now,
                    metadata={"member_id": "fang", "facts": [{"kind": "decision", "subject_key": "rel.v11", "value": "Compass v1.1 本机联调已接通验证通过"}]},
                ),
            ]
            ws.save(events)
            ctx = ProjectContext.for_project(project, "fang", "s1", "antigravity")
            srv = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx))
            from project_compass.fact_engine import derive_facts
            v11_id = next(f.id for f in derive_facts(events) if f.subject_key == "rel.v11")
            res = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "compass_app_action", "arguments": {"action": "accept_fact", "fact_id": v11_id}}})
            wb = res["result"]["structuredContent"]
            groups = {g["key"]: g for g in wb["mindmap"]["groups"]}
            self.assertIn("product_ux", groups)
            self.assertIn("architecture", groups)
            self.assertIn("execution", groups)
            self.assertIn("archive", groups)
            self.assertFalse(groups["product_ux"]["collapsed_by_default"])
            self.assertTrue(groups["archive"]["collapsed_by_default"])
            self.assertEqual([i["value"] for i in groups["execution"]["items"]], ["发布前审阅 v1.4.0 开源演示脚本"])
            arch_vals = [i["value"] for i in groups["architecture"]["items"]]
            ux_vals = [i["value"] for i in groups["product_ux"]["items"]]
            self.assertIn("用户权限隔离与数据库锁架构", arch_vals)
            self.assertNotIn("用户权限隔离与数据库锁架构", ux_vals)
            archive_vals = {i["value"] for i in groups["archive"]["items"]}
            self.assertIn("更早的旧探索思路，超过72小时。", archive_vals)
            self.assertIn("Compass v1.1 本机联调已接通验证通过", archive_vals)


if __name__ == "__main__":
    unittest.main()
