"""Layer 2: extraction.

Does Compass turn raw material into facts that a human would call true, and
does it refuse the ones that are not?

The layer measures the *product's* contract — exact quotes, evidence
attachment, member attribution, conflict preservation — and reports the
precision and recall of whatever extractor was plugged in. Keeping those two
things apart matters: a weak extractor and a broken contract are different
problems with different fixes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..corpus import Corpus
from ..scorers import score_extraction
from .base import HIGHER, LayerResult, Metric, ratio

LAYER_ID = "L2"
TITLE = "抽取层：事实准召与抽取契约"


@dataclass(frozen=True)
class ExtractionOutcome:
    """The result of running one extractor over the corpus."""

    extractor: str
    proposals: tuple
    candidates: int = 0
    rejected: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def extract_and_validate(corpus: Corpus, extractor_result) -> ExtractionOutcome:
    """Run an extractor and pass its candidates through the product's gate.

    The gate is the product's own ``validate_candidates``: a candidate only
    survives with an exact quote in a real source. A runner therefore cannot
    make the product believe something the product would not accept.
    """
    from ...candidate_extraction import validate_candidates

    if not extractor_result.ok:
        return ExtractionOutcome(
            extractor=extractor_result.name, proposals=(), error=extractor_result.error
        )
    # A batched extractor already validated every batch against its own
    # window, so its proposals are the product's own accepted candidates.
    if extractor_result.proposals:
        return ExtractionOutcome(
            extractor=extractor_result.name,
            proposals=tuple(extractor_result.proposals),
            candidates=extractor_result.candidates,
            rejected=extractor_result.rejected,
        )
    candidates = extractor_result.payload.get("candidates") or []
    accepted: list = []
    rejected = 0
    first_error = ""
    for candidate in candidates:
        try:
            accepted.extend(
                validate_candidates(list(corpus.events), {"candidates": [candidate]})
            )
        except (ValueError, TypeError, KeyError) as exc:
            rejected += 1
            first_error = first_error or str(exc)
    if candidates and not accepted:
        return ExtractionOutcome(
            extractor=extractor_result.name,
            proposals=(),
            candidates=len(candidates),
            rejected=rejected,
            error=f"候选整体未通过抽取校验：{first_error}",
        )
    return ExtractionOutcome(
        extractor=extractor_result.name,
        proposals=tuple(accepted),
        candidates=len(candidates),
        rejected=rejected,
    )


def run_extraction(corpus: Corpus, *, extractor_result, outcome: ExtractionOutcome | None = None):
    """Measure one extractor run against the independent gold set."""
    from ...fact_engine import derive_facts

    events = list(corpus.events)
    name = extractor_result.name
    notes: list[str] = []

    if outcome is None:
        outcome = extract_and_validate(corpus, extractor_result)

    if not outcome.ok:
        return LayerResult(
            layer=LAYER_ID,
            title=TITLE,
            metrics=(
                Metric("extraction_ran", 0.0, 1.0, HIGHER, hard=True, detail=outcome.error),
            ),
            details={"extractor": name, "error": outcome.error},
            notes=("抽取器没有返回可用结果，本层无法评分。",),
        )

    proposals = list(outcome.proposals)
    enriched = [*events, *proposals]
    facts = derive_facts(enriched)
    score = score_extraction(facts, list(corpus.gold.facts))

    attached = sum(1 for fact in facts if fact.evidence_ids)
    author_known = sum(
        1 for fact in facts if fact.author and fact.author not in {"", "project-documents"}
    )

    # A conflict must keep every side in the team view, not just the newest.
    distinct_by_subject: dict[str, set[str]] = {}
    for fact in facts:
        distinct_by_subject.setdefault(fact.subject_key, set()).add(fact.value)
    conflicted_subjects = {
        subject for subject, values in distinct_by_subject.items() if len(values) > 1
    }
    team_conflicts = {
        item["subject_key"]: {side["value"] for side in item["sides"]}
        for item in _team_conflicts(enriched)
    }
    preserved = sum(
        1
        for subject in conflicted_subjects
        if team_conflicts.get(subject) == distinct_by_subject[subject]
    )

    metrics = (
        Metric(
            "extraction_precision",
            score.precision,
            0.0,
            HIGHER,
            hard=False,
            detail=f"{score.matched}/{score.predicted_total} 条候选命中金标准",
        ),
        Metric(
            "extraction_recall",
            score.recall,
            0.0,
            HIGHER,
            hard=False,
            detail=f"{score.matched}/{score.gold_total} 条金标准被找回",
        ),
        Metric(
            "extraction_f1",
            score.f1,
            0.0,
            HIGHER,
            hard=False,
            detail="抽取层 F1",
        ),
        Metric(
            "contract_accept_rate",
            ratio(outcome.candidates - outcome.rejected, outcome.candidates) if outcome.candidates else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="所有候选都带有原文精确引用"
            if outcome.candidates
            else "无候选生成（按 0 拒收空洞通过）",
        ),
        Metric(
            "evidence_attachment",
            ratio(attached, len(facts)) if facts else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="每条事实都挂到证据" if facts else "0 条派生事实（空洞通过）",
        ),
        Metric(
            "member_attribution",
            ratio(author_known, len(facts)) if facts else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="每条事实都能追到成员" if facts else "0 条派生事实（空洞通过）",
        ),
        Metric(
            "conflict_preservation",
            ratio(preserved, len(conflicted_subjects)) if conflicted_subjects else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail="同一主题的不同主张在团队视图中全部保留"
            if conflicted_subjects
            else "当前语料含 0 处冲突，属空洞通过（vacuous pass）",
        ),
    )
    if not outcome.candidates:
        notes.append("vacuous_contract_check: extractor emitted 0 candidates.")
    if not facts:
        notes.append("vacuous_fact_attribution: 0 facts derived from accepted proposals.")
    if not conflicted_subjects:
        notes.append("vacuous_conflict_check: extracted facts contain 0 conflicting subjects.")

    return LayerResult(
        layer=LAYER_ID,
        title=TITLE,
        metrics=metrics,
        details={
            "extractor": name,
            "candidates": outcome.candidates,
            "accepted_candidates": len(proposals),
            "rejected_candidates": outcome.rejected,
            "facts": len(facts),
            "missed_gold": list(score.missed),
            "spurious_count": len(score.spurious),
            "conflicted_subjects": sorted(conflicted_subjects),
        },
        notes=tuple(notes),
    )


def _team_conflicts(events):
    """Return the conflict entries the product builds for the team view."""
    from ...projections import build_views

    return build_views(list(events)).get("team", {}).get("conflicts", [])
