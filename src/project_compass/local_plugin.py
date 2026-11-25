from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agent_inbox import AgentInbox
from .completion_gate import evaluate_completion_gate
from .dashboard import build_dashboard_state, build_mindmap_tree
from .decision_graph import (
    classify_mindmap_topic,
    is_legacy_noise_fact,
    is_owner_dialogue_decided_fact,
)
from .doc_fact_intake import record_document_candidates
from .evidence_filters import as_utc_timestamp
from .investigator import investigate
from .plugin_protocol import (
    FactProposal,
    ProjectContext,
    StateQuery,
    build_compact_project_context,
    evidence_event_to_protocol_dict,
    validate_protocol_version,
)
from .project_refresh import ProjectRescan
from .project_scanner import scan_project
from .team_templates import (
    extract_priority_dispatches,
    list_team_templates,
    record_priority_dispatch,
)
from .text_summary import (
    is_historical_doc_fact,
    select_next_consensus,
    select_primary_goal,
    summarize_node_title,
)


def cold_start_bootstrap_workspace(workspace) -> tuple[list, bool]:
    """Perform read-only cold-start doc scan & candidate intake when a workspace has no saved events."""
    has_events = workspace.exists() and len(workspace.load()) > 0
    if has_events:
        return workspace.load(), False
    scanned = [
        ev for ev in scan_project(workspace.project_path)
        if ev.kind == "file_snapshot"
    ]
    if scanned:
        workspace.save(scanned, {"source": "cold_start_bootstrap"}, complete_scan=True)
        loaded_events = workspace.load()
        record_document_candidates(loaded_events, workspace)
        return workspace.load(), True
    return ([], False)


_WORKBENCH_ACTIONS = frozenset({
    "state",
    "scan_docs",
    "accept_fact",
    "reject_fact",
    "complete_fact",
    "record_note",
    "dispatch_priority",
})
_OWNER_ONLY_WORKBENCH_ACTIONS = frozenset({"accept_fact", "reject_fact", "complete_fact", "scan_docs"})
STALE_PENDING_SECONDS = 72 * 3600


