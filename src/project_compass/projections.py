from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from .evidence_filters import is_public_raw_event, resolve_member_id
from .fact_engine import derive_facts
from .models import EvidenceEvent
from .source_currentness import source_states
from .directions import direction_projection, direction_suggestion


def run_silent_speculative_sandbox(
    project_root: str | Path | None = None,
    test_target: str | None = None,
    *,
    timeout: int = 60,
    runner_cmd: list[str] | None = None,
) -> dict:
    """Run speculative tests in an isolated background subprocess.

    Strictly adheres to the Silent Principle:
    - Never raises unhandled exceptions or prompts the user on failure/timeout.
    - Times out after at most `timeout` seconds (bounded to 60s max) and terminates the process.
    - Only returns `verified: True` when all tests pass (exit code 0).
    """
    cmd = runner_cmd
    if not cmd:
        if test_target:
            cmd = [sys.executable, "-m", "unittest", test_target]
        else:
            cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]

    cwd = str(Path(project_root).resolve()) if project_root else None
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout, 60)),
        )
        if proc.returncode == 0:
            return {
                "verified": True,
                "exit_code": 0,
                "summary": "Tests passed in silent sandbox (100% green)",
                "silent": True,
            }
        return {
            "verified": False,
            "exit_code": proc.returncode,
            "summary": "Tests failed or returned non-zero",
            "silent": True,
        }
    except subprocess.TimeoutExpired:
        return {
            "verified": False,
            "exit_code": -1,
            "summary": "Sandbox execution timed out (strictly aborted within limit)",
            "silent": True,
        }
    except Exception as exc:
        return {
            "verified": False,
            "exit_code": -1,
            "summary": f"Sandbox could not execute: {exc}",
            "silent": True,
        }


def _speculative_validate_conflict(subject_key: str, subject_facts: list[dict], events: list[EvidenceEvent]) -> dict:
    """Lightweight speculative execution & candidate recommendation for conflicting facts."""
    event_by_id = {e.id: e for e in events}
    sides = []
    scores = []
    max_observed = max((f.get("observed_at") or "" for f in subject_facts), default="")

    for fact in subject_facts:
        fact_id = fact["id"]
        value = fact["value"]
        status = fact["status"]
        author = fact["author"]
        evidence_ids = fact["evidence_ids"]
        source_state = fact.get("source_state") or {}
        observed_at = fact.get("observed_at") or ""
        source_kind = fact.get("source_kind")
        session_id = fact.get("session_id")

        score = 0.0
        reasons = []

        # 1. Source liveness / currentness
        if source_state.get("status") in {"recorded", "current"}:
            score += 2.0
            reasons.append("数据源记录有效且未被替换")
        elif source_state.get("status") in {"replaced", "superseded", "unavailable"}:
            score -= 1.0
            reasons.append("已被后续材料替换或当前不可用")

        # 2. Test execution / verification outcome
        speculative_verified = False
        for eid in evidence_ids:
            ev = event_by_id.get(eid)
            if ev is not None:
                meta = ev.metadata if isinstance(ev.metadata, dict) else {}
                exit_code = meta.get("exit_code")
                if exit_code == 0 or (ev.kind == "test_result" and exit_code is None):
                    score += 3.0
                    speculative_verified = True
                    reasons.append("经由测试/验证执行通过 (exit_code=0)")
                    break
                elif exit_code is not None and exit_code != 0:
                    score -= 2.0
                    reasons.append(f"执行失败 (exit_code={exit_code})")
                    break

        # 3. Temporal recency
        if observed_at and observed_at == max_observed:
            score += 1.5
            reasons.append(f"最新采集时间戳 ({observed_at[:19]})")

        # 4. Status bonus
        if status == "accepted":
            score += 5.0
            reasons.append("团队负责人此前已确认采纳")

        # 5. Evidence backing quantity
        ev_count = len(evidence_ids)
        score += 0.5 * min(ev_count, 4)
        if ev_count > 0:
            reasons.append(f"拥有 {ev_count} 条证据溯源支撑")

        scores.append(score)
        side_dict = {
            "fact_id": fact_id,
            "value": value,
            "status": status,
            "author": author,
            "evidence_ids": evidence_ids,
            "source_state": source_state,
            "observed_at": observed_at,
            "source_kind": source_kind,
            "session_id": session_id,
            "speculative_score": round(score, 2),
            "speculative_reasons": reasons,
            "speculative_verified": speculative_verified,
        }
        sides.append(side_dict)

    max_score = max(scores) if scores else 0.0
    best_index = scores.index(max_score) if scores else 0
    best_side = sides[best_index]
    second_score = sorted(scores, reverse=True)[1] if len(scores) > 1 else 0.0
    is_tie = len(scores) > 1 and max_score == second_score

    for i, side in enumerate(sides):
        if not is_tie and i == best_index:
            side["speculative_status"] = "recommended"
        else:
            side["speculative_status"] = "alternative"

    if is_tie:
        confidence = "low"
        resolution = f"'{subject_key}' 双方提议证据权重持平 ({max_score}分)，建议由负责人人工裁决消解冲突。"
    else:
        confidence = "high" if (max_score - second_score >= 2.0) else "medium"
        resolution = f"若采纳 {best_side['author']} 的提议 '{best_side['value']}' ({best_side['fact_id']})，将消解 '{subject_key}' 的歧义状态。"

    rec = {
        "recommended_fact_id": best_side["fact_id"] if not is_tie else None,
        "recommended_value": best_side["value"] if not is_tie else "平局待定",
        "confidence": confidence,
        "score": round(max_score, 2),
        "reasons": best_side["speculative_reasons"] if not is_tie else ["各方证据权重完全持平"],
        "hypothetical_resolution": resolution,
        "tie": is_tie,
        "speculative_verified": best_side.get("speculative_verified", False) if not is_tie else False,
        "evidence_ids": list(best_side.get("evidence_ids", [])) if not is_tie else [],
    }

    return {
        "subject_key": subject_key,
        "sides": sides,
        "speculative_recommendation": rec,
    }


