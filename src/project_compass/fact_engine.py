from __future__ import annotations

from collections import defaultdict
from hashlib import sha1

from .models import CandidateFact, EvidenceEvent, FactKind, FactStatus
from .candidate_extraction import source_claim_type


def validate_partial_quote(source_text: str, streaming_chunk: str, current_offset: int) -> dict:
    """Validate one streamed quote chunk against ``source_text`` starting at ``current_offset``.

    Chaining chunks by feeding back ``next_offset`` is equivalent to the full
    ``source_text[start:end] == quote`` check, but fails at the first diverging character.
    """
    if not isinstance(source_text, str) or not isinstance(streaming_chunk, str):
        raise TypeError("source_text and streaming_chunk must be str")
    if isinstance(current_offset, bool) or not isinstance(current_offset, int):
        raise TypeError("current_offset must be int")
    if current_offset < 0 or current_offset > len(source_text):
        return {"valid": False, "matched": 0, "next_offset": current_offset, "reason": "offset_out_of_range"}
    window = source_text[current_offset:current_offset + len(streaming_chunk)]
    matched = 0
    for expected, actual in zip(window, streaming_chunk):
        if expected != actual:
            break
        matched += 1
    valid = matched == len(streaming_chunk)
    reason = None if valid else ("beyond_source_end" if matched == len(window) else "mismatch")
    return {"valid": valid, "matched": matched, "next_offset": current_offset + matched, "reason": reason}


class StreamingQuoteValidator:
    """Stateful accumulator for streaming LLM tokens against a known source text."""

    def __init__(self, source_text: str, start_offset: int = 0):
        if not isinstance(source_text, str):
            raise TypeError("source_text must be str")
        if isinstance(start_offset, bool) or not isinstance(start_offset, int) or start_offset < 0 or start_offset > len(source_text):
            raise ValueError("start_offset out of bounds")
        self.source_text = source_text
        self.start_offset = start_offset
        self.current_offset = start_offset
        self.accumulated_quote = ""
        self.is_valid = True
        self.failure_reason = None

    def feed_chunk(self, chunk: str) -> dict:
        """Feed a new streaming chunk of text."""
        if not self.is_valid:
            return {
                "valid": False,
                "current_offset": self.current_offset,
                "accumulated_quote": self.accumulated_quote,
                "reason": self.failure_reason or "already_invalidated",
                "span": (self.start_offset, self.current_offset),
            }
        result = validate_partial_quote(self.source_text, chunk, self.current_offset)
        self.accumulated_quote += chunk[:result["matched"]]
        self.current_offset = result["next_offset"]
        if not result["valid"]:
            self.is_valid = False
            self.failure_reason = result["reason"]
        return {
            "valid": self.is_valid,
            "matched": result["matched"],
            "current_offset": self.current_offset,
            "accumulated_quote": self.accumulated_quote,
            "reason": self.failure_reason,
            "span": (self.start_offset, self.current_offset),
        }

    def verify_exact_span(self, expected_quote: str) -> bool:
        """Verify that accumulated text matches expected quote and exactly matches source slice."""
        return (
            self.is_valid
            and self.accumulated_quote == expected_quote
            and self.source_text[self.start_offset:self.current_offset] == expected_quote
        )


def derive_facts(
    events: list[EvidenceEvent],
    *,
    strict: bool = True,
    warnings_out: list[str] | None = None,
) -> list[CandidateFact]:
    raw: list[CandidateFact] = []
    sources = {event.id: event for event in events if event.kind != "fact_proposal"}
    for event in events:
        facts_meta = event.metadata.get("facts")
        if facts_meta is None:
            facts_meta = []
        elif not isinstance(facts_meta, list):
            if strict:
                raise ValueError("invalid persisted facts metadata")
            if warnings_out is not None:
                warnings_out.append(f"skipped non-list facts metadata on event={event.id}")
            continue
        for index, item in enumerate(facts_meta):
            if not isinstance(item, dict):
                if strict:
                    raise ValueError("invalid persisted fact item")
                if warnings_out is not None:
                    warnings_out.append(f"skipped non-dict fact item on event={event.id} index={index}")
                continue
            source = event
            if event.kind == "fact_proposal":
                source = sources.get(item.get("source_id"))
                quote = item.get("quote")
                start, end = item.get("source_start"), item.get("source_end")
                valid_span = (
                    isinstance(start, int)
                    and not isinstance(start, bool)
                    and isinstance(end, int)
                    and not isinstance(end, bool)
                    and 0 <= start <= end
                    and source is not None
                    and end <= len(source.content)
                )
                if not valid_span or not isinstance(quote, str) or not quote.strip() or source.content[start:end] != quote or item.get("value") != quote:
                    if strict:
                        raise ValueError("invalid persisted proposal source span")
                    if warnings_out is not None:
                        warnings_out.append(f"skipped invalid proposal span on event={event.id} index={index}")
                    continue
            try:
                kind = FactKind(item["kind"])
                subject_key = item["subject_key"]
                raw_value = item["value"]
            except (KeyError, TypeError, ValueError):
                if strict:
                    raise
                if warnings_out is not None:
                    warnings_out.append(f"skipped invalid persisted fact on event={event.id} index={index}")
                continue
            if not isinstance(subject_key, str) or not subject_key:
                if strict:
                    raise ValueError("invalid persisted fact subject_key")
                if warnings_out is not None:
                    warnings_out.append(f"skipped invalid persisted fact on event={event.id} index={index}")
                continue
            value = str(raw_value)
            if "status" in item:
                value = f"{value} [{item['status']}]"
            digest = sha1(f"{event.id}:{index}".encode(), usedforsecurity=False).hexdigest()[:10]
            raw.append(CandidateFact(
                id=f"fact-{digest}", kind=kind, subject_key=subject_key,
                value=value, status=FactStatus.PROPOSED, evidence_ids=(source.id,),
                author=str(event.metadata.get("member_id") or source.metadata.get("member_id") or source.author), observed_at=source.observed_at, session_id=source.session_id,
                quote=item.get("quote"), source_ref=source.metadata.get("source_ref"),
                claim_type=source_claim_type(source) if event.kind == "fact_proposal" else item.get("claim_type"), reported_by=source.author, task_state=item.get("task_state"),
            ))
    by_subject: dict[str, list[CandidateFact]] = defaultdict(list)
    for fact in raw:
        by_subject[fact.subject_key].append(fact)
    result: list[CandidateFact] = []
    for fact in raw:
        values = {candidate.value for candidate in by_subject[fact.subject_key]}
        status = FactStatus.CONFLICTED if len(values) > 1 else fact.status
        result.append(CandidateFact(**{**fact.__dict__, "status": status}))
    return result
