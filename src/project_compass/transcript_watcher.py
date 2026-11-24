"""Live watcher for streaming agent transcripts (Antigravity/JSONL).

Provides line-incompleteness protection and idempotent incremental sync.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import quote as url_quote

from .antigravity_adapter import AntigravityTranscriptAdapter, infer_transcript_session_id
from .direction_intake import record_direction_candidates
from .models import EvidenceEvent
from .user_task_intake import record_user_task_candidates

_SYSTEM_AUTHORS = frozenset({
    "",
    "antigravity",
    "project-documents",
    "scanner",
    "git",
    "codex",
    "claude",
    "cursor",
    "system",
    "__local_owner__",
})
_DISCOVERY_CACHE_LOCK = Lock()
_DISCOVERY_CACHE: dict[tuple[str, str, int, int], tuple[bool, bool, bool]] = {}
_DISCOVERY_CHUNK_BYTES = 524288
_DISCOVERY_OVERLAP_BYTES = 512
_DISCOVERY_MAX_SCAN_BYTES = 32 * 1024 * 1024


def infer_primary_human_member(
    events: list[EvidenceEvent] | tuple[EvidenceEvent, ...] = (),
    review_history: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> str:
    """Resolve the workspace's active human owner name so transcripts never clash with web notes."""
    for item in reversed(review_history or ()):
        if not isinstance(item, dict):
            continue
        reviewer = str(item.get("reviewer") or "").strip()
        if reviewer and reviewer.casefold() not in _SYSTEM_AUTHORS:
            return reviewer
    for ev in reversed(events or ()):
        if ev.kind not in {"user_message", "fact_proposal"}:
            continue
        author = str(ev.author or "").strip()
        if author and author.casefold() not in _SYSTEM_AUTHORS:
            return author
        meta = ev.metadata if isinstance(ev.metadata, dict) else {}
        member = str(meta.get("member_id") or "").strip()
        if member and member.casefold() not in _SYSTEM_AUTHORS:
            return member
    return "solo"


def _project_path_match_patterns(project_path: str | Path) -> tuple[re.Pattern[str], ...]:
    resolved = str(Path(project_path).expanduser().resolve()).rstrip("\\/")
    posix = resolved.replace("\\", "/")
    backslash = resolved.replace("/", "\\")
    escaped_backslash = backslash.replace("\\", "\\\\")
    raw_variants = {posix, backslash, escaped_backslash}
    # Support Antigravity file:// workspace URI forms (encoded & unencoded drive colons/CJK segments)
    if len(posix) >= 2 and posix[1] == ":":
        drive = posix[0].lower()
        rest = posix[2:]
        encoded_rest = url_quote(rest, safe="/")
        for drv in {drive, drive.upper()}:
            raw_variants.add(f"file:///{drv}%3A{encoded_rest}")
            raw_variants.add(f"file:///{drv}%3a{encoded_rest}")
            raw_variants.add(f"file:///{drv}%3A{rest}")
            raw_variants.add(f"file:///{drv}:{rest}")
    flags = re.IGNORECASE if os.name == "nt" else 0
    return tuple(
        re.compile(re.escape(variant) + r"(?![A-Za-z0-9_.\-/]|\\\\|\\(?![nrt\"'])|%2[fF]|%5[cC])", flags)
        for variant in sorted(raw_variants, key=len, reverse=True)
        if variant
    )


def _scan_transcript_candidate(
    cand: Path,
    size: int,
    patterns: tuple[re.Pattern[str], ...],
    needles: tuple[bytes, ...],
) -> tuple[bool, bool, bool]:
    """Check whether ``cand`` binds the target project and contains user conversation markers."""
    matched_project = False
    is_user_conv = False
    try:
        with cand.open("rb") as handle:
            first_line = handle.readline(262144)
            if (
                b"call the finish tool with your result" in first_line
                or (b'"SYSTEM_MESSAGE"' in first_line and b'"USER_EXPLICIT"' not in first_line)
            ):
                return False, False, True
            handle.seek(0)
            head = handle.read(65536)
            if b'"USER_EXPLICIT"' in head:
                is_user_conv = True
            head_lower = head.lower()
            if not needles or any(n in head_lower for n in needles):
                head_text = head.decode("utf-8", errors="replace")
                if any(pat.search(head_text) for pat in patterns):
                    matched_project = True
            if matched_project and is_user_conv:
                return True, True, False

            pos = size
            scanned = 0
            while pos > 0 and scanned < _DISCOVERY_MAX_SCAN_BYTES:
                start = max(0, pos - _DISCOVERY_CHUNK_BYTES)
                read_len = min(size - start, _DISCOVERY_CHUNK_BYTES + _DISCOVERY_OVERLAP_BYTES)
                handle.seek(start)
                chunk = handle.read(read_len)
                scanned += len(chunk)
                if not is_user_conv and b'"USER_EXPLICIT"' in chunk:
                    is_user_conv = True
                if not matched_project:
                    chunk_lower = chunk.lower()
                    if not needles or any(n in chunk_lower for n in needles):
                        chunk_text = chunk.decode("utf-8", errors="replace")
                        if any(pat.search(chunk_text) for pat in patterns):
                            matched_project = True
                if matched_project and is_user_conv:
                    return True, True, False
                if start <= 65536 - _DISCOVERY_OVERLAP_BYTES:
                    break
                pos = start
    except OSError:
        return False, False, False
    return matched_project, is_user_conv, False


