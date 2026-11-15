"""Unit tests covering M2 convergence guarantees across filters, storage, facts, CLI, and retrieval."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_compass import cli, literal_relevance
from project_compass.candidate_extraction import validate_candidates
from project_compass.dashboard import build_dashboard_state
from project_compass.evidence_filters import atomic_write_text, parse_iso_timestamp
from project_compass.evidence_linking import build_requested_evidence_relations
from project_compass.evidence_store import EvidenceStore
from project_compass.fact_engine import derive_facts
from project_compass.investigator import investigate
from project_compass.models import EvidenceEvent
from project_compass.project_workspace import ProjectWorkspace
from project_compass.projections import build_views
from project_compass.sample_data import sample_events


def _make_event(
    eid: str,
    kind: str,
    author: str,
    content: str,
    *,
    session_id: str = "sess-1",
    offset_hours: int = 0,
    metadata: dict | None = None,
) -> EvidenceEvent:
    base = datetime(2026, 11, 14, offset_hours % 24, 0, 0, tzinfo=timezone.utc)
    return EvidenceEvent(
        id=eid,
        kind=kind,
        author=author,
        content=content,
        observed_at=base,
        session_id=session_id,
        metadata=metadata or {},
    )


class BackendConvergenceTests(unittest.TestCase):
    def test_dashboard_vs_projections_member_attribution_parity(self) -> None:
        chat = _make_event(
            "ev-chat-1",
            "user_message",
            "codex",
            "采用本地 SQLite WAL。",
            session_id="sess-alice",
        )
        doc = _make_event(
            "ev-doc-1",
            "file_snapshot",
            "alice",
            "# Architecture Spec",
            session_id="sess-alice",
            offset_hours=1,
            metadata={"source_ref": "docs/SPEC.md", "member_id": "alice"},
        )
        commit = _make_event(
            "ev-git-1",
            "git_commit",
            "alice",
            "feat: converge filters",
            session_id="sess-alice",
            offset_hours=2,
            metadata={"source_ref": "HEAD~1", "member_id": "alice"},
        )
        session_members = {"sess-alice": "alice-mapped"}
        events = [chat, doc, commit]

        views = build_views(events, session_members=session_members)
        board = build_dashboard_state(events, session_members=session_members)
        activity_keys = {item["member_id"] for item in board["personal_activity"]}

        self.assertIn("alice-mapped", views["personal"])
        self.assertIn("project-documents", views["personal"])
        self.assertEqual(activity_keys, {"alice-mapped", "project-documents"})
        by_owner = {item["member_id"]: item["event_count"] for item in board["personal_activity"]}
        self.assertEqual(by_owner["alice-mapped"], 1)
        self.assertEqual(by_owner["project-documents"], 2)

    def test_iso_timestamp_z_suffix_and_dashboard_evidence_requests(self) -> None:
        dt_z = parse_iso_timestamp("2026-11-14T08:30:00Z")
        dt_space = parse_iso_timestamp("2026-11-14 08:30:00z")
        self.assertEqual(dt_z, dt_space)
        self.assertEqual(dt_z.tzinfo, timezone.utc)

        base_events = list(sample_events())
        facts = derive_facts(base_events)
        target_fact = facts[0]
        review_history = [
            {
                "action": "request_evidence",
                "fact_id": target_fact.id,
                "observed_at": "2020-01-01T00:00:00Z",
                "evidence_ids": list(target_fact.evidence_ids),
                "reviewer": "lead",
            }
        ]
        state = build_dashboard_state(base_events, review_history=review_history)
        self.assertEqual(len(state["evidence_requests"]), 1)
        self.assertEqual(state["evidence_requests"][0]["status"], "ready_for_review")
        self.assertTrue(state["evidence_requests"][0]["new_evidence_ids"])

    def test_concurrent_atomic_writes_and_workspace_serialization_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "atomic.json"

            def write_job(idx: int) -> None:
                payload = json.dumps({"worker": idx, "ok": True})
                atomic_write_text(target, payload)

            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(write_job, range(24)))

            parsed = json.loads(target.read_text(encoding="utf-8"))
            self.assertTrue(parsed["ok"])
            self.assertEqual(list(root.glob("*.tmp")), [])

            store_path = root / "store.json"
            ev = _make_event("e1", "user_message", "bob", "hello")
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: EvidenceStore([ev]).save(store_path), range(12)))
            loaded_store = EvidenceStore.load(store_path)
            self.assertEqual([item.id for item in loaded_store.list()], ["e1"])

            project_dir = root / "proj"
            project_dir.mkdir()
            ws_root = root / "ws"
            ws = ProjectWorkspace(ws_root, project_dir)
            with self.assertRaises(TypeError):
                ws.save([ev], metadata={"non_json": object()})
            self.assertFalse(ws.registry_path.exists())
            self.assertFalse(ws.state_path.exists())

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i: ws.save([ev], metadata={"pass": i}), range(8)))
            self.assertTrue(ws.registry_path.exists())
            self.assertEqual(len(ProjectWorkspace.list_registered(ws_root)), 1)

    def test_derive_facts_non_strict_isolates_malformed_proposal(self) -> None:
        src = _make_event("src-1", "assistant_message", "codex", "决定采用本地缓存方案。")
        good_proposal = validate_candidates(
            [src],
            {
                "candidates": [
                    {
                        "source_id": "src-1",
                        "kind": "decision",
                        "subject_key": "cache_choice",
                        "quote": "采用本地缓存方案",
                        "task_state": "unknown",
                    }
                ]
            },
        )[0]
        bad_proposal = EvidenceEvent(
            id="bad-prop-1",
            kind="fact_proposal",
            author="codex",
            content="corrupt span proposal",
            observed_at=src.observed_at,
            session_id=src.session_id,
            metadata={
                "facts": [
                    {
                        "source_id": "src-1",
                        "kind": "decision",
                        "subject_key": "broken_key",
                        "value": "never exists",
                        "quote": "never exists",
                        "source_start": 0,
                        "source_end": 9999,
                    }
                ],
                "member_id": "codex",
            },
        )
        events = [src, good_proposal, bad_proposal]

        with self.assertRaises(ValueError):
            derive_facts(events, strict=True)

        warnings: list[str] = []
        facts = derive_facts(events, strict=False, warnings_out=warnings)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].subject_key, "decision:cache_choice")
        self.assertEqual(len(warnings), 1)
        self.assertIn("bad-prop-1", warnings[0])

    def test_cli_index_code_generates_summary_and_rejects_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / "sample_mod.py").write_text(
                "def helper():\n    return 1\n\ndef entry():\n    return helper()\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(["--scan", str(proj), "--index-code"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(Path(payload["project_path"]).resolve(), proj.resolve())
            self.assertGreaterEqual(payload["summary"]["nodes"], 2)

            err_buf = io.StringIO()
            with redirect_stdout(io.StringIO()), patch("sys.stderr", err_buf):
                rc_bad = cli.main(["--sample", "--index-code"])
            self.assertNotEqual(rc_bad, 0)

    def test_literal_relevance_fts5_fallback_and_nul_byte_safety(self) -> None:
        pool = [
            {"id": "1", "text": "Use\x00 DeltaCache lookup for archived evidence."},
            {"id": "2", "text": "Update\x00 CSS grid layout tokens."},
        ]
        # NUL bytes in both query and docs should not raise ValueError inside sqlite3.
        ranked = literal_relevance.rank_literal(
            "Why\x00 choose DeltaCache?",
            pool,
            [],
            text=lambda item: item["text"],
        )
        self.assertEqual(ranked[0]["id"], "1")

        # Simulated host libsqlite3 without FTS5/trigram cleanly uses pure-Python fallback.
        with patch.object(literal_relevance, "_open_trigram_index", return_value=None):
            fallback_ranked = literal_relevance.rank_literal(
                "DeltaCache lookup",
                pool,
                [],
                text=lambda item: item["text"],
            )
            self.assertEqual(fallback_ranked[0]["id"], "1")

    def test_workspace_concurrent_multi_project_registry_save_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_root = root / "workspaces"
            projects = []
            for idx in range(4):
                pdir = root / f"proj-{idx}"
                pdir.mkdir()
                projects.append((idx, pdir, ProjectWorkspace(ws_root, pdir)))

            def _worker(item: tuple[int, Path, ProjectWorkspace]) -> int:
                idx, pdir, ws = item
                ev = _make_event(f"ev-ws-{idx}", "user_message", "alice", f"work {idx}")
                for rev in range(6):
                    ws.save([ev], metadata={"rev": rev, "project": pdir.name})
                return len(ProjectWorkspace.list_registered(ws_root))

            with ThreadPoolExecutor(max_workers=4) as executor:
                counts = list(executor.map(_worker, projects))

            self.assertTrue(all(c >= 1 for c in counts))
            registered = ProjectWorkspace.list_registered(ws_root)
            self.assertEqual(len(registered), 4)

    def test_mixed_naive_and_aware_timestamps_across_dashboard_and_linking(self) -> None:
        plus8 = timezone(timedelta(hours=8))
        ev_proposal = _make_event(
            "ev-prop-tz",
            "fact_proposal",
            "alice",
            "choose DeltaQueue",
            offset_hours=1,
            metadata={
                "member_id": "alice",
                "facts": [{
                    "kind": "decision",
                    "subject_key": "decision:queue",
                    "value": "choose DeltaQueue",
                    "quote": "choose DeltaQueue",
                    "source_id": "ev-src-tz",
                    "source_start": 0,
                    "source_end": 17,
                }],
            },
        )
        ev_src = EvidenceEvent(
            id="ev-src-tz",
            kind="user_message",
            author="alice",
            content="choose DeltaQueue",
            observed_at=datetime(2026, 11, 14, 1, 0, 0),  # naive
            session_id="sess-tz",
            metadata={"member_id": "alice"},
        )
        # 09:30+08:00 == 01:30Z (earlier than 02:00Z, even though wall clock 09:30 > 02:00)
        ev_late_plus8 = EvidenceEvent(
            id="ev-plus8",
            kind="user_message",
            author="alice",
            content="note in +08",
            observed_at=datetime(2026, 11, 14, 9, 30, 0, tzinfo=plus8),
            session_id="sess-tz",
            metadata={"member_id": "alice"},
        )
        ev_latest_utc = EvidenceEvent(
            id="ev-latest-utc",
            kind="user_message",
            author="alice",
            content="follow-up after review",
            observed_at=datetime(2026, 11, 14, 2, 0, 0, tzinfo=timezone.utc),
            session_id="sess-tz",
            metadata={"member_id": "alice"},
        )
        facts = derive_facts([ev_src, ev_proposal])
        fact_id = facts[0].id
        reviews = [
            {
                "fact_id": fact_id,
                "action": "request_evidence",
                "status": "needs_more_evidence",
                "observed_at": "2026-11-14T01:15:00",  # naive string
                "evidence_ids": ["ev-src-tz"],
            }
        ]
        events = [ev_src, ev_proposal, ev_latest_utc, ev_late_plus8]
        board = build_dashboard_state(events, review_history=reviews)
        alice_act = next(item for item in board["personal_activity"] if item["member_id"] == "alice")
        self.assertEqual(alice_act["last_event_id"], "ev-latest-utc")
        reqs = {item["fact_id"]: item for item in board["evidence_requests"]}
        self.assertEqual(set(reqs[fact_id]["new_evidence_ids"]), {"ev-plus8", "ev-latest-utc"})

        relations = build_requested_evidence_relations(events, facts, reviews)
        self.assertEqual({r.evidence_id for r in relations}, {"ev-plus8", "ev-latest-utc"})

    def test_fact_engine_malformed_inputs_and_member_id_none(self) -> None:
        src = _make_event("ev-src-fe", "user_message", "bob", "Adopt FastCache now", metadata={"member_id": None})
        bool_prop = _make_event(
            "ev-prop-bool",
            "fact_proposal",
            "codex",
            "bad bool span",
            metadata={
                "member_id": None,
                "facts": [{
                    "kind": "decision",
                    "subject_key": "decision:cache",
                    "value": "A",
                    "quote": "A",
                    "source_id": "ev-src-fe",
                    "source_start": False,
                    "source_end": True,
                }],
            },
        )
        with self.assertRaises(ValueError):
            derive_facts([src, bool_prop], strict=True)

        good_prop = _make_event(
            "ev-prop-ok",
            "fact_proposal",
            "codex",
            "good",
            metadata={
                "member_id": None,
                "facts": [{
                    "kind": "decision",
                    "subject_key": "decision:cache",
                    "value": "Adopt FastCache now",
                    "quote": "Adopt FastCache now",
                    "source_id": "ev-src-fe",
                    "source_start": 0,
                    "source_end": len("Adopt FastCache now"),
                }],
            },
        )
        bad_nonlist = _make_event("ev-nonlist", "user_message", "bob", "x", metadata={"facts": None})
        bad_items = _make_event(
            "ev-bad-items",
            "user_message",
            "bob",
            "y",
            metadata={
                "facts": [
                    "not-a-dict",
                    {"kind": "not_a_kind", "subject_key": "k", "value": "v"},
                    {"kind": "decision", "value": "missing-key"},
                ]
            },
        )
        warnings: list[str] = []
        facts = derive_facts([src, bool_prop, good_prop, bad_nonlist, bad_items], strict=False, warnings_out=warnings)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].author, "bob")
        self.assertGreaterEqual(len(warnings), 4)

    def test_fts5_bm25_high_df_length_order_and_ascii_boundary_scaling(self) -> None:
        high_df_pool = [
            {"id": "long", "text": "alpha protocol verification suite for multi node distributed cache benchmark report"},
            {"id": "short", "text": "alpha protocol fix"},
            {"id": "mid", "text": "alpha protocol design note"},
            {"id": "other1", "text": "unrelated storage note one"},
            {"id": "other2", "text": "unrelated storage note two"},
        ]
        ranked_df = literal_relevance.rank_literal("alpha protocol", high_df_pool, [], text=lambda x: x["text"])
        self.assertEqual(ranked_df[0]["id"], "short")

        ann_pool = [
            {"id": "diluted", "text": "ann wrote anna anna anna anna anna anna notes"},
            {"id": "focused", "text": "ann reviewed architecture notes today ann"},
        ]
        ranked_ann = literal_relevance.rank_literal("ann", ann_pool, [], text=lambda x: x["text"])
        self.assertEqual(ranked_ann[0]["id"], "focused")

    def test_cli_sample_mode_env_blocks_index_code(self) -> None:
        err_buf = io.StringIO()
        with patch.dict(os.environ, {"SAMPLE_MODE": "true"}, clear=False):
            with redirect_stdout(io.StringIO()), patch("sys.stderr", err_buf):
                rc = cli.main(["--index-code"])
        self.assertNotEqual(rc, 0)
        self.assertIn("--sample", err_buf.getvalue())

    def test_investigator_raw_fallback_and_direct_lookup_filtering(self) -> None:
        old_snap = _make_event(
            "ev-snap-old",
            "file_snapshot",
            "alice",
            "old snapshot mentions FluxEngine",
            offset_hours=1,
            metadata={"member_id": "alice", "source_ref": "docs/SPEC.md"},
        )
        new_snap = _make_event(
            "ev-snap-new",
            "file_snapshot",
            "alice",
            "new snapshot without match",
            offset_hours=2,
            metadata={"member_id": "alice", "source_ref": "docs/SPEC.md"},
        )
        secret_msg = _make_event(
            "ev-secret",
            "user_message",
            "alice",
            "FluxEngine GITHUB_TOKEN=ghp_1234567890",
            offset_hours=3,
            metadata={"member_id": "alice"},
        )
        reasoning_msg = _make_event(
            "ev-reason",
            "assistant_message",
            "alice",
            "FluxEngine internal chain",
            offset_hours=4,
            metadata={"member_id": "alice", "phase": "analysis"},
        )
        valid_msg = _make_event(
            "ev-valid",
            "user_message",
            "alice",
            "FluxEngine passed smoke validation",
            offset_hours=5,
            metadata={"member_id": "alice"},
        )
        ans_no_facts = investigate([old_snap, new_snap, secret_msg, reasoning_msg, valid_msg], "alice FluxEngine")
        finding_ids = [eid for f in ans_no_facts.findings for eid in f.get("evidence_ids", [])]
        self.assertEqual(finding_ids, ["ev-valid"])

        base_msg = _make_event(
            "ev-base-goal",
            "user_message",
            "alice",
            "Target milestone AlphaRelease",
            offset_hours=0,
            metadata={"member_id": "alice"},
        )
        prop_msg = _make_event(
            "ev-base-prop",
            "fact_proposal",
            "codex",
            "goal proposal",
            offset_hours=0,
            metadata={
                "member_id": "alice",
                "facts": [{
                    "kind": "goal",
                    "subject_key": "goal:main",
                    "value": "Target milestone AlphaRelease",
                    "quote": "Target milestone AlphaRelease",
                    "source_id": "ev-base-goal",
                    "source_start": 0,
                    "source_end": len("Target milestone AlphaRelease"),
                }],
            },
        )
        ans_with_facts = investigate(
            [base_msg, prop_msg, old_snap, new_snap, secret_msg, reasoning_msg, valid_msg],
            "alice FluxEngine",
        )
        self.assertIn("ev-valid", ans_with_facts.evidence_ids)
        for bad_id in ("ev-snap-old", "ev-secret", "ev-reason"):
            self.assertNotIn(bad_id, ans_with_facts.evidence_ids)

        direct = investigate([old_snap, new_snap], "evidence:ev-snap-new", session_members={"sess-1": "alice"})
        self.assertEqual(direct.findings[0]["member_id"], "project-documents")


if __name__ == "__main__":
    unittest.main()
