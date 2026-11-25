"""Built-in team role templates, AgentInbox config builder, and priority dispatch queue helpers."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from hashlib import sha256
from pathlib import Path
import re
import secrets
from typing import Any, Iterable

from .evidence_filters import SENSITIVE, as_utc_timestamp, normalize_text
from .models import EvidenceEvent
from .project_workspace import ProjectWorkspace
from .text_summary import summarize_node_title

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
MAX_TEAM_SEATS = 8
RESERVED_MEMBER_IDS = frozenset({"project-documents", "__local_owner__"})
_CLIENT_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TOKEN_PLACEHOLDER = "fill-your-token-here"


TEAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "solo": {
        "key": "solo",
        "label": "个人模式（本地多会话）",
        "description": "单人多会话本地并发协作，无需远程成员席位或 HTTP 令牌，通过 session_id 隔离并行窗口。",
        "mode": "solo",
        "owner_id": "owner",
        "owner_label": "个人开发者 · 主导者",
        "seats": (),
    },
    "product_delivery": {
        "key": "product_delivery",
        "label": "通用产品交付组",
        "description": "项目负责人把控目标与确认；产品方案、研发实现与测试验收三席并行提交依据与提案。",
        "mode": "team",
        "owner_id": "lead",
        "owner_label": "项目负责人",
        "seats": (
            {
                "member_id": "planner",
                "client_id": "planner",
                "session_id": "session-planner",
                "agent": "claude-code",
                "role_label": "产品与方案席",
                "role_brief": "负责需求拆解、边界梳理与待验证前提记录",
            },
            {
                "member_id": "developer",
                "client_id": "developer",
                "session_id": "session-developer",
                "agent": "claude-code",
                "role_label": "研发实现席",
                "role_brief": "负责核心功能实现、代码变更与自测结果上报",
            },
            {
                "member_id": "qa",
                "client_id": "qa",
                "session_id": "session-qa",
                "agent": "claude-code",
                "role_label": "测试与验收席",
                "role_brief": "负责回归测试、边界排查与待修问题记录",
            },
        ),
    },
    "fullstack_engineering": {
        "key": "fullstack_engineering",
        "label": "全栈软件研发组",
        "description": "技术负责人确认主线事项；前端、后端与测试审查席按独立令牌并行汇报证据与提案。",
        "mode": "team",
        "owner_id": "owner",
        "owner_label": "技术负责人",
        "seats": (
            {
                "member_id": "frontend",
                "client_id": "frontend",
                "session_id": "session-frontend",
                "agent": "claude-code",
                "role_label": "前端交互席",
                "role_brief": "负责界面布局、交互响应与无障碍验证",
            },
            {
                "member_id": "backend",
                "client_id": "backend",
                "session_id": "session-backend",
                "agent": "claude-code",
                "role_label": "后端与接口席",
                "role_brief": "负责数据模型、接口契约与鉴权边界",
            },
            {
                "member_id": "reviewer",
                "client_id": "reviewer",
                "session_id": "session-reviewer",
                "agent": "claude-code",
                "role_label": "测试与审查席",
                "role_brief": "负责单元测试、回归契约与异常边界排查",
            },
        ),
    },
    "research_lab": {
        "key": "research_lab",
        "label": "科研 / 方案攻坚组",
        "description": "主笔负责人确认实验结论；调研与复现席位各自沉淀多源证据与消融对照结果。",
        "mode": "team",
        "owner_id": "lead",
        "owner_label": "主笔负责人",
        "seats": (
            {
                "member_id": "researcher",
                "client_id": "researcher",
                "session_id": "session-researcher",
                "agent": "claude-code",
                "role_label": "调研与文献席",
                "role_brief": "负责多源检索、竞品证据归档与缺口标记",
            },
            {
                "member_id": "verifier",
                "client_id": "verifier",
                "session_id": "session-verifier",
                "agent": "claude-code",
                "role_label": "实验与复现席",
                "role_brief": "负责脚本跑分、消融对照与复现记录",
            },
        ),
    },
}


def _validate_text(value: Any, field_name: str, limit: int, *, slug: bool = False, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains invalid null byte")
    cleaned = normalize_text(value).strip()
    if not cleaned:
        if allow_empty:
            return ""
        raise ValueError(f"{field_name} cannot be blank")
    if len(cleaned) > limit:
        raise ValueError(f"{field_name} exceeds maximum length of {limit}")
    if SENSITIVE.search(cleaned) is not None:
        raise ValueError(f"{field_name} contains sensitive credential material")
    if slug and not _CLIENT_SLUG_RE.fullmatch(cleaned):
        raise ValueError(f"{field_name} must match [A-Za-z0-9_.-]+")
    return cleaned


def _derive_client_slug(member_id: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", member_id).strip(".-_")
    if not slug or not _CLIENT_SLUG_RE.fullmatch(slug):
        slug = f"seat-{index}"
    return slug[:64]


def _derive_token_env(client_id: str, index: int, seen_envs: set[str]) -> str:
    suffix = re.sub(r"[^A-Z0-9_]+", "_", client_id.upper()).strip("_") or f"SEAT_{index}"
    candidate = f"COMPASS_TOKEN_{suffix}"
    if candidate in seen_envs:
        candidate = f"{candidate}_{index}"
    if not _ENV_NAME_RE.fullmatch(candidate):
        candidate = f"COMPASS_TOKEN_SEAT_{index}"
    return candidate


def _format_mcp_snippet(
    client_type: str,
    *,
    project_path: str,
    member_id: str,
    session_id: str,
    base_url: str | None = None,
    token_env: str | None = None,
) -> dict[str, Any]:
    args = ["-m", "project_compass.mcp_server"]
    env: dict[str, str] = {}
    if base_url:
        args.extend(["--base-url", base_url])
        if token_env:
            env[token_env] = _TOKEN_PLACEHOLDER
    args.extend([
        "--project-path",
        project_path,
        "--member-id",
        member_id,
        "--session-id",
        session_id,
    ])
    server_entry: dict[str, Any] = {
        "command": "python",
        "args": args,
    }
    if env:
        server_entry["env"] = env
    if client_type == "antigravity":
        return {
            "name": "project-compass",
            "protocol": "mcp-stdio",
            **server_entry,
        }
    return {
        "mcpServers": {
            "project-compass": server_entry,
        }
    }


def list_team_templates() -> list[dict[str, Any]]:
    """Return serializable summaries of all built-in team templates for UI and CLI."""
    summaries: list[dict[str, Any]] = []
    for key in ("solo", "product_delivery", "fullstack_engineering", "research_lab"):
        tpl = TEAM_TEMPLATES[key]
        seats = [
            {
                "member_id": seat["member_id"],
                "client_id": seat["client_id"],
                "session_id": seat["session_id"],
                "agent": seat["agent"],
                "role_label": seat["role_label"],
                "role_brief": seat["role_brief"],
            }
            for seat in tpl["seats"]
        ]
        summaries.append({
            "key": tpl["key"],
            "label": tpl["label"],
            "description": tpl["description"],
            "mode": tpl["mode"],
            "owner_id": tpl["owner_id"],
            "owner_label": tpl["owner_label"],
            "seat_count": len(seats),
            "seats": seats,
            "supports_custom_seats": True,
        })
    return summaries


def build_team_config(
    template_key: str,
    project_path: str | Path,
    *,
    owner_id: str | None = None,
    custom_seats: list[dict[str, str]] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    client: str = "claude",
) -> dict[str, Any]:
    """Build an AgentInbox config skeleton (token_env only) and per-seat MCP setup snippets."""
    key = _validate_text(str(template_key or ""), "template_key", 64)
    if key != "custom" and key not in TEAM_TEMPLATES:
        raise ValueError(f"unknown team template: {key}")

    client_type = (client or "claude").strip().lower()
    if client_type not in {"claude", "cursor", "antigravity"}:
        raise ValueError(f"unsupported MCP client: {client}")

    resolved_project = str(Path(project_path).expanduser().resolve())
    clean_base_url = _validate_text(base_url, "base_url", 512).rstrip("/")
    if not clean_base_url:
        raise ValueError("base_url cannot be blank")

    template = TEAM_TEMPLATES.get(key)
    default_owner = template["owner_id"] if template else "owner"
    effective_owner_id = (
        _validate_text(owner_id, "owner_id", 120) if owner_id is not None else default_owner
    )
    if effective_owner_id in RESERVED_MEMBER_IDS:
        raise ValueError(f"invalid reserved owner_id: {effective_owner_id}")
    owner_label = template["owner_label"] if template else "项目负责人"

    if key == "solo":
        if custom_seats is not None:
            if not isinstance(custom_seats, list):
                raise ValueError("custom_seats must be a list")
            if len(custom_seats) > 0:
                raise ValueError("solo template requires 0 remote seats; use 'custom' or a team template")
        raw_seats: list[dict[str, str]] = []
    elif key == "custom":
        if not isinstance(custom_seats, list) or not 1 <= len(custom_seats) <= MAX_TEAM_SEATS:
            raise ValueError(f"custom template requires 1 to {MAX_TEAM_SEATS} seats")
        raw_seats = custom_seats
    else:
        if custom_seats is not None:
            if not isinstance(custom_seats, list) or not 1 <= len(custom_seats) <= MAX_TEAM_SEATS:
                raise ValueError(f"team template requires 1 to {MAX_TEAM_SEATS} seats")
            raw_seats = custom_seats
        else:
            raw_seats = [dict(seat) for seat in template["seats"]]  # type: ignore[index]

    inbox_clients: list[dict[str, str]] = []
    seat_snippets: list[dict[str, Any]] = []
    seen_members: set[str] = set()
    seen_clients: set[str] = set()
    seen_sessions: set[str] = set()
    seen_envs: set[str] = set()

    for idx, seat in enumerate(raw_seats, start=1):
        if not isinstance(seat, dict):
            raise ValueError(f"seat #{idx} must be an object")

        member_id = _validate_text(seat.get("member_id"), "member_id", 120)
        if member_id == effective_owner_id or member_id in RESERVED_MEMBER_IDS:
            raise ValueError(f"seat member_id conflicts with owner or reserved identity: {member_id}")
        if member_id in seen_members:
            raise ValueError(f"duplicate member_id: {member_id}")
        seen_members.add(member_id)

        role_label = _validate_text(seat.get("role_label"), "role_label", 80)
        raw_brief = seat.get("role_brief", "")
        role_brief = _validate_text(
            "" if raw_brief is None else raw_brief,
            "role_brief",
            240,
            allow_empty=True,
        )

        raw_client_id = seat.get("client_id")
        if raw_client_id is not None and str(raw_client_id).strip():
            client_id = _validate_text(raw_client_id, "client_id", 64, slug=True)
        else:
            client_id = _derive_client_slug(member_id, idx)
        if client_id in seen_clients:
            raise ValueError(f"duplicate client_id: {client_id}")
        seen_clients.add(client_id)

        raw_session_id = seat.get("session_id")
        if raw_session_id is not None and str(raw_session_id).strip():
            session_id = _validate_text(raw_session_id, "session_id", 256)
        else:
            session_id = f"session-{client_id}"
        if session_id in seen_sessions:
            raise ValueError(f"duplicate session_id: {session_id}")
        seen_sessions.add(session_id)

        agent = _validate_text(seat.get("agent") or "claude-code", "agent", 64)

        raw_token_env = seat.get("token_env")
        if raw_token_env is not None and str(raw_token_env).strip():
            token_env = _validate_text(raw_token_env, "token_env", 128)
            if not _ENV_NAME_RE.fullmatch(token_env):
                raise ValueError(f"invalid token_env format: {token_env}")
            if token_env in seen_envs:
                raise ValueError(f"duplicate token_env: {token_env}")
        else:
            token_env = _derive_token_env(client_id, idx, seen_envs)
        seen_envs.add(token_env)

        inbox_entry: dict[str, str] = {
            "client_id": client_id,
            "member_id": member_id,
            "session_id": session_id,
            "agent": agent,
            "token_env": token_env,
            "role_label": role_label,
        }
        if role_brief:
            inbox_entry["role_brief"] = role_brief
        inbox_clients.append(inbox_entry)

        seat_snippets.append({
            "client_id": client_id,
            "member_id": member_id,
            "session_id": session_id,
            "agent": agent,
            "role_label": role_label,
            "role_brief": role_brief,
            "token_env": token_env,
            "mcp_config": _format_mcp_snippet(
                client_type,
                project_path=resolved_project,
                member_id=member_id,
                session_id=session_id,
                base_url=clean_base_url,
                token_env=token_env,
            ),
        })

    local_sessions: list[dict[str, Any]] = []
    if key == "solo":
        for sid, label in (("session-main", "主开发会话"), ("session-parallel", "并行调研/测试会话")):
            local_sessions.append({
                "member_id": effective_owner_id,
                "session_id": sid,
                "role_label": label,
                "mcp_config": _format_mcp_snippet(
                    client_type,
                    project_path=resolved_project,
                    member_id=effective_owner_id,
                    session_id=sid,
                ),
            })

    return {
        "schema_version": 1,
        "template_key": key,
        "template_label": template["label"] if template else "自定义团队模板",
        "mode": "solo" if key == "solo" else "team",
        "project_path": resolved_project,
        "base_url": clean_base_url,
        "owner_id": effective_owner_id,
        "owner_label": owner_label,
        "authority_model": {
            "two_tier_enforced": True,
            "owner_id": effective_owner_id,
            "owner_actions": ["confirm_fact", "reject_fact", "resolve_conflict", "priority_dispatch"],
            "seat_actions": ["append_evidence", "propose_fact", "record_note", "read_state"],
        },
        "agent_inbox_config": (
            {
                "schema_version": 1,
                "project_path": resolved_project,
                "owner_id": effective_owner_id,
                "clients": inbox_clients,
            }
            if inbox_clients
            else None
        ),
        "seats": seat_snippets,
        "local_sessions": local_sessions,
    }


def record_priority_dispatch(
    workspace: ProjectWorkspace,
    *,
    fact_id: str,
    title: str,
    value: str,
    evidence_ids: list[str] | tuple[str, ...],
    actor: str,
    mode: str = "queue",
    note: str = "",
) -> dict[str, Any]:
    """Persist an immutable human-priority dispatch event in the append-only workspace ledger."""
    clean_fact_id = _validate_text(fact_id, "fact_id", 128)
    clean_value = _validate_text(value, "value", 4000)
    raw_title = _validate_text("" if title is None else title, "title", 120, allow_empty=True)
    clean_title = raw_title or summarize_node_title(clean_value, max_chars=28)
    clean_actor = _validate_text(actor, "actor", 120)
    if clean_actor in RESERVED_MEMBER_IDS:
        raise ValueError(f"invalid dispatch actor: {clean_actor}")
    clean_mode = _validate_text("" if mode is None else mode, "mode", 64, allow_empty=True) or "queue"
    clean_note = _validate_text("" if note is None else note, "note", 1000, allow_empty=True)

    if isinstance(evidence_ids, (str, bytes)) or not isinstance(evidence_ids, Iterable):
        raise ValueError("evidence_ids must be a list or tuple of evidence ID strings")
    clean_evidence_ids: list[str] = []
    seen_eids: set[str] = set()
    for raw_eid in evidence_ids:
        eid = _validate_text(raw_eid, "evidence_id", 128)
        if eid not in seen_eids:
            seen_eids.add(eid)
            clean_evidence_ids.append(eid)
        if len(clean_evidence_ids) > 32:
            raise ValueError("evidence_ids exceeds limit of 32 entries")

    now = datetime.now(timezone.utc)
    nonce = secrets.token_hex(8)
    digest = sha256(
        f"{clean_fact_id}:{clean_actor}:{clean_mode}:{now.isoformat()}:{nonce}:{clean_value}".encode("utf-8")
    ).hexdigest()[:16]
    event_id = f"dispatch-{digest}"

    content = f"[优先派发:{clean_mode}] {clean_title} — {clean_value}"
    if clean_note:
        content = f"{content}（附注：{clean_note}）"

    metadata: dict[str, Any] = {
        "source": "compass_priority_dispatch",
        "actor_type": "human",
        "member_id": clean_actor,
        "fact_id": clean_fact_id,
        "dispatch_mode": clean_mode,
        "short_title": clean_title,
        "dispatch_value": clean_value,
        "evidence_ids": clean_evidence_ids,
        "dispatch_nonce": nonce,
    }
    if clean_note:
        metadata["dispatch_note"] = clean_note

    event = EvidenceEvent(
        id=event_id,
        session_id="compass-dispatch",
        author=clean_actor,
        kind="user_message",
        content=content,
        observed_at=now,
        metadata=metadata,
    )
    workspace.save([event], {"source": "compass_priority_dispatch"})

    return {
        "id": event_id,
        "fact_id": clean_fact_id,
        "title": clean_title,
        "value": clean_value,
        "evidence_ids": clean_evidence_ids,
        "actor": clean_actor,
        "mode": clean_mode,
        "observed_at": now.isoformat(),
        "note": clean_note,
    }


def extract_priority_dispatches(events: list[EvidenceEvent], limit: int = 8) -> list[dict[str, Any]]:
    """Scan events in reverse chronological order and extract human-queued priority dispatches."""
    if limit <= 0:
        return []

    matched: list[tuple[datetime, int, EvidenceEvent]] = []
    for idx, event in enumerate(events):
        meta = getattr(event, "metadata", None)
        if not isinstance(meta, dict) or meta.get("source") != "compass_priority_dispatch":
            continue
        try:
            stamp = as_utc_timestamp(event.observed_at)
        except (TypeError, ValueError):
            stamp = datetime.min.replace(tzinfo=timezone.utc)
        matched.append((stamp, idx, event))

    matched.sort(key=lambda item: (item[0], item[1]), reverse=True)

    results: list[dict[str, Any]] = []
    for _stamp, _idx, event in matched[:limit]:
        meta = event.metadata if isinstance(event.metadata, dict) else {}
        raw_value = (
            str(meta["dispatch_value"])
            if meta.get("dispatch_value") is not None
            else str(getattr(event, "content", "") or "")
        )
        raw_title = str(meta.get("short_title") or "").strip() or summarize_node_title(raw_value, max_chars=28)
        raw_eids = meta.get("evidence_ids") if isinstance(meta.get("evidence_ids"), (list, tuple)) else []
        observed = getattr(event, "observed_at", "")
        observed_str = observed.isoformat() if isinstance(observed, datetime) else str(observed)
        results.append({
            "id": str(event.id),
            "fact_id": str(meta.get("fact_id") or ""),
            "title": raw_title,
            "value": raw_value,
            "evidence_ids": [str(eid) for eid in raw_eids if str(eid).strip()],
            "actor": str(meta.get("member_id") or getattr(event, "author", "") or ""),
            "mode": str(meta.get("dispatch_mode") or "queue"),
            "observed_at": observed_str,
            "note": str(meta.get("dispatch_note") or ""),
        })
    return results
