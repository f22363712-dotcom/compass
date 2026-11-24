from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
import json
from typing import Protocol
from .evidence_filters import as_utc_timestamp, is_platform_control, is_public_raw_event, parse_iso_timestamp
from .native_command_trace import CAPTURE as NATIVE_COMMAND_CAPTURE

from .models import (
    CandidateFact,
    EvidenceCatalogEntry,
    EvidenceEvent,
    EvidenceRelation,
    EvidenceRelationMethod,
    EvidenceRelationStatus,
    FactKind,
)


@dataclass(frozen=True)
class RelationSuggestion:
    method: EvidenceRelationMethod
    score: float | None
    basis: str


class RelationProvider(Protocol):
    def suggest(self, fact: CandidateFact, evidence: EvidenceEvent) -> RelationSuggestion | None:
        """Return a bounded suggestion for an eligible fact/evidence pair."""


class DeterministicLinkProvider:
    """Offline, auditable relation suggestions used by default."""

    def suggest(
        self,
        fact: CandidateFact,
        evidence: EvidenceEvent,
        *,
        explicit_ids: set[str] | None = None,
        content_folded: str | None = None,
        value_folded: str | None = None,
    ) -> RelationSuggestion | None:
        resolved_explicit = _explicit_ids(evidence) if explicit_ids is None else explicit_ids
        if fact.id in resolved_explicit or evidence.id in fact.evidence_ids:
            return RelationSuggestion(EvidenceRelationMethod.EXPLICIT, 1.0, "explicit-reference")

        value = fact.value
        if value:
            needle = value.casefold() if value_folded is None else value_folded
            haystack = evidence.content.casefold() if content_folded is None else content_folded
            if needle in haystack:
                return RelationSuggestion(EvidenceRelationMethod.DETERMINISTIC, 0.9, "exact-text-match")

        if evidence.kind in {"test_result", "tool_result"} and fact.kind is FactKind.TASK:
            if evidence.author == fact.author and evidence.session_id == fact.session_id:
                return RelationSuggestion(EvidenceRelationMethod.DETERMINISTIC, 0.45, "same-session-result")
        return None


@dataclass(frozen=True)
class EvidenceIndex:
    catalog: tuple[EvidenceCatalogEntry, ...]
    candidate_relations: tuple[EvidenceRelation, ...]
    confirmed_relations: tuple[EvidenceRelation, ...] = ()

    @property
    def catalog_by_id(self) -> dict[str, EvidenceCatalogEntry]:
        return {entry.id: entry for entry in self.catalog}

    def with_confirmed(self, relation: EvidenceRelation) -> "EvidenceIndex":
        if relation.status is not EvidenceRelationStatus.CONFIRMED:
            raise ValueError("confirmed index entries must have confirmed status")
        candidate_id = relation.id.removesuffix(":confirmed")
        candidates = {candidate.id: candidate for candidate in self.candidate_relations}
        if candidate_id not in candidates:
            raise ValueError("confirmed relation must be copied from a candidate in this index")
        candidate = candidates[candidate_id]
        if relation.id != candidate.id + ":confirmed":
            raise ValueError("confirmed relation id must be derived from the candidate id")
        if relation.method is not EvidenceRelationMethod.HUMAN or not relation.reviewed_by:
            raise ValueError("confirmed relation must include a human reviewer")
        if (
            relation.fact_id != candidate.fact_id
            or relation.evidence_id != candidate.evidence_id
            or relation.relation != candidate.relation
            or relation.score != candidate.score
            or relation.basis != candidate.basis
        ):
            raise ValueError("confirmed relation must preserve the candidate relation fields")
        if any(existing.id == relation.id for existing in self.confirmed_relations):
            raise ValueError("confirmed relation already exists")
        catalog = tuple(
            replace(
                entry,
                confirmed_fact_ids=tuple(sorted(set(entry.confirmed_fact_ids) | ({relation.fact_id} if entry.id == relation.evidence_id else set()))),
            )
            for entry in self.catalog
        )
        return EvidenceIndex(catalog, self.candidate_relations, self.confirmed_relations + (relation,))

    def with_candidate_relations(self, relations: list[EvidenceRelation] | tuple[EvidenceRelation, ...]) -> "EvidenceIndex":
        existing = {candidate.id for candidate in self.candidate_relations}
        additions = tuple(relation for relation in relations if relation.id not in existing)
        if not additions:
            return self
        candidate_by_evidence: dict[str, set[str]] = {}
        for relation in additions:
            candidate_by_evidence.setdefault(relation.evidence_id, set()).add(relation.fact_id)
        catalog = tuple(
            replace(entry, candidate_fact_ids=tuple(sorted(set(entry.candidate_fact_ids) | candidate_by_evidence.get(entry.id, set()))))
            for entry in self.catalog
        )
        return EvidenceIndex(catalog, self.candidate_relations + additions, self.confirmed_relations)

    def with_confirmed_relations(self, relations: list[EvidenceRelation] | tuple[EvidenceRelation, ...]) -> "EvidenceIndex":
        updated = self
        for relation in relations:
            if any(existing.id == relation.id for existing in updated.confirmed_relations):
                continue
            try:
                updated = updated.with_confirmed(relation)
            except ValueError:
                # A rescan can leave a historical confirmation without its old candidate.
                # Keep the audit record, but do not project stale state into the current board.
                continue
        return updated

    def to_dict(self) -> dict[str, list[dict]]:
        return {
            "evidence": [entry.to_dict() for entry in self.catalog],
            "candidate_relations": [relation.to_dict() for relation in self.candidate_relations],
            "confirmed_relations": [relation.to_dict() for relation in self.confirmed_relations],
        }


