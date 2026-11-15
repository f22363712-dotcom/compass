"""Read-only adapter for Antigravity conversation transcripts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .evidence_filters import SENSITIVE, is_platform_control, parse_iso_timestamp
from .models import EvidenceEvent


USER_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL)
_GOAL_LINE_RE = re.compile(r"^目标[：:]\s*(\S.+)$")
_HUMAN_GOAL_RE = re.compile(r"[^。\n]*围绕[^。\n]+打造[^。\n]*")
_USER_DECISION_RE = re.compile(r"^(?:选项[一二三四1234]|选\s*[A-D])[，,。:\s]\s*\S.+")
_EXPLICIT_DECISION_RE = re.compile(r"^(?:核心决策|决策)[：:]\s*(\S.+)$")
_ASSISTANT_TASK_RE = re.compile(r"^(?:已实现|已完成)\s+(?:Module\s+\d+|`?[A-Za-z_][A-Za-z0-9_.-]*`?)[^。\n]*。?")


def _extract_message_facts(content: str, claim_type: str) -> list[dict[str, Any]]:
    """Extract deterministic, source-bound candidate facts from explicit dialogue lines."""
    facts: list[dict[str, Any]] = []
    seen_quotes: set[str] = set()

    for raw_line in content.splitlines():
        cleaned = re.sub(r"^[>\-\*\s]+", "", raw_line).strip()
        plain = cleaned.replace("**", "").strip()
        if not plain or ("<" in plain and ">" in plain):
            continue

        goal_match = _GOAL_LINE_RE.match(plain)
        if goal_match:
            quote = plain
            if quote not in seen_quotes:
                seen_quotes.add(quote)
                facts.append({
                    "kind": "goal",
                    "subject_key": f"goal.agy.{_hash_content(quote)}",
                    "value": quote,
                    "quote": quote,
                    "claim_type": claim_type,
                })
            continue

        if claim_type == "user_statement":
            human_goal = _HUMAN_GOAL_RE.search(plain)
            if human_goal:
                quote = human_goal.group(0).strip()
                if quote not in seen_quotes:
                    seen_quotes.add(quote)
                    facts.append({
                        "kind": "goal",
                        "subject_key": f"goal.agy.{_hash_content(quote)}",
                        "value": quote,
                        "quote": quote,
                        "claim_type": claim_type,
                    })

            if _USER_DECISION_RE.match(plain) or _EXPLICIT_DECISION_RE.match(plain):
                quote = plain
                if quote not in seen_quotes:
                    seen_quotes.add(quote)
                    facts.append({
                        "kind": "decision",
                        "subject_key": f"decision.agy.{_hash_content(quote)}",
                        "value": quote,
                        "quote": quote,
                        "claim_type": claim_type,
                    })
                continue

        if claim_type == "assistant_report":
            task_match = _ASSISTANT_TASK_RE.match(plain)
            if task_match:
                quote = task_match.group(0).strip()
                if quote not in seen_quotes:
                    seen_quotes.add(quote)
                    facts.append({
                        "kind": "task",
                        "subject_key": f"task.agy.{_hash_content(quote)}",
                        "value": quote,
                        "quote": quote,
                        "claim_type": claim_type,
                        "task_state": "reported_complete",
                    })

    return facts


class AntigravityTranscriptAdapter:
    """Extract public user messages, assistant reports and optional tool events from an Antigravity transcript."""

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
        resolved_session = session_id or transcript_path.parent.parent.name
        resolved_member = member_id.strip() or "antigravity"
        events: list[EvidenceEvent] = []

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

        if source == "USER_EXPLICIT" and record_type == "USER_INPUT":
            content = record.get("content") or ""
            match = USER_REQUEST_RE.search(content)
            cleaned_content = match.group(1).strip() if match else content.strip()
            if not cleaned_content or is_platform_control(cleaned_content, kind="user_message") or SENSITIVE.search(cleaned_content):
                return events
            event_id = f"agy-u-{step_index}-{_hash_content(cleaned_content)}"
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
                event_id = f"agy-a-{step_index}-{_hash_content(content)}"
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
                        call_id = f"agy-call-{step_index}-{call_index}"
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

        elif source == "MODEL" and record_type == "GENERIC" and include_tools:
            content = (record.get("content") or "").strip()
            if content and not SENSITIVE.search(content):
                bounded = content[:max_tool_chars]
                res_id = f"agy-res-{step_index}-{_hash_content(bounded)}"
                events.append(
                    EvidenceEvent(
                        id=res_id,
                        session_id=resolved_session,
                        author="antigravity",
                        kind="tool_result",
                        content=bounded,
                        observed_at=observed_at,
                        metadata={
                            "source_ref": f"agy-transcript:{step_index}",
                            "step_index": step_index,
                            "member_id": resolved_member,
                            "agent": "antigravity",
                            "capture": "antigravity-transcript",
                        },
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
        resolved_session = session_id or transcript_path.parent.parent.name
        resolved_member = member_id.strip() or "antigravity"
        events: list[EvidenceEvent] = []

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
                )
                events.extend(parsed)

        return events

        return events


def _hash_content(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
