"""v1.2 regression tests: title dehydration, action folding, baseline isolation, completion gate, and leak checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from project_compass.activity_stream import build_session_activity_stream
from project_compass.agent_inbox import AgentInbox
from project_compass.completion_gate import evaluate_completion_gate
from project_compass.dashboard import build_dashboard_state
from project_compass.local_plugin import LocalPluginAdapter, WorkspaceMCPAdapter
from project_compass.mcp_server import ProjectCompassMCPServer
from project_compass.mcp_setup import RULES_BEGIN_MARKER, RULES_END_MARKER, install_agent_rules
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import ProjectContext, build_compact_project_context
from project_compass.project_workspace import ProjectWorkspace
from project_compass.text_summary import is_historical_doc_fact, summarize_node_title
from project_compass.web_server import create_dashboard_server

REPO_ROOT = Path(__file__).resolve().parents[1]


class V12GuardrailsAndUXTests(unittest.TestCase):
    def test_title_dehydration_and_historical_doc_folding_vs_promotion(self):
        raw_log = "2026-10-26 first-load performance correction uses `derive_facts` in src/project_compass/fact_engine.py"
        short = summarize_node_title(raw_log, max_chars=22)
        self.assertLessEqual(len(short), 22)
        self.assertNotIn("2026-10-26", short)
        self.assertNotIn("`", short)
        self.assertNotIn("src/project_compass/", short)

        explicit = summarize_node_title(raw_log, explicit_title="优化 `derive_facts` 首屏加载速度", max_chars=22)
        self.assertEqual(explicit, "优化 derive_facts 首屏加载速度")

        goal_raw = "Demo 是人与 AI 共同设计开发的「实时交互纪要与低认知负载掌控台」：详细长说明在后面"
        goal_short = summarize_node_title(goal_raw, max_chars=28)
        self.assertEqual(goal_short, "实时交互纪要与低认知负载掌控台")

        with tempfile.TemporaryDirectory() as raw_tmp:
            repo = Path(raw_tmp) / "repo"
            repo.mkdir()
            t0 = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
            events = [
                EvidenceEvent(
                    "scan-file-doc1",
                    "project-scan",
                    "scanner",
                    "file_snapshot",
                    raw_log,
                    t0,
                    {
                        "source_ref": "DECISIONS.md",
                        "facts": [
                            {
                                "kind": "decision",
                                "subject_key": "doc.perf",
                                "value": raw_log,
                                "quote": raw_log,
                                "claim_type": "document",
                            },
                            {
                                "kind": "goal",
                                "subject_key": "project.goal",
                                "value": goal_raw,
                                "quote": goal_raw,
                                "claim_type": "document",
                            },
                        ],
                    },
                ),
                EvidenceEvent(
                    "ev-live-1",
                    "s-fang",
                    "fang",
                    "user_message",
                    "新决策：保持纯标准库与零外部依赖",
                    t0 + timedelta(seconds=5),
                    {
                        "member_id": "fang",
                        "short_title": "保持纯标准库零依赖",
                        "facts": [
                            {
                                "kind": "decision",
                                "subject_key": "arch.stdlib",
                                "value": "新决策：保持纯标准库与零外部依赖",
                            }
                        ],
                    },
                ),
            ]
            state_before = build_dashboard_state(events, project_path=str(repo))
            tl = state_before["team"]["thinking_line"]
            self.assertEqual(tl["root"]["label"], "实时交互纪要与低认知负载掌控台")
            self.assertEqual(len(tl["branches"]), 1)
            self.assertEqual(tl["branches"][0]["label"], "保持纯标准库零依赖")
            self.assertEqual(tl["historical_archive"]["count"], 1)
            arch_item = tl["historical_archive"]["items"][0]
            self.assertNotIn("2026-10-26", arch_item["label"])
            self.assertEqual(arch_item["full_label"], raw_log)

            # Personal view falls back to team goal so personal mode never loses project root goal
            self.assertIn("fallback_goal", state_before["personal"]["fang"])
            self.assertEqual(state_before["personal"]["fang"]["thinking_line"]["root"]["label"], "实时交互纪要与低认知负载掌控台")

            # Raw fact value stays intact for drawer audit
            doc_fact = next(f for f in state_before["team"]["facts"] if f["subject_key"] == "doc.perf")
            self.assertEqual(doc_fact["value"], raw_log)
            self.assertTrue(doc_fact["is_historical_doc"])
            self.assertTrue(is_historical_doc_fact(doc_fact))

            # Accepting the historical doc item promotes it out of the archive into the active mindmap branches
            state_after = build_dashboard_state(
                events,
                project_path=str(repo),
                fact_reviews=[{"action": "accept_fact", "fact_id": doc_fact["id"], "subject_key": doc_fact["subject_key"], "reviewer": "fang"}],
            )
            tl_after = state_after["team"]["thinking_line"]
            self.assertEqual(tl_after["historical_archive"]["count"], 0)
            self.assertTrue(any(b["fact_id"] == doc_fact["id"] and b["status"] == "accepted" for b in tl_after["branches"]))

    def test_activity_stream_human_translation_cross_tool_folding_and_note_dedup(self):
        t0 = datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc)
        events = [
            EvidenceEvent("tc-1", "s1", "fang", "tool_call", "read_file src/project_compass/dashboard.py", t0, {"member_id": "fang", "tool": "read_file", "paired_evidence_id": "tr-1"}),
            EvidenceEvent("tr-1", "s1", "fang", "tool_result", "ok", t0 + timedelta(seconds=1), {"member_id": "fang", "exit_code": 0, "paired_evidence_id": "tc-1"}),
            EvidenceEvent("tc-2", "s1", "fang", "tool_call", "grep_search build_thinking_line", t0 + timedelta(seconds=2), {"member_id": "fang", "tool": "grep_search", "paired_evidence_id": "tr-2"}),
            EvidenceEvent("tr-2", "s1", "fang", "tool_result", "ok", t0 + timedelta(seconds=3), {"member_id": "fang", "exit_code": 0, "paired_evidence_id": "tc-2"}),
            EvidenceEvent("fc-1", "s1", "fang", "file_change", "Updated UI", t0 + timedelta(seconds=4), {"member_id": "fang", "files": ["src/project_compass/web/app.js", "src/project_compass/web/styles.css"]}),
            EvidenceEvent("test-ok", "s1", "fang", "test_result", "Ran 548 tests OK", t0 + timedelta(seconds=5), {"member_id": "fang", "command": ["python", "-m", "unittest"], "exit_code": 0}),
            EvidenceEvent("test-fail", "s1", "fang", "command_execution", "1 failed", t0 + timedelta(seconds=6), {"member_id": "fang", "command": ["node", "tests/web_v11_solo_and_mindmap_test.cjs"], "exit_code": 1}),
            EvidenceEvent("note-abc", "s1", "fang", "user_message", "记录一个待定架构分支的完整上下文说明", t0 + timedelta(seconds=7), {"member_id": "fang", "source": "mcp_record_note", "short_title": "待定架构分支说明"}),
            EvidenceEvent("prop-abc", "s1", "fang", "fact_proposal", "记录一个待定架构分支的完整上下文说明", t0 + timedelta(seconds=7), {"member_id": "fang", "facts": [{"kind": "decision", "subject_key": "note.decision.1", "value": "x", "quote": "x", "source_id": "note-abc", "source_start": 0, "source_end": 1}]}),
        ]
        stream = build_session_activity_stream(events)
        # Paired companion proposal for note-abc does not duplicate the note row; read_file + grep_search fold into 1 explore item
        self.assertEqual(len(stream), 5)
        self.assertEqual(stream[0]["action_kind"], "note")
        self.assertEqual(stream[0]["summary"], "待定架构分支说明")

        self.assertEqual(stream[1]["action_kind"], "test")
        self.assertEqual(stream[1]["exit_code"], 1)
        self.assertIn("失败", stream[1]["summary"])

        self.assertEqual(stream[2]["action_kind"], "test")
        self.assertEqual(stream[2]["exit_code"], 0)
        self.assertIn("通过", stream[2]["summary"])

        self.assertEqual(stream[3]["action_kind"], "edit")
        self.assertEqual(stream[3]["action_label"], "修改文件")
        self.assertIn("app.js", stream[3]["summary"])

        self.assertEqual(stream[4]["action_kind"], "explore")
        self.assertEqual(stream[4]["action_label"], "探索上下文")
        self.assertEqual(stream[4]["collapsed_count"], 2)
        self.assertIn("共 2 步", stream[4]["summary"])

    def test_compact_context_never_promotes_unconfirmed_proposals_into_accepted_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "fresh-proj"
            project.mkdir()
            ctx = ProjectContext.for_project(project, "fang", "s1", "codex")
            state = {
                "handoff_brief": {"focus_goal": {"fact_id": "g1", "value": "做一个零配置 AI 协作成长看板", "status": "proposed"}},
                "team": {
                    "facts": [
                        {"id": "g1", "kind": "goal", "subject_key": "project.goal", "value": "做一个零配置 AI 协作成长看板", "status": "proposed"},
                        {"id": "f1", "kind": "decision", "subject_key": "dec.1", "value": "考虑支持深色模式（尚未拍板）", "status": "proposed"},
                        {"id": "t1", "kind": "task", "subject_key": "task.1", "value": "登录限流坑位待补充", "status": "proposed", "task_state": "pending"},
                    ],
                    "conflicts": [],
                },
                "evidence": [],
            }
            compact = build_compact_project_context(ctx, state)
            self.assertEqual(compact["accepted_facts"], [])
            self.assertEqual(compact["core_goal_status"], "proposed")
            self.assertEqual(len(compact["pending_proposals"]), 2)
            self.assertEqual(len(compact["open_pitfalls"]), 1)
            self.assertEqual(len(compact["nudge_lines"]), 2)
            self.assertIn("暂无已定案基准", compact["nudge_lines"][0])

    def test_record_note_and_verify_completion_mcp_and_http_parity_and_degradation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "new-app"
            project.mkdir()
            ws = ProjectWorkspace(root / "ws", project)
            ws.save([])
            ctx = ProjectContext.for_project(project, "fang", "s-v12", "codex")
            mcp_srv = ProjectCompassMCPServer(WorkspaceMCPAdapter(ws, ctx))

            # 1. Empty workspace verify_completion without files/tests is blocked
            res_empty_gate = mcp_srv.handle({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "verify_completion", "arguments": {"summary": "全都做完了"}},
            })
            self.assertFalse(res_empty_gate["result"]["isError"])
            gate_empty = res_empty_gate["result"]["structuredContent"]
            self.assertFalse(gate_empty["passed"])
            self.assertEqual(gate_empty["verdict"], "blocked")
            self.assertEqual(gate_empty["blockers"][0]["code"], "missing_verification_evidence")

            # 2. record_note in 1 step with concise short_title
            res_note = mcp_srv.handle({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "record_note",
                    "arguments": {
                        "text": "待填坑位：补充并发锁与断电恢复边界测试",
                        "kind": "task",
                        "title": "补全并发与断电测试",
                        "client_nonce": "mcp-n1",
                    },
                },
            })
            self.assertFalse(res_note["result"]["isError"])
            note_out = res_note["result"]["structuredContent"]
            self.assertTrue(note_out["recorded"])
            self.assertEqual(note_out["note"]["short_title"], "补全并发与断电测试")
            self.assertEqual(len(note_out["nudge_lines"]), 2)

            # 3. Record failing command -> verify_completion blocks completion
            fail_ev = EvidenceEvent("cmd-fail-1", "s-v12", "fang", "test_result", "FAILED", datetime.now(timezone.utc), {"member_id": "fang", "exit_code": 1})
            ws.save([fail_ev])
            res_fail_gate = mcp_srv.handle({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "verify_completion",
                    "arguments": {"summary": "修复完成", "changed_files": ["src/app.py"]},
                },
            })
            gate_fail = res_fail_gate["result"]["structuredContent"]
            self.assertFalse(gate_fail["passed"])
            self.assertTrue(any(b["code"] == "latest_verification_failed" for b in gate_fail["blockers"]))

            # 4. Passing verification passes gate while warning about open pitfall
            pass_ev = EvidenceEvent("cmd-pass-2", "s-v12", "fang", "test_result", "OK", datetime.now(timezone.utc) + timedelta(seconds=2), {"member_id": "fang", "exit_code": 0})
            ws.save([pass_ev])
            res_pass_gate = mcp_srv.handle({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "verify_completion",
                    "arguments": {"summary": "修通所有测试", "changed_files": ["src/app.py"], "test_evidence_ids": ["cmd-pass-2"]},
                },
            })
            gate_pass = res_pass_gate["result"]["structuredContent"]
            self.assertTrue(gate_pass["passed"])
            self.assertEqual(gate_pass["verdict"], "warn")
            self.assertTrue(any(w["code"] == "open_pitfalls_remaining" for w in gate_pass["warnings"]))

            # 5. Sidecar critic timeout degrades gracefully (fail-warn, never blocks) & SAMPLE_MODE skips sidecar
            state_obj = build_dashboard_state(ws.load(), project_path=str(project))
            dummy_key = "sk-" + "dummy-test-key"
            with patch.dict(os.environ, {"COMPASS_CRITIC_API_KEY": dummy_key, "SAMPLE_MODE": "false"}), patch(
                "project_compass.completion_gate.urlopen", side_effect=TimeoutError("timed out")
            ):
                degraded = evaluate_completion_gate(state_obj, ws.load(), summary="完成", changed_files=["src/app.py"], test_evidence_ids=["cmd-pass-2"])
            self.assertTrue(degraded["passed"])
            self.assertEqual(degraded["sidecar_critic"]["status"], "degraded_timeout_or_error")

            with patch.dict(os.environ, {"COMPASS_CRITIC_API_KEY": dummy_key, "SAMPLE_MODE": "true"}):
                skipped = evaluate_completion_gate(state_obj, ws.load(), summary="完成", changed_files=["src/app.py"], test_evidence_ids=["cmd-pass-2"])
            self.assertFalse(skipped["sidecar_critic"]["enabled"])
            self.assertEqual(skipped["sidecar_critic"]["status"], "skipped_sample_mode")

            # 6. LocalPluginAdapter HTTP parity over /api/agent/notes and /api/agent/verify-completion
            token = "z" * 40
            events = ws.load()
            inbox = AgentInbox({"schema_version": 1, "project_path": str(project), "owner_id": "owner", "clients": [
                {"client_id": "http-c1", "member_id": "fang", "session_id": "s-v12", "agent": "codex", "token": token}
            ]}, ws, events)
            server = create_dashboard_server(events, port=0, project_path=str(project), agent_inbox=inbox)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                adapter = LocalPluginAdapter(f"http://127.0.0.1:{server.server_address[1]}", ctx, token)
                http_note = adapter.dispatch("note.record", {"text": "采用标准库完成鉴权校验", "kind": "decision", "title": "标准库完成鉴权"})
                self.assertTrue(http_note["recorded"])
                http_gate = adapter.dispatch("completion.verify", {"summary": "HTTP 门禁", "changed_files": ["src/auth.py"], "test_evidence_ids": ["cmd-pass-2"]})
                self.assertTrue(http_gate["passed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_install_agent_rules_idempotency_and_public_export_leak_scan(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            proj = tmp / "sample-repo"
            proj.mkdir()
            agents_file = proj / "AGENTS.md"
            agents_file.write_text("# My Project\n\nKeep custom user rule.\n", encoding="utf-8")

            install_agent_rules(proj, member_id="fang")
            first = agents_file.read_text(encoding="utf-8")
            self.assertIn("# My Project", first)
            self.assertIn("Keep custom user rule.", first)
            self.assertIn(RULES_BEGIN_MARKER, first)
            self.assertIn(RULES_END_MARKER, first)
            self.assertIn("`fang`", first)

            install_agent_rules(proj, member_id="alice")
            second = agents_file.read_text(encoding="utf-8")
            self.assertEqual(second.count(RULES_BEGIN_MARKER), 1)
            self.assertIn("`alice`", second)
            self.assertIn("Keep custom user rule.", second)

            # Real repository docs/files must contain 0 private user path leaks
            exporter_path = REPO_ROOT / "scripts" / "export_public_release.py"
            spec = importlib.util.spec_from_file_location("export_public_release", exporter_path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            export_dir = tmp / "public-out"
            summary = module.export_public_release(REPO_ROOT, export_dir, init_git=False)
            self.assertEqual(summary["leaks_found"], 0, summary)


if __name__ == "__main__":
    unittest.main()
