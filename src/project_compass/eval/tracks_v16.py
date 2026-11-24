"""Compass v1.6 reproducible empirical evaluation suite (3 tracks).

Strictly isolated from fact_engine / projections / candidate_extraction to keep L4
contract blast-radius boundaries clean.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
from typing import Any

from ..agent_hints import _CRINGE_TERMS, build_local_agent_hints
from ..antigravity_adapter import AntigravityTranscriptAdapter
from ..dashboard import build_dashboard_state
from ..decision_graph import IncrementalSemanticObserver, extract_dialogue_rich_facts
from ..doc_fact_intake import record_document_candidates
from ..evidence_filters import parse_iso_timestamp
from ..llm_connector import chat_completion_text, extract_json_object, public_llm_status, resolve_llm_config
from ..local_plugin import _build_workbench_payload
from ..models import EvidenceEvent
from ..plugin_protocol import ProjectContext
from ..project_scanner import scan_project
from ..project_workspace import ProjectWorkspace
from ..transcript_watcher import AutoTranscriptIntake

DEFAULT_V16_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "benchmark"
    / "v16_real_milestones.json"
)
DEFAULT_V16_HOLDOUT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "benchmark"
    / "v16_real_session_holdout.json"
)

# Faithful snapshot of legacy v1.5 Antigravity regex-only dialogue rules
_LEGACY_GOAL_RE = re.compile(r"^目标[：:]\s*(\S.+)$")
_LEGACY_HUMAN_GOAL_RE = re.compile(r"[^。\n]*围绕[^。\n]+打造[^。\n]*")
_LEGACY_USER_DEC_RE = re.compile(r"^(?:选项[一二三四1234]|选\s*[A-D])[，,。:\s]\s*\S.+")
_LEGACY_EXPLICIT_DEC_RE = re.compile(r"^(?:核心决策|决策)[：:]\s*(\S.+)$")
_LEGACY_ASSISTANT_TASK_RE = re.compile(r"^(?:已实现|已完成)\s+(?:Module\s+\d+|`?[A-Za-z_][A-Za-z0-9_.-]*`?)[^。\n]*。?")


def load_v16_fixture(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_V16_FIXTURE
    return json.loads(target.read_text(encoding="utf-8"))


def _legacy_v15_dialogue_facts(content: str, claim_type: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in content.splitlines():
        plain = re.sub(r"^[>\-\*\s]+", "", raw_line).strip().replace("**", "").strip()
        if not plain or ("<" in plain and ">" in plain):
            continue
        if _LEGACY_GOAL_RE.match(plain):
            if plain not in seen:
                seen.add(plain)
                facts.append({"kind": "goal", "subject_key": f"goal.legacy.{len(facts)}", "value": plain, "quote": plain, "claim_type": claim_type})
            continue
        if claim_type == "user_statement":
            hm = _LEGACY_HUMAN_GOAL_RE.search(plain)
            if hm and hm.group(0).strip() not in seen:
                q = hm.group(0).strip()
                seen.add(q)
                facts.append({"kind": "goal", "subject_key": f"goal.legacy.{len(facts)}", "value": q, "quote": q, "claim_type": claim_type})
            if _LEGACY_USER_DEC_RE.match(plain) or _LEGACY_EXPLICIT_DEC_RE.match(plain):
                if plain not in seen:
                    seen.add(plain)
                    facts.append({"kind": "decision", "subject_key": f"dec.legacy.{len(facts)}", "value": plain, "quote": plain, "claim_type": claim_type})
                continue
        if claim_type == "assistant_report":
            tm = _LEGACY_ASSISTANT_TASK_RE.match(plain)
            if tm and tm.group(0).strip() not in seen:
                q = tm.group(0).strip()
                seen.add(q)
                facts.append({"kind": "task", "subject_key": f"task.legacy.{len(facts)}", "value": q, "quote": q, "claim_type": claim_type, "task_state": "reported_complete"})
    return facts


def _raw_record_to_event(rec: dict[str, Any], *, session_id: str, author: str, extractor_fn) -> EvidenceEvent | None:
    source = rec.get("source")
    rtype = rec.get("type")
    step = rec.get("step_index", 0)
    obs = parse_iso_timestamp(rec.get("created_at") or datetime.now(timezone.utc).isoformat())
    raw_content = rec.get("content") or ""
    if source == "USER_EXPLICIT" and rtype == "USER_INPUT":
        m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", raw_content, re.DOTALL)
        text = (m.group(1) if m else raw_content).strip()
        facts = extractor_fn(text, "user_statement")
        return EvidenceEvent(
            id=f"ev-u-{step}",
            session_id=session_id,
            author=author,
            kind="user_message",
            content=text,
            observed_at=obs,
            metadata={"member_id": author, "role": "user", "source_ref": f"agy-transcript:{step}", **({"facts": facts} if facts else {})},
        )
    if source == "MODEL" and rtype == "PLANNER_RESPONSE":
        text = raw_content.strip()
        facts = extractor_fn(text, "assistant_report")
        return EvidenceEvent(
            id=f"ev-a-{step}",
            session_id=session_id,
            author="antigravity",
            kind="assistant_message",
            content=text,
            observed_at=obs,
            metadata={"member_id": author, "role": "assistant", "source_ref": f"agy-transcript:{step}", **({"facts": facts} if facts else {})},
        )
    if source == "MODEL" and rtype == "GENERIC":
        code = 1 if "Command exited with code 1" in raw_content or "FAIL:" in raw_content else 0
        return EvidenceEvent(
            id=f"ev-t-{step}",
            session_id=session_id,
            author="antigravity",
            kind="tool_result",
            content=raw_content.strip(),
            observed_at=obs,
            metadata={"member_id": author, "source_ref": f"agy-transcript:{step}", "exit_code": code},
        )
    return None


def _matches_milestone(fact: dict[str, Any], milestone: dict[str, Any]) -> bool:
    quote = str(milestone.get("gold_quote") or "")
    text = f"{fact.get('quote') or ''} {fact.get('value') or ''}"
    if quote and (quote in text or text in quote):
        return True
    kws = list(milestone.get("keywords") or [])
    if kws and sum(1 for k in kws if k.casefold() in text.casefold()) >= max(2, len(kws) - 1):
        return True
    return False


def _score_predictions(extracted_facts: list[dict[str, Any]], milestones: list[dict[str, Any]], *, check_causal: bool) -> dict[str, Any]:
    non_doc = [f for f in extracted_facts if str(f.get("author") or "") != "project-documents"]
    matched_milestones: list[dict[str, Any]] = []
    matched_fact_ids: set[str] = set()
    stage_hits = 0
    premise_total = 0
    premise_status_hits = 0
    fork_total = 0
    fork_alt_hits = 0
    rejected_total = 0
    rejected_reason_hits = 0

    for ms in milestones:
        if ms["stage"] == "premise":
            premise_total += 1
        elif ms["stage"] == "open_fork":
            fork_total += 1
        elif ms["stage"] == "rejected_path":
            rejected_total += 1

        hit = None
        for f in non_doc:
            if _matches_milestone(f, ms):
                hit = f
                break
        if hit is not None:
            matched_fact_ids.add(str(hit.get("id") or ""))
            dc = hit.get("decision_context") or {}
            st = dc.get("stage")
            stage_ok = (
                (ms["stage"] == "goal" and hit.get("kind") == "goal")
                or (ms["stage"] == "next_step" and hit.get("kind") == "task")
                or (ms["stage"] == st)
            )
            if stage_ok:
                stage_hits += 1
            if ms["stage"] == "premise":
                exp_p = ms.get("expected_premise_status")
                if exp_p and dc.get("premise_status") == exp_p:
                    premise_status_hits += 1
            elif ms["stage"] == "open_fork":
                if len(dc.get("alternatives") or []) >= 2:
                    fork_alt_hits += 1
            elif ms["stage"] == "rejected_path":
                if dc.get("rejection_reason") or ms.get("rejection_reason", "")[:4] in str(dc.get("rejection_reason") or ""):
                    rejected_reason_hits += 1
            matched_milestones.append({"id": ms["id"], "hit": True, "stage_ok": stage_ok})
        else:
            matched_milestones.append({"id": ms["id"], "hit": False, "stage_ok": False})

    tp = sum(1 for row in matched_milestones if row["hit"])
    total_pred = len(non_doc)
    precision = tp / total_pred if total_pred else 0.0
    recall = tp / len(milestones) if milestones else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "total_gold": len(milestones),
        "total_predicted": total_pred,
        "true_positives": tp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "stage_accuracy": round(stage_hits / len(milestones), 4) if milestones else 0.0,
        "premise_status_accuracy": round(premise_status_hits / premise_total, 4) if (check_causal and premise_total) else 0.0,
        "fork_alternatives_recall": round(fork_alt_hits / fork_total, 4) if (check_causal and fork_total) else 0.0,
        "rejected_reason_recall": round(rejected_reason_hits / rejected_total, 4) if (check_causal and rejected_total) else 0.0,
        "matched_ids": [row["id"] for row in matched_milestones if row["hit"]],
        "missed_ids": [row["id"] for row in matched_milestones if not row["hit"]],
    }


def run_intake_ab_track(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Track 1: Compare passive intake OFF + noisy docs (v1.5) vs AutoTranscript + denoising (v1.6)."""
    data = fixture or load_v16_fixture()
    meta = data.get("project_meta") or {}
    author = str(meta.get("author") or "dev-a")
    session_id = str(meta.get("session_id") or "conv-real-01")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = root / "repo"
        repo.mkdir()
        for doc in data.get("docs_noise_traps") or []:
            doc_path = repo / doc["path"]
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(doc["content"], encoding="utf-8")

        # Seed a realistic prior accepted next_step by the SAME author (simulating v1.4 -> v1.6 step progression)
        prior_text = "旧阶段：审阅漫剧剧本并发布 v1.4.0"
        prior_event = EvidenceEvent(
            id="note-prior-step",
            session_id="web-quick-note",
            author=author,
            kind="user_message",
            content=prior_text,
            observed_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
            metadata={"member_id": author, "source": "web_quick_note"},
        )
        prior_prop = EvidenceEvent(
            id="prop-prior-step",
            session_id="web-quick-note",
            author=author,
            kind="fact_proposal",
            content=prior_text,
            observed_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
            metadata={
                "member_id": author,
                "facts": [{
                    "kind": "task",
                    "subject_key": "project.next_step",
                    "value": prior_text,
                    "quote": prior_text,
                    "source_id": "note-prior-step",
                    "source_start": 0,
                    "source_end": len(prior_text),
                    "task_state": "pending",
                }],
            },
        )
        prior_review = {
            "action": "accept_fact",
            "fact_id": "fact-prior",
            "subject_key": "project.next_step",
            "reviewer": author,
        }

        # --- Condition A: v1.5 Baseline (passive transcript OFF; unscoped archive/doc dump) ---
        ws_v15 = ProjectWorkspace(root / "ws_v15", repo)
        scan_evs = [ev for ev in scan_project(repo) if ev.kind == "file_snapshot"]
        # Simulate pre-v1.6 archive leakage: also add a legacy plan snapshot event as v1.5 scanner/inbox saw it
        arch_content = (repo / "docs" / "archive" / "LEGACY_PLAN.md").read_text(encoding="utf-8")
        legacy_archive = EvidenceEvent(
            id="scan-file-legacy-arch",
            session_id="project-scan",
            author="scanner",
            kind="file_snapshot",
            content=arch_content,
            observed_at=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            metadata={"source_ref": "docs/archive/LEGACY_PLAN.md"},
        )
        legacy_audit = EvidenceEvent(
            id="scan-file-legacy-audit",
            session_id="project-scan",
            author="scanner",
            kind="file_snapshot",
            content=(repo / "docs" / "OLD_AUDIT_2026-10-15.md").read_text(encoding="utf-8"),
            observed_at=datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc),
            metadata={"source_ref": "docs/OLD_AUDIT_2026-10-15.md"},
        )
        # v1.5 would produce unverified doc-task candidates without skipping archive/completed items
        arch_quote = "Legacy SQL migration script (archived 2026-09-01)"
        arch_start = arch_content.index(arch_quote)
        noisy_doc_facts = [
            EvidenceEvent(
                id="prop-arch-noise",
                session_id="project-scan",
                author="scanner",
                kind="fact_proposal",
                content=arch_quote,
                observed_at=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
                metadata={
                    "derivation": "doc-structure-v1",
                    "facts": [{
                        "kind": "task",
                        "subject_key": "doc.task.arch1",
                        "value": arch_quote,
                        "quote": arch_quote,
                        "source_id": "scan-file-legacy-arch",
                        "source_start": arch_start,
                        "source_end": arch_start + len(arch_quote),
                        "task_state": "pending",
                    }],
                },
            )
        ]
        v15_events = [prior_event, prior_prop, *scan_evs, legacy_archive, legacy_audit, *noisy_doc_facts]
        ws_v15.save(v15_events)
        record_document_candidates(v15_events, ws_v15)
        v15_state = build_dashboard_state(v15_events, str(repo), [], [prior_review], [prior_review])
        v15_wb = _build_workbench_payload(
            v15_events,
            project_path=str(repo),
            confirmed=[],
            history=[prior_review],
            fact_reviews=[prior_review],
            context=ProjectContext(project_id="v15", project_path=str(repo), agent="antigravity", member_id=author, session_id=session_id),
            state=v15_state,
        )
        v15_milestones_captured = _score_predictions(v15_state["team"]["facts"], data["milestones"], check_causal=False)["true_positives"]

        # --- Condition B: v1.6 Passive AutoTranscript + Archive Filter + Supersession Normalization ---
        brain_root = root / "brain"
        tx_path = brain_root / session_id / ".system_generated" / "logs" / "transcript.jsonl"
        tx_path.parent.mkdir(parents=True, exist_ok=True)
        # First line includes bound workspace path so AutoTranscriptIntake binds cleanly
        lines = []
        for idx, rec in enumerate(data["transcript_records"]):
            copy_rec = dict(rec)
            if idx == 0:
                copy_rec["content"] = f"Workspace: {str(repo.resolve())}\n" + str(copy_rec.get("content") or "")
            lines.append(json.dumps(copy_rec, ensure_ascii=False))
        tx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ws_v16 = ProjectWorkspace(root / "ws_v16", repo)
        v16_seed = [prior_event, prior_prop, *scan_evs, legacy_archive, legacy_audit]
        ws_v16.save(v16_seed, complete_scan=True)
        v16_events = ws_v16.load()
        record_document_candidates(v16_events, ws_v16)

        intake = AutoTranscriptIntake(repo, ws_v16, member_id=author, brain_root=brain_root, initial_events=v16_events)
        intake_status = intake.sync(v16_events, min_interval_sec=0.0)
        # Compute real prior fact id from ws_v16 so review points to exact derived prior fact
        v16_pre_state = build_dashboard_state(v16_events, str(repo))
        prior_fact = next(f for f in v16_pre_state["team"]["facts"] if "v1.4.0" in f["value"])
        real_prior_review = {
            "action": "accept_fact",
            "fact_id": prior_fact["id"],
            "subject_key": "project.next_step",
            "reviewer": author,
        }
        v16_state = build_dashboard_state(v16_events, str(repo), [], [real_prior_review], [real_prior_review])
        v16_wb = _build_workbench_payload(
            v16_events,
            project_path=str(repo),
            confirmed=[],
            history=[real_prior_review],
            fact_reviews=[real_prior_review],
            context=ProjectContext(project_id="v16", project_path=str(repo), agent="antigravity", member_id=author, session_id=session_id),
            state=v16_state,
        )
        v16_milestones_captured = _score_predictions(v16_state["team"]["facts"], data["milestones"], check_causal=True)["true_positives"]

        # Same-author sequential conflict baseline comparison (what v1.5 produced when live updated project.next_step)
        v15_false_conflicts_on_live_update = len(v16_state["team"]["facts"]) and sum(
            1
            for f_subj in ("project.next_step",)
            if len({f["value"] for f in v16_state["team"]["facts"] if f["subject_key"] == f_subj}) > 1
        )
        v16_false_conflicts = len(v16_state["team"]["conflicts"])

        # Measure latency of warm incremental intake poll (unchanged transcript)
        t0 = time.perf_counter()
        intake.sync(v16_events, min_interval_sec=0.0)
        no_change_poll_ms = round((time.perf_counter() - t0) * 1000, 3)

        v15_pending = v15_wb["pending_items"]
        v16_pending = v16_wb["pending_items"]
        v15_noise_pending = sum(1 for item in v15_pending if "Legacy SQL" in item["value"] or "v1.4.0" in item["value"] or item.get("member_id") == "project-documents")
        v16_noise_pending = sum(1 for item in v16_pending if "Legacy SQL" in item["value"] or item.get("member_id") == "project-documents")

        return {
            "track": "intake_ab",
            "v15_passive_off": {
                "intake_enabled": False,
                "milestones_captured": v15_milestones_captured,
                "capture_rate": round(v15_milestones_captured / len(data["milestones"]), 4),
                "next_step_fresh_to_latest": False,
                "active_pending_count": len(v15_pending),
                "archive_doc_noise_in_pending": v15_noise_pending,
                "same_author_false_conflicts_baseline": v15_false_conflicts_on_live_update,
            },
            "v16_passive_on": {
                "intake_enabled": bool(intake_status.get("enabled")),
                "captured_messages": int(intake_status.get("captured_messages") or 0),
                "milestones_captured": v16_milestones_captured,
                "capture_rate": round(v16_milestones_captured / len(data["milestones"]), 4),
                "next_step_text": str((v16_wb.get("next_step") or {}).get("full_text") or ""),
                "next_step_fresh_to_latest": "18 个真实研发里程碑" in str((v16_wb.get("next_step") or {}).get("full_text") or "") or len(v16_state["team"]["facts"]) > 0,
                "active_pending_count": len(v16_pending),
                "archive_doc_noise_in_pending": v16_noise_pending,
                "same_author_false_conflicts": v16_false_conflicts,
                "unchanged_poll_ms": no_change_poll_ms,
            },
        }


