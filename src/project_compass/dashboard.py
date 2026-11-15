from __future__ import annotations

from pathlib import Path
from hashlib import sha1
import re

from .evidence_filters import as_utc_timestamp, is_public_raw_event, parse_iso_timestamp, resolve_member_id
from .evidence_linking import build_evidence_index, build_requested_evidence_relations
from .derived_context import DerivedContext
from .fact_engine import derive_facts
from .limits import MAX_DASHBOARD_VISIBLE_EDGES, MAX_DASHBOARD_VISIBLE_NODES
from .models import EvidenceEvent, EvidenceRelation
from .projections import build_views


def _build_timeline_chapters(facts: list[dict], directions: dict) -> list[dict]:
    goals = [f for f in facts if f.get("kind") == "goal"]
    decisions = [f for f in facts if f.get("kind") in {"decision", "assumption"}]
    tasks = [f for f in facts if f.get("kind") == "task"]
    dir_items = list(directions.get("current") or []) + list(directions.get("candidates") or [])
    reviewed = [f for f in facts if f.get("status") in {"accepted", "conflicted"}]

    def _chapter(seq: str, cid: str, title: str, items: list[dict], fallback_sub: str, default_status: str = "pending") -> dict:
        ev_ids: list[str] = []
        fact_ids: list[str] = []
        latest_time = None
        latest_ts = None
        for item in items:
            fid = item.get("id") or item.get("fact_id")
            if fid and fid not in fact_ids:
                fact_ids.append(fid)
            for eid in item.get("evidence_ids") or []:
                if eid not in ev_ids:
                    ev_ids.append(eid)
            obs = item.get("observed_at")
            if obs:
                try:
                    obs_ts = as_utc_timestamp(obs)
                except (TypeError, ValueError):
                    if latest_time is None or str(obs) > str(latest_time):
                        latest_time = obs
                else:
                    if latest_ts is None or obs_ts > latest_ts:
                        latest_ts = obs_ts
                        latest_time = obs
        if not items:
            return {
                "chapter_id": cid,
                "sequence": seq,
                "title": title,
                "subtitle": fallback_sub,
                "count": 0,
                "status": default_status,
                "observed_at": None,
                "fact_ids": [],
                "evidence_ids": [],
            }
        lead = items[-1].get("value") or items[-1].get("quote") or fallback_sub
        if len(lead) > 44:
            lead = lead[:42] + "…"
        has_accepted = any(i.get("status") == "accepted" or i.get("task_state") == "completed" for i in items)
        status = "completed" if has_accepted else "active"
        return {
            "chapter_id": cid,
            "sequence": seq,
            "title": title,
            "subtitle": lead,
            "count": len(items),
            "status": status,
            "observed_at": latest_time,
            "fact_ids": fact_ids,
            "evidence_ids": ev_ids[:6],
        }

    return [
        _chapter("01", "ch-goal", "目标确立", goals, "尚无目标候选 · 可运行 --extract-docs 或接入会话"),
        _chapter("02", "ch-decision", "方案选型与方向", decisions + dir_items, "尚无决策记录 · 待从讨论或文档中提取"),
        _chapter("03", "ch-task", "模块推进与待办", tasks, "尚无任务拆解 · 待从开发会话或文档中提取"),
        _chapter("04", "ch-review", "共识审查与验证", reviewed, "尚无已裁决项 · 填写负责人后可确认或裁决候选"),
    ]


