"""Cognitive asset export engine for Project Compass.

Transforms verified project state and evidence chains into GitHub Issues,
Pull Request templates, and Product Requirement Documents (PRDs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _clean_text(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, dict):
        text = str(val.get("value") or val.get("label") or val.get("content") or "").strip()
        if not text:
            text = str(val)
    else:
        text = str(val).strip()
    return text.replace("@[Quote]", "").strip()


def _is_task_completed(item: Any) -> bool:
    """Return True only when a structured task record explicitly marks completion and is not rejected."""
    return (
        isinstance(item, dict)
        and item.get("task_state") in {"completed", "reported_complete"}
        and item.get("status") != "rejected"
    )


def export_github_issue(state: dict[str, Any]) -> str:
    """Generate a structured, ready-to-paste GitHub Issue from verified state."""
    project = state.get("project", {})
    team = state.get("team", {})
    facts = team.get("facts", [])
    brief = state.get("handoff_brief", {})
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"# [Project Issue] {project.get('name', 'Project Compass')}",
        "",
        f"> 自动生成自 Project Compass 协作证据看板 · 导出时间：{exported_at}",
        "",
        "## 🎯 核心目标与焦点 (Core Goal & Focus)",
    ]

    goal_text = _clean_text(brief.get("focus_goal") or project.get("goal") or "待定核心目标")
    lines.append(f"- **目标**：{goal_text}")
    lines.append("")

    lines.append("## 📋 已确认事实与关键决策 (Confirmed Facts & Decisions)")
    accepted_decisions = brief.get("accepted_decisions") or []
    if accepted_decisions:
        for dec in accepted_decisions:
            lines.append(f"- [x] **决策**：{_clean_text(dec)}")
    else:
        confirmed_facts = [f for f in facts if f.get("status") == "accepted"]
        if confirmed_facts:
            for f in confirmed_facts:
                ev_str = f" `[{f['evidence_ids'][0]}]`" if f.get("evidence_ids") else ""
                lines.append(f"- [x] {_clean_text(f.get('value'))}{ev_str}")
        else:
            lines.append("_暂无已确认决策，当前为初始讨论阶段。_")
    lines.append("")

    lines.append("## ⏳ 待办与推进清单 (Action Items & Task Checklist)")
    open_todos = brief.get("open_todos") or []
    if open_todos:
        for todo in open_todos:
            mark = "x" if _is_task_completed(todo) else " "
            lines.append(f"- [{mark}] {_clean_text(todo)}")
    else:
        task_facts = [f for f in facts if f.get("kind") == "task"]
        if task_facts:
            for t in task_facts:
                mark = "x" if _is_task_completed(t) else " "
                ev_str = f" `[{t['evidence_ids'][0]}]`" if t.get("evidence_ids") else ""
                lines.append(f"- [{mark}] {_clean_text(t.get('value'))}{ev_str}")
        else:
            lines.append("_当前暂无已提取的结构化待办任务。_")
    lines.append("")

    lines.append("## ⚠️ 待审候选事实与待核对前提 (Pending Candidates)")
    pending = brief.get("pending_candidates") or []
    if pending:
        for p in pending:
            lines.append(f"- [ ] **待核对**：{_clean_text(p)}")
    else:
        lines.append("_所有当前事实均已获得负责人确认。_")
    lines.append("")

    lines.append("---")
    lines.append(f"*Verified with Project Compass Evidence Engine · Total Evidence Items: {project.get('evidence_count', len(state.get('evidence', [])))}*")
    return "\n".join(lines)


def export_pull_request(state: dict[str, Any]) -> str:
    """Generate a structured Pull Request description for multi-agent code review."""
    project = state.get("project", {})
    brief = state.get("handoff_brief", {})
    presence = state.get("session_presence", {})
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"## 🚀 PR: {project.get('name', 'Project Compass')} Feature Implementation",
        "",
        f"> 由 Project Compass 证据看板自动生成 · 导出时间：{exported_at}",
        "",
        "### 📌 关联目标与背景 (Context & Goal)",
        f"- **目标**：{_clean_text(brief.get('focus_goal') or '实现核心功能')}",
        "",
        "### 🛠️ 本次变更落地之关键事实与行动项 (Delivered Facts & Tasks)",
    ]

    todos = brief.get("open_todos") or []
    if todos:
        for todo in todos:
            mark = "x" if _is_task_completed(todo) else " "
            lines.append(f"- [{mark}] {_clean_text(todo)}")
    else:
        lines.append("_当前尚无结构化待办任务记录。_")
    lines.append("")

    lines.append("### 🔍 跨生态在场与评审状态 (Presence & Reviews)")
    team_presence = presence.get("team", {})
    lines.append(f"- **团队确认事实数**：{team_presence.get('accepted_count', 0)} 项")
    lines.append(f"- **待核对候选数**：{team_presence.get('pending_count', 0)} 项")
    members = presence.get("members", [])
    valid_members = [m.get("member_id") or m.get("id") for m in members if m.get("member_id") or m.get("id")]
    if valid_members:
        mem_str = ", ".join(f"`{mid}`" for mid in valid_members)
        lines.append(f"- **协同参与者/Agent**：{mem_str}")
    else:
        lines.append("- **协同参与者/Agent**：_未记录会话成员_")
    lines.append("")

    lines.append("### 🧪 自动化回归与质量断言 (Verification & Tests)")
    commands: list[str] = []
    for item in state.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        cmd_preview = item.get("command_preview")
        if isinstance(cmd_preview, str) and cmd_preview.strip():
            cmd_line = cmd_preview.strip()
            if cmd_line not in commands:
                commands.append(cmd_line)
        if len(commands) >= 3:
            break
    if commands:
        lines.append("```bash")
        lines.extend(commands)
        lines.append("```")
    else:
        lines.append("_当前证据链尚未记录自动化测试命令，提交前请补充本地实跑验证记录。_")
    lines.append("- [ ] 单元测试全部通过（待提交前本地实跑核对）")
    lines.append("- [ ] 集成契约或端到端验证已实跑核对")
    lines.append("- [ ] 遵循 IEEE TSE 2001 PBR 三视角代码审查无 P0/P1 缺陷")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by Project Compass Cognitive Engine*")
    return "\n".join(lines)


def export_prd(state: dict[str, Any]) -> str:
    """Generate a formal Product Requirement Document (PRD / SPEC) Markdown."""
    project = state.get("project", {})
    team = state.get("team", {})
    brief = state.get("handoff_brief", {})
    thinking = state.get("thinking_line") or team.get("thinking_line") or {}
    timeline = state.get("chapter_timeline") or team.get("timeline_chapters") or []
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    conflicts = team.get("conflicts") or []
    assumptions = [f for f in (team.get("facts") or []) if f.get("kind") == "assumption"]
    if conflicts:
        conflict_keys = ", ".join(f"`{c.get('subject_key')}`" for c in conflicts[:4] if c.get("subject_key"))
        problem_summary = f"当前存在 {len(conflicts)} 组待裁决技术分歧（涉及 {conflict_keys or '未命名主题'}），需结合原始证据对比并显式确认共识。"
    elif assumptions:
        problem_summary = f"当前仍存在 {len(assumptions)} 项未验证前提（例如：{_clean_text(assumptions[0].get('value'))}），需补充执行证据核实。"
    else:
        problem_summary = "[待补充问题背景：尚未从会话或文档证据中提取技术分歧或未验证前提]"
    goal_summary = _clean_text(brief.get("focus_goal") or project.get("goal")) or "[待确认核心目标：请运行项目扫描或确认目标候选]"

    lines: list[str] = [
        f"# 产品需求与技术规格说明书 (PRD / SPEC)",
        f"## 项目：{project.get('name', 'Project Compass')}",
        "",
        f"- **文档版本**：v1.5",
        f"- **生成时间**：{exported_at}",
        f"- **可追溯证据总量**：{project.get('evidence_count', len(state.get('evidence', [])))} 条",
        "",
        "---",
        "",
        "## 1. 产品核心愿景与问题定义",
        f"**核心背景与待解分歧**：{problem_summary}",
        f"**核心目标**：{goal_summary}",
        "",
        "## 2. 阶段演进脉络与关键里程碑 (Chapter Timeline)",
    ]

    if timeline:
        for chapter in timeline:
            idx = chapter.get("id") or chapter.get("sequence") or chapter.get("chapter_id") or "00"
            title = chapter.get("title", "未命名阶段")
            summary = _clean_text(chapter.get("summary") or chapter.get("subtitle") or "")
            count = chapter.get("count", 0)
            lines.append(f"### 阶段 {idx}：{title} ({count} 项证据)")
            if summary:
                lines.append(f"> {summary}")
            lines.append("")
    else:
        lines.append("_暂无阶段划分数据。_")
        lines.append("")

    lines.append("## 3. 决策脉络与思维推演树 (Thinking Line Topology)")
    root_node = thinking.get("root", {})
    if root_node:
        lines.append(f"- **目标根节点 (Goal Root)**：{_clean_text(root_node.get('label'))}")
        branches = thinking.get("branches", [])
        for branch in branches:
            b_label = _clean_text(branch.get("label", ""))
            b_status = branch.get("status", "proposed")
            lines.append(f"  - **分支决策 [{b_status}]**：{b_label}")
            for child in branch.get("children", []):
                c_label = _clean_text(child.get("label", ""))
                lines.append(f"    - *支撑事实*：{c_label}")
    else:
        lines.append("_暂无结构化决策树。_")
    lines.append("")

    lines.append("## 4. 功能规范与已确认团队共识 (Confirmed Scope)")
    accepted = brief.get("accepted_decisions") or []
    if accepted:
        for acc in accepted:
            lines.append(f"- **[RFC/规范已采纳]**：{_clean_text(acc)}")
    else:
        pending_decisions = [f for f in (team.get("facts") or []) if f.get("kind") == "decision" and f.get("status") in {"proposed", "conflicted"}]
        if pending_decisions:
            for dec in pending_decisions[:6]:
                lines.append(f"- **[待确认候选]**：{_clean_text(dec.get('value'))}")
        else:
            lines.append("_暂无已确认团队规范，待负责人审阅候选决策后生成。_")
    lines.append("")

    lines.append("## 5. 执行清单与待办工作 (Execution Roadmap)")
    todos = brief.get("open_todos") or []
    if todos:
        for todo in todos:
            mark = "x" if _is_task_completed(todo) else " "
            lines.append(f"- [{mark}] {_clean_text(todo)}")
    else:
        task_facts = [f for f in (team.get("facts") or []) if f.get("kind") == "task"]
        if task_facts:
            for t in task_facts[:8]:
                mark = "x" if _is_task_completed(t) else " "
                lines.append(f"- [{mark}] {_clean_text(t.get('value'))}")
        else:
            lines.append("_当前暂无待办任务记录。_")
    lines.append("")

    lines.append("---")
    lines.append("*Project Compass Autonomous Cognitive Specification Engine*")
    return "\n".join(lines)


def export_mindmap(state: dict[str, Any]) -> str:
    """Generate a Mermaid cognitive mindmap + evidence index Markdown export."""
    project = state.get("project", {})
    team = state.get("team", {})
    thinking = state.get("thinking_line") or team.get("thinking_line") or {}
    root = thinking.get("root") or {}
    branches = thinking.get("branches") or []
    code_nodes = thinking.get("code_nodes") or []
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _mm_safe(text: Any, max_len: int = 44) -> str:
        cleaned = _clean_text(text).replace('"', "'").replace("`", "'").replace("\n", " ")
        cleaned = cleaned.replace("(", "（").replace(")", "）").replace("[", "【").replace("]", "】")
        if len(cleaned) > max_len:
            cleaned = cleaned[: max_len - 1] + "…"
        return cleaned or "未命名节点"

    root_label = _mm_safe(root.get("label") or project.get("name") or "核心目标待定锚", 32)
    mermaid_lines: list[str] = [
        "```mermaid",
        "mindmap",
        f"  root(({root_label}))",
    ]
    index_lines: list[str] = []

    if branches:
        for branch in branches:
            b_state = branch.get("state")
            b_status = branch.get("status")
            prefix = "已舍弃" if b_state == "abandoned" else "已暂缓" if b_state == "deferred" else "已定案" if b_status == "accepted" else "待拍板"
            b_label = _mm_safe(branch.get("label"), 26)
            mermaid_lines.append(f"    {prefix}：{b_label}")
            ev_str = ", ".join(branch.get("evidence_ids") or [])
            full_branch = _clean_text(branch.get("full_label") or branch.get("label"))
            index_lines.append(f"- **[{prefix}]** {full_branch}" + (f" `{ev_str}`" if ev_str else ""))
            for child in branch.get("children") or []:
                mark = "已完成" if child.get("task_state") == "completed" else "待办"
                c_label = _mm_safe(child.get("label"), 24)
                mermaid_lines.append(f"      {mark}：{c_label}")
                c_ev = ", ".join(child.get("evidence_ids") or [])
                full_child = _clean_text(child.get("full_label") or child.get("label"))
                index_lines.append(f"  - [{mark}] {full_child}" + (f" `{c_ev}`" if c_ev else ""))
    else:
        mermaid_lines.append("    待提炼分支（随手记或接入对话后自动生长）")

    archive = thinking.get("historical_archive") or {}
    archive_items = archive.get("items") or []
    if archive_items:
        mermaid_lines.append(f"    历史文档参考（{len(archive_items)} 条）")
        for arch in archive_items[:5]:
            mermaid_lines.append(f"      {_mm_safe(arch.get('label'), 24)}")

    if code_nodes:
        mermaid_lines.append("    关联代码结构")
        for node in code_nodes:
            mermaid_lines.append(f"      {_mm_safe(node.get('label') or node.get('id'), 36)}")

    mermaid_lines.append("```")

    lines = [
        f"# {project.get('name', 'Compass')} · 认知思维导图 (Cognitive Mindmap)",
        "",
        f"> 导出时间：{exported_at} · 可直接在 GitHub / Markdown 编辑器 / Obsidian 渲染",
        "",
        *mermaid_lines,
        "",
        "## 节点与原始证据编号对照",
        *(index_lines or ["_当前尚无分支记录。_"]),
        "",
    ]
    return "\n".join(lines)


def export_state_by_format(state: dict[str, Any], fmt: str) -> tuple[str, str, str]:
    """Return (content, content_type, filename) for the requested export format."""
    normalized = (fmt or "json").strip().lower()
    proj_name = state.get("project", {}).get("name", "compass")
    if normalized == "issue":
        return export_github_issue(state), "text/markdown; charset=utf-8", f"{proj_name}-github-issue.md"
    if normalized == "pr":
        return export_pull_request(state), "text/markdown; charset=utf-8", f"{proj_name}-pull-request.md"
    if normalized == "prd":
        return export_prd(state), "text/markdown; charset=utf-8", f"{proj_name}-prd-spec.md"
    if normalized == "mindmap":
        return export_mindmap(state), "text/markdown; charset=utf-8", f"{proj_name}-mindmap.md"
    # Default to json
    import json
    payload = {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2), "application/json; charset=utf-8", f"{proj_name}-state.json"
