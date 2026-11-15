from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence_filters import SENSITIVE, is_platform_control, parse_iso_timestamp
from .models import EvidenceEvent


SUPPORTED_TYPES = {"assistant_message", "user_message", "tool_call", "tool_result", "test_result", "file_change"}


class CodexAdapter:
    @staticmethod
    def from_jsonl(path: str | Path) -> list[EvidenceEvent]:
        events: list[EvidenceEvent] = []
        session_id = None
        for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid Codex JSONL at line {line_number}: {exc.msg}") from exc
            if payload.get("type") == "session_meta":
                session_id = (payload.get("payload") or {}).get("id")
                continue
            if payload.get("type") in {"turn_context", "token_usage_record", "event_msg", "world_state", "compacted"}:
                continue
            if payload.get("type") == "response_item":
                event = CodexAdapter.normalize_response_item(payload, line_number, session_id)
                if event is not None:
                    events.append(event)
                continue
            events.append(CodexAdapter.normalize(payload, line_number))
        return events

    @staticmethod
    def normalize_response_item(payload: dict[str, Any], line_number: int = 0, session_id: str | None = None) -> EvidenceEvent | None:
        item = payload.get("payload")
        if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") not in {"user", "assistant"}:
            return None
        parts = item.get("content", [])
        if not isinstance(parts, list):
            raise ValueError(f"invalid native message content at line {line_number}")
        content = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"} and isinstance(part.get("text", ""), str))
        if not content.strip() or is_platform_control(content, kind=item["role"] + "_message") or SENSITIVE.search(content):
            return None
        event_id = item.get("id") or hashlib.sha1(json.dumps(payload, sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:16]
        timestamp = payload.get("timestamp")
        if timestamp is None:
            raise ValueError(f"native response item requires timestamp at line {line_number}")
        observed_at = parse_iso_timestamp(timestamp)
        return EvidenceEvent(
            id=str(event_id), session_id=str(session_id or "codex-unknown-session"), author="codex",
            kind=item["role"] + "_message", content=content, observed_at=observed_at,
            metadata={"source_ref": f"native-rollout:{line_number}", "role": item["role"], "capture": "codex-jsonl-public"},
        )

    @staticmethod
    def normalize(payload: dict[str, Any], line_number: int = 0) -> EvidenceEvent:
        if not isinstance(payload, dict):
            raise ValueError(f"Codex event at line {line_number} must be an object")
        kind = payload.get("type")
        if kind not in SUPPORTED_TYPES:
            raise ValueError(f"unsupported Codex event type at line {line_number}: {kind}")
        event_id = payload.get("id") or hashlib.sha1(json.dumps(payload, sort_keys=True).encode(), usedforsecurity=False).hexdigest()[:16]
        metadata = dict(payload.get("metadata", {}))
        for key in ("tool", "command", "exit_code", "files"):
            if key in payload:
                metadata[key] = payload[key]
        timestamp = payload.get("timestamp") or payload.get("observed_at")
        if timestamp is None:
            observed_at = datetime.now(timezone.utc)
            metadata["inferred_timestamp"] = True
        else:
            observed_at = parse_iso_timestamp(timestamp)
        return EvidenceEvent(
            id=str(event_id),
            session_id=str(payload.get("session_id", "codex-unknown-session")),
            author=str(payload.get("author", "codex")),
            kind=kind,
            content=str(payload.get("content", "")),
            observed_at=observed_at,
            metadata=metadata,
        )
