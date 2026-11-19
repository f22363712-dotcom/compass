"""Layer 3: handoff.

Can a member or an agent get the right answer out of Compass, and does the
answer stay inside the evidence?

This is the layer that carries the user-visible experience: a question in, an
answer out, with the evidence that supports it. It is measured twice, because
the two failures are different:

* retrieval — is the answer-bearing evidence reachable at all, and how high in
  the list does it appear;
* answer — does the final text contain the required content, avoid forbidden
  content, and cite only evidence that exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..corpus import Corpus
from ..scorers import score_answer, score_retrieval
from .base import HIGHER, LayerResult, Metric, ratio

LAYER_ID = "L3"
TITLE = "交接层：检索可达性与答案质量"


@dataclass(frozen=True)
class Answer:
    """One answer produced for one question."""

    text: str
    error: str = ""


class ProductAnswerer:
    """Answer with the product's own deterministic investigation path."""

    name = "product-investigator"

    def __init__(self, events) -> None:
        self.events = list(events)
        self._cache: dict[str, tuple[str, list[str]]] = {}

    def _evaluate(self, question: str) -> tuple[str, list[str]]:
        if question in self._cache:
            return self._cache[question]
        from ...investigator import investigate

        result = investigate(self.events, question)
        # Rank using the actual evidence ordering returned by investigate():
        # findings first, then next_action_basis, then remaining cited IDs.
        ranked: list[str] = []
        seen: set[str] = set()
        for finding in result.findings:
            for evidence_id in finding.get("evidence_ids") or ():
                if evidence_id and evidence_id not in seen:
                    seen.add(evidence_id)
                    ranked.append(evidence_id)
        if result.next_action_basis:
            for evidence_id in result.next_action_basis.get("evidence_ids") or ():
                if evidence_id and evidence_id not in seen:
                    seen.add(evidence_id)
                    ranked.append(evidence_id)
        for evidence_id in result.evidence_ids:
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                ranked.append(evidence_id)

        # Evaluate only the focused user-visible answer (conclusion, goal,
        # selected findings, single next_action, bounded evidence_gaps),
        # never dumping dozens of unfiltered active_tasks / assumptions.
        parts = [result.conclusion, result.goal]
        parts.extend(
            f"{finding.get('quote', '')} [{','.join(finding.get('evidence_ids', []))}]"
            for finding in result.findings
        )
        if result.next_action:
            parts.append(result.next_action)
        parts.extend(list(result.evidence_gaps)[:3])
        text = "\n".join(part for part in parts if part)
        self._cache[question] = (text, ranked)
        return text, ranked

    def rank_for_question(self, question: str) -> list[str]:
        try:
            _, ranked = self._evaluate(question)
            return list(ranked)
        except Exception:  # noqa: BLE001 - failure recorded during answer()
            return []

    def answer(self, question: str, context: dict) -> Answer:
        try:
            text, _ = self._evaluate(question)
        except Exception as exc:  # noqa: BLE001 - a failing answer is a measurement
            return Answer(text="", error=str(exc))
        return Answer(text=text)


class AgentAnswerer:
    """Answer with an external harness that reads a JSON context."""

    name = "agent"

    def __init__(self, runner) -> None:
        self.runner = runner
        self.name = getattr(runner, "spec", None)
        self.name = self.name.name if self.name is not None else "agent"

    def answer(self, question: str, context: dict) -> Answer:
        text, error = self.runner.answer(question, context)
        return Answer(text=text, error=error)


def _ranked_evidence(question: str, facts, *, events=None) -> list[str]:
    """Rank evidence ids by literal match over derived facts with hybrid raw-message fallback."""
    from ...literal_relevance import rank_literal

    evidence: list[str] = []
    if facts:
        ranked = rank_literal(
            question,
            facts,
            list(facts),
            text=lambda fact: f"{fact.quote or fact.value} {fact.subject_key}",
        )
        for fact in ranked:
            for evidence_id in fact.evidence_ids:
                if evidence_id not in evidence:
                    evidence.append(evidence_id)
    if events and len(evidence) < 8:
        msg_events = [
            ev for ev in events
            if getattr(ev, "kind", None) in {"assistant_message", "user_message"} and getattr(ev, "content", "")
        ]
        raw_ranked = rank_literal(
            question,
            msg_events,
            [],
            text=lambda ev: ev.content,
        )
        for ev in raw_ranked:
            if ev.id not in evidence:
                evidence.append(ev.id)
            if len(evidence) >= 12:
                break
    return evidence


def _context_for(facts, evidence_ids: list[str], events_by_id: dict) -> dict:
    """Build the bounded context handed to an answering harness."""
    selected = [fact for fact in facts if any(eid in evidence_ids for eid in fact.evidence_ids)]
    return {
        "facts": [
            {
                "fact_id": fact.id,
                "kind": fact.kind.value,
                "subject_key": fact.subject_key,
                "value": fact.value,
                "quote": fact.quote,
                "author": fact.author,
                "status": fact.status.value,
                "evidence_ids": list(fact.evidence_ids),
            }
            for fact in selected[:12]
        ],
        "evidence": [
            {
                "id": evidence_id,
                "kind": events_by_id[evidence_id].kind,
                "member_id": events_by_id[evidence_id].metadata.get("member_id", ""),
                "observed_at": events_by_id[evidence_id].observed_at.isoformat(),
                "excerpt": events_by_id[evidence_id].content[:1200],
            }
            for evidence_id in evidence_ids[:12]
            if evidence_id in events_by_id
        ],
    }


