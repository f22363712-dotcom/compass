"""Tests for team role templates, AgentInbox role metadata, priority dispatch queue, and CLI setup."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_compass.agent_inbox import AgentInbox
from project_compass.fact_engine import derive_facts
from project_compass.mcp_setup import main as setup_main, render_agent_rules_snippet
from project_compass.models import EvidenceEvent
from project_compass.project_workspace import ProjectWorkspace
from project_compass.team_templates import (
    TEAM_TEMPLATES,
    build_team_config,
    extract_priority_dispatches,
    list_team_templates,
    record_priority_dispatch,
)


class TeamTemplatesAndDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "demo-project"
        self.project.mkdir()
        self.workspace = ProjectWorkspace(self.root / "state", self.project)

    def test_builtin_four_presets_and_summary_serialization(self) -> None:
        self.assertEqual(
            set(TEAM_TEMPLATES.keys()),
            {"solo", "product_delivery", "fullstack_engineering", "research_lab"},
        )
        summaries = list_team_templates()
        self.assertEqual(len(summaries), 4)
        encoded = json.dumps(summaries, ensure_ascii=False)
        self.assertIn("product_delivery", encoded)

        solo_cfg = build_team_config("solo", self.project)
        self.assertEqual(solo_cfg["mode"], "solo")
        self.assertIsNone(solo_cfg["agent_inbox_config"])
        self.assertEqual(solo_cfg["seats"], [])
        self.assertGreaterEqual(len(solo_cfg["local_sessions"]), 2)

        delivery_cfg = build_team_config("product_delivery", self.project)
        self.assertEqual(delivery_cfg["mode"], "team")
        self.assertEqual(delivery_cfg["owner_id"], "lead")
        self.assertEqual(delivery_cfg["owner_label"], "项目负责人")
        self.assertTrue(delivery_cfg["authority_model"]["two_tier_enforced"])
        delivery_seats = {s["member_id"]: s for s in delivery_cfg["seats"]}
        self.assertEqual(set(delivery_seats), {"planner", "developer", "qa"})
        self.assertEqual(delivery_seats["planner"]["role_label"], "产品与方案席")
        self.assertIn("需求拆解、边界梳理与待验证前提记录", delivery_seats["planner"]["role_brief"])
        self.assertEqual(delivery_seats["developer"]["role_label"], "研发实现席")
        self.assertEqual(delivery_seats["qa"]["role_label"], "测试与验收席")
        self.assertEqual(delivery_seats["planner"]["token_env"], "COMPASS_TOKEN_PLANNER")

        fs_cfg = build_team_config("fullstack_engineering", self.project)
        self.assertEqual(fs_cfg["owner_id"], "owner")
        self.assertEqual(fs_cfg["owner_label"], "技术负责人")
        self.assertEqual(
            [s["member_id"] for s in fs_cfg["seats"]],
            ["frontend", "backend", "reviewer"],
        )

        lab_cfg = build_team_config("research_lab", self.project)
        self.assertEqual(lab_cfg["owner_id"], "lead")
        self.assertEqual(lab_cfg["owner_label"], "主笔负责人")
        self.assertEqual(
            [s["member_id"] for s in lab_cfg["seats"]],
            ["researcher", "verifier"],
        )

    def test_custom_seats_override_and_validation_bounds(self) -> None:
        custom_cfg = build_team_config(
            "custom",
            self.project,
            owner_id="lead",
            custom_seats=[
                {"member_id": "策划", "role_label": "方案架构席", "role_brief": "负责方案拆解与边界定义"},
                {"member_id": "ops", "role_label": "运维发布席"},
            ],
        )
        self.assertEqual(custom_cfg["owner_id"], "lead")
        self.assertEqual(len(custom_cfg["seats"]), 2)
        self.assertEqual(custom_cfg["seats"][0]["client_id"], "seat-1")
        self.assertEqual(custom_cfg["seats"][0]["token_env"], "COMPASS_TOKEN_SEAT_1")
        self.assertEqual(custom_cfg["seats"][1]["role_brief"], "")
        self.assertNotIn("role_brief", custom_cfg["agent_inbox_config"]["clients"][1])

        overridden = build_team_config(
            "fullstack_engineering",
            self.project,
            custom_seats=[{"member_id": "qa", "role_label": "质量验收席", "role_brief": "回归全套契约"}],
        )
        self.assertEqual(overridden["owner_id"], "owner")
        self.assertEqual([s["member_id"] for s in overridden["seats"]], ["qa"])

        nine_seats = [
            {"member_id": f"m{i}", "role_label": f"席位{i}"}
            for i in range(1, 10)
        ]
        with self.assertRaises(ValueError):
            build_team_config("custom", self.project, custom_seats=nine_seats)
        with self.assertRaises(ValueError):
            build_team_config("fullstack_engineering", self.project, custom_seats=nine_seats)

        with self.assertRaises(ValueError):
            build_team_config("custom", self.project, custom_seats=[{"member_id": "a", "role_label": "   "}])

        with self.assertRaises(ValueError):
            build_team_config(
                "custom",
                self.project,
                custom_seats=[
                    {"member_id": "dup", "role_label": "席位A"},
                    {"member_id": "dup", "role_label": "席位B"},
                ],
            )

        with self.assertRaises(ValueError):
            build_team_config(
                "custom",
                self.project,
                custom_seats=[
                    {"member_id": "a", "client_id": "same-client", "role_label": "席位A"},
                    {"member_id": "b", "client_id": "same-client", "role_label": "席位B"},
                ],
            )

        with self.assertRaises(ValueError):
            build_team_config(
                "custom",
                self.project,
                custom_seats=[
                    {"member_id": "a", "session_id": "same-sess", "role_label": "席位A"},
                    {"member_id": "b", "session_id": "same-sess", "role_label": "席位B"},
                ],
            )

        with self.assertRaises(ValueError):
            build_team_config(
                "custom",
                self.project,
                owner_id="lead",
                custom_seats=[{"member_id": "lead", "role_label": "冲突席"}],
            )

        with self.assertRaises(ValueError):
            build_team_config("solo", self.project, custom_seats=[{"member_id": "a", "role_label": "席位"}])

        with self.assertRaises(ValueError):
            build_team_config("nonexistent", self.project)

    def test_agent_inbox_backward_compat_and_role_metadata_propagation(self) -> None:
        self.workspace.save([])
        events: list[EvidenceEvent] = []

        legacy_cfg = {
            "schema_version": 1,
            "project_path": str(self.project),
            "owner_id": "owner",
            "clients": [
                {
                    "client_id": "legacy-a",
                    "member_id": "agent-a",
                    "session_id": "sess-a",
                    "agent": "codex",
                    "token": "a" * 40,
                }
            ],
        }
        legacy_inbox = AgentInbox(legacy_cfg, self.workspace, events)
        self.assertEqual(legacy_inbox.clients[0].role_label, "")
        self.assertEqual(legacy_inbox.clients[0].role_brief, "")
        self.assertEqual(
            legacy_inbox.public_status()["clients"],
            [{"client_id": "legacy-a", "member_id": "agent-a", "session_id": "sess-a", "agent": "codex"}],
        )

        team_cfg = build_team_config("product_delivery", self.project)
        inbox_file = self.root / "team-access.json"
        inbox_file.write_text(json.dumps(team_cfg["agent_inbox_config"], ensure_ascii=False), encoding="utf-8")

        fake_tokens = {
            "COMPASS_TOKEN_PLANNER": "p" * 40,
            "COMPASS_TOKEN_DEVELOPER": "d" * 40,
            "COMPASS_TOKEN_QA": "q" * 40,
        }
        with patch.dict(os.environ, fake_tokens):
            team_inbox = AgentInbox.from_file(inbox_file, self.workspace, events)

        status = team_inbox.public_status()
        self.assertEqual(status["owner_id"], "lead")
        self.assertEqual(len(status["clients"]), 3)
        self.assertEqual(status["clients"][0]["role_label"], "产品与方案席")
        self.assertIn("需求拆解、边界梳理与待验证前提记录", status["clients"][0]["role_brief"])
        status_json = json.dumps(status, ensure_ascii=False)
        for secret_val in fake_tokens.values():
            self.assertNotIn(secret_val, status_json)

        bad_cfg = json.loads(json.dumps(legacy_cfg))
        bad_cfg["clients"][0]["role_label"] = "x" * 81
        with self.assertRaises(ValueError):
            AgentInbox(bad_cfg, self.workspace, events)

        bad_brief_cfg = json.loads(json.dumps(legacy_cfg))
        bad_brief_cfg["clients"][0]["role_brief"] = "y" * 241
        with self.assertRaises(ValueError):
            AgentInbox(bad_brief_cfg, self.workspace, events)

    def test_priority_dispatch_persistence_and_reverse_chronological_extraction(self) -> None:
        self.workspace.save([])
        self.workspace.save_review_state([], [], [{"action": "accept_fact", "fact_id": "f-keep", "reviewer": "lead"}])

        first = record_priority_dispatch(
            self.workspace,
            fact_id="fact-001",
            title="先修鉴权边界",
            value="保持 2-tier owner/member 权限隔离并补齐单测",
            evidence_ids=["ev-1", "ev-2"],
            actor="lead",
            mode="queue",
            note="优先分配给研发席",
        )
        second = record_priority_dispatch(
            self.workspace,
            fact_id="fact-001",
            title="先修鉴权边界",
            value="保持 2-tier owner/member 权限隔离并补齐单测",
            evidence_ids=("ev-1",),
            actor="lead",
            mode="send_message",
        )

        self.assertTrue(first["id"].startswith("dispatch-"))
        self.assertTrue(second["id"].startswith("dispatch-"))
        self.assertNotEqual(first["id"], second["id"])

        loaded_events = self.workspace.load()
        self.assertEqual(len(loaded_events), 2)
        self.assertEqual(loaded_events[0].kind, "user_message")
        self.assertEqual(loaded_events[0].metadata["source"], "compass_priority_dispatch")
        self.assertEqual(loaded_events[0].metadata["actor_type"], "human")
        self.assertEqual(derive_facts(loaded_events), [])
        self.assertEqual(self.workspace.load_review_state()[2][0]["fact_id"], "f-keep")

        extracted = extract_priority_dispatches(loaded_events, limit=8)
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0]["id"], second["id"])
        self.assertEqual(extracted[0]["mode"], "send_message")
        self.assertEqual(extracted[1]["id"], first["id"])
        self.assertEqual(extracted[1]["note"], "优先分配给研发席")
        self.assertEqual(extracted[1]["evidence_ids"], ["ev-1", "ev-2"])

        t0 = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
        unordered = [
            EvidenceEvent(
                "dispatch-older",
                "compass-dispatch",
                "lead",
                "user_message",
                "旧派活",
                t0,
                {
                    "source": "compass_priority_dispatch",
                    "fact_id": "f-old",
                    "short_title": "旧派活",
                    "dispatch_value": "旧指令",
                    "dispatch_mode": "queue",
                    "evidence_ids": [],
                },
            ),
            EvidenceEvent(
                "non-dispatch",
                "s1",
                "planner",
                "user_message",
                "普通消息",
                t0 + timedelta(minutes=5),
                {"source": "web_quick_note"},
            ),
            EvidenceEvent(
                "dispatch-newer",
                "compass-dispatch",
                "lead",
                "user_message",
                "新派活",
                t0 + timedelta(minutes=2),
                {
                    "source": "compass_priority_dispatch",
                    "fact_id": "f-new",
                    "short_title": "新派活",
                    "dispatch_value": "新指令",
                    "dispatch_mode": "new_window",
                    "evidence_ids": ["ev-9"],
                    "dispatch_note": "紧急",
                },
            ),
        ]
        ordered = extract_priority_dispatches(unordered, limit=1)
        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0]["id"], "dispatch-newer")
        self.assertEqual(ordered[0]["note"], "紧急")

        with self.assertRaises(ValueError):
            record_priority_dispatch(
                self.workspace,
                fact_id="fact-bad",
                title="泄露检查",
                value="Bearer secret-token-value",
                evidence_ids=[],
                actor="lead",
            )

    def test_mcp_setup_cli_templates_and_rules_snippet(self) -> None:
        buf_list = io.StringIO()
        with redirect_stdout(buf_list):
            rc = setup_main(["--list-templates"])
        self.assertEqual(rc, 0)
        listed = json.loads(buf_list.getvalue())
        self.assertEqual(len(listed["templates"]), 4)

        real_looking_secret = "tok_" + "z" * 36
        buf_tpl = io.StringIO()
        with patch.dict(os.environ, {"COMPASS_TOKEN_PLANNER": real_looking_secret}):
            with redirect_stdout(buf_tpl):
                rc = setup_main(["--team-template", "product_delivery", "--project-path", str(self.project)])
        self.assertEqual(rc, 0)
        raw_out = buf_tpl.getvalue()
        self.assertNotIn(real_looking_secret, raw_out)
        parsed = json.loads(raw_out)
        self.assertEqual(parsed["template_key"], "product_delivery")
        self.assertEqual(parsed["seats"][0]["token_env"], "COMPASS_TOKEN_PLANNER")

        buf_custom = io.StringIO()
        with redirect_stdout(buf_custom):
            rc = setup_main([
                "--team-template",
                "custom",
                "--project-path",
                str(self.project),
                "--role-seat",
                "qa:质量守门席:核验核心边界与回归测试",
                "--role-seat",
                "docs:文档交付席",
            ])
        self.assertEqual(rc, 0)
        custom_out = json.loads(buf_custom.getvalue())
        self.assertEqual(len(custom_out["seats"]), 2)
        self.assertEqual(custom_out["seats"][0]["role_brief"], "核验核心边界与回归测试")
        self.assertEqual(custom_out["seats"][1]["role_label"], "文档交付席")

        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc_err = setup_main(["--role-seat", "qa:测试席"])
        self.assertEqual(rc_err, 2)

        with redirect_stderr(io.StringIO()):
            rc_bad = setup_main(["--team-template", "custom", "--project-path", str(self.project), "--role-seat", "invalid_no_colon"])
        self.assertEqual(rc_bad, 2)

        snippet = render_agent_rules_snippet(member_id="lead")
        self.assertIn("`lead`", snippet)
        self.assertIn("project_context", snippet)
        self.assertIn("record_note", snippet)
        self.assertIn("open_compass", snippet)
        self.assertIn("/compass", snippet)
        self.assertIn("verify_completion", snippet)
        self.assertIn("priority_dispatches", snippet)


if __name__ == "__main__":
    unittest.main()
