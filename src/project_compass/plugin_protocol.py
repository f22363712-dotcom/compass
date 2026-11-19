from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from typing import Any

from .text_summary import (
    is_historical_doc_fact,
    select_next_consensus,
    select_primary_goal,
    summarize_node_title,
)

PROTOCOL_VERSION = 1


def validate_protocol_version(value: Any) -> None:
    if type(value) is not int or value != PROTOCOL_VERSION:
        raise ValueError(f"unsupported ProjectCompass plugin protocol version: {value!r}")


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    project_path: str
    member_id: str
    session_id: str
    agent: str
    schema_version: int = PROTOCOL_VERSION
    core_goal: str | None = None
    accepted_facts: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    entities: tuple[dict[str, Any], ...] = ()
    spills: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        validate_protocol_version(self.schema_version)
        _text(self.project_id, "project_id", 128)
        _text(self.project_path, "project_path", 2048)
        _text(self.member_id, "member_id", 120)
        _text(self.session_id, "session_id", 256)
        _text(self.agent, "agent", 64)

    def __hash__(self) -> int:
        return hash((self.project_id, self.project_path, self.member_id, self.session_id, self.agent, self.schema_version))

    @classmethod
    def for_project(cls, project_path: str | Path, member_id: str, session_id: str, agent: str) -> "ProjectContext":
        path = Path(project_path).expanduser().resolve()
        project_id = sha1(str(path).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        return cls(project_id, str(path), member_id, session_id, agent)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_path": self.project_path,
            "member_id": self.member_id,
            "session_id": self.session_id,
            "agent": self.agent,
        }
        if self.core_goal is not None:
            data["core_goal"] = self.core_goal
        if self.accepted_facts:
            data["accepted_facts"] = list(self.accepted_facts)
        if self.conflicts:
            data["conflicts"] = list(self.conflicts)
        if self.entities:
            data["entities"] = list(self.entities)
        if self.spills:
            data["spills"] = list(self.spills)
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProjectContext":
        if not isinstance(value, dict):
            raise ValueError("project context must be an object")
        core_goal = value.get("core_goal")
        accepted_facts = tuple(value.get("accepted_facts", ()))
        conflicts = tuple(value.get("conflicts", ()))
        entities = tuple(value.get("entities", ()))
        spills = tuple(value.get("spills", ()))
        return cls(
            value.get("project_id", ""),
            value.get("project_path", ""),
            value.get("member_id", ""),
            value.get("session_id", ""),
            value.get("agent", ""),
            value.get("schema_version", 0),
            core_goal=core_goal,
            accepted_facts=accepted_facts,
            conflicts=conflicts,
            entities=entities,
            spills=spills,
        )


def _format_size(byte_count: int) -> str:
    if byte_count < 1024:
        return f"{byte_count}B"
    return f"{byte_count / 1024:.1f}KB"


