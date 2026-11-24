from __future__ import annotations

from pathlib import Path
from hashlib import sha1
import re

from .activity_stream import build_session_activity_stream
from .agent_hints import build_local_agent_hints
from .decision_graph import (
    attach_decision_context,
    is_legacy_noise_fact,
    normalize_same_author_supersession,
)
from .evidence_filters import (
    SENSITIVE,
    as_utc_timestamp,
    is_platform_control,
    is_public_raw_event,
    parse_iso_timestamp,
    resolve_member_id,
)
from .evidence_linking import build_evidence_index, build_requested_evidence_relations
from .derived_context import DerivedContext
from .fact_engine import derive_facts
from .limits import MAX_DASHBOARD_VISIBLE_EDGES, MAX_DASHBOARD_VISIBLE_NODES
from .llm_connector import public_llm_status
from .models import EvidenceEvent, EvidenceRelation
from .projections import build_views
from .text_summary import (
    clean_display_text,
    is_historical_doc_fact,
    select_next_consensus,
    select_primary_goal,
    summarize_node_title,
)


def _enrich_fact_titles(facts_list: list[dict], events_by_id: dict[str, EvidenceEvent]) -> None:
    """Attach non-mutating display summaries (`short_title`, `clean_value`, `is_historical_doc`) to projected facts."""
    for fact in facts_list:
        explicit_title = None
        source_kind = fact.get("source_kind")
        for eid in fact.get("evidence_ids") or []:
            src_ev = events_by_id.get(eid)
            if src_ev is not None:
                if not source_kind:
                    source_kind = src_ev.kind
                if isinstance(src_ev.metadata, dict) and src_ev.metadata.get("short_title"):
                    explicit_title = str(src_ev.metadata.get("short_title"))
                    break
        if source_kind and not fact.get("source_kind"):
            fact["source_kind"] = source_kind
        max_len = 28 if fact.get("kind") == "goal" else 22
        raw_val = fact.get("value") or fact.get("quote") or ""
        fact["clean_value"] = clean_display_text(raw_val)
        fact["short_title"] = summarize_node_title(raw_val, explicit_title, max_chars=max_len)
        fact["is_historical_doc"] = is_historical_doc_fact(fact)


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
        lead = items[-1].get("short_title") or summarize_node_title(
            items[-1].get("value") or items[-1].get("quote") or fallback_sub,
            max_chars=26,
        )
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
        _chapter("04", "ch-review", "确认审查与验证", reviewed, "尚无已确认项 · 填写负责人后可确认或选择分支"),
    ]


