from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from project_compass.agent_hints import (
    AsyncHintCache,
    build_local_agent_hints,
    synthesize_investigation_summary,
)
from project_compass.candidate_extraction import validate_candidates
from project_compass.cli import _review_callback
from project_compass.dashboard import build_dashboard_state
from project_compass.investigator import investigate
from project_compass.llm_connector import (
    public_llm_status,
    resolve_llm_config,
    strip_model_thinking,
)
from project_compass.models import EvidenceEvent
from project_compass.project_workspace import ProjectWorkspace
from project_compass.text_summary import (
    clean_display_text,
    select_next_consensus,
    select_primary_goal,
)
from project_compass.web_server import create_dashboard_server


class V13GovernanceAndLLMConnectorTests(unittest.TestCase):
    def test_strip_model_thinking_and_resolve_llm_config(self):
        self.assertEqual(
            strip_model_thinking("<think>Internal draft</think>\n```json\n{\"ok\": true}\n```"),
            '{"ok": true}',
        )
        # Unclosed truncated think tag must never leak English draft
        self.assertEqual(strip_model_thinking("<think>Let me analyze the codebase"), "")

        fake_minimax_key = "sk-" + "cp-fake-minimax-token-123456"
        with patch.dict(
            os.environ,
            {"COMPASS_LLM_API_KEY": fake_minimax_key, "SAMPLE_MODE": "false"},
            clear=True,
        ):
            cfg = resolve_llm_config()
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["mode"], "cloud_llm")
            self.assertEqual(cfg["model"], "MiniMax-M2.7")
            self.assertIn("minimaxi.com", cfg["base_url"])
            pub = public_llm_status()
            self.assertEqual(pub["provider_label"], "AI 辅助 · MiniMax-M2.7")
            self.assertNotIn("api_key", pub)
            self.assertNotIn("base_url", pub)

        with patch.dict(
            os.environ,
            {"OLLAMA_HOST": "http://127.0.0.1:11434", "SAMPLE_MODE": "false"},
            clear=True,
        ):
            ollama_cfg = resolve_llm_config()
            self.assertTrue(ollama_cfg["enabled"])
            self.assertEqual(ollama_cfg["mode"], "local_llm")
            self.assertTrue(ollama_cfg["base_url"].endswith("/v1/chat/completions"))

        with patch.dict(
            os.environ,
            {"COMPASS_LLM_API_KEY": fake_minimax_key, "SAMPLE_MODE": "true"},
            clear=True,
        ):
            sample_cfg = resolve_llm_config()
            self.assertFalse(sample_cfg["enabled"])
            self.assertEqual(sample_cfg["mode"], "local")

    def test_goal_and_next_consensus_isolation_across_legacy_docs_and_live_notes(self):
        facts = [
            {
                "id": "g-doc",
                "kind": "goal",
                "subject_key": "goal.doc",
                "value": "README 中的长篇项目背景目标说明",
                "author": "project-documents",
                "status": "proposed",
                "evidence_ids": ["scan-file-readme"],
            },
            {
                "id": "g-live",
                "kind": "goal",
                "subject_key": "project.goal",
                "value": "打造高掌控感个人开发工作台",
                "author": "fang",
                "status": "accepted",
                "evidence_ids": ["note-1"],
            },
            {
                "id": "t-doc",
                "kind": "task",
                "subject_key": "task.o23",
                "value": "**O2.3 手工移出受保护的未追踪竞赛文档**",
                "author": "project-documents",
                "status": "proposed",
                "task_state": "pending",
                "evidence_ids": ["scan-file-plan"],
            },
            {
                "id": "d-live",
                "kind": "decision",
                "subject_key": "note.dec.1",
                "value": "先修通一框两用搜词追问体验",
                "author": "fang",
                "status": "proposed",
                "evidence_ids": ["note-2"],
            },
        ]
        self.assertEqual(select_primary_goal(facts)["id"], "g-live")
        # Legacy project-documents task is ignored; falls back to live pending candidate suggestion
        next_c = select_next_consensus(facts)
        self.assertIsNotNone(next_c)
        self.assertEqual(next_c["id"], "d-live")
        self.assertTrue(next_c["is_candidate_suggestion"])

        # Adding an explicit project.next_step task takes priority cleanly
        facts.append({
            "id": "t-next",
            "kind": "task",
            "subject_key": "project.next_step",
            "value": "完成 Agent 提示与全量评测对比",
            "author": "fang",
            "status": "accepted",
            "task_state": "pending",
            "evidence_ids": ["note-3"],
        })
        chosen_next = select_next_consensus(facts)
        self.assertEqual(chosen_next["id"], "t-next")
        self.assertEqual(clean_display_text("**O2.3** `app.js`"), "O2.3 app.js")

    def test_investigate_keyword_search_compound_questions_and_legacy_task_isolation(self):
        t0 = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
        doc_plan = EvidenceEvent(
            "scan-file-plan1",
            "scan",
            "project-documents",
            "file_snapshot",
            "- [ ] **O2.3 手工移出旧规划文档**\n\n正交思维脑图与双栏对照模块已在重构清单中。",
            t0,
            {"member_id": "project-documents", "source_ref": "docs/OLD_PLAN.md"},
        )
        live_msg = EvidenceEvent(
            "msg-live-1",
            "s1",
            "fang",
            "user_message",
            ("前期背景日志。" * 30) + " 我们确定启用正交思维脑图作为右侧生长视图，并通过文件锁保护并发写。",
            t0 + timedelta(minutes=5),
            {"member_id": "fang"},
        )
        live_goal = EvidenceEvent(
            "msg-goal-1",
            "s1",
            "fang",
            "user_message",
            "打造极简零配置个人掌控台",
            t0 + timedelta(minutes=6),
            {"member_id": "fang"},
        )
        prop_doc = validate_candidates(
            [doc_plan],
            {"candidates": [{"source_id": "scan-file-plan1", "kind": "task", "subject_key": "doc.plan.o23", "quote": "**O2.3 手工移出旧规划文档**", "task_state": "pending"}]},
        )
        prop_goal = validate_candidates(
            [live_goal],
            {"candidates": [{"source_id": "msg-goal-1", "kind": "goal", "subject_key": "project.goal", "quote": "打造极简零配置个人掌控台"}]},
        )
        events = [doc_plan, *prop_doc, live_msg, live_goal, *prop_goal]

        # 1. Bare Chinese keyword without question words returns raw findings (never refuses)
        kw_ans = investigate(events, "脑图").to_dict()
        self.assertFalse(any("尚未得到回答" in g for g in kw_ans["evidence_gaps"]))
        self.assertTrue(kw_ans["findings"])
        self.assertTrue(any("msg-live-1" in (f.get("evidence_ids") or []) for f in kw_ans["findings"]))

        # 2. Single-character noun search ("锁") works seamlessly
        lock_ans = investigate(events, "锁").to_dict()
        self.assertTrue(lock_ans["findings"])
        self.assertIn("msg-live-1", lock_ans["evidence_ids"])

        # 3. Compound question does NOT trigger unknown-member choice
        comp_ans = investigate(events, "当前目标是什么？接下来做什么？").to_dict()
        self.assertIsNone(comp_ans["scope"])
        self.assertEqual(comp_ans["goal"], "打造极简零配置个人掌控台")
        self.assertNotIn("O2.3", comp_ans["next_action"])

        # 4. Unknown human subject & translation query still behave strictly
        self.assertEqual(investigate(events, "Charlie 下一步做什么？").to_dict()["scope"]["kind"], "member_choice")
        trans = investigate(events, "Translate this note to French.").to_dict()
        self.assertTrue(any("尚未得到回答" in g for g in trans["evidence_gaps"]))

    def test_next_step_api_endpoint_async_hints_and_grounded_summary(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            ws_root = tmp / "ws"
            repo = tmp / "repo"
            repo.mkdir()
            ev = EvidenceEvent(
                "ev-init",
                "s1",
                "fang",
                "test_result",
                "FAILED unit check",
                datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc),
                {"member_id": "fang", "exit_code": 1},
            )
            ws = ProjectWorkspace(ws_root, repo)
            ws.save([ev], complete_scan=True)
            events = ws.load()
            cb, confirmed, history, reviews = _review_callback(events, ws, str(repo), [], [], [])
            srv = create_dashboard_server(
                events,
                host="127.0.0.1",
                port=0,
                project_path=str(repo),
                confirmed_relations=confirmed,
                review_history=history,
                fact_reviews=reviews,
                review_callback=cb,
                workspace_root=ws_root,
            )
            t = Thread(target=srv.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                body = json.dumps({
                    "text": "完成双锚点与 Agent 提示验证",
                    "kind": "task",
                    "topic": "next_step",
                    "auto_accept": True,
                    "reviewer": "fang",
                    "client_nonce": "next-1",
                }).encode("utf-8")
                req = Request(f"{base}/api/notes", data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req, timeout=5) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["next_consensus"]["short_title"], "完成双锚点与 Agent 提示验证")
                self.assertEqual(payload["next_consensus"]["status"], "accepted")
                # Check search_excerpt populated & local agent hints free of cringe copy
                cat_item = next(e for e in payload["evidence"] if e["id"] == "ev-init")
                self.assertIn("FAILED unit check", cat_item["search_excerpt"])
                hints_text = json.dumps(payload["agent_hints"], ensure_ascii=False)
                self.assertNotIn("军师", hints_text)
                self.assertNotIn("锦囊", hints_text)
            finally:
                srv.shutdown()
                srv.server_close()
                t.join(timeout=2)

        # Verify AsyncHintCache strips unknown citations and synthesize_investigation_summary sanitizes brackets
        fake_key = "sk-" + "cp-mock-key-000"
        with patch.dict(os.environ, {"COMPASS_LLM_API_KEY": fake_key, "SAMPLE_MODE": "false"}, clear=True):
            with patch(
                "project_compass.agent_hints.chat_completion_text",
                return_value=(
                    '{"category":"推进建议","text":"优先核查最近失败记录并补齐测试闭环","evidence_id":"ev-hallucinated"}',
                    "",
                ),
            ):
                cache = AsyncHintCache()
                sample_state = build_dashboard_state(
                    [EvidenceEvent("ev-real", "s1", "fang", "user_message", "记录目标", datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc), {"member_id": "fang"})]
                )
                sample_state["evidence"] = [{"id": "ev-real"}]
                cache.get_or_schedule("rev-1", sample_state, sample_mode=False)
                for _ in range(25):
                    hints, gen = cache.get_or_schedule("rev-1", sample_state, sample_mode=False)
                    if gen > 0:
                        break
                    time.sleep(0.02)
                self.assertEqual(hints[0]["source"], "llm")
                self.assertEqual(hints[0]["evidence_ids"], [])  # Hallucinated ev-hallucinated stripped!

            with patch(
                "project_compass.agent_hints.chat_completion_text",
                return_value=("已定位到正交脑图决策 [ev-real]，但 [ev-fake-999] 不存在。", ""),
            ):
                summary = synthesize_investigation_summary(
                    "脑图",
                    {"goal": "g", "next_action": "n", "evidence_ids": ["ev-real"], "findings": [{"quote": "正交脑图", "evidence_ids": ["ev-real"]}]},
                )
                self.assertIn("[ev-real]", summary)
                self.assertNotIn("ev-fake-999", summary)


if __name__ == "__main__":
    unittest.main()