def _classification(event: EvidenceEvent) -> str:
    if event.metadata.get("facts"):
        return "fact_source"
    if event.kind == "test_result":
        return "test_result"
    if event.kind in {"tool_result", "tool_call", "command_execution"}:
        return "execution_result"
    if event.kind == "git_commit":
        return "change"
    return "unclassified"


def _preview(content: str, limit: int = 240) -> str:
    compact = " ".join(content.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def command_context(event):
    if event.kind not in {'command_execution', 'tool_call', 'tool_result', 'test_result'}:
        return {}
    command = event.metadata.get('command')
    if isinstance(command, str):
        text = command
    elif isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        text = json.dumps(command, ensure_ascii=False)
    else:
        return {}
    if not text.strip():
        return {}
    if len(text) > 1600:
        text = text[:800] + ' … ' + text[-797:]
    meta = event.metadata
    agent = meta.get('actor_type') == 'agent' or meta.get('origin') == 'agent_submission' or meta.get('capture') == 'agent-http-v1'
    origin = 'agent_report' if agent else 'native_trace' if event.kind == 'command_execution' and meta.get('capture') == NATIVE_COMMAND_CAPTURE else 'reported'
    return {'command_preview': text, 'command_origin': origin,
            'exit_code': meta.get('exit_code') if type(meta.get('exit_code')) is int else None}


def _explicit_ids(event: EvidenceEvent) -> set[str]:
    values: set[str] = set()
    for key in ("supports_fact_ids", "fact_refs"):
        raw = event.metadata.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple, set)):
            values.update(str(item) for item in raw)
    return values


