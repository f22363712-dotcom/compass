"""Proactive local & async LLM Agent hints plus grounded investigation synthesis.

Pure Python standard library only. Never imports fact_engine, projections, or
candidate_extraction so L4 benchmark blast-radius contracts remain untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
import json
import re
from threading import Lock, Thread
import time
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
_CRINGE_RE = re.compile("|".join(re.escape(t) for t in _CRINGE_TERMS), re.IGNORECASE)
_CHINESE_GENERIC_BIGRAMS = frozenset({
    "我们", "你们", "他们", "这个", "那个", "这样", "方案", "路线", "使用",
    "采用", "实现", "系统", "问题", "工作", "当前", "进行", "通过", "可以",
    "需要", "应该", "如果", "因为", "所以", "或者", "还是", "关于", "基于",
})
_ALLOWED_HINT_CATEGORIES = frozenset({
    "推进建议",
    "偏航提醒",
    "风险提示",
    "待定锚点",
    "待拍板",
    "未验前提",
    "方案权衡",
    "盲区预警",
})
_WARN_CATEGORIES = frozenset({"偏航提醒", "风险提示", "未验前提", "盲区预警"})
_PREMISE_RISK_LEVEL = {"invalidated": 0, "unverified": 1}


def _parse_ts_epoch(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _latest_ts_epoch(state: dict[str, Any]) -> float | None:
    epochs: list[float] = []
    for item in state.get("activity_stream") or []:
        ep = _parse_ts_epoch(item.get("observed_at") or item.get("ts"))
        if ep is not None:
            epochs.append(ep)
    for fact in (state.get("team") or {}).get("facts") or []:
        ep = _parse_ts_epoch(fact.get("observed_at") or fact.get("updated_at") or fact.get("ts"))
        if ep is not None:
            epochs.append(ep)
    return max(epochs) if epochs else None


def _extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in _TOKEN_RE.findall(str(text or "").casefold()):
        if chunk.isascii():
            tokens.add(chunk)
        elif len(chunk) == 2:
            if chunk not in _CHINESE_GENERIC_BIGRAMS and not any(ch in chunk for ch in "的了是在和与"):
                tokens.add(chunk)
        else:
            for i in range(len(chunk) - 1):
                bg = chunk[i : i + 2]
                if bg not in _CHINESE_GENERIC_BIGRAMS and not any(ch in bg for ch in "的了是在和与"):
                    tokens.add(bg)
    return tokens


def _scrub_hint_text(text: str) -> str:
    cleaned = clean_display_text(text)
    cleaned = _CRINGE_RE.sub("Agent ", cleaned)
    return " ".join(cleaned.split()).strip()


def _detect_ast_blast_radius(state: dict[str, Any], recent_edits: list[dict[str, Any]]) -> tuple[str, int, str] | None:
    """Detect whether recent edited files have high cross-module caller fan-in."""
    ctx = state.get("derived_context") or {}
    if not ctx.get("enabled") or not recent_edits:
        return None
    nodes = {str(n.get("id")): n for n in (ctx.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    edges = [e for e in (ctx.get("edges") or []) if isinstance(e, dict)]
    if not nodes or not edges:
        return None

    in_callers_by_file: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("kind") not in {"calls", "imports"}:
            continue
        src_node = nodes.get(str(edge.get("from_id") or ""))
        dst_node = nodes.get(str(edge.get("to_id") or ""))
        if not src_node or not dst_node:
            continue
        src_file = str(src_node.get("source_ref") or "").replace("\\", "/").lstrip("./")
        dst_file = str(dst_node.get("source_ref") or "").replace("\\", "/").lstrip("./")
        if src_file and dst_file and src_file != dst_file:
            in_callers_by_file.setdefault(dst_file, set()).add(src_file)

    best_hit: tuple[int, str, str] | None = None
    for edit in recent_edits:
        edit_ref = str(edit.get("source_ref") or "").replace("\\", "/").lstrip("./")
        edit_summary = str(edit.get("summary") or "").replace("\\", "/")
        for dst_file, callers in in_callers_by_file.items():
            if len(callers) < 3:
                continue
            matched = False
            if edit_ref:
                matched = edit_ref == dst_file or edit_ref.endswith("/" + dst_file) or dst_file.endswith("/" + edit_ref)
            else:
                file_base = dst_file.rsplit("/", 1)[-1]
                matched = bool(dst_file in edit_summary or (file_base and re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(file_base)}(?![A-Za-z0-9_.-])", edit_summary)))
            if matched:
                ev_id = str((edit.get("evidence_ids") or [edit.get("primary_evidence_id") or ""])[0] or "")
                cand = (len(callers), dst_file, ev_id)
                if best_hit is None or cand[0] > best_hit[0]:
                    best_hit = cand
    if best_hit is None:
        return None
    return (best_hit[1], best_hit[0], best_hit[2])


def build_local_agent_hints(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build up to 3 high-signal, abstention-gated deterministic Agent hints."""
    if not isinstance(state, dict):
        return []
    team = state.get("team") or {}
    team_facts = list(team.get("facts") or [])
    activity_stream = list(state.get("activity_stream") or [])
    decision_summary = state.get("decision_summary") or {}
    evidence_count = int((state.get("project") or {}).get("evidence_count") or 0)

    if evidence_count == 0 and not team_facts:
        return [
            {
                "id": "hint-anchor-goal-empty",
                "category": "待定锚点",
                "level": "info",
                "text": "新项目还没定目标，在上方「核心目标」写一句话确认后，后续讨论都会围绕它对齐。",
                "evidence_ids": [],
                "fact_id": None,
                "action_kind": "edit_goal",
                "action_label": "设定目标",
                "source": "local",
            }
        ]

    hints: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _push(hint: dict[str, Any]) -> None:
        hid = str(hint.get("id") or "")
        if hid and hid not in seen_ids:
            seen_ids.add(hid)
            hints.append(hint)

    latest_review: dict[str, dict[str, Any]] = {}
    for rev in (state.get("review_history") or []):
        fid = str(rev.get("fact_id") or "")
        if fid and rev.get("action") != "confirm_relation":
            latest_review[fid] = rev
    rejected_fact_ids = {
        fid for fid, rev in latest_review.items() if rev.get("action") == "reject_fact"
    }
    superseded_ids = {
        str(f.get("id") or "")
        for f in team_facts
        if f.get("superseded_by_fact_id")
    }
    active_facts = [
        f for f in team_facts
        if str(f.get("id") or "") not in rejected_fact_ids
        and f.get("status") != "rejected"
    ]

    primary_goal = select_primary_goal(active_facts)
    next_consensus = state.get("next_consensus") or select_next_consensus(active_facts)
    if next_consensus and str(next_consensus.get("fact_id") or next_consensus.get("id") or "") in rejected_fact_ids:
        next_consensus = None
    has_explicit_next = bool(next_consensus and not next_consensus.get("is_candidate_suggestion"))
    recent_edits = [item for item in activity_stream[:6] if item.get("action_kind") == "edit"]

    # 1. Execution failure warning (highest operational priority)
    latest_failure = None
    for item in activity_stream[:5]:
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
        _push({
            "id": f"hint-fail-{ev_ids[0] if ev_ids else 'cmd'}",
            "category": "风险提示",
            "level": "warn",
            "text": f"最近一次运行没通过（{fail_summary}），建议先排查报错再继续往下做。",
            "evidence_ids": ev_ids[:2],
            "fact_id": None,
            "action_kind": "open_evidence" if ev_ids else "",
            "action_label": "查看记录" if ev_ids else "",
            "source": "local",
        })

    # 2. Invalidated or unverified critical premise gate
    premises = sorted(
        [
            p for p in (decision_summary.get("premises") or [])
            if str(p.get("fact_id") or "") not in superseded_ids
            and str(p.get("fact_id") or "") not in rejected_fact_ids
        ],
        key=lambda p: _PREMISE_RISK_LEVEL.get(str(p.get("status") or ""), 9),
    )
    invalidated_premise = next((p for p in premises if p.get("status") == "invalidated"), None)
    unverified_premise = next((p for p in premises if p.get("status") == "unverified"), None)
    if invalidated_premise is not None:
        p_title = clean_display_text(invalidated_premise.get("title") or "关键假设", max_chars=26)
        _push({
            "id": f"hint-premise-invalidated-{invalidated_premise.get('fact_id', 'p')}",
            "category": "未验前提",
            "level": "warn",
            "text": f"方案前提「{p_title}」刚刚运行失败、可能不成立，建议先核对再继续开发。",
            "evidence_ids": list(invalidated_premise.get("evidence_ids") or [])[:2],
            "fact_id": invalidated_premise.get("fact_id"),
            "action_kind": "open_fact" if invalidated_premise.get("fact_id") else "open_evidence",
            "action_label": "核查前提",
            "source": "local",
        })
    elif unverified_premise is not None and (recent_edits or decision_summary.get("open_forks_count") or len(team_facts) >= 2):
        p_title = clean_display_text(unverified_premise.get("title") or "待验证前提", max_chars=26)
        _push({
            "id": f"hint-premise-unverified-{unverified_premise.get('fact_id', 'p')}",
            "category": "未验前提",
            "level": "warn",
            "text": f"方案前提「{p_title}」还没实测验证，动手前建议先跑个最小检查确认能走通。",
            "evidence_ids": list(unverified_premise.get("evidence_ids") or [])[:2],
            "fact_id": unverified_premise.get("fact_id"),
            "action_kind": "open_fact" if unverified_premise.get("fact_id") else "open_evidence",
            "action_label": "核查前提",
            "source": "local",
        })

    # 3. Blind-spot alert: rejected-path relapse OR high-fan-in AST blast radius
    rejected_paths = [
        r for r in (decision_summary.get("rejected_paths") or [])
        if str(r.get("fact_id") or "") not in superseded_ids
        and str(r.get("fact_id") or "") not in rejected_fact_ids
    ]
    if rejected_paths:
        recent_live_texts = [
            (f.get("id"), f.get("value") or f.get("quote") or "", list(f.get("evidence_ids") or []))
            for f in active_facts
            if f.get("status") in {"proposed", "conflicted"}
            and not is_historical_doc_fact(f)
            and not f.get("superseded_by_fact_id")
            and f.get("decision_context", {}).get("stage") != "rejected_path"
        ]
        recent_live_texts.extend(
            (None, f"{e.get('summary') or ''} {e.get('source_ref') or ''}", list(e.get("evidence_ids") or []))
            for e in activity_stream[:4]
        )
        for rej in rejected_paths:
            r_tokens = _extract_tokens(f"{rej.get('title') or ''} {rej.get('value') or ''}")
            if len(r_tokens) < 2:
                continue
            for item_fid, text_val, ev_ids in recent_live_texts:
                overlap = r_tokens & _extract_tokens(text_val)
                if len(overlap) >= 3:
                    r_title = clean_display_text(rej.get("title") or "既往排除方案", max_chars=22)
                    reason = clean_display_text(rej.get("reason") or "历史决策已排除", max_chars=24)
                    _push({
                        "id": f"hint-relapse-{rej.get('fact_id', 'r')}",
                        "category": "盲区预警",
                        "level": "warn",
                        "text": f"最近动态疑似重提已否决方案「{r_title}」（当时原因：{reason}），如果情况没变别再踩坑。",
                        "evidence_ids": (list(rej.get("evidence_ids") or []) + list(ev_ids))[:2],
                        "fact_id": rej.get("fact_id") or item_fid,
                        "action_kind": "open_fact" if (rej.get("fact_id") or item_fid) else "open_evidence",
                        "action_label": "对照原由",
                        "source": "local",
                    })
                    break
            if any(h.get("category") == "盲区预警" for h in hints):
                break

    if not any(h.get("category") == "盲区预警" for h in hints):
        blast = _detect_ast_blast_radius(state, recent_edits)
        if blast is not None:
            dst_file, fan_in, ev_id = blast
            short_file = dst_file.rsplit("/", 1)[-1]
            _push({
                "id": f"hint-ast-blast-{short_file}",
                "category": "盲区预警",
                "level": "warn",
                "text": f"「{short_file}」被 {fan_in} 处其他文件引用，改完建议顺手跑一下相关测试看有没有影响。",
                "evidence_ids": [ev_id] if ev_id else [],
                "fact_id": None,
                "action_kind": "open_evidence" if ev_id else "",
                "action_label": "查看变更" if ev_id else "",
                "source": "local",
            })

    # 4. Anchor completeness & next-step drift
    if primary_goal is None:
        _push({
            "id": "hint-anchor-goal-empty",
            "category": "待定锚点",
            "level": "warn",
            "text": "还没写清楚核心目标，点上方目标卡用一句话定下来，后面更容易看清重点。",
            "evidence_ids": [],
            "fact_id": None,
            "action_kind": "edit_goal",
            "action_label": "设定目标",
            "source": "local",
        })
    elif primary_goal.get("status") != "accepted":
        goal_short = primary_goal.get("short_title") or summarize_node_title(primary_goal.get("value") or "", max_chars=22)
        _push({
            "id": f"hint-anchor-goal-{primary_goal.get('id', 'g')}",
            "category": "待定锚点",
            "level": "info",
            "text": f"核心目标「{goal_short}」还没确认，可直接改写精简或点一下确认定下来。",
            "evidence_ids": list(primary_goal.get("evidence_ids") or [])[:2],
            "fact_id": primary_goal.get("id"),
            "action_kind": "accept_fact",
            "action_label": "✓ 确认目标",
            "source": "local",
        })
    elif not has_explicit_next:
        _push({
            "id": "hint-anchor-next-empty",
            "category": "待定锚点",
            "level": "info",
            "text": "核心目标已定，建议顺手补一句「当前下一步」，让大家清楚手头优先做什么。",
            "evidence_ids": list(next_consensus.get("evidence_ids") or [])[:2] if next_consensus else [],
            "fact_id": next_consensus.get("id") if next_consensus else None,
            "action_kind": "edit_next",
            "action_label": "设定下一步",
            "source": "local",
        })

    # 5. Unresolved fork / multi-option trade-off brief
    open_forks = [
        f for f in (decision_summary.get("open_forks") or [])
        if str(f.get("fact_id") or "") not in superseded_ids
        and str(f.get("fact_id") or "") not in rejected_fact_ids
    ]
    if open_forks:
        top_fork = open_forks[0]
        alts = [clean_display_text(a, max_chars=20) for a in (top_fork.get("alternatives") or [])][:2]
        alts_txt = f"（{' vs '.join(alts)}）" if len(alts) >= 2 else ""
        fork_title = clean_display_text(top_fork.get("title") or "待决技术选型", max_chars=22)
        _push({
            "id": f"hint-fork-{top_fork.get('fact_id', 'f')}",
            "category": "方案权衡",
            "level": "info",
            "text": f"「{fork_title}」有几个备选方向{alts_txt}，建议先选定一个再大步写代码。",
            "evidence_ids": list(top_fork.get("evidence_ids") or [])[:2],
            "fact_id": top_fork.get("fact_id"),
            "action_kind": "open_fact" if top_fork.get("fact_id") else "open_evidence",
            "action_label": "查看对比",
            "source": "local",
        })

    # 6. Edit/topic drift against locked next-step anchor (skip stale >48h anchors)
    latest_ep = _latest_ts_epoch(state)
    next_ep = _parse_ts_epoch(next_consensus.get("observed_at")) if next_consensus else None
    next_is_stale = bool(latest_ep is not None and next_ep is not None and (latest_ep - next_ep) >= 48 * 3600)
    if latest_failure is None and has_explicit_next and not next_is_stale and len(recent_edits) >= 3:
        anchor_text = " ".join(
            str(part or "")
            for part in (
                primary_goal.get("value") if primary_goal else "",
                next_consensus.get("value") if next_consensus else "",
            )
        )
        anchor_tokens = _extract_tokens(anchor_text)
        edit_text = " ".join(f"{e.get('summary', '')} {e.get('source_ref', '')}" for e in recent_edits)
        if anchor_tokens and not (anchor_tokens & _extract_tokens(edit_text)):
            next_short = next_consensus.get("short_title") or summarize_node_title(next_consensus.get("value") or "", max_chars=20)
            _push({
                "id": f"hint-drift-{next_consensus.get('id', 'next')}",
                "category": "偏航提醒",
                "level": "warn",
                "text": f"最近几次改动和「当前下一步：{next_short}」关联较少，如果重心已切换，建议顺手更新一下。",
                "evidence_ids": list(recent_edits[0].get("evidence_ids") or [])[:2],
                "fact_id": next_consensus.get("id"),
                "action_kind": "edit_next",
                "action_label": "更新下一步",
                "source": "local",
            })

    # 7. Unconfirmed live proposal backlog
    if len(hints) < 3:
        pending_live = [
            f
            for f in active_facts
            if f.get("kind") in {"decision", "assumption"}
            and f.get("status") in {"proposed", "conflicted"}
            and not is_historical_doc_fact(f)
            and not f.get("superseded_by_fact_id")
            and not f.get("completed")
            and f.get("task_state") not in {"completed", "reported_complete"}
            and (f.get("decision_context") or {}).get("stage") != "rejected_path"
        ]
        if latest_ep is not None:
            recent_pending = [
                f
                for f in pending_live
                if (
                    (ep := _parse_ts_epoch(f.get("observed_at") or f.get("ts"))) is None
                    or (latest_ep - ep) <= 48 * 3600
                )
            ]
        else:
            recent_pending = pending_live
        if len(recent_pending) >= 3:
            first_item = recent_pending[-1]
            first_short = first_item.get("short_title") or summarize_node_title(first_item.get("value") or "", max_chars=20)
            _push({
                "id": f"hint-backlog-{len(recent_pending)}-{first_item.get('id', 'p')}",
                "category": "待拍板",
                "level": "info",
                "text": f"最近有 {len(recent_pending)} 项待确认想法（如「{first_short}」），挑重要的确认、不用的点忽略即可。",
                "evidence_ids": list(first_item.get("evidence_ids") or [])[:2],
                "fact_id": first_item.get("id"),
                "action_kind": "open_fact",
                "action_label": "查看待确认",
                "source": "local",
            })

    return hints[:3]


