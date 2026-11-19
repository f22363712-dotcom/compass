from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

from project_compass.agent_hints import synthesize_investigation_summary
from project_compass.candidate_extraction import validate_candidates
from project_compass.doc_fact_intake import record_document_candidates
from project_compass.extraction_progress import ExtractionProgress
from project_compass.fact_engine import derive_facts
from project_compass.intent_vocab import is_recent_completed_query
from project_compass.investigator import investigate
from project_compass.llm_connector import reset_active_llm_profile, set_active_llm_profile
from project_compass.models import EvidenceEvent
from project_compass.project_refresh import ProjectRescan
from project_compass.project_scanner import scan_project, watched_docs_signature
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


class RecentCompletedAndLiveDocSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_llm_profile()

    def tearDown(self) -> None:
        reset_active_llm_profile()

    def test_handoff_colon_stages_and_decisions_heading_extraction_preserve_legacy_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text(
                "# Demo\n\nBuild an append-only local control console for coding agents.\n",
                encoding="utf-8",
            )
            (root / "DECISIONS.md").write_text(
                "# Decisions\n\n### 2026-11-17: Auto sync markdown changes without restarting server\n\n- Context: avoid stale answers.\n",
                encoding="utf-8",
            )
            (root / "HANDOFF.md").write_text(
                "# Handoff\n\n"
                "1. **v1.1 · 基础看板落地（已验收交付）**：\n   - detail\n"
                "2. **v1.4 · 近期完成检索与热同步（2026-11-17 已完成封板）**：\n   - detail\n",
                encoding="utf-8",
            )
            ws_root = Path(tmp) / "ws"
            ws = ProjectWorkspace(ws_root, root)
            # Simulate an existing legacy doc-fact-rules cursor namespace from v1.0/v1.3.
            legacy_prog = ExtractionProgress(ws.state_path.parent / "doc-fact-rules", namespace="doc-structure-v1:scan-v1")
            legacy_prog.acknowledge({"a" * 64: 10})

            events = scan_project(root)
            ws.save(events, {"source": "scan"}, complete_scan=True)
            events = ws.load()

            first = record_document_candidates(events, ws)
            self.assertTrue(first["updated"])
            facts = derive_facts(ws.load())
            dec_quotes = [f.quote or f.value for f in facts if f.kind.value == "decision"]
            self.assertTrue(any("2026-11-17: Auto sync markdown changes" in q for q in dec_quotes))
            done_tasks = [f for f in facts if f.kind.value == "task" and f.task_state == "reported_complete"]
            self.assertTrue(any("v1.4 · 近期完成检索与热同步" in (f.quote or f.value) for f in done_tasks))

            second = record_document_candidates(ws.load(), ws)
            self.assertFalse(second["updated"])

    def test_agents_md_fallback_goal_and_watched_signature_skips_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "drama"
            (root / "assets").mkdir(parents=True)
            (root / "assets" / "clip.mp4").write_bytes(b"binary-video")
            (root / "AGENTS.md").write_text(
                "# Studio Rules\n\n> 本文件由创作者对齐确定，用于电影级 AI 漫剧半自动制片与质量卡点控制。\n",
                encoding="utf-8",
            )
            sig1 = watched_docs_signature(root)
            self.assertIsNotNone(sig1)
            self.assertEqual([name for name, _, _ in sig1], ["AGENTS.md"])

            ws = ProjectWorkspace(Path(tmp) / "ws", root)
            events = scan_project(root)
            ws.save(events, {"source": "scan"}, complete_scan=True)
            events = ws.load()
            res = record_document_candidates(events, ws)
            self.assertTrue(res["updated"])
            goals = [f for f in derive_facts(ws.load()) if f.kind.value == "goal"]
            self.assertEqual(len(goals), 1)
            self.assertIn("电影级 AI 漫剧", goals[0].value)

    def test_recent_completed_query_excludes_pending_and_orders_latest_first(self) -> None:
        self.assertTrue(is_recent_completed_query("最近完成的工作是什么"))
        self.assertTrue(is_recent_completed_query("刚刚完成了哪些任务？"))
        self.assertFalse(is_recent_completed_query("还有什么未完成的工作"))

        now_t1 = datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc)
        now_t2 = datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)
        now_t3 = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
        q_old = "v1.1 本机联调已完成"
        q_pending = "完成 v1.5 发布检查清单"
        q_new = "2026-11-17 v1.4.0 实时同步与热重载已验收交付"
        q_goal = "实时开发纪要与低认知负载项目掌控台"
        sources = [
            EvidenceEvent("e-goal", "s1", "fang", "user_message", q_goal, now_t1, {"member_id": "fang"}),
            EvidenceEvent("e-old", "s1", "fang", "user_message", q_old, now_t1, {"member_id": "fang"}),
            EvidenceEvent("e-pending", "s1", "fang", "user_message", q_pending, now_t2, {"member_id": "fang"}),
            EvidenceEvent("e-new", "s1", "fang", "user_message", q_new, now_t3, {"member_id": "fang"}),
        ]
        proposals = validate_candidates(
            sources,
            {
                "candidates": [
                    {"source_id": "e-goal", "kind": "goal", "subject_key": "project.goal", "quote": q_goal},
                    {"source_id": "e-old", "kind": "task", "subject_key": "doc.task.old", "quote": q_old, "task_state": "reported_complete"},
                    {"source_id": "e-pending", "kind": "task", "subject_key": "project.next_step", "quote": q_pending, "task_state": "pending"},
                    {"source_id": "e-new", "kind": "task", "subject_key": "doc.task.new", "quote": q_new, "task_state": "reported_complete"},
                ]
            },
        )
        events = [*sources, *proposals]
        reviews = [{"action": "accept_fact", "fact_id": "fact-pending-or-ignored", "subject_key": "other", "reviewer": "fang"}]
        ans = investigate(events, "最近完成的工作是什么", reviews, current_member="fang").to_dict()
        items = ans.get("completed_items") or []
        self.assertGreaterEqual(len(items), 2)
        self.assertIn("v1.4.0", items[0]["quote"])
        self.assertTrue(all("v1.5 发布检查清单" not in row["quote"] for row in items))
        self.assertTrue(ans["conclusion"].startswith("近期已完成："))

    def test_live_http_server_auto_syncs_doc_changes_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "README.md").write_text(
                "# LiveSyncDemo\n\nProvide instant live sync for markdown docs without restart.\n",
                encoding="utf-8",
            )
            handoff = root / "HANDOFF.md"
            handoff.write_text("# Handoff\n\n- [x] 2026-11-16 初始框架已完成\n", encoding="utf-8")

            ws = ProjectWorkspace(Path(tmp) / "ws", root)
            initial = scan_project(root)
            ws.save(initial, {"source": "scan"}, complete_scan=True)
            events = ws.load()
            record_document_candidates(events, ws)
            events = ws.load()

            rescan = ProjectRescan(ws, events, extract_docs=True)
            rescan._last_sig_check_mono = 0.0
            srv = create_dashboard_server(
                events, host="127.0.0.1", port=0, project_path=str(root),
                rescan_callback=rescan.refresh,
                workspace_root=Path(tmp) / "ws",
                auto_doc_sync=lambda: rescan.sync_if_docs_changed(min_interval_sec=0.0),
            )
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            self.addCleanup(t.join, 3)
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            base = f"http://127.0.0.1:{srv.server_address[1]}"

            # Mutate HANDOFF.md on disk WITHOUT restarting the server.
            handoff.write_text(
                "# Handoff\n\n"
                "- [x] 2026-11-16 初始框架已完成\n"
                "- [x] 2026-11-17 自动增量热同步回归验收已完成\n",
                encoding="utf-8",
            )
            with urllib.request.urlopen(base + "/api/state", timeout=5) as resp:
                state_payload = json.load(resp)
            self.assertTrue(state_payload["project_scan"]["updated"])

            req = urllib.request.Request(
                base + "/api/investigate",
                data=json.dumps({"question": "最近完成的工作是什么"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                ans = json.load(resp)
            completed = ans.get("completed_items") or []
            self.assertTrue(completed)
            self.assertIn("自动增量热同步回归验收已完成", completed[0]["quote"])

    def test_synthesize_summary_uses_completed_items_and_cache_isolates_profiles(self) -> None:
        captured_payloads = []

        class _FakeResp:
            def __init__(self, body: dict):
                self._raw = json.dumps(body).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self._raw

        def fake_open(req, timeout=8.0):
            captured_payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeResp({"choices": [{"message": {"content": "最近已完成热同步升级 [e1]。"}}]})

        fake_mm = "sk-cp-" + "fake-mm-test"
        fake_ds = "sk-" + "fake-ds-test"
        with patch.dict(
            "os.environ",
            {"MINIMAX_API_KEY": fake_mm, "DEEPSEEK_API_KEY": fake_ds, "SAMPLE_MODE": "false"},
            clear=True,
        ):
            set_active_llm_profile("minimax-m3.1-flash")
            with patch("project_compass.llm_connector.urlopen", side_effect=fake_open):
                # Call synthesize directly with completed_items
                ans_dict = {
                    "goal": "项目掌控台",
                    "next_action": "发布开源",
                    "evidence_ids": ["e1"],
                    "findings": [],
                    "completed_items": [{"kind": "task", "status": "proposed", "observed_at": "2026-11-17T10:00:00Z", "evidence_ids": ["e1"], "quote": "2026-11-17 热同步已完成"}],
                }
                summary = synthesize_investigation_summary("最近完成的工作是什么", ans_dict)
                self.assertIn("热同步升级", summary)
                self.assertIn("completed_items", captured_payloads[0]["messages"][1]["content"])

            # Verify HTTP server investigation cache isolates active LLM profile
            now_t = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
            ev1 = EvidenceEvent("e1", "s1", "fang", "user_message", "2026-11-17 已完成测试", now_t, {"member_id": "fang"})
            props1 = validate_candidates(
                [ev1],
                {"candidates": [{"source_id": "e1", "kind": "task", "subject_key": "t1", "quote": "2026-11-17 已完成测试", "task_state": "reported_complete"}]},
            )
            srv = create_dashboard_server([ev1, *props1], port=0)
            set_active_llm_profile("local")
            local_res = srv.investigate("最近完成的工作是什么")
            self.assertIsNone(local_res.get("semantic_summary"))
            set_active_llm_profile("deepseek-chat")
            with patch("project_compass.llm_connector.urlopen", side_effect=fake_open):
                ds_res = srv.investigate("最近完成的工作是什么")
            self.assertEqual(ds_res.get("llm_status", {}).get("active_profile"), "deepseek-chat")
            self.assertTrue(ds_res.get("semantic_summary"))
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
