"""Layer 1: structure.

Does Compass ingest the material and build the two layers of truth without
losing ownership or promoting a claim on its own?

This layer is the cheapest one to run and the one that guards the product's
hard red lines, so it is also the layer that must never be skipped.
"""

from __future__ import annotations

from ..corpus import Corpus
from .base import HIGHER, LayerResult, Metric, ratio

LAYER_ID = "L1"
TITLE = "结构层：摄入、归属与两层真相"


def run_structure(corpus: Corpus, *, events=None) -> LayerResult:
    """Measure ingestion, member attribution and truth separation.

    ``events`` may carry the proposals an extractor produced; the truth-layer
    checks need those, because a corpus of raw material alone has no claims
    to keep apart.
    """
    from ...candidate_extraction import source_member
    from ...evidence_store import EvidenceStore
    from ...fact_engine import derive_facts
    from ...native_codex import is_platform_control
    from ...projections import build_views

    events = list(events) if events is not None else list(corpus.events)

    store = EvidenceStore()
    duplicate_rejected = 0
    for event in events:
        try:
            store.append(event)
        except ValueError:
            duplicate_rejected += 1
    stored = store.list()

    facts = derive_facts(events)
    views = build_views(events)
    personal = views["personal"]
    team = views["team"]

    members = sorted({str(event.metadata.get("member_id", "")) for event in events})
    known_members = [member for member in members if member]

    attributed = 0
    session_consistent = 0
    for event in events:
        member = event.metadata.get("member_id")
        if isinstance(member, str) and member:
            attributed += 1
            if member in str(event.session_id):
                session_consistent += 1

    # Evidence ownership: an event must show up in the view of the member it
    # belongs to. A member may *cite* another member's event, so the check is
    # not that an event appears exactly once — it is that it appears in the
    # right place.
    owner_views: dict[str, set[str]] = {}
    for member_id, view in personal.items():
        for evidence_id in view.get("evidence_ids", []):
            owner_views.setdefault(evidence_id, set()).add(member_id)
    raw_events = [
        event for event in events
        if event.kind not in {"fact_proposal", "file_observation"}
        and not is_platform_control(event.content, kind=event.kind)
    ]
    owned = 0
    for event in raw_events:
        if event.kind in {"file_snapshot", "file_unavailable", "git_commit"}:
            owner = "project-documents"
        else:
            owner = event.metadata.get("member_id") or source_member(event)
        if owner in owner_views.get(event.id, set()):
            owned += 1

    # Fact isolation: a claim belongs to its author. It must appear in exactly
    # one personal view, and that view must be the author's own.
    fact_views: dict[str, list[str]] = {}
    for member_id, view in personal.items():
        for fact in view.get("facts", []):
            fact_views.setdefault(fact["id"], []).append(member_id)
    isolated = 0
    for fact in facts:
        owners = fact_views.get(fact.id, [])
        if len(owners) == 1 and owners[0] == fact.author:
            isolated += 1

    # The hard red line: nothing may claim team truth without a human record.
    accepted_without_review = [
        fact["id"] for fact in team["facts"] if fact["status"] == "accepted"
    ]
    facts_in_team = len(team["facts"])
    team_covers_all = sum(
        1 for fact in facts if any(item["id"] == fact.id for item in team["facts"])
    )

    # Conflicting claims must stay visible on both sides.
    conflict_subjects = {fact.subject_key for fact in facts if fact.status.value == "conflicted"}
    reported_conflicts = {item["subject_key"] for item in team["conflicts"]}
    conflicts_visible = len(conflict_subjects & reported_conflicts)

    metrics = (
        Metric(
            "ingest_completeness",
            ratio(len(stored), len(events)),
            1.0,
            HIGHER,
            hard=True,
            detail=f"{len(stored)}/{len(events)} 条证据写入存储",
        ),
        Metric(
            "member_attribution",
            ratio(attributed, len(events)),
            1.0,
            HIGHER,
            hard=True,
            detail="每条证据都能定位到成员",
        ),
        Metric(
            "session_consistency",
            ratio(session_consistent, len(events)),
            1.0,
            HIGHER,
            hard=True,
            detail="会话 ID 与成员一致",
        ),
        Metric(
            "evidence_owner",
            ratio(owned, len(raw_events)),
            1.0,
            HIGHER,
            hard=True,
            detail="每条证据都出现在其归属成员的视图里",
        ),
        Metric(
            "fact_isolation",
            ratio(isolated, len(facts)) if facts else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="每条事实只出现在作者本人的个人视图里",
        ),
        Metric(
            "no_unconfirmed_promotion",
            1.0 if not accepted_without_review else 0.0,
            1.0,
            HIGHER,
            hard=True,
            detail="未经人工确认的事实没有晋升为团队事实",
        ),
        Metric(
            "team_view_coverage",
            ratio(team_covers_all, len(facts)) if facts else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="团队视图覆盖全部候选事实",
        ),
        Metric(
            "conflict_visibility",
            ratio(conflicts_visible, len(conflict_subjects)) if conflict_subjects else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail=(
                "冲突主张在团队视图中同时保留两侧"
                if conflict_subjects
                else "当前语料含 0 处冲突，属空洞通过（vacuous pass）"
            ),
        ),
    )

    notes = [
        "本层不依赖任何模型，可直接在 CI 中运行。",
        "成员视图只做隔离，不做语义过滤；语义精度由 L2 与 L3 负责。",
    ]
    if not conflict_subjects:
        notes.append("vacuous_conflict_check: corpus has 0 conflicting subjects (requires multi-stance corpus for non-vacuous conflict check).")

    return LayerResult(
        layer=LAYER_ID,
        title=TITLE,
        metrics=metrics,
        details={
            "events": len(events),
            "stored_events": len(stored),
            "duplicate_rejected": duplicate_rejected,
            "members": known_members,
            "facts": facts_in_team,
            "conflicted_subjects": sorted(conflict_subjects),
            "personal_members": sorted(personal),
        },
        notes=tuple(notes),
    )