def _eligible_pairs(events: list[EvidenceEvent], facts: list[CandidateFact]) -> list[tuple[CandidateFact, EvidenceEvent]]:
    from bisect import bisect_right
    from collections import defaultdict

    pairs: list[tuple[CandidateFact, EvidenceEvent]] = []
    if not events or not facts:
        return pairs
    events_by_id: dict[str, EvidenceEvent] = {}
    indices_by_id: dict[str, list[int]] = defaultdict(list)
    explicit_by_fact: dict[str, list[int]] = defaultdict(list)
    contents: list[str] = []
    for idx, event in enumerate(events):
        events_by_id[event.id] = event
        indices_by_id[event.id].append(idx)
        for fid in _explicit_ids(event):
            explicit_by_fact[fid].append(idx)
        contents.append(event.content.casefold())

    sessions = [
        fact.session_id
        or next(
            (events_by_id[source_id].session_id for source_id in fact.evidence_ids if source_id in events_by_id),
            None,
        )
        for fact in facts
    ]
    task_counts = Counter((fact.author, session) for fact, session in zip(facts, sessions) if fact.kind is FactKind.TASK)
    single_task_results: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    for idx, event in enumerate(events):
        if event.kind in {"test_result", "tool_result"} and task_counts[event.author, event.session_id] == 1:
            single_task_results[(event.author, event.session_id)].append(idx)

    # Per-read preparation preserves input order and duplicate entries. No state
    # survives this call, so changed source text/metadata cannot reuse old matches.
    sep = "\0"
    joined_corpus = sep.join(contents)
    end_offsets: list[int] = []
    cursor = 0
    for content in contents:
        cursor += len(content)
        end_offsets.append(cursor)
        cursor += 1
    needle_cache: dict[str, tuple[int, ...]] = {}

    def _needle_indices(needle: str) -> tuple[int, ...]:
        cached = needle_cache.get(needle)
        if cached is not None:
            return cached
        if not needle:
            matched: tuple[int, ...] = ()
        elif sep in needle:
            matched = tuple(idx for idx, content in enumerate(contents) if needle in content)
        else:
            hits: list[int] = []
            pos = joined_corpus.find(needle)
            while pos != -1:
                ev_idx = bisect_right(end_offsets, pos)
                hits.append(ev_idx)
                pos = joined_corpus.find(needle, end_offsets[ev_idx] + 1)
            matched = tuple(hits)
        needle_cache[needle] = matched
        return matched

    for fact, fact_session in zip(facts, sessions):
        needle = fact.value.casefold() if fact.value else ""
        matching_fact = replace(fact, session_id=fact_session) if fact.session_id is None else fact
        candidate_indices: set[int] = set()
        for source_id in fact.evidence_ids:
            candidate_indices.update(indices_by_id.get(source_id, ()))
        candidate_indices.update(explicit_by_fact.get(fact.id, ()))
        if fact.kind is FactKind.TASK:
            candidate_indices.update(single_task_results.get((fact.author, fact_session), ()))
        if needle:
            candidate_indices.update(_needle_indices(needle))
        for ev_idx in sorted(candidate_indices):
            pairs.append((matching_fact, events[ev_idx]))
    return pairs


