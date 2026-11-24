"""Deterministic completion gate & optional timeout-bounded clean-context critic.

Pure Python standard library only. Never imports core fact/view/extraction engines
so L4 benchmark blast-radius contracts remain strictly intact.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .evidence_filters import is_public_raw_event
from .llm_connector import chat_completion_text, extract_json_object, is_truthy_env, resolve_llm_config
from .models import EvidenceEvent
from .text_summary import is_historical_doc_fact, summarize_node_title

DEFAULT_CRITIC_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_CRITIC_MODEL = "deepseek-chat"
DEFAULT_CRITIC_TIMEOUT = 6.0


def _clean_files_list(changed_files: list[str] | tuple[str, ...] | None) -> list[str]:
    if not changed_files:
        return []
    out: list[str] = []
    for raw in changed_files:
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip()[:260])
        if len(out) >= 32:
            break
    return out


def _clean_id_list(ids: list[str] | tuple[str, ...] | None) -> list[str]:
    if not ids:
        return []
    out: list[str] = []
    for raw in ids:
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip()[:128])
        if len(out) >= 16:
            break
    return out


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _run_sidecar_critic(
    *,
    core_goal: str,
    accepted_baseline: list[str],
    pending_proposals: list[str],
    open_pitfalls: list[str],
    summary: str,
    changed_files: list[str],
    timeout: float,
) -> dict[str, Any]:
    if is_truthy_env("SAMPLE_MODE"):
        return {
            "enabled": False,
            "status": "skipped_sample_mode",
            "verdict": "skipped",
            "findings": [],
        }
    cfg = resolve_llm_config()
    if not cfg["enabled"]:
        return {
            "enabled": False,
            "status": "unconfigured",
            "verdict": "skipped",
            "findings": [],
        }

    model = cfg["model"]
    bounded_timeout = max(1.0, min(float(timeout), 12.0))

    # Clean-context prompt: pass ONLY user baseline/goals + claimed completion diff/summary (zero conversation noise).
    messages = [
        {
            "role": "system",
            "content": (
                "你是独立的软件验收旁路督导员。只依据已确认事项、待确认项、遗留坑位和本次改动总结，"
                "判断是否存在偏离目标、把未确认备选当需求实现、或疑似未验证的问题。"
                '严格返回 JSON：{"verdict":"pass|warn|fail","findings":["..."]}，最多 3 条简短中文。'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "core_goal": core_goal,
                    "accepted_baseline": accepted_baseline[:8],
                    "pending_proposals": pending_proposals[:6],
                    "open_pitfalls": open_pitfalls[:6],
                    "claimed_summary": summary[:1200],
                    "changed_files": changed_files[:20],
                },
                ensure_ascii=False,
            ),
        },
    ]

    content, err = chat_completion_text(
        messages,
        max_tokens=800,
        timeout=bounded_timeout,
        temperature=0.0,
        urlopen_fn=urlopen,
    )
    if err or not content:
        return {
            "enabled": True,
            "status": "degraded_timeout_or_error",
            "model": model,
            "verdict": "skipped",
            "findings": [],
            "note": "旁路审查超时或不可用，已自动退回本地确定性规则（不阻塞工作流）。",
        }
    parsed = extract_json_object(content) or {}
    verdict = str(parsed.get("verdict") or "warn").lower()
    if verdict not in {"pass", "warn", "fail"}:
        verdict = "warn"
    findings = [
        summarize_node_title(str(item), max_chars=48)
        for item in (parsed.get("findings") or [])[:3]
        if str(item).strip()
    ]
    return {
        "enabled": True,
        "status": "evaluated",
        "model": model,
        "verdict": verdict,
        "findings": findings,
    }


def evaluate_completion_gate(
    state: dict[str, Any],
    events: list[EvidenceEvent] | tuple[EvidenceEvent, ...],
    *,
    summary: str = "",
    changed_files: list[str] | tuple[str, ...] | None = None,
    test_evidence_ids: list[str] | tuple[str, ...] | None = None,
    critic_timeout: float = DEFAULT_CRITIC_TIMEOUT,
) -> dict[str, Any]:
    """Check completion claim against confirmed baselines, execution proof, and open pitfalls."""
    files = _clean_files_list(changed_files)
    test_ids = _clean_id_list(test_evidence_ids)
    team = state.get("team", {}) if isinstance(state, dict) else {}
    team_facts = list(team.get("facts") or [])
    conflicts = list(team.get("conflicts") or [])
    brief = state.get("handoff_brief", {}) if isinstance(state, dict) else {}
    focus_goal = brief.get("focus_goal") or {}
    core_goal = str(focus_goal.get("value") or "核心目标待确定")

    public_events = [ev for ev in events if is_public_raw_event(ev)]
    events_by_id = {ev.id: ev for ev in public_events}

    # 1. Inspect execution / modification evidence
    verification_events = [
        ev for ev in public_events
        if ev.kind in {"test_result", "command_execution"}
        or (ev.kind in {"tool_call", "tool_result"} and isinstance(ev.metadata, dict) and isinstance(ev.metadata.get("exit_code"), int))
    ]
    file_change_events = [
        ev for ev in public_events
        if ev.kind == "file_change"
        or (isinstance(ev.metadata, dict) and bool(ev.metadata.get("files")))
    ]

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    has_execution_proof = bool(test_ids) or any(
        (isinstance(ev.metadata, dict) and ev.metadata.get("exit_code") == 0) or ev.kind == "test_result"
        for ev in verification_events
    )
    has_diff_proof = bool(files) or bool(file_change_events)

    if not has_execution_proof and not has_diff_proof:
        blockers.append({
            "code": "missing_verification_evidence",
            "message": "仅口头汇报完工，缺少改动文件清单（changed_files）或可核对的实测结果（test_evidence_ids/命令记录）。",
        })

    # Inspect explicit test_evidence_ids or latest verification record for non-zero exit codes
    latest_failed = None
    for tid in test_ids:
        ev = events_by_id.get(tid)
        if ev is not None and isinstance(ev.metadata, dict):
            code = ev.metadata.get("exit_code")
            if isinstance(code, int) and code != 0:
                latest_failed = code
                break
    if latest_failed is None and verification_events:
        latest_ver = sorted(verification_events, key=lambda ev: (ev.observed_at.isoformat(), ev.id))[-1]
        if isinstance(latest_ver.metadata, dict):
            code = latest_ver.metadata.get("exit_code")
            if isinstance(code, int) and code != 0:
                latest_failed = code

    if latest_failed is not None:
        blockers.append({
            "code": "latest_verification_failed",
            "message": f"最近一次校验或测试失败（退出码 {latest_failed}），请先修复并通过复测后再宣称完工。",
        })

    # 2. Check open pitfalls (uncompleted tasks & unverified assumptions) and unconfirmed proposals
    accepted_facts = [f for f in team_facts if f.get("status") == "accepted"]
    accepted_subjects = {f.get("subject_key") for f in accepted_facts if f.get("subject_key")}

    open_pitfalls: list[dict[str, Any]] = []
    pending_proposals: list[dict[str, Any]] = []
    latest_review_by_fact: dict[str, dict[str, Any]] = {}
    for rev in (state.get("review_history") or []) if isinstance(state, dict) else []:
        fid = str(rev.get("fact_id") or "")
        if fid and rev.get("action") != "confirm_relation":
            latest_review_by_fact[fid] = rev
    rejected_fact_ids = {
        fid for fid, rev in latest_review_by_fact.items() if rev.get("action") == "reject_fact"
    }
    for fact in team_facts:
        fid = str(fact.get("id") or "")
        if (
            fact.get("status") == "rejected"
            or (fid and fid in rejected_fact_ids)
            or is_historical_doc_fact(fact)
            or fact.get("completed")
            or fact.get("superseded_by_fact_id")
            or (fact.get("decision_context") or {}).get("stage") == "rejected_path"
        ):
            continue
        short_label = fact.get("short_title") or summarize_node_title(fact.get("value") or "", max_chars=22)
        if fact.get("kind") == "task" and fact.get("task_state") not in {"completed", "reported_complete"}:
            open_pitfalls.append({
                "fact_id": fact.get("id"),
                "kind": "task",
                "short_title": short_label,
                "task_state": fact.get("task_state") or "pending",
            })
        elif fact.get("kind") == "assumption" and fact.get("status") != "accepted":
            open_pitfalls.append({
                "fact_id": fact.get("id"),
                "kind": "assumption",
                "short_title": short_label,
                "task_state": "unverified",
            })
        if fact.get("status") in {"proposed", "conflicted", "needs_evidence"} and fact.get("subject_key") not in accepted_subjects and fact.get("kind") in {"decision", "assumption", "goal"}:
            pending_proposals.append({
                "fact_id": fact.get("id"),
                "kind": fact.get("kind"),
                "short_title": short_label,
            })

    if open_pitfalls:
        sample_labels = "、".join(p["short_title"] for p in open_pitfalls[:3])
        warnings.append({
            "code": "open_pitfalls_remaining",
            "message": f"尚有 {len(open_pitfalls)} 项待办与待核实前提：{sample_labels}",
        })

    if pending_proposals:
        warnings.append({
            "code": "unconfirmed_proposals_present",
            "message": f"当前有 {len(pending_proposals)} 项待确认方案尚未经用户确认，请提醒用户审阅而非默认已确认。",
        })

    if conflicts:
        warnings.append({
            "code": "unresolved_conflicts",
            "message": f"存在 {len(conflicts)} 组前后分歧尚未选定，请引导用户在看板分歧对照中确认。",
        })

    sidecar = _run_sidecar_critic(
        core_goal=core_goal,
        accepted_baseline=[str(f.get("value") or "") for f in accepted_facts],
        pending_proposals=[p["short_title"] for p in pending_proposals],
        open_pitfalls=[p["short_title"] for p in open_pitfalls],
        summary=summary,
        changed_files=files,
        timeout=critic_timeout,
    )
    if sidecar.get("status") == "evaluated" and sidecar.get("verdict") in {"warn", "fail"}:
        for finding in sidecar.get("findings") or []:
            warnings.append({
                "code": "sidecar_critic_finding",
                "message": f"旁路督导提醒：{finding}",
            })

    passed = len(blockers) == 0
    verdict = "blocked" if not passed else ("warn" if warnings else "pass")

    if not passed:
        nudge_1 = f"完工拦截：{blockers[0]['message']}"
    elif warnings:
        nudge_1 = f"完工提示：{warnings[0]['message']}"
    else:
        nudge_1 = f"完工核对通过：改动 {len(files) or len(file_change_events)} 处并附带校验依据。"

    nudge_2 = (
        f"当前基准 {len(accepted_facts)} 条 · 待确认 {len(pending_proposals)} 条 · 待办与待核实前提 {len(open_pitfalls)} 项；"
        + ("可点击下方看板入口确认新决策。" if pending_proposals else "可随时提醒用户查看看板全貌。")
    )

    return {
        "passed": passed,
        "verdict": verdict,
        "blockers": blockers,
        "warnings": warnings,
        "open_pitfalls": open_pitfalls[:6],
        "pending_proposals": pending_proposals[:6],
        "sidecar_critic": sidecar,
        "nudge_lines": [nudge_1, nudge_2],
    }