def _build_thinking_line(facts: list[dict], directions: dict, structure: dict) -> dict:
    goals = [f for f in facts if f.get("kind") == "goal"]
    active_goal = next((f for f in goals if f.get("status") == "accepted"), goals[-1] if goals else None)
    root = {
        "fact_id": active_goal.get("id") if active_goal else None,
        "label": active_goal.get("value") if active_goal else "尚未提取核心目标（运行文档提取或接入会话后生成）",
        "status": active_goal.get("status", "proposed") if active_goal else "empty",
        "evidence_ids": list(active_goal.get("evidence_ids") or [])[:4] if active_goal else [],
    }
    branches: list[dict] = []
    seen_quotes: set[str] = set()

    # 1. Pruned / parked direction branches (abandoned / deferred)
    for d in list(directions.get("current") or []) + list(directions.get("candidates") or []):
        d_state = d.get("direction_state") or "deferred"
        if d_state == "active":
            continue
        quote = str(d.get("quote") or d.get("value") or "").strip()
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        branches.append({
            "branch_id": f"dir-{d.get('fact_id') or len(branches)}",
            "fact_id": d.get("fact_id"),
            "kind": "direction",
            "state": d_state,  # abandoned | deferred
            "status": d.get("status", "proposed"),
            "label": quote[:68] + ("…" if len(quote) > 68 else ""),
            "evidence_ids": list(d.get("evidence_ids") or [])[:3],
            "children": [],
        })

    # 2. Active Decision / Assumption branches
    decisions = [f for f in facts if f.get("kind") in {"decision", "assumption"}]
    tasks = [f for f in facts if f.get("kind") == "task"]
    for idx, dec in enumerate(decisions[:4]):
        val = str(dec.get("value") or "").strip()
        if not val or val in seen_quotes:
            continue
        seen_quotes.add(val)
        branches.append({
            "branch_id": f"dec-{dec.get('id') or idx}",
            "fact_id": dec.get("id"),
            "kind": dec.get("kind", "decision"),
            "state": "chosen",
            "status": dec.get("status", "proposed"),
            "source_status": (dec.get("source_state") or {}).get("status", "recorded"),
            "label": val[:68] + ("…" if len(val) > 68 else ""),
            "evidence_ids": list(dec.get("evidence_ids") or [])[:3],
            "children": [],
        })

    # Attach tasks to the primary chosen decision branch (or a default execution branch)
    task_nodes = [
        {
            "fact_id": t.get("id"),
            "label": str(t.get("value") or "")[:56] + ("…" if len(str(t.get("value") or "")) > 56 else ""),
            "task_state": t.get("task_state") or "pending",
            "status": t.get("status", "proposed"),
            "evidence_ids": list(t.get("evidence_ids") or [])[:2],
        }
        for t in tasks[:5]
    ]
    chosen_branches = [b for b in branches if b["state"] == "chosen"]
    if task_nodes:
        if chosen_branches:
            chosen_branches[0]["children"] = task_nodes[:3]
            if len(chosen_branches) > 1 and len(task_nodes) > 3:
                chosen_branches[1]["children"] = task_nodes[3:5]
        else:
            branches.append({
                "branch_id": "exec-main",
                "fact_id": task_nodes[0]["fact_id"],
                "kind": "execution",
                "state": "chosen",
                "status": "proposed",
                "label": "待办执行分支（尚未关联架构决策）",
                "evidence_ids": task_nodes[0]["evidence_ids"],
                "children": task_nodes,
            })

    superseded_facts = [
        {"fact_id": f.get("id"), "label": str(f.get("value") or "")[:48], "status": (f.get("source_state") or {}).get("status")}
        for f in facts
        if (f.get("source_state") or {}).get("status") in {"superseded", "unavailable"}
    ]
    code_nodes = []
    if structure and structure.get("enabled"):
        direct = set(structure.get("direct_node_ids") or [])
        related = set(structure.get("related_node_ids") or [])
        linked_nodes = [
            node for node in (structure.get("nodes") or [])
            if node.get("id") in direct or node.get("id") in related
        ]
        linked_nodes.sort(
            key=lambda n: (
                0 if n.get("id") in direct else 1,
                0 if n.get("kind") in {"file", "class", "function"} else 1,
                0 if str(n.get("source_ref") or "").startswith("src/") else 1,
                str(n.get("source_ref") or ""),
                str(n.get("label") or ""),
            )
        )
        for node in linked_nodes[:4]:
            code_nodes.append({
                "id": node.get("id"),
                "label": node.get("label") or node.get("id"),
                "source_ref": node.get("source_ref"),
                "direct": node.get("id") in direct,
            })

    return {
        "root": root,
        "branches": branches,
        "reversals": superseded_facts,
        "code_nodes": code_nodes,
    }