def run_handoff(
    corpus: Corpus,
    *,
    events=None,
    answerer=None,
    cutoff: int = 5,
) -> LayerResult:
    """Measure retrieval reachability and answer quality for every question."""
    from ...fact_engine import derive_facts

    working = list(events) if events is not None else list(corpus.events)
    facts = derive_facts(working)
    events_by_id = {event.id: event for event in working}
    questions = list(corpus.gold.questions)
    responder = answerer or ProductAnswerer(working)
    notes: list[str] = []

    retrieval_scores = []
    answer_scores = []
    non_empty_answers = 0
    errors: list[str] = []
    covered_gold: list[float] = []
    for question in questions:
        if hasattr(responder, "rank_for_question"):
            ranked = responder.rank_for_question(question.question)
        else:
            ranked = _ranked_evidence(question.question, facts, events=working)
        retrieval_scores.append(score_retrieval(ranked, question, cutoff=cutoff))

        # Was the answer-bearing evidence ever quoted as a fact at all? Without
        # this, a retrieval miss cannot be told apart from an extraction miss,
        # and the two need very different fixes.
        gold = set(question.evidence_ids)
        with_fact = {
            evidence_id
            for fact in facts
            for evidence_id in fact.evidence_ids
            if evidence_id in gold
        }
        covered_gold.append(len(with_fact) / max(1, len(gold)))

        context = _context_for(facts, ranked, events_by_id)
        answer = responder.answer(question.question, context)
        if answer.error:
            errors.append(f"{question.id}: {answer.error}")
            answer = Answer(text="")
        if str(answer.text or "").strip():
            non_empty_answers += 1
        answer_scores.append(
            score_answer(
                answer.text,
                question,
                known_evidence_ids=set(events_by_id),
            )
        )

    hits = sum(1 for score in retrieval_scores if score.rank is not None)
    correct = sum(1 for score in answer_scores if score.correct)
    team = [score for score in answer_scores if score.scope == "team"]
    personal = [score for score in answer_scores if score.scope == "personal"]
    team_correct = sum(1 for score in team if score.correct)
    personal_correct = sum(1 for score in personal if score.correct)

    reciprocal = sum(score.reciprocal_rank for score in retrieval_scores) / max(1, len(retrieval_scores))

    metrics = (
        Metric(
            "evidence_coverage",
            ratio(
                sum(1 for value in covered_gold if value > 0),
                len(covered_gold),
            )
            if covered_gold
            else 1.0,
            0.0,
            HIGHER,
            hard=False,
            detail=(
                f"{sum(1 for value in covered_gold if value > 0)}/{len(covered_gold)} "
                "道题的金标准证据至少被一条事实引用过"
            ),
        ),
        Metric(
            "retrieval_hit_rate",
            ratio(hits, len(retrieval_scores)),
            0.0,
            HIGHER,
            hard=False,
            detail=f"{hits}/{len(retrieval_scores)} 道题在前 {cutoff} 条证据内命中",
        ),
        Metric(
            "retrieval_mrr",
            reciprocal,
            0.0,
            HIGHER,
            hard=False,
            detail="命中证据的平均倒数排名",
        ),
        Metric(
            "answer_accuracy",
            ratio(correct, len(answer_scores)),
            0.0,
            HIGHER,
            hard=False,
            detail=f"{correct}/{len(answer_scores)} 道题答对",
        ),
        Metric(
            "answer_accuracy_team",
            ratio(team_correct, len(team)),
            0.0,
            HIGHER,
            hard=False,
            detail=f"团队视角 {team_correct}/{len(team)}",
        ),
        Metric(
            "answer_accuracy_personal",
            ratio(personal_correct, len(personal)),
            0.0,
            HIGHER,
            hard=False,
            detail=f"个人视角 {personal_correct}/{len(personal)}",
        ),
        Metric(
            "answers_produced",
            ratio(non_empty_answers, len(questions)),
            1.0,
            HIGHER,
            hard=True,
            detail=f"{non_empty_answers}/{len(questions)} 道题给出了非空回答",
        ),
        Metric(
            "evidence_validity",
            ratio(
                sum(1 for score in answer_scores if score.cited_known_evidence),
                len(answer_scores),
            ),
            1.0,
            HIGHER,
            hard=True,
            detail="答案没有引用不存在的证据",
        ),
    )

    if errors:
        notes.append(f"{len(errors)} 道题的回答失败，已按未答对计入。")

    return LayerResult(
        layer=LAYER_ID,
        title=TITLE,
        metrics=metrics,
        details={
            "answerer": getattr(responder, "name", "unknown"),
            "questions": len(questions),
            "facts": len(facts),
            "retrieval": [score.to_dict() for score in retrieval_scores],
            "answers": [score.to_dict() for score in answer_scores],
            "errors": errors,
        },
        notes=tuple(notes),
    )