class AsyncHintCache:
    """Thread-safe revision-keyed cache computing rate-limited async LLM Agent hints."""

    def __init__(self, *, cooldown_sec: float = 60.0) -> None:
        self._lock = Lock()
        self._cooldown_sec = max(0.0, float(cooldown_sec))
        self._done: dict[str, dict[str, Any] | None] = {}
        self._done_by_snap: dict[str, dict[str, Any] | None] = {}
        self._inflight: set[str] = set()
        self._generation = 0
        self._epoch = 0
        self._last_spawn_mono: float | None = None
        self._last_llm_hint: dict[str, Any] | None = None

    def clear(self) -> None:
        with self._lock:
            self._done.clear()
            self._done_by_snap.clear()
            self._inflight.clear()
            self._last_spawn_mono = None
            self._last_llm_hint = None
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
        evidence_count = int((state.get("project") or {}).get("evidence_count") or 0)
        if sample_mode or evidence_count == 0 or not revision:
            return local_hints[:3], 0

        with self._lock:
            generation = self._generation
            spawn_epoch = self._epoch
            if revision in self._done:
                return self._merge_hints(local_hints, self._done[revision]), generation

        cfg = resolve_llm_config()
        if not cfg["enabled"]:
            return local_hints[:3], 0

        snapshot = self._build_snapshot(state)
        snap_key = "snap-" + sha1(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:16]

        with self._lock:
            generation = self._generation
            spawn_epoch = self._epoch
            if revision in self._done:
                cached = self._done[revision]
                return self._merge_hints(local_hints, cached), generation
            if snap_key in self._done_by_snap:
                cached = self._done_by_snap[snap_key]
                self._done[revision] = cached
                if len(self._done) > 16:
                    self._done.pop(next(iter(self._done)))
                return self._merge_hints(local_hints, cached), generation
            now_mono = time.monotonic()
            within_cooldown = (
                self._last_spawn_mono is not None
                and self._cooldown_sec > 0
                and (now_mono - self._last_spawn_mono) < self._cooldown_sec
            )
            if within_cooldown or revision in self._inflight or snap_key in self._inflight:
                return self._merge_hints(local_hints, self._last_llm_hint), generation
            self._inflight.add(revision)
            self._inflight.add(snap_key)
            self._last_spawn_mono = now_mono

        known_ev_ids = {
            str(ev.get("id"))
            for ev in (state.get("evidence") or [])
            if isinstance(ev, dict) and ev.get("id")
        }
        thread = Thread(
            target=self._worker,
            args=(revision, snap_key, snapshot, known_ev_ids, str(cfg["model"] or ""), spawn_epoch),
            daemon=True,
        )
        thread.start()

        return local_hints[:3], generation

    @staticmethod
    def _merge_hints(local_hints: list[dict[str, Any]], llm_hint: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not llm_hint:
            return local_hints[:3]
        merged = [llm_hint]
        merged.extend(local_hints[:2])
        return merged[:3]

    @staticmethod
    def _build_snapshot(state: dict[str, Any]) -> dict[str, Any]:
        team = state.get("team") or {}
        team_facts = list(team.get("facts") or [])
        latest_rev: dict[str, dict[str, Any]] = {}
        for rev in (state.get("review_history") or []):
            fid = str(rev.get("fact_id") or "")
            if fid and rev.get("action") != "confirm_relation":
                latest_rev[fid] = rev
        rejected_fact_ids = {
            fid for fid, rev in latest_rev.items() if rev.get("action") == "reject_fact"
        }
        superseded_ids = {
            str(f.get("id") or "")
            for f in team_facts
            if f.get("superseded_by_fact_id")
        }
        excluded_ids = superseded_ids | rejected_fact_ids
        decision_summary = state.get("decision_summary") or {}
        active_facts = [
            f for f in team_facts
            if str(f.get("id") or "") not in rejected_fact_ids and f.get("status") != "rejected"
        ]
        goal = select_primary_goal(active_facts)
        next_step = state.get("next_consensus") or select_next_consensus(active_facts)
        if next_step and str(next_step.get("fact_id") or next_step.get("id") or "") in excluded_ids:
            next_step = None
        latest_ep = _latest_ts_epoch(state)

        def _age_days(ts_raw: Any) -> float | None:
            ep = _parse_ts_epoch(ts_raw)
            if ep is None or latest_ep is None:
                return None
            return round(max(0.0, latest_ep - ep) / 86400.0, 1)

        accepted = [
            f.get("short_title") or clean_display_text(f.get("value") or "", max_chars=40)
            for f in active_facts
            if f.get("status") == "accepted" and not f.get("superseded_by_fact_id")
        ][-4:]
        pending = [
            f.get("short_title") or clean_display_text(f.get("value") or "", max_chars=40)
            for f in active_facts
            if f.get("status") in {"proposed", "conflicted"}
            and not is_historical_doc_fact(f)
            and not f.get("superseded_by_fact_id")
            and not f.get("completed")
            and f.get("task_state") not in {"completed", "reported_complete"}
            and (f.get("decision_context") or {}).get("stage") != "rejected_path"
        ][-4:]
        recent_completed = [
            f.get("short_title") or clean_display_text(f.get("value") or "", max_chars=40)
            for f in active_facts
            if f.get("completed") or f.get("task_state") in {"completed", "reported_complete"}
        ][-3:]
        recent_activity = [
            {
                "kind": item.get("action_kind"),
                "summary": clean_display_text(item.get("summary") or "", max_chars=60),
                "observed_at": item.get("observed_at") or item.get("ts") or "",
                "evidence_id": item.get("primary_evidence_id") or "",
            }
            for item in (state.get("activity_stream") or [])[:4]
        ]
        next_step_ts = next_step.get("observed_at") if next_step else ""
        return {
            "core_goal": clean_display_text(goal.get("value") if goal else "", max_chars=80),
            "goal_status": goal.get("status") if goal else "empty",
            "next_step": clean_display_text(next_step.get("value") if next_step else "", max_chars=80),
            "next_step_observed_at": next_step_ts or "",
            "next_step_age_days": _age_days(next_step_ts),
            "accepted_baselines": accepted,
            "pending_items": pending,
            "recent_completed": recent_completed,
            "unverified_premises": [
                {"title": p.get("title"), "status": p.get("status"), "evidence_ids": p.get("evidence_ids")}
                for p in (decision_summary.get("premises") or [])
                if p.get("status") != "verified" and str(p.get("fact_id") or "") not in excluded_ids
            ][:4],
            "open_forks": [
                {"title": f.get("title"), "alternatives": f.get("alternatives"), "evidence_ids": f.get("evidence_ids")}
                for f in (decision_summary.get("open_forks") or [])
                if str(f.get("fact_id") or "") not in excluded_ids
            ][:3],
            "rejected_paths": [
                {"title": r.get("title"), "reason": r.get("reason"), "evidence_ids": r.get("evidence_ids")}
                for r in (decision_summary.get("rejected_paths") or [])
                if str(r.get("fact_id") or "") not in excluded_ids
            ][:3],
            "recent_activity": recent_activity,
        }

    def _worker(
        self,
        revision: str,
        snap_key: str,
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
                        "你是帮开发者盯紧项目进度的务实协作者，只用大白话给 1 条具体建议。"
                        "严禁使用「锚定、收敛、闭环、契约、证伪、分叉、喧宾夺主、对齐主线」等黑话。"
                        "必须先核对 next_step_observed_at、next_step_age_days、recent_completed 和 recent_activity："
                        "如果 next_step 已经超过 2 天（age_days >= 2）或看起来已被 recent_completed / 新活动覆盖，"
                        "禁止再发「偏航提醒」去质疑新工作；此时要么保持静默，要么温和问一句旧的「下一步」是不是已经做完该更新了。"
                        "如果当前状态健康且没有值得打断的新风险，直接返回 {\"abstain\":true}；"
                        "否则只给 1 条短句建议（15～64字，一看就懂下一步该查什么）。"
                        '严格只输出 JSON：{"abstain":false,"category":"未验前提|方案权衡|盲区预警|偏航提醒|风险提示|推进建议","text":"...","evidence_id":"来自快照中的真实evidence_id"}。'
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
                if parsed.get("abstain") is True:
                    hint_obj = None
                else:
                    category = str(parsed.get("category") or "推进建议").strip()
                    if category not in _ALLOWED_HINT_CATEGORIES:
                        category = "推进建议"
                    text = _scrub_hint_text(str(parsed.get("text") or ""))
                    if 8 <= len(text) <= 92:
                        ev_id = str(parsed.get("evidence_id") or "").strip()
                        valid_ev_ids = [ev_id] if (ev_id and ev_id in known_ev_ids) else []
                        hint_obj = {
                            "id": f"hint-llm-{revision[:10]}",
                            "category": category,
                            "level": "warn" if category in _WARN_CATEGORIES else "info",
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
                self._inflight.discard(snap_key)
                if self._epoch == spawn_epoch:
                    self._done[revision] = hint_obj
                    self._done_by_snap[snap_key] = hint_obj
                    self._last_llm_hint = hint_obj
                    if len(self._done) > 16:
                        self._done.pop(next(iter(self._done)))
                    if len(self._done_by_snap) > 16:
                        self._done_by_snap.pop(next(iter(self._done_by_snap)))
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
