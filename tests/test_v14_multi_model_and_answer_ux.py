from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from project_compass.cli import _review_callback
from project_compass.investigator import investigate
from project_compass.llm_connector import (
    available_llm_profiles,
    chat_completion_text,
    parse_llm_credential_file,
    public_llm_status,
    reset_active_llm_profile,
    resolve_llm_config,
    set_active_llm_profile,
)
from project_compass.models import EvidenceEvent, EvidenceRelation
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


class V14MultiModelAndAnswerUXTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_llm_profile()

    def tearDown(self) -> None:
        reset_active_llm_profile()

    def test_parse_kv_and_single_line_credential_files_and_multi_profile_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            minimax_note = root / "mm.md"
            deepseek_note = root / "ds.md"
            fake_mm_key = "sk-" + "cp-fake-minimax-key-01"
            fake_ds_key = "sk-" + "fake-deepseek-key-02"
            minimax_note.write_text(f"{fake_mm_key}\n11月测试\n", encoding="utf-8")
            deepseek_note.write_text(
                f"base_url:https://api.deepseek.com\napi_key:{fake_ds_key}\n",
                encoding="utf-8",
            )

            parsed_mm = parse_llm_credential_file(str(minimax_note))
            parsed_ds = parse_llm_credential_file(str(deepseek_note))
            self.assertEqual(parsed_mm["api_key"], fake_mm_key)
            self.assertIn("minimaxi.com", parsed_mm["base_url"])
            self.assertEqual(parsed_ds["api_key"], fake_ds_key)
            self.assertEqual(parsed_ds["base_url"], "https://api.deepseek.com/v1/chat/completions")

            with patch.dict(
                os.environ,
                {
                    "COMPASS_LLM_KEY_FILES": f"{minimax_note};{deepseek_note}",
                    "COMPASS_LLM_MODEL": "MiniMax-M3.1-Flash",
                    "SAMPLE_MODE": "false",
                },
                clear=True,
            ):
                cfg = resolve_llm_config()
                self.assertTrue(cfg["enabled"])
                self.assertEqual(cfg["model"], "MiniMax-M3.1-Flash")
                self.assertEqual(cfg["active_profile"], "minimax-m3.1-flash")

                profiles = available_llm_profiles()
                ids = [item["id"] for item in profiles]
                self.assertIn("minimax-m3.1-flash", ids)
                self.assertIn("minimax-m2.7", ids)
                self.assertIn("deepseek-chat", ids)
                self.assertEqual(ids[-1], "local")

                # Secrets & local note paths never appear in public_llm_status()
                pub = public_llm_status()
                pub_dump = json.dumps(pub, ensure_ascii=False)
                self.assertNotIn(fake_mm_key, pub_dump)
                self.assertNotIn(fake_ds_key, pub_dump)
                self.assertNotIn("mm.md", pub_dump)
                self.assertNotIn("api_key", pub_dump)
                self.assertNotIn("base_url", pub_dump)

                # Runtime switching between models & local works cleanly
                set_active_llm_profile("deepseek-chat")
                cfg_ds = resolve_llm_config()
                self.assertEqual(cfg_ds["model"], "deepseek-chat")
                self.assertEqual(cfg_ds["base_url"], "https://api.deepseek.com/v1/chat/completions")

                set_active_llm_profile("local")
                cfg_local = resolve_llm_config()
                self.assertFalse(cfg_local["enabled"])
                self.assertEqual(public_llm_status()["active_profile"], "local")
                self.assertTrue(len(public_llm_status()["profiles"]) >= 3)

                with self.assertRaises(ValueError):
                    set_active_llm_profile("unknown-provider")

            # Changing env automatically invalidates stale override
            with patch.dict(os.environ, {"SAMPLE_MODE": "true"}, clear=True):
                self.assertEqual(available_llm_profiles(), [])
                self.assertFalse(resolve_llm_config()["enabled"])

    def test_compound_goal_and_next_question_surfaces_settled_next_step_with_unrelated_conflict(self) -> None:
        t0 = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 11, 16, 2, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
        ev_goal = EvidenceEvent(
            "note-goal",
            "s1",
            "fang",
            "user_message",
            "打造高掌控项目掌控台",
            t0,
            {
                "member_id": "fang",
                "facts": [
                    {
                        "kind": "goal",
                        "subject_key": "project.goal",
                        "value": "打造高掌控项目掌控台",
                        "quote": "打造高掌控项目掌控台",
                    }
                ],
            },
        )
        ev_conflict_a = EvidenceEvent(
            "ev-ca",
            "s1",
            "fang",
            "user_message",
            "方案选择 A",
            t0,
            {
                "member_id": "fang",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "design.choice",
                        "value": "采用方案 A",
                        "quote": "方案选择 A",
                    }
                ],
            },
        )
        ev_conflict_b = EvidenceEvent(
            "ev-cb",
            "s1",
            "fang",
            "user_message",
            "方案选择 B",
            t1,
            {
                "member_id": "fang",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "design.choice",
                        "value": "采用方案 B",
                        "quote": "方案选择 B",
                    }
                ],
            },
        )
        ev_next = EvidenceEvent(
            "note-next",
            "s1",
            "fang",
            "user_message",
            "完成双极速模型横评并封板 v1.4",
            t2,
            {
                "member_id": "fang",
                "facts": [
                    {
                        "kind": "task",
                        "subject_key": "project.next_step",
                        "value": "完成双极速模型横评并封板 v1.4",
                        "quote": "完成双极速模型横评并封板 v1.4",
                        "task_state": "pending",
                    }
                ],
            },
        )
        events = [ev_goal, ev_conflict_a, ev_conflict_b, ev_next]
        from project_compass.fact_engine import derive_facts

        facts = derive_facts(events)
        goal_fact = next(f for f in facts if f.subject_key == "project.goal")
        next_fact = next(f for f in facts if f.subject_key == "project.next_step")
        reviews = [
            {"action": "accept_fact", "fact_id": goal_fact.id, "subject_key": "project.goal", "reviewer": "fang", "observed_at": t1.isoformat()},
            {"action": "accept_fact", "fact_id": next_fact.id, "subject_key": "project.next_step", "reviewer": "fang", "observed_at": t2.isoformat()},
        ]
        answer = investigate(events, "当前的目标是什么？接下来做什么？", reviews, []).to_dict()
        self.assertEqual(answer["goal"], "打造高掌控项目掌控台")
        self.assertEqual(answer["next_action"], "完成双极速模型横评并封板 v1.4")
        self.assertEqual(answer["next_action_status"], "accepted")
        finding_quotes = [row["quote"] for row in answer["findings"]]
        self.assertIn("打造高掌控项目掌控台", finding_quotes)
        self.assertIn("完成双极速模型横评并封板 v1.4", finding_quotes)

    def test_post_llm_mode_endpoint_clears_caches_and_validates_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_root = root / "ws"
            repo = root / "repo"
            repo.mkdir()
            mm_note = root / "mm.md"
            ds_note = root / "ds.md"
            mm_note.write_text("sk-" + "cp-fake-mm-srv\n", encoding="utf-8")
            ds_note.write_text("base_url:https://api.deepseek.com\napi_key:" + "sk-" + "fake-ds-srv\n", encoding="utf-8")

            ev = EvidenceEvent(
                "ev-1",
                "s1",
                "fang",
                "user_message",
                "记录首条目标",
                datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc),
                {"member_id": "fang"},
            )
            ws = ProjectWorkspace(ws_root, repo)
            ws.save([ev], complete_scan=True)
            events = ws.load()
            cb, confirmed, history, reviews = _review_callback(events, ws, str(repo), [], [], [])

            with patch.dict(
                os.environ,
                {
                    "COMPASS_LLM_KEY_FILES": f"{mm_note};{ds_note}",
                    "COMPASS_LLM_MODEL": "MiniMax-M3.1-Flash",
                    "SAMPLE_MODE": "false",
                },
                clear=True,
            ):
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
                srv.investigation_cache[("rev", "", "q")] = {"conclusion": "stale"}
                t = Thread(target=srv.serve_forever, daemon=True)
                t.start()
                base = f"http://127.0.0.1:{srv.server_address[1]}"
                try:
                    req = Request(
                        f"{base}/api/llm-mode",
                        data=json.dumps({"profile_id": "deepseek-chat"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(req, timeout=5) as resp:
                        state_payload = json.loads(resp.read().decode("utf-8"))
                    self.assertEqual(state_payload["llm_status"]["active_profile"], "deepseek-chat")
                    self.assertEqual(state_payload["llm_status"]["model"], "deepseek-chat")
                    self.assertEqual(state_payload["llm_status"]["provider_label"], "AI 辅助 · deepseek-chat")
                    self.assertEqual(len(srv.investigation_cache), 0)

                    bad_req = Request(
                        f"{base}/api/llm-mode",
                        data=json.dumps({"profile_id": "nonexistent"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as ctx:
                        urlopen(bad_req, timeout=5)
                    self.assertEqual(ctx.exception.code, 400)
                finally:
                    srv.shutdown()
                    srv.server_close()
                    t.join(timeout=2)

    def test_chat_completion_sets_reasoning_effort_low_only_for_m31_flash(self) -> None:
        captured: list[dict] = []

        class _FakeResp:
            def __init__(self, text: str) -> None:
                self._raw = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")

            def read(self) -> bytes:
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_open(req, timeout=8.0):
            captured.append(json.loads(req.data.decode("utf-8")))
            return _FakeResp("OK")

        fake_mm = "sk-" + "cp-fake-flash-only"
        with patch.dict(
            os.environ,
            {"COMPASS_LLM_API_KEY": fake_mm, "COMPASS_LLM_MODEL": "MiniMax-M3.1-Flash", "SAMPLE_MODE": "false"},
            clear=True,
        ):
            reply, err = chat_completion_text([{"role": "user", "content": "hi"}], max_tokens=8192, urlopen_fn=fake_open)
            self.assertEqual((reply, err), ("OK", ""))
            self.assertEqual(captured[-1]["reasoning_effort"], "low")
            self.assertEqual(captured[-1]["max_tokens"], 8192)

        fake_ds = "sk-" + "fake-ds-only"
        with patch.dict(
            os.environ,
            {"COMPASS_LLM_API_KEY": fake_ds, "COMPASS_LLM_MODEL": "deepseek-chat", "SAMPLE_MODE": "false"},
            clear=True,
        ):
            reply2, err2 = chat_completion_text([{"role": "user", "content": "hi"}], urlopen_fn=fake_open)
            self.assertEqual((reply2, err2), ("OK", ""))
            self.assertNotIn("reasoning_effort", captured[-1])

    def test_parallel_minimax_and_deepseek_env_keys_expose_all_profiles(self) -> None:
        fake_mm = "sk-cp-" + "fake-mm-env"
        fake_ds = "sk-" + "fake-ds-env"
        with patch.dict(
            os.environ,
            {
                "MINIMAX_API_KEY": fake_mm,
                "DEEPSEEK_API_KEY": fake_ds,
                "COMPASS_LLM_MODEL": "MiniMax-M3.1-Flash",
                "SAMPLE_MODE": "false",
            },
            clear=True,
        ):
            reset_active_llm_profile()
            profiles = available_llm_profiles()
            ids = [p["id"] for p in profiles]
            self.assertEqual(ids, ["minimax-m3.1-flash", "minimax-m2.7", "deepseek-chat", "local"])
            cfg = resolve_llm_config()
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["model"], "MiniMax-M3.1-Flash")


if __name__ == "__main__":
    unittest.main()
