from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from project_compass.activity_stream import build_session_activity_stream
from project_compass.agent_inbox import AgentInbox
from project_compass.cli import _review_callback
from project_compass.cognitive_export import export_state_by_format
from project_compass.dashboard import build_dashboard_state
from project_compass.mcp_server import ProjectCompassMCPServer, WorkspaceMCPAdapter
from project_compass.models import EvidenceEvent
from project_compass.onboarding import workspace_code_index_path
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_scan_job import ProjectScanJob
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


def _post_json(url: str, body: dict | bytes, headers: dict | None = None) -> tuple[int, dict]:
    raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    req = Request(url, data=raw, headers=req_headers, method="POST")
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class V11SoloAndConcurrencyTest(unittest.TestCase):
    def _seed_workspace(self, tmp: Path) -> tuple[Path, Path, ProjectWorkspace, list[EvidenceEvent]]:
        ws_root = tmp / "ws"
        repo = tmp / "solo-repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "README.md").write_text("# Demo\n\n目标：验证个人开发主线闭环。\n", encoding="utf-8")
        t0 = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)
        initial_events = [
            EvidenceEvent(
                "ev-seed-1",
                "s-fang",
                "fang",
                "user_message",
                "初始需求：用文件锁保护跨进程持久化。",
                t0,
                {"member_id": "fang"},
            )
        ]
        ws = ProjectWorkspace(ws_root, repo)
        ws.save(initial_events, {"source": "test"}, complete_scan=True)
        return ws_root, repo, ws, ws.load()

    def test_quick_note_http_contracts_idempotency_and_restart_persistence(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ws_root, repo, ws, events = self._seed_workspace(tmp)
            confirmed, history, fact_reviews = ws.load_review_state()
            cb, confirmed, history, fact_reviews = _review_callback(events, ws, str(repo), confirmed, history, fact_reviews)

            secondary = tmp / "secondary-repo"
            secondary.mkdir()
            sec_ws = ProjectWorkspace(ws_root, secondary)
            sec_ws.save(
                [EvidenceEvent("sec-1", "s2", "bob", "user_message", "Secondary goal", datetime.now(timezone.utc), {"member_id": "bob"})],
                {"source": "test"},
                complete_scan=True,
            )
            sec_id = next(p["project_id"] for p in ProjectWorkspace.list_registered(ws_root) if Path(p["project_path"]) == secondary.resolve())

            server = create_dashboard_server(
                events,
                host="127.0.0.1",
                port=0,
                project_path=str(repo),
                confirmed_relations=confirmed,
                review_history=history,
                fact_reviews=fact_reviews,
                review_callback=cb,
                workspace_root=ws_root,
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                # 1. Missing application/json -> 415
                code, _ = _post_json(f"{base}/api/notes", b'{"text":"hello"}', headers={"Content-Type": "text/plain"})
                self.assertEqual(code, 415)

                # 2. Cross-origin mutation -> 403
                code, _ = _post_json(f"{base}/api/notes", {"text": "hello", "kind": "decision"}, headers={"Origin": "https://evil.example"})
                self.assertEqual(code, 403)

                # 3. Empty & secret & unsupported kind -> 400
                code, _ = _post_json(f"{base}/api/notes", {"text": "   ", "kind": "decision"})
                self.assertEqual(code, 400)
                dummy_secret = "sk-" + "1234567890abcdefghijklmnop"
                code, _ = _post_json(f"{base}/api/notes", {"text": dummy_secret, "kind": "decision"})
                self.assertEqual(code, 400)
                code, _ = _post_json(f"{base}/api/notes", {"text": "Bad kind", "kind": "unknown_kind"})
                self.assertEqual(code, 400)

                # 4. Read-only secondary project write attempt -> 403
                code, _ = _post_json(f"{base}/api/notes", {"text": "Leak", "kind": "decision", "project_id": sec_id})
                self.assertEqual(code, 403)

                # 5. Proposed quick notes for all kinds + single-member Solo preservation
                for note_kind, note_text in [
                    ("decision", "采用单文件 MCP 状态签名校验"),
                    ("assumption", "浏览器刷新窗口内写入不丢失"),
                    ("task", "补充全部回归断言"),
                    ("goal", "实现可溯源的个人认知工作台"),
                ]:
                    code, payload = _post_json(
                        f"{base}/api/notes",
                        {"text": note_text, "kind": note_kind, "client_nonce": f"nonce-{note_kind}"},
                    )
                    self.assertEqual(code, 200)
                    self.assertEqual(payload["quick_note"]["kind"], note_kind)
                    self.assertEqual(payload["quick_note"]["member_id"], "fang")
                    self.assertEqual(list(k for k in payload["personal"].keys() if k != "project-documents"), ["fang"])

                # 6. Idempotent client_nonce replay produces zero duplicate facts
                before_facts = len(payload["personal"]["fang"]["facts"])
                code, replay = _post_json(
                    f"{base}/api/notes",
                    {"text": "采用单文件 MCP 状态签名校验", "kind": "decision", "client_nonce": "nonce-decision"},
                )
                self.assertEqual(code, 200)
                self.assertEqual(len(replay["personal"]["fang"]["facts"]), before_facts)

                # 7. Auto-accept quick note requires reviewer and persists accepted fact across reload
                code, _ = _post_json(f"{base}/api/notes", {"text": "No reviewer", "kind": "decision", "auto_accept": True})
                self.assertEqual(code, 400)
                code, acc_payload = _post_json(
                    f"{base}/api/notes",
                    {
                        "text": "关键基准：保持纯 Python 标准库零第三方依赖",
                        "kind": "decision",
                        "auto_accept": True,
                        "reviewer": "fang",
                        "client_nonce": "nonce-accepted-dec",
                    },
                )
                self.assertEqual(code, 200)
                self.assertTrue(acc_payload["quick_note"]["accepted"])
                reloaded_events = ws.load()
                _, _, reloaded_reviews = ws.load_review_state()
                self.assertTrue(any(ev.kind == "fact_proposal" for ev in reloaded_events))
                self.assertTrue(any(r.get("fact_id") == acc_payload["quick_note"]["fact_id"] for r in reloaded_reviews))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_quick_note_blocks_sample_mode_and_requires_owner_cookie_under_agent_api(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ws_root, repo, ws, events = self._seed_workspace(tmp)

            sample_srv = create_dashboard_server(events, host="127.0.0.1", port=0, project_path=str(repo), workspace_root=ws_root, sample_mode=True)
            t_s = Thread(target=sample_srv.serve_forever, daemon=True)
            t_s.start()
            try:
                code, _ = _post_json(f"http://127.0.0.1:{sample_srv.server_address[1]}/api/notes", {"text": "Try sample", "kind": "decision"})
                self.assertEqual(code, 403)
            finally:
                sample_srv.shutdown()
                sample_srv.server_close()
                t_s.join(timeout=2)

            cfg = {
                "schema_version": 1,
                "project_path": str(repo.resolve()),
                "owner_id": "fang",
                "clients": [
                    {"client_id": "ag1", "member_id": "agent-bot", "session_id": "s-agent", "agent": "ag", "token": "a" * 36}
                ],
            }
            inbox = AgentInbox(cfg, ws, events)
            agent_srv = create_dashboard_server(events, host="127.0.0.1", port=0, project_path=str(repo), workspace_root=ws_root, agent_inbox=inbox)
            t_a = Thread(target=agent_srv.serve_forever, daemon=True)
            t_a.start()
            try:
                base = f"http://127.0.0.1:{agent_srv.server_address[1]}"
                code, _ = _post_json(f"{base}/api/notes", {"text": "Unauthed note", "kind": "decision"})
                self.assertEqual(code, 403)
            finally:
                agent_srv.shutdown()
                agent_srv.server_close()
                t_a.join(timeout=2)

    def test_cross_process_merge_and_live_mcp_visibility_without_restart(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ws_root, repo, ws, events = self._seed_workspace(tmp)

            # Process A saves one review, Process B merges a second review -> both preserved
            ws.save_review_state([], [{"action": "accept_fact", "fact_id": "f1", "reviewer": "fang"}], [{"fact_id": "f1", "reviewer": "fang"}])
            _, m_hist, m_rev = ws.merge_and_save_review_state([], [{"action": "accept_fact", "fact_id": "f2", "reviewer": "fang"}], [{"fact_id": "f2", "reviewer": "fang"}])
            self.assertEqual({item["fact_id"] for item in m_rev}, {"f1", "f2"})
            self.assertEqual(len(m_hist), 2)

            # Start dashboard server without restarting after external MCP write
            server = create_dashboard_server(events, host="127.0.0.1", port=0, project_path=str(repo), workspace_root=ws_root)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/api/state", timeout=5) as resp:
                    before = json.loads(resp.read().decode("utf-8"))
                before_count = before["project"]["fact_count"]

                mcp_ws = ProjectWorkspace(ws_root, repo)
                mcp_ctx = ProjectContext.for_project(repo, "fang", "mcp-live", "antigravity")
                adapter = WorkspaceMCPAdapter(mcp_ws, mcp_ctx)
                mcp_srv = ProjectCompassMCPServer(adapter)
                append_res = mcp_srv.handle({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "append_evidence",
                        "arguments": {
                            "event": {
                                "schema_version": 1,
                                "event": {
                                    "id": "mcp-ev-1",
                                    "type": "assistant_message",
                                    "timestamp": "2026-11-15T14:30:00+00:00",
                                    "content": "外部 MCP 提案实时可见：通过状态签名监听外部 MCP 写入。",
                                },
                            }
                        },
                    },
                })
                self.assertFalse(append_res["result"]["isError"], append_res)
                src_id = append_res["result"]["structuredContent"]["ids"][0]
                prop_res = mcp_srv.handle({
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "propose_fact",
                        "arguments": {
                            "proposals": [
                                {
                                    "id": "mcp-prop-1",
                                    "source_id": src_id,
                                    "kind": "decision",
                                    "subject_key": "mcp_live",
                                    "quote": "外部 MCP 提案实时可见",
                                }
                            ]
                        },
                    },
                })
                self.assertFalse(prop_res["result"]["isError"], prop_res)

                with urlopen(f"{base}/api/state", timeout=5) as resp:
                    after = json.loads(resp.read().decode("utf-8"))
                self.assertGreater(after["project"]["fact_count"], before_count)
                self.assertTrue(any("外部 MCP 提案实时可见" in f["value"] for f in after["personal"]["fang"]["facts"]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_scan_job_with_docs_ast_broken_syntax_tolerance_and_isolated_storage(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ws_root = tmp / "ws"
            repo = tmp / "target-app"
            repo.mkdir()
            (repo / "README.md").write_text("# Target App\n\n目标：打造零污染项目扫描。\n", encoding="utf-8")
            (repo / "src").mkdir()
            (repo / "src" / "main.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
            (repo / "src" / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

            job = ProjectScanJob(ws_root, timeout_seconds=30.0)
            started = job.start(str(repo), extract_docs=True, with_code_index=True)
            self.assertIn(started["state"], {"running", "complete"})
            deadline = time.monotonic() + 15.0
            status = job.status()
            while time.monotonic() < deadline and status["state"] in {"scanning", "running", "pending"}:
                time.sleep(0.05)
                status = job.status()
            self.assertEqual(status["state"], "complete", status)
            self.assertGreater(status["evidence_count"], 0)

            ws = ProjectWorkspace(ws_root, repo)
            idx_path = workspace_code_index_path(ws)
            self.assertTrue(idx_path.is_file(), "code-index.json not written into Compass workspace")
            self.assertFalse((repo / "code-index.json").exists(), "AST index polluted target repository")

            # Secondary saved project loads isolated code-index.json into derived_context
            server = create_dashboard_server([], host="127.0.0.1", port=0, project_path=None, workspace_root=ws_root)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                pid = status["project_id"]
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state?project_id={pid}", timeout=5) as resp:
                    proj_state = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(proj_state["derived_context"]["enabled"])
                self.assertTrue(any("src/main.py" in n.get("source_ref", "") for n in proj_state["derived_context"]["nodes"]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_activity_stream_collapses_healthy_tools_and_exports_mermaid_mindmap(self):
        t0 = datetime(2026, 11, 15, 11, 0, tzinfo=timezone.utc)
        events = [
            EvidenceEvent("doc-1", "s1", "fang", "file_snapshot", "README snapshot", t0, {"member_id": "fang"}),
            EvidenceEvent("tc-1", "s1", "fang", "tool_call", "read_file a.py", t0 + timedelta(seconds=1), {"member_id": "fang", "tool": "read_file", "paired_evidence_id": "tr-1"}),
            EvidenceEvent("tr-1", "s1", "fang", "tool_result", "ok", t0 + timedelta(seconds=2), {"member_id": "fang", "exit_code": 0, "paired_evidence_id": "tc-1"}),
            EvidenceEvent("tc-2", "s1", "fang", "tool_call", "read_file b.py", t0 + timedelta(seconds=3), {"member_id": "fang", "tool": "read_file", "paired_evidence_id": "tr-2"}),
            EvidenceEvent("tr-2", "s1", "fang", "tool_result", "ok", t0 + timedelta(seconds=4), {"member_id": "fang", "exit_code": 0, "paired_evidence_id": "tc-2"}),
            EvidenceEvent("cmd-fail", "s1", "fang", "command_execution", "AssertionError", t0 + timedelta(seconds=5), {"member_id": "fang", "command": ["python", "-m", "unittest"], "exit_code": 1}),
            EvidenceEvent("note-1", "s1", "fang", "user_message", "记录脑图决策", t0 + timedelta(seconds=6), {"member_id": "fang", "source": "web_quick_note"}),
        ]
        stream = build_session_activity_stream(events)
        self.assertFalse(any(item["primary_evidence_id"] == "doc-1" for item in stream))
        self.assertEqual(stream[0]["action_kind"], "note")
        self.assertEqual(stream[0]["action_label"], "随手记")
        self.assertEqual(stream[1]["action_kind"], "test")
        self.assertEqual(stream[1]["exit_code"], 1)
        collapsed_tool = stream[2]
        self.assertEqual(collapsed_tool["collapsed_count"], 2)
        self.assertEqual(set(collapsed_tool["evidence_ids"]), {"tc-1", "tr-1", "tc-2", "tr-2"})

        state = build_dashboard_state(events, project_path="C:/demo/myproj")
        body, content_type, filename = export_state_by_format(state, "mindmap")
        self.assertEqual(content_type, "text/markdown; charset=utf-8")
        self.assertEqual(filename, "myproj-mindmap.md")
        self.assertIn("```mermaid", body)
        self.assertIn("mindmap", body)

        fallback_state = {**state, "project": {k: v for k, v in (state.get("project") or {}).items() if k != "name"}}
        _, _, fallback_filename = export_state_by_format(fallback_state, "mindmap")
        self.assertTrue(fallback_filename.startswith("compass-"))
        self.assertTrue(fallback_filename.endswith("-mindmap.md"))


if __name__ == "__main__":
    unittest.main()
