"""Read-only adapter for Antigravity conversation transcripts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .decision_graph import extract_dialogue_rich_facts
from .evidence_filters import SENSITIVE, is_platform_control, parse_iso_timestamp
from .models import EvidenceEvent


USER_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL)
_CMD_EXIT_CODE_RE = re.compile(r"Command exited with code\s+(-?\d+)", re.IGNORECASE)
_ASK_TS_HEADER_RE = re.compile(r"\A(?:(?:Created|Completed)\s+At:\s*[^\n]+\r?\n)+", re.IGNORECASE)


def infer_transcript_session_id(path: str | Path) -> str:
    """Resolve the conversation UUID/session name from Antigravity or legacy log paths."""
    resolved = Path(os.path.abspath(os.path.expanduser(str(path))))
    parent = resolved.parent
    grandparent = parent.parent
    if parent.name == "logs":
        if grandparent.name == ".system_generated" and grandparent.parent.name:
            return grandparent.parent.name
        if grandparent.name:
            return grandparent.name
        return resolved.stem or "antigravity-session"
    return parent.name or grandparent.name or resolved.stem or "antigravity-session"


def _extract_message_facts(content: str, claim_type: str) -> list[dict[str, Any]]:
    """Extract deterministic, source-bound candidate facts + causal context from dialogue lines."""
    return extract_dialogue_rich_facts(content, claim_type)


class AntigravityTranscriptAdapter:
    """Extract public user messages, assistant reports and optional tool events from an Antigravity transcript."""

    @classmethod
    def parse_record(
        cls,
        record: dict[str, Any],
        *,
        resolved_session: str,
        resolved_member: str = "antigravity",
        include_tools: bool = True,
        max_tool_chars: int = 8000,
        line_number: int = 1,
        pending_ask_question: bool = False,
    ) -> list[EvidenceEvent]:
        """Parse a single JSON transcript record into zero or more EvidenceEvent objects."""
        events: list[EvidenceEvent] = []
        source = record.get("source")
        record_type = record.get("type")
        step_index = record.get("step_index", line_number)
        timestamp_str = record.get("created_at")
        observed_at = (
            parse_iso_timestamp(timestamp_str)
            if timestamp_str
            else datetime.now(timezone.utc)
        )
        sess_tag = _hash_content(f"{resolved_session}:{resolved_member}")[:6]

        if source == "USER_EXPLICIT" and record_type == "USER_INPUT":
            content = record.get("content") or ""
            match = USER_REQUEST_RE.search(content)
            cleaned_content = match.group(1).strip() if match else content.strip()
            if not cleaned_content or is_platform_control(cleaned_content, kind="user_message") or SENSITIVE.search(cleaned_content):
                return events
            event_id = f"agy-u-{sess_tag}-{step_index}-{_hash_content(cleaned_content)}"
            facts = _extract_message_facts(cleaned_content, "user_statement")
            metadata: dict[str, Any] = {
                "source_ref": f"agy-transcript:{step_index}",
                "step_index": step_index,
                "member_id": resolved_member,
                "role": "user",
                "agent": "antigravity",
                "capture": "antigravity-transcript",
            }
            if facts:
                metadata["facts"] = facts
            events.append(
                EvidenceEvent(
                    id=event_id,
                    session_id=resolved_session,
                    author=resolved_member,
                    kind="user_message",
                    content=cleaned_content,
                    observed_at=observed_at,
                    metadata=metadata,
                )
            )

        elif source == "MODEL" and record_type == "PLANNER_RESPONSE":
            content = (record.get("content") or "").strip()
            if content and not is_platform_control(content, kind="assistant_message") and not SENSITIVE.search(content):
                event_id = f"agy-a-{sess_tag}-{step_index}-{_hash_content(content)}"
                facts = _extract_message_facts(content, "assistant_report")
                metadata = {
                    "source_ref": f"agy-transcript:{step_index}",
                    "step_index": step_index,
                    "member_id": resolved_member,
                    "role": "assistant",
                    "agent": "antigravity",
                    "capture": "antigravity-transcript",
                }
                if facts:
                    metadata["facts"] = facts
                events.append(
                    EvidenceEvent(
                        id=event_id,
                        session_id=resolved_session,
                        author="antigravity",
                        kind="assistant_message",
                        content=content,
                        observed_at=observed_at,
                        metadata=metadata,
                    )
                )

            if include_tools:
                tool_calls = record.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call_index, call in enumerate(tool_calls):
                        if not isinstance(call, dict):
                            continue
                        tool_name = str(call.get("name") or "unknown_tool")
                        tool_args = call.get("args") or {}
                        summary = f"Call {tool_name}"
                        if "CommandLine" in tool_args:
                            summary += f": {tool_args['CommandLine']}"
                        elif "Path" in tool_args:
                            summary += f": {tool_args['Path']}"
                        if SENSITIVE.search(summary):
                            continue
                        call_id = f"agy-call-{sess_tag}-{step_index}-{call_index}-{_hash_content(summary)}"
                        events.append(
                            EvidenceEvent(
                                id=call_id,
                                session_id=resolved_session,
                                author="antigravity",
                                kind="tool_call",
                                content=summary[:max_tool_chars],
                                observed_at=observed_at,
                                metadata={
                                    "source_ref": f"agy-transcript:{step_index}:call:{call_index}",
                                    "tool": tool_name,
                                    "step_index": step_index,
                                    "member_id": resolved_member,
                                    "agent": "antigravity",
                                },
                            )
                        )

        elif source == "MODEL" and record_type == "GENERIC":
            raw_content = (record.get("content") or "").strip()
            ts_match = _ASK_TS_HEADER_RE.match(raw_content)
            stripped_answer = raw_content[ts_match.end():].strip() if ts_match else raw_content
            if (ts_match or pending_ask_question) and re.match(r"^A1:\s+\S", stripped_answer):
                if not SENSITIVE.search(stripped_answer):
                    facts = _extract_message_facts(stripped_answer, "user_statement")
                    ans_meta: dict[str, Any] = {
                        "source_ref": f"agy-transcript:{step_index}",
                        "step_index": step_index,
                        "member_id": resolved_member,
                        "role": "user",
                        "agent": "antigravity",
                        "capture": "antigravity-ask-question",
                    }
                    if facts:
                        ans_meta["facts"] = facts
                    events.append(
                        EvidenceEvent(
                            id=f"agy-uq-{sess_tag}-{step_index}-{_hash_content(stripped_answer)}",
                            session_id=resolved_session,
                            author=resolved_member,
                            kind="user_message",
                            content=stripped_answer,
                            observed_at=observed_at,
                            metadata=ans_meta,
                        )
                    )
                return events

            if include_tools and raw_content and not SENSITIVE.search(raw_content):
                bounded = raw_content[:max_tool_chars]
                res_id = f"agy-res-{sess_tag}-{step_index}-{_hash_content(bounded)}"
                res_meta: dict[str, Any] = {
                    "source_ref": f"agy-transcript:{step_index}",
                    "step_index": step_index,
                    "member_id": resolved_member,
                    "agent": "antigravity",
                    "capture": "antigravity-transcript",
                }
                exit_match = _CMD_EXIT_CODE_RE.search(bounded)
                if exit_match:
                    try:
                        res_meta["exit_code"] = int(exit_match.group(1))
                    except ValueError:
                        pass
                events.append(
                    EvidenceEvent(
                        id=res_id,
                        session_id=resolved_session,
                        author="antigravity",
                        kind="tool_result",
                        content=bounded,
                        observed_at=observed_at,
                        metadata=res_meta,
                    )
                )

        return events

    @classmethod
    def from_transcript(
        cls,
        path: str | Path,
        *,
        session_id: str | None = None,
        member_id: str = "antigravity",
        include_tools: bool = True,
        max_tool_chars: int = 8000,
    ) -> list[EvidenceEvent]:
        transcript_path = Path(path).expanduser().resolve(strict=True)
        resolved_session = session_id or infer_transcript_session_id(transcript_path)
        resolved_member = member_id.strip() or "antigravity"
        events: list[EvidenceEvent] = []
        pending_ask_question = False

        with transcript_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid Antigravity transcript at line {line_number}: {exc.msg}") from exc

                parsed = cls.parse_record(
                    record,
                    resolved_session=resolved_session,
                    resolved_member=resolved_member,
                    include_tools=include_tools,
                    max_tool_chars=max_tool_chars,
                    line_number=line_number,
                    pending_ask_question=pending_ask_question,
                )
                events.extend(parsed)
                if record.get("source") == "MODEL" and record.get("type") == "PLANNER_RESPONSE":
                    pending_ask_question = any(
                        isinstance(c, dict) and c.get("name") == "ask_question"
                        for c in (record.get("tool_calls") or [])
                    )
                elif record.get("source") == "USER_EXPLICIT" or (parsed and parsed[0].kind == "user_message"):
                    pending_ask_question = False

        return events


def _hash_content(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
