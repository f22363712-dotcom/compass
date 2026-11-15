"""Deterministic scoring for the ProjectCompass evaluation benchmark.

Every score here is model independent: it compares facts, evidence identifiers
and terms, never the wording a particular agent would have produced. A model
may be used as an agent under test or as a judge, but never as the rule that
decides whether an answer was correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from ..models import CandidateFact
from .gold import GoldFact, GoldQuestion

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Fold text to a comparable form without changing its meaning."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()


def contains_all(text: str, terms) -> bool:
    """Return whether every term appears in the normalized text."""
    haystack = normalize(text)
    return all(normalize(term) in haystack for term in terms if str(term).strip())


def contains_any(text: str, terms) -> list[str]:
    """Return the terms that appear in the normalized text."""
    haystack = normalize(text)
    return [term for term in terms if str(term).strip() and normalize(term) in haystack]


@dataclass(frozen=True)
class FactMatch:
    """Why a predicted fact did or did not satisfy a gold fact."""

    gold_id: str
    matched: bool
    evidence_shared: bool
    missing_terms: tuple[str, ...] = ()
    violated_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "gold_id": self.gold_id,
            "matched": self.matched,
            "evidence_shared": self.evidence_shared,
            "missing_terms": list(self.missing_terms),
            "violated_terms": list(self.violated_terms),
        }


def match_fact(predicted: CandidateFact, gold: GoldFact, *, require_evidence: bool = True) -> FactMatch:
    """Match one predicted fact against one gold fact.

    A match needs the required terms to be present and no forbidden term to
    appear. Requiring a shared evidence anchor keeps the score honest: the
    fact has to be attached to the source that actually records it.
    """
    evidence_shared = bool(set(predicted.evidence_ids) & set(gold.evidence_ids))
    haystack = f"{predicted.value} {predicted.quote or ''}"
    missing = tuple(term for term in gold.required_terms if normalize(term) not in normalize(haystack))
    violated = tuple(contains_any(haystack, gold.forbidden_terms))
    matched = not missing and not violated and (evidence_shared or not require_evidence)
    return FactMatch(
        gold_id=gold.id,
        matched=matched,
        evidence_shared=evidence_shared,
        missing_terms=missing,
        violated_terms=violated,
    )


@dataclass(frozen=True)
class ExtractionScore:
    """Precision and recall of the extraction layer against independent gold."""

    gold_total: int
    predicted_total: int
    matched: int
    missed: tuple[str, ...]
    spurious: tuple[str, ...]
    matches: tuple[FactMatch, ...] = ()

    @property
    def precision(self) -> float:
        if self.predicted_total == 0:
            return 0.0
        return self.matched / self.predicted_total

    @property
    def recall(self) -> float:
        if self.gold_total == 0:
            return 0.0
        return self.matched / self.gold_total

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)

    def to_dict(self) -> dict:
        return {
            "gold_total": self.gold_total,
            "predicted_total": self.predicted_total,
            "matched": self.matched,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "missed": list(self.missed),
            "spurious": list(self.spurious),
            "matches": [match.to_dict() for match in self.matches],
        }


def score_extraction(
    predicted: list[CandidateFact],
    gold: list[GoldFact],
    *,
    require_evidence: bool = True,
) -> ExtractionScore:
    """Score predicted facts against gold facts with one-to-one assignment.

    Uses deterministic maximum bipartite matching so ordering of predictions or
    gold facts never drops a valid pairing.
    """
    adj: list[list[tuple[int, FactMatch]]] = []
    for gold_fact in gold:
        options: list[tuple[int, FactMatch]] = []
        for p_idx, candidate in enumerate(predicted):
            match = match_fact(candidate, gold_fact, require_evidence=require_evidence)
            if match.matched:
                options.append((p_idx, match))
        options.sort(key=lambda item: (0 if item[1].evidence_shared else 1, item[0]))
        adj.append(options)

    p_to_g: dict[int, tuple[int, FactMatch]] = {}

    def _augment(g_idx: int, seen_p: set[int]) -> bool:
        for p_idx, match in adj[g_idx]:
            if p_idx in seen_p:
                continue
            seen_p.add(p_idx)
            if p_idx not in p_to_g or _augment(p_to_g[p_idx][0], seen_p):
                p_to_g[p_idx] = (g_idx, match)
                return True
        return False

    for g_idx in range(len(gold)):
        _augment(g_idx, set())

    g_to_match: dict[int, FactMatch] = {g_idx: match for g_idx, match in p_to_g.values()}
    used = set(p_to_g.keys())
    matches: list[FactMatch] = []
    missed: list[str] = []
    for g_idx, gold_fact in enumerate(gold):
        match = g_to_match.get(g_idx)
        if match is not None:
            matches.append(match)
        else:
            missed.append(gold_fact.id)
    spurious = [candidate.id for index, candidate in enumerate(predicted) if index not in used]
    return ExtractionScore(
        gold_total=len(gold),
        predicted_total=len(predicted),
        matched=len(matches),
        missed=tuple(missed),
        spurious=tuple(spurious),
        matches=tuple(matches),
    )


@dataclass(frozen=True)
class RetrievalScore:
    """Whether the ranked evidence list puts the answer within reach."""

    question_id: str
    hit_at: int | None
    rank: int | None
    gold_total: int

    @property
    def reciprocal_rank(self) -> float:
        return 0.0 if self.rank is None else 1.0 / self.rank

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "hit_at": self.hit_at,
            "rank": self.rank,
            "gold_total": self.gold_total,
            "reciprocal_rank": round(self.reciprocal_rank, 4),
        }


def score_retrieval(ranked_evidence_ids, question: GoldQuestion, *, cutoff: int = 5) -> RetrievalScore:
    """Score one ranked evidence list against a gold question."""
    gold = set(question.evidence_ids)
    ranked = list(ranked_evidence_ids)
    rank = None
    for index, evidence_id in enumerate(ranked[:cutoff], start=1):
        if evidence_id in gold:
            rank = index
            break
    return RetrievalScore(
        question_id=question.id,
        hit_at=cutoff if rank is not None else None,
        rank=rank,
        gold_total=len(gold),
    )


@dataclass(frozen=True)
class AnswerScore:
    """Rule based verdict on one agent answer."""

    question_id: str
    scope: str
    correct: bool
    covered_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    violated_terms: tuple[str, ...]
    cited_known_evidence: bool
    cited_unknown_evidence: tuple[str, ...]
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "scope": self.scope,
            "correct": self.correct,
            "covered_terms": list(self.covered_terms),
            "missing_terms": list(self.missing_terms),
            "violated_terms": list(self.violated_terms),
            "cited_known_evidence": self.cited_known_evidence,
            "cited_unknown_evidence": list(self.cited_unknown_evidence),
            "detail": self.detail,
        }


_EVIDENCE_TOKEN = re.compile(r"\b(ev-[A-Za-z0-9_-]{4,}|[a-z]+-[0-9a-f]{10,})\b")


def score_answer(
    answer: str,
    question: GoldQuestion,
    *,
    known_evidence_ids: set[str] | None = None,
) -> AnswerScore:
    """Judge one answer with fixed rules, never with model taste.

    An answer is correct when it covers every required term, breaks no
    forbidden term and does not cite evidence that does not exist.
    """
    text = answer or ""
    covered = tuple(term for term in question.required_terms if normalize(term) in normalize(text))
    missing = tuple(term for term in question.required_terms if normalize(term) not in normalize(text))
    violated = tuple(contains_any(text, question.forbidden_terms))
    cited = tuple(sorted(set(_EVIDENCE_TOKEN.findall(text))))
    known = known_evidence_ids if known_evidence_ids is not None else set(question.evidence_ids)
    unknown = tuple(item for item in cited if item not in known)
    accepted = bool(question.accepted_answers) and any(
        normalize(candidate) in normalize(text) for candidate in question.accepted_answers
    )
    correct = not missing and not violated and not unknown
    detail = "accepted-answer" if accepted else ("rule-match" if correct else "rule-miss")
    return AnswerScore(
        question_id=question.id,
        scope=question.scope,
        correct=correct,
        covered_terms=covered,
        missing_terms=missing,
        violated_terms=violated,
        cited_known_evidence=not unknown,
        cited_unknown_evidence=unknown,
        detail=detail,
    )


@dataclass
class MetricSet:
    """Named metric values that a report can compare against a baseline."""

    values: dict = field(default_factory=dict)

    def set(self, name: str, value) -> None:
        self.values[name] = value

    def get(self, name: str, default=None):
        return self.values.get(name, default)

    def to_dict(self) -> dict:
        return dict(self.values)
