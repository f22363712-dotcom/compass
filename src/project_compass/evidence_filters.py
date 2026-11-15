"""Shared content filters, timestamp parsing, member attribution, and atomic IO."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from pathlib import Path
import re
import threading
import time
from typing import Any
import unicodedata

SENSITIVE = re.compile(
    r"配对码|API.?KEY|Bearer\s|sk-[A-Za-z0-9]|密码|私钥|<environment_context>|<system-reminder>"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:Authorization|Cookie|Set-Cookie)\s*[:=]"
    r"|(?<![A-Z0-9_])(?:AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|AWS_SESSION_TOKEN|GITHUB_TOKEN|GH_TOKEN"
    r"|[A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|ACCESS_TOKEN|AUTH_TOKEN|REFRESH_TOKEN|CLIENT_SECRET|SECRET_KEY))\s*['\"]?\s*[:=]",
    re.I,
)

NON_PUBLIC_RECORD_KINDS = frozenset({"fact_proposal", "file_observation"})
DOCUMENT_RECORD_KINDS = frozenset({"file_snapshot", "file_unavailable", "git_commit"})

_PLATFORM_TAG_RE = re.compile(r"<(?P<tag>external_codex_apps_[a-z_]+|codex_internal_context)(?:\s+[^<>]*)?>")
_DATE_SPACE_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?.*)$")
_IO_LOCK_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}


def is_platform_control(content: str, *, kind: str | None = None) -> bool:
    """Return True when content is a full platform-injected control envelope."""
    if kind is not None and kind not in {"user_message", "assistant_message", "agent_message"}:
        return False
    text = content.strip()
    opening = _PLATFORM_TAG_RE.match(text)
    if opening is None:
        return False
    closing = "</" + opening["tag"] + ">"
    return text.endswith(closing) and text.find(closing, opening.end()) == len(text) - len(closing)


def is_public_raw_event(event: Any) -> bool:
    """Return True when an event is a public raw record suitable for attribution and retrieval."""
    return event.kind not in NON_PUBLIC_RECORD_KINDS and not is_platform_control(event.content, kind=event.kind)


def resolve_member_id(
    event: Any,
    session_members: dict[str, str] | None = None,
    fallback: str | None = None,
    *,
    route_documents: bool = False,
) -> str:
    """Resolve the owning member identity consistently across projections, dashboard, and extractors."""
    if route_documents and getattr(event, "kind", None) in DOCUMENT_RECORD_KINDS:
        return "project-documents"
    meta = event.metadata if isinstance(getattr(event, "metadata", None), dict) else {}
    return str(
        meta.get("member_id")
        or (session_members or {}).get(getattr(event, "session_id", None))
        or fallback
        or event.author
    )


def normalize_text(text: str) -> str:
    """Normalize text with Unicode NFKC for consistent matching across terminals and platforms."""
    return unicodedata.normalize("NFKC", text)


def parse_iso_timestamp(value: str, *, default_tz: tzinfo | None = None) -> datetime:
    """Parse ISO-8601 timestamps safely on Python 3.10+, including trailing 'Z' and space separators."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid ISO timestamp: {value!r}")
    text = value.strip()
    space_match = _DATE_SPACE_TIME_RE.match(text)
    if space_match:
        text = f"{space_match.group(1)}T{space_match.group(2)}"
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if default_tz is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=default_tz)
    return parsed


def as_utc_timestamp(value: datetime | str) -> datetime:
    """Normalize a datetime or ISO-8601 string to an aware UTC datetime."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_iso_timestamp(value, default_tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def path_lock(target: str | Path) -> threading.RLock:
    """Return the reentrant in-process lock bound to a normalized filesystem path."""
    resolved = Path(target).expanduser().resolve()
    with _IO_LOCK_GUARD:
        lock = _PATH_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[resolved] = lock
        return lock


_path_lock = path_lock


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Atomically write text using a locked staging temp file and bounded Windows replace retries."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(target)
    with lock:
        temp_path = (
            target.with_suffix(f"{target.suffix}.tmp")
            if target.suffix
            else target.with_name(f"{target.name}.tmp")
        )
        write_ok = False
        try:
            temp_path.write_text(content, encoding=encoding)
            write_ok = True
            for attempt in range(6):
                try:
                    temp_path.replace(target)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.005 * (attempt + 1))
        finally:
            if not write_ok and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    return target