def discover_active_antigravity_transcript(
    project_path: str | Path,
    *,
    brain_root: str | Path | None = None,
    max_candidates: int = 32,
) -> Path | None:
    """Locate the newest Antigravity JSONL transcript bound to ``project_path``."""
    if os.environ.get("SAMPLE_MODE", "").strip().lower() == "true":
        return None
    if os.environ.get("COMPASS_DISABLE_AUTO_TRANSCRIPT", "").strip().lower() in {"1", "true", "yes"}:
        return None

    env_root = os.environ.get("COMPASS_ANTIGRAVITY_BRAIN_DIR", "").strip()
    root = Path(brain_root).expanduser() if brain_root else (
        Path(env_root).expanduser() if env_root else (Path.home() / ".gemini" / "antigravity" / "brain")
    )
    if not root.is_dir():
        return None

    try:
        resolved_project = Path(project_path).expanduser().resolve()
    except OSError:
        return None
    patterns = _project_path_match_patterns(resolved_project)
    if not patterns:
        return None
    project_key = str(resolved_project).casefold()
    leaf = resolved_project.name.strip()
    needles = tuple(
        {
            raw.lower().encode("utf-8")
            for raw in (leaf, url_quote(leaf, safe=""))
            if raw
        }
    )

    candidates: list[tuple[int, int, Path]] = []
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        for rel in (Path(".system_generated") / "logs" / "transcript.jsonl", Path("transcript.jsonl")):
            cand = sub / rel
            try:
                if cand.is_file():
                    st = cand.stat()
                    if st.st_size > 0:
                        candidates.append((int(st.st_mtime_ns), int(st.st_size), cand))
            except OSError:
                continue

    candidates.sort(key=lambda row: row[0], reverse=True)
    max_non_subagent = max(1, int(max_candidates))
    scan_limit = min(len(candidates), max(128, max_non_subagent * 4))
    non_subagent_checked = 0
    fallback_hit: Path | None = None
    for mtime_ns, size, cand in candidates[:scan_limit]:
        cache_key = (project_key, str(cand), mtime_ns, size)
        with _DISCOVERY_CACHE_LOCK:
            cached = _DISCOVERY_CACHE.get(cache_key)
        if cached is None:
            cached = _scan_transcript_candidate(cand, size, patterns, needles)
            with _DISCOVERY_CACHE_LOCK:
                if len(_DISCOVERY_CACHE) >= 256:
                    for stale_key in list(_DISCOVERY_CACHE)[:128]:
                        _DISCOVERY_CACHE.pop(stale_key, None)
                _DISCOVERY_CACHE[cache_key] = cached
        matched_project, is_user_conv, is_subagent = cached
        if is_subagent:
            continue
        non_subagent_checked += 1
        if non_subagent_checked > max_non_subagent:
            break
        if not matched_project:
            continue
        # Prefer top-level user conversation transcripts over isolated subagent logs.
        if is_user_conv:
            return cand
        if fallback_hit is None:
            fallback_hit = cand
    return fallback_hit