def build_compact_project_context(
    context: ProjectContext,
    state: dict[str, Any] | None = None,
    events: list[Any] | None = None,
) -> dict[str, Any]:
    """Produce an Inline & Spill compact context representation with strict baseline isolation."""
    state = state or {}
    team = state.get("team", {})
    team_facts = team.get("facts", [])

    # 1. Inline: Core Goal & Status (never claim an unconfirmed goal is accepted)
    core_goal = ""
    core_goal_status = "empty"
    handoff_brief = state.get("handoff_brief", {}) or {}
    handoff_goal = handoff_brief.get("goal")
    focus_goal = handoff_brief.get("focus_goal")
    selected_goal = select_primary_goal(team_facts)
    accepted_goals = [f for f in team_facts if f.get("kind") == "goal" and f.get("status") == "accepted"]

    if selected_goal is not None and selected_goal.get("status") == "accepted":
        core_goal = str(selected_goal.get("value") or selected_goal.get("quote") or "").strip()
        core_goal_status = "accepted"
    elif handoff_goal:
        core_goal = str(handoff_goal).strip()
        core_goal_status = "accepted" if accepted_goals else (selected_goal.get("status", "proposed") if selected_goal else "proposed")
    elif isinstance(focus_goal, dict) and focus_goal.get("fact_id") and focus_goal.get("value"):
        core_goal = str(focus_goal.get("value")).strip()
        core_goal_status = str(focus_goal.get("status") or "proposed")
    elif selected_goal is not None:
        core_goal = str(selected_goal.get("value") or selected_goal.get("quote") or "").strip()
        core_goal_status = str(selected_goal.get("status") or "proposed")

    if not core_goal and events:
        for ev in events:
            if getattr(ev, "kind", None) == "goal" or getattr(ev, "metadata", {}).get("kind") == "goal":
                core_goal = str(getattr(ev, "content", "") or "").strip()
                if core_goal:
                    core_goal_status = "proposed"
                break

    if not core_goal:
        core_goal = "核心目标待定锚"
        core_goal_status = "empty"

    next_consensus = state.get("next_consensus") or handoff_brief.get("next_consensus") or select_next_consensus(team_facts)

    # 2. Inline: Strictly Confirmed Baselines ONLY (never promote proposed candidates here)
    accepted = [fact for fact in team_facts if fact.get("status") == "accepted"][:5]
    accepted_subjects = {fact.get("subject_key") for fact in accepted if fact.get("subject_key")}

    compact_accepted = [
        {
            "id": fact.get("id"),
            "kind": fact.get("kind"),
            "subject_key": fact.get("subject_key"),
            "short_title": fact.get("short_title") or summarize_node_title(fact.get("value") or fact.get("quote") or "", max_chars=22),
            "summary": str(fact.get("value") or fact.get("quote") or "")[:50],
        }
        for fact in accepted
    ]

    # 2b. Inline: Active Unconfirmed Proposals & Open Pitfalls (anti-drift guardrails)
    pending_proposals = []
    open_pitfalls = []
    for fact in team_facts:
        status = fact.get("status")
        kind = fact.get("kind")
        if status == "rejected":
            continue
        if is_historical_doc_fact(fact):
            continue
        short_label = fact.get("short_title") or summarize_node_title(fact.get("value") or fact.get("quote") or "", max_chars=22)
        if status in {"proposed", "conflicted", "needs_evidence"} and fact.get("subject_key") not in accepted_subjects and kind in {"decision", "assumption", "goal"}:
            pending_proposals.append({
                "id": fact.get("id"),
                "kind": kind,
                "status": status,
                "short_title": short_label,
                "warning": "尚未定案，严禁当作已确认需求实现",
            })
        if kind == "task" and fact.get("task_state") != "completed":
            open_pitfalls.append({
                "id": fact.get("id"),
                "kind": "task",
                "short_title": short_label,
                "task_state": fact.get("task_state") or "pending",
            })
        elif kind == "assumption" and status != "accepted":
            open_pitfalls.append({
                "id": fact.get("id"),
                "kind": "assumption",
                "short_title": short_label,
                "task_state": "unverified",
            })

    pending_proposals = pending_proposals[:8]
    open_pitfalls = open_pitfalls[:6]

    # 3. Inline: Pending Conflicts Summary
    raw_conflicts = team.get("conflicts", [])
    compact_conflicts = []
    for c in raw_conflicts:
        sides = c.get("sides", [])
        sides_summary = " vs ".join(
            f"{s.get('author')}: {str(s.get('value', ''))[:40]}" for s in sides[:2]
        )
        compact_c = {
            "subject_key": c.get("subject_key"),
            "side_count": len(sides),
            "summary": sides_summary,
        }
        if "speculative_recommendation" in c:
            compact_c["speculative_recommendation"] = c["speculative_recommendation"]
        compact_conflicts.append(compact_c)

    # 4. Inline: Entity IDs + 50-char Short Summaries
    entities = []
    for fact in team_facts:
        if fact.get("kind") == "task":
            entities.append({
                "id": fact.get("id"),
                "kind": "task",
                "summary": str(fact.get("value") or "")[:50],
            })
            if len(entities) >= 5:
                break
    source_refs = state.get("derived_context", {}).get("evidence_source_refs", [])
    for ref in source_refs[:3]:
        entities.append({
            "id": ref,
            "kind": "source_ref",
            "summary": ref[:50],
        })

    # 5. Spill: Truncate long test stacks, raw command traces, logs into pointers
    spills = []
    all_ev = state.get("evidence", [])
    if not all_ev and events:
        all_ev = [ev.to_dict() if hasattr(ev, "to_dict") else ev for ev in events]

    spillable_kinds = {"test_result", "command_execution", "tool_result", "file_snapshot"}
    for ev in all_ev:
        ev_id = ev.get("id", "")
        kind = ev.get("kind", "")
        preview = ev.get("content_preview") or ev.get("content") or ""
        content = ev.get("content") or preview
        byte_size = len(str(content).encode("utf-8"))
        if kind in spillable_kinds or byte_size > 150:
            spills.append({
                "id": ev_id,
                "kind": kind,
                "bytes": byte_size,
                "pointer": f"[{ev_id}: {_format_size(byte_size)}] -> call query_state(\"{ev_id}\")",
                "summary": str(preview)[:50].replace("\n", " ").strip(),
            })

    next_short = ""
    next_summary = None
    if isinstance(next_consensus, dict) and (next_consensus.get("value") or next_consensus.get("short_title")):
        next_short = str(
            next_consensus.get("short_title")
            or summarize_node_title(next_consensus.get("value") or "", max_chars=22)
        )
        next_summary = {
            "short_title": next_short,
            "status": str(next_consensus.get("status") or "proposed"),
        }

    goal_short = summarize_node_title(core_goal, max_chars=26) if core_goal != "核心目标待定锚" else "核心目标待定锚"
    if compact_accepted or core_goal_status == "accepted":
        line_1 = f"已定案基准 {len(compact_accepted)} 条；目标「{goal_short}」（{'已定案' if core_goal_status == 'accepted' else '待拍板'}）。"
    elif core_goal_status == "proposed":
        line_1 = f"暂无已定案基准：目标「{goal_short}」及全部讨论仍属待拍板备选，实现前需向用户确认。"
    else:
        line_1 = "新项目尚未立目标：首次明确目标或关键取舍时，请调用 record_note 写入 15 字短标题。"

    top_hint = next(iter(state.get("agent_hints") or []), None)
    hint_tail = ""
    if isinstance(top_hint, dict) and top_hint.get("text"):
        hint_tail = f" · 提示：{summarize_node_title(top_hint['text'], max_chars=28)}"
    elif next_short:
        hint_tail = f" · 当前下一步「{next_short}」"

    line_2 = (
        f"待拍板 {len(pending_proposals)} 项 / 未填坑位 {len(open_pitfalls)} 项 / 分歧 {len(compact_conflicts)} 组{hint_tail}；"
        "遇到分叉或待办记一笔 record_note，报完工前先跑 verify_completion。"
    )
    nudge_lines = [line_1, line_2]

    inline_data = {
        "core_goal": core_goal,
        "core_goal_status": core_goal_status,
        **({"next_consensus": next_summary} if next_summary else {}),
        "accepted_count": len(compact_accepted),
        "pending_count": len(pending_proposals),
        "pitfall_count": len(open_pitfalls),
        "conflict_count": len(compact_conflicts),
        "nudge_lines": nudge_lines,
    }

    return {
        "schema_version": context.schema_version,
        "project_id": context.project_id,
        "project_path": context.project_path,
        "member_id": context.member_id,
        "session_id": context.session_id,
        "agent": context.agent,
        "inline": inline_data,
        "spills": spills,
        "core_goal": core_goal,
        "core_goal_status": core_goal_status,
        "accepted_facts": compact_accepted,
        "pending_proposals": pending_proposals,
        "open_pitfalls": open_pitfalls,
        "conflicts": compact_conflicts,
        "entities": entities,
        "nudge_lines": nudge_lines,
    }