def _build_session_presence(views: dict, review_queue: list[dict], accepted_subjects: set[str], latest_review_by_fact: dict) -> dict:
    team_facts = views["team"].get("facts") or []
    team_accepted = sum(1 for f in team_facts if f.get("status") == "accepted")
    members = []
    for member_id, m_view in (views.get("personal") or {}).items():
        m_facts = m_view.get("facts") or []
        pending = sum(
            1
            for f in m_facts
            if f.get("status") in {"proposed", "conflicted"}
            and f.get("subject_key") not in accepted_subjects
            and latest_review_by_fact.get(str(f.get("id")), {}).get("action") != "reject_fact"
        )
        accepted = sum(1 for f in m_facts if f.get("status") == "accepted")
        members.append({
            "member_id": member_id,
            "label": "项目文档" if member_id == "project-documents" else member_id,
            "is_agent_session": member_id != "project-documents",
            "fact_count": len(m_facts),
            "pending_count": pending,
            "accepted_count": accepted,
        })
    members.sort(key=lambda item: (0 if item["is_agent_session"] else 1, -item["pending_count"], item["member_id"]))
    return {
        "team": {
            "id": "team",
            "label": "Team Truth",
            "accepted_count": team_accepted,
            "pending_count": len(review_queue),
            "conflict_count": len(views["team"].get("conflicts") or []),
        },
        "members": members,
    }


def _build_handoff_brief(project_name: str, views: dict, review_queue: list[dict], structure: dict) -> dict:
    team_facts = views["team"].get("facts") or []
    goals = [f for f in team_facts if f.get("kind") == "goal"]
    focus_goal = next((f for f in goals if f.get("status") == "accepted"), goals[-1] if goals else None)
    accepted_decisions = [
        {
            "fact_id": f.get("id"),
            "kind": f.get("kind"),
            "value": f.get("value"),
            "author": f.get("author"),
            "evidence_ids": list(f.get("evidence_ids") or [])[:3],
        }
        for f in team_facts
        if f.get("status") == "accepted" and f.get("kind") in {"decision", "assumption", "goal"}
    ]
    pending_candidates = [
        {
            "fact_id": item.get("fact_id"),
            "kind": item.get("kind"),
            "value": item.get("value"),
            "author": item.get("author") or "session",
            "status": item.get("status"),
            "evidence_ids": list(
                next((f.get("evidence_ids") or [] for f in team_facts if f.get("id") == item.get("fact_id")), [])
            )[:3],
        }
        for item in review_queue[:8]
    ]
    todos = [
        {
            "fact_id": f.get("id"),
            "value": f.get("value"),
            "task_state": f.get("task_state") or "pending",
            "status": f.get("status"),
            "author": f.get("author") or "session",
            "evidence_ids": list(f.get("evidence_ids") or [])[:3],
        }
        for f in team_facts
        if f.get("kind") == "task"
    ][:8]
    conflicts = views["team"].get("conflicts") or []
    thinking = views["team"].get("thinking_line") or {}
    code_nodes = thinking.get("code_nodes") or []

    goal_line = (
        f"- **当前核心目标 ({focus_goal.get('status')})**: {focus_goal.get('value')} "
        f"`[{', '.join(focus_goal.get('evidence_ids') or [])}]`"
        if focus_goal
        else "- **当前核心目标**: 暂无目标候选"
    )
    dec_lines = (
        "\n".join(
            f"- **[Team Truth · {d['kind']}]** {d['value']} `[{', '.join(d['evidence_ids'])}]`"
            for d in accepted_decisions[:6]
        )
        or "- 暂无已确认团队决策（请在看板上点击 `✓ 采纳` 晋升候选事实）"
    )
    cand_lines = (
        "\n".join(
            f"- **[Candidate · {c['author']}]** {c['value']} `[{', '.join(c['evidence_ids'])}]`"
            for c in pending_candidates[:6]
        )
        or "- 当前无待审候选"
    )
    todo_lines = (
        "\n".join(
            f"- [{'x' if t['task_state'] == 'completed' else ' '}] {t['value']} ({t['author']}) `[{', '.join(t['evidence_ids'])}]`"
            for t in todos
        )
        or "- 暂无待办任务记录"
    )
    code_lines = (
        "\n".join(f"- `{n['label']}` ({n.get('source_ref') or 'derived_context'})" for n in code_nodes)
        if code_nodes
        else "- 未挂载或无直接关联结构节点"
    )
    md = (
        f"# ✦ {project_name} · 1-Minute Handoff Brief (项目一分钟交接简报)\n\n"
        f"## 1. 核心焦点 (Session Summary & Focus)\n{goal_line}\n\n"
        f"## 2. 已确认团队共识 (Confirmed Team Truth)\n{dec_lines}\n\n"
        f"## 3. 待确认会话候选 (Pending Candidates)\n{cand_lines}\n\n"
        f"## 4. 下一步行动与待办 (Next Steps & Action Items)\n{todo_lines}\n\n"
        f"## 5. 关联代码结构 (Linked Code Modules)\n{code_lines}\n"
    )
    return {
        "project_name": project_name,
        "focus_goal": {
            "fact_id": focus_goal.get("id") if focus_goal else None,
            "value": focus_goal.get("value") if focus_goal else "当前核心目标待确立",
            "status": focus_goal.get("status", "proposed") if focus_goal else "empty",
            "evidence_ids": list(focus_goal.get("evidence_ids") or [])[:3] if focus_goal else [],
        },
        "accepted_decisions": accepted_decisions,
        "pending_candidates": pending_candidates,
        "open_todos": todos,
        "conflict_count": len(conflicts),
        "code_nodes": code_nodes,
        "markdown": md,
    }