class TranscriptWatcher:
    """Incrementally ingests streaming JSONL transcript lines into a workspace and event list."""

    def __init__(
        self,
        transcript_path: str | Path,
        *,
        member_id: str = "antigravity",
        session_id: str | None = None,
        include_tools: bool = True,
        max_tool_chars: int = 8000,
        max_initial_tool_events: int = 240,
        session_members: dict[str, str] | None = None,
        initial_events: list[EvidenceEvent] | None = None,
    ) -> None:
        self.path = Path(transcript_path).expanduser().resolve()
        self.member_id = (member_id or "antigravity").strip() or "antigravity"
        self.session_id = session_id or infer_transcript_session_id(self.path)
        self.include_tools = include_tools
        self.max_tool_chars = max_tool_chars
        self.max_initial_tool_events = max(0, int(max_initial_tool_events))
        self.session_members = session_members if session_members is not None else {}
        self.last_byte_offset: int = 0
        self.line_count: int = 0
        self.known_event_ids: set[str] = set()
        self._pending_ask_question: bool = False

        if initial_events:
            for event in initial_events:
                self.known_event_ids.add(event.id)

    def sync(
        self,
        project_workspace: Any = None,
        events: list[EvidenceEvent] | None = None,
    ) -> dict[str, Any]:
        """Read newly appended lines from the transcript with line-incompleteness protection."""
        def _build_status(updated: bool, new_events_count: int, **extra: Any) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "enabled": True,
                "channel": "antigravity",
                "member_id": self.member_id,
                "updated": updated,
                "new_events_count": new_events_count,
                "captured_messages": len(self.known_event_ids),
                "total_events": len(events) if events is not None else len(self.known_event_ids),
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }
            payload.update(extra)
            return payload

        if not self.path.exists() or not self.path.is_file():
            return _build_status(False, 0, error="transcript file does not exist")

        file_size = self.path.stat().st_size
        if file_size < self.last_byte_offset:
            # File was truncated or rotated: reset offset
            self.last_byte_offset = 0
            self.line_count = 0

        was_initial_backfill = self.last_byte_offset == 0
        batch_new_events: list[EvidenceEvent] = []

        with self.path.open("rb") as handle:
            handle.seek(self.last_byte_offset)
            raw_bytes = handle.read()

            if not raw_bytes:
                return _build_status(False, 0, offset=self.last_byte_offset)

            # Line-incompleteness protection:
            # If the chunk does not end with a newline, the last line is still being written.
            if not raw_bytes.endswith(b"\n"):
                last_newline_idx = raw_bytes.rfind(b"\n")
                if last_newline_idx == -1:
                    # Incomplete line; wait for the rest to be flushed
                    return _build_status(False, 0, offset=self.last_byte_offset, pending_partial_line=True)
                valid_chunk = raw_bytes[: last_newline_idx + 1]
                self.last_byte_offset += last_newline_idx + 1
            else:
                valid_chunk = raw_bytes
                self.last_byte_offset += len(raw_bytes)

        # Parse complete lines
        text = valid_chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            raw_line = line.strip()
            if not raw_line:
                continue
            self.line_count += 1
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            parsed_events = AntigravityTranscriptAdapter.parse_record(
                record,
                resolved_session=self.session_id,
                resolved_member=self.member_id,
                include_tools=self.include_tools,
                max_tool_chars=self.max_tool_chars,
                line_number=self.line_count,
                pending_ask_question=self._pending_ask_question,
            )
            if record.get("source") == "MODEL" and record.get("type") == "PLANNER_RESPONSE":
                self._pending_ask_question = any(
                    isinstance(c, dict) and c.get("name") == "ask_question"
                    for c in (record.get("tool_calls") or [])
                )
            elif record.get("source") == "USER_EXPLICIT" or (parsed_events and parsed_events[0].kind == "user_message"):
                self._pending_ask_question = False

            for event in parsed_events:
                if event.id not in self.known_event_ids:
                    self.known_event_ids.add(event.id)
                    batch_new_events.append(event)

        if was_initial_backfill and len(batch_new_events) > self.max_initial_tool_events:
            tool_kinds = {"tool_call", "tool_result"}
            tool_indices = [idx for idx, ev in enumerate(batch_new_events) if ev.kind in tool_kinds]
            if len(tool_indices) > self.max_initial_tool_events:
                keep_tool_indices = set(tool_indices[-self.max_initial_tool_events :])
                batch_new_events = [
                    ev
                    for idx, ev in enumerate(batch_new_events)
                    if ev.kind not in tool_kinds or idx in keep_tool_indices
                ]

        # Append to active state & workspace
        direction_status: dict[str, Any] = {"updated": False}
        task_status: dict[str, Any] = {"updated": False}

        if batch_new_events:
            if events is not None:
                events.extend(batch_new_events)
            if project_workspace is not None:
                project_workspace.save(batch_new_events)
                target_events = events if events is not None else batch_new_events
                direction_status = record_direction_candidates(
                    target_events, project_workspace, session_members=self.session_members
                )
                task_status = record_user_task_candidates(
                    target_events, project_workspace, session_members=self.session_members
                )

        updated = bool(batch_new_events) or direction_status.get("updated", False) or task_status.get("updated", False)

        return _build_status(
            updated,
            len(batch_new_events),
            offset=self.last_byte_offset,
            line_count=self.line_count,
        )