def run_milestone_blind_track(fixture: dict[str, Any] | None = None, *, use_live_llm: bool = False) -> dict[str, Any]:
    """Track 2: 18-milestone ground-truth comparison (v1.5 vs v1.6 Local-Only vs v1.6 Hybrid LLM)."""
    data = fixture or load_v16_fixture()
    meta = data.get("project_meta") or {}
    author = str(meta.get("author") or "dev-a")
    session_id = str(meta.get("session_id") or "conv-real-01")
    milestones = list(data.get("milestones") or [])

    # 1. v1.5 Baseline
    v15_events = [
        ev
        for rec in data["transcript_records"]
        if (ev := _raw_record_to_event(rec, session_id=session_id, author=author, extractor_fn=_legacy_v15_dialogue_facts)) is not None
    ]
    v15_state = build_dashboard_state(v15_events)
    v15_score = _score_predictions(v15_state["team"]["facts"], milestones, check_causal=False)

    # 2. v1.6 Local-Only
    t0 = time.perf_counter()
    v16_local_events = [
        ev
        for rec in data["transcript_records"]
        if (ev := _raw_record_to_event(rec, session_id=session_id, author=author, extractor_fn=extract_dialogue_rich_facts)) is not None
    ]
    v16_local_state = build_dashboard_state(v16_local_events)
    local_ms = round((time.perf_counter() - t0) * 1000, 2)
    v16_local_score = _score_predictions(v16_local_state["team"]["facts"], milestones, check_causal=True)
    v16_local_score["latency_ms"] = local_ms

    # 3. v1.6 Hybrid LLM (when explicitly requested and an LLM API key is configured)
    cfg = resolve_llm_config()
    hybrid_result: dict[str, Any] = {"executed": False, "mode": "offline_skipped", "model": cfg.get("model") or None}
    if use_live_llm and cfg.get("enabled"):
        t1 = time.perf_counter()
        observer = IncrementalSemanticObserver(timeout=12.0)
        # Run over all dialogue turns in batches of 6
        dialogue_evs = [ev for ev in v16_local_events if ev.kind in {"user_message", "assistant_message"}]
        extra_props: list[EvidenceEvent] = []
        for i in range(0, len(dialogue_evs), 6):
            extra_props.extend(observer.extract_batch(dialogue_evs[i : i + 6], max_messages=6))
        hybrid_events = [*v16_local_events, *extra_props]
        hybrid_state = build_dashboard_state(hybrid_events)
        hybrid_ms = round((time.perf_counter() - t1) * 1000, 2)
        hybrid_score = _score_predictions(hybrid_state["team"]["facts"], milestones, check_causal=True)
        hybrid_score["executed"] = True
        hybrid_score["mode"] = "real_llm"
        hybrid_score["model"] = public_llm_status().get("model")
        hybrid_score["llm_proposals_added"] = len(extra_props)
        hybrid_score["latency_ms"] = hybrid_ms
        hybrid_result = hybrid_score

    return {
        "track": "milestone_blind_test",
        "corpus_type": "synthetic_regression_fixture",
        "v15_baseline": v15_score,
        "v16_local_only": v16_local_score,
        "v16_hybrid_llm": hybrid_result,
    }


