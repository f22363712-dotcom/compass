"""Deterministic adapters that turn real project material into corpus events.

The adapters preserve the source text byte for byte inside every event so an
exact-quote rule can still find its source span. Only the de-identification
step is allowed to rewrite text, and it is recorded in the build report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import re
from typing import Iterable

from ..evidence_filters import parse_iso_timestamp
from ..models import EvidenceEvent
from .corpus import Deidentifier

SYNC_HEADER = re.compile(r"^##\s+\[(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})\]\s*(?P<rest>.+?)\s*$")
SECTION = re.compile(r"^-\s+(?P<label>[^：\[\]()*<>]{1,24})：\s*(?P<value>.*)$")
SECTION_ASCII = re.compile(r"^-\s+(?P<label>[^:\[\]()*<>]{1,24}):(?!\/\/)\s*(?P<value>.*)$")
AGENT_SUFFIX = re.compile(r"[·・]\s*agent\s*=\s*(?P<agent>[A-Za-z0-9_.-]+)\s*$")


class AdapterError(ValueError):
    """Raised when source material cannot be parsed into a bounded structure."""


@dataclass(frozen=True)
class ConversationEntry:
    """One dated, authored entry of an append-only collaboration log."""

    index: int
    timestamp: datetime
    member_label: str
    agent: str
    sections: tuple[tuple[str, str], ...]
    raw: str

    def section(self, label: str) -> str:
        for name, value in self.sections:
            if name == label:
                return value
        return ""

    def labels(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.sections)


def _parse_timestamp(value: str) -> datetime:
    try:
        return parse_iso_timestamp(value, default_tz=timezone.utc)
    except ValueError as exc:
        raise AdapterError(f"invalid entry timestamp: {value}") from exc


def _split_member(rest: str) -> tuple[str, str]:
    match = AGENT_SUFFIX.search(rest)
    if match:
        return rest[: match.start()].strip(" ·・-"), match.group("agent")
    return rest.strip(), ""


def parse_sync_conversation(text: str) -> list[ConversationEntry]:
    """Parse an append-only sync log whose entries use ``## [time] member · agent=X``."""
    if not isinstance(text, str):
        raise AdapterError("conversation source must be a string")
    entries: list[ConversationEntry] = []
    current: dict | None = None
    lines = text.splitlines()

    def flush() -> None:
        if current is None:
            return
        body_lines: list[str] = []
        sections: list[tuple[str, str]] = []
        active: list[str] | None = None
        for line in current["body"]:
            if not line.strip():
                continue
            match = SECTION.match(line) or SECTION_ASCII.match(line)
            if match and not line.startswith((" ", "\t")):
                label = match.group("label").strip()
                value = match.group("value").strip()
                sections.append((label, value))
                active = [value]
                body_lines.append(line)
                continue
            if active is not None:
                active.append(line.strip())
                body_lines.append(line)
                continue
            body_lines.append(line)
        merged = tuple((label, "\n".join(value).strip()) for label, value in sections)
        raw = "\n".join([current["header"]] + body_lines).strip()
        entries.append(
            ConversationEntry(
                index=len(entries),
                timestamp=_parse_timestamp(current["timestamp"]),
                member_label=current["member"],
                agent=current["agent"],
                sections=merged,
                raw=raw,
            )
        )

    for line in lines:
        header = SYNC_HEADER.match(line)
        if header:
            flush()
            member, agent = _split_member(header.group("rest"))
            current = {
                "timestamp": header.group("timestamp"),
                "member": member,
                "agent": agent,
                "header": line,
                "body": [],
            }
            continue
        if current is not None:
            current["body"].append(line)
    flush()
    if not entries:
        raise AdapterError("no dated entries were found in the conversation source")
    return entries


def _event_id(prefix: str, session_id: str, index: int, content: str) -> str:
    digest = sha1(f"{session_id}:{index}:{content}".encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}-{digest}"


def conversation_events(
    entries: Iterable[ConversationEntry],
    *,
    deidentifier: Deidentifier,
    source_ref: str,
    session_prefix: str = "sync",
    member_aliases: dict[str, str] | None = None,
) -> list[EvidenceEvent]:
    """Convert parsed entries into corpus events with de-identified content.

    ``member_aliases`` maps every spelling of a person to one canonical name so
    a member who signed entries under two labels keeps a single identity.
    """
    aliases = member_aliases or {}
    entry_list = list(entries)
    resolved_members: list[str] = []
    for entry in entry_list:
        canonical = aliases.get(entry.member_label, entry.member_label)
        resolved_members.append(deidentifier.alias(entry.member_label, same_as=canonical))

    events: list[EvidenceEvent] = []
    for entry, member in zip(entry_list, resolved_members):
        content = deidentifier.text(entry.raw)
        session_id = f"{session_prefix}-{member}"
        events.append(
            EvidenceEvent(
                id=_event_id("conv", session_id, entry.index, content),
                session_id=session_id,
                author=member,
                kind="assistant_message",
                content=content,
                observed_at=entry.timestamp,
                metadata={
                    "member_id": member,
                    "role": "assistant",
                    "agent": deidentifier.text(entry.agent),
                    "source_ref": source_ref,
                    "entry_index": entry.index,
                    "sections": [deidentifier.text(label) for label in entry.labels()],
                    "relayed_user_request": "用户诉求" in entry.labels(),
                    "derivation": "eval-sync-conversation-v1",
                },
            )
        )
    return events
