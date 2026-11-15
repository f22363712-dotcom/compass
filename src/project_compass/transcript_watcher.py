"""Live watcher for streaming agent transcripts (Antigravity/JSONL).

Provides line-incompleteness protection and idempotent incremental sync.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .antigravity_adapter import AntigravityTranscriptAdapter
from .direction_intake import record_direction_candidates
from .models import EvidenceEvent
from .user_task_intake import record_user_task_candidates


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
        session_members: dict[str, str] | None = None,
        initial_events: list[EvidenceEvent] | None = None,
    ) -> None:
        self.path = Path(transcript_path).expanduser().resolve()
        self.member_id = (member_id or "antigravity").strip() or "antigravity"
        self.session_id = session_id or self.path.parent.parent.name
        self.include_tools = include_tools
        self.max_tool_chars = max_tool_chars
        self.session_members = session_members if session_members is not None else {}
        self.last_byte_offset: int = 0
        self.line_count: int = 0
        self.known_event_ids: set[str] = set()

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
            )

            for event in parsed_events:
                if event.id not in self.known_event_ids:
                    self.known_event_ids.add(event.id)
                    batch_new_events.append(event)

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