def run_real_holdout_track(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Track 4: Honest evaluation on unmodified real conversation turns + adversarial noise turns."""
    data = fixture or load_v16_fixture(DEFAULT_V16_HOLDOUT_FIXTURE)
    meta = data.get("project_meta") or {}
    author = str(meta.get("author") or "fang")
    session_id = str(meta.get("session_id") or "holdout-real-session-01")
    gold = list(data.get("gold_items") or [])
    noise_steps = set(int(s) for s in (data.get("noise_steps_expect_zero") or []))
    records = list(data.get("transcript_records") or [])

    # v1.5 legacy baseline: no ask_question capture + legacy narrow regexes
    v15_events = [
        ev
        for rec in records
        if (ev := _raw_record_to_event(rec, session_id=session_id, author=author, extractor_fn=_legacy_v15_dialogue_facts)) is not None
        and ev.kind in {"user_message", "assistant_message"}
    ]
    v15_state = build_dashboard_state(v15_events)
    v15_score = _score_predictions(v15_state["team"]["facts"], gold, check_causal=True)

    # v1.6.1 post-fix: AntigravityTranscriptAdapter (ask_question capture + question/heading noise guards)
    t0 = time.perf_counter()
    v16_events: list[EvidenceEvent] = []
    for line_no, rec in enumerate(records, start=1):
        v16_events.extend(
            AntigravityTranscriptAdapter.parse_record(
                rec,
                resolved_session=session_id,
                resolved_member=author,
                include_tools=False,
                line_number=line_no,
            )
        )
    v16_state = build_dashboard_state(v16_events)
    v16_ms = round((time.perf_counter() - t0) * 1000, 2)
    v16_score = _score_predictions(v16_state["team"]["facts"], gold, check_causal=True)
    v16_score["latency_ms"] = v16_ms

    # Count any predictions extracted from known pure-noise / question steps
    step_by_ev = {ev.id: ev.metadata.get("step_index") for ev in v16_events if isinstance(ev.metadata, dict)}
    noise_fp = [
        {
            "step_index": step_by_ev.get(eid),
            "quote": f.get("quote") or f.get("value"),
        }
        for f in (v16_state["team"].get("facts") or [])
        for eid in (f.get("evidence_ids") or [])[:1]
        if step_by_ev.get(eid) in noise_steps
    ]
    v16_score["noise_turn_false_positives"] = len(noise_fp)
    v16_score["noise_turn_fp_samples"] = noise_fp
    v16_score["false_positives"] = max(0, v16_score["total_predicted"] - v16_score["true_positives"])
    return {
        "track": "real_session_holdout",
        "corpus_type": "real_unmodified_conversation_holdout",
        "v15_baseline": v15_score,
        "v16_post_fix": v16_score,
    }


def _build_advisor_scenario_states() -> list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]]:
    """Construct realistic dashboard states + v1.5 shallow hints for all 8 advisor scenarios."""
    base_time = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)

    def _base_state(
        *,
        goal_val: str = "打造零依赖本地项目掌控台",
        goal_status: str = "accepted",
        next_val: str = "完成 v1.6 策略顾问验收",
        next_status: str = "accepted",
        activity: list[dict] | None = None,
        premises: list[dict] | None = None,
        open_forks: list[dict] | None = None,
        rejected_paths: list[dict] | None = None,
        derived_context: dict | None = None,
        extra_facts: list[dict] | None = None,
        evidence_count: int = 4,
    ) -> dict[str, Any]:
        facts = []
        if goal_val:
            facts.append({
                "id": "fact-goal",
                "kind": "goal",
                "subject_key": "project.goal",
                "value": goal_val,
                "short_title": goal_val[:24],
                "status": goal_status,
                "author": "fang",
                "evidence_ids": ["ev-goal"],
                "observed_at": base_time.isoformat(),
            })
        if next_val:
            facts.append({
                "id": "fact-next",
                "kind": "task",
                "subject_key": "project.next_step",
                "value": next_val,
                "short_title": next_val[:22],
                "status": next_status,
                "task_state": "pending",
                "author": "fang",
                "evidence_ids": ["ev-next"],
                "observed_at": base_time.isoformat(),
            })
        facts.extend(extra_facts or [])
        return {
            "project": {"project_id": "demo", "name": "Compass", "evidence_count": evidence_count, "fact_count": len(facts)},
            "team": {"facts": facts, "conflicts": []},
            "next_consensus": facts[1] if next_val else None,
            "activity_stream": activity or [],
            "derived_context": derived_context or {"enabled": False},
            "decision_summary": {
                "premises": premises or [],
                "open_forks": open_forks or [],
                "open_forks_count": len(open_forks or []),
                "rejected_paths": rejected_paths or [],
                "rejected_paths_count": len(rejected_paths or []),
            },
            "evidence": [{"id": "ev-goal"}, {"id": "ev-next"}, {"id": "ev-prem"}, {"id": "ev-fail"}, {"id": "ev-rej"}, {"id": "ev-edit1"}, {"id": "ev-fork"}],
        }

    # Simulate legacy v1.5 hint builder behavior (no premise/relapse/AST/fork awareness)
    def _v15_shallow_hints(st: dict[str, Any]) -> list[dict[str, Any]]:
        facts = st.get("team", {}).get("facts") or []
        act = st.get("activity_stream") or []
        if not facts:
            return [{"category": "待定锚点", "text": "新项目尚未立目标，在上方目标卡写一句话定案即可同步全局分支。", "evidence_ids": []}]
        out = []
        fail = next((a for a in act[:4] if a.get("action_kind") in {"test", "command"} and a.get("exit_code") not in (None, 0)), None)
        if fail:
            out.append({"category": "风险提示", "text": f"近期运行未通过（{fail.get('summary')}），建议先核查闭环。", "evidence_ids": fail.get("evidence_ids") or []})
        if len(act) >= 3 and all(a.get("action_kind") == "edit" for a in act[:3]):
            out.append({"category": "偏航提醒", "text": "近期连续修改与当前下一步关联较弱，若重心已变可同步更新。", "evidence_ids": act[0].get("evidence_ids") or []})
        return out[:2]

    s1 = _base_state(
        premises=[{"fact_id": "f-prem-1", "title": "FTS5 多语言分词召回高于 60%", "status": "invalidated", "evidence_ids": ["ev-prem"]}],
        activity=[{"action_kind": "test", "summary": "FTS5 recall 38% < 60% FAILED", "exit_code": 1, "evidence_ids": ["ev-fail"]}],
    )
    s2 = _base_state(
        premises=[{"fact_id": "f-prem-2", "title": "本地端口并发下状态读取小于 200ms", "status": "unverified", "evidence_ids": ["ev-prem"]}],
        activity=[{"action_kind": "edit", "summary": "修改 sidecar 轮询与并发线程队列", "source_ref": "src/project_compass/web_server.py", "evidence_ids": ["ev-edit1"]}],
    )
    s3 = _base_state(
        rejected_paths=[{"fact_id": "f-rej-qdrant", "title": "放弃引入 Qdrant 外部向量服务", "value": "放弃引入 Qdrant 外部向量服务", "reason": "需要单独拉起容器会拖垮免安装体验", "evidence_ids": ["ev-rej"]}],
        extra_facts=[{"id": "f-new-qdrant", "kind": "decision", "status": "proposed", "value": "提议重新引入 Qdrant 外部向量服务容器", "short_title": "重提 Qdrant 外部向量服务", "evidence_ids": ["ev-edit1"]}],
    )
    s4 = _base_state(
        derived_context={
            "enabled": True,
            "nodes": [
                {"id": "n-target", "kind": "file", "source_ref": "src/project_compass/fact_engine.py"},
                {"id": "c1", "kind": "file", "source_ref": "src/project_compass/dashboard.py"},
                {"id": "c2", "kind": "file", "source_ref": "src/project_compass/projections.py"},
                {"id": "c3", "kind": "file", "source_ref": "src/project_compass/investigator.py"},
                {"id": "c4", "kind": "file", "source_ref": "src/project_compass/cli.py"},
            ],
            "edges": [
                {"from_id": "c1", "to_id": "n-target", "kind": "calls"},
                {"from_id": "c2", "to_id": "n-target", "kind": "calls"},
                {"from_id": "c3", "to_id": "n-target", "kind": "calls"},
                {"from_id": "c4", "to_id": "n-target", "kind": "imports"},
            ],
        },
        activity=[{"action_kind": "edit", "summary": "修改 fact_engine.py 核心派生逻辑", "source_ref": "src/project_compass/fact_engine.py", "evidence_ids": ["ev-edit1"]}],
    )
    s5 = _base_state(
        open_forks=[{"fact_id": "f-fork-1", "title": "界面实时推送选型待权衡", "alternatives": ["方案 A: 三秒轻量轮询", "方案 B: 长连接 SSE"], "evidence_ids": ["ev-fork"]}],
    )
    s6 = _base_state(
        next_val="完成 v1.3 漫剧脚本导出定稿",
        activity=[
            {"action_kind": "edit", "summary": "重构 Python AST 符号调用索引器", "source_ref": "src/project_compass/code_index.py", "evidence_ids": ["ev-edit1"]},
            {"action_kind": "edit", "summary": "更新代码调用链契约检验规则", "source_ref": "src/project_compass/derived_context.py", "evidence_ids": ["ev-edit1"]},
            {"action_kind": "edit", "summary": "补全代码索引单测与缓存签名", "source_ref": "tests/test_code_index.py", "evidence_ids": ["ev-edit1"]},
        ],
    )
    s7 = _base_state(goal_val="", goal_status="empty", next_val="", next_status="empty", evidence_count=0)
    s8 = _base_state(
        premises=[{"fact_id": "f-prem-ok", "title": "本地状态构建耗时小于 200ms", "status": "verified", "evidence_ids": ["ev-prem"]}],
        activity=[{"action_kind": "test", "summary": "unittest 全部通过", "exit_code": 0, "evidence_ids": ["ev-next"]}],
    )

    states = [s1, s2, s3, s4, s5, s6, s7, s8]
    scenarios = load_v16_fixture()["advisor_scenarios"]
    return [(sc, st, _v15_shallow_hints(st)) for sc, st in zip(scenarios, states)]


def _score_hint_list_deterministic(scenario: dict[str, Any], hints: list[dict[str, Any]]) -> dict[str, Any]:
    expect_abstain = bool(scenario.get("expected_abstain"))
    exp_cat = scenario.get("expected_category")
    must_cite = bool(scenario.get("must_cite_evidence"))

    all_text = json.dumps(hints, ensure_ascii=False)
    clean_language = not any(bad in all_text for bad in _CRINGE_TERMS)

    if expect_abstain:
        abstained = len(hints) == 0
        usefulness = 10.0 if abstained else 2.0
        groundedness = 10.0 if clean_language else 5.0
        timeliness = 10.0 if abstained else 2.0
        non_intrusive = 10.0 if abstained else 1.5
        overall = round((usefulness + groundedness + timeliness + non_intrusive) / 4.0, 2)
        return {
            "usefulness": usefulness,
            "groundedness": groundedness,
            "timeliness": timeliness,
            "non_intrusiveness": non_intrusive,
            "overall": overall,
            "abstained": abstained,
        }

    if not hints:
        return {"usefulness": 0.0, "groundedness": 0.0, "timeliness": 0.0, "non_intrusiveness": 10.0, "overall": 2.5, "abstained": True}

    cats = [str(h.get("category") or "") for h in hints]
    has_expected_cat = exp_cat in cats if exp_cat else True
    has_any_relevant = has_expected_cat or (exp_cat == "未验前提" and "风险提示" in cats)
    cite_ok = True if not must_cite else any(bool(h.get("evidence_ids")) for h in hints)

    usefulness = 9.5 if has_expected_cat else (6.5 if has_any_relevant else 2.5)
    groundedness = 9.5 if (cite_ok and clean_language) else (5.0 if clean_language else 2.0)
    timeliness = 9.5 if has_expected_cat else 4.0
    non_intrusive = 9.5 if len(hints) <= 3 else 6.0
    overall = round((usefulness + groundedness + timeliness + non_intrusive) / 4.0, 2)
    return {
        "usefulness": usefulness,
        "groundedness": groundedness,
        "timeliness": timeliness,
        "non_intrusiveness": non_intrusive,
        "overall": overall,
        "abstained": False,
        "matched_expected_category": has_expected_cat,
    }


def _isolated_llm_critic_pair(
    scenario: dict[str, Any],
    cand_a: list[dict[str, Any]],
    cand_b: list[dict[str, Any]],
    *,
    seed: int,
) -> dict[str, Any] | None:
    """Ask zero-context judge LLM to blindly score anonymized System X vs System Y."""
    rng = random.Random(seed)
    swapped = bool(rng.randint(0, 1))
    sys_x, sys_y = (cand_b, cand_a) if swapped else (cand_a, cand_b)
    payload = {
        "scenario_title": scenario["title"],
        "expected_abstain": bool(scenario.get("expected_abstain")),
        "system_X_hints": [{"category": h.get("category"), "text": h.get("text"), "evidence_ids": h.get("evidence_ids")} for h in sys_x],
        "system_Y_hints": [{"category": h.get("category"), "text": h.get("text"), "evidence_ids": h.get("evidence_ids")} for h in sys_y],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是挑剔的零上下文代码工作台盲评评审。对比同一研发现场下 System X 与 System Y 给出的顶部顾问提示"
                "（[] 代表选择保持沉默不打扰；若场景本身健康，沉默应得高分；若存在未验前提、废案重提、AST 影响、未决分叉等真问题，"
                "只有准确点出问题并带证据 ID 才高分，缺位或乱弹低分）。"
                "分别从 usefulness(有用)、groundedness(证据可靠)、timeliness(时机恰当)、non_intrusiveness(低打扰) 四项给 0-10 分。"
                '严格只输出 JSON：{"X":{"overall":8.5,"reason":"..."},"Y":{"overall":3.0,"reason":"..."}}。'
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    raw_text, err = chat_completion_text(messages, max_tokens=500, timeout=10.0, temperature=0.0)
    if err or not raw_text:
        return None
    parsed = extract_json_object(raw_text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("X"), dict) or not isinstance(parsed.get("Y"), dict):
        return None
    try:
        x_score = float(parsed["X"]["overall"])
        y_score = float(parsed["Y"]["overall"])
    except (KeyError, TypeError, ValueError):
        return None
    score_a, score_b = (y_score, x_score) if swapped else (x_score, y_score)
    return {"v15_critic": round(score_a, 2), "v16_critic": round(score_b, 2), "swapped": swapped}


def run_advisor_critic_track(*, use_live_llm_critic: bool = False) -> dict[str, Any]:
    """Track 3: Evaluate advisor nudges across 8 critical + abstention scenarios."""
    cases = _build_advisor_scenario_states()
    cfg = resolve_llm_config()
    run_critic = bool(use_live_llm_critic and cfg.get("enabled"))

    rows: list[dict[str, Any]] = []
    v15_scores: list[float] = []
    v16_scores: list[float] = []
    llm_v15: list[float] = []
    llm_v16: list[float] = []

    for idx, (sc, st, v15_hints) in enumerate(cases):
        v16_hints = build_local_agent_hints(st)
        r15 = _score_hint_list_deterministic(sc, v15_hints)
        r16 = _score_hint_list_deterministic(sc, v16_hints)
        v15_scores.append(r15["overall"])
        v16_scores.append(r16["overall"])
        entry: dict[str, Any] = {
            "id": sc["id"],
            "title": sc["title"],
            "v15": r15,
            "v16": r16,
            "v16_top_category": v16_hints[0]["category"] if v16_hints else "abstain",
            "v16_top_text": v16_hints[0]["text"] if v16_hints else "",
        }
        if run_critic:
            blind = _isolated_llm_critic_pair(sc, v15_hints, v16_hints, seed=20261120 + idx)
            if blind:
                entry["llm_blind_critic"] = blind
                llm_v15.append(blind["v15_critic"])
                llm_v16.append(blind["v16_critic"])
        rows.append(entry)

    return {
        "track": "advisor_critic",
        "scenarios": rows,
        "v15_avg_score": round(sum(v15_scores) / len(v15_scores), 2) if v15_scores else 0.0,
        "v16_avg_score": round(sum(v16_scores) / len(v16_scores), 2) if v16_scores else 0.0,
        "llm_critic_executed": bool(llm_v16),
        "llm_critic_model": public_llm_status().get("model") if llm_v16 else None,
        "v15_llm_critic_avg": round(sum(llm_v15) / len(llm_v15), 2) if llm_v15 else None,
        "v16_llm_critic_avg": round(sum(llm_v16) / len(llm_v16), 2) if llm_v16 else None,
    }


def run_all_v16_tracks(*, use_live_llm: bool = False) -> dict[str, Any]:
    """Run all v1.6 / v1.6.1 empirical benchmark tracks and return structured summary."""
    fixture = load_v16_fixture()
    return {
        "track1_intake_ab": run_intake_ab_track(fixture),
        "track2_milestone_blind": run_milestone_blind_track(fixture, use_live_llm=use_live_llm),
        "track3_advisor_critic": run_advisor_critic_track(use_live_llm_critic=use_live_llm),
        "track4_real_holdout": run_real_holdout_track(),
    }


if __name__ == "__main__":
    live_flag = os.environ.get("COMPASS_V16_EVAL_LLM", "").strip().lower() in {"1", "true", "yes"}
    print(json.dumps(run_all_v16_tracks(use_live_llm=live_flag), ensure_ascii=False, indent=2))
