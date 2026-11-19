"""Deterministic, model-free extraction of bounded candidate facts from project documents."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .candidate_extraction import current_file_snapshots, validate_candidates
from .evidence_filters import SENSITIVE
from .extraction_progress import ExtractionProgress, source_key
from .fact_engine import derive_facts
from .limits import MAX_CANDIDATES_PER_PAYLOAD, MAX_FACT_QUOTE_CHARS
from .models import EvidenceEvent


RULE = "doc-structure-v1"
_MAX_GOALS = 2
_MAX_DECISIONS = 8
_MAX_TASKS = 12
_MAX_DOC_QUOTE_CHARS = min(650, MAX_FACT_QUOTE_CHARS)

_GOAL_FILES = ("README.MD", "PRODUCT_GOAL.MD", "PRODUCT_SPEC.MD")
_DATE_PARA_RE = re.compile(
    r"^(20\d{2}-\d{2}-\d{2})\s+[^\n]+(?:\n(?!\s*\n|20\d{2}-\d{2}-\d{2}\s)[^\n]+)*",
    re.MULTILINE,
)
_HEADING_DECISION_RE = re.compile(
    r"^#{1,4}\s+(20\d{2}-\d{2}-\d{2}[:：]?\s+[^\n]+)$",
    re.MULTILINE,
)
_SENTENCE_END_RE = re.compile(r"(?:。|[a-zA-Z0-9\)\]\"'”）]\.(?=\s|$))")
_CHECKBOX_RE = re.compile(r"^[ \t]*[-*]\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)
_NUMBERED_STAGE_RE = re.compile(r"^[ \t]*\d+\.\s+(\*\*[^\n]{8,})$", re.MULTILINE)
_EXT_BEFORE_DOT_RE = re.compile(r"(?:md|py|js|cjs|mjs|json|html|css|yml|yaml|txt|ts)\.$", re.I)
_COMPLETED_MILESTONE_TOKENS = (
    "已完成",
    "完成",
    "闭环",
    "收口",
    "止血",
    "交付",
    "定型",
    "封板",
    "封存",
    "就绪",
    "跑通",
    "已验收",
)


def _is_safe_quote(quote: str) -> bool:
    if not quote or not (8 <= len(quote) <= _MAX_DOC_QUOTE_CHARS):
        return False
    if "<" in quote or ">" in quote:
        return False
    return SENSITIVE.search(quote) is None


def _extract_readme_goal(content: str) -> str | None:
    in_fence = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.startswith(("#", "---", "===", ">", "-", "*", "![", "[![", "<")):
            continue
        if re.match(r"^(?:状态|Status|Last\s+updated|日期|版本)[：:]", line, re.I):
            continue
        if re.match(r"^\d+\.\s", line):
            continue
        # Skip standalone bold slogans without sentence punctuation.
        if line.startswith("**") and line.endswith("**") and "。" not in line and ". " not in line:
            continue
        if not (15 <= len(line) <= 240):
            continue
        if "[" in line and "](" in line:
            continue
        if _is_safe_quote(line):
            return line
    return None


def _slice_decision_sentence(para: str) -> str:
    if len(para) <= 280 and ("\n" not in para or para.count("\n") <= 2):
        # Still prefer a clean sentence boundary when multiple sentences exist.
        pass
    for match in _SENTENCE_END_RE.finditer(para):
        end = match.end()
        prefix = para[:end]
        if end < 45:
            continue
        if _EXT_BEFORE_DOT_RE.search(prefix):
            continue
        if end <= _MAX_DOC_QUOTE_CHARS:
            return prefix.strip()
        break
    first_line = para.splitlines()[0].strip()
    if len(first_line) >= 24 and len(para) <= _MAX_DOC_QUOTE_CHARS:
        return para.strip()
    return first_line[:_MAX_DOC_QUOTE_CHARS].strip()


def _extract_agents_goal(content: str) -> str | None:
    goal = _extract_readme_goal(content)
    if goal:
        return goal
    in_fence = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith(("#", "---", "===", "<!--")):
            continue
        candidate = ""
        if line.startswith(">"):
            candidate = line.lstrip(">").strip()
        elif re.match(r"^(?:[-*]|\d+\.)\s+", line):
            candidate = re.sub(r"^(?:[-*]|\d+\.)\s+", "", line, count=1).strip()
        if candidate and candidate in content and (15 <= len(candidate) <= 240) and _is_safe_quote(candidate):
            return candidate
    return None


def _extract_decisions(content: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    seen_quotes: set[str] = set()
    for match in _DATE_PARA_RE.finditer(content):
        para = match.group(0).strip()
        quote = _slice_decision_sentence(para)
        if _is_safe_quote(quote) and quote not in seen_quotes:
            seen_quotes.add(quote)
            matches.append((match.start(), quote))
    for match in _HEADING_DECISION_RE.finditer(content):
        quote = match.group(1).strip()
        if _is_safe_quote(quote) and quote not in seen_quotes:
            seen_quotes.add(quote)
            matches.append((match.start(), quote))
    matches.sort(key=lambda item: item[0])
    return [quote for _, quote in matches[-_MAX_DECISIONS:]]


def _extract_tasks(content: str, name_upper: str) -> list[tuple[str, str]]:
    tasks: list[tuple[str, str]] = []
    for match in _CHECKBOX_RE.finditer(content):
        checked = match.group(1).lower() == "x"
        quote = match.group(2).strip()
        if _is_safe_quote(quote):
            tasks.append((quote, "reported_complete" if checked else "pending"))
    if not tasks and name_upper == "HANDOFF.MD":
        for match in _NUMBERED_STAGE_RE.finditer(content):
            quote = match.group(1).strip().rstrip("：:").strip()
            if not quote or not _is_safe_quote(quote):
                continue
            neg_hint = any(tok in quote for tok in ("未完成", "待完成", "尚未完成"))
            done_hint = (not neg_hint) and any(tok in quote for tok in _COMPLETED_MILESTONE_TOKENS)
            tasks.append((quote, "reported_complete" if done_hint else "pending"))
        if tasks:
            return list(reversed(tasks[-_MAX_TASKS:]))
    return tasks


def _doc_priority(event: EvidenceEvent) -> tuple[int, str, str]:
    rel = str(event.metadata.get("source_ref") or event.id).replace("\\", "/")
    upper = Path(rel).name.upper()
    if upper == "README.MD":
        rank = 0
    elif upper == "PRODUCT_GOAL.MD":
        rank = 1
    elif upper == "PRODUCT_SPEC.MD":
        rank = 2
    elif upper == "AGENTS.MD":
        rank = 3
    elif upper == "DECISIONS.MD":
        rank = 4
    elif upper == "PROGRESS.MD":
        rank = 5
    elif upper == "HANDOFF.MD":
        rank = 6
    elif "PLAN" in upper:
        rank = 7
    elif upper == "ROADMAP.MD":
        rank = 8
    else:
        rank = 9
    return (rank, rel.casefold(), event.id)


def scan_document_candidates(
    events: list[EvidenceEvent],
    *,
    cursors: dict[str, int] | None = None,
) -> tuple[list[EvidenceEvent], dict[str, int], dict[str, Any]]:
    """Deterministically extract bounded goal/decision/task proposals from current doc snapshots."""
    cursor_map = dict(cursors or {})
    snapshots = sorted(current_file_snapshots(events), key=_doc_priority)
    keyed = [(source, source_key(source)) for source in snapshots]
    for source, key in keyed:
        cur = cursor_map.get(key, 0)
        if type(cur) is not int or cur not in (0, len(source.content)):
            raise ValueError("document fact rule requires a whole immutable source cursor")

    covered = [(f.evidence_ids, f.quote or f.value) for f in derive_facts(events)]
    existing_goals = sum(1 for f in derive_facts(events) if f.kind.value == "goal" and f.claim_type == "document_statement")

    rows: list[dict[str, Any]] = []
    updates: dict[str, int] = {}
    seen_pairs: set[tuple[str, str]] = set()
    counts = {"goal": existing_goals, "decision": 0, "task": 0}
    limits = {"goal": _MAX_GOALS, "decision": _MAX_DECISIONS, "task": _MAX_TASKS}
    visited = 0

    def _add_candidate(source: EvidenceEvent, kind: str, topic_prefix: str, quote: str, task_state: str = "unknown") -> bool:
        if len(rows) >= min(22, MAX_CANDIDATES_PER_PAYLOAD):
            return False
        if counts[kind] >= limits[kind]:
            return False
        if not quote or quote not in source.content:
            return False
        pair = (source.id, quote)
        if pair in seen_pairs:
            return False
        if any(source.id in ids and quote in existing for ids, existing in covered):
            return False
        digest = sha256(f"{kind}:{quote}".encode("utf-8")).hexdigest()[:12]
        rows.append(
            {
                "source_id": source.id,
                "kind": kind,
                "subject_key": f"{topic_prefix}.{digest}",
                "quote": quote,
                "task_state": task_state,
            }
        )
        seen_pairs.add(pair)
        covered.append(([source.id], quote))
        counts[kind] += 1
        return True

    for source, key in keyed:
        if cursor_map.get(key, 0) == len(source.content):
            continue
        rel = str(source.metadata.get("source_ref") or "").replace("\\", "/")
        name_upper = Path(rel).name.upper()
        visited += 1
        updates[key] = len(source.content)

        if name_upper in _GOAL_FILES and counts["goal"] < limits["goal"]:
            goal_quote = _extract_readme_goal(source.content)
            if goal_quote:
                _add_candidate(source, "goal", "doc.goal", goal_quote, "unknown")
        elif name_upper == "AGENTS.MD" and counts["goal"] == 0:
            goal_quote = _extract_agents_goal(source.content)
            if goal_quote:
                _add_candidate(source, "goal", "doc.goal", goal_quote, "unknown")

        if name_upper == "DECISIONS.MD" and counts["decision"] < limits["decision"]:
            for dec_quote in _extract_decisions(source.content):
                if not _add_candidate(source, "decision", "doc.decision", dec_quote, "unknown"):
                    if counts["decision"] >= limits["decision"] or len(rows) >= 22:
                        break

        is_task_doc = (
            name_upper in {"PROGRESS.MD", "HANDOFF.MD", "ROADMAP.MD"}
            or "PLAN" in name_upper
            or "CHECKLIST" in name_upper
        )
        if is_task_doc and counts["task"] < limits["task"]:
            for task_quote, task_state in _extract_tasks(source.content, name_upper):
                if not _add_candidate(source, "task", "doc.task", task_quote, task_state):
                    if counts["task"] >= limits["task"] or len(rows) >= 22:
                        break

    proposals = [
        replace(proposal, metadata={**proposal.metadata, "derivation": RULE})
        for proposal in validate_candidates(events, {"candidates": rows})
    ]
    merged = {**cursor_map, **updates}
    complete = sum(1 for source, key in keyed if merged.get(key, 0) == len(source.content))
    status = {
        "enabled": True,
        "rule": RULE,
        "eligible_sources": len(keyed),
        "completed_sources": complete,
        "pending_sources": len(keyed) - complete,
        "batch_sources": visited,
        "semantic_coverage": False,
    }
    return proposals, updates, status


def record_document_candidates(events: list[EvidenceEvent], workspace=None) -> dict[str, Any]:
    """Persist deterministic document candidate proposals before acknowledging progress cursors."""
    progress = (
        ExtractionProgress(workspace.state_path.parent / "doc-fact-rules-v2", namespace=f"{RULE}:scan-v2")
        if workspace is not None
        else None
    )
    proposals, updates, status = scan_document_candidates(
        events,
        cursors=progress.load() if progress is not None else None,
    )
    if proposals:
        if workspace is not None:
            workspace.save(proposals)
            events[:] = workspace.load()
        else:
            events.extend(proposals)
    if progress is not None and updates:
        progress.acknowledge(updates)
    return {
        "doc_fact_scan": status,
        "new_doc_proposals": len(proposals),
        "updated": bool(proposals),
    }