def build_views(events: list[EvidenceEvent], accepted_fact_ids=(), *, session_members=None, fact_reviews=()) -> dict:
    facts = derive_facts(events)
    sources = {event.id: event for event in events}

    def source_context(fact):
        source = sources.get(fact.evidence_ids[0]) if fact.evidence_ids else None
        return {'observed_at': fact.observed_at.isoformat(), 'session_id': fact.session_id,
                'direction_suggestion':direction_suggestion(fact.quote or fact.value) if fact.kind.value=='decision' else None,
                'source_kind': source.kind if source is not None else None}

    states = source_states(events, facts)
    accepted = set(accepted_fact_ids)
    personal: dict[str, dict] = {}
    raw_events = [event for event in events if is_public_raw_event(event)]
    for event in raw_events:
        owner = resolve_member_id(event, session_members=session_members, route_documents=True)
        member = personal.setdefault(owner, {'member_id': owner, 'facts': [], 'evidence_ids': []})
        member['evidence_ids'].append(event.id)
    def is_fact_verified(fact):
        return any(
            isinstance(sources.get(eid), EvidenceEvent)
            and (
                sources[eid].metadata.get("exit_code") == 0
                or (sources[eid].kind == "test_result" and sources[eid].metadata.get("exit_code") is None)
            )
            for eid in fact.evidence_ids
        )

    for fact in facts:
        member = personal.setdefault(fact.author, {"member_id": fact.author, "facts": [], "evidence_ids": []})
        member["facts"].append({"id": fact.id, "kind": fact.kind.value, "subject_key": fact.subject_key, "value": fact.value, "status": fact.status.value, "evidence_ids": list(fact.evidence_ids), "quote": fact.quote, "source_ref": fact.source_ref, "claim_type": fact.claim_type, "reported_by": fact.reported_by, "task_state": fact.task_state, "speculative_verified": is_fact_verified(fact)})
        member["evidence_ids"].extend(fact.evidence_ids)
        member['facts'][-1]['source_state'] = states[fact.id]
        member['facts'][-1].update(source_context(fact))
    for member in personal.values():
        member["evidence_ids"] = sorted(set(member["evidence_ids"]))
        member['directions']=direction_projection(facts,fact_reviews,events,member_id=member['member_id'])
    team_facts = [
        {
            "id": fact.id,
            "kind": fact.kind.value,
            "subject_key": fact.subject_key,
            "value": fact.value,
            "status": "accepted" if fact.id in accepted else fact.status.value,
            "author": fact.author,
            "evidence_ids": list(fact.evidence_ids),
            "quote": fact.quote,
            "source_ref": fact.source_ref,
            "claim_type": fact.claim_type,
            "reported_by": fact.reported_by,
            "task_state": fact.task_state,
            "speculative_verified": is_fact_verified(fact),
            'source_state': states[fact.id],
            **source_context(fact),
        }
        for fact in facts
    ]
    by_subject: dict[str, list[dict]] = {}
    for fact in team_facts:
        by_subject.setdefault(fact["subject_key"], []).append(fact)
    conflicts = [
        _speculative_validate_conflict(subject_key, subject_facts, events)
        for subject_key, subject_facts in by_subject.items()
        if len({fact["value"] for fact in subject_facts}) > 1
    ]
    team = {"facts": team_facts, "evidence_ids": sorted({event.id for event in raw_events}), "conflicts": conflicts}
    team['directions']=direction_projection(facts,fact_reviews,events)
    return {"personal": personal, "team": team, "evidence_count": len(raw_events)}
