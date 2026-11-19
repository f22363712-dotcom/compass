"""Shared content filters, timestamp parsing, member attribution, and atomic IO."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, tzinfo
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
import unicodedata

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

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
_PATH_LOCKS: dict[str, threading.RLock] = {}
_ACTIVE_OS_LOCKS: set[str] = set()


def _canonical_path_key(target: str | Path) -> str:
    raw = os.path.abspath(os.path.expanduser(os.fspath(target)))
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return os.path.normcase(raw)


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
    key = _canonical_path_key(target)
    with _IO_LOCK_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


_path_lock = path_lock


@contextmanager
def interprocess_file_lock(target: str | Path, timeout: float = 5.0):
    """Acquire both in-process RLock and OS advisory lock on a sibling ``.lock`` file."""
    key = _canonical_path_key(target)
    raw = os.path.abspath(os.path.expanduser(os.fspath(target)))
    clean_target = Path(raw[4:] if raw.startswith("\\\\?\\") else raw)
    lock_file = clean_target.with_name(f"{clean_target.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with path_lock(clean_target):
        if key in _ACTIVE_OS_LOCKS:
            yield
            return
        handle = open(lock_file, "a+b")
        acquired = False
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\x00")
                handle.flush()
            deadline = time.monotonic() + max(0.1, float(timeout))
            delay = 0.005
            while not acquired:
                try:
                    handle.seek(0)
                    if sys.platform == "win32":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"timed out acquiring lock for {clean_target}") from exc
                    time.sleep(delay)
                    delay = min(0.05, delay * 1.5)
            _ACTIVE_OS_LOCKS.add(key)
            yield
        finally:
            _ACTIVE_OS_LOCKS.discard(key)
            if acquired:
                try:
                    handle.seek(0)
                    if sys.platform == "win32":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


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
