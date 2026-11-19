"""Readable session activity stream formatter (zero model dependencies).

Normalizes public EvidenceEvents into a concise, human-readable chronological-reverse
stream by filtering static repository snapshots, pairing tool_call / tool_result records
via ``paired_evidence_id``, translating raw tool/command/file/test records into plain
Chinese steps, and folding consecutive healthy exploration steps across tools.
"""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Any

from .evidence_filters import (
    DOCUMENT_RECORD_KINDS,
    as_utc_timestamp,
    is_public_raw_event,
    resolve_member_id,
)
from .models import EvidenceEvent
from .text_summary import summarize_node_title

_TEST_COMMAND_HINTS = (
    "unittest",
    "pytest",
    "_test.cjs",
    "node --check",
    "project_compass.eval",
    "cargo test",
    "npm test",
    "vitest",
    "jest",
)

_EXPLORE_COMMAND_HINTS = (
    "git status",
    "git diff",
    "git log",
    "rg ",
    "grep ",
    "ls ",
    "dir ",
    "cat ",
    "head ",
    "tail ",
    "get-childitem",
    "select-string",
    "get-content",
)

_EXPLORE_TOOLS = frozenset({
    "read_file",
    "view_file",
    "grep_search",
    "find_by_name",
    "list_dir",
    "view_file_outline",
    "view_code_item",
    "glob",
    "read",
    "grep",
    "search",
    "project_context",
    "query_state",
})

_EDIT_TOOLS = frozenset({
    "edit_file",
    "write_file",
    "replace_file_content",
    "multi_replace_file_content",
    "apply_patch",
    "write_to_file",
    "edit",
    "write",
})

_ACTION_LABELS = {
    "note": "随手记",
    "prompt": "提出指令",
    "reply": "方案与进展",
    "edit": "修改文件",
    "test": "运行测试",
    "explore": "探索上下文",
    "command": "执行命令",
    "tool": "调用工具",
    "record": "会话记录",
}

_PATH_BASENAME_RE = re.compile(r"([A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8})\b")


def _clean_preview(text: Any, limit: int = 120) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)].rstrip() + "…"


def _format_command_preview(event: EvidenceEvent) -> str:
    meta = event.metadata if isinstance(event.metadata, dict) else {}
    cmd = meta.get("command")
    if isinstance(cmd, list) and cmd:
        return " ".join(str(part) for part in cmd)
    if isinstance(cmd, str) and cmd.strip():
        return cmd.strip()
    return ""


