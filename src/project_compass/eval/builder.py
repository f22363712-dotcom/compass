"""Build a benchmark corpus from an authored specification.

The specification names facts and questions that a human believes the product
should find, anchored to distinctive text in the real source material. The
builder resolves every anchor against the raw source and fails loudly when an
anchor cannot be found, so a gold set can never drift away from reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from ..limits import MAX_ANCHORS_PER_ITEM
from .adapters import AdapterError, ConversationEntry, conversation_events, parse_sync_conversation
from .corpus import Corpus, Deidentifier
from .gold import GoldFact, GoldQuestion, GoldSet


class BuildError(ValueError):
    """Raised when a specification cannot be turned into a corpus."""


@dataclass(frozen=True)
class BuildResult:
    corpus: Corpus
    deidentification: dict
    anchor_report: dict
    summary: dict = field(default_factory=dict)


def _resolve_anchors(
    anchors,
    entries: list[ConversationEntry],
    events,
) -> list[str]:
    if not isinstance(anchors, list) or not anchors:
        raise BuildError("every gold item needs at least one anchor")
    resolved: list[str] = []
    for anchor in anchors:
        if not isinstance(anchor, str) or not anchor.strip():
            raise BuildError("anchor must be a non-empty string")
        needle = anchor.strip()
        hits = [
            index for index, entry in enumerate(entries) if needle in entry.raw
        ]
        if not hits:
            raise BuildError(f"anchor not found in the source material: {needle!r}")
        if len(hits) > MAX_ANCHORS_PER_ITEM:
            raise BuildError(
                f"anchor {needle!r} matches {len(hits)} entries; use a more specific anchor"
            )
        for index in hits:
            if needle not in events[index].content:
                raise BuildError(
                    f"anchor {needle!r} is not part of the de-identified corpus; "
                    "an anchor must not carry personal text that de-identification removed"
                )
            event_id = events[index].id
            if event_id not in resolved:
                resolved.append(event_id)
    return resolved


def _validate_terms(terms, evidence_ids, events_by_id, label: str) -> None:
    """Require every required term to exist in the anchored source text."""
    if not isinstance(terms, list):
        raise BuildError(f"{label} required_terms must be a list")
    corpus_text = "\n".join(events_by_id[evidence_id].content for evidence_id in evidence_ids)
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise BuildError(f"{label} required term must be a non-empty string")
        if term not in corpus_text:
            raise BuildError(
                f"{label} requires the term {term!r}, which does not appear in the anchored source"
            )


def build_corpus_from_spec(spec: dict, *, source_root: str | Path) -> BuildResult:
    """Turn an authored specification into a de-identified benchmark corpus."""
    if not isinstance(spec, dict):
        raise BuildError("specification must be an object")
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BuildError("specification needs a name")
    sources = spec.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise BuildError("specification needs at least one source")
    root = Path(source_root)
    conversation_rel = sources.get("conversation")
    if not isinstance(conversation_rel, str) or not conversation_rel.strip():
        raise BuildError("specification needs a conversation source")
    conversation_path = root / conversation_rel
    try:
        text = conversation_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"conversation source could not be read: {conversation_path}") from exc
    try:
        entries = parse_sync_conversation(text)
    except AdapterError as exc:
        raise BuildError(str(exc)) from exc

    deidentifier = Deidentifier()
    member_aliases = spec.get("member_aliases") or {}
    if not isinstance(member_aliases, dict):
        raise BuildError("member_aliases must be an object")
    deidentifier.register_labels(member_aliases)
    events = conversation_events(
        entries,
        deidentifier=deidentifier,
        source_ref=conversation_rel,
        member_aliases=member_aliases,
    )
    if len({event.id for event in events}) != len(events):
        raise BuildError("conversation entries produced duplicate event ids")

    events_by_id = {event.id: event for event in events}
    facts: list[GoldFact] = []
    for item in spec.get("facts") or []:
        if not isinstance(item, dict):
            raise BuildError("each gold fact specification must be an object")
        fact_id = item.get("id")
        if not isinstance(fact_id, str) or not fact_id.strip():
            raise BuildError("gold fact specification needs an id")
        anchors = _resolve_anchors(item.get("anchors"), entries, events)
        _validate_terms(item.get("required_terms") or (), anchors, events_by_id, f"gold fact {fact_id}")
        facts.append(
            GoldFact(
                id=fact_id,
                kind=item.get("kind"),
                subject_key=item.get("subject_key") or f"{item.get('kind')}:{fact_id}",
                value=item.get("value"),
                evidence_ids=tuple(anchors),
                required_terms=tuple(item.get("required_terms") or ()),
                forbidden_terms=tuple(item.get("forbidden_terms") or ()),
                note=str(item.get("note") or ""),
            )
        )

    questions: list[GoldQuestion] = []
    for item in spec.get("questions") or []:
        if not isinstance(item, dict):
            raise BuildError("each gold question specification must be an object")
        question_id = item.get("id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise BuildError("gold question specification needs an id")
        anchors = _resolve_anchors(item.get("anchors"), entries, events)
        _validate_terms(item.get("required_terms") or (), anchors, events_by_id, f"gold question {question_id}")
        questions.append(
            GoldQuestion(
                id=question_id,
                scope=item.get("scope"),
                question=item.get("question"),
                evidence_ids=tuple(anchors),
                required_terms=tuple(item.get("required_terms") or ()),
                forbidden_terms=tuple(item.get("forbidden_terms") or ()),
                accepted_answers=tuple(item.get("accepted_answers") or ()),
                note=str(item.get("note") or ""),
            )
        )

    gold = GoldSet(
        facts=tuple(facts),
        questions=tuple(questions),
        meta={
            "conversation_source": conversation_rel,
            "entry_count": len(entries),
            "member_count": len(deidentifier.aliases),
            "agent_names": sorted({entry.agent for entry in entries if entry.agent}),
            "gold_note": str(spec.get("gold_note") or ""),
        },
    )
    corpus = Corpus(
        name=name,
        events=tuple(events),
        gold=gold,
        meta={
            "conversation_source": conversation_rel,
            "entry_count": len(entries),
            "member_count": len(deidentifier.aliases),
        },
    )
    anchor_report = {
        "facts": len(facts),
        "questions": len(questions),
        "entries": len(entries),
        "events": len(events),
    }
    return BuildResult(
        corpus=corpus,
        deidentification=deidentifier.report(),
        anchor_report=anchor_report,
        summary=deidentifier.summary(),
    )


def load_spec(path: str | Path) -> dict:
    """Read an authored corpus specification."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError("corpus specification could not be read") from exc
    if not isinstance(payload, dict):
        raise BuildError("corpus specification must be an object")
    return payload
