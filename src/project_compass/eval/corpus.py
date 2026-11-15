"""Benchmark corpus: de-identified evidence events plus an independent gold set.

The corpus is committed to the repository so the benchmark can run in CI
without reading any private session store. De-identification happens once, at
build time, and the builder records what it replaced so a reviewer can audit
the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re

from ..models import EvidenceEvent
from .gold import GoldError, GoldSet

CORPUS_FORMAT = "project-compass-eval-corpus"
CORPUS_VERSION = 1


class CorpusError(ValueError):
    """Raised when a corpus payload is malformed or inconsistent."""


@dataclass(frozen=True)
class Corpus:
    """A named benchmark corpus."""

    name: str
    events: tuple[EvidenceEvent, ...]
    gold: GoldSet
    meta: dict = field(default_factory=dict)

    def event_by_id(self, event_id: str) -> EvidenceEvent | None:
        for event in self.events:
            if event.id == event_id:
                return event
        return None

    def event_ids(self) -> set[str]:
        return {event.id for event in self.events}


def _event_from_dict(payload: dict) -> EvidenceEvent:
    try:
        return EvidenceEvent.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError("corpus event is malformed") from exc


def load_corpus(path: str | Path) -> Corpus:
    """Load a corpus directory that holds ``events.json`` and ``gold.json``."""
    root = Path(path)
    events_path = root / "events.json"
    gold_path = root / "gold.json"
    try:
        events_payload = json.loads(events_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusError("corpus events file could not be read") from exc
    try:
        gold_payload = json.loads(gold_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusError("corpus gold file could not be read") from exc
    return corpus_from_payload(events_payload, gold_payload)


def corpus_from_payload(events_payload: dict, gold_payload: dict) -> Corpus:
    if not isinstance(events_payload, dict):
        raise CorpusError("corpus events payload must be an object")
    if events_payload.get("format") != CORPUS_FORMAT:
        raise CorpusError("unsupported corpus events format")
    if events_payload.get("version") != CORPUS_VERSION:
        raise CorpusError("unsupported corpus events version")
    raw_events = events_payload.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise CorpusError("corpus needs at least one event")
    events = tuple(_event_from_dict(item) for item in raw_events)
    identifiers = [event.id for event in events]
    if len(set(identifiers)) != len(identifiers):
        raise CorpusError("corpus has duplicate event ids")
    try:
        gold = GoldSet.from_dict(gold_payload)
    except GoldError as exc:
        raise CorpusError(f"corpus gold set is invalid: {exc}") from exc
    known = set(identifiers)
    for fact in gold.facts:
        unknown = [anchor for anchor in fact.evidence_ids if anchor not in known]
        if unknown:
            raise CorpusError(f"gold fact {fact.id} anchors unknown events: {unknown}")
    for question in gold.questions:
        unknown = [anchor for anchor in question.evidence_ids if anchor not in known]
        if unknown:
            raise CorpusError(f"gold question {question.id} anchors unknown events: {unknown}")
    name = events_payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CorpusError("corpus needs a name")
    meta = events_payload.get("meta") or {}
    if not isinstance(meta, dict):
        raise CorpusError("corpus meta must be an object")
    return Corpus(name=name, events=events, gold=gold, meta=dict(meta))


def write_corpus(root: str | Path, corpus: Corpus) -> Path:
    """Write a corpus directory with stable, reviewable JSON."""
    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    events_payload = {
        "format": CORPUS_FORMAT,
        "version": CORPUS_VERSION,
        "name": corpus.name,
        "meta": dict(corpus.meta),
        "events": [event.to_dict() for event in corpus.events],
    }
    (target / "events.json").write_text(
        json.dumps(events_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "gold.json").write_text(
        json.dumps(corpus.gold.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


_HOME_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+"),
    re.compile(r"/(?:home|Users)[^/\s\"']+"),
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:[\\/](?:[^\s\"'<>|]+)")
_URL = re.compile(r"https?://[^\s\"'<>]+")


@dataclass
class Deidentifier:
    """Replace personal identifiers with stable aliases.

    Every substitution is recorded so the corpus build can report what was
    removed instead of silently mutating the source material. One person may
    appear under several labels, so aliases resolve through a canonical name
    instead of producing one member per spelling.
    """

    canonical: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    extra_patterns: list[tuple[re.Pattern, str]] = field(default_factory=list)
    applied: dict[str, int] = field(default_factory=dict)

    def alias(self, label: str, *, same_as: str | None = None) -> str:
        """Return the member alias for ``label``, merging it with ``same_as``."""
        key = label.strip()
        if not key:
            raise CorpusError("alias label must not be empty")
        target = self.canonical.get(key, key)
        if same_as:
            canonical = self.canonical.get(same_as.strip(), same_as.strip())
            self.canonical[key] = canonical
            target = canonical
        self.canonical.setdefault(key, target)
        self.canonical.setdefault(target, target)
        if target not in self.aliases:
            self.aliases[target] = f"member-{len(self.aliases) + 1}"
        return self.aliases[target]

    def add_pattern(self, pattern: str, replacement: str) -> None:
        self.extra_patterns.append((re.compile(pattern), replacement))

    def register_labels(self, mapping: dict[str, str]) -> None:
        """Declare every spelling of every person and pre-issue aliases.

        Pre-issuing aliases ensures that a person mentioned in body text before
        authoring any entry (or never authoring one) is still de-identified.
        """
        for label, canonical in mapping.items():
            key = str(label).strip()
            target = str(canonical).strip()
            if not key or not target:
                continue
            self.alias(key, same_as=target)

    def _record(self, key: str) -> None:
        self.applied[key] = self.applied.get(key, 0) + 1

    def text(self, value: str) -> str:
        result = value
        ordered = sorted(self.canonical.items(), key=lambda item: -len(item[0]))
        for original, target in ordered:
            alias = self.aliases.get(target)
            if not alias or not original:
                continue
            replaced, count = self._replace_alias(result, original, alias)
            if count:
                result = replaced
                self._record(f"alias:{original}")
        for pattern, replacement in self.extra_patterns:
            result, count = pattern.subn(replacement, result)
            if count:
                self._record(f"pattern:{pattern.pattern}")
        for pattern in _HOME_PATTERNS:
            result, count = pattern.subn("<home>", result)
            if count:
                self._record("home-path")
        result, count = _EMAIL.subn("<email>", result)
        if count:
            self._record("email")
        result, count = _URL.subn("<url>", result)
        if count:
            self._record("url")
        result, count = _ABSOLUTE_PATH.subn("<path>", result)
        if count:
            self._record("absolute-path")
        return result

    @staticmethod
    def _replace_alias(text: str, original: str, alias: str) -> tuple[str, int]:
        """Replace one alias, matching whole words only for ASCII labels.

        A bare ``str.replace`` would turn ``Fang`` inside ``Fangwei`` into
        ``member-2wei``. Word boundaries keep the substitution exact; labels
        written in Chinese have no word boundary, so they stay a plain
        replacement.
        """
        if original.isascii():
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(original)}(?![A-Za-z0-9_])")
            return pattern.subn(alias, text)
        return text.replace(original, alias), text.count(original)

    def report(self) -> dict:
        """Full audit trail, including the real names. Never commit this."""
        return {
            "aliases": dict(self.aliases),
            "labels": dict(sorted(self.canonical.items())),
            "replacements": dict(sorted(self.applied.items())),
            "total_replacements": sum(self.applied.values()),
        }

    def summary(self) -> dict:
        """Audit trail that is safe to commit.

        The real names never appear here: alias replacements are counted per
        member alias and pattern replacements per pattern category, so a
        reviewer can still verify that de-identification ran and how much it
        touched without learning who the people are.
        """
        by_alias: dict[str, int] = {}
        by_pattern: dict[str, int] = {}
        for key, count in self.applied.items():
            if key.startswith("alias:"):
                target = self.canonical.get(key.split(":", 1)[1], "")
                alias = self.aliases.get(target, "member-?")
                by_alias[alias] = by_alias.get(alias, 0) + count
            else:
                by_pattern[key] = by_pattern.get(key, 0) + count
        return {
            "member_count": len(self.aliases),
            "member_aliases": dict(sorted(by_alias.items())),
            "pattern_replacements": dict(sorted(by_pattern.items())),
            "total_replacements": sum(self.applied.values()),
        }


def build_event(
    event_id: str,
    session_id: str,
    author: str,
    kind: str,
    content: str,
    observed_at: datetime,
    metadata: dict,
) -> EvidenceEvent:
    """Create one corpus event with a bounded, explicit metadata contract."""
    if not isinstance(event_id, str) or not event_id.strip():
        raise CorpusError("event id must be a non-empty string")
    if not isinstance(content, str):
        raise CorpusError("event content must be a string")
    if not isinstance(metadata, dict):
        raise CorpusError("event metadata must be an object")
    return EvidenceEvent(
        id=event_id,
        session_id=session_id,
        author=author,
        kind=kind,
        content=content,
        observed_at=observed_at,
        metadata=dict(metadata),
    )