def build_evidence_index(
    events: list[EvidenceEvent],
    facts: list[CandidateFact] | None = None,
    provider: RelationProvider | None = None,
) -> EvidenceIndex:
    from .fact_engine import derive_facts

    facts = list(facts) if facts is not None else derive_facts(events)
    events = [event for event in events if is_public_raw_event(event)]
    deterministic = DeterministicLinkProvider()
    selected_provider = provider or deterministic
    relations: list[EvidenceRelation] = []
    relation_keys: set[tuple[str, str]] = set()
    explicit_by_ev: dict[int, set[str]] = {}
    folded_by_ev: dict[int, str] = {}
    folded_by_fact: dict[int, str] = {}
    for fact, event in _eligible_pairs(events, facts):
        ev_key = id(event)
        ev_explicit = explicit_by_ev.get(ev_key)
        if ev_explicit is None:
            ev_explicit = _explicit_ids(event)
            explicit_by_ev[ev_key] = ev_explicit
        ev_folded = folded_by_ev.get(ev_key)
        if ev_folded is None:
            ev_folded = event.content.casefold()
            folded_by_ev[ev_key] = ev_folded
        fact_key = id(fact)
        val_folded = folded_by_fact.get(fact_key)
        if val_folded is None:
            val_folded = fact.value.casefold() if fact.value else ""
            folded_by_fact[fact_key] = val_folded
        fallback = deterministic.suggest(
            fact,
            event,
            explicit_ids=ev_explicit,
            content_folded=ev_folded,
            value_folded=val_folded,
        )
        if fallback is None:
            continue
        suggestion = fallback if selected_provider is deterministic else (selected_provider.suggest(fact, event) or fallback)
        key = (fact.id, event.id)
        if key in relation_keys:
            continue
        relation_keys.add(key)
        relations.append(EvidenceRelation(
            id=f"relation-{fact.id}-{event.id}",
            fact_id=fact.id,
            evidence_id=event.id,
            relation="supports",
            status=EvidenceRelationStatus.CANDIDATE,
            method=suggestion.method,
            score=suggestion.score,
            basis=suggestion.basis,
        ))

    candidate_links: dict[str, list[str]] = {event.id: [] for event in events}
    for relation in relations:
        candidate_links.setdefault(relation.evidence_id, []).append(relation.fact_id)
    catalog = tuple(
        EvidenceCatalogEntry(
            id=event.id,
            kind=event.kind,
            author=event.author,
            observed_at=event.observed_at,
            source_ref=event.metadata.get("source_ref"),
            content_preview=_preview((command.get('command_preview', '') + '\n' + event.content) if event.kind == 'command_execution' else event.content),
            candidate_fact_ids=tuple(sorted(set(candidate_links.get(event.id, [])))),
            confirmed_fact_ids=(),
            classification=_classification(event),
            **command,
        )
        for event, command in ((event, command_context(event)) for event in events)
    )
    return EvidenceIndex(catalog, tuple(relations))


def build_requested_evidence_relations(events: list[EvidenceEvent], facts: list[CandidateFact], review_history=()) -> tuple[EvidenceRelation, ...]:
    """Create bounded candidate links for material that arrived after an owner request."""
    latest = {}
    for review in review_history:
        fact_id = review.get("fact_id")
        if not fact_id:
            continue
        fact_id = str(fact_id)
        if review.get("action") == "request_evidence":
            latest[fact_id] = review
        elif review.get("action") in {"accept_fact", "reject_fact"}:
            latest.pop(fact_id, None)
    by_id = {fact.id: fact for fact in facts}
    relations = []
    for fact_id, review in latest.items():
        if review.get("action") != "request_evidence" or fact_id not in by_id:
            continue
        requested_at = review.get("observed_at")
        try:
            requested_time = as_utc_timestamp(requested_at) if requested_at else None
        except (TypeError, ValueError):
            requested_time = None
        if requested_time is None:
            continue
        original_ids = set(review.get("evidence_ids") or by_id[fact_id].evidence_ids)
        for event in events:
            if event.id in original_ids or as_utc_timestamp(event.observed_at) <= requested_time or not is_public_raw_event(event):
                continue
            relations.append(EvidenceRelation(
                id=f"relation-{fact_id}-{event.id}-requested",
                fact_id=fact_id,
                evidence_id=event.id,
                relation="supports",
                status=EvidenceRelationStatus.CANDIDATE,
                method=EvidenceRelationMethod.DETERMINISTIC,
                score=None,
                basis="requested-evidence",
            ))
    return tuple(relations)


def confirm_relation(relation: EvidenceRelation, reviewer: str) -> EvidenceRelation:
    if relation.status is not EvidenceRelationStatus.CANDIDATE:
        raise ValueError("only candidate relations can be confirmed")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    return EvidenceRelation(
        id=relation.id + ":confirmed",
        fact_id=relation.fact_id,
        evidence_id=relation.evidence_id,
        relation=relation.relation,
        status=EvidenceRelationStatus.CONFIRMED,
        method=EvidenceRelationMethod.HUMAN,
        score=relation.score,
        basis=relation.basis,
        reviewed_by=reviewer,
    )