def _build_thinking_line(
    facts: list[dict],
    directions: dict,
    structure: dict,
    *,
    fallback_goal: dict | None = None,
) -> dict:
    active_goal = select_primary_goal(facts) or fallback_goal

    if active_goal:
        root_full = str(active_goal.get("value") or "").strip()
        root_short = active_goal.get("short_title") or summarize_node_title(root_full, max_chars=28)
        root = {
            "fact_id": active_goal.get("id"),
            "label": root_short,
            "full_label": root_full,
            "status": active_goal.get("status", "proposed"),
            "evidence_ids": list(active_goal.get("evidence_ids") or [])[:4],
            "inherited": (not any(f.get("kind") == "goal" for f in facts)) and fallback_goal is not None,
        }
    else:
        root = {
            "fact_id": None,
            "label": "核心目标待确定",
            "full_label": "写一条随手记或让 AI 记录核心目标，右侧分支会自动生长",
            "status": "empty",
            "evidence_ids": [],
            "inherited": False,
        }

    branches: list[dict] = []
    historical_items: list[dict] = []
    seen_quotes: set[str] = set()
    accepted_fact_ids = {f.get("id") for f in facts if f.get("status") == "accepted"}

    # 1. Pruned / parked direction branches (abandoned / deferred)
    for d in list(directions.get("current") or []) + list(directions.get("candidates") or []):
        d_state = d.get("direction_state") or "deferred"
        if d_state == "active":
            continue
        quote = str(d.get("quote") or d.get("value") or "").strip()
        if not quote or quote in seen_quotes:
            continue
        seen_quotes.add(quote)
        dir_fact_stub = {
            "id": d.get("fact_id"),
            "kind": "direction",
            "status": d.get("status", "proposed") if d.get("fact_id") not in accepted_fact_ids else "accepted",
            "author": d.get("author"),
            "source_ref": d.get("source_ref"),
            "evidence_ids": list(d.get("evidence_ids") or [])[:3],
        }
        short_dir = summarize_node_title(quote, max_chars=22)
        if is_historical_doc_fact(dir_fact_stub):
            historical_items.append({
                "fact_id": d.get("fact_id"),
                "kind": "direction",
                "state": d_state,
                "status": dir_fact_stub["status"],
                "label": short_dir,
                "full_label": quote,
                "source_ref": d.get("source_ref") or "",
                "evidence_ids": list(d.get("evidence_ids") or [])[:2],
            })
            continue
        branches.append({
            "branch_id": f"dir-{d.get('fact_id') or len(branches)}",
            "fact_id": d.get("fact_id"),
            "kind": "direction",
            "state": d_state,  # abandoned | deferred
            "status": d.get("status", "proposed"),
            "label": short_dir,
            "full_label": quote,
            "evidence_ids": list(d.get("evidence_ids") or [])[:3],
            "children": [],
        })

    # 2. Separate live/accepted decisions from unconfirmed static document scan facts
    decisions = [f for f in facts if f.get("kind") in {"decision", "assumption"}]
    active_decisions: list[dict] = []
    for dec in decisions:
        if dec.get("is_historical_doc") or is_historical_doc_fact(dec):
            val = str(dec.get("value") or "").strip()
            if val and val not in seen_quotes:
                seen_quotes.add(val)
                historical_items.append({
                    "fact_id": dec.get("id"),
                    "kind": dec.get("kind", "decision"),
                    "status": dec.get("status", "proposed"),
                    "label": dec.get("short_title") or summarize_node_title(val, max_chars=22),
                    "full_label": val,
                    "source_ref": dec.get("source_ref") or "",
                    "evidence_ids": list(dec.get("evidence_ids") or [])[:2],
                })
        else:
            active_decisions.append(dec)

    def _safe_obs_ts(raw_obs: object) -> float:
        if not raw_obs:
            return 0.0
        try:
            return as_utc_timestamp(raw_obs).timestamp()
        except (TypeError, ValueError):
            return 0.0

    active_decisions.sort(
        key=lambda dec: (
            1 if dec.get("superseded_by_fact_id") else 0,
            0 if dec.get("status") == "accepted" else (1 if dec.get("status") == "conflicted" else 2),
            -_safe_obs_ts(dec.get("observed_at")),
            str(dec.get("id") or ""),
        )
    )

    for idx, dec in enumerate(active_decisions[:8]):
        val = str(dec.get("value") or "").strip()
        if not val or val in seen_quotes:
            continue
        seen_quotes.add(val)
        dc = dec.get("decision_context") or {}
        c_stage = str(dc.get("stage") or "")
        premise_state = str(
            dc.get("premise_status")
            or ((dc.get("premises") or [{}])[0].get("status") if dc.get("premises") else "")
            or ""
        )
        branch_state = "abandoned" if c_stage == "rejected_path" else "chosen"
        short_label = dec.get("short_title") or summarize_node_title(val, max_chars=22)
        branches.append({
            "branch_id": f"dec-{dec.get('id') or idx}",
            "fact_id": dec.get("id"),
            "kind": dec.get("kind", "decision"),
            "state": branch_state,
            "causal_stage": c_stage,
            "fork_count": len(dc.get("alternatives") or []),
            "premise_state": premise_state,
            "rejection_reason": str(dc.get("rejection_reason") or ""),
            "status": dec.get("status", "proposed"),
            "source_status": (dec.get("source_state") or {}).get("status", "recorded"),
            "label": short_label,
            "full_label": val,
            "evidence_ids": list(dec.get("evidence_ids") or [])[:3],
            "_subject_prefix": str(dec.get("subject_key") or "").split(".", 1)[0],
            "children": [],
        })

    # Order active chosen branches ahead of abandoned/deferred ones so live consensus stands out first.
    branches.sort(
        key=lambda b: (
            0 if (b["state"] == "chosen" and b["status"] == "accepted") else (1 if b["state"] == "chosen" else 2),
        )
    )

    # 3. Tasks: keep active/accepted tasks as leaves, fold unconfirmed static-doc tasks into historical archive
    raw_tasks = [f for f in facts if f.get("kind") == "task"]
    tasks: list[dict] = []
    for t in raw_tasks:
        if t.get("is_historical_doc") or is_historical_doc_fact(t):
            val = str(t.get("value") or "").strip()
            if val:
                historical_items.append({
                    "fact_id": t.get("id"),
                    "kind": "task",
                    "status": t.get("status", "proposed"),
                    "label": t.get("short_title") or summarize_node_title(val, max_chars=20),
                    "full_label": val,
                    "source_ref": t.get("source_ref") or "",
                    "evidence_ids": list(t.get("evidence_ids") or [])[:2],
                })
        else:
            tasks.append(t)

    def _make_task_leaf(task_fact: dict) -> dict:
        full_val = str(task_fact.get("value") or "").strip()
        short_val = task_fact.get("short_title") or summarize_node_title(full_val, max_chars=20)
        return {
            "fact_id": task_fact.get("id"),
            "label": short_val,
            "full_label": full_val,
            "task_state": task_fact.get("task_state") or "pending",
            "status": task_fact.get("status", "proposed"),
            "evidence_ids": list(task_fact.get("evidence_ids") or [])[:2],
        }

    chosen_branches = [b for b in branches if b["state"] == "chosen"]
    unmatched_tasks: list[dict] = []
    for task_fact in tasks[:10]:
        task_ev = set(task_fact.get("evidence_ids") or [])
        task_prefix = str(task_fact.get("subject_key") or "").split(".", 1)[0]
        target_branch = None
        for b in chosen_branches:
            if len(b["children"]) >= 4:
                continue
            if task_ev & set(b.get("evidence_ids") or []):
                target_branch = b
                break
        if target_branch is None and task_prefix:
            for b in chosen_branches:
                if len(b["children"]) < 4 and b.get("_subject_prefix") == task_prefix:
                    target_branch = b
                    break
        if target_branch is None and len(chosen_branches) == 1 and len(chosen_branches[0]["children"]) < 4:
            target_branch = chosen_branches[0]
        if target_branch is not None:
            target_branch["children"].append(_make_task_leaf(task_fact))
        else:
            unmatched_tasks.append(_make_task_leaf(task_fact))

    for b in chosen_branches:
        b.pop("_subject_prefix", None)

    if unmatched_tasks:
        first_unmatched = unmatched_tasks[0]
        branches.append({
            "branch_id": "exec-main",
            "fact_id": first_unmatched["fact_id"],
            "kind": "execution",
            "state": "chosen",
            "status": first_unmatched.get("status", "proposed"),
            "label": "待办事项" if chosen_branches else "待办执行清单",
            "full_label": "尚未归入具体决策分支的待办事项",
            "evidence_ids": first_unmatched["evidence_ids"],
            "children": unmatched_tasks[:6],
        })

    superseded_facts = [
        {"fact_id": f.get("id"), "label": f.get("short_title") or summarize_node_title(f.get("value") or "", max_chars=22), "status": (f.get("source_state") or {}).get("status")}
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

    historical_archive = {
        "count": len(historical_items),
        "label": f"历史文档参考（{len(historical_items)} 条）" if historical_items else "",
        "items": historical_items[:24],
    }

    return {
        "root": root,
        "branches": branches,
        "historical_archive": historical_archive,
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


def _build_handoff_brief(
    project_name: str,
    views: dict,
    review_queue: list[dict],
    structure: dict,
    *,
    rejected_fact_ids: set[str] | frozenset[str] = frozenset(),
) -> dict:
    team_facts = views["team"].get("facts") or []
    active_team_facts = [
        f for f in team_facts if f.get("id") not in rejected_fact_ids and f.get("status") != "rejected"
    ]
    focus_goal = select_primary_goal(active_team_facts)
    next_consensus = select_next_consensus(
        [f for f in active_team_facts if not is_legacy_noise_fact(f)]
    )
    accepted_decisions = [
        {
            "fact_id": f.get("id"),
            "kind": f.get("kind"),
            "value": f.get("value"),
            "clean_value": f.get("clean_value") or clean_display_text(f.get("value") or ""),
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
    all_task_facts = [f for f in active_team_facts if f.get("kind") == "task"]
    live_task_facts = [f for f in all_task_facts if not is_historical_doc_fact(f)]
    chosen_task_facts = live_task_facts or all_task_facts
    todos = [
        {
            "fact_id": f.get("id"),
            "value": f.get("clean_value") or clean_display_text(f.get("value") or ""),
            "task_state": f.get("task_state") or "pending",
            "status": f.get("status"),
            "author": f.get("author") or "session",
            "evidence_ids": list(f.get("evidence_ids") or [])[:3],
        }
        for f in chosen_task_facts
    ][:8]
    conflicts = views["team"].get("conflicts") or []
    thinking = views["team"].get("thinking_line") or {}
    code_nodes = thinking.get("code_nodes") or []

    goal_line = (
        f"- **当前核心目标 ({focus_goal.get('status')})**: {clean_display_text(focus_goal.get('value') or '')} "
        f"`[{', '.join(focus_goal.get('evidence_ids') or [])}]`"
        if focus_goal
        else "- **当前核心目标**: 暂无目标候选"
    )
    next_line = (
        f"- **下一步工作共识 ({next_consensus.get('status')})**: {next_consensus.get('clean_value') or clean_display_text(next_consensus.get('value') or '')} "
        f"`[{', '.join(next_consensus.get('evidence_ids') or [])}]`"
        if next_consensus
        else "- **下一步工作共识**: 暂未设定"
    )
    dec_lines = (
        "\n".join(
            f"- **[Team Truth · {d['kind']}]** {d['clean_value']} `[{', '.join(d['evidence_ids'])}]`"
            for d in accepted_decisions[:6]
        )
        or "- 暂无已确认团队决定（请在看板上点击 `✓ 确认` 加入已确认事项）"
    )
    cand_lines = (
        "\n".join(
            f"- **[Candidate · {c['author']}]** {clean_display_text(c['value'])} `[{', '.join(c['evidence_ids'])}]`"
            for c in pending_candidates[:6]
        )
        or "- 当前无待确认想法"
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
        f"## 1. 核心焦点 (Session Summary & Focus)\n{goal_line}\n{next_line}\n\n"
        f"## 2. 已确认事项 (Confirmed Truth)\n{dec_lines}\n\n"
        f"## 3. 待确认想法 (Pending Candidates)\n{cand_lines}\n\n"
        f"## 4. 下一步行动与待办 (Next Steps & Action Items)\n{todo_lines}\n\n"
        f"## 5. 关联代码结构 (Linked Code Modules)\n{code_lines}\n"
    )
    next_consensus_summary = None
    if next_consensus is not None:
        next_val = str(next_consensus.get("value") or "").strip()
        next_consensus_summary = {
            "id": next_consensus.get("id"),
            "fact_id": next_consensus.get("id"),
            "kind": next_consensus.get("kind"),
            "value": next_val,
            "clean_value": next_consensus.get("clean_value") or clean_display_text(next_val),
            "short_title": next_consensus.get("short_title") or summarize_node_title(next_val, max_chars=24),
            "status": next_consensus.get("status", "proposed"),
            "author": next_consensus.get("author"),
            "observed_at": next_consensus.get("observed_at"),
            "is_candidate_suggestion": bool(next_consensus.get("is_candidate_suggestion")),
            "evidence_ids": list(next_consensus.get("evidence_ids") or [])[:3],
        }
    return {
        "project_name": project_name,
        "focus_goal": {
            "fact_id": focus_goal.get("id") if focus_goal else None,
            "value": focus_goal.get("value") if focus_goal else "当前核心目标待确立",
            "clean_value": clean_display_text(focus_goal.get("value") or "") if focus_goal else "当前核心目标待确立",
            "short_title": (focus_goal.get("short_title") or summarize_node_title(focus_goal.get("value") or "", max_chars=28)) if focus_goal else "核心目标待确定",
            "status": focus_goal.get("status", "proposed") if focus_goal else "empty",
            "evidence_ids": list(focus_goal.get("evidence_ids") or [])[:3] if focus_goal else [],
        },
        "next_consensus": next_consensus_summary,
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
    latest_review_by_fact: dict[str, dict] = {}
    for review in [*fact_reviews, *review_history]:
        if review.get("fact_id") and review.get("action") != "confirm_relation":
            latest_review_by_fact[str(review["fact_id"])] = review
    rejected_fact_ids = {
        fid for fid, rev in latest_review_by_fact.items() if rev.get("action") == "reject_fact"
    }
    accepted_by_subject: dict[str, str] = {}
    for item in fact_reviews:
        fid = item.get("fact_id")
        if item.get("action") == "accept_fact" and fid and str(fid) not in rejected_fact_ids:
            accepted_by_subject[str(item.get("subject_key", fid))] = str(fid)
    accepted_fact_ids = list(accepted_by_subject.values())
    views = build_views(events, accepted_fact_ids=accepted_fact_ids, session_members=session_members, fact_reviews=fact_reviews)
    events_by_id = {ev.id: ev for ev in events}
    _enrich_fact_titles(views["team"].get("facts") or [], events_by_id)
    for member_view in (views.get("personal") or {}).values():
        _enrich_fact_titles(member_view.get("facts") or [], events_by_id)
    normalize_same_author_supersession(views, review_history)
    index = build_evidence_index(events, facts).with_candidate_relations(build_requested_evidence_relations(events, facts, review_history)).with_confirmed_relations(confirmed_relations)
    team_facts = views["team"]["facts"]
    accepted_subjects = {fact["subject_key"] for fact in team_facts if fact["status"] == "accepted"}
    completed_fact_ids = {
        str(review["fact_id"])
        for review in [*fact_reviews, *review_history]
        if review.get("fact_id") and review.get("action") == "complete_fact"
    }
    if completed_fact_ids:
        for f in team_facts:
            if f.get("id") in completed_fact_ids:
                f["completed"] = True
                f["task_state"] = "completed"
        for member_view in (views.get("personal") or {}).values():
            for f in (member_view.get("facts") or []):
                if f.get("id") in completed_fact_ids:
                    f["completed"] = True
                    f["task_state"] = "completed"
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
            "reason": "负责人要求补充证据" if latest_review_by_fact.get(fact["id"], {}).get("action") == "request_evidence" else ("存在分歧的两种说法待负责人确认" if fact["status"] == "conflicted" else "待确认想法待负责人确认"),
        }
        for fact in team_facts
        if fact["status"] in {"proposed", "conflicted"}
        and fact["subject_key"] not in accepted_subjects
        and fact["id"] not in completed_fact_ids
        and latest_review_by_fact.get(fact["id"], {}).get("action") != "reject_fact"
        and not is_legacy_noise_fact(fact)
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
        py_basenames = {tok.rsplit("/", 1)[-1] for tok in py_tokens}
        direct_symbol_ids: set[str] = set()
        for node in nodes:
            norm_src = node.source_ref.replace("\\", "/")
            norm_tail = norm_src.rsplit("/", 1)[-1]
            if norm_src in py_tokens or (norm_tail in py_basenames and any(norm_src.endswith("/" + tok) for tok in py_tokens)):
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
    decision_summary = attach_decision_context(
        views["team"].get("facts") or [],
        views.get("personal") or {},
        events,
        derived_context_dict=structure,
    )
    active_team_facts = [
        f
        for f in (views["team"].get("facts") or [])
        if f.get("id") not in rejected_fact_ids and f.get("status") != "rejected"
    ]
    team_fallback_goal = select_primary_goal(active_team_facts)
    views["team"]["timeline_chapters"] = _build_timeline_chapters(views["team"].get("facts") or [], views["team"].get("directions") or {})
    views["team"]["thinking_line"] = _build_thinking_line(active_team_facts, views["team"].get("directions") or {}, structure)
    for member_view in views["personal"].values():
        m_facts = member_view.get("facts") or []
        active_m_facts = [f for f in m_facts if f.get("id") not in rejected_fact_ids and f.get("status") != "rejected"]
        m_dirs = member_view.get("directions") or {}
        member_view["timeline_chapters"] = _build_timeline_chapters(m_facts, m_dirs)
        member_view["thinking_line"] = _build_thinking_line(active_m_facts, m_dirs, structure, fallback_goal=team_fallback_goal)
        if not any(f.get("kind") == "goal" for f in active_m_facts) and team_fallback_goal is not None:
            member_view["fallback_goal"] = dict(team_fallback_goal)
    project_name = Path(project_path).name if project_path else "Project Compass"
    session_presence = _build_session_presence(views, review_queue, accepted_subjects, latest_review_by_fact)
    handoff_brief = _build_handoff_brief(
        project_name,
        views,
        review_queue,
        structure,
        rejected_fact_ids=rejected_fact_ids,
    )
    index_payload = index.to_dict()
    evidence_catalog = index_payload.get("evidence") or []
    dense_catalog = len(evidence_catalog) > 400
    recent_tool_cutoff = max(0, len(evidence_catalog) - 120)
    excerpt_limit = 500 if dense_catalog else 2000
    tool_kinds = {"tool_call", "tool_result"}
    for idx, catalog_item in enumerate(evidence_catalog):
        src_ev = events_by_id.get(catalog_item.get("id"))
        if src_ev is None or not is_public_raw_event(src_ev):
            continue
        if dense_catalog and src_ev.kind in tool_kinds and idx < recent_tool_cutoff:
            continue
        if not is_platform_control(src_ev.content, kind=src_ev.kind) and SENSITIVE.search(src_ev.content) is None:
            catalog_item["search_excerpt"] = src_ev.content[:excerpt_limit]
    state = {
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
        "next_consensus": handoff_brief.get("next_consensus"),
        "review_history": list(review_history),
        "fact_reviews": list(fact_reviews),
        "personal_activity": sorted(activity.values(), key=lambda item: item["member_id"]),
        "activity_stream": build_session_activity_stream(events, session_members=session_members),
        "team_review_queue": review_queue,
        "evidence_requests": evidence_requests,
        "derived_context": structure,
        "decision_summary": decision_summary,
        "llm_status": public_llm_status(),
        **index_payload,
    }
    state["agent_hints"] = build_local_agent_hints(state)
    return state


def build_mindmap_tree(state: dict, *, max_nodes: int = 12) -> dict:
    """Project a compact orthogonal mindmap node list from dashboard state for MCP App & companions."""
    team = state.get("team") or {}
    team_facts = list(team.get("facts") or [])
    thinking_line = team.get("thinking_line") or {}

    latest_review: dict[str, dict] = {}
    for item in state.get("review_history") or []:
        fid = item.get("fact_id")
        if fid and item.get("action") != "confirm_relation":
            latest_review[str(fid)] = item
    rejected_ids = {fid for fid, rev in latest_review.items() if rev.get("action") == "reject_fact"}
    fact_by_id = {str(f.get("id")): f for f in team_facts if f.get("id")}

    def _to_node(fact: dict) -> dict:
        raw_val = str(fact.get("value") or fact.get("quote") or "").strip()
        kind = str(fact.get("kind") or "decision")
        return {
            "id": str(fact.get("id") or ""),
            "kind": kind,
            "title": fact.get("short_title") or summarize_node_title(raw_val, max_chars=28 if kind == "goal" else 22),
            "value": str(fact.get("clean_value") or clean_display_text(raw_val) or raw_val),
            "status": str(fact.get("status") or "proposed"),
            "evidence_ids": list(fact.get("evidence_ids") or [])[:4],
            "member_id": str(fact.get("author") or ""),
            "session_id": str(fact.get("session_id") or ""),
            **({"task_state": fact.get("task_state")} if fact.get("task_state") else {}),
        }

    nodes: list[dict] = []
    seen_ids: set[str] = set()

    def _append_fact(fact: dict | None) -> None:
        if not fact or len(nodes) >= max_nodes:
            return
        fid = str(fact.get("id") or "")
        if not fid or fid in seen_ids or fid in rejected_ids:
            return
        src_status = (fact.get("source_state") or {}).get("status")
        if src_status in {"superseded", "unavailable"}:
            return
        seen_ids.add(fid)
        nodes.append(_to_node(fact))

    for branch in thinking_line.get("branches") or []:
        bfid = str(branch.get("fact_id") or "")
        if bfid and bfid in fact_by_id:
            _append_fact(fact_by_id[bfid])
        for child in branch.get("children") or []:
            cfid = str(child.get("fact_id") or "")
            if cfid and cfid in fact_by_id:
                _append_fact(fact_by_id[cfid])

    live_extras = [
        f
        for f in team_facts
        if f.get("kind") in {"decision", "assumption", "task"}
        and not (f.get("is_historical_doc") or is_historical_doc_fact(f))
    ]
    live_extras.sort(
        key=lambda f: (
            0 if f.get("status") == "accepted" else (1 if f.get("status") == "conflicted" else 2),
            0 if f.get("kind") in {"decision", "assumption"} else 1,
        )
    )
    for fact in live_extras:
        _append_fact(fact)

    if len(nodes) < 4:
        doc_extras = [
            f
            for f in team_facts
            if f.get("kind") in {"decision", "assumption", "task"}
            and str(f.get("id") or "") not in seen_ids
        ]
        doc_extras.sort(key=lambda f: (0 if f.get("kind") in {"decision", "assumption"} else 1))
        for fact in doc_extras:
            if len(nodes) >= min(max_nodes, 8):
                break
            _append_fact(fact)

    return {
        "root": dict(thinking_line.get("root") or {}),
        "nodes": nodes,
    }
