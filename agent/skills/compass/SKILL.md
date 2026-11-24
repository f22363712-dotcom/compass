---
name: compass
description: Open the live Compass workbench (`/compass`) across Antigravity native side-pane, IDE built-in browser, local desktop browser, or terminal fallback with cold-start doc bootstrap and multi-session alignment. 按需通过 `/compass` 唤醒实时 Compass 项目掌控台，自动适配 Antigravity 原生右侧副栏、IDE 内置浏览器、本地系统浏览器或纯终端降级。
---

# Compass Live Workbench (`/compass`)

Use this skill **only** when the user explicitly invokes `/compass` or asks to open, show, or inspect the Compass workbench/side-pane（如“打开 Compass”“看看思维导图与分歧”）.

## Silent-First Discipline

- **Do NOT call `open_compass` during ordinary background turns.** Routine code edits, single-line bug fixes, and normal Q&A stay silent via background Compass MCP tracking (`project_context`, `record_note`, `verify_completion`) without popping open the side-pane or launching browsers.
- **Open on demand**: Trigger `open_compass` immediately when `/compass` is invoked, when the user asks to inspect the board, or when an unresolved conflict / `verify_completion` block needs visual human triage.

## Execution Workflow

1. **Call `open_compass` immediately** with explicit workspace and session routing so parallel projects and sessions stay isolated:
   - `project_path`: current workspace root directory
   - `session_id`: current conversation/session identifier
   Compass automatically inspects the connected MCP client profile (`clientInfo`, capabilities, desktop/SSH environment) and populates `ui_delivery` in the returned payload (performing read-only cold-start document bootstrapping if the workspace has no prior Compass history).

2. **Deliver the right visual surface based on `ui_delivery.tier`**:
   - If `ui_delivery.tier == "antigravity_sidecar"` (native full dashboard hosted in Antigravity's auxiliary pane): emit the clickable toggle pill on its own line in your reply:

     [打开 Compass 实时掌控台](sidecar://compass/compass_board/)

   - If `ui_delivery.tier == "ide_builtin_browser"` (e.g. Codex / Cursor / Windsurf / Antigravity without plugin): report the live local URL `ui_delivery.dashboard_url` (use any available built-in preview/browser tool if provided by the host IDE, or give the clickable local URL directly).
   - If `ui_delivery.tier == "external_browser"` (local CLI desktop agents such as Hermes local desktop / Claude Code): state `ui_delivery.dashboard_url` and note whether the system default browser was automatically opened (`ui_delivery.browser_opened`), so the user can dock it beside the terminal.
   - If `ui_delivery.tier == "headless_terminal"` (remote SSH / no GUI display): print `ui_delivery.dashboard_url` and the ready-to-paste `ui_delivery.ssh_port_forward_hint` command.
   - If `ui_delivery.tier == "mcp_app_inline"`: confirm the inline MCP App panel rendered cleanly.

3. **Reply with a concise 4-line Chinese summary** grounded strictly in the returned payload (never fabricate fields or dump raw JSON):
   - **核心目标**：`<core_goal.text>`（已定案 / 待定 / 待确立）
   - **下一步共识**：`<next_step.text>`（已定案 / 待定 / 待确立）
   - **待拍板与分歧**：`待拍板 <pending_items.length> 条 · 分歧 <conflicts.length> 处`
   - **优先施工队列**：`<priority_dispatches.length> 项（列出首条标题，或“暂无待推进队列”）`

4. **Next interaction**: Briefly note in plain language that clicking mindmap nodes opens evidence timelines and conflict controls, and confirmed work can be sent back into the chat input capsule, sent straight into the active chat, opened in a new thread (in Antigravity sidecar), or queued & copied in standalone browsers.