def _coerce_timestamp(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not value:
        return 0.0
    try:
        return as_utc_timestamp(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _build_workbench_payload(
    events,
    *,
    project_path,
    confirmed,
    history,
    fact_reviews,
    context: ProjectContext,
    agent_inbox=None,
    bootstrapped: bool = False,
    role_mode: str = "owner",
    can_review: bool = True,
    state: dict | None = None,
    priority_dispatches: list[dict] | None = None,
    status_note: str = "",
) -> dict:
    """Build the unified interactive workbench payload shared by local owner and member seats."""
    if state is None:
        state = build_dashboard_state(
            events,
            project_path=str(project_path),
            confirmed_relations=confirmed,
            review_history=history,
            fact_reviews=fact_reviews,
        )

    combined_reviews = [
        *(state.get("fact_reviews") or fact_reviews or []),
        *(state.get("review_history") or history or []),
    ]
    latest_review: dict[str, dict] = {}
    completed_ids: set[str] = set()
    for item in combined_reviews:
        fid = item.get("fact_id")
        act = item.get("action")
        if not fid:
            continue
        fid_str = str(fid)
        if act == "complete_fact":
            completed_ids.add(fid_str)
            continue
        if act != "confirm_relation":
            latest_review[fid_str] = item
    rejected_ids = {fid for fid, rev in latest_review.items() if rev.get("action") == "reject_fact"}

    def _is_completed(fact: dict) -> bool:
        return bool(
            fact.get("completed")
            or fact.get("task_state") in {"completed", "reported_complete"}
            or str(fact.get("id") or "") in completed_ids
        )

    team = state.get("team") or {}
    team_facts = list(team.get("facts") or [])
    fact_by_id = {str(f.get("id") or ""): f for f in team_facts if f.get("id")}
    active_facts = [f for f in team_facts if str(f.get("id") or "") not in rejected_ids]
    accepted_subjects = {
        str(f.get("subject_key") or "")
        for f in active_facts
        if f.get("status") == "accepted" and f.get("subject_key")
    }

    templates = list_team_templates()
    if agent_inbox is not None:
        pub = agent_inbox.public_status()
        team_block = {
            "enabled": bool(pub.get("enabled", True)),
            "owner_id": pub.get("owner_id") or context.member_id,
            "seats": list(pub.get("clients") or []),
            "templates": templates,
        }
    elif isinstance(state.get("agent_api"), dict) and state["agent_api"].get("enabled"):
        api_info = state["agent_api"]
        team_block = {
            "enabled": True,
            "owner_id": api_info.get("owner_id") or context.member_id,
            "seats": list(api_info.get("clients") or []),
            "templates": templates,
        }
    else:
        team_block = {
            "enabled": False,
            "owner_id": context.member_id,
            "seats": [],
            "templates": templates,
        }
    team_enabled = bool(team_block.get("enabled"))
    owner_id = str(team_block.get("owner_id") or context.member_id)

    events_by_id = {str(ev.id): ev for ev in (events or ()) if getattr(ev, "id", None)}

    def _fact_source_event(fact: dict):
        for eid in fact.get("evidence_ids") or []:
            ev = events_by_id.get(str(eid))
            if ev is not None:
                return ev
        return None

    def _resolve_title(fact: dict, *, max_chars: int = 34) -> str:
        raw_val = str(fact.get("value") or fact.get("quote") or "").strip()
        src_ev = _fact_source_event(fact)
        explicit = None
        if src_ev is not None and isinstance(getattr(src_ev, "metadata", None), dict):
            explicit = src_ev.metadata.get("short_title")
        if explicit:
            return summarize_node_title(raw_val, explicit_title=explicit, max_chars=max_chars)
        return summarize_node_title(raw_val, max_chars=max_chars)

    def _is_current(fact: dict) -> bool:
        return (fact.get("source_state") or {}).get("status") not in {"superseded", "unavailable"}

    def _is_doc_origin(fact: dict) -> bool:
        if fact.get("is_historical_doc") or is_historical_doc_fact(fact):
            return True
        return fact.get("status") != "accepted" and str(fact.get("author") or "").strip().lower() == "project-documents"

    ev_ts_map: dict[str, float] = {}
    reference_ts = 0.0
    for ev in events or ():
        ts = _coerce_timestamp(getattr(ev, "observed_at", None))
        if ts > 0:
            ev_ts_map[str(ev.id)] = ts
            if ts > reference_ts:
                reference_ts = ts
    for ev_item in state.get("evidence") or []:
        ev_id = ev_item.get("id")
        ts = _coerce_timestamp(ev_item.get("observed_at"))
        if ts > 0:
            if ev_id:
                ev_ts_map.setdefault(str(ev_id), ts)
            if ts > reference_ts:
                reference_ts = ts

    def _fact_ts(fact: dict) -> float:
        ts = _coerce_timestamp(fact.get("observed_at") or fact.get("timestamp"))
        if ts > 0:
            return ts
        best = 0.0
        for eid in fact.get("evidence_ids") or []:
            cand = ev_ts_map.get(str(eid), 0.0)
            if cand > best:
                best = cand
        return best

    for f in active_facts:
        ts = _fact_ts(f)
        if ts > reference_ts:
            reference_ts = ts

    dialogue_decided_ids: set[str] = set()
    for f in active_facts:
        fid = str(f.get("id") or "")
        if not fid or _is_completed(f) or f.get("superseded_by_fact_id") or not _is_current(f):
            continue
        if f.get("subject_key") in accepted_subjects:
            continue
        if is_owner_dialogue_decided_fact(
            f,
            _fact_source_event(f),
            owner_id=owner_id,
            can_review=bool(can_review),
            team_enabled=team_enabled,
        ):
            dialogue_decided_ids.add(fid)

    goal_fact = select_primary_goal(active_facts)
    if goal_fact:
        core_goal = {
            "fact_id": goal_fact.get("id"),
            "text": _resolve_title(goal_fact, max_chars=28),
            "full_text": str(goal_fact.get("value") or "").strip(),
            "status": str(goal_fact.get("status") or "proposed"),
            "evidence_ids": list(goal_fact.get("evidence_ids") or [])[:4],
        }
    else:
        core_goal = {
            "fact_id": None,
            "text": "暂未设定核心目标",
            "status": "missing",
            "evidence_ids": [],
        }

    next_candidates = [
        f
        for f in active_facts
        if not _is_completed(f)
        and not is_legacy_noise_fact(f)
        and str(f.get("id") or "") not in dialogue_decided_ids
    ]
    next_fact = select_next_consensus(next_candidates)
    if next_fact:
        next_step = {
            "fact_id": next_fact.get("id"),
            "kind": str(next_fact.get("kind") or "task"),
            "completed": False,
            "text": _resolve_title(next_fact, max_chars=34),
            "full_text": str(next_fact.get("value") or "").strip(),
            "status": str(next_fact.get("status") or "proposed"),
            "evidence_ids": list(next_fact.get("evidence_ids") or [])[:4],
        }
    else:
        next_step = {
            "fact_id": None,
            "kind": "task",
            "completed": False,
            "text": "暂未设定当前下一步",
            "status": "missing",
            "evidence_ids": [],
        }

    def _to_item(fact: dict, *, allow_stale: bool = False) -> dict:
        raw_val = str(fact.get("value") or fact.get("quote") or "").strip()
        kind = str(fact.get("kind") or "decision")
        fid = str(fact.get("id") or "")
        item_ts = _fact_ts(fact)
        is_stale = bool(
            allow_stale
            and reference_ts > 0
            and item_ts > 0
            and (reference_ts - item_ts) > STALE_PENDING_SECONDS
        )
        raw_status = str(fact.get("status") or "proposed")
        if fid in dialogue_decided_ids:
            eff_status = "dialogue_decided"
            decision_origin = "dialogue_selected"
        elif raw_status == "accepted":
            eff_status = "accepted"
            decision_origin = "manual_confirmed"
        else:
            eff_status = raw_status
            decision_origin = "pending"
        item_dict = {
            "fact_id": fid,
            "kind": kind,
            "title": _resolve_title(fact, max_chars=28 if kind == "goal" else 34),
            "value": str(fact.get("clean_value") or raw_val).strip(),
            "quote": str(fact.get("quote") or "").strip(),
            "status": eff_status,
            "decision_origin": decision_origin,
            "observed_at": str(fact.get("observed_at") or ""),
            "completed": _is_completed(fact),
            "is_stale": is_stale,
            "evidence_ids": list(fact.get("evidence_ids") or [])[:4],
            "member_id": str(fact.get("author") or ""),
            "session_id": str(fact.get("session_id") or ""),
        }
        if isinstance(fact.get("decision_context"), dict):
            item_dict["decision_context"] = fact["decision_context"]
        return item_dict

    mindmap = build_mindmap_tree(state)
    filtered_nodes: list[dict] = []
    for node in mindmap.get("nodes") or []:
        nid = str(node.get("id") or "")
        src = fact_by_id.get(nid)
        if src is not None and is_legacy_noise_fact(src):
            continue
        node_copy = dict(node)
        if src is not None:
            node_copy["completed"] = _is_completed(src)
            node_copy["title"] = _resolve_title(src, max_chars=34)
            if nid in dialogue_decided_ids:
                node_copy["status"] = "dialogue_decided"
                node_copy["decision_origin"] = "dialogue_selected"
            elif src.get("status") == "accepted":
                node_copy["decision_origin"] = "manual_confirmed"
            else:
                node_copy["decision_origin"] = "pending"
        filtered_nodes.append(node_copy)
    mindmap["nodes"] = filtered_nodes

    root_goal_id = str(core_goal.get("fact_id") or "")
    map_pool = [
        f
        for f in active_facts
        if str(f.get("id") or "") != root_goal_id
        and _is_current(f)
        and not f.get("superseded_by_fact_id")
        and not is_legacy_noise_fact(f)
    ]
    live_map_facts = [f for f in map_pool if not _is_doc_origin(f)]
    doc_map_facts = [f for f in map_pool if _is_doc_origin(f)]
    chosen_map_facts = live_map_facts if live_map_facts else doc_map_facts[:6]

    topic_defs = (
        ("product_ux", "产品与界面体验", "视觉样式、交互布局与易用性细节"),
        ("architecture", "架构与技术规则", "技术选型、权限隔离、接口与数据规则"),
        ("execution", "当前待办与推进", "近期待落地、验收或执行的事项"),
        ("open_risks", "待核实前提与分歧", "仍待验证的前提条件或未决分歧"),
        ("decisions", "其他项目决定", "日常沟通过程中形成的技术或协作约定"),
        ("archive", "历史里程碑与更早记录", "已完成任务、早期版本里程碑与超过 72 小时的旧记录"),
    )
    bucket_items: dict[str, list[tuple[dict, float]]] = {k: [] for k, _, _ in topic_defs}
    for f in chosen_map_facts:
        item_payload = _to_item(f, allow_stale=True)
        topic_key = classify_mindmap_topic(
            f,
            is_completed=item_payload["completed"],
            is_stale=item_payload["is_stale"],
        )
        bucket_items.setdefault(topic_key, []).append((item_payload, _fact_ts(f)))

    mindmap_groups: list[dict] = []
    for g_key, g_title, g_sub in topic_defs:
        rows = bucket_items.get(g_key) or []
        if not rows:
            continue
        if g_key == "archive":
            rows.sort(key=lambda pair: -pair[1])
        else:
            rows.sort(
                key=lambda pair: (
                    0 if pair[0]["status"] in {"conflicted", "proposed"} else 1,
                    -pair[1],
                )
            )
        items_only = [pair[0] for pair in rows]
        mindmap_groups.append({
            "key": g_key,
            "title": g_title,
            "subtitle": g_sub,
            "collapsed_by_default": g_key == "archive",
            "count": len(items_only),
            "pending_count": sum(
                1 for x in items_only if not x.get("completed") and x["status"] in {"proposed", "conflicted"}
            ),
            "items": items_only,
        })
    mindmap["groups"] = mindmap_groups

    raw_pending_pool = [
        f
        for f in active_facts
        if f.get("status") in {"proposed", "conflicted", "needs_evidence"}
        and f.get("subject_key") not in accepted_subjects
        and str(f.get("id") or "") not in dialogue_decided_ids
        and not f.get("superseded_by_fact_id")
        and not _is_completed(f)
        and _is_current(f)
    ]
    legacy_noise_count = sum(1 for f in raw_pending_pool if is_legacy_noise_fact(f))
    pending_pool = [f for f in raw_pending_pool if not is_legacy_noise_fact(f)]

    live_pending = [f for f in pending_pool if not _is_doc_origin(f)]
    doc_pending = [f for f in pending_pool if _is_doc_origin(f)]
    ordered_pending = list(live_pending)
    if not ordered_pending and doc_pending:
        ordered_pending.extend(doc_pending[:3])

    manual_accepted_items = [
        _to_item(f, allow_stale=True)
        for f in active_facts
        if f.get("status") == "accepted" and _is_current(f)
    ]
    dialogue_accepted_items = [
        _to_item(f, allow_stale=True)
        for f in reversed(active_facts)
        if str(f.get("id") or "") in dialogue_decided_ids and _is_current(f)
    ]
    accepted_items = [*manual_accepted_items, *dialogue_accepted_items]
    pending_items = [_to_item(f, allow_stale=True) for f in ordered_pending]
    active_pending_count = sum(1 for item in pending_items if not item.get("is_stale"))
    stale_pending_count = sum(1 for item in pending_items if item.get("is_stale"))

    active_conflicts: list[dict] = []
    for conflict in team.get("conflicts") or []:
        sides = [s for s in (conflict.get("sides") or []) if str(s.get("fact_id") or "") not in rejected_ids]
        if any(s.get("status") == "accepted" for s in sides):
            continue
        if len({str(s.get("value") or "") for s in sides}) <= 1:
            continue
        live_authors = {
            str(s.get("author") or "").strip().casefold()
            for s in sides
            if not is_historical_doc_fact(s) and str(s.get("author") or "").strip()
        }
        if len(live_authors) <= 1:
            continue
        item = {
            "subject_key": conflict.get("subject_key"),
            "sides": sides,
        }
        if "speculative_recommendation" in conflict:
            item["speculative_recommendation"] = conflict["speculative_recommendation"]
        active_conflicts.append(item)

    if priority_dispatches is not None:
        dispatches = list(priority_dispatches)
    elif events:
        dispatches = extract_priority_dispatches(events)
    else:
        dispatches = list(state.get("priority_dispatches") or [])

    project_meta = state.get("project") or {}
    project_name = str(project_meta.get("name") or Path(project_path).name or "Compass")
    ev_count = int(project_meta.get("evidence_count") or 0)
    effective_note = status_note
    if not effective_note:
        effective_note = (
            "暂无历史记录，可随时在左栏对话记账"
            if (ev_count == 0 and not active_facts and not bootstrapped)
            else "已就绪"
        )

    return {
        "project_path": str(project_path),
        "project_name": project_name,
        "session_id": context.session_id,
        "member_id": context.member_id,
        "role_mode": role_mode,
        "can_review": bool(can_review),
        "bootstrapped": bool(bootstrapped),
        "core_goal": core_goal,
        "next_step": next_step,
        "mindmap": mindmap,
        "pending_items": pending_items,
        "active_pending_count": active_pending_count,
        "stale_pending_count": stale_pending_count,
        "filtered_legacy_noise_count": legacy_noise_count,
        "dialogue_decided_count": len(dialogue_decided_ids),
        "accepted_items": accepted_items,
        "conflicts": active_conflicts,
        "priority_dispatches": dispatches,
        "team": team_block,
        "status_note": effective_note,
    }


class PluginRequestError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


class LocalPluginAdapter:
    """Small MCP-style local adapter over the existing project-bound Agent API."""

    METHODS = {
        "project.context",
        "evidence.append",
        "state.query",
        "fact.propose",
        "note.record",
        "completion.verify",
        "workbench.open",
        "workbench.action",
    }
    STATE_SCOPES = {"team", "personal", "evidence", "requests", "history"}

    def __init__(self, base_url: str, context: ProjectContext, token: str, *, timeout: float = 5.0, workspace=None):
        if not isinstance(base_url, str) or not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("local plugin adapter requires a loopback HTTP URL")
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
            raise ValueError("invalid plugin credential")
        self.base_url = base_url.rstrip("/")
        self.context = context
        self.token = token
        self.timeout = timeout
        self.workspace = workspace
        self._cached_context: dict | None = None

    def dispatch(self, method: str, params: dict) -> dict:
        if method not in self.METHODS:
            raise ValueError(f"unsupported plugin method: {method}")
        if not isinstance(params, dict):
            raise ValueError("plugin params must be an object")
        if method == "project.context":
            if not params.get("refresh") and self._cached_context is not None:
                return self._cached_context
            try:
                state = self._get("/api/agent/state")
                compact = build_compact_project_context(self.context, state)
                if "priority_dispatches" in state:
                    compact["priority_dispatches"] = list(state.get("priority_dispatches") or [])
            except Exception:
                if self.workspace is not None and hasattr(self.workspace, "compact_context"):
                    compact = self.workspace.compact_context(
                        member_id=self.context.member_id,
                        session_id=self.context.session_id,
                        agent=self.context.agent,
                    )
                else:
                    compact = self.context.to_dict()
            self._cached_context = compact
            return compact
        if method == "workbench.open":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("workbench project mismatch")
            state = self._get("/api/agent/state")
            return _build_workbench_payload(
                [],
                project_path=self.context.project_path,
                confirmed=(),
                history=state.get("review_history", []),
                fact_reviews=state.get("fact_reviews", []),
                context=self.context,
                bootstrapped=False,
                role_mode="member",
                can_review=False,
                state=state,
            )
        if method == "workbench.action":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("workbench project mismatch")
            action = str(params.get("action") or "state").strip()
            if action not in _WORKBENCH_ACTIONS:
                raise ValueError(f"unsupported workbench action: {action}")
            if action in _OWNER_ONLY_WORKBENCH_ACTIONS:
                raise PermissionError("owner confirmation permission required; member seats may only propose or record notes")
            if action == "state":
                return self.dispatch("workbench.open", params)
            if action == "record_note":
                note_payload = {
                    k: v
                    for k, v in params.items()
                    if k in {"text", "kind", "title", "client_nonce", "project_id"}
                }
                self.dispatch("note.record", note_payload)
                payload = self.dispatch("workbench.open", {"project_id": project_id})
                payload["status_note"] = "已记录个人想法"
                return payload
            if action == "dispatch_priority":
                fact_id = str(params.get("fact_id") or "").strip()
                title = str(params.get("title") or "").strip()
                value = str(params.get("value") or "").strip()
                if not fact_id or not value:
                    raise ValueError("fact_id and value are required for dispatch_priority")
                short = title or summarize_node_title(value, max_chars=22)
                self.dispatch(
                    "note.record",
                    {
                        "project_id": project_id,
                        "kind": "task",
                        "title": short,
                        "text": f"[协作者推进引用] {short} — {value}",
                        "client_nonce": str(params.get("client_nonce") or ""),
                    },
                )
                payload = self.dispatch("workbench.open", {"project_id": project_id})
                payload["status_note"] = "已提交推进引用（正式优先列表需负责人确认）"
                return payload
            raise AssertionError("unreachable")
        if method == "evidence.append":
            envelope = params.get("event")
            if not isinstance(envelope, dict):
                raise ValueError("evidence.append requires an event envelope")
            validate_protocol_version(envelope.get("schema_version"))
            project_id = envelope.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("plugin event project mismatch")
            event = envelope.get("event")
            if not isinstance(event, dict):
                raise ValueError("plugin event must be an object")
            result = self._post("/api/agent/events", {"schema_version": 1, "events": [event]})
            self._cached_context = None
            return result
        if method == "state.query":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("state query project mismatch")
            question = params.get("question") or params.get("evidence_id") or params.get("id") or ""
            query = StateQuery(self.context, question, tuple(params.get("scopes", ("team", "personal", "evidence"))))
            unknown = set(query.scopes) - self.STATE_SCOPES
            if unknown:
                raise ValueError("unsupported state query scope")
            response = self._post("/api/agent/query", {"question": query.question})
            if not isinstance(response.get("state"), dict) or not isinstance(response.get("answer"), dict):
                raise PluginRequestError(None, "ProjectCompass plugin returned an invalid query result")
            result = self._project_state(response["state"], query)
            result["answer"] = self._structure_answer(response["answer"], response["state"], query)
            result["investigation_stats"] = response["state"].get("investigation_stats", {})
            return result
        if method == "fact.propose":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("fact proposal project mismatch")
            proposal = dict(params)
            proposal.pop("project_id", None)
            validate_protocol_version(proposal.get("schema_version"))
            proposal["proposals"] = proposal.get("proposals", [])
            result = self._post("/api/agent/proposals", {"schema_version": 1, "proposals": proposal["proposals"]})
            self._cached_context = None
            return result
        if method == "note.record":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("note record project mismatch")
            note_payload = {k: v for k, v in params.items() if k != "project_id"}
            note_payload.setdefault("schema_version", 1)
            result = self._post("/api/agent/notes", note_payload)
            self._cached_context = None
            return result
        if method == "completion.verify":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("completion verify project mismatch")
            verify_payload = {k: v for k, v in params.items() if k != "project_id"}
            return self._post("/api/agent/verify-completion", verify_payload)
        raise AssertionError("unreachable")

    def append_event(self, event) -> dict:
        return self.dispatch("evidence.append", {"event": evidence_event_to_protocol_dict(event, self.context)})

    def query_state(self, query: StateQuery) -> dict:
        return self.dispatch("state.query", query.to_payload())

    def propose_fact(self, proposal: FactProposal) -> dict:
        return self.dispatch("fact.propose", proposal.to_payload())

    def _project_state(self, payload: dict, query: StateQuery) -> dict:
        """Return a bounded, member-scoped view for an Agent query."""
        result = {
            "schema_version": query.context.schema_version,
            "project": payload.get("project", {}),
            "state_version": payload.get("state_version"),
            "question": query.question,
            "scopes": list(query.scopes),
        }
        selected_ids: set[str] = set()
        if "team" in query.scopes:
            result["team"] = payload.get("team", {})
            selected_ids.update(result["team"].get("evidence_ids", []))
        if "personal" in query.scopes:
            personal = payload.get("personal", {}).get(query.context.member_id, {"member_id": query.context.member_id, "facts": [], "evidence_ids": []})
            result["personal"] = personal
            selected_ids.update(personal.get("evidence_ids", []))
        if "requests" in query.scopes:
            requests = [item for item in payload.get("evidence_requests", []) if item.get("member_id") == query.context.member_id]
            result["evidence_requests"] = requests
            for item in requests:
                selected_ids.update(item.get("requested_evidence_ids", []))
                selected_ids.update(item.get("new_evidence_ids", []))
        if "history" in query.scopes:
            result["review_history"] = payload.get("review_history", [])
        if "evidence" in query.scopes:
            catalog = payload.get("evidence", [])
            result["evidence"] = [item for item in catalog if not selected_ids or item.get("id") in selected_ids]
            result["candidate_relations"] = [item for item in payload.get("candidate_relations", []) if not selected_ids or item.get("evidence_id") in selected_ids]
            result["confirmed_relations"] = [item for item in payload.get("confirmed_relations", []) if not selected_ids or item.get("evidence_id") in selected_ids]
        return result

    @staticmethod
    def _structure_answer(answer: dict, state: dict, query: StateQuery) -> dict:
        """Expose stable categories so an Agent does not infer meaning from prose."""
        team = state.get("team", {})
        facts = [
            {
                "id": fact.get("id"), "kind": fact.get("kind"),
                "subject_key": fact.get("subject_key"), "value": fact.get("value"),
                "status": fact.get("status"), "evidence_ids": fact.get("evidence_ids", []),
            }
            for fact in team.get("facts", [])
            if fact.get("status") in {"accepted", "conflicted", "proposed"}
        ]
        evidence = {item.get("id"): item for item in state.get("evidence", [])}
        relation_by_evidence = {}
        for relation in state.get("confirmed_relations", []) + state.get("candidate_relations", []):
            relation_by_evidence.setdefault(relation.get("evidence_id"), []).append({
                "fact_id": relation.get("fact_id"), "status": relation.get("status"),
                "basis": relation.get("basis"),
            })
        supporting = []
        for evidence_id in answer.get("evidence_ids", []):
            item = evidence.get(evidence_id, {"id": evidence_id})
            supporting.append({
                "id": evidence_id, "preview": item.get("content_preview"),
                "author": item.get("author"), "observed_at": item.get("observed_at"),
                "relations": relation_by_evidence.get(evidence_id, []),
            })
        gaps = list(answer.get("evidence_gaps", []))
        gaps.extend({"fact_id": request.get("fact_id"), "status": request.get("status"), "note": request.get("note", "")}
                    for request in state.get("evidence_requests", []) if request.get("status") != "ready_for_review")
        return {
            **answer,
            "current_facts": facts,
            "supporting_evidence": supporting,
            "conflicts": answer.get("conflicts", []),
            "evidence_gaps": gaps,
            "chain_of_recall": answer.get("chain_of_recall", []),
            "next": {
                "text": answer.get("next_action", ""),
                "status": answer.get("next_action_status"),
                "basis": answer.get("next_action_basis"),
            },
            "query_scope": list(query.scopes),
            "query_stats": state.get("investigation_stats", {}),
        }

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}

    def _get(self, path: str) -> dict:
        request = Request(self.base_url + path, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            raise PluginRequestError(status, "ProjectCompass plugin request failed") from exc

    def _post(self, path: str, payload: dict) -> dict:
        request = Request(self.base_url + path, data=json.dumps(payload).encode("utf-8"), headers=self._headers(), method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            raise PluginRequestError(status, "ProjectCompass plugin request failed") from exc


class WorkspaceMCPAdapter:
    """Zero-config local adapter backed directly by a bound ProjectWorkspace."""

    METHODS = LocalPluginAdapter.METHODS
    STATE_SCOPES = LocalPluginAdapter.STATE_SCOPES

    def __init__(self, workspace, context: ProjectContext):
        if context.member_id in {"project-documents", "__local_owner__"}:
            raise ValueError("invalid MCP local member_id")
        self.workspace = workspace
        self.context = context
        self._cached_context: dict | None = None
        self._cached_signature: tuple[int, int] | None = None
        self._ephemeral_token = secrets.token_urlsafe(32)
        self._client = None
        self._inbox: AgentInbox | None = None

    def _ensure_inbox(self) -> tuple[AgentInbox, object]:
        if not self.workspace.exists():
            self.workspace.save([])
        events = self.workspace.load()
        if self._inbox is None:
            config = {
                "schema_version": 1,
                "project_path": str(self.workspace.project_path),
                "owner_id": "__local_owner__",
                "clients": [
                    {
                        "client_id": f"mcp-{self.context.agent}",
                        "member_id": self.context.member_id,
                        "session_id": self.context.session_id,
                        "agent": self.context.agent,
                        "token": self._ephemeral_token,
                    }
                ],
            }
            self._inbox = AgentInbox(config, self.workspace, events)
            self._client = self._inbox.clients[0]
        else:
            self._inbox.events[:] = events
        return self._inbox, self._client

    def _load_full_state(self) -> tuple[list, dict, list, list]:
        events = self.workspace.load() if self.workspace.exists() else []
        confirmed, history, fact_reviews = self.workspace.load_review_state() if self.workspace.exists() else ([], [], [])
        state = build_dashboard_state(
            events,
            project_path=str(self.workspace.project_path),
            confirmed_relations=confirmed,
            review_history=history,
            fact_reviews=fact_reviews,
        )
        return events, state, confirmed, fact_reviews

    def dispatch(self, method: str, params: dict) -> dict:
        if method not in self.METHODS:
            raise ValueError(f"unsupported plugin method: {method}")
        if not isinstance(params, dict):
            raise ValueError("plugin params must be an object")
        if method == "project.context":
            cur_sig = self.workspace.state_stat_signature() if self.workspace.exists() else None
            if not params.get("refresh") and self._cached_context is not None and cur_sig == self._cached_signature:
                return self._cached_context
            compact = self.workspace.compact_context(
                member_id=self.context.member_id,
                session_id=self.context.session_id,
                agent=self.context.agent,
            )
            self._cached_context = compact
            self._cached_signature = self.workspace.state_stat_signature() if self.workspace.exists() else None
            return compact
        if method == "evidence.append":
            envelope = params.get("event")
            if not isinstance(envelope, dict):
                raise ValueError("evidence.append requires an event envelope")
            validate_protocol_version(envelope.get("schema_version"))
            project_id = envelope.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("plugin event project mismatch")
            event = envelope.get("event")
            if not isinstance(event, dict):
                raise ValueError("plugin event must be an object")
            inbox, client = self._ensure_inbox()
            result = inbox.append_events(client, {"schema_version": 1, "events": [event]})
            self._cached_context = None
            return result
        if method == "state.query":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("state query project mismatch")
            question = params.get("question") or params.get("evidence_id") or params.get("id") or ""
            query = StateQuery(self.context, question, tuple(params.get("scopes", ("team", "personal", "evidence"))))
            unknown = set(query.scopes) - self.STATE_SCOPES
            if unknown:
                raise ValueError("unsupported state query scope")
            events, state, confirmed, fact_reviews = self._load_full_state()
            answer = investigate(
                events,
                query.question,
                confirmed_relations=confirmed,
                fact_reviews=fact_reviews,
                current_member=self.context.member_id,
            )
            answer_dict = answer.to_dict() if hasattr(answer, "to_dict") else answer
            result = LocalPluginAdapter._project_state(self, state, query)
            result["answer"] = LocalPluginAdapter._structure_answer(answer_dict, state, query)
            result["investigation_stats"] = state.get("investigation_stats", {})
            return result
        if method == "fact.propose":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("fact proposal project mismatch")
            validate_protocol_version(params.get("schema_version"))
            proposals = params.get("proposals", [])
            inbox, client = self._ensure_inbox()
            result = inbox.propose(client, {"schema_version": 1, "proposals": proposals})
            self._cached_context = None
            return result
        if method == "note.record":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("note record project mismatch")
            note_payload = {k: v for k, v in params.items() if k != "project_id"}
            note_payload.setdefault("schema_version", 1)
            inbox, client = self._ensure_inbox()
            result = inbox.record_note(client, note_payload)
            self._cached_context = None
            return result
        if method == "completion.verify":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("completion verify project mismatch")
            events, state, _, _ = self._load_full_state()
            return evaluate_completion_gate(
                state,
                events,
                summary=str(params.get("summary") or ""),
                changed_files=params.get("changed_files"),
                test_evidence_ids=params.get("test_evidence_ids"),
            )
        if method == "workbench.open":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("workbench project mismatch")
            bootstrapped = False
            skip_bootstrap = bool(params.get("_skip_bootstrap"))
            is_sample = os.environ.get("SAMPLE_MODE", "").strip().lower() == "true"
            if not is_sample and not skip_bootstrap:
                events, bootstrapped = cold_start_bootstrap_workspace(self.workspace)
                if bootstrapped:
                    self._cached_context = None
            else:
                events = self.workspace.load() if self.workspace.exists() else []
            confirmed, history, fact_reviews = (
                self.workspace.load_review_state() if self.workspace.exists() else ([], [], [])
            )
            status_note = ""
            if not events and not bootstrapped:
                status_note = "暂无历史记录，可随时在左栏对话记账"
            return _build_workbench_payload(
                events,
                project_path=self.workspace.project_path,
                confirmed=confirmed,
                history=history,
                fact_reviews=fact_reviews,
                context=self.context,
                agent_inbox=None,
                bootstrapped=bootstrapped,
                role_mode="owner",
                can_review=True,
                status_note=status_note,
            )
        if method == "workbench.action":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("workbench project mismatch")
            action = str(params.get("action") or "state").strip()
            if action not in _WORKBENCH_ACTIONS:
                raise ValueError(f"unsupported workbench action: {action}")
            if action == "state":
                return self.dispatch("workbench.open", {**params, "_skip_bootstrap": True})
            if action == "scan_docs":
                if os.environ.get("SAMPLE_MODE", "").strip().lower() == "true":
                    raise ValueError("scan_docs is disabled in sample mode")
                if not self.workspace.exists():
                    self.workspace.save([])
                events = self.workspace.load()
                rescan_info = ProjectRescan(self.workspace, events, extract_docs=True).refresh()
                self._cached_context = None
                confirmed, history, fact_reviews = self.workspace.load_review_state()
                fresh_events = self.workspace.load()
                return _build_workbench_payload(
                    fresh_events,
                    project_path=self.workspace.project_path,
                    confirmed=confirmed,
                    history=history,
                    fact_reviews=fact_reviews,
                    context=self.context,
                    bootstrapped=bool(rescan_info.get("new_doc_proposals") or rescan_info.get("updated")),
                    role_mode="owner",
                    can_review=True,
                    status_note="已完成项目文档扫描",
                )
            if action in {"accept_fact", "reject_fact", "complete_fact"}:
                fact_id = str(params.get("fact_id") or "").strip()
                if not fact_id:
                    raise ValueError("fact_id is required")
                if not self.workspace.exists():
                    raise ValueError("fact not found")
                reviewer = str(params.get("reviewer") or self.context.member_id).strip()
                if not reviewer:
                    raise ValueError("reviewer is required")
                note = str(params.get("note") or "").strip()
                events = self.workspace.load()
                confirmed, history, fact_reviews = self.workspace.load_review_state()
                from .cli import _review_callback

                review_fn, confirmed, history, fact_reviews = _review_callback(
                    events,
                    self.workspace,
                    str(self.workspace.project_path),
                    confirmed,
                    history,
                    fact_reviews,
                )
                review_fn(action, fact_id, reviewer, note)
                self._cached_context = None
                if action == "accept_fact":
                    status_note = "已加入「已确认事项」"
                elif action == "complete_fact":
                    status_note = "已标记为完成"
                elif "撤回" in note:
                    status_note = "已移出当前列表（原始记录仍保留）"
                else:
                    status_note = "已忽略该条目（原始记录仍保留）"
                return _build_workbench_payload(
                    events,
                    project_path=self.workspace.project_path,
                    confirmed=confirmed,
                    history=history,
                    fact_reviews=fact_reviews,
                    context=self.context,
                    bootstrapped=False,
                    role_mode="owner",
                    can_review=True,
                    status_note=status_note,
                )
            if action == "record_note":
                note_payload = {
                    k: v
                    for k, v in params.items()
                    if k in {"text", "kind", "title", "client_nonce", "project_id"}
                }
                self.dispatch("note.record", note_payload)
                payload = self.dispatch("workbench.open", {"project_id": project_id, "_skip_bootstrap": True})
                payload["status_note"] = "已记入待确认想法，并同步更新思维导图"
                return payload
            if action == "dispatch_priority":
                fact_id = str(params.get("fact_id") or "").strip()
                title = str(params.get("title") or "").strip()
                value = str(params.get("value") or "").strip()
                evidence_ids = params.get("evidence_ids") if params.get("evidence_ids") is not None else []
                mode = str(params.get("mode") or "queue").strip() or "queue"
                note = str(params.get("note") or "").strip()
                actor = str(params.get("reviewer") or self.context.member_id).strip()
                record_priority_dispatch(
                    self.workspace,
                    fact_id=fact_id,
                    title=title,
                    value=value,
                    evidence_ids=evidence_ids,
                    actor=actor,
                    mode=mode,
                    note=note,
                )
                self._cached_context = None
                payload = self.dispatch("workbench.open", {"project_id": project_id, "_skip_bootstrap": True})
                payload["status_note"] = "已加入待优先处理列表"
                return payload
        raise AssertionError("unreachable")

    def append_event(self, event) -> dict:
        return self.dispatch("evidence.append", {"event": evidence_event_to_protocol_dict(event, self.context)})

    def query_state(self, query: StateQuery) -> dict:
        return self.dispatch("state.query", query.to_payload())

    def propose_fact(self, proposal: FactProposal) -> dict:
        return self.dispatch("fact.propose", proposal.to_payload())