@dataclass(frozen=True)
class StateQuery:
    context: ProjectContext
    question: str
    scopes: tuple[str, ...] = ("team", "personal", "evidence")

    def __post_init__(self) -> None:
        _text(self.question, "question", 2000)
        if not self.scopes or any(not isinstance(scope, str) or not scope.strip() for scope in self.scopes):
            raise ValueError("invalid state query scopes")

    def to_payload(self) -> dict[str, Any]:
        return {"schema_version": PROTOCOL_VERSION, "project_id": self.context.project_id,
                "question": self.question, "scopes": list(self.scopes)}


@dataclass(frozen=True)
class FactProposal:
    id: str
    context: ProjectContext
    source_id: str
    kind: str
    subject_key: str
    quote: str
    task_state: str | None = None

    def __post_init__(self) -> None:
        for value, name, limit in ((self.id, "proposal id", 128), (self.source_id, "source id", 256),
                                   (self.kind, "fact kind", 64), (self.subject_key, "subject key", 256),
                                   (self.quote, "quote", 48000)):
            _text(value, name, limit)
        if self.task_state is not None:
            _text(self.task_state, "task state", 64)

    def to_payload(self) -> dict[str, Any]:
        proposal = {"id": self.id, "source_id": self.source_id, "kind": self.kind,
                    "subject_key": self.subject_key, "quote": self.quote}
        if self.task_state is not None:
            proposal["task_state"] = self.task_state
        return {"schema_version": PROTOCOL_VERSION, "project_id": self.context.project_id,
                "proposals": [proposal]}


def _event_type(kind: str) -> str:
    allowed = {"user_message", "assistant_message", "tool_call", "tool_result", "test_result", "file_change"}
    if kind not in allowed:
        raise ValueError(f"unsupported plugin event type: {kind}")
    return kind


def _event_payload(event: Any, context: ProjectContext) -> dict[str, Any]:
    if getattr(event, "session_id", None) != context.session_id or getattr(event, "author", None) not in {context.member_id, context.agent}:
        raise ValueError("evidence event does not match project context")
    observed_at = event.observed_at
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("evidence event requires a timezone-aware timestamp")
    payload = {"id": _text(event.id, "event id", 128), "type": _event_type(event.kind),
               "timestamp": observed_at.isoformat(), "content": _text(event.content, "event content", 48000)}
    source_ref = getattr(event, "metadata", {}).get("source_ref")
    if isinstance(source_ref, str) and source_ref.strip():
        payload["source_ref"] = source_ref[:2048]
    return payload


def evidence_event_to_protocol_dict(event: Any, context: ProjectContext) -> dict[str, Any]:
    return {"schema_version": PROTOCOL_VERSION, "project_id": context.project_id,
            "event": _event_payload(event, context)}
