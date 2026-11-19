"""Append-only quick-note ledger writer shared by Web UI and 1-step MCP record_note."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

from .evidence_filters import SENSITIVE, normalize_text
from .models import EvidenceEvent
from .project_workspace import ProjectWorkspace
from .text_summary import summarize_node_title

ALLOWED_NOTE_KINDS = frozenset({"decision", "assumption", "task", "goal"})
MAX_NOTE_CHARS = 2000


def _sanitize_member_id(member_id: str | None) -> str:
    clean = normalize_text(str(member_id or "")).strip()
    if not clean:
        raise ValueError("member_id is required for quick note")
    if len(clean) > 120:
        raise ValueError("member_id exceeds length limit")
    if clean in {"project-documents", "__local_owner__"}:
        raise ValueError("invalid member_id for quick note")
    return clean


def append_quick_note(
    workspace: ProjectWorkspace,
    events: list[EvidenceEvent],
    *,
    text: str,
    kind: str,
    member_id: str,
    title: str = "",
    topic: str = "",
    client_nonce: str = "",
    session_id: str = "web-quick-note",
    source_channel: str = "web_quick_note",
) -> dict[str, Any]:
    """Append a quick note as an immutable raw event + exact-span proposed fact."""
    clean_kind = str(kind or "decision").strip().lower()
    if clean_kind not in ALLOWED_NOTE_KINDS:
        raise ValueError(f"unsupported quick note kind: {clean_kind}")
    if not isinstance(text, str):
        raise ValueError("note text must be a string")
    clean_text = normalize_text(text).strip()
    if not clean_text:
        raise ValueError("note text cannot be empty")
    if len(clean_text) > MAX_NOTE_CHARS:
        raise ValueError(f"note text exceeds {MAX_NOTE_CHARS} characters")
    if SENSITIVE.search(clean_text) is not None:
        raise ValueError("note contains sensitive credential material")

    clean_title_input = normalize_text(str(title or "")).strip()
    if clean_title_input and SENSITIVE.search(clean_title_input) is not None:
        raise ValueError("note title contains sensitive credential material")
    short_title = summarize_node_title(
        clean_text,
        clean_title_input or None,
        max_chars=28 if clean_kind == "goal" else 22,
    )

    clean_member = _sanitize_member_id(member_id)
    clean_topic = normalize_text(str(topic or "")).strip().lower()
    clean_nonce = normalize_text(str(client_nonce or "")).strip()[:80]
    channel = "mcp_record_note" if source_channel == "mcp_record_note" else "web_quick_note"
    source_ref = "mcp://record-note" if channel == "mcp_record_note" else "web://quick-note"
    derivation = "mcp-record-note-v1" if channel == "mcp_record_note" else "web-quick-note-v1"

    now = datetime.now(timezone.utc)
    entropy = clean_nonce or now.isoformat()
    digest = sha1(f"{clean_member}:{clean_kind}:{clean_text}:{entropy}".encode("utf-8"), usedforsecurity=False).hexdigest()

    source_id = f"note-{digest[:16]}"
    proposal_id = f"proposal-{digest[:16]}"
    if clean_kind == "goal":
        subject_key = "project.goal"
    elif clean_kind == "task" and clean_topic == "next_step":
        subject_key = "project.next_step"
    else:
        subject_key = f"note.{clean_kind}.{digest[:10]}"
    fact_id = f"fact-{sha1(f'{proposal_id}:0'.encode('utf-8'), usedforsecurity=False).hexdigest()[:10]}"

    fact_entry: dict[str, Any] = {
        "kind": clean_kind,
        "subject_key": subject_key,
        "value": clean_text,
        "quote": clean_text,
        "source_id": source_id,
        "source_start": 0,
        "source_end": len(clean_text),
    }
    if clean_kind == "task":
        fact_entry["task_state"] = "pending"

    source_event = EvidenceEvent(
        id=source_id,
        session_id=str(session_id or "web-quick-note"),
        author=clean_member,
        kind="user_message",
        content=clean_text,
        observed_at=now,
        metadata={
            "member_id": clean_member,
            "source": channel,
            "note_kind": clean_kind,
            "source_ref": source_ref,
            "short_title": short_title,
        },
    )
    proposal_event = EvidenceEvent(
        id=proposal_id,
        session_id=str(session_id or "web-quick-note"),
        author=clean_member,
        kind="fact_proposal",
        content=clean_text,
        observed_at=now,
        metadata={
            "member_id": clean_member,
            "derivation": derivation,
            "short_title": short_title,
            "facts": [fact_entry],
        },
    )

    workspace.save([source_event, proposal_event], {"source": channel})
    reloaded = workspace.load()
    events[:] = reloaded

    return {
        "source_id": source_id,
        "proposal_id": proposal_id,
        "fact_id": fact_id,
        "kind": clean_kind,
        "subject_key": subject_key,
        "member_id": clean_member,
        "short_title": short_title,
        "status": "proposed",
    }
