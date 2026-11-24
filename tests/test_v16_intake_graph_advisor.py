from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from urllib.request import Request, urlopen

from project_compass.agent_hints import AsyncHintCache, build_local_agent_hints
from project_compass.antigravity_adapter import AntigravityTranscriptAdapter, infer_transcript_session_id
from project_compass.dashboard import build_dashboard_state
from project_compass.decision_graph import IncrementalSemanticObserver, extract_dialogue_rich_facts
from project_compass.doc_fact_intake import record_document_candidates
from project_compass.eval.tracks_v16 import run_all_v16_tracks
from project_compass.models import EvidenceEvent
from project_compass.project_scanner import scan_project
from project_compass.project_workspace import ProjectWorkspace
from project_compass.sidecar_backend import build_sidecar_server
from project_compass.transcript_watcher import AutoTranscriptIntake, discover_active_antigravity_transcript
from project_compass.web_server import create_dashboard_server


class V16IntakeGraphAndAdvisorTests(unittest.TestCase):
    def test_auto_transcript_discovery_respects_sample_mode_and_path_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj_a = root / "compass"
            proj_b = root / "compass-extra"
            proj_a.mkdir()
            proj_b.mkdir()
            brain = root / "brain"

            # Decoy transcript matching sibling prefix proj_b must NOT match proj_a
            decoy_tx = brain / "conv-decoy" / ".system_generated" / "logs" / "transcript.jsonl"
            decoy_tx.parent.mkdir(parents=True)
            decoy_tx.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"<USER_REQUEST>Workspace: {proj_b}</USER_REQUEST>"}) + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(discover_active_antigravity_transcript(proj_a, brain_root=brain))

            real_tx = brain / "conv-real" / ".system_generated" / "logs" / "transcript.jsonl"
            real_tx.parent.mkdir(parents=True)
            real_tx.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"<USER_REQUEST>目标：验证 {proj_a} 旁听</USER_REQUEST>"}) + "\n",
                encoding="utf-8",
            )
            hit = discover_active_antigravity_transcript(proj_a, brain_root=brain)
            self.assertEqual(hit, real_tx)

            with patch.dict(os.environ, {"SAMPLE_MODE": "true"}, clear=False):
                self.assertIsNone(discover_active_antigravity_transcript(proj_a, brain_root=brain))

    def test_sidecar_backend_wires_passive_transcript_and_ignores_archived_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "demo_repo"
            repo.mkdir()
            (repo / "README.md").write_text("# DemoRepo\n\nBuild an offline-first console for agents.\n", encoding="utf-8")
            (repo / "docs" / "archive").mkdir(parents=True)
            (repo / "docs" / "archive" / "OLD_PLAN.md").write_text("# Old\n\n- [ ] Archived stale item\n", encoding="utf-8")
            (repo / "docs" / "AUDIT_2026-10-10.md").write_text("### 2026-10-10: Stale snapshot\n", encoding="utf-8")

            brain = root / "brain"
            tx = brain / "conv-1" / ".system_generated" / "logs" / "transcript.jsonl"
            tx.parent.mkdir(parents=True)
            tx.write_text(
                "\n".join([
                    json.dumps({
                        "step_index": 1,
                        "source": "USER_EXPLICIT",
                        "type": "USER_INPUT",
                        "created_at": "2026-11-20T09:00:00Z",
                        "content": f"<USER_REQUEST>Workspace: {repo.resolve()}\n目标：上线被动采集工作台\n采用 Python 标准库路线。</USER_REQUEST>",
                    }),
                ]) + "\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"COMPASS_ANTIGRAVITY_BRAIN_DIR": str(brain), "SAMPLE_MODE": "false"}, clear=False):
                srv = build_sidecar_server(repo, port=0, workspace_root=root / "ws")
                try:
                    st = srv.dashboard_state()
                    self.assertTrue(st["intake"]["enabled"])
                    self.assertEqual(st["intake"]["channel"], "antigravity")
                    self.assertGreaterEqual(st["intake"]["captured_messages"], 1)
                    fact_values = [f["value"] for f in st["team"]["facts"]]
                    self.assertTrue(any("上线被动采集工作台" in v for v in fact_values))
                    self.assertTrue(any("采用 Python 标准库路线" in v for v in fact_values))
                    # Archived snapshot doc should not leak into facts
                    self.assertFalse(any("Archived stale item" in v for v in fact_values))

                    # Append another live turn and sync passively
                    with tx.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({
                            "step_index": 2,
                            "source": "USER_EXPLICIT",
                            "type": "USER_INPUT",
                            "created_at": "2026-11-20T09:05:00Z",
                            "content": "<USER_REQUEST>下一步：完成 AST 调用影响提示验证。</USER_REQUEST>",
                        }, ensure_ascii=False) + "\n")
                    st2 = srv.dashboard_state()
                    self.assertIn("AST 调用影响提示验证", st2["next_consensus"]["value"])
                finally:
                    srv.server_close()

    def test_causal_dialogue_extraction_supersession_and_llm_quote_gate(self) -> None:
        text = (
            "方案选择有两种方案待权衡：\n"
            "方案 A：轻量轮询同步状态\n"
            "方案 B：引入重型消息队列\n"
            "前提是本地状态构建耗时能控制在 200ms 以内。\n"
            "放弃引入外部图数据库，因为会破坏零外部依赖约束。\n"
            "最终定为使用纯标准库内置索引。"
        )
        facts = extract_dialogue_rich_facts(text, "user_statement")
        stages = {f.get("decision_stage") for f in facts}
        self.assertIn("open_fork", stages)
        self.assertIn("premise", stages)
        self.assertIn("rejected_path", stages)
        self.assertIn("settled", stages)
        for f in facts:
            self.assertIn(f["quote"], text)

        # Reject fabricated quote in IncrementalSemanticObserver while keeping grounded verbatim quote
        src_ev = EvidenceEvent(
            id="ev-src-1",
            session_id="s1",
            author="fang",
            kind="user_message",
            content="前提是系统能在无密钥下离线跑通。",
            observed_at=datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc),
            metadata={"member_id": "fang"},
        )
        fake_llm_reply = json.dumps({
            "candidates": [
                {"source_id": "ev-src-1", "kind": "assumption", "decision_stage": "premise", "quote": "前提是系统能在无密钥下离线跑通。"},
                {"source_id": "ev-src-1", "kind": "decision", "decision_stage": "settled", "quote": "这是模型捏造的原文"},
            ]
        }, ensure_ascii=False)
        obs = IncrementalSemanticObserver(llm_callable=lambda _msgs: fake_llm_reply)
        proposals = obs.extract_batch([src_ev])
        self.assertEqual(len(proposals), 1)
        self.assertEqual(len(proposals[0].metadata["facts"]), 1)
        self.assertEqual(proposals[0].metadata["facts"][0]["quote"], "前提是系统能在无密钥下离线跑通。")

    def test_same_author_supersession_eliminates_false_conflict(self) -> None:
        t1 = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        q1 = "完成 v1.3 看板实测"
        q2 = "发布 v1.4.0 开源版"
        e1 = EvidenceEvent("n1", "s1", "fang", "user_message", q1, t1, {"member_id": "fang"})
        p1 = EvidenceEvent("p1", "s1", "fang", "fact_proposal", q1, t1, {"member_id": "fang", "facts": [{"kind": "task", "subject_key": "project.next_step", "value": q1, "quote": q1, "source_id": "n1", "source_start": 0, "source_end": len(q1)}]})
        e2 = EvidenceEvent("n2", "s1", "fang", "user_message", q2, t2, {"member_id": "fang"})
        p2 = EvidenceEvent("p2", "s1", "fang", "fact_proposal", q2, t2, {"member_id": "fang", "facts": [{"kind": "task", "subject_key": "project.next_step", "value": q2, "quote": q2, "source_id": "n2", "source_start": 0, "source_end": len(q2)}]})

        state = build_dashboard_state([e1, p1, e2, p2])
        self.assertEqual(state["team"]["conflicts"], [])
        self.assertFalse(any(f["status"] == "conflicted" for f in state["team"]["facts"]))
        self.assertTrue(any(f.get("superseded_by_fact_id") for f in state["team"]["facts"]))

    def test_v16_three_eval_tracks_deterministic_baseline_vs_upgrade(self) -> None:
        report = run_all_v16_tracks(use_live_llm=False)
        t1 = report["track1_intake_ab"]
        self.assertGreater(t1["v16_passive_on"]["capture_rate"], t1["v15_passive_off"]["capture_rate"])
        self.assertEqual(t1["v16_passive_on"]["archive_doc_noise_in_pending"], 0)
        self.assertEqual(t1["v16_passive_on"]["same_author_false_conflicts"], 0)

        t2 = report["track2_milestone_blind"]
        self.assertGreater(t2["v16_local_only"]["f1"], t2["v15_baseline"]["f1"])
        self.assertGreaterEqual(t2["v16_local_only"]["recall"], 0.85)
        self.assertGreaterEqual(t2["v16_local_only"]["premise_status_accuracy"], 0.75)

        t3 = report["track3_advisor_critic"]
        self.assertGreater(t3["v16_avg_score"], t3["v15_avg_score"])
        self.assertGreaterEqual(t3["v16_avg_score"], 9.0)
        sc_abstain = next(row for row in t3["scenarios"] if row["id"] == "sc-08-healthy-calm-abstain")
        self.assertTrue(sc_abstain["v16"]["abstained"])

        t4 = report["track4_real_holdout"]
        self.assertGreater(t4["v16_post_fix"]["f1"], t4["v15_baseline"]["f1"])
        self.assertEqual(t4["v16_post_fix"]["noise_turn_false_positives"], 0)
        self.assertGreaterEqual(t4["v16_post_fix"]["f1"], 0.9)

        # AsyncHintCache abstains cleanly when LLM returns {"abstain": true}
        fake_key = "sk-" + "cp-mock-abstain-000"
        with patch.dict(os.environ, {"COMPASS_LLM_API_KEY": fake_key, "SAMPLE_MODE": "false"}, clear=True):
            with patch("project_compass.agent_hints.chat_completion_text", return_value=('{"abstain":true}', "")):
                cache = AsyncHintCache()
                healthy = {
                    "project": {"evidence_count": 2},
                    "team": {"facts": [
                        {"id": "g1", "kind": "goal", "value": "G", "status": "accepted", "evidence_ids": ["e1"]},
                        {"id": "n1", "kind": "task", "subject_key": "project.next_step", "value": "N", "status": "accepted", "evidence_ids": ["e2"]},
                    ]},
                    "next_consensus": {"id": "n1", "value": "N", "status": "accepted", "evidence_ids": ["e2"]},
                    "decision_summary": {"premises": [], "open_forks": [], "rejected_paths": []},
                    "activity_stream": [],
                    "evidence": [{"id": "e1"}, {"id": "e2"}],
                }
                cache.get_or_schedule("rev-calm", healthy, sample_mode=False)
                for _ in range(25):
                    hints, gen = cache.get_or_schedule("rev-calm", healthy, sample_mode=False)
                    if gen > 0:
                        self.assertEqual(hints, [])
                        break
                    import time
                    time.sleep(0.02)


        # Ensure subdirectory /compass/sub-pkg never falsely matches /compass transcript
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent_proj = root / "compass"
            child_proj = parent_proj / "sub-pkg"
            parent_proj.mkdir()
            child_proj.mkdir()
            brain = root / "brain"
            child_tx = brain / "conv-child" / ".system_generated" / "logs" / "transcript.jsonl"
            child_tx.parent.mkdir(parents=True)
            child_tx.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"<USER_REQUEST>Workspace: {child_proj}</USER_REQUEST>"}) + "\n",
                encoding="utf-8",
            )
            self.assertIsNone(discover_active_antigravity_transcript(parent_proj, brain_root=brain))

    def test_pbr_regression_guards_accepted_not_hiding_newer_draft_and_exit_code_none(self) -> None:
        # 1. Newer same-author proposed anchor update must NOT be hidden under older accepted anchor
        t1 = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
        q1 = "旧定案：发布 v1.4.0"
        q2 = "新提议：切换到 v1.6 策略顾问"
        e1 = EvidenceEvent("n1", "s1", "fang", "user_message", q1, t1, {"member_id": "fang"})
        p1 = EvidenceEvent("p1", "s1", "fang", "fact_proposal", q1, t1, {"member_id": "fang", "facts": [{"kind": "task", "subject_key": "project.next_step", "value": q1, "quote": q1, "source_id": "n1", "source_start": 0, "source_end": len(q1)}]})
        e2 = EvidenceEvent("n2", "s1", "fang", "user_message", q2, t2, {"member_id": "fang"})
        p2 = EvidenceEvent("p2", "s1", "fang", "fact_proposal", q2, t2, {"member_id": "fang", "facts": [{"kind": "task", "subject_key": "project.next_step", "value": q2, "quote": q2, "source_id": "n2", "source_start": 0, "source_end": len(q2)}]})
        # Get real derived fact id of old q1
        pre = build_dashboard_state([e1, p1, e2, p2])
        old_fact_id = next(f["id"] for f in pre["team"]["facts"] if q1 in f["value"])
        reviews = [{"action": "accept_fact", "fact_id": old_fact_id, "subject_key": "project.next_step", "reviewer": "fang"}]
        post = build_dashboard_state([e1, p1, e2, p2], review_history=reviews, fact_reviews=reviews)
        new_fact = next(f for f in post["team"]["facts"] if q2 in f["value"])
        self.assertEqual(new_fact["status"], "proposed")
        self.assertFalse(new_fact.get("superseded_by_fact_id"))

        # 2. Missing exit_code on test_result must NOT verify a premise; inequality <50ms must extract
        rich = extract_dialogue_rich_facts("前提是响应延迟 < 50ms 且吞吐 > 1000 req/s。", "user_statement")
        self.assertTrue(any(f.get("kind") == "assumption" and "< 50ms" in f["quote"] for f in rich))
        ep_src = EvidenceEvent("e-prem", "s1", "fang", "user_message", "前提是延迟 < 50ms。", t1, {"member_id": "fang", "facts": rich})
        ep_test_none = EvidenceEvent("e-res", "s1", "antigravity", "test_result", "延迟 < 50ms crash without exit code", t2, {"member_id": "fang"})
        st_none = build_dashboard_state([ep_src, ep_test_none])
        prem = next(f for f in st_none["team"]["facts"] if f["kind"] == "assumption")
        self.assertEqual(prem["decision_context"]["premise_status"], "unverified")

    def test_large_multi_session_discovery_and_session_uuid_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / "compass"
            proj.mkdir()
            brain = root / "brain"

            # Older small session mentioning proj at byte 0
            old_tx = brain / "conv-old-small" / ".system_generated" / "logs" / "transcript.jsonl"
            old_tx.parent.mkdir(parents=True)
            old_tx.write_text(
                json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": f"<USER_REQUEST>Old {proj}</USER_REQUEST>"}) + "\n",
                encoding="utf-8",
            )
            os.utime(old_tx, (1700000000, 1700000000))

            # Newer > 1 MB session where project path ONLY appears around byte ~300 KB
            active_tx = brain / "conv-real-uuid-123" / ".system_generated" / "logs" / "transcript.jsonl"
            active_tx.parent.mkdir(parents=True)
            filler = "pad_word " * 12000  # ~108 KB
            lines = [
                json.dumps({"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "<USER_REQUEST>开始重构</USER_REQUEST>"}),
                json.dumps({"step_index": 2, "source": "MODEL", "type": "GENERIC", "content": filler * 3}),
                json.dumps({"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": f"cd {proj} && pytest"}}]}),
                json.dumps({"step_index": 4, "source": "MODEL", "type": "GENERIC", "content": filler * 8}),
            ]
            active_tx.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # Even newer subagent & workflow-child decoys referencing proj must NEVER hijack human session
            sub_tx = brain / "conv-subagent" / ".system_generated" / "logs" / "transcript.jsonl"
            sub_tx.parent.mkdir(parents=True)
            sub_tx.write_text(
                "\n".join([
                    json.dumps({"step_index": 0, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "content": f"Check {proj}"}),
                    json.dumps({"step_index": 1, "source": "MODEL", "type": "GENERIC", "content": f'"USER_EXPLICIT" {proj}'}),
                ]) + "\n",
                encoding="utf-8",
            )
            wf_tx = brain / "conv-workflow" / ".system_generated" / "logs" / "transcript.jsonl"
            wf_tx.parent.mkdir(parents=True)
            wf_tx.write_text(
                json.dumps({
                    "step_index": 0,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": f"<USER_REQUEST>Check {proj}\nWhen you are done, call the finish tool with your result.\n</USER_REQUEST>",
                }) + "\n",
                encoding="utf-8",
            )
            os.utime(active_tx, (1800000000, 1800000000))
            os.utime(sub_tx, (1900000000, 1900000000))
            os.utime(wf_tx, (1900000010, 1900000010))

            hit = discover_active_antigravity_transcript(proj, brain_root=brain)
            self.assertEqual(hit, active_tx)
            self.assertEqual(infer_transcript_session_id(hit), "conv-real-uuid-123")

    def test_human_attribution_ask_question_capture_noise_filtering_and_zero_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            ws_root = root / "ws"
            ws = ProjectWorkspace(ws_root, repo)
            t0 = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
            q_accepted = "完成 v1.4.0 发布与截图"
            ev_note = EvidenceEvent("note-1", "web-quick-note", "fang", "user_message", q_accepted, t0, {"member_id": "fang"})
            ev_prop = EvidenceEvent("prop-1", "web-quick-note", "fang", "fact_proposal", q_accepted, t0, {
                "member_id": "fang",
                "facts": [{"kind": "task", "subject_key": "project.next_step", "value": q_accepted, "quote": q_accepted, "source_id": "note-1", "source_start": 0, "source_end": len(q_accepted)}],
            })
            ws.save([ev_note, ev_prop], complete_scan=True)
            pre = build_dashboard_state(ws.load(), str(repo))
            acc_fid = next(f["id"] for f in pre["team"]["facts"] if q_accepted in f["value"])
            acc_rev = {"action": "accept_fact", "fact_id": acc_fid, "subject_key": "project.next_step", "reviewer": "fang"}
            ws.save_review_state([], [acc_rev], [acc_rev])

            brain = root / "brain"
            tx = brain / "conv-human-1" / ".system_generated" / "logs" / "transcript.jsonl"
            tx.parent.mkdir(parents=True)
            tx.write_text("\n".join([
                json.dumps({
                    "step_index": 1,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "created_at": "2026-11-20T09:00:00Z",
                    "content": f"<USER_REQUEST>Workspace: {repo}\n前提是我们先提交到 GitHub，对吧？</USER_REQUEST>",
                }, ensure_ascii=False),
                json.dumps({
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "created_at": "2026-11-20T09:01:00Z",
                    "content": "### 两种路线对比与待拍板选项\n\n接下来要不要趁热打铁重构？",
                    "tool_calls": [{"name": "ask_question", "args": {"questions": []}}],
                }, ensure_ascii=False),
                json.dumps({
                    "step_index": 3,
                    "source": "MODEL",
                    "type": "GENERIC",
                    "created_at": "2026-11-20T09:02:00Z",
                    "content": "Created At: 2026-11-20T09:02:00Z\nA1: (Recommended) 保持清爽米白纸面高对比主题\nA2: 1和2",
                }, ensure_ascii=False),
            ]) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"COMPASS_ANTIGRAVITY_BRAIN_DIR": str(brain), "SAMPLE_MODE": "false"}, clear=False):
                srv = build_sidecar_server(repo, port=0, workspace_root=ws_root)
                try:
                    st = srv.dashboard_state()
                    self.assertEqual(st["intake"]["thread_id"], "conv-human-1")
                    self.assertEqual(st["intake"]["member_id"], "fang")
                    self.assertEqual(st["team"]["conflicts"], [])
                    texts = [f["value"] for f in st["team"]["facts"]]
                    self.assertTrue(any("保持清爽米白纸面高对比主题" in v for v in texts))
                    self.assertFalse(any("对吧" in v or "要不要" in v or "两种路线对比" in v for v in texts))
                    self.assertFalse(any(v == "A2: 1和2" for v in texts))
                finally:
                    srv.server_close()

    def test_tight_causal_linking_and_delta_polling_plus_hint_cooldown(self) -> None:
        t0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
        q_prem = "前提是磁盘路径索引延迟 < 20ms"
        q_rej = "放弃引入外部重型图数据库，因为安装太重。"
        q_dist = "采用清晰字体排版与窄栏布局"
        evs = [
            EvidenceEvent("e-p", "same-sess", "fang", "user_message", q_prem, t0, {"step_index": 2, "member_id": "fang", "facts": extract_dialogue_rich_facts(q_prem, "user_statement")}),
            EvidenceEvent("e-r", "same-sess", "fang", "user_message", q_rej, t0, {"step_index": 10, "member_id": "fang", "facts": extract_dialogue_rich_facts(q_rej, "user_statement")}),
            EvidenceEvent("e-d", "same-sess", "fang", "user_message", q_dist, t0, {"step_index": 15, "member_id": "fang", "facts": extract_dialogue_rich_facts(q_dist, "user_statement")}),
        ]
        st = build_dashboard_state(evs)
        rej_fact = next(f for f in st["team"]["facts"] if f["decision_stage"] == "rejected_path") if any("decision_stage" in f for f in st["team"]["facts"]) else next(f for f in st["team"]["facts"] if f["decision_context"]["stage"] == "rejected_path")
        dist_fact = next(f for f in st["team"]["facts"] if "窄栏布局" in f["value"])
        self.assertEqual(rej_fact["decision_context"]["premises"], [])
        self.assertEqual(dist_fact["decision_context"]["premises"], [])

        # Verify delta polling (?since_version), intake.refreshable=False, and AsyncHintCache 60s cooldown + superseded filter
        from threading import Thread
        srv = create_dashboard_server(evs, host="127.0.0.1", port=0, intake_status={"enabled": True}, refresh_callback=None)
        t = Thread(target=srv.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            full_raw = urlopen(f"{base}/api/state", timeout=5).read()
            full = json.loads(full_raw.decode("utf-8"))
            self.assertFalse(full["intake"]["refreshable"])
            ver = full["state_version"]
            delta_raw = urlopen(f"{base}/api/state?since_version={ver}", timeout=5).read()
            delta = json.loads(delta_raw.decode("utf-8"))
            self.assertTrue(delta["unchanged"])
            self.assertEqual(delta["state_version"], ver)
            self.assertLess(len(delta_raw), 2048)
            self.assertLess(len(delta_raw), len(full_raw))
        finally:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=2)

        fake_key = "sk-" + "cp-mock-cooldown-000"
        calls: list[str] = []

        def fake_llm(_msgs, **_kwargs):
            calls.append(json.dumps(_msgs, ensure_ascii=False))
            return ('{"abstain":false,"category":"推进建议","text":"继续验证真实对话抽样覆盖率。","evidence_id":"e-p"}', "")

        with patch.dict(os.environ, {"COMPASS_LLM_API_KEY": fake_key, "SAMPLE_MODE": "false"}, clear=True):
            with patch("project_compass.agent_hints.chat_completion_text", side_effect=fake_llm):
                cache = AsyncHintCache(cooldown_sec=60.0)
                st_copy = json.loads(json.dumps(st))
                # Inject a superseded fact that must be stripped from LLM snapshot
                st_copy["team"]["facts"].append({
                    "id": "old-superseded",
                    "kind": "task",
                    "status": "proposed",
                    "value": "OBSOLETE_V13_NOISE_TASK",
                    "short_title": "OBSOLETE_V13_NOISE_TASK",
                    "superseded_by_fact_id": "new-1",
                    "evidence_ids": ["e-d"],
                })
                cache.get_or_schedule("rev-a", st_copy, sample_mode=False)
                for _ in range(30):
                    hints_a, gen_a = cache.get_or_schedule("rev-a", st_copy, sample_mode=False)
                    if gen_a > 0:
                        break
                    import time
                    time.sleep(0.02)
                # Mutate state so rev-b + snap_key differ, within 60s cooldown -> must NOT call LLM again
                st_copy["team"]["facts"].append({"id": "new-extra", "kind": "decision", "status": "accepted", "value": "新增定案测试", "short_title": "新增定案测试", "evidence_ids": ["e-d"]})
                cache.get_or_schedule("rev-b", st_copy, sample_mode=False)
                import time
                time.sleep(0.05)
                self.assertEqual(len(calls), 1)
                self.assertNotIn("OBSOLETE_V13_NOISE_TASK", calls[0])

    def test_gemini_pbr_session_id_and_dense_secret_excerpt_guard(self) -> None:
        self.assertEqual(infer_transcript_session_id("/logs/transcript.jsonl"), "transcript")
        nested = Path("/tmp/virtual_symlink/conv-uuid-888/.system_generated/logs/transcript.jsonl")
        self.assertEqual(infer_transcript_session_id(nested), "conv-uuid-888")

        t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
        secret = "sk" + "-proj-" + "secret1234567890abcdef"
        events = [
            EvidenceEvent(f"ev-{i}", "conv-uuid-888", "fang", "user_message", f"ordinary update {i}", t0, {"member_id": "fang"})
            for i in range(405)
        ]
        events.append(
            EvidenceEvent(
                "ev-secret-tail",
                "conv-uuid-888",
                "fang",
                "user_message",
                ("public prefix context " * 45) + f" token={secret}",
                t0,
                {"member_id": "fang"},
            )
        )
        dense_state = build_dashboard_state(events)
        secret_entry = next(item for item in dense_state["evidence"] if item["id"] == "ev-secret-tail")
        self.assertNotIn("search_excerpt", secret_entry)

    def test_local_agent_hints_exclude_superseded_and_rejected_decision_summary(self) -> None:
        state = {
            "project": {"evidence_count": 3},
            "team": {
                "facts": [
                    {"id": "g-1", "kind": "goal", "subject_key": "project.goal", "value": "打造清晰面板", "status": "accepted", "evidence_ids": ["e1"]},
                    {"id": "n-1", "kind": "task", "subject_key": "project.next_step", "value": "完善测试", "status": "accepted", "evidence_ids": ["e2"]},
                    {"id": "p-sup", "kind": "assumption", "value": "旧假设已取代", "status": "proposed", "superseded_by_fact_id": "p-new", "evidence_ids": ["e1"]},
                    {"id": "f-rej", "kind": "decision", "value": "已驳回分叉", "status": "proposed", "evidence_ids": ["e3"]},
                ]
            },
            "review_history": [{"action": "reject_fact", "fact_id": "f-rej"}],
            "decision_summary": {
                "premises": [{"fact_id": "p-sup", "title": "旧假设已取代", "status": "invalidated", "evidence_ids": ["e1"]}],
                "open_forks": [{"fact_id": "f-rej", "title": "已驳回分叉", "alternatives": ["A", "B"], "evidence_ids": ["e3"]}],
                "rejected_paths": [{"fact_id": "p-sup", "title": "旧假设已取代", "reason": "过时", "evidence_ids": ["e1"]}],
            },
            "activity_stream": [],
        }
        local = build_local_agent_hints(state)
        self.assertFalse(any(h.get("fact_id") in {"p-sup", "f-rej"} for h in local))


if __name__ == "__main__":
    unittest.main()
