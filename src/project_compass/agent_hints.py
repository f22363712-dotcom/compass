"""Proactive local & async LLM Agent hints plus grounded investigation synthesis.

Pure Python standard library only. Never imports fact_engine, projections, or
candidate_extraction so L4 benchmark blast-radius contracts remain untouched.
"""

from __future__ import annotations

import json
import re
from threading import Lock, Thread
from typing import Any

from .llm_connector import (
    chat_completion_text,
    extract_json_object,
    resolve_llm_config,
)
from .text_summary import (
    clean_display_text,
    is_historical_doc_fact,
    select_next_consensus,
    select_primary_goal,
    summarize_node_title,
)

_TOKEN_RE = re.compile(r"[a-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_BRACKET_ID_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
_CRINGE_TERMS = ("参谋军师", "军师", "锦囊", "哨兵", "把脉")
_ALLOWED_HINT_CATEGORIES = frozenset({"推进建议", "偏航提醒", "风险提示", "待定锚点", "待拍板"})


def _extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in _TOKEN_RE.findall(str(text or "").casefold()):
        if chunk.isascii():
            tokens.add(chunk)
        elif len(chunk) == 2:
            tokens.add(chunk)
        else:
            for i in range(len(chunk) - 1):
                tokens.add(chunk[i : i + 2])
    return tokens


def _scrub_hint_text(text: str) -> str:
    cleaned = clean_display_text(text)
    for bad in _CRINGE_TERMS:
        cleaned = cleaned.replace(bad, "Agent ")
    return " ".join(cleaned.split()).strip()


def build_local_agent_hints(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build up to 2 instant, deterministic Agent hints from current state."""
    if not isinstance(state, dict):
        return []
    team = state.get("team") or {}
    team_facts = list(team.get("facts") or [])
    activity_stream = list(state.get("activity_stream") or [])
    evidence_count = int((state.get("project") or {}).get("evidence_count") or 0)

    if evidence_count == 0 and not team_facts:
        return [
            {
                "id": "hint-anchor-goal-empty",
                "category": "待定锚点",
                "level": "info",
                "text": "新项目尚未立目标，在上方目标卡写一句话定案即可同步全局分支。",
                "evidence_ids": [],
                "fact_id": None,
                "action_kind": "edit_goal",
                "action_label": "设定目标",
                "source": "local",
            }
        ]

    hints: list[dict[str, Any]] = []
    primary_goal = select_primary_goal(team_facts)
    next_consensus = state.get("next_consensus") or select_next_consensus(team_facts)
    has_explicit_next = bool(next_consensus and not next_consensus.get("is_candidate_suggestion"))

    if primary_goal is None:
        hints.append({
            "id": "hint-anchor-goal-empty",
            "category": "待定锚点",
            "level": "warn",
            "text": "尚未确立核心目标，点击上方目标卡用一句话定案后可对齐后续进展。",
            "evidence_ids": [],
            "fact_id": None,
            "action_kind": "edit_goal",
            "action_label": "设定目标",
            "source": "local",
        })
    elif primary_goal.get("status") != "accepted":
        goal_short = primary_goal.get("short_title") or summarize_node_title(primary_goal.get("value") or "", max_chars=22)
        hints.append({
            "id": f"hint-anchor-goal-{primary_goal.get('id', 'g')}",
            "category": "待定锚点",
            "level": "info",
            "text": f"核心目标「{goal_short}」尚未定案，可直接改写精简或一键定案。",
            "evidence_ids": list(primary_goal.get("evidence_ids") or [])[:2],
            "fact_id": primary_goal.get("id"),
            "action_kind": "accept_fact",
            "action_label": "✓ 定案目标",
            "source": "local",
        })
    elif not has_explicit_next:
        hints.append({
            "id": "hint-anchor-next-empty",
            "category": "待定锚点",
            "level": "info",
            "text": "核心目标已定案，建议补一句「下一步工作共识」锁定当前推进焦点。",
            "evidence_ids": list(next_consensus.get("evidence_ids") or [])[:2] if next_consensus else [],
            "fact_id": next_consensus.get("id") if next_consensus else None,
            "action_kind": "edit_next",
            "action_label": "设定下一步",
            "source": "local",
        })

    # Hint 2: Execution failure > edit drift > unconfirmed proposal backlog
    latest_failure = None
    for item in activity_stream[:4]:
        kind = item.get("action_kind")
        code = item.get("exit_code")
        if kind == "test" and code == 0:
            break
        if kind in {"test", "command"} and isinstance(code, int) and code != 0:
            latest_failure = item
            break

    if latest_failure is not None:
        fail_summary = clean_display_text(latest_failure.get("summary") or "最近测试或命令失败", max_chars=34)
        ev_ids = list(latest_failure.get("evidence_ids") or [])
        if not ev_ids and latest_failure.get("primary_evidence_id"):
            ev_ids = [latest_failure["primary_evidence_id"]]
        hints.append({
            "id": f"hint-fail-{ev_ids[0] if ev_ids else 'cmd'}",
            "category": "风险提示",
            "level": "warn",
            "text": f"近期运行未通过（{fail_summary}），建议先核查闭环再继续扩展。",
            "evidence_ids": ev_ids[:2],
            "fact_id": None,
            "action_kind": "open_evidence" if ev_ids else "",
            "action_label": "查看记录" if ev_ids else "",
            "source": "local",
        })
    else:
        recent_edits = [item for item in activity_stream[:4] if item.get("action_kind") == "edit"]
        anchor_text = " ".join(
            str(part or "")
            for part in (
                primary_goal.get("value") if primary_goal else "",
                next_consensus.get("value") if next_consensus else "",
            )
        )
        anchor_tokens = _extract_tokens(anchor_text)
        if has_explicit_next and len(recent_edits) >= 3 and anchor_tokens:
            edit_text = " ".join(f"{e.get('summary', '')} {e.get('source_ref', '')}" for e in recent_edits)
            if not (anchor_tokens & _extract_tokens(edit_text)):
                next_short = next_consensus.get("short_title") or summarize_node_title(next_consensus.get("value") or "", max_chars=20)
                hints.append({
                    "id": f"hint-drift-{next_consensus.get('id', 'next')}",
                    "category": "偏航提醒",
                    "level": "warn",
                    "text": f"近期连续修改与当前下一步「{next_short}」关联较弱，若重心已变可同步更新。",
                    "evidence_ids": list(recent_edits[0].get("evidence_ids") or [])[:2],
                    "fact_id": next_consensus.get("id"),
                    "action_kind": "edit_next",
                    "action_label": "更新下一步",
                    "source": "local",
                })

    if len(hints) < 2:
        pending_live = [
            f
            for f in team_facts
            if f.get("kind") in {"decision", "assumption"}
            and f.get("status") in {"proposed", "conflicted"}
            and not is_historical_doc_fact(f)
        ]
        if len(pending_live) >= 3:
            first_item = pending_live[-1]
            first_short = first_item.get("short_title") or summarize_node_title(first_item.get("value") or "", max_chars=20)
            hints.append({
                "id": f"hint-backlog-{len(pending_live)}-{first_item.get('id', 'p')}",
                "category": "待拍板",
                "level": "info",
                "text": f"当前有 {len(pending_live)} 项待拍板思路（最新如「{first_short}」），及时定案可收敛分支。",
                "evidence_ids": list(first_item.get("evidence_ids") or [])[:2],
                "fact_id": first_item.get("id"),
                "action_kind": "accept_fact",
                "action_label": "✓ 定案最新项",
                "source": "local",
            })

    return hints[:2]


class AsyncHintCache:
    """Thread-safe revision-keyed cache computing optional LLM Agent hints in the background."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._done: dict[str, dict[str, Any] | None] = {}
        self._inflight: set[str] = set()
        self._generation = 0
        self._epoch = 0

    def clear(self) -> None:
        with self._lock:
            self._done.clear()
            self._inflight.clear()
            self._epoch += 1
            self._generation += 1

    def get_or_schedule(
        self,
        revision: str,
        state: dict[str, Any],
        *,
        sample_mode: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        local_hints = build_local_agent_hints(state)
        cfg = resolve_llm_config()
        evidence_count = int((state.get("project") or {}).get("evidence_count") or 0)
        if sample_mode or not cfg["enabled"] or evidence_count == 0 or not revision:
            return local_hints[:2], 0

        with self._lock:
            generation = self._generation
            spawn_epoch = self._epoch
            if revision in self._done:
                cached = self._done[revision]
                return self._merge_hints(local_hints, cached), generation
            should_spawn = revision not in self._inflight
            if should_spawn:
                self._inflight.add(revision)

        if should_spawn:
            snapshot = self._build_snapshot(state)
            known_ev_ids = {
                str(ev.get("id"))
                for ev in (state.get("evidence") or [])
                if isinstance(ev, dict) and ev.get("id")
            }
            thread = Thread(
                target=self._worker,
                args=(revision, snapshot, known_ev_ids, str(cfg["model"] or ""), spawn_epoch),
                daemon=True,
            )
            thread.start()

        return local_hints[:2], generation

    @staticmethod
    def _merge_hints(local_hints: list[dict[str, Any]], llm_hint: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not llm_hint:
            return local_hints[:2]
        merged = [llm_hint]
        if local_hints:
            merged.append(local_hints[0])
        return merged[:2]

    @staticmethod
    def _build_snapshot(state: dict[str, Any]) -> dict[str, Any]:
        team = state.get("team") or {}
        team_facts = list(team.get("facts") or [])
        goal = select_primary_goal(team_facts)
        next_step = state.get("next_consensus") or select_next_consensus(team_facts)
        accepted = [
            f.get("short_title") or clean_display_text(f.get("value") or "", max_chars=40)
            for f in team_facts
            if f.get("status") == "accepted"
        ][:4]
        pending = [
            f.get("short_title") or clean_display_text(f.get("value") or "", max_chars=40)
            for f in team_facts
            if f.get("status") in {"proposed", "conflicted"} and not is_historical_doc_fact(f)
        ][:4]
        recent_activity = [
            {
                "kind": item.get("action_kind"),
                "summary": clean_display_text(item.get("summary") or "", max_chars=60),
                "evidence_id": item.get("primary_evidence_id") or "",
            }
            for item in (state.get("activity_stream") or [])[:4]
        ]
        return {
            "core_goal": clean_display_text(goal.get("value") if goal else "", max_chars=80),
            "goal_status": goal.get("status") if goal else "empty",
            "next_step": clean_display_text(next_step.get("value") if next_step else "", max_chars=80),
            "accepted_baselines": accepted,
            "pending_items": pending,
            "recent_activity": recent_activity,
        }

    def _worker(
        self,
        revision: str,
        snapshot: dict[str, Any],
        known_ev_ids: set[str],
        model_name: str,
        spawn_epoch: int = 0,
    ) -> None:
        hint_obj: dict[str, Any] | None = None
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是代码项目的实时协作辅助提示器。根据当前目标、下一步、已定案基准、待拍板项和最近动作，"
                        "提炼 1 条简洁克制的中文提示（15～58字，只指出偏航、遗漏验证、未闭环风险或最值得确认的下一步）。"
                        '严格只输出 JSON：{"category":"推进建议|偏航提醒|风险提示","text":"...","evidence_id":"可为空或来自recent_activity"}。'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(snapshot, ensure_ascii=False),
                },
            ]
            raw_text, err = chat_completion_text(
                messages,
                max_tokens=700,
                timeout=7.5,
                temperature=0.1,
            )
            if not err and raw_text:
                parsed = extract_json_object(raw_text) or {}
                category = str(parsed.get("category") or "推进建议").strip()
                if category not in _ALLOWED_HINT_CATEGORIES:
                    category = "推进建议"
                text = _scrub_hint_text(str(parsed.get("text") or ""))
                if 8 <= len(text) <= 84:
                    ev_id = str(parsed.get("evidence_id") or "").strip()
                    valid_ev_ids = [ev_id] if (ev_id and ev_id in known_ev_ids) else []
                    hint_obj = {
                        "id": f"hint-llm-{revision[:10]}",
                        "category": category,
                        "level": "warn" if category in {"偏航提醒", "风险提示"} else "info",
                        "text": text,
                        "evidence_ids": valid_ev_ids,
                        "fact_id": None,
                        "action_kind": "open_evidence" if valid_ev_ids else "",
                        "action_label": "查看依据" if valid_ev_ids else "",
                        "source": "llm",
                        "model": model_name,
                    }
        finally:
            with self._lock:
                self._inflight.discard(revision)
                if self._epoch == spawn_epoch:
                    self._done[revision] = hint_obj
                    if len(self._done) > 16:
                        self._done.pop(next(iter(self._done)))
                    self._generation += 1


def synthesize_investigation_summary(
    question: str,
    answer_dict: dict[str, Any],
    *,
    timeout: float = 8.0,
) -> str:
    """Summarize retrieved findings into 1-2 grounded Chinese sentences when an LLM is configured."""
    cfg = resolve_llm_config()
    if not cfg["enabled"]:
        return ""
    gaps = [str(g) for g in (answer_dict.get("evidence_gaps") or [])]
    if any("尚未得到回答" in g for g in gaps):
        return ""
    findings = list(answer_dict.get("findings") or [])
    completed_items = list(answer_dict.get("completed_items") or [])
    if not findings and not completed_items and not answer_dict.get("evidence_ids"):
        return ""

    known_ids = {str(eid) for eid in (answer_dict.get("evidence_ids") or []) if eid}
    for row in [*findings, *completed_items]:
        for eid in row.get("evidence_ids") or []:
            if eid:
                known_ids.add(str(eid))

    compact_findings = [
        {
            "kind": row.get("kind") or row.get("claim_type"),
            "status": row.get("status"),
            "evidence_ids": list(row.get("evidence_ids") or [])[:2],
            "quote": clean_display_text(row.get("quote") or "", max_chars=260),
        }
        for row in findings[:5]
    ]
    payload: dict[str, Any] = {
        "question": str(question or "")[:200],
        "goal": clean_display_text(answer_dict.get("goal") or "", max_chars=80),
        "next_action": clean_display_text(answer_dict.get("next_action") or "", max_chars=100),
        "next_action_status": answer_dict.get("next_action_status"),
        "findings": compact_findings,
    }
    if completed_items:
        payload["completed_items"] = [
            {
                "kind": row.get("kind") or row.get("claim_type"),
                "status": row.get("status"),
                "observed_at": row.get("observed_at"),
                "evidence_ids": list(row.get("evidence_ids") or [])[:2],
                "quote": clean_display_text(row.get("quote") or "", max_chars=240),
            }
            for row in completed_items[:3]
        ]
    messages = [
        {
            "role": "system",
            "content": (
                "你是 Compass 证据归纳助手。只根据提供的问题和真实记录摘要，"
                "用 1～2 句简练大白话（不超过 100 字）直接回答；"
                "若问题询问最近完成的工作或最新进展且数据提供了 completed_items，"
                "请优先按 completed_items 最新顺序概括已完成成果，切勿把未完成的 next_action 当作已完成事项；"
                "若同时问及目标与下一步，请明确写出核心目标和接下来要做的事；"
                "如需引用编号，只能原样使用数据里的 evidence_ids，严禁编造未出现的编号或结论。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]
    raw_reply, err = chat_completion_text(
        messages,
        max_tokens=700,
        timeout=timeout,
        temperature=0.05,
    )
    if err or not raw_reply:
        return ""

    def _keep_known_id(match: re.Match[str]) -> str:
        token = match.group(1)
        return f"[{token}]" if token in known_ids else ""

    sanitized = _BRACKET_ID_RE.sub(_keep_known_id, raw_reply)
    sanitized = _scrub_hint_text(sanitized)
    if len(sanitized) > 160:
        sanitized = summarize_node_title(sanitized, max_chars=160)
    return sanitized
