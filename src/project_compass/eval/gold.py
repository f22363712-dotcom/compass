"""Gold standards for the ProjectCompass evaluation benchmark.

A gold entry is authored from material that is independent of ProjectCompass
output (decision ledgers, task lists, review reports). Nothing here may be
derived from a fact that Compass produced, otherwise the benchmark only proves
that Compass agrees with itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

GOLD_FORMAT = "project-compass-eval-gold"
GOLD_VERSION = 1


class GoldError(ValueError):
    """Raised when a gold payload is malformed or internally inconsistent."""


@dataclass(frozen=True)
class GoldFact:
    """One independently authored fact that the extraction layer should find."""

    id: str
    kind: str
    subject_key: str
    value: str
    evidence_ids: tuple[str, ...]
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "subject_key": self.subject_key,
            "value": self.value,
            "evidence_ids": list(self.evidence_ids),
            "required_terms": list(self.required_terms),
            "forbidden_terms": list(self.forbidden_terms),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "GoldFact":
        if not isinstance(payload, dict):
            raise GoldError("gold fact must be an object")
        fact_id = payload.get("id")
        kind = payload.get("kind")
        value = payload.get("value")
        evidence_ids = payload.get("evidence_ids")
        if not isinstance(fact_id, str) or not fact_id.strip():
            raise GoldError("gold fact needs an id")
        if kind not in {"goal", "task", "decision", "assumption"}:
            raise GoldError(f"gold fact {fact_id} has an invalid kind")
        if not isinstance(value, str) or not value.strip():
            raise GoldError(f"gold fact {fact_id} needs a value")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise GoldError(f"gold fact {fact_id} needs at least one evidence anchor")
        if any(not isinstance(anchor, str) or not anchor.strip() for anchor in evidence_ids):
            raise GoldError(f"gold fact {fact_id} has an invalid evidence anchor")
        subject_key = payload.get("subject_key") or f"{kind}:{fact_id}"
        if not isinstance(subject_key, str) or not subject_key.strip():
            raise GoldError(f"gold fact {fact_id} needs a subject key")
        required_terms = tuple(
            str(term).strip()
            for term in (payload.get("required_terms") or ())
            if str(term).strip()
        )
        if not required_terms:
            raise GoldError(f"gold fact {fact_id} needs at least one required term")
        return cls(
            id=fact_id,
            kind=kind,
            subject_key=subject_key,
            value=value,
            evidence_ids=tuple(evidence_ids),
            required_terms=required_terms,
            forbidden_terms=tuple(payload.get("forbidden_terms") or ()),
            note=str(payload.get("note") or ""),
        )


@dataclass(frozen=True)
class GoldQuestion:
    """One handoff question with the evidence a correct answer must rely on."""

    id: str
    scope: str
    question: str
    evidence_ids: tuple[str, ...]
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    accepted_answers: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "question": self.question,
            "evidence_ids": list(self.evidence_ids),
            "required_terms": list(self.required_terms),
            "forbidden_terms": list(self.forbidden_terms),
            "accepted_answers": list(self.accepted_answers),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "GoldQuestion":
        if not isinstance(payload, dict):
            raise GoldError("gold question must be an object")
        question_id = payload.get("id")
        scope = payload.get("scope")
        question = payload.get("question")
        evidence_ids = payload.get("evidence_ids")
        if not isinstance(question_id, str) or not question_id.strip():
            raise GoldError("gold question needs an id")
        if scope not in {"personal", "team"}:
            raise GoldError(f"gold question {question_id} needs scope personal or team")
        if not isinstance(question, str) or not question.strip():
            raise GoldError(f"gold question {question_id} needs a question")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise GoldError(f"gold question {question_id} needs at least one evidence anchor")
        required_terms = tuple(
            str(term).strip()
            for term in (payload.get("required_terms") or ())
            if str(term).strip()
        )
        accepted_answers = tuple(
            str(ans).strip()
            for ans in (payload.get("accepted_answers") or ())
            if str(ans).strip()
        )
        if not required_terms and not accepted_answers:
            raise GoldError(
                f"gold question {question_id} needs at least one required_term or accepted_answer"
            )
        return cls(
            id=question_id,
            scope=scope,
            question=question,
            evidence_ids=tuple(evidence_ids),
            required_terms=required_terms,
            forbidden_terms=tuple(payload.get("forbidden_terms") or ()),
            accepted_answers=accepted_answers,
            note=str(payload.get("note") or ""),
        )


@dataclass(frozen=True)
class GoldSet:
    """Facts and questions that the benchmark scores against."""

    facts: tuple[GoldFact, ...] = ()
    questions: tuple[GoldQuestion, ...] = ()
    meta: dict = field(default_factory=dict)

    def fact_by_id(self, fact_id: str) -> GoldFact | None:
        for fact in self.facts:
            if fact.id == fact_id:
                return fact
        return None

    def questions_for_scope(self, scope: str) -> tuple[GoldQuestion, ...]:
        return tuple(question for question in self.questions if question.scope == scope)

    def to_dict(self) -> dict:
        return {
            "format": GOLD_FORMAT,
            "version": GOLD_VERSION,
            "meta": dict(self.meta),
            "facts": [fact.to_dict() for fact in self.facts],
            "questions": [question.to_dict() for question in self.questions],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "GoldSet":
        if not isinstance(payload, dict):
            raise GoldError("gold set must be an object")
        if payload.get("format") != GOLD_FORMAT:
            raise GoldError("unsupported gold set format")
        if payload.get("version") != GOLD_VERSION:
            raise GoldError("unsupported gold set version")
        facts = payload.get("facts")
        questions = payload.get("questions")
        if not isinstance(facts, list) or not isinstance(questions, list):
            raise GoldError("gold set needs facts and questions lists")
        parsed_facts = tuple(GoldFact.from_dict(item) for item in facts)
        parsed_questions = tuple(GoldQuestion.from_dict(item) for item in questions)
        identifiers = [fact.id for fact in parsed_facts]
        if len(set(identifiers)) != len(identifiers):
            raise GoldError("gold set has duplicate fact ids")
        question_ids = [question.id for question in parsed_questions]
        if len(set(question_ids)) != len(question_ids):
            raise GoldError("gold set has duplicate question ids")
        meta = payload.get("meta") or {}
        if not isinstance(meta, dict):
            raise GoldError("gold set meta must be an object")
        return cls(parsed_facts, parsed_questions, dict(meta))

    @classmethod
    def load(cls, path: str | Path) -> "GoldSet":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GoldError("gold set file could not be read") from exc
        return cls.from_dict(payload)