def _short_file_name(raw_path: Any) -> str:
    normalized = str(raw_path or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    name = PurePosixPath(normalized).name
    return name or normalized


def _describe_test_suite(command_text: str) -> str:
    lowered = command_text.lower()
    if "_test.cjs" in lowered or "node --check" in lowered:
        return "前端契约检查"
    if "project_compass.eval" in lowered:
        return "五层评测基准"
    if "unittest" in lowered or "pytest" in lowered:
        return "Python 单元测试"
    return "自动化测试"


def _translate_command_action(cmd_preview: str, exit_code: int | None, fallback_text: str) -> tuple[str, str]:
    lowered = cmd_preview.lower()
    if any(hint in lowered for hint in _TEST_COMMAND_HINTS):
        suite = _describe_test_suite(cmd_preview)
        if exit_code == 0:
            return "test", f"运行{suite} · 通过"
        if isinstance(exit_code, int) and exit_code != 0:
            return "test", f"运行{suite} · 失败（退出码 {exit_code}）"
        return "test", f"运行{suite}"

    if any(hint in lowered for hint in _EXPLORE_COMMAND_HINTS) and exit_code in (None, 0):
        if "git status" in lowered or "git diff" in lowered:
            return "explore", "检查仓库变更状态"
        if "git log" in lowered:
            return "explore", "查阅最近提交历史"
        return "explore", f"检索代码与目录 · {_clean_preview(cmd_preview, 48)}"

    if isinstance(exit_code, int) and exit_code != 0:
        return "command", f"执行命令失败（退出码 {exit_code}）：{_clean_preview(cmd_preview or fallback_text, 64)}"
    if cmd_preview:
        return "command", f"执行命令 · {_clean_preview(cmd_preview, 68)}"
    return "command", _clean_preview(fallback_text, 80) or "执行命令"


def _classify_event(event: EvidenceEvent, paired: EvidenceEvent | None = None) -> tuple[str, str, int | None, str]:
    meta = event.metadata if isinstance(event.metadata, dict) else {}
    kind = str(event.kind or "")

    if kind == "user_message":
        if meta.get("source") in {"web_quick_note", "mcp_record_note"}:
            short = meta.get("short_title")
            summary = summarize_node_title(event.content, short, max_chars=36) if (short or len(str(event.content or "")) > 60) else _clean_preview(event.content)
            return "note", _ACTION_LABELS["note"], None, summary
        return "prompt", _ACTION_LABELS["prompt"], None, _clean_preview(event.content)

    if kind == "fact_proposal":
        short = meta.get("short_title")
        summary = summarize_node_title(event.content, short, max_chars=36)
        return "note", "记录待定思路", None, summary

    if kind in {"assistant_message", "agent_message"}:
        return "reply", _ACTION_LABELS["reply"], None, _clean_preview(event.content)

    if kind == "file_change":
        files = meta.get("files") if isinstance(meta.get("files"), list) else []
        names = [_short_file_name(f) for f in files if _short_file_name(f)]
        if not names and meta.get("reported_source_ref"):
            names = [_short_file_name(meta.get("reported_source_ref"))]
        if not names and meta.get("source_ref") and not str(meta.get("source_ref")).startswith("agent://"):
            names = [_short_file_name(meta.get("source_ref"))]
        if len(names) == 1:
            return "edit", _ACTION_LABELS["edit"], None, f"修改文件 · {names[0]}"
        if len(names) > 1:
            return "edit", _ACTION_LABELS["edit"], None, f"修改了 {len(names)} 个文件（{names[0]} 等）"
        return "edit", _ACTION_LABELS["edit"], None, summarize_node_title(event.content or "修改项目文件", max_chars=44)

    if kind == "test_result":
        exit_code = meta.get("exit_code") if isinstance(meta.get("exit_code"), int) else None
        cmd_preview = _format_command_preview(event) or str(event.content or "")
        _, summary = _translate_command_action("unittest " + cmd_preview if not any(h in cmd_preview.lower() for h in _TEST_COMMAND_HINTS) else cmd_preview, exit_code, event.content)
        return "test", _ACTION_LABELS["test"], exit_code, summary

    if kind == "command_execution":
        cmd_preview = _format_command_preview(event)
        exit_code = meta.get("exit_code") if isinstance(meta.get("exit_code"), int) else None
        action_kind, summary = _translate_command_action(cmd_preview, exit_code, event.content)
        return action_kind, _ACTION_LABELS[action_kind], exit_code, summary

    if kind in {"tool_call", "tool_result"}:
        call_ev = event if kind == "tool_call" else paired
        res_ev = paired if kind == "tool_call" else event
        call_meta = call_ev.metadata if call_ev and isinstance(call_ev.metadata, dict) else {}
        res_meta = res_ev.metadata if res_ev and isinstance(res_ev.metadata, dict) else {}
        exit_code = res_meta.get("exit_code") if isinstance(res_meta.get("exit_code"), int) else (
            meta.get("exit_code") if isinstance(meta.get("exit_code"), int) else None
        )
        tool_name = str(call_meta.get("tool") or meta.get("tool") or "").strip()
        tool_lower = tool_name.lower()
        cmd_preview = _format_command_preview(call_ev or event)
        raw_src = cmd_preview or (call_ev.content if call_ev else "") or (res_ev.content if res_ev else "") or event.content

        if cmd_preview and any(hint in cmd_preview.lower() for hint in _TEST_COMMAND_HINTS):
            action_kind, summary = _translate_command_action(cmd_preview, exit_code, raw_src)
            return action_kind, _ACTION_LABELS[action_kind], exit_code, summary

        if tool_lower in _EXPLORE_TOOLS or (not tool_lower and any(tok in str(raw_src).lower() for tok in ("read_file", "grep", "search"))):
            target_match = _PATH_BASENAME_RE.search(str(raw_src or ""))
            target_hint = target_match.group(1) if target_match else _clean_preview(raw_src, 36)
            if tool_lower == "project_context":
                summary = "对齐项目核心基准"
            elif tool_lower == "query_state":
                summary = f"检索项目依据 · {_clean_preview(raw_src, 36)}"
            elif target_hint:
                summary = f"查阅上下文 · {target_hint}"
            else:
                summary = "查阅代码与上下文"
            if isinstance(exit_code, int) and exit_code != 0:
                return "tool", f"查阅失败 · {tool_name or '工具'}", exit_code, summary
            return "explore", _ACTION_LABELS["explore"], exit_code, summary

        if tool_lower in _EDIT_TOOLS:
            target_match = _PATH_BASENAME_RE.search(str(raw_src or ""))
            target_hint = target_match.group(1) if target_match else _clean_preview(raw_src, 36)
            summary = f"修改文件 · {target_hint}" if target_hint else "写入或修改项目文件"
            return "edit", _ACTION_LABELS["edit"], exit_code, summary

        if tool_lower in {"record_note", "propose_fact"}:
            return "note", _ACTION_LABELS["note"], exit_code, summarize_node_title(raw_src, max_chars=36)

        if cmd_preview:
            action_kind, summary = _translate_command_action(cmd_preview, exit_code, raw_src)
            return action_kind, _ACTION_LABELS[action_kind], exit_code, summary

        label = f"{_ACTION_LABELS['tool']} · {tool_name}" if tool_name else _ACTION_LABELS["tool"]
        return "tool", label, exit_code, _clean_preview(raw_src, 80)

    return "record", _ACTION_LABELS["record"], None, _clean_preview(event.content or meta.get("source_ref") or kind)


def _timestamp_key(event: EvidenceEvent) -> tuple[float, str]:
    try:
        ts = as_utc_timestamp(event.observed_at).timestamp()
    except (TypeError, ValueError):
        ts = 0.0
    return (ts, event.id)


def build_session_activity_stream(
    events: list[EvidenceEvent],
    *,
    session_members: dict[str, str] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Build a normalized, paired, cross-tool exploration-collapsed chronological-reverse activity feed."""
    if not events:
        return []

    filtered: list[EvidenceEvent] = [
        ev for ev in events
        if is_public_raw_event(ev) and ev.kind not in DOCUMENT_RECORD_KINDS
    ]

    # Track user quick notes / MCP recorded notes so companion fact_proposal events don't duplicate stream rows.
    noted_source_ids: set[str] = {
        ev.id
        for ev in filtered
        if ev.kind == "user_message"
        and isinstance(ev.metadata, dict)
        and ev.metadata.get("source") in {"web_quick_note", "mcp_record_note"}
    }

    by_id = {ev.id: ev for ev in filtered}
    consumed_ids: set[str] = set()
    normalized_items: list[dict[str, Any]] = []

    for ev in sorted(filtered, key=_timestamp_key):
        if ev.id in consumed_ids:
            continue
        meta = ev.metadata if isinstance(ev.metadata, dict) else {}
        if ev.kind == "fact_proposal":
            facts_meta = meta.get("facts") if isinstance(meta.get("facts"), list) else []
            src_ids = {str(item.get("source_id") or "") for item in facts_meta if isinstance(item, dict)}
            if src_ids and src_ids <= noted_source_ids:
                consumed_ids.add(ev.id)
                continue

        paired_id = meta.get("paired_evidence_id")
        paired = by_id.get(str(paired_id)) if isinstance(paired_id, str) and paired_id else None
        evidence_ids = [ev.id]
        if paired is not None and paired.id != ev.id:
            consumed_ids.add(paired.id)
            evidence_ids.append(paired.id)
        consumed_ids.add(ev.id)

        owner = resolve_member_id(ev, session_members=session_members, route_documents=True)
        action_kind, action_label, exit_code, summary = _classify_event(ev, paired)
        observed_source = paired if (ev.kind == "tool_call" and paired is not None and _timestamp_key(paired) >= _timestamp_key(ev)) else ev

        normalized_items.append({
            "id": ev.id,
            "member_id": owner,
            "action_kind": action_kind,
            "action_label": action_label,
            "summary": summary or ev.id,
            "observed_at": observed_source.observed_at.isoformat(),
            "exit_code": exit_code,
            "evidence_ids": evidence_ids,
            "primary_evidence_id": ev.id,
            "collapsed_count": 1,
            "source_ref": str(meta.get("source_ref") or ""),
            "_sort_ts": _timestamp_key(observed_source),
        })

    # Reverse chronological order (newest first), collapsing adjacent healthy exploration/tool steps.
    newest_first = sorted(normalized_items, key=lambda row: row["_sort_ts"], reverse=True)
    collapsed: list[dict[str, Any]] = []
    for item in newest_first:
        prev = collapsed[-1] if collapsed else None
        is_collapsible_kind = item["action_kind"] in {"explore", "tool"}
        prev_collapsible_kind = prev is not None and prev["action_kind"] in {"explore", "tool"}
        can_collapse = (
            prev is not None
            and is_collapsible_kind
            and prev_collapsible_kind
            and item["member_id"] == prev["member_id"]
            and item["exit_code"] in (None, 0)
            and prev["exit_code"] in (None, 0)
        )
        if can_collapse:
            prev["collapsed_count"] += 1
            prev["action_kind"] = "explore"
            prev["action_label"] = _ACTION_LABELS["explore"]
            prev["summary"] = f"连续探索代码与上下文（共 {prev['collapsed_count']} 步）"
            for eid in item["evidence_ids"]:
                if eid not in prev["evidence_ids"] and len(prev["evidence_ids"]) < 6:
                    prev["evidence_ids"].append(eid)
            continue
        collapsed.append(item)

    result: list[dict[str, Any]] = []
    for row in collapsed[: max(1, int(limit))]:
        row.pop("_sort_ts", None)
        result.append(row)
    return result