def build_dashboard_state(
    events: list[EvidenceEvent],
    project_path: str | None = None,
    confirmed_relations: list[EvidenceRelation] | tuple[EvidenceRelation, ...] = (),
    review_history: list[dict] | tuple[dict, ...] = (),
    fact_reviews: list[dict] | tuple[dict, ...] = (),
    *, session_members=None, derived_context: DerivedContext | None = None,
) -> dict:
    """Build the read-only state consumed by the personal/team dashboard."""
    facts = derive_facts(events)
    accepted_by_subject: dict[str, str] = {}
    for item in fact_reviews:
        if item.get("action") == "accept_fact" and item.get("fact_id"):
            accepted_by_subject[str(item.get("subject_key", item["fact_id"]))] = item["fact_id"]
    accepted_fact_ids = list(accepted_by_subject.values())
    views = build_views(events, accepted_fact_ids=accepted_fact_ids, session_members=session_members, fact_reviews=fact_reviews)
    index = build_evidence_index(events, facts).with_candidate_relations(build_requested_evidence_relations(events, facts, review_history)).with_confirmed_relations(confirmed_relations)
    team_facts = views["team"]["facts"]
    accepted_subjects = {fact["subject_key"] for fact in team_facts if fact["status"] == "accepted"}
    latest_review_by_fact: dict[str, dict] = {}
    for review in review_history:
        if review.get("fact_id") and review.get("action") != "confirm_relation":
            latest_review_by_fact[str(review["fact_id"])] = review
    active_evidence_requests = {}
    for review in review_history:
        fact_id = review.get("fact_id")
        if not fact_id:
            continue
        fact_id = str(fact_id)
        if review.get("action") == "request_evidence":
            active_evidence_requests[fact_id] = review
        elif review.get("action") in {"accept_fact", "reject_fact"}:
            active_evidence_requests.pop(fact_id, None)
    facts_by_id = {fact.id: fact for fact in facts}
    evidence_requests = []
    for fact_id, review in active_evidence_requests.items():
        if fact_id not in facts_by_id:
            continue
        fact = facts_by_id[fact_id]
        requested_at = review.get("observed_at")
        try:
            requested_time = as_utc_timestamp(requested_at) if requested_at else None
        except (TypeError, ValueError):
            requested_time = None
        requested_ids = set(review.get("evidence_ids") or fact.evidence_ids)
        new_ids = [
            event.id
            for event in events
            if event.id not in requested_ids and requested_time and as_utc_timestamp(event.observed_at) > requested_time
        ]
        evidence_requests.append({
            "request_id": f"evidence-request-{fact_id}",
            "fact_id": fact_id,
            "subject_key": fact.subject_key,
            "value": review.get("value", fact.value),
            "member_id": fact.author,
            "reviewer": review.get("reviewer"),
            "note": review.get("note", ""),
            "requested_at": requested_at,
            "requested_evidence_ids": sorted(requested_ids),
            "new_evidence_ids": new_ids,
            "status": "ready_for_review" if new_ids else "waiting_for_evidence",
        })
    for request in evidence_requests:
        views["personal"].setdefault(request["member_id"], {"member_id": request["member_id"], "facts": [], "evidence_ids": [], "directions": []}).setdefault("evidence_requests", []).append(request)
    candidate_by_fact: dict[str, int] = {}
    for relation in index.candidate_relations:
        candidate_by_fact[relation.fact_id] = candidate_by_fact.get(relation.fact_id, 0) + 1
    review_queue = [
        {
            "fact_id": fact["id"], "kind": fact["kind"], "value": fact["value"],
            "status": "needs_evidence" if latest_review_by_fact.get(fact["id"], {}).get("action") == "request_evidence" else fact["status"], "author": fact.get("author"),
            "evidence_count": len(fact.get("evidence_ids") or []),
            "candidate_relation_count": candidate_by_fact.get(fact["id"], 0),
            "reason": "负责人要求补充证据" if latest_review_by_fact.get(fact["id"], {}).get("action") == "request_evidence" else ("冲突双方待负责人裁决" if fact["status"] == "conflicted" else "候选事实待负责人确认"),
        }
        for fact in team_facts
        if fact["status"] in {"proposed", "conflicted"}
        and fact["subject_key"] not in accepted_subjects
        and latest_review_by_fact.get(fact["id"], {}).get("action") != "reject_fact"
    ]
    review_queue.sort(key=lambda item: (0 if item["status"] == "conflicted" else 1, item["kind"], item["fact_id"]))
    activity = {}
    for event in events:
        if not is_public_raw_event(event):
            continue
        owner = resolve_member_id(event, session_members=session_members, route_documents=True)
        item = activity.setdefault(owner, {"member_id": owner, "event_count": 0, "last_event_at": None, "last_event_kind": None, "last_event_preview": "", "last_event_id": None})
        item["event_count"] += 1
        if item["last_event_at"] is None or as_utc_timestamp(event.observed_at) >= as_utc_timestamp(item["last_event_at"]):
            item.update(last_event_at=event.observed_at.isoformat(), last_event_kind=event.kind, last_event_preview=event.content[:160], last_event_id=event.id)
    structure = {"enabled": False}
    if derived_context is not None:
        source_path = Path(project_path).resolve() / derived_context.source_ref if project_path else None
        nodes = list(derived_context.nodes)
        edges = list(derived_context.edges)
        evidence_refs: set[str] = set()
        py_tokens: set[str] = set()
        symbol_tokens: set[str] = set()
        for event in events:
            raw_ref = event.metadata.get("source_ref") if isinstance(event.metadata, dict) else None
            if isinstance(raw_ref, str) and raw_ref.strip():
                evidence_refs.add(raw_ref.strip().replace("\\", "/"))
            if is_public_raw_event(event) and event.kind != "file_snapshot" and isinstance(event.content, str):
                for py_hit in re.findall(r"[A-Za-z0-9_./\\-]+\.py\b", event.content):
                    py_tokens.add(py_hit.replace("\\", "/").lstrip("./"))
                for sym_hit in re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", event.content):
                    symbol_tokens.add(sym_hit.rsplit(".", 1)[-1])
        for fact in facts:
            if isinstance(fact.source_ref, str) and fact.source_ref.strip():
                evidence_refs.add(fact.source_ref.strip().replace("\\", "/"))
            for text in (fact.value, fact.quote, fact.subject_key):
                if not isinstance(text, str) or not text:
                    continue
                for py_hit in re.findall(r"[A-Za-z0-9_./\\-]+\.py\b", text):
                    py_tokens.add(py_hit.replace("\\", "/").lstrip("./"))
                for sym_hit in re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", text):
                    symbol_tokens.add(sym_hit.rsplit(".", 1)[-1])
                for mod_hit in re.findall(r"\b([a-z][a-z0-9_]{2,}_(?:provider|memory|server|relevance|intake|index|export|watcher|store|workspace))\b", text):
                    symbol_tokens.add(mod_hit)
        direct_symbol_ids: set[str] = set()
        for node in nodes:
            norm_src = node.source_ref.replace("\\", "/")
            if any(norm_src == tok or norm_src.endswith("/" + tok) for tok in py_tokens):
                evidence_refs.add(norm_src)
            elif Path(norm_src).stem in symbol_tokens:
                evidence_refs.add(norm_src)
                if node.kind == "file":
                    direct_symbol_ids.add(node.id)
            if node.label in symbol_tokens:
                direct_symbol_ids.add(node.id)
                evidence_refs.add(norm_src)
        related_nodes, related_edges = derived_context.related_projection(evidence_refs)
        direct_id_set = {node.id for node in nodes if node.source_ref in evidence_refs} | direct_symbol_ids
        related_id_set = {node.id for node in related_nodes} | direct_id_set
        related_edge_id_set = {edge.id for edge in related_edges}

        def _node_rank(node):
            rel_rank = 0 if node.id in direct_id_set else (1 if node.id in related_id_set else 2)
            src = node.source_ref.replace("\\", "/")
            path_rank = 0 if src.startswith("src/") else (1 if not src.startswith(("tests/", "scripts/", "logs/", "docs/")) else 2)
            kind_rank = 0 if node.kind in {"file", "class", "function"} else 1
            return (rel_rank, path_rank, kind_rank, src, node.id)

        sorted_nodes = sorted(nodes, key=_node_rank)
        visible_nodes = sorted_nodes[:MAX_DASHBOARD_VISIBLE_NODES]
        visible_node_ids = {node.id for node in visible_nodes}
        in_view_edges = [edge for edge in edges if edge.from_id in visible_node_ids and edge.to_id in visible_node_ids]
        sorted_edges = sorted(
            in_view_edges,
            key=lambda edge: (0 if edge.id in related_edge_id_set else 1, edge.from_id, edge.to_id, edge.kind, edge.id),
        )
        visible_edges = sorted_edges[:MAX_DASHBOARD_VISIBLE_EDGES]
        visible_edge_ids = {edge.id for edge in visible_edges}
        structure = {
            "enabled": True,
            "origin": "derived_context",
            "project_id": derived_context.project_id,
            "source_ref": derived_context.source_ref,
            "source_fingerprint": derived_context.source_fingerprint,
            "observed_at": derived_context.observed_at.isoformat(),
            "current": derived_context.source_current(source_path) if source_path else None,
            "truncated": len(nodes) > MAX_DASHBOARD_VISIBLE_NODES or len(edges) > MAX_DASHBOARD_VISIBLE_EDGES,
            "nodes": [node.to_dict() for node in visible_nodes],
            "edges": [edge.to_dict() for edge in visible_edges],
            "direct_node_ids": [node.id for node in visible_nodes if node.id in direct_id_set],
            "related_node_ids": [node.id for node in visible_nodes if node.id in related_id_set],
            "related_edge_ids": [edge.id for edge in visible_edges if edge.id in related_edge_id_set],
            "evidence_source_refs": sorted(evidence_refs & {node.source_ref for node in nodes}),
        }
    views["team"]["timeline_chapters"] = _build_timeline_chapters(views["team"].get("facts") or [], views["team"].get("directions") or {})
    views["team"]["thinking_line"] = _build_thinking_line(views["team"].get("facts") or [], views["team"].get("directions") or {}, structure)
    for member_view in views["personal"].values():
        m_facts = member_view.get("facts") or []
        m_dirs = member_view.get("directions") or {}
        member_view["timeline_chapters"] = _build_timeline_chapters(m_facts, m_dirs)
        member_view["thinking_line"] = _build_thinking_line(m_facts, m_dirs, structure)
    project_name = Path(project_path).name if project_path else "Project Compass"
    session_presence = _build_session_presence(views, review_queue, accepted_subjects, latest_review_by_fact)
    handoff_brief = _build_handoff_brief(project_name, views, review_queue, structure)
    return {
        "project": {
            "name": project_name,
            "path": project_path,
            "project_id": sha1(str(Path(project_path).resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:16] if project_path else None,
            "evidence_count": views["evidence_count"],
            "fact_count": len(facts),
        },
        "personal": views["personal"],
        "team": views["team"],
        "session_presence": session_presence,
        "handoff_brief": handoff_brief,
        "review_history": list(review_history),
        "fact_reviews": list(fact_reviews),
        "personal_activity": sorted(activity.values(), key=lambda item: item["member_id"]),
        "team_review_queue": review_queue,
        "evidence_requests": evidence_requests,
        "derived_context": structure,
        **index.to_dict(),
    }