class AutoTranscriptIntake:
    """Throttled passive Antigravity/local transcript observer bound to a project workspace."""

    def __init__(
        self,
        project_path: str | Path,
        workspace: Any,
        *,
        member_id: str = "antigravity",
        brain_root: str | Path | None = None,
        initial_events: list[EvidenceEvent] | None = None,
        include_tools: bool = True,
    ) -> None:
        self.project_path = Path(project_path).expanduser().resolve()
        self.workspace = workspace
        self.member_id = (member_id or "antigravity").strip() or "antigravity"
        self.brain_root = brain_root
        self.include_tools = include_tools
        self._sync_lock = Lock()
        self.watcher: TranscriptWatcher | None = None
        self._last_sig: tuple[int, int] | None = None
        self._last_check_mono = 0.0
        self._last_discover_mono = 0.0
        self._discovered_candidate: Path | None = None
        self._last_status: dict[str, Any] = {"enabled": False, "channel": "antigravity"}
        self._bind_latest(initial_events=initial_events, force=True)

    def pre_discover(self, *, force: bool = False) -> None:
        """Run transcript directory discovery off the HTTP state lock when cooldown elapses."""
        now_mono = time.monotonic()
        with self._sync_lock:
            if not force and (now_mono - self._last_discover_mono) < 10.0:
                return
            self._last_discover_mono = now_mono
        found = discover_active_antigravity_transcript(self.project_path, brain_root=self.brain_root)
        if found is not None:
            resolved = found.resolve()
            with self._sync_lock:
                self._discovered_candidate = resolved

    def _bind_latest(self, *, initial_events: list[EvidenceEvent] | None = None, force: bool = False) -> None:
        resolved_found: Path | None = None
        with self._sync_lock:
            if self._discovered_candidate is not None and self._discovered_candidate.is_file():
                resolved_found = self._discovered_candidate
            now_mono = time.monotonic()
            need_scan = force or ((now_mono - self._last_discover_mono) >= 10.0)
            if need_scan:
                self._last_discover_mono = now_mono
        if need_scan or resolved_found is None:
            found = discover_active_antigravity_transcript(self.project_path, brain_root=self.brain_root)
            if found is not None:
                resolved_found = found.resolve()
                with self._sync_lock:
                    self._discovered_candidate = resolved_found
        if resolved_found is None:
            return
        if self.watcher is not None and self.watcher.path == resolved_found:
            return
        events_seed = initial_events if initial_events is not None else (
            self.workspace.load() if self.workspace is not None and self.workspace.exists() else []
        )
        self.watcher = TranscriptWatcher(
            resolved_found,
            member_id=self.member_id,
            include_tools=self.include_tools,
            initial_events=events_seed,
        )
        self._last_sig = None

    def initial_status(self, events: list[EvidenceEvent] | None = None) -> dict[str, Any]:
        if self.watcher is None:
            return {"enabled": False, "channel": "antigravity"}
        return self.sync(events, min_interval_sec=0.0)

    def sync(
        self,
        events: list[EvidenceEvent] | None = None,
        *,
        min_interval_sec: float = 1.5,
    ) -> dict[str, Any]:
        now_mono = time.monotonic()
        allow_rediscover = (min_interval_sec <= 0) or ((now_mono - self._last_check_mono) >= min_interval_sec)
        pending_switch = False
        with self._sync_lock:
            pending_switch = (
                self._discovered_candidate is not None
                and (self.watcher is None or self.watcher.path != self._discovered_candidate)
            )
        if self.watcher is None or allow_rediscover or pending_switch:
            self._last_check_mono = now_mono
            self._bind_latest(initial_events=events, force=(min_interval_sec <= 0))
        if self.watcher is None or not self.watcher.path.exists():
            self._last_status = {"enabled": False, "channel": "antigravity"}
            return dict(self._last_status)
        try:
            st = self.watcher.path.stat()
            sig = (int(st.st_size), int(st.st_mtime_ns))
        except OSError:
            return dict(self._last_status)

        if sig == self._last_sig and self._last_status.get("enabled"):
            out = dict(self._last_status)
            out["updated"] = False
            out["new_events_count"] = 0
            return out

        status = self.watcher.sync(self.workspace, events)
        status["thread_id"] = self.watcher.session_id
        # Do NOT lock _last_sig when an incomplete trailing JSONL line prevented consuming up to st_size.
        self._last_sig = sig if self.watcher.last_byte_offset >= sig[0] and not status.get("pending_partial_line") else None
        self._last_status = dict(status)
        return status
