const state = { data: null, lens: "personal", workMode: null, workbenchView: readStorage("compass_workbench_view") === "mindmap" ? "mindmap" : "list", member: null, evidenceQuery: "", layer: "overview", refreshing: false, quickNotePending: false, anchorEditing: null, anchorSaving: false, pendingSignerAction: null, revision: 0, investigationRequest: 0, projectId: null, activeChapterId: null, freshFactIds: new Set(), freshTimer: null, evidenceCache: Object.create(null), evidenceRequestSeq: 0, popoverTimer: null, popoverAnchor: null, popoverCurrentId: null, lastTriggerElement: null, lastModalTrigger: null, lastDrawerTrigger: null, lastDrawerTriggerSpec: null, copyRestoreTimer: null, exportTimers: Object.create(null) };

const cleanUiText = (value) => String(value ?? "").replace(/\*\*/g, "").replace(/__/g, "").replace(/`/g, "").replace(/^\s*[-*]\s+\[[ xX]\]\s*/gm, "").replace(/\s+/g, " ").trim();

function readDismissedHints() {
  const raw = readStorage("compass_dismissed_hints");
  if (!raw) return new Set();
  try {
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : []);
  } catch (_err) {
    return new Set();
  }
}

function dismissHint(hintId) {
  if (!hintId) return;
  const current = readDismissedHints();
  current.add(String(hintId));
  const list = [...current].slice(-32);
  writeStorage("compass_dismissed_hints", JSON.stringify(list));
  renderAgentHints(effectiveWorkMode() === "solo");
  bindDynamicControls();
}

function collectFactIdSet(data) {
  const ids = new Set();
  for (const fact of (data?.team?.facts || [])) {
    if (fact?.id) ids.add(fact.id);
  }
  for (const memberView of Object.values(data?.personal || {})) {
    for (const fact of (memberView?.facts || [])) {
      if (fact?.id) ids.add(fact.id);
    }
  }
  return ids;
}

function readStorage(key) {
  try {
    return typeof window !== "undefined" && window.localStorage ? String(window.localStorage.getItem(key) || "") : "";
  } catch (_err) {
    return "";
  }
}
function writeStorage(key, value) {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(key, String(value ?? ""));
      return true;
    }
  } catch (_err) {
    return false;
  }
  return false;
}
function effectiveWorkMode() {
  if (state.workMode === "solo" || state.workMode === "team") return state.workMode;
  const saved = readStorage("compass_work_mode");
  if (saved === "solo" || saved === "team") {
    state.workMode = saved;
    return saved;
  }
  const humanMembers = Object.keys(state.data?.personal || {}).filter((member) => member !== "project-documents");
  return humanMembers.length > 1 ? "team" : "solo";
}
function setWorkMode(mode) {
  const normalized = mode === "team" ? "team" : "solo";
  state.workMode = normalized;
  writeStorage("compass_work_mode", normalized);
  render();
}
function setWorkbenchView(viewMode) {
  const normalized = viewMode === "mindmap" ? "mindmap" : "list";
  state.workbenchView = normalized;
  writeStorage("compass_workbench_view", normalized);
  render();
}

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
const label = (kind) => ({goal:"核心目标", task:"待办事项", decision:"决策", assumption:"未验证前提"}[kind] || kind || "记录");
const statusLabel = (status) => ({
  accepted: "已确认",
  confirmed: "已确认",
  completed: "已完成",
  proposed: "待核对",
  candidate: "候选",
  conflicted: "存在分歧",
  rejected: "已驳回",
  needs_evidence: "待补证据",
  needs_more_evidence: "待补证据",
  superseded: "已更替",
  deferred: "已暂缓",
  abandoned: "已放弃",
  raw: "原始记录",
  pending: "待处理",
  active: "进行中",
}[status] || status || "待核对");
const safeToken = (value, fallback = "pending") => {
  const raw = String(value ?? "");
  return /^[a-z0-9_-]+$/i.test(raw) ? raw : fallback;
};
const STATUS_BADGE_MAP = Object.assign(Object.create(null), {
  accepted: { cls: "is-accepted", text: "已确认" },
  confirmed: { cls: "is-accepted", text: "已确认" },
  completed: { cls: "is-accepted", text: "已完成" },
  current: { cls: "is-accepted", text: "● 当前最新" },
  conflicted: { cls: "is-conflicted", text: "存在分歧" },
  blocked: { cls: "is-conflicted", text: "受阻" },
  unavailable: { cls: "is-conflicted", text: "● 来源缺失" },
  rejected: { cls: "is-rejected", text: "已驳回" },
  abandoned: { cls: "is-rejected", text: "已放弃" },
  needs_evidence: { cls: "is-warn", text: "待补证据" },
  needs_more_evidence: { cls: "is-warn", text: "待补证据" },
  superseded: { cls: "is-warn", text: "已更替" },
  deferred: { cls: "is-warn", text: "已暂缓" },
  proposed: { cls: "is-proposed", text: "待核对" },
  candidate: { cls: "is-proposed", text: "候选" },
  raw: { cls: "is-proposed", text: "原始记录" },
  pending: { cls: "is-proposed", text: "待处理" },
  active: { cls: "is-info", text: "进行中" },
  relation_confirmed: { cls: "is-info", text: "关系已确认" },
  recommended: { cls: "is-info", text: "系统推荐" },
});
function getBadgeMeta(status) {
  const key = String(status || "proposed").toLowerCase();
  return Object.prototype.hasOwnProperty.call(STATUS_BADGE_MAP, key)
    ? STATUS_BADGE_MAP[key]
    : { cls: "is-proposed", text: key ? statusLabel(key) : "待核对" };
}
function renderStatusBadge(status, customLabel = "") {
  const meta = getBadgeMeta(status);
  return `<span class="status-badge ${meta.cls}">${esc(customLabel || meta.text)}</span>`;
}
function resolveFactStatus(fact) {
  if (!fact) return "proposed";
  if (fact.status === "accepted") return "accepted";
  const factId = fact.id || fact.fact_id;
  if (!factId) return fact.status || "proposed";
  if ((state.data?.team?.facts || []).some((f) => f?.id === factId && f.status === "accepted")) {
    return "accepted";
  }
  const history = state.data?.review_history || [];
  for (let i = history.length - 1; i >= 0; i -= 1) {
    const item = history[i];
    if (item?.fact_id === factId && item.action !== "confirm_relation") {
      if (item.action === "reject_fact") return "rejected";
      if (item.action === "request_evidence") return "needs_evidence";
      break;
    }
  }
  return fact.status || "proposed";
}
const claimLabel = (type) => ({assistant_report:"助手报告", user_statement:"用户表达", conversation_exchange:"问答记录", document_statement:"项目文档", execution_record:"执行记录"}[type] || "来源声明");
const commandOriginLabel = (origin) => ({native_trace:'原生命令记录',agent_report:'Agent命令报告',reported:'命令报告'}[origin] || '命令报告');
const taskStateLabel = (taskState) => ({
  completed: "已完成",
  reported_complete: "已完成",
  active: "进行中",
  in_progress: "进行中",
  blocked: "受阻卡点",
  pending: "待推进",
  todo: "待推进",
  unknown: "待核实",
}[String(taskState || "pending").toLowerCase()] || "待推进");
const evidenceKindLabel = (kind, sourceRef = "") => {
  const ref = String(sourceRef || "").trim();
  if (ref === "web://quick-note") return "随手记";
  if (ref === "mcp://record-note") return "实时记账";
  return ({
    user_message: "对话发言",
    assistant_message: "助手回复",
    agent_message: "助手回复",
    fact_proposal: "结构化提议",
    file_snapshot: "项目文档",
    file_unavailable: "缺失文件记录",
    git_commit: "Git 提交",
    command_execution: "命令执行",
    test_result: "测试记录",
    tool_call: "工具调用",
    tool_result: "工具输出",
  }[kind] || "来源记录");
};
const humanSourceRef = (sourceRef, kind = "") => {
  const ref = String(sourceRef || "").trim();
  if (ref === "web://quick-note") return "网页随手记";
  if (ref === "mcp://record-note") return "助手实时记账";
  return ref || (kind ? evidenceKindLabel(kind) : "");
};
const evidenceClassLabel = (cls) => ({
  fact_source: "结论依据",
  execution_result: "执行记录",
}[cls] || "过程记录");
const relationMethodLabel = (method) => ({
  quote_match: "原文精确引用",
  lexical: "关键词关联",
  manual: "人工确认关联",
  owner_confirmed: "人工确认关联",
}[method] || method || "关联线索");
const subjectKeyLabel = (subjectKey) => {
  const key = String(subjectKey || "").trim();
  if (!key) return "项目记录";
  if (key === "project.goal" || key.startsWith("doc.goal.")) return "项目核心目标";
  if (key === "project.next_step") return "当前下一步共识";
  if (key.startsWith("doc.task.") || key.startsWith("note.task.") || key.startsWith("task.")) return "待办事项";
  if (key.startsWith("doc.decision.") || key.startsWith("note.decision.") || key.startsWith("dec.")) return "方案决策";
  if (key.startsWith("note.assumption.")) return "待验证前提";
  return key;
};
function factEffectiveTimestamp(fact) {
  if (!fact) return 0;
  let ts = Date.parse(fact.observed_at || "") || 0;
  const fid = fact.id || fact.fact_id;
  if (!fid) return ts;
  for (const row of [...(state.data?.fact_reviews || []), ...(state.data?.review_history || [])]) {
    if (row?.action === "accept_fact" && row?.fact_id === fid && row?.observed_at) {
      const rts = Date.parse(row.observed_at) || 0;
      if (rts > ts) ts = rts;
    }
  }
  return ts;
}
function findSubjectPeers(fact) {
  if (!fact?.subject_key) return [];
  const selfId = fact.id || fact.fact_id;
  const seen = new Map();
  const pool = [
    ...(state.data?.team?.facts || []),
    ...(state.data?.personal?.[state.member]?.facts || []),
  ];
  for (const cand of pool) {
    if (!cand || cand.subject_key !== fact.subject_key) continue;
    const cid = cand.id || cand.fact_id;
    if (selfId && cid === selfId) continue;
    if (!selfId && cand.value === fact.value && cand.author === fact.author) continue;
    const key = cid || `${cand.author || ""}:${cand.value || ""}`;
    if (!seen.has(key)) seen.set(key, cand);
  }
  return [...seen.values()];
}
function findSupersedingAcceptedFact(fact) {
  if (!fact || resolveFactStatus(fact) !== "conflicted") return null;
  const selfTs = Date.parse(fact.observed_at || "") || 0;
  const peers = findSubjectPeers(fact).filter(
    (peer) => resolveFactStatus(peer) === "accepted" && sourceCurrent(peer) && factEffectiveTimestamp(peer) > selfTs
  );
  if (!peers.length) return null;
  peers.sort((a, b) => factEffectiveTimestamp(b) - factEffectiveTimestamp(a));
  return peers[0];
}
function renderCardConflictHintHTML(fact, _isSolo) {
  if (!fact || resolveFactStatus(fact) !== "conflicted" || findSupersedingAcceptedFact(fact)) return "";
  const peers = findSubjectPeers(fact);
  if (!peers.length) return "";
  const other = peers.find((p) => resolveFactStatus(p) === "accepted") || peers[0];
  const otherText = truncateUiText(cleanUiText(other.short_title || other.clean_value || other.value), 36);
  const who = other.author && other.author !== fact.author ? ` ${esc(other.author)} 的` : "另一条";
  return `<div class="card-conflict-digest">⚡ 分歧点：与${who}主张「${esc(otherText)}」不一致 · 点击对照</div>`;
}
function renderDrawerConflictOrSupersedeHTML(fact, isSolo) {
  if (!fact) return "";
  const evButtons = (ids) => (ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("");
  const superseder = findSupersedingAcceptedFact(fact);
  if (superseder) {
    const oldText = cleanUiText(fact.short_title || fact.clean_value || fact.value);
    const newText = cleanUiText(superseder.short_title || superseder.clean_value || superseder.value);
    return `<div class="drawer-comparison-box is-superseded">
      <div class="detail-label">新旧计划接替说明</div>
      <p class="drawer-comparison-lead">「${esc(subjectKeyLabel(fact.subject_key))}」已有一条更晚拍板定案的新记录，本条旧计划仅作历史保留，当前已不构成未决冲突。</p>
      <div class="drawer-vs-grid">
        <div class="drawer-vs-pane">
          <span class="conflict-stance-label">历史旧记录</span>
          <strong>${esc(oldText)}</strong>
          <small>${esc(fact.author || "记录者")} · ${sourceTimeHTML(fact)}</small>
          <div class="card-pill-row">${evButtons(fact.evidence_ids)}</div>
        </div>
        <div class="drawer-vs-pane is-accepted">
          <div class="conflict-pane-head"><span class="conflict-stance-label">当前生效新定案</span>${renderStatusBadge("accepted", isSolo ? "已定案" : "已确认")}</div>
          <strong>${esc(newText)}</strong>
          <small>${esc(superseder.author || "定案人")} · ${sourceTimeHTML(superseder)}</small>
          <div class="card-pill-row">${evButtons(superseder.evidence_ids)}</div>
        </div>
      </div>
    </div>`;
  }
  if (resolveFactStatus(fact) !== "conflicted") return "";
  const peers = findSubjectPeers(fact);
  if (!peers.length) return "";
  const other = peers.find((p) => resolveFactStatus(p) === "accepted") || peers[0];
  const paneFor = (item, labelText) => {
    const itemStatus = resolveFactStatus(item);
    const itemText = cleanUiText(item.value || item.short_title || "");
    const acceptHere = !state.data?.project?.read_only && canInlineAcceptFact(item) && (state.lens === "team" || isSolo)
      ? `<button type="button" class="mini-btn accept-btn" data-fact-review-id="${esc(item.id)}">✓ 定案此主张</button>`
      : "";
    return `<div class="drawer-vs-pane ${itemStatus === "accepted" ? "is-accepted" : "is-conflicted"}">
      <div class="conflict-pane-head"><span class="conflict-stance-label">${esc(labelText)}</span>${renderStatusBadge(itemStatus)}</div>
      <strong>${esc(itemText)}</strong>
      <small>${esc(item.author || "记录者")} · ${sourceTimeHTML(item)}</small>
      <div class="card-pill-row">${evButtons(item.evidence_ids)}</div>
      ${acceptHere}
    </div>`;
  };
  return `<div class="drawer-comparison-box is-conflicted">
    <div class="detail-label">分歧双方对照（为什么标为存在分歧？）</div>
    <p class="drawer-comparison-lead">同一「${esc(subjectKeyLabel(fact.subject_key))}」下存在两条不同主张，尚未最终统一：</p>
    <div class="drawer-vs-grid">${paneFor(fact, "主张 A（当前查看）")}${paneFor(other, "主张 B（另一方记录）")}</div>
  </div>`;
}
const sourceCurrent = (fact) => !["superseded", "unavailable"].includes(fact.source_state?.status);
const projectQuerySuffix = () => (state.data?.project?.read_only && state.projectId ? `&project_id=${encodeURIComponent(state.projectId)}` : "");
function canInlineAcceptFact(fact) {
  if (!fact || state.data?.project?.read_only) return false;
  if (!sourceCurrent(fact)) return false;
  if (["abandoned", "deferred"].includes(fact.direction_suggestion)) return false;
  if ((state.data?.team?.directions?.current || []).some((row) => row.fact_id === fact.id)) return false;
  return resolveFactStatus(fact) !== "accepted";
}
const sourceNote = (fact) => fact.source_state?.status === "superseded" ? "来源已换版，需复核" : fact.source_state?.status === "unavailable" ? "来源当前不可用，需复核" : "";
const olderState = (payload) => Number.isFinite(payload.state_version) && Number.isFinite(state.data?.state_version) && payload.state_version < state.data.state_version;
const formatTime = (value) => { if (!value) return "时间未记录"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", {hour12: false}); };
const sourceTimeLabel = (record) => record.source_kind === 'file_snapshot' ? '材料采集时间' : '来源记录时间';
const hasSourceTime = (record) => !!record.observed_at && !Number.isNaN(new Date(record.observed_at).getTime());
const sourceTimeText = (record, title = sourceTimeLabel(record)) => hasSourceTime(record) ? `${title} ${formatTime(record.observed_at)}` : `${title}未提供`;
const sourceTimeHTML = (record, title = sourceTimeLabel(record)) => hasSourceTime(record) ? `<time datetime="${esc(record.observed_at)}">${esc(sourceTimeText(record, title))}</time>` : `<span>${esc(sourceTimeText(record, title))}</span>`;

async function apiFetch(url, options = {}) {
  if (typeof fetch !== "function") throw new Error("fetch unavailable");
  const { timeoutMs = 12000, rawResponse = false, parseErrorBody = true, background = false, ...fetchOptions } = options;
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(url, {
      cache: "no-store",
      ...fetchOptions,
      signal: controller ? controller.signal : undefined,
    });
    if (!response.ok) {
      let payload = null;
      if (parseErrorBody && response.status !== 401 && response.status !== 403 && typeof response.json === "function") {
        try {
          payload = await response.json();
        } catch (parseErr) {
          if (parseErr?.name === "AbortError" || parseErr?.name === "TypeError") throw parseErr;
          payload = null;
        }
      }
      const err = new Error(payload?.error || `request failed (${response.status ?? "error"})`);
      err.payload = payload;
      throw err;
    }
    if (!background && state.data) {
      const conn = document.getElementById("connection-label");
      if (conn && (conn.textContent === "请求超时，请检查本地服务" || conn.textContent === "网络暂时不可用")) {
        conn.textContent = formatConnectionLabel(state.data);
      }
    }
    if (rawResponse) return response;
    return typeof response.json === "function" ? await response.json() : null;
  } catch (error) {
    if (!background) {
      const conn = document.getElementById("connection-label");
      if (conn && (error?.name === "AbortError" || error?.name === "TypeError")) {
        conn.textContent = error.name === "AbortError" ? "请求超时，请检查本地服务" : "网络暂时不可用";
      }
    }
    throw error;
  } finally {
    if (timer !== null) clearTimeout(timer);
  }
}

async function readInitialState(projectId = null) {
  const payload = await apiFetch(projectId ? `/api/state?project_id=${encodeURIComponent(projectId)}` : "/api/state", { timeoutMs: 8000, parseErrorBody: false });
  const validView = (view) => view && typeof view === "object" && Array.isArray(view.facts) && Array.isArray(view.evidence_ids);
  if (!payload || !Number.isInteger(payload.project?.evidence_count) || payload.project.evidence_count < 0 ||
      !Number.isInteger(payload.project?.fact_count) || payload.project.fact_count < 0 ||
      !payload.personal || typeof payload.personal !== "object" || Array.isArray(payload.personal) ||
      !Object.values(payload.personal).every(validView) || !validView(payload.team) || !Array.isArray(payload.evidence)) {
    throw new Error("invalid dashboard state");
  }
  return payload;
}

async function loadState() {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let payload;
    try {
      payload = await readInitialState(state.projectId);
    } catch (error) {
      if (attempt === 2 || !["TypeError", "AbortError"].includes(error.name)) throw error;
      document.getElementById("connection-label").textContent = `连接暂时中断，重试 ${attempt + 2}/3`;
      await new Promise((resolve) => setTimeout(resolve, attempt === 0 ? 250 : 750));
      continue;
    }
    const prevLoadedProjectId = state.data?.project?.project_id || null;
    const nextLoadedProjectId = payload.project?.project_id || state.projectId || null;
    if (prevLoadedProjectId && nextLoadedProjectId && prevLoadedProjectId !== nextLoadedProjectId) {
      state.evidenceCache = Object.create(null);
      state.evidenceRequestSeq = (state.evidenceRequestSeq || 0) + 1;
      state.activeChapterId = null;
      hideCitationPopover();
    }
    state.data = payload;
    state.projectId = payload.project?.project_id || state.projectId;
    loadProjects();
    state.revision += 1;
    render();
    return;
  }
}

async function loadProjects() {
  const target = document.getElementById("project-list");
  if (!target) return;
  try {
    const projects = state.data?.projects || [];
    target.innerHTML = projects.length ? projects.map((project) => `<button type="button" class="project-choice ${project.project_id === state.projectId ? "active" : ""}" data-project-id="${esc(project.project_id)}">${esc(project.project_name)}</button>`).join("") : "暂无已保存项目";
    if (typeof target.querySelectorAll === "function") {
      target.querySelectorAll("[data-project-id]").forEach((button) => button.addEventListener("click", async () => {
        const nextId = button.dataset?.projectId;
        const prevId = state.projectId;
        if (!nextId || nextId === prevId) return;
        const prevCache = state.evidenceCache;
        state.projectId = nextId;
        state.evidenceCache = Object.create(null);
        hideCitationPopover();
        try {
          await loadState();
        } catch (error) {
          state.projectId = prevId;
          state.evidenceCache = prevCache || Object.create(null);
          loadProjects();
          render();
          const connEl = document.getElementById("connection-label");
          if (connEl) connEl.textContent = `切换项目失败: ${error?.message || "连接不可用"}`;
        }
      }));
    }
  } catch (error) {
    target.textContent = "项目列表暂不可用";
  }
}

const SCAN_STAGE_LABELS = {
  scanning: "正在扫描目录与会话…",
  extracting_docs: "正在提取文档目标与候选…",
  indexing_code: "正在建立 AST 代码结构索引…",
  complete: "扫描完成",
};

async function scanNewProject(event) {
  event.preventDefault();
  const result = document.getElementById("project-scan-result");
  const projectPath = document.getElementById("project-path-input").value.trim();
  const extractEl = document.getElementById("scan-extract-docs");
  const codeEl = document.getElementById("scan-code-index");
  const extractDocs = extractEl ? extractEl.checked !== false : true;
  const withCodeIndex = codeEl ? codeEl.checked !== false : true;
  if (!projectPath) { result.textContent = "请填写目录"; return; }
  result.textContent = "正在扫描…";
  try {
    await apiFetch("/api/projects/scan", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({project_path: projectPath, extract_docs: extractDocs, with_code_index: withCodeIndex}),
    });
    result.textContent = "正在扫描目录与会话…";
    let completed = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      const status = await apiFetch("/api/projects/scan-status");
      if (status.state === "failed") throw new Error(status.error || "扫描失败");
      if (status.stage && SCAN_STAGE_LABELS[status.stage] && status.state !== "complete") {
        result.textContent = SCAN_STAGE_LABELS[status.stage];
      }
      if (status.state === "complete") {
        completed = true;
        state.projectId = status.project_id;
        await loadState();
        const warningNote = Array.isArray(status.warnings) && status.warnings.length
          ? `（${status.warnings.length} 项附带提示：${status.warnings[0]}）`
          : "";
        result.textContent = `已保存 ${status.project_path}${warningNote}`;
        loadProjects();
        break;
      }
    }
    if (!completed) result.textContent = "扫描仍在进行，可稍后刷新页面查看状态。";
  } catch (error) {
    result.textContent = error.message;
  }
}

function renderQuickNoteBar(isSolo) {
  const form = document.getElementById("quick-note-form");
  const kindSelect = document.getElementById("quick-note-kind");
  const input = document.getElementById("quick-note-input");
  const acceptWrap = document.getElementById("quick-note-accept-wrap");
  const acceptLabel = document.getElementById("quick-note-accept-label");
  const acceptBox = document.getElementById("quick-note-accept");
  const submitBtn = document.getElementById("quick-note-submit");
  const feedback = document.getElementById("quick-note-feedback");
  if (acceptLabel) acceptLabel.textContent = isSolo ? "直接定案为基准" : "同时确认为团队事实";
  if (acceptWrap) acceptWrap.hidden = Boolean(state.data?.agent_api?.enabled);
  if (!form) return;
  const readOnly = Boolean(state.data?.project?.read_only);
  form.classList?.toggle?.("is-readonly", readOnly);
  if (kindSelect) kindSelect.disabled = readOnly || state.quickNotePending;
  if (input) {
    input.disabled = readOnly || state.quickNotePending;
    input.placeholder = readOnly ? "只读历史项目不可写入随手记，请切回当前运行项目" : (isSolo ? "随手记一条待定思路、前提或待办，自动沉淀可溯源记录…" : "随手记一条项目思路、前提或待办，先记为个人候选…");
  }
  if (acceptBox) acceptBox.disabled = readOnly || state.quickNotePending;
  if (submitBtn) submitBtn.disabled = readOnly || state.quickNotePending;
  if (feedback && readOnly && !feedback.textContent) {
    feedback.textContent = "只读项目不可新增随手记";
  }
}

async function submitQuickNote(event, overrides = {}) {
  event?.preventDefault?.();
  if (state.quickNotePending) return;
  const feedback = document.getElementById("quick-note-feedback");
  if (state.data?.project?.read_only) {
    if (feedback) feedback.textContent = "当前项目为只读预览，不能添加随手记。";
    return;
  }
  const kindEl = document.getElementById("quick-note-kind");
  const inputEl = document.getElementById("quick-note-input");
  const acceptEl = document.getElementById("quick-note-accept");
  const submitBtn = document.getElementById("quick-note-submit");
  const kind = overrides.kind || kindEl?.value || "decision";
  const text = String(overrides.text !== undefined ? overrides.text : (inputEl?.value || "")).trim();
  const autoAccept = overrides.autoAccept !== undefined ? Boolean(overrides.autoAccept) : Boolean(acceptEl?.checked);
  const isSolo = effectiveWorkMode() === "solo";
  if (!text) {
    if (feedback) feedback.textContent = "请输入内容后再记录";
    inputEl?.focus?.();
    return;
  }
  const reviewerInput = document.getElementById("reviewer-input");
  const signerValue = String(overrides.signer || reviewerInput?.value || "").trim();
  if (autoAccept && !signerValue) {
    if (isSolo) {
      requestInlineSoloSigner(
        { type: "quick_note", kind, text, autoAccept: true },
        "首次直接定案需要一次个人署名，填好后自动记住并完成记录。",
      );
    } else {
      if (feedback) feedback.textContent = "请先在上方填写负责人姓名后再直接确认，或取消勾选仅记为候选。";
      reviewerInput?.focus?.();
    }
    return;
  }
  const targetMember = (state.member && state.member !== "project-documents")
    ? state.member
    : (signerValue || Object.keys(state.data?.personal || {}).find((m) => m !== "project-documents") || "");
  const nonce = `note-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  state.quickNotePending = true;
  if (submitBtn) submitBtn.disabled = true;
  if (feedback) feedback.textContent = "正在写入…";
  try {
    const payload = await apiFetch("/api/notes", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text,
        kind,
        member_id: targetMember,
        auto_accept: autoAccept,
        reviewer: signerValue,
        client_nonce: nonce,
      }),
    });
    if (isSolo && !state.workMode) state.workMode = "solo";
    if (!olderState(payload)) {
      state.data = payload;
      render();
    }
    if (inputEl && !overrides.keepInput) inputEl.value = "";
    if (acceptEl && !overrides.keepAccept) acceptEl.checked = false;
    const warn = payload?.quick_note?.warning;
    if (feedback) {
      feedback.textContent = warn
        ? `已记为待定（${warn}）`
        : payload?.quick_note?.accepted
          ? `✓ 已记入并定案为${label(kind)}`
          : `✓ 已记为待定${label(kind)}`;
    }
  } catch (error) {
    if (feedback) feedback.textContent = `记录失败：${error.message}`;
  } finally {
    state.quickNotePending = false;
    renderQuickNoteBar(effectiveWorkMode() === "solo");
  }
}

function selectAvailableMember() {
  const members = Object.keys(state.data.personal || {});
  if (members.includes(state.member)) return;
  const preferred = (state.data.intake?.enabled && state.data.intake.member_id) || (state.data.extraction?.enabled && state.data.extraction.member_id);
  state.member = members.includes(preferred) ? preferred : members.find((member) => member !== "project-documents") || members[0] || null;
}

function renderMemberPicker(members) {
  const picker = document.getElementById("member-picker");
  const select = document.getElementById("member-select");
  const isSolo = effectiveWorkMode() === "solo";
  const nonDocMembers = members.filter((member) => member !== "project-documents");
  picker.hidden = state.lens !== "personal" || (isSolo && nonDocMembers.length <= 1);
  select.innerHTML = members.length ? members.map((member) => `<option value="${esc(member)}">${member === "project-documents" ? "项目材料" : esc(member)}</option>`).join("") : `<option value="">暂无成员数据</option>`;
  select.value = state.member || "";
}

function activeView() {
  if (state.lens === "team") return state.data.team || {facts: [], evidence_ids: []};
  return (state.data.personal || {})[state.member] || {facts: [], evidence_ids: []};
}

function computeHeroSummary(isSolo) {
  const data = state.data;
  const evCount = data?.project?.evidence_count ?? 0;
  const factCount = data?.project?.fact_count ?? 0;
  if (!data || evCount === 0 || factCount === 0) {
    return isSolo
      ? "新项目已就绪 · 对话或随手记下第 1 个目标，脑图将实时生长。"
      : "项目已就绪 · 接入成员会话后自动记录决策基准与证据轨迹。";
  }
  const teamFacts = data.team?.facts || [];
  const acceptedCount = teamFacts.filter((f) => resolveFactStatus(f) === "accepted" && sourceCurrent(f)).length;
  const pendingActiveCount = teamFacts.filter((f) => !f.is_historical_doc && ["decision", "assumption", "goal"].includes(f.kind) && !["accepted", "rejected"].includes(resolveFactStatus(f))).length;
  const todoCount = teamFacts.filter((f) => !f.is_historical_doc && f.kind === "task" && f.task_state !== "completed" && resolveFactStatus(f) !== "rejected").length;
  return isSolo
    ? `当前 ${acceptedCount} 项已定案 · ${pendingActiveCount} 项待拍板 · ${todoCount} 项待办，点击任意节点溯源原文。`
    : `双视角共享账本 · ${acceptedCount} 项已确认共识 · ${pendingActiveCount} 项待核对。`;
}

function applyModeLexicon(isSolo, workbenchView) {
  const lexicon = {
    "reviewer-field-tag": isSolo ? "我的署名" : "负责人",
    "toolbar-note": isSolo ? "只留已拍板基准 · 待定不入正式需求" : "候选需负责人确认 · 原始证据追加保留",
    "lens-personal-btn": isSolo ? "实时纪要 · 待定思路" : "个人视图",
    "lens-team-btn": isSolo ? "已定案基准" : "团队共识",
    "handoff-brief-label": isSolo ? "续写快照" : "交接简报",
    "goal-kicker": "核心目标",
    "hero-copy": computeHeroSummary(isSolo),
    "legend-accepted-title": isSolo ? "已定案关系" : "已确认关系",
    "legend-accepted-desc": isSolo ? "你已拍板定案的基准与依据关系。" : "负责人已经确认的事实与依据关系。",
    "legend-candidate-desc": isSolo ? "AI 或会话提炼的待定关联，留待你拍板。" : "材料可能支持该结论，仍待人工核对。",
    "activity-kicker": isSolo ? "会话动态" : "推进动态",
    "personal-todos-kicker": isSolo ? "待办与坑位" : "待办清单",
    "personal-decisions-kicker": isSolo ? "待拍板与前提" : "决策台账",
    "solo-baseline-kicker": "已定案基准",
    "conflict-kicker": isSolo ? "变更与历史" : "分歧对照与裁决",
    "review-queue-kicker": isSolo ? "待定案" : "待晋升候选",
    "trace-confirm-note": isSolo ? "定案状态单独标记 · 时间顺序不代表因果" : "负责人确认单独标记 · 时间顺序不代表因果",
    "thinking-kicker": isSolo && workbenchView === "mindmap"
      ? "思维脑图 · 生长视图"
      : "阶段演进",
  };
  Object.entries(lexicon).forEach(([id, text]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  });
}

function decisionActionBar(fact, isSolo, effectiveStatus) {
  if (effectiveStatus === "accepted") {
    return `<span class="in-card-actions">${renderStatusBadge("accepted", isSolo ? "✓ 已定案基准" : "✓ 已确认共识")}</span>`;
  }
  if (state.data.project?.read_only) return "";
  const acceptBtn = canInlineAcceptFact(fact)
    ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="${isSolo ? "定案为项目基准" : "确认为团队共识"}">${isSolo ? "✓ 定案基准" : "✓ 确认决策"}</button>`
    : "";
  const rejectBtn = effectiveStatus === "rejected"
    ? ""
    : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="${isSolo ? "暂不采用" : "驳回候选"}">${isSolo ? "✕ 暂不采纳" : "✕ 驳回"}</button>`;
  return (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
}

function renderDecisionCardHTML(fact, isSolo) {
  const effectiveStatus = resolveFactStatus(fact);
  const superseder = findSupersedingAcceptedFact(fact);
  const typeTag = fact.kind === "goal"
    ? (effectiveStatus === "accepted" ? "已定案核心目标" : "核心目标候选")
    : fact.kind === "task"
      ? (effectiveStatus === "accepted" ? "已定案行动项" : "待办事项")
      : fact.kind === "decision"
        ? (effectiveStatus === "accepted" ? "已定案决策" : "待拍板决策")
        : (effectiveStatus === "accepted" ? "已核实前提" : "未验证前提");
  const inlineTriage = superseder ? "" : decisionActionBar(fact, isSolo, effectiveStatus);
  const displayTitle = fact.short_title || fact.clean_value || cleanUiText(fact.value);
  const freshCls = state.freshFactIds?.has?.(fact.id) ? " is-fresh-node" : "";
  const statusPill = superseder
    ? renderStatusBadge("superseded", "已由新定案接替")
    : renderStatusBadge(effectiveStatus);
  const subText = superseder
    ? `已被「${truncateUiText(cleanUiText(superseder.short_title || superseder.value), 30)}」接替 · ${fact.evidence_ids?.length || 0} 条依据`
    : `${statusLabel(effectiveStatus)} · ${fact.evidence_ids?.length || 0} 条依据`;
  const conflictHint = superseder ? "" : renderCardConflictHintHTML(fact, isSolo);
  return `<div class="decision-item${freshCls}" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${typeTag}</strong><span>${esc(displayTitle)}</span><small>${esc(subText)}</small>${conflictHint}<div class="card-pill-row">${statusPill}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
}

function openAnchorInlineForm(targetKind, initialText = "") {
  if (state.data?.project?.read_only) return;
  const form = document.getElementById("anchor-inline-form");
  const input = document.getElementById("anchor-inline-input");
  const saveBtn = document.getElementById("anchor-inline-save");
  if (!form || !input) return;
  state.anchorEditing = targetKind === "goal" ? "goal" : "next_step";
  form.hidden = false;
  input.value = cleanUiText(initialText);
  input.placeholder = state.anchorEditing === "goal"
    ? "输入一句话核心目标（约10～25字），回车即定案…"
    : "输入一句当前下一步工作共识，回车即锁定…";
  if (saveBtn) saveBtn.disabled = state.anchorSaving;
  input.focus?.();
}

function closeAnchorInlineForm() {
  state.anchorEditing = null;
  const form = document.getElementById("anchor-inline-form");
  if (form) form.hidden = true;
}

async function saveAnchorInlineForm(event) {
  event?.preventDefault?.();
  if (state.anchorSaving || !state.anchorEditing || state.data?.project?.read_only) return;
  const input = document.getElementById("anchor-inline-input");
  const saveBtn = document.getElementById("anchor-inline-save");
  const targetKind = state.anchorEditing;
  const text = String(input?.value || "").trim();
  if (!text) {
    input?.focus?.();
    return;
  }
  const isSolo = effectiveWorkMode() === "solo";
  const reviewerEl = document.getElementById("reviewer-input");
  const signer = String(state.data?.agent_api?.owner_id || reviewerEl?.value || readStorage("compass_reviewer_name") || state.member || "").trim()
    || (isSolo ? "solo" : "");
  if (!signer) {
    reviewerEl?.focus?.();
    return;
  }
  if (isSolo && reviewerEl && !reviewerEl.value && !reviewerEl.readOnly) {
    reviewerEl.value = signer;
    writeStorage("compass_reviewer_name", signer);
  }
  const targetMember = (state.member && state.member !== "project-documents")
    ? state.member
    : (signer || Object.keys(state.data?.personal || {}).find((m) => m !== "project-documents") || "solo");
  const nonce = `anchor-${targetKind}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  state.anchorSaving = true;
  if (saveBtn) saveBtn.disabled = true;
  try {
    const payload = await apiFetch("/api/notes", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text,
        kind: targetKind === "goal" ? "goal" : "task",
        topic: targetKind === "next_step" ? "next_step" : "",
        member_id: targetMember,
        auto_accept: true,
        reviewer: signer,
        client_nonce: nonce,
      }),
    });
    state.anchorEditing = null;
    if (!olderState(payload)) {
      state.data = payload;
    }
    closeAnchorInlineForm();
    render();
  } catch (error) {
    const noteEl = document.getElementById(targetKind === "goal" ? "goal-note" : "next-consensus-note");
    if (noteEl) noteEl.textContent = `定案保存失败：${error.message}`;
  } finally {
    state.anchorSaving = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

function renderAgentHints(isSolo) {
  const surface = document.getElementById("agent-hints-surface");
  const listEl = document.getElementById("agent-hints-list");
  const modeEl = document.getElementById("agent-hints-mode");
  if (!surface || !listEl) return;
  const dismissed = readDismissedHints();
  const hints = (state.data?.agent_hints || []).filter((h) => h && !dismissed.has(String(h.id || "")));
  if (!hints.length) {
    surface.hidden = true;
    listEl.innerHTML = "";
    return;
  }
  surface.hidden = false;
  if (modeEl) {
    modeEl.textContent = hints.some((h) => h.source === "llm") ? "语义提示" : "本地规则";
  }
  listEl.innerHTML = hints.slice(0, 2).map((hint) => {
    const badgeCls = hint.level === "warn" ? "is-warn" : (hint.source === "llm" ? "is-info" : "is-proposed");
    const evId = (hint.evidence_ids && hint.evidence_ids[0]) ? hint.evidence_ids[0] : "";
    const actionBtn = hint.action_label
      ? `<button type="button" class="mini-btn accept-btn" data-hint-action="${esc(hint.action_kind || "")}" data-hint-fact="${esc(hint.fact_id || "")}" data-hint-ev="${esc(evId)}">${esc(hint.action_label)}</button>`
      : "";
    const evLinks = evId ? renderEvPills([evId]) : "";
    return `<div class="agent-hint-card level-${safeToken(hint.level, "info")}">
      <div class="agent-hint-body">
        <span class="status-badge ${badgeCls}">${esc(hint.category || "提示")}</span>
        <span class="agent-hint-text">${esc(cleanUiText(hint.text || ""))}</span>
        ${evLinks}
      </div>
      <div class="agent-hint-actions">
        ${actionBtn}
        <button type="button" class="mini-btn" data-dismiss-hint="${esc(hint.id)}" title="暂时收起此提示">${isSolo ? "收起" : "忽略"}</button>
      </div>
    </div>`;
  }).join("");
}

function renderDualAnchors(isSolo, goal, isGoalAccepted) {
  const goalActions = [];
  if (goal?.evidence_ids?.length) {
    goalActions.push(`<div class="card-pill-row">${renderEvPills(goal.evidence_ids)}</div>`);
  }
  const goalActionBtns = [];
  if (goal && !isGoalAccepted && canInlineAcceptFact(goal)) {
    goalActionBtns.push(`<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(goal.id)}" title="${isSolo ? "定案为核心目标" : "确认为团队核心目标"}">${isSolo ? "✓ 定案为核心目标" : "✓ 确认为团队目标"}</button>`);
  }
  if (!state.data?.project?.read_only) {
    const goalSeed = goal ? (goal.short_title || goal.clean_value || cleanUiText(goal.value)) : "";
    goalActionBtns.push(`<button type="button" class="mini-btn" data-anchor-edit="goal" data-anchor-seed="${esc(goalSeed)}">${goal ? "✎ 改写定案" : "✎ 设定目标"}</button>`);
  }
  if (goalActionBtns.length) {
    goalActions.push(`<div class="in-card-actions">${goalActionBtns.join("")}</div>`);
  }
  const goalActionsEl = document.getElementById("goal-actions");
  if (goalActionsEl) goalActionsEl.innerHTML = goalActions.join("");

  const nextItem = state.data?.next_consensus || state.data?.handoff_brief?.next_consensus || null;
  const nextTitleEl = document.getElementById("next-consensus-title");
  const nextNoteEl = document.getElementById("next-consensus-note");
  const nextStatusEl = document.getElementById("next-consensus-status");
  const nextActionsEl = document.getElementById("next-consensus-actions");

  const resolvedStatus = nextItem ? resolveFactStatus({ id: nextItem.fact_id, status: nextItem.status }) : "empty";
  const isNextAccepted = Boolean(nextItem && !nextItem.is_candidate_suggestion && resolvedStatus === "accepted");
  if (nextTitleEl) {
    nextTitleEl.textContent = nextItem
      ? (nextItem.short_title || nextItem.clean_value || cleanUiText(nextItem.value))
      : "暂未设定当前下一步";
  }
  if (nextStatusEl) {
    if (!nextItem) {
      nextStatusEl.textContent = "待设定";
      nextStatusEl.className = "status-pill status-badge is-proposed";
    } else if (nextItem.is_candidate_suggestion) {
      nextStatusEl.textContent = "候选参考 · 待定";
      nextStatusEl.className = "status-pill status-badge is-proposed";
    } else {
      nextStatusEl.textContent = isNextAccepted ? (isSolo ? "已定案 · 当前下一步" : "已确认 · 下一步") : "待定下一步";
      nextStatusEl.className = `status-pill status-badge ${isNextAccepted ? "accepted is-accepted" : "is-proposed"}`;
    }
  }
  if (nextNoteEl) {
    if (!nextItem) {
      nextNoteEl.textContent = "历史旧计划不自动当成下一步，点击下方用一句话锁定当前焦点。";
    } else if (nextItem.is_candidate_suggestion) {
      nextNoteEl.textContent = "当前暂无独立下一步任务，暂展示最近一条活跃思路供参考；可直接改写锁定。";
    } else {
      nextNoteEl.textContent = isNextAccepted
        ? (isSolo ? "已锁定为当前推进共识 · 新动向未完成前以此为准" : "已确认的下一步工作共识")
        : "待定下一步工作 · 拍板后全站同步对齐";
    }
  }
  if (nextActionsEl) {
    const nextParts = [];
    if (nextItem?.evidence_ids?.length) {
      nextParts.push(`<div class="card-pill-row">${renderEvPills(nextItem.evidence_ids)}</div>`);
    }
    const nextBtns = [];
    if (nextItem && !isNextAccepted && !nextItem.is_candidate_suggestion && nextItem.fact_id && !state.data?.project?.read_only) {
      nextBtns.push(`<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(nextItem.fact_id)}">✓ 定案下一步</button>`);
    }
    if (!state.data?.project?.read_only) {
      const nextSeed = nextItem ? (nextItem.short_title || nextItem.clean_value || cleanUiText(nextItem.value)) : "";
      nextBtns.push(`<button type="button" class="mini-btn" data-anchor-edit="next_step" data-anchor-seed="${esc(nextSeed)}">${nextItem ? "✎ 改写定案" : "✎ 设定下一步"}</button>`);
    }
    if (nextBtns.length) nextParts.push(`<div class="in-card-actions">${nextBtns.join("")}</div>`);
    nextActionsEl.innerHTML = nextParts.join("");
  }

  const inlineForm = document.getElementById("anchor-inline-form");
  if (inlineForm) {
    inlineForm.hidden = !state.anchorEditing || Boolean(state.data?.project?.read_only);
  }
}

function renderActivityStream(isSolo) {
  const listEl = document.getElementById("personal-activity-list");
  const countEl = document.getElementById("activity-count");
  if (!listEl) return;
  const stream = state.data?.activity_stream;
  if (Array.isArray(stream) && stream.length > 0) {
    const scoped = (state.lens === "team" || !state.member || state.member === "project-documents")
      ? stream
      : stream.filter((item) => item.member_id === state.member);
    const items = scoped.length ? scoped : stream;
    if (countEl) countEl.textContent = items.length;
    listEl.innerHTML = items.slice(0, 18).map((item) => {
      const repeatTag = (item.collapsed_count || 1) > 1
        ? `<span class="activity-repeat-badge">连续 ${esc(item.collapsed_count)} 步</span>`
        : "";
      const exitTag = (item.exit_code !== null && item.exit_code !== undefined && item.exit_code !== 0)
        ? `<span class="status-badge is-conflicted">退出码 ${esc(item.exit_code)}</span>`
        : "";
      const actorNote = (!isSolo && item.member_id) ? `<b>${esc(item.member_id)}</b> · ` : "";
      const evIds = Array.isArray(item.evidence_ids) && item.evidence_ids.length
        ? item.evidence_ids
        : (item.primary_evidence_id ? [item.primary_evidence_id] : []);
      return `<div class="activity-item" role="button" tabindex="0" data-evidence-id="${esc(item.primary_evidence_id)}">
        <div class="activity-item-head">
          <span class="activity-action-tag kind-${safeToken(item.action_kind, "record")}">${esc(item.action_label || "会话记录")}</span>
          ${repeatTag}${exitTag}
          <span class="activity-time">${actorNote}${esc(formatTime(item.observed_at))}</span>
        </div>
        <strong class="activity-summary">${esc(item.summary || item.source_ref || item.primary_evidence_id)}</strong>
        <div class="card-pill-row">${renderEvPills(evIds)}</div>
      </div>`;
    }).join("");
    return;
  }
  const activities = (state.data.personal_activity || []).filter((item) => state.lens === "team" || !state.member || item.member_id === state.member);
  if (countEl) countEl.textContent = activities.length;
  listEl.innerHTML = activities.length
    ? activities.map((item) => `<div class="activity-item" role="button" tabindex="0" data-evidence-id="${esc(item.last_event_id)}"><strong>${esc(item.member_id)}</strong><span>${esc(item.last_event_kind || "event")} · ${esc(formatTime(item.last_event_at))}</span><small>${esc(item.last_event_preview || "")} · ${item.event_count} 条 · 查看原文</small><div class="card-pill-row">${renderEvPills([item.last_event_id])}</div></div>`).join("")
    : `<p class="empty">暂无会话行动轨迹。</p>`;
}

function render() {
  if (!state.data) return;
  const isSolo = effectiveWorkMode() === "solo";
  const workbenchView = isSolo ? (state.workbenchView === "mindmap" ? "mindmap" : "list") : "list";
  if (document.body?.dataset) {
    document.body.dataset.layer = state.layer;
    document.body.dataset.workMode = isSolo ? "solo" : "team";
    document.body.dataset.workbenchView = workbenchView;
  }
  document.querySelectorAll(".mode-pill").forEach((button) => button.classList?.toggle?.("active", button.dataset?.workMode === (isSolo ? "solo" : "team")));
  document.querySelectorAll(".layer-choice").forEach((button) => button.classList?.toggle?.("active", button.dataset?.layerChoice === state.layer));
  const viewBar = document.getElementById("workbench-view-bar");
  if (viewBar) viewBar.hidden = !isSolo || state.lens !== "personal";
  const listViewBtn = document.getElementById("view-list-btn");
  if (listViewBtn) listViewBtn.classList?.toggle?.("active", workbenchView === "list");
  const mindmapViewBtn = document.getElementById("view-mindmap-btn");
  if (mindmapViewBtn) mindmapViewBtn.classList?.toggle?.("active", workbenchView === "mindmap");
  const viewHintEl = document.getElementById("workbench-view-hint");
  if (viewHintEl) {
    viewHintEl.textContent = workbenchView === "mindmap"
      ? "实时正交脑图 · 点击任意分支溯源原文或定案"
      : "待拍板与已定案基准清晰分流 · 支持随手记与一键定案";
  }
  const submit = document.getElementById("investigate-submit");
  if (submit) submit.disabled = false;
  const reviewer = document.getElementById("reviewer-input");
  reviewer.readOnly = state.data.agent_api?.enabled === true || state.data.project?.read_only === true;
  if (reviewer.readOnly) {
    reviewer.value = state.data.agent_api?.owner_id || "";
  } else if (!reviewer.value) {
    const savedReviewer = readStorage("compass_reviewer_name").trim();
    if (savedReviewer) reviewer.value = savedReviewer;
  }
  reviewer.placeholder = isSolo ? "输入你的署名（自动记住）" : "填写姓名后可确认事实";
  applyModeLexicon(isSolo, workbenchView);
  selectAvailableMember();
  renderQuickNoteBar(isSolo);
  renderIntake();
  renderProjectScan();
  renderDerivedContext();
  renderExtraction();
  const guidance = document.getElementById("candidate-guidance");
  const intake = state.data.intake || {};
  const evidenceOnly = state.data.project?.fact_count === 0 && intake.enabled;
  const extraction = state.data.extraction || {};
  const pendingChars = Number.isInteger(extraction.pending_chars) ? extraction.pending_chars : 0;
  const partialCoverage = intake.enabled && state.data.project?.fact_count > 0 && pendingChars > 0;
  const guidanceVisible = evidenceOnly || partialCoverage;
  guidance.hidden = !guidanceVisible;
  if (guidanceVisible) {
    const extractionEnabled = extraction.enabled;
    const lead = evidenceOnly
      ? `已接入 ${state.data.project?.evidence_count || 0} 条原始材料和 ${intake.captured_messages || 0} 条公开会话消息，当前还没有结构化事实。`
      : `当前已有 ${state.data.project?.fact_count || 0} 条结构化事实，仍有约 ${pendingChars} 个字符尚未进入候选整理。`;
    guidance.innerHTML = `<span>${lead}${extractionEnabled ? (isSolo ? "可以启动一批候选整理，结果仍需你拍板定案。" : "可以启动一批候选整理，结果仍需负责人确认。") : "当前服务未启用候选整理，请用 --enable-extraction 重启。"}</span>${extractionEnabled ? '<button type="button" id="guidance-extract">整理一批新材料</button>' : ""}`;
  }
  const view = activeView();
  const facts = view.facts || [];
  const relations = [...(state.data.candidate_relations || []), ...(state.data.confirmed_relations || [])];
  const factIds = new Set(facts.map((fact) => fact.id));
  const sourceIds = new Set(view.evidence_ids || []);
  facts.forEach((fact) => [...(fact.evidence_ids || []), ...(fact.source_state?.replacement_ids || []), ...(fact.source_state?.observation_ids || [])].forEach((id) => sourceIds.add(id)));
  (state.data.confirmed_relations || []).filter((relation) => factIds.has(relation.fact_id)).forEach((relation) => sourceIds.add(relation.evidence_id));
  const catalog = state.data.evidence || [];
  const evidence = state.lens === "team" ? catalog : catalog.filter((item) => sourceIds.has(item.id));
  const query = state.evidenceQuery.trim().toLowerCase();
  const visibleEvidence = query ? evidence.filter((item) => `${item.id} ${item.content_preview} ${item.search_excerpt || ""} ${item.command_preview || ""} ${item.source_ref || ""} ${item.author || ""}`.toLowerCase().includes(query)) : evidence;
  const candidates = relations.filter((relation) => relation.status === "candidate" && factIds.has(relation.fact_id)).length;
  const tasks = facts.filter((fact) => fact.kind === "task").length;
  const unlinkedEvidence = evidence.filter((item) => !(item.candidate_fact_ids?.length || item.confirmed_fact_ids?.length)).length;
  const acceptedGoals = facts.filter((fact) => fact.kind === "goal" && resolveFactStatus(fact) === "accepted" && sourceCurrent(fact));
  const liveGoals = facts.filter((fact) => fact.kind === "goal" && fact.author !== "project-documents" && sourceCurrent(fact));
  const allCurrentGoals = facts.filter((fact) => fact.kind === "goal" && sourceCurrent(fact));
  const personalGoal = acceptedGoals[acceptedGoals.length - 1] || liveGoals[liveGoals.length - 1] || allCurrentGoals[allCurrentGoals.length - 1] || null;
  const goal = personalGoal || (state.lens === "personal" ? view.fallback_goal : null) || null;

  const llmBadgeEl = document.getElementById("llm-status-badge");
  const llmInfo = state.data.llm_status || {};
  if (llmBadgeEl) {
    llmBadgeEl.textContent = llmInfo.provider_label || "本地检索";
    llmBadgeEl.className = `status-badge ${llmInfo.enabled ? "is-accepted" : "is-proposed"}`;
  }
  const llmSelectEl = document.getElementById("llm-profile-select");
  if (llmSelectEl) {
    const profiles = !state.data?.sample_mode && Array.isArray(llmInfo.profiles) ? llmInfo.profiles : [];
    llmSelectEl.hidden = profiles.length <= 1;
    if (profiles.length > 1) {
      llmSelectEl.innerHTML = profiles.map((p) => {
        const text = p.id === "local" ? "切换：本地检索" : `切换：${p.label || p.model || p.id}`;
        const selected = p.id === llmInfo.active_profile ? " selected" : "";
        return `<option value="${esc(p.id)}"${selected}>${esc(text)}</option>`;
      }).join("");
      llmSelectEl.value = llmInfo.active_profile || profiles[0].id || "";
    } else {
      llmSelectEl.innerHTML = "";
    }
  }

  document.getElementById("project-title").textContent = state.data.project?.name || "Compass";
  document.getElementById("evidence-count").textContent = state.data.project?.evidence_count ?? catalog.length;
  document.getElementById("evidence-kicker").textContent = state.lens === "team" ? (isSolo ? "项目基准证据" : "团队共识证据") : state.member === "project-documents" ? "项目材料档案" : (isSolo ? "实时行动记录" : "个人证据链");
  const goalEffectiveStatus = goal ? resolveFactStatus(goal) : "proposed";
  const isGoalAccepted = Boolean(goal && goalEffectiveStatus === "accepted");
  const goalBadgeMeta = getBadgeMeta(goalEffectiveStatus);

  document.getElementById("goal-title").textContent = goal ? (goal.short_title || goal.clean_value || cleanUiText(goal.value)) : "核心目标待定锚";
  document.getElementById("goal-note").textContent = goal
    ? `${isGoalAccepted ? (isSolo ? "已定案为核心目标" : "已确认为团队目标") : (isSolo ? "待定目标思路 · 尚未拍板定案" : "候选目标 · 尚未经负责人确认为团队共识")} · ${goal.evidence_ids?.length || 0} 条依据 · ${sourceTimeText(goal)}${isGoalAccepted ? "" : " · 有效性待核对"}`
    : state.data.project?.fact_count ? "请在下方或右侧思维脑图确认主目标，或在随手记补全一条核心目标。" : "写一条随手记或用 MCP 记下第 1 个目标，右侧脑图自动生长。";
  const goalStatusEl = document.getElementById("goal-status");
  goalStatusEl.textContent = isGoalAccepted
    ? (isSolo ? "已定案 · 核心目标" : "已确认 · 团队目标")
    : goalEffectiveStatus === "rejected"
      ? "已驳回"
      : `${statusLabel(goalEffectiveStatus)} · ${isSolo ? "待拍板定案" : "待负责人确认"}`;
  goalStatusEl.className = `status-pill status-badge ${isGoalAccepted ? "accepted " : ""}${goalBadgeMeta.cls}`;
  const goalSurface = typeof document.querySelector === "function" ? document.querySelector(".goal-surface") : null;
  if (goalSurface?.classList) {
    goalSurface.classList.toggle("is-accepted", isGoalAccepted);
    goalSurface.classList.toggle("is-conflicted", !isGoalAccepted && goalEffectiveStatus === "conflicted");
    goalSurface.classList.toggle("is-rejected", !isGoalAccepted && goalEffectiveStatus === "rejected");
    goalSurface.classList.toggle("is-proposed", !isGoalAccepted && goalEffectiveStatus !== "conflicted" && goalEffectiveStatus !== "rejected");
  }

  renderDualAnchors(isSolo, goal, isGoalAccepted);
  renderAgentHints(isSolo);
  const scopeTag = document.getElementById("investigation-scope-tag");
  if (scopeTag) scopeTag.textContent = state.lens === "team" ? (isSolo ? "项目基准范围" : "团队共识范围") : (isSolo ? "个人实时范围" : "个人视图范围");
  renderSessionPresence();
  renderTimelineAndThinkingLine(view, facts);
  const activeChapter = (view.timeline_chapters || []).find((ch) => ch.chapter_id === state.activeChapterId);
  const chapterFactSet = activeChapter ? new Set(activeChapter.fact_ids || []) : null;
  const filterByChapter = (items) => chapterFactSet ? items.filter((item) => chapterFactSet.has(item.id || item.fact_id)) : items;
  document.getElementById("facts-kicker").textContent = state.lens === "team" ? (isSolo ? "已定案项目基准" : "团队共识陈述") : state.member === "project-documents" ? "项目材料候选" : (isSolo ? "待定思路与近期记录" : "个人候选事实");
  document.getElementById("facts-count").textContent = facts.length;
  document.getElementById("spine-count").textContent = query ? `${visibleEvidence.length}/${evidence.length}` : evidence.length;
  document.getElementById("metrics").innerHTML = [
    metric(facts.length, state.lens === "team" ? (isSolo ? "基准条目" : "团队陈述") : state.member === "project-documents" ? "材料候选" : (isSolo ? "个人记录" : "个人候选")),
    metric(tasks, "待办候选"),
    metric(candidates, "候选关系"),
    metric((state.data.team?.facts || []).filter((fact) => fact.status === "accepted" && sourceCurrent(fact)).length, isSolo ? "已定案基准" : "当前已确认事实"),
    metric(unlinkedEvidence, "未关联证据"),
  ].join("");
  const queryStats = state.data.investigation_stats || {total: 0, cache_hits: 0, unique_questions: 0, repeated_questions: []};
  const hitRate = queryStats.total ? Math.round((queryStats.cache_hits / queryStats.total) * 100) : 0;
  document.getElementById("investigation-stats-count").textContent = `${queryStats.total} 次`;
  document.getElementById("investigation-stats-list").innerHTML = `<div class="stats-line"><strong>${queryStats.unique_questions}</strong><span>个不同问题 · 缓存命中 ${hitRate}%</span></div>${queryStats.repeated_questions?.length ? `<div class="stats-label">反复追问</div>${queryStats.repeated_questions.map((item) => `<div class="stats-question"><span>${esc(item.question)}</span><b>${item.count}</b></div>`).join("")}` : `<p class="empty">还没有重复问题。</p>`}${queryStats.recent_queries?.length ? `<div class="stats-label">最近查询</div>${queryStats.recent_queries.slice(-5).reverse().map((item) => `<div class="stats-recent"><span>${esc(item.question)}${item.evidence_gap_count ? ` · 缺证 ${item.evidence_gap_count}` : ""}</span><b>${item.cache_hit ? "缓存" : "新查"}</b></div>`).join("")}` : ""}`;
  renderActivityStream(isSolo);
  const todosRaw = state.lens === "personal" ? filterByChapter(facts.filter((fact) => fact.kind === "task")) : [];
  const liveTodos = todosRaw.filter((fact) => !fact.is_historical_doc);
  const todos = (isSolo && liveTodos.length) ? liveTodos : todosRaw;
  const activeTodos = [];
  const supersededTodos = [];
  for (const fact of todos) {
    const sup = findSupersedingAcceptedFact(fact);
    if (sup) supersededTodos.push({ fact, superseder: sup });
    else activeTodos.push(fact);
  }
  const todosCountEl = document.getElementById("personal-todos-count");
  if (todosCountEl) todosCountEl.textContent = activeTodos.length;
  document.getElementById("personal-todos").hidden = state.lens !== "personal";
  const renderTodoCard = (fact) => {
    const effectiveStatus = resolveFactStatus(fact);
    const accepted = effectiveStatus === "accepted";
    const rejected = effectiveStatus === "rejected";
    const isCompleted = fact.task_state === "completed" || fact.task_state === "reported_complete";
    let inlineTriage = "";
    if (accepted) {
      inlineTriage = `<span class="in-card-actions">${renderStatusBadge("accepted", isSolo ? "✓ 已定案" : "✓ 团队事实")}</span>`;
    } else if (!state.data.project?.read_only) {
      const acceptBtn = canInlineAcceptFact(fact) ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="${isSolo ? "定案为项目基准" : "采纳为团队任务"}">${isSolo ? "✓ 定案" : "✓ 采纳"}</button>` : "";
      const rejectBtn = rejected ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="驳回候选">✕ 驳回</button>`;
      inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
    }
    const freshCls = state.freshFactIds?.has?.(fact.id) ? " is-fresh-node" : "";
    const statusText = isSolo && effectiveStatus === "accepted" ? "已定案" : statusLabel(effectiveStatus);
    const conflictHint = renderCardConflictHintHTML(fact, isSolo);
    return `<div class="todo-item${freshCls}" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${isCompleted ? "☑" : "☐"} ${esc(fact.short_title || fact.clean_value || cleanUiText(fact.value))}</strong><span>进度：${isCompleted ? "已完成" : esc(taskStateLabel(fact.task_state))} · ${esc(statusText)} · ${fact.evidence_ids?.length || 0} 条依据</span>${conflictHint}<div class="card-pill-row">${renderStatusBadge(effectiveStatus)}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
  };
  const supersededHTML = supersededTodos.length
    ? `<details class="superseded-todos-fold"><summary>历史已接替记录（${supersededTodos.length} 条 · 默认折叠）</summary><div class="superseded-todos-list">${supersededTodos.map(({ fact, superseder }) => {
        const supTitle = truncateUiText(cleanUiText(superseder.short_title || superseder.value), 34);
        return `<div class="todo-item is-superseded-todo" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>☐ ${esc(fact.short_title || fact.clean_value || cleanUiText(fact.value))}</strong><span>已被新定案「${esc(supTitle)}」接替 · ${fact.evidence_ids?.length || 0} 条依据</span><div class="card-pill-row">${renderStatusBadge("superseded", "已由新定案接替")}${renderEvPills(fact.evidence_ids)}</div></div>`;
      }).join("")}</div></details>`
    : "";
  document.getElementById("personal-todo-list").innerHTML = activeTodos.length
    ? activeTodos.map(renderTodoCard).join("") + supersededHTML
    : (supersededHTML || `<p class="empty">${isSolo ? "暂无待办事项，可在上方随手记选择「待办事项」添加。" : "当前成员暂无待办候选。"}</p>`);
  const evidenceRequests = state.lens === "personal" ? (state.data.evidence_requests || []).filter((request) => request.member_id === state.member) : [];
  document.getElementById("personal-evidence-requests").hidden = state.lens !== "personal" || evidenceRequests.length === 0;
  document.getElementById("evidence-request-count").textContent = evidenceRequests.length;
  document.getElementById("evidence-request-list").innerHTML = evidenceRequests.length ? evidenceRequests.map((request) => `<button type="button" class="evidence-request-item" data-fact-id="${esc(request.fact_id)}"><strong>${esc(request.value)}</strong><span>${request.status === "ready_for_review" ? "已有新证据，可重新核对" : "等待新证据"} · ${request.new_evidence_ids?.length || 0} 条新增 · ${esc(request.note || (isSolo ? "待补充验证依据" : "负责人未填写说明"))}</span></button>`).join("") : `<p class="empty">当前成员没有待补证据任务。</p>`;
  const allDecisions = state.lens === "personal" ? filterByChapter(facts.filter((fact) => fact.kind === "decision" || fact.kind === "assumption")) : [];
  document.getElementById("personal-decisions").hidden = state.lens !== "personal";
  const decisionsCountEl = document.getElementById("personal-decisions-count");
  if (isSolo) {
    const pendingItems = allDecisions.filter((fact) => resolveFactStatus(fact) !== "accepted");
    const pendingDecs = pendingItems.filter((fact) => fact.kind === "decision");
    const pendingAssumps = pendingItems.filter((fact) => fact.kind === "assumption");
    if (decisionsCountEl) decisionsCountEl.textContent = pendingItems.length;
    const sections = [];
    if (pendingDecs.length) {
      sections.push(`<div class="decision-group"><h3 class="decision-group-head">待拍板决策 (${pendingDecs.length})</h3>${pendingDecs.map((fact) => renderDecisionCardHTML(fact, true)).join("")}</div>`);
    }
    if (pendingAssumps.length) {
      sections.push(`<div class="decision-group"><h3 class="decision-group-head">未验证前提 (${pendingAssumps.length})</h3>${pendingAssumps.map((fact) => renderDecisionCardHTML(fact, true)).join("")}</div>`);
    }
    document.getElementById("personal-decision-list").innerHTML = sections.length
      ? sections.join("")
      : `<p class="empty">当前没有待拍板思路或未验证前提 · 已定案项目基准见下方，或用上方随手记快速新增。</p>`;
  } else {
    if (decisionsCountEl) decisionsCountEl.textContent = allDecisions.length;
    document.getElementById("personal-decision-list").innerHTML = allDecisions.length
      ? allDecisions.map((fact) => renderDecisionCardHTML(fact, false)).join("")
      : `<p class="empty">当前成员暂无决策或未验证前提。</p>`;
  }
  const baselineSurface = document.getElementById("solo-baseline-surface");
  const baselineList = document.getElementById("solo-baseline-list");
  const baselineCount = document.getElementById("solo-baseline-count");
  if (baselineSurface && baselineList) {
    baselineSurface.hidden = !(isSolo && state.lens === "personal");
    if (!baselineSurface.hidden) {
      const mergedById = new Map();
      [...facts, ...(state.data.team?.facts || [])].forEach((fact) => {
        if (fact?.id) mergedById.set(fact.id, fact);
      });
      const kindRank = { goal: 0, decision: 1, assumption: 2, task: 3 };
      const baselineFacts = filterByChapter([...mergedById.values()])
        .filter((fact) => resolveFactStatus(fact) === "accepted" && sourceCurrent(fact))
        .sort((a, b) => (kindRank[a.kind] ?? 9) - (kindRank[b.kind] ?? 9));
      if (baselineCount) baselineCount.textContent = baselineFacts.length;
      baselineList.innerHTML = baselineFacts.length
        ? baselineFacts.map((fact) => renderDecisionCardHTML(fact, true)).join("")
        : `<p class="empty">尚无已定案项目基准 · 可在上方面板点击「✓ 定案基准」或在随手记勾选「直接定案为基准」。</p>`;
    }
  }
  const reviewQueue = filterByChapter(state.data.team_review_queue || []);
  const reviewSurface = document.getElementById("team-review-queue");
  reviewSurface.hidden = state.lens !== "team" || (isSolo && reviewQueue.length === 0);
  document.getElementById("team-review-count").textContent = reviewQueue.length;
  document.getElementById("team-review-list").innerHTML = reviewSurface.hidden ? "" : reviewQueue.length
    ? reviewQueue.map((item) => {
        const qFact = (state.data.team?.facts || []).find((f) => f.id === item.fact_id);
        let inlineTriage = "";
        if (!state.data.project?.read_only) {
          const allowAccept = qFact ? canInlineAcceptFact(qFact) : true;
          const qStatus = qFact ? resolveFactStatus(qFact) : item.status;
          const acceptBtn = allowAccept && qStatus !== "accepted" ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(item.fact_id)}" title="${isSolo ? "定案为基准" : "直接确认入库"}">${isSolo ? "✓ 定案" : "✓ 确认"}</button>` : "";
          const rejectBtn = qStatus === "rejected" ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(item.fact_id)}" title="驳回">✕ 驳回</button>`;
          inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
        }
        return `<div class="review-queue-item" role="button" tabindex="0" data-fact-id="${esc(item.fact_id)}">${renderStatusBadge(item.status, item.status === "conflicted" ? "冲突" : item.status === "needs_evidence" ? "补证据" : "待确认")}<span class="review-queue-main"><strong>${esc(item.value)}</strong><small>${esc(item.reason)} · ${esc(item.author || "作者未提供")} · ${item.evidence_count} 条证据 · ${item.candidate_relation_count} 条候选关系</small><span class="card-pill-row">${renderEvPills(qFact?.evidence_ids)}</span>${inlineTriage}</span></div>`;
      }).join("")
    : `<p class="empty">${isSolo ? "当前没有待定案条目。" : "当前没有待负责人核对的团队事实。"}</p>`;
  document.getElementById("fact-list").innerHTML = facts.length ? facts.map((fact) => factCard(fact, relations)).join("") : `<p class="empty">当前视图还没有结构化事实。原始材料仍可在证据脊柱中查看。</p>`;
  renderTrace(facts, relations, evidence);
  renderDirections(view.directions || {candidates:[],current:[],history:[]}, state.lens === "team");
  renderReasonPreview();
  renderTeamHistory();
  document.getElementById("evidence-filter").value = state.evidenceQuery;
  const evidencePageSize = 50;
  const renderedEvidence = visibleEvidence.slice(0, evidencePageSize);
  const hiddenEvidenceCount = visibleEvidence.length - renderedEvidence.length;
  const evidenceLimitNote = hiddenEvidenceCount > 0
    ? `<p class="empty">原文层当前显示 ${renderedEvidence.length} 条，另有 ${hiddenEvidenceCount} 条可继续缩小筛选；完整原文可从过程层来源或证据 ID 打开。</p>`
    : "";
  document.getElementById("evidence-spine").innerHTML = renderedEvidence.length
    ? renderedEvidence.map(evidenceCard).join("") + evidenceLimitNote
    : `<p class="empty">没有匹配的证据材料。</p>`;
  document.querySelectorAll(".lens").forEach((button) => button.classList.toggle("active", button.dataset.lens === state.lens));
  renderMemberPicker(Object.keys(state.data.personal || {}));
  bindDynamicControls();
}

function renderProjectScan() {
  const scan = state.data?.project_scan;
  document.getElementById("project-scan-bar").hidden = !scan?.enabled;
  document.getElementById("project-scan-status").textContent = !scan?.last_checked_at ? "文件视图来自已保存扫描，可重新检查项目。" : `文件检查 ${formatTime(scan.last_checked_at)} · ${scan.file_count} 份当前文件 · ${scan.changed_files} 份换版 · ${scan.unavailable_files} 份当前不可用。新内容需提取后才会形成候选。`;
}

function renderDerivedContext() {
  const surface = document.getElementById('derived-context-surface');
  const context = state.data?.derived_context;
  surface.hidden = !context?.enabled;
  if (!context?.enabled) return;
  const nodes = context.nodes || [];
  const edges = context.edges || [];
  const directIds = new Set(context.direct_node_ids || []);
  const relatedIds = new Set(context.related_node_ids || []);
  const labelById = new Map(nodes.map((node) => [node.id, node.label || node.id]));
  const edgesByNode = new Map();
  for (const edge of edges) {
    if (!edgesByNode.has(edge.from_id)) edgesByNode.set(edge.from_id, []);
    edgesByNode.get(edge.from_id).push(`${edge.kind} → ${labelById.get(edge.to_id) || edge.to_id}`);
  }
  document.getElementById('derived-context-count').textContent = nodes.length;
  const freshness = context.current === true ? '来源当前' : context.current === false ? '来源已变化或不可用' : '来源当前性未知';
  const relatedNote = relatedIds.size ? ` · 关联当前证据节点 ${relatedIds.size} 个` : '';
  const noteEl = document.getElementById('derived-context-note');
  noteEl.classList.toggle('source-warning', context.current === false);
  noteEl.textContent = `${freshness} · ${context.source_ref || '结构图来源未知'} · ${edges.length} 条结构关系${relatedNote}${context.truncated ? ' · 页面已截断' : ''}。此处仅供导航，不代表团队事实。`;
  const ordered = [...nodes].sort((a, b) => Number(relatedIds.has(b.id)) - Number(relatedIds.has(a.id)) || Number(directIds.has(b.id)) - Number(directIds.has(a.id)));
  document.getElementById('derived-context-list').innerHTML = ordered.length
    ? ordered.map((node) => {
        const badge = directIds.has(node.id) ? ' · 证据直接来源' : relatedIds.has(node.id) ? ' · 证据关联结构' : '';
        const relations = edgesByNode.get(node.id) || [];
        const relationLine = relations.length ? `<small class="derived-context-edges">结构关系：${esc(relations.slice(0, 4).join(' · '))}${relations.length > 4 ? ` 等 ${relations.length} 条` : ''}</small>` : '';
        return `<div class="derived-context-item${relatedIds.has(node.id) ? ' related' : ''}"><strong>${esc(node.label || node.id)}</strong><span>${esc(node.kind)} · ${esc(node.source_ref)} · ${esc(node.origin || 'derived_context')}${badge}</span>${node.summary ? `<small>${esc(node.summary)}</small>` : ''}${relationLine}</div>`;
      }).join('')
    : '<p class="empty">当前结构上下文没有节点。</p>';
}

function extractionMember() {
  return state.lens === 'personal' && state.member && state.member !== 'project-documents' ? state.member : null;
}

function renderExtraction() {
  const job = state.data?.extraction;
  document.getElementById("extraction-bar").hidden = !job?.enabled;
  if (!job?.enabled) return;
  const names = {idle:"等待整理", running:"正在整理候选", complete:"本批已完成", failed:"本批失败，自动重试已停止", stopped:"本次启动预算已停止"};
  const member = extractionMember();
  const scope = job.batches_used > 0 ? job.scope : member ? {kind:'member',member_id:member} : {kind:'project'};
  const scopeNote = scope?.kind === 'member' ? `成员 ${scope.member_id}` : '项目材料与对话';
  const added = Number.isInteger(job.last_result?.new_candidates) ? job.last_result.new_candidates : null;
  const resultNote = added !== null ? `本批新增 ${added} 条候选 · ` : "";
  const rejected = Array.isArray(job.last_result?.rejected_candidates) ? job.last_result.rejected_candidates.length : 0;
  const rejectionNote = rejected ? `本批拒绝 ${rejected} 条无精确引文候选 · ` : "";
  document.getElementById("extraction-status").textContent = `${job.automatic ? "自动整理" : "手动整理"} · ${scopeNote} · ${names[job.state] || job.state} · 本次启动 ${job.batches_used}/${job.max_batches} 批 · ${job.running ? "本批用量待回报 · " : ""}已知 ${job.known_tokens} tokens，停止阈值 ${job.max_tokens}，单次可能超出 · 未知用量 ${job.unknown_usage_requests} 次 · 项目待检查 ${job.pending_chars ?? "未知"} 字符。${resultNote}${rejectionNote}候选仍需负责人确认。`;
  document.getElementById("extract-candidates").textContent = member ? '整理当前成员对话' : '整理一批项目候选';
  document.getElementById("extract-candidates").disabled = job.running || job.closed || job.batches_used >= job.max_batches || job.known_tokens >= job.max_tokens || job.unknown_usage_requests > 0 || job.pending_chars === 0 || (member && Array.isArray(job.eligible_members) && !job.eligible_members.includes(member));
}

async function extractCandidates() {
  try {
    const member = extractionMember();
    const payload = await apiFetch("/api/extract", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(member ? {member_id:member} : {})});
    if (payload?.extraction) { state.data.extraction = payload.extraction; renderExtraction(); }
  } catch (error) {
    if (error.payload?.extraction) { state.data.extraction = error.payload.extraction; renderExtraction(); }
    document.getElementById("extraction-status").textContent = `候选整理未启动。${error.message}`;
  }
}

async function rescanProject() {
  if (state.rescanning || !state.data?.project_scan?.enabled) return;
  state.rescanning = true;
  document.getElementById("rescan-project").disabled = true;
  try {
    const payload = await apiFetch("/api/rescan", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    if (olderState(payload)) return;
    state.data = payload;
    render();
    if (payload.project_scan.updated) invalidateInvestigation("项目来源已更新。历史确认保留，换版或不可用的来源需要复核，请重新提问。");
  } catch (error) {
    document.getElementById("project-scan-status").textContent = `项目扫描失败，已保存记录保留。${error.message}`;
  } finally {
    state.rescanning = false;
    document.getElementById("rescan-project").disabled = false;
  }
}

function formatConnectionLabel(data) {
  if (data?.sample_mode === true) return "合成样例 · 本地工作区";
  const rawPath = String(data?.project?.path || "").trim();
  if (!rawPath) return "本地工作区";
  const projName = data?.project?.name || rawPath.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
  return projName ? `本地工作区 · ${projName}` : "本地工作区";
}

function renderIntake() {
  const intake = state.data?.intake;
  const api = state.data?.agent_api;
  const ruleScan = intake?.direction_scan;
  const userScan = intake?.user_task_scan;
  const sample = state.data?.sample_mode === true;
  document.getElementById("connection-label").textContent = formatConnectionLabel(state.data);
  const syncEl = document.getElementById("sync-time-label");
  if (syncEl) {
    const checkedAt = !sample && state.data?.project_scan?.last_checked_at ? String(state.data.project_scan.last_checked_at) : "";
    const parsed = checkedAt ? new Date(checkedAt) : null;
    const hhmm = parsed && !Number.isNaN(parsed.getTime())
      ? `${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`
      : "";
    syncEl.hidden = !hhmm;
    syncEl.textContent = hhmm ? `· 同步 ${hhmm}` : "";
  }
  document.getElementById("intake-bar").hidden = !sample && !intake?.enabled && !api?.enabled && !ruleScan?.enabled && !userScan?.enabled;
  document.getElementById("refresh-intake").hidden = sample;
  if (sample) {
    document.getElementById("intake-status").textContent = "合成样例供试用。包含两名成员和一组冲突，审核仅保存在独立样例工作区，不代表真实项目验收或赞助服务已连接。";
    return;
  }
  const apiNote = api?.enabled ? `Agent HTTP 已启用 · ${api.clients?.length || 0} 个 Agent 上下文可提交证据与候选。` : '';
  const ruleNote = ruleScan?.enabled ? `方向规则已扫 ${ruleScan.completed_sources}/${ruleScan.eligible_sources} 条${ruleScan.pending_sources ? `（仍有 ${ruleScan.pending_sources} 条待扫）` : ''}。` : '';
  const userNote = userScan?.enabled ? `用户任务规则已扫 ${userScan.completed_sources}/${userScan.eligible_sources} 条${userScan.pending_sources ? `（仍有 ${userScan.pending_sources} 条待扫）` : ''}${userScan.skipped_long_sources ? `，${userScan.skipped_long_sources} 条长消息保留原文` : ''}。` : '';
  const scopeNote = (ruleScan?.enabled || userScan?.enabled) ? '规则仅匹配明确短句，不含深度语义提取。' : '';
  if (!intake?.enabled) {
    document.getElementById('intake-status').textContent = apiNote + ruleNote + userNote + scopeNote;
    return;
  }
  const extractionNote = state.data?.extraction?.enabled ? "候选整理状态见下方。" : "新材料需单独提取。";
  const toolNote = intake.tools_enabled ? `工具记录 ${intake.stored_tool_records || 0} 条，最多回填 ${intake.max_tool_pairs} 组文本调用与结果；命令执行 ${intake.stored_native_commands || 0} 条，最多回填 ${intake.max_native_commands || 200} 条。` : intake.stored_tool_records || intake.stored_native_commands ? `保留 ${intake.stored_tool_records || 0} 条工具历史与 ${intake.stored_native_commands || 0} 条命令执行，当前未采集新的工具记录。` : "当前不包含工具输出。";
  const backfill = intake.backfill;
  const backfillNote = backfill?.enabled ? `历史原文回填 ${backfill.state === 'complete' ? '已完成' : backfill.state === 'pending' ? '进行中' : '尚未开始'} · 已完成 ${backfill.batches_completed || 0} 批 · 仍有 ${backfill.remaining_tool_pairs || 0} 组工具调用与 ${backfill.remaining_commands || 0} 条命令记录 · ${backfill.raw_only ? '只收录原文，不代表语义整理完整。' : ''}` : '';
  const intakeChannelLabel = intake.channel === "antigravity" ? "Antigravity 会话已连接" : intake.channel === "codex" ? "Codex 会话已连接" : "会话通道已连接";
  document.getElementById("intake-status").textContent = `${intakeChannelLabel} · ${intake.captured_messages || 0} 条公开消息 · ${intake.skipped_sensitive || 0} 条敏感或环境消息与 ${intake.skipped_control || 0} 条平台标记已跳过。${toolNote}${backfillNote}${apiNote}${extractionNote}${ruleNote}${userNote}${scopeNote}`;
}

function invalidateInvestigation(message) {
  state.revision += 1;
  const panel = document.getElementById("investigation-answer");
  panel.hidden = false;
  panel.innerHTML = `<p class="empty">${esc(message)}</p>`;
}

async function refreshNative() {
  if (!state.data || state.data.sample_mode === true || state.data.project?.read_only || state.refreshing) return;
  state.refreshing = true;
  const refreshBtn = document.getElementById("refresh-intake");
  if (refreshBtn) refreshBtn.disabled = true;
  try {
    const useRefresh = Boolean(state.data.intake?.enabled || state.data.intake?.direction_scan?.enabled || state.data.intake?.user_task_scan?.enabled);
    const payload = useRefresh
      ? await apiFetch("/api/refresh", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
      : await apiFetch("/api/state", { background: true });
    if (olderState(payload)) return;
    const prevActSig = `${state.data.activity_stream?.[0]?.id || ""}:${state.data.activity_stream?.length || 0}`;
    const nextActSig = `${payload.activity_stream?.[0]?.id || ""}:${payload.activity_stream?.length || 0}`;
    const evidenceChanged = payload.project.evidence_count !== state.data.project.evidence_count;
    const reviewChanged = (payload.review_history?.length || 0) !== (state.data.review_history?.length || 0);
    const candidatesChanged = payload.project.fact_count !== state.data.project.fact_count;
    const versionChanged = payload.state_version !== state.data.state_version;
    const activityChanged = prevActSig !== nextActSig;
    const prevHintSig = `${state.data.hint_generation || 0}:${(state.data.agent_hints || []).map((h) => h.id).join(",")}`;
    const nextHintSig = `${payload.hint_generation || 0}:${(payload.agent_hints || []).map((h) => h.id).join(",")}`;
    if (evidenceChanged || reviewChanged || candidatesChanged || versionChanged || activityChanged) {
      const prevIds = collectFactIdSet(state.data);
      const nextIds = collectFactIdSet(payload);
      const newlyAdded = [...nextIds].filter((id) => !prevIds.has(id));
      if (newlyAdded.length) {
        state.freshFactIds = new Set(newlyAdded);
        if (state.freshTimer) clearTimeout(state.freshTimer);
        state.freshTimer = setTimeout(() => {
          state.freshFactIds = new Set();
          state.freshTimer = null;
          render();
        }, 4000);
      }
      state.data = payload;
      render();
      invalidateInvestigation(candidatesChanged ? "新候选已更新，原始材料和负责人确认记录保留，请重新提问。" : evidenceChanged ? payload.intake?.new_tool_records ? "已接入工具记录，原有事实与确认历史保留，请重新提问。" : "已接入新消息。原有事实与确认记录保留，新材料需提取后再重新调查。" : "项目状态或负责人确认记录已更新，请重新提问以使用最新状态。");
    } else {
      state.data.intake = payload.intake;
      state.data.extraction = payload.extraction;
      if (payload.llm_status) state.data.llm_status = payload.llm_status;
      renderIntake();
      renderExtraction();
      if (nextHintSig !== prevHintSig) {
        state.data.agent_hints = payload.agent_hints;
        state.data.hint_generation = payload.hint_generation;
        renderAgentHints(effectiveWorkMode() === "solo");
        bindDynamicControls();
      }
    }
  } catch (error) {
    const intakeStatusEl = document.getElementById("intake-status");
    if (intakeStatusEl) intakeStatusEl.textContent = `会话刷新失败，已保存内容保留。${error.message}`;
  } finally {
    state.refreshing = false;
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

function rawFindingMeta(item) {
  if (item.status !== 'raw') return '';
  const kind = ({git_commit:'Git 提交',command_execution:'命令记录',test_result:'测试记录',tool_result:'工具结果',assistant_message:'助手发言',user_message:'用户发言'})[item.source_kind] || item.source_kind || '来源记录';
  const execution = ['command_execution','test_result','tool_result'].includes(item.source_kind);
  const command = item.command_preview ? `<span class="evidence-command">${esc(item.command_preview)}</span>` : '';
  const origin = item.command_origin ? ` · ${commandOriginLabel(item.command_origin)}` : '';
  const exit = execution ? ` · 退出码 ${Number.isInteger(item.exit_code) ? item.exit_code : '未知'}` : '';
  return `<div class="raw-finding-meta"><strong>${esc(kind)} · 原始记录</strong><span>${esc(origin + exit)}</span>${command}${item.source_ref ? `<span class="trace-meta">${esc(item.source_ref)}</span>` : ''}</div>`;
}

const directionLabel = (value) => ({abandoned:'已放弃',deferred:'已暂缓',active:'已恢复推进'}[value] || '状态待核对');
const directionCandidateLabel = (value) => ({abandoned:'放弃表述',deferred:'暂缓表述'}[value] || '状态待核对');
function directionStateText(fact) {
  const current=(state.data?.team?.directions?.current || []).find((row)=>row.fact_id===fact.id);
  return current ? `团队方向${directionLabel(current.direction_state)} · 本卡保留原始状态表述` : '';
}
function directionFindingMeta(item) {
  if (!item.direction_state) return '';
  return `<p class="${item.status === 'accepted' ? 'reviewed-note' : 'meta-note'}">${esc(item.status === 'proposed' ? directionCandidateLabel(item.direction_state) : directionLabel(item.direction_state))} · ${item.status === 'proposed' ? '状态候选' : item.current ? '当前确认' : '历史确认'} · 下方保留原始状态表述</p>`;
}

function renderDirections(directions, isTeam) {
  const surface = document.getElementById("direction-surface");
  if (!surface) return;
  const isSolo = effectiveWorkMode() === "solo";
  const current = directions.current || [], history = directions.history || [];
  const rows = isTeam ? current.filter((row) => row.direction_state !== "active") : directions.candidates || [];
  document.getElementById("direction-title").textContent = isTeam ? "舍弃与暂缓方向" : "方向状态候选";
  document.getElementById("direction-count").textContent = rows.length;
  document.getElementById("direction-note").textContent = isTeam
    ? (isSolo ? "清单仅收录你明确拍板定案的方向。恢复及旧状态保留在下方历史。" : "清单仅收录负责人明确确认的方向。恢复及旧状态保留在下方历史。")
    : "明确表述仍是候选。未被采用的建议不会自动归为已放弃。";
  const entry = (row, historical = false) => `<div class="direction-entry"><div class="detail-label">${esc(!isTeam && row.status === "proposed" ? directionCandidateLabel(row.direction_state) : directionLabel(row.direction_state))} · ${historical ? (row.current ? "当前确认" : "历史确认") : isTeam ? (isSolo ? "已定案" : "负责人已确认") : (isSolo ? "待定案" : "待负责人确认")}</div><button type="button" class="direction-open" data-fact-id="${esc(row.fact_id)}">${esc(row.quote)}</button><p class="meta-note">${esc(row.member_id || "")} · ${sourceTimeHTML(row)}</p>${row.reviewed_by ? `<p class="reviewed-note">${esc(row.reviewed_by)} · ${esc(formatTime(row.reviewed_at))}</p>` : ""}<div>${(row.evidence_ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("")}</div>${sourceNote(row) ? `<p class="source-warning">${esc(sourceNote(row))}</p>` : ""}</div>`;
  document.getElementById("direction-list").innerHTML = rows.length ? rows.map((row) => entry(row)).join("") : `<p class="empty">${isTeam ? (isSolo ? "尚无已定案的舍弃或暂缓方向。" : "尚无当前已确认的放弃或暂缓方向。") : "尚无可归类的明确方向表述。可继续查看个人候选和原始来源。"}</p>`;
  document.getElementById("direction-history").innerHTML = isTeam && history.length ? `<div class="history-label">方向状态历史 · ${history.length}</div>${history.map((row) => entry(row, true)).join("")}` : "";
}

function reasonPreviewHTML(preview) {
  const isSolo = effectiveWorkMode() === "solo";
  const rows = preview?.candidates || [], gaps = preview?.gaps || [];
  const links = (ids) => (ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("");
  const target = (row) => `<button type="button" class="reason-target" data-fact-id="${esc(row.target_fact_id)}">对应陈述 · ${esc(row.target_quote)}</button>`;
  const quotes = (items, qLabel) => !items?.length ? "" : `<details class="reason-sources"><summary>${esc(qLabel)} · ${items.length}</summary>${items.map((q) => `<div class="detail-block"><p class="meta-note">${esc(q.member_id)} · ${esc(claimLabel(q.claim_type))} · ${esc(q.reported_by)} · ${sourceTimeHTML(q)}</p><pre class="reason-quote">${esc(q.quote)}</pre>${links([q.source_id])}</div>`).join("")}</details>`;
  return `<p class="empty">${isSolo ? "只读预览 · 待你核对。引文匹配仅核对出处，原因联系与模型分类仍需复核。" : "只读预览 · 待负责人核对。引文匹配仅核对出处，原因联系与模型分类仍需核对。"}</p>${preview?.unavailable_targets ? `<p class="source-warning">${esc(preview.unavailable_targets)} 项目标或来源已变化，相关预览暂未展示。</p>` : ""}${rows.map((row) => `<article class="reason-card"><div class="detail-label">${row.relation_type_suggested === "hypothesized_reason" ? "推断假说" : "来源说明候选"} · 待核对</div>${target(row)}<p class="detail-value">${esc(row.summary)}</p>${row.assumptions?.length ? `<div class="reason-assumptions"><strong>推断前提</strong>${row.assumptions.map((a) => `<p>${esc(a)}</p>`).join("")}</div>` : ""}${quotes(row.source_quotes, "原文引文")}${quotes(row.counter_evidence, "反向或替代线索")}<p class="meta-note">生成模型 ${esc(row.model || "")}</p></article>`).join("")}${gaps.map((gap) => `<div class="reason-gap">${target(gap)}<p class="detail-label">所选材料中的缺证说明</p><p class="detail-value">${esc(gap.text)}</p>${links(gap.scope_source_ids)}</div>`).join("")}${!rows.length && !gaps.length ? '<p class="empty">当前问题或视图没有匹配的原因预览，可继续核对原始材料。</p>' : ""}`;
}

function renderReasonPreview() {
  const surface = document.getElementById("reason-preview-surface");
  if (!surface) return;
  const preview = state.data?.reason_preview; surface.hidden = !preview?.enabled;
  if (!preview?.enabled) return;
  const selected = {...preview, candidates: (preview.candidates || []).filter((r) => state.lens === "team" || r.member_id === state.member), gaps: (preview.gaps || []).filter((r) => state.lens === "team" || r.member_id === state.member)};
  document.getElementById("reason-preview-count").textContent = selected.candidates.length;
  document.getElementById("reason-preview-list").innerHTML = reasonPreviewHTML(selected);
}

function truncateUiText(text, maxLen = 64) {
  const clean = cleanUiText(text || "");
  if (clean.length <= maxLen) return clean;
  return clean.slice(0, Math.max(1, maxLen - 1)).trimEnd() + "…";
}

function renderInvestigation(answer) {
  const panel = document.getElementById("investigation-answer");
  const isSolo = effectiveWorkMode() === "solo";
  panel.hidden = false;
  const evidenceLinks = (ids) => (ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("");
  const scopeLabel = answer.scope ? (isSolo ? "个人记录" : "成员记录") : (isSolo ? "当前目标" : "团队目标");
  const basis = answer.next_action_basis;
  const actionLabel = answer.next_action_status === "accepted" ? "已确认下一步" : basis ? "候选下一步" : "下一步动作";
  const basisHTML = basis ? `<div class="detail-block"><p class="meta-note">${sourceTimeHTML(basis)} · ${esc(basis.member_id || "")} · ${esc(claimLabel(basis.claim_type))}</p>${basis.status === "accepted" ? `<p class="reviewed-note">${esc(basis.reviewed_by || "owner")} · ${sourceTimeHTML({observed_at: basis.reviewed_at}, isSolo ? "定案时间" : "负责人确认时间")}</p>` : '<p class="source-warning">候选来源的当前版本需核对，历史任务不会自动成为当前确认。</p>'}${evidenceLinks(basis.evidence_ids || [])}</div>` : "";
  const conflicts = answer.conflicts || [];
  const sourceWarnings = Array.isArray(answer.source_warnings) ? answer.source_warnings : [];
  const acceptedWarnCount = sourceWarnings.filter((item) => item?.status === "accepted").length;
  const goalUpdatedBadge = acceptedWarnCount > 0 ? '<span class="status-badge is-warn">已定案来源有更新</span>' : "";
  const displayGoal = cleanUiText(answer.goal);
  const shortGoal = truncateUiText(displayGoal, 64);
  const displayNextAction = cleanUiText(answer.next_action);
  const hasSettledNext = answer.next_action_status === "accepted";
  const nextBadgeStatus = hasSettledNext ? "accepted" : (answer.next_action_status || (basis ? "proposed" : "info"));
  const nextBadgeText = hasSettledNext ? (isSolo ? "已定案" : "已确认") : (basis ? "待定建议" : "指引");
  const hasEmptyNext = !displayNextAction || /尚未提取|暂未设定|未找到/.test(displayNextAction);
  const editNextBtn = (!state.data?.project?.read_only && hasEmptyNext)
    ? '<button type="button" class="mini-btn accept-btn" data-anchor-edit="next_step" data-anchor-seed="">✎ 设定下一步</button>'
    : "";

  const summaryHTML = answer.semantic_summary
    ? `<div class="answer-semantic-summary"><span class="status-badge is-accepted">语义归纳</span><p>${esc(cleanUiText(answer.semantic_summary))}</p></div>`
    : `<div class="answer-conclusion">${esc(cleanUiText(answer.conclusion))}</div>`;

  const completedList = Array.isArray(answer.completed_items) ? answer.completed_items : [];
  const completedHTML = completedList.length
    ? `<div class="answer-takeaway-row is-completed-focus">
      <div class="takeaway-head"><span class="detail-label">近期已完成事项</span><span class="status-badge is-accepted">已核实记录</span></div>
      <div class="completed-items-list">${completedList.slice(0, 3).map((item) => {
        const title = truncateUiText(cleanUiText(item.quote || item.value || ""), 78);
        return `<div class="completed-item-line"><strong>${esc(title)}</strong><div class="meta-note">${sourceTimeHTML(item)} ${evidenceLinks(item.evidence_ids || [])}</div></div>`;
      }).join("")}</div>
    </div>`
    : "";

  const takeawaysHTML = `<div class="answer-key-takeaways answer-grid">
    ${completedHTML}
    <div class="answer-takeaway-row">
      <div class="takeaway-head"><span class="detail-label">${scopeLabel}</span>${goalUpdatedBadge}</div>
      <div class="detail-value takeaway-goal-text" title="${esc(displayGoal)}">${esc(shortGoal || "暂无目标")}</div>
    </div>
    <div class="answer-takeaway-row is-next-focus">
      <div class="takeaway-head"><span class="detail-label">${actionLabel}</span>${renderStatusBadge(nextBadgeStatus, nextBadgeText)}${editNextBtn}</div>
      <strong class="takeaway-next-text">${esc(displayNextAction || "暂未设定下一步")}</strong>
      ${basisHTML}
    </div>
  </div>`;

  const evidenceSectionHTML = `<div class="answer-evidence-section">
    <div class="detail-label">命中的核心依据${answer.findings?.length ? `（${answer.findings.length}）` : ""}</div>
    <div class="answer-evidence-list">${evidenceLinks(answer.evidence_ids)}</div>
  </div>`;

  const conflictsHTML = conflicts.length
    ? `<div class="answer-conflicts"><div class="detail-label">分歧历史</div>${conflicts.map((conflict) => `<div class="answer-conflict"><strong>${esc(conflict.subject_key)}</strong>${(conflict.sides || []).map((side) => { const sideStatus = resolveFactStatus(side.fact_id ? { id: side.fact_id, status: side.status } : side); return `<span>${renderStatusBadge(sideStatus)} ${esc(side.value)} · ${sourceTimeHTML(side)} · ${evidenceLinks(side.evidence_ids)}</span>`; }).join("")}</div>`).join("")}</div>`
    : "";

  const gapsList = answer.evidence_gaps || [];
  const needsOpenGaps = gapsList.some((gap) => /尚未得到回答|证据不足|未找到/.test(String(gap)));
  const footnoteItems = [...gapsList];
  if (answer.acceptance_condition) footnoteItems.push(`验收条件：${answer.acceptance_condition}`);
  const footnotesHTML = footnoteItems.length
    ? `<details class="answer-footnotes"${needsOpenGaps ? " open" : ""}><summary>核验边界与验收说明（${footnoteItems.length}）</summary>${footnoteItems.map((item) => `<p class="detail-value">${esc(item)}</p>`).join("")}</details>`
    : "";

  const warningsFoldHTML = sourceWarnings.length
    ? `<details class="answer-footnotes answer-warnings-fold"><summary>历史来源变动复核明细（${sourceWarnings.length} 项 · 默认折叠）</summary><div class="answer-warnings-list">${sourceWarnings.map((item) => `<div class="answer-warning-item"><p>${esc(item.fact_id)} · ${esc(statusLabel(item.source_state?.status || "unknown"))} · 原状态 ${esc(statusLabel(item.status || "proposed"))}</p><div class="card-pill-row">${evidenceLinks([...(item.evidence_ids || []), ...(item.source_state?.replacement_ids || []), ...(item.source_state?.observation_ids || [])])}</div></div>`).join("")}</div></details>`
    : "";

  panel.innerHTML = `${summaryHTML}${takeawaysHTML}${evidenceSectionHTML}${conflictsHTML}${footnotesHTML}${warningsFoldHTML}`;
  if (answer.cache) {
    const cacheNote = document.createElement("p");
    cacheNote.className = "meta-note";
    cacheNote.textContent = answer.cache.hit ? "当前状态下复用的调查结果" : "刚刚完成的调查";
    panel.appendChild(cacheNote);
  }
  if (answer.findings?.length) {
    const evListEl = typeof panel.querySelector === "function" ? panel.querySelector(".answer-evidence-list") : null;
    if (evListEl) {
      evListEl.innerHTML = answer.findings.slice(0, 3).map((item) => {
        const itemStatus = item.fact_id || item.id ? resolveFactStatus({ id: item.fact_id || item.id, status: item.status }) : item.status;
        const quoteText = item.status === "raw" ? cleanUiText(item.quote) : truncateUiText(item.quote, 140);
        return `<div class="detail-block"><div class="detail-label">${esc(claimLabel(item.claim_type))} ${renderStatusBadge(itemStatus)}</div>${rawFindingMeta(item)}${directionFindingMeta(item)}${item.member_id ? `<p class="meta-note">${esc(item.member_id)} · ${sourceTimeHTML(item)}</p>` : ""}${item.reviewed_by ? `<p class="reviewed-note">${esc(item.reviewed_by)} · ${esc(formatTime(item.reviewed_at))}</p>` : ""}<p class="detail-value">${esc(quoteText)}</p>${item.excerpt_truncated ? '<p class="meta-note">原文摘录，完整内容可从来源打开。</p>' : ""}${evidenceLinks(item.evidence_ids)}</div>`;
      }).join("");
    }
  }
  if (answer.reason_preview?.enabled) {
    const reasons = document.createElement("div"); reasons.className = "answer-conflicts";
    reasons.innerHTML = `<div class="detail-label">原因候选预览</div>${reasonPreviewHTML(answer.reason_preview)}`;
    panel.appendChild(reasons);
  }
  bindDynamicControls();
}

async function investigateProject(event) {
  event.preventDefault();
  if (!state.data) {
    const panel=document.getElementById('investigation-answer');
    panel.hidden=false;
    panel.innerHTML='<p class="empty">项目状态尚未加载完成，请加载成功后再提问。</p>';
    return;
  }
  const questionInput = document.getElementById("investigation-question");
  const question = questionInput.value.trim() || "为什么项目处于当前状态，下一步该做什么？";
  if (!question) return;
  const revision = state.revision;
  const requestId = ++state.investigationRequest;
  const panel = document.getElementById("investigation-answer");
  panel.hidden = false;
  panel.innerHTML = `<p class="empty">正在按证据链调查…</p>`;
  try {
    const reqBody = state.data?.project?.read_only && state.projectId ? { question, project_id: state.projectId } : { question };
    const answer = await apiFetch("/api/investigate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(reqBody)});
    if (revision !== state.revision || requestId !== state.investigationRequest) return;
    renderInvestigation(answer);
  } catch (error) {
    if (revision !== state.revision || requestId !== state.investigationRequest) return;
    panel.innerHTML = `<p class="empty">调查失败：${esc(error.message)}</p>`;
  }
}

function metric(value, text) { return `<div class="metric"><span class="metric-value">${esc(value)}</span><span class="metric-label">${esc(text)}</span></div>`; }

function buildTraceGroups(facts, relations, catalog, reviews, teamFacts) {
  const sources = new Map(catalog.map((item) => [item.id, item]));
  const team = new Map(teamFacts.map((fact) => [fact.id, fact]));
  const groups = new Map();
  const timestamp = (record) => hasSourceTime(record) ? new Date(record.observed_at).getTime() : Infinity;
  for (const fact of facts) {
    const subject = fact.subject_key || fact.id;
    if (!groups.has(subject)) groups.set(subject, {subject, facts: [], time: Infinity, latestTime: -Infinity});
    const related = relations.filter((relation) => relation.fact_id === fact.id);
    const ids = [...new Set([...(fact.evidence_ids || []), ...related.map((relation) => relation.evidence_id)])];
    const citations = ids.filter((id) => sources.has(id)).map((id) => ({source: sources.get(id),
      confirmed: related.some((relation) => relation.evidence_id === id && relation.status === 'confirmed')}));
    const accepted = reviews.filter((review) => review.action === 'accept_fact' && review.fact_id === fact.id);
    const markers = accepted.map((review, index) => ({...review, current: index === accepted.length - 1 &&
      team.get(fact.id)?.status === 'accepted' && sourceCurrent(team.get(fact.id))}));
    const group = groups.get(subject);
    const times = [timestamp(fact), ...citations.map(({source}) => timestamp(source))];
    group.time = Math.min(group.time, ...times);
    group.latestTime = Math.max(group.latestTime, ...times.filter(Number.isFinite), ...markers.map(timestamp).filter(Number.isFinite));
    group.facts.push({fact, citations, missing: ids.filter((id) => !sources.has(id)), reviews: markers});
  }
  for (const group of groups.values()) group.facts.sort((a, b) => timestamp(a.fact) - timestamp(b.fact));
  return [...groups.values()].sort((a, b) => a.time - b.time);
}

function renderTrace(facts, relations, catalog) {
  const scroller = document.getElementById('trace-scroller');
  const track = document.getElementById('trace-track');
  const key = JSON.stringify([state.lens, state.lens === 'personal' ? state.member : null]);
  state.tracePositions ||= {};
  if (state.traceViewKey && Number.isFinite(scroller.scrollLeft)) state.tracePositions[state.traceViewKey] = scroller.scrollLeft;
  const groups = buildTraceGroups(facts, relations, catalog, state.data.fact_reviews || [], state.data.team?.facts || []);
  state.traceLatestIndex = groups.reduce((latest, group, index) => Number.isFinite(group.latestTime) &&
    (latest < 0 || group.latestTime > groups[latest].latestTime) ? index : latest, -1);
  document.getElementById('trace-latest').disabled = state.traceLatestIndex < 0;
  document.getElementById('trace-count').textContent = `${groups.length} 主题 · ${facts.length} 条记录`;
  track.innerHTML = groups.length ? groups.map((group, index) => `<section class="trace-group" data-trace-index="${index}">
    <header class="trace-group-head"><span class="trace-sequence">${String(index + 1).padStart(2, '0')}</span><div><strong>${esc(label(group.facts[0].fact.kind))}${group.facts.length > 1 ? ` · ${group.facts.length} 条记录` : ''}</strong><small>${esc(group.subject)}</small></div></header>
    <div class="trace-branches">${group.facts.map(({fact, citations, missing, reviews}) => { const traceStatus = resolveFactStatus(fact); const shownCitations = state.layer === 'process' ? citations.slice(0, 2) : citations; const hiddenCitationCount = citations.length - shownCitations.length; return `<div class="trace-branch">
      <div class="trace-sources">${shownCitations.map(({source, confirmed}) => `<div class="trace-citation"><button class="trace-source" data-evidence-id="${esc(source.id)}"><span class="fact-kind">原始来源</span><span class="trace-copy">${esc(source.content_preview || source.id)}</span><span class="trace-meta">${esc(source.author || '作者未提供')} · ${esc(source.kind || '来源记录')}</span><span class="trace-meta">${sourceTimeHTML({...source, source_kind: source.kind})}</span></button><div class="trace-wire ${confirmed ? 'confirmed' : 'candidate'}"><span>${confirmed ? '支持关系已确认' : '引用关联待核对'}</span></div></div>`).join('')}
      ${hiddenCitationCount > 0 ? `<p class="trace-gap">过程层显示 ${shownCitations.length} 条来源，另有 ${hiddenCitationCount} 条可在原文层查看。</p>` : ''}
      ${missing.length || !citations.length ? `<p class="trace-gap">缺失来源 ${esc(missing.join(' · ') || '未提供来源引用')}</p>` : ''}</div>
      <button class="trace-fact ${traceStatus === 'conflicted' ? 'conflicted' : traceStatus === 'rejected' ? 'is-rejected' : ''}" data-fact-id="${esc(fact.id)}"><span class="fact-kind">${esc(label(fact.kind))}${renderStatusBadge(traceStatus)}</span><span class="trace-copy">${esc(fact.value)}</span><span class="trace-meta">${esc(fact.author || '作者未提供')} · ${esc(claimLabel(fact.claim_type))}</span><span class="trace-meta">${sourceTimeHTML(fact)}</span>${directionStateText(fact) ? `<span class="trace-meta">${esc(directionStateText(fact))}</span>` : ''}${sourceNote(fact) ? `<span class="trace-gap">${esc(sourceNote(fact))}</span>` : ''}</button>
      ${reviews.map((review) => `<div class="trace-review ${review.current ? 'current' : 'historical'}"${review.current ? ' data-current-team="true"' : ''}><strong>${review.current ? '当前团队确认' : '历史确认'}</strong><span>${esc(review.reviewer || 'owner')} · ${esc(formatTime(review.observed_at))}</span></div>`).join('')}
    </div>`}).join('')}</div></section>`).join('') : `<p class="empty">当前视图尚无结构化记录。来源材料仍可在下方查看，整理后才会形成历程节点。</p>`;
  if (Object.prototype.hasOwnProperty.call(state.tracePositions, key)) scroller.scrollLeft = state.tracePositions[key];
  else {
    const current = track.querySelector?.('[data-current-team]');
    const group = current?.closest?.('.trace-group');
    if (group) scroller.scrollLeft = group.offsetLeft;
    else jumpTrace(true);
  }
  state.traceViewKey = key;
}

function jumpTrace(latest) {
  const scroller = document.getElementById('trace-scroller');
  const group = latest && state.traceLatestIndex >= 0 ? document.getElementById('trace-track').querySelector?.(`[data-trace-index="${state.traceLatestIndex}"]`) : null;
  scroller.scrollLeft = Math.min(group?.offsetLeft || 0, Math.max(0, (scroller.scrollWidth || 0) - (scroller.clientWidth || 0)));
}

function renderSpeculativeBadge(item) {
  if (!item || !item.speculative_verified) return "";
  const ids = Array.isArray(item.evidence_ids) ? item.evidence_ids.filter(Boolean) : [];
  if (ids.length > 0) {
    return `<span class="speculative-verified-badge" role="button" tabindex="0" data-evidence-id="${esc(ids[0])}" title="关联测试记录退出码为 0，点击查看对应证据（需独立核对适用范围）">✦ 关联校验通过</span>`;
  }
  return `<span class="speculative-verified-badge unlinked" title="仅记录校验标记，当前缺少可直接核对的测试证据 ID">✦ 校验标记（缺证据）</span>`;
}

function renderSpeculativeDetail(fact) {
  if (!fact || !fact.speculative_verified) return "";
  const ids = Array.isArray(fact.evidence_ids) ? fact.evidence_ids.filter(Boolean) : [];
  const pills = ids.length ? `<div class="card-pill-row">${renderEvPills(ids)}</div>` : `<p class="empty">当前缺少可直接跳转的测试证据 ID（证据缺口）。</p>`;
  const note = ids.length ? "关联测试记录退出码为 0（仅证明该次执行记录通过，请点击上方证据核对覆盖范围）" : "存在投机校验标记，但未附带可溯源测试证据 ID";
  return `<div class="detail-block"><div class="detail-label">校验与证据关联</div><div class="detail-value">${esc(note)}</div>${pills}</div>`;
}

function factCard(fact, relations) {
  const related = relations.filter((relation) => relation.fact_id === fact.id);
  const confirmed = related.some((relation) => relation.status === "confirmed");
  const effectiveStatus = resolveFactStatus(fact);
  const superseder = findSupersedingAcceptedFact(fact);
  const currentStatus = superseder ? "superseded"
    : effectiveStatus === "accepted" ? "accepted"
      : effectiveStatus === "conflicted" ? "conflicted"
        : effectiveStatus === "rejected" ? "rejected"
          : effectiveStatus === "needs_evidence" ? "needs_evidence"
            : confirmed ? "relation_confirmed" : "candidate";
  const author = fact.author ? ` · ${esc(fact.author)}` : "";
  const verifiedBadge = renderSpeculativeBadge(fact);
  const conflictHint = superseder
    ? `<div class="card-conflict-digest is-superseded">已被新定案「${esc(truncateUiText(cleanUiText(superseder.short_title || superseder.value), 32))}」接替</div>`
    : renderCardConflictHintHTML(fact, effectiveWorkMode() === "solo");
  const badgeHtml = superseder
    ? renderStatusBadge("superseded", "已由新定案接替")
    : renderStatusBadge(currentStatus);
  return `<div class="fact-card" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><div class="fact-main"><div class="fact-kind">${esc(label(fact.kind))}${verifiedBadge}</div><div class="fact-value">${esc(fact.value)}</div><div class="fact-meta">${esc(claimLabel(fact.claim_type))}${author} · ${related.length} 条关联</div><div class="fact-meta">${sourceTimeHTML(fact)}${effectiveStatus === 'accepted' || superseder ? '' : ' · 当前有效性待核对'}</div>${conflictHint}${directionStateText(fact) ? `<div class="fact-meta">${esc(directionStateText(fact))}</div>` : ''}${sourceNote(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 原记录保留</p>` : ""}</div>${badgeHtml}</div>`;
}

function renderTeamHistory() {
  const isSolo = effectiveWorkMode() === "solo";
  const surface = document.getElementById("team-truth-history");
  const conflicts = state.data.team?.conflicts || [];
  const history = state.data.review_history || [];
  surface.hidden = state.lens !== "team" || (!conflicts.length && !history.length);
  document.getElementById("conflict-count").textContent = conflicts.length;
  const teamFacts = state.data.team?.facts || [];
  document.getElementById("conflict-list").innerHTML = conflicts.length ? conflicts.map((conflict) => {
    const rec = conflict.speculative_recommendation;
    const sides = conflict.sides || [];
    const recSide = rec?.recommended_fact_id ? sides.find((s) => s.fact_id === rec.recommended_fact_id) : null;
    const recForBadge = rec && (!Array.isArray(rec.evidence_ids) || !rec.evidence_ids.length) && recSide?.evidence_ids?.length
      ? { ...rec, evidence_ids: recSide.evidence_ids }
      : rec;
    const recVerified = renderSpeculativeBadge(recForBadge);
    const recHTML = rec ? `<div class="conflict-speculative-rec"><strong>系统启发式建议:</strong> ${esc(rec.hypothetical_resolution || rec.recommended_value)}${recVerified} <span class="rec-meta">(${esc(rec.confidence)} 置信度 · ${esc(rec.score ?? "")}分，${isSolo ? "以你的最终定案为准" : "最终以负责人裁决为准"})</span></div>` : "";
    const sideCards = sides.map((side, idx) => {
      const recBadge = side.speculative_status === "recommended" ? renderStatusBadge("recommended", "系统推荐") : "";
      const verifiedBadge = renderSpeculativeBadge(side);
      const matchedFact = teamFacts.find((f) => f.id === side.fact_id || (f.subject_key === conflict.subject_key && f.value === side.value && f.author === side.author));
      const sideStatus = resolveFactStatus(matchedFact || (side.fact_id ? { id: side.fact_id, status: side.status } : side));
      const inlineBtn = matchedFact && sideStatus !== "accepted" && canInlineAcceptFact(matchedFact)
        ? `<div class="conflict-pane-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(matchedFact.id)}" title="${isSolo ? "采纳此方思路定案" : "采纳此方立场为团队事实"}">✓ ${isSolo ? "定案" : "采纳"}立场 ${String.fromCharCode(65 + idx)}</button></div>`
        : "";
      const sideTag = `<span class="conflict-stance-label">立场 ${String.fromCharCode(65 + idx)}</span>`;
      const divider = idx === 0 && sides.length > 1 ? `<div class="conflict-vs-divider" aria-hidden="true"><span>VS</span></div>` : "";
      const paneClass = sideStatus === "accepted" ? "is-accepted" : sideStatus === "rejected" ? "is-rejected" : sideStatus === "needs_evidence" ? "is-needs-evidence" : "is-conflicted";
      return `<article class="conflict-side-pane ${paneClass}"><div class="conflict-pane-head">${sideTag}${renderStatusBadge(sideStatus)}${recBadge}${verifiedBadge}</div><div class="conflict-pane-value">${esc(side.value)}</div><div class="conflict-meta">${esc(side.author || "unknown")} · ${sourceTimeHTML(side)}</div><div class="card-pill-row">${renderEvPills(side.evidence_ids)}</div>${inlineBtn}</article>${divider}`;
    }).join("");
    return `<div class="conflict-card"><div class="conflict-card-head"><span class="conflict-key">${esc(conflict.subject_key)}</span><span class="conflict-count-tag">${sides.length} 立场对峙 · 证据同时保留</span></div>${recHTML}<div class="conflict-vs-grid">${sideCards}</div></div>`;
  }).join("") : `<p class="empty">当前没有前后分歧记录。</p>`;
  const actionLabels = {
    accept_fact: isSolo ? "定案为项目基准" : "确认团队事实",
    confirm_relation: isSolo ? "定案证据关联" : "确认证据关系",
    confirm_abandoned: "确认放弃方向",
    confirm_deferred: "确认暂缓方向",
    restore_direction: "恢复方向",
    reject_fact: isSolo ? "暂不采纳" : "拒绝候选",
    request_evidence: "标记待补证据",
  };
  document.getElementById("history-list").innerHTML = history.length ? `<div class="history-label">${isSolo ? "定案记录" : "审核历史"}</div>${history.map((entry) => `<div class="history-item"><strong>${esc(actionLabels[entry.action] || entry.action)}</strong><span>${esc(entry.value || entry.fact_id || entry.relation_id || "")} · ${esc(entry.reviewer || "owner")} · ${entry.evidence_ids?.length || 0} 条证据 · ${esc(formatTime(entry.observed_at))}${entry.evidence_request_id ? " · 已处理补证请求" : ""}${entry.resolved_relation_ids?.length ? ` · ${entry.resolved_relation_ids.length} 条关系已确认` : ""}${entry.note ? ` · ${esc(entry.note)}` : ""}</span></div>`).join("")}` : "";
}

function renderEvPills(ids) {
  const valid = (ids || []).filter(Boolean).slice(0, 4);
  if (!valid.length) return "";
  return valid.map((id, idx) => `<span class="ev-pill" role="button" tabindex="0" data-evidence-id="${esc(id)}" title="悬停预览原文，点击查看出处 (${esc(id)})">依据 · ${idx + 1}</span>`).join("");
}

function renderTimelineAndThinkingLine(view, facts) {
  const chaptersEl = document.getElementById("chapter-timeline");
  const canvasEl = document.getElementById("thinking-line-canvas");
  const revBadge = document.getElementById("thinking-reversal-badge");
  const clearBtn = document.getElementById("thinking-clear-filter");
  if (!chaptersEl || !canvasEl) return;

  const chapters = view.timeline_chapters || [];
  const thinking = view.thinking_line || { root: { label: "当前核心目标待确立", status: "empty", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] };

  if (clearBtn) {
    clearBtn.hidden = !state.activeChapterId;
  }
  const reversals = thinking.reversals || [];
  if (revBadge) {
    revBadge.hidden = reversals.length === 0;
    revBadge.textContent = `${reversals.length} 处来源换版需复核`;
  }

  chaptersEl.innerHTML = chapters.length ? chapters.map((ch, idx) => {
    const isSelected = state.activeChapterId === ch.chapter_id;
    const statusClass = safeToken(ch.status, "pending");
    const arrow = idx < chapters.length - 1 ? `<span class="chapter-arrow ${statusClass}" aria-hidden="true">→</span>` : "";
    return `<button type="button" class="chapter-node ${statusClass}${isSelected ? " selected" : ""}" data-chapter-id="${esc(ch.chapter_id)}">
      <div class="chapter-top"><span class="chapter-seq">${esc(ch.sequence)}</span><span class="chapter-title">${esc(ch.title)}</span><span class="chapter-badge">${esc(ch.count ?? 0)}</span></div>
      <div class="chapter-sub">${esc(ch.subtitle || "")}</div>
    </button>${arrow}`;
  }).join("") : `<p class="empty">暂无阶段时间轴数据。</p>`;

  const root = thinking.root || { label: "核心目标待定锚", status: "empty", evidence_ids: [] };
  const rootStatus = root.fact_id ? resolveFactStatus({ id: root.fact_id, status: root.status }) : (root.status || "empty");
  const branches = thinking.branches || [];
  const codeNodes = thinking.code_nodes || [];

  const isSolo = effectiveWorkMode() === "solo";
  const branchHTML = branches.length ? branches.map((b) => {
    const branchStatus = b.fact_id ? resolveFactStatus({ id: b.fact_id, status: b.status }) : (b.status || "proposed");
    const isDropped = b.state === "abandoned" || b.state === "deferred";
    const icon = b.state === "abandoned" ? "✕" : b.state === "deferred" ? "⏸" : branchStatus === "accepted" ? "✓" : "◆";
    const freshCls = state.freshFactIds?.has?.(b.fact_id) ? " is-fresh-node" : "";
    const stateClass = (isDropped ? "branch-dropped" : branchStatus === "accepted" ? "branch-accepted" : "branch-proposed") + freshCls;
    const kindText = b.kind === "assumption" ? "未验证前提" : "决策";
    const tagText = b.state === "abandoned" ? "已舍弃" : b.state === "deferred" ? "已暂缓" : branchStatus === "accepted" ? (isSolo ? "已定案基准" : "团队共识") : (isSolo ? "待定思路" : "候选状态");
    const canQuickAccept = Boolean(b.fact_id && !state.data?.project?.read_only && branchStatus !== "accepted" && !isDropped && (isSolo || state.lens === "team"));
    const quickAction = canQuickAccept
      ? `<div class="thinking-branch-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(b.fact_id)}">${isSolo ? "✓ 定案" : "✓ 确认"}</button></div>`
      : "";
    const childrenHTML = (b.children || []).length
      ? `<div class="thinking-children">${b.children.map((child) => {
          const done = child.task_state === "completed";
          const leafFresh = state.freshFactIds?.has?.(child.fact_id) ? " is-fresh-node" : "";
          return `<div class="thinking-leaf ${done ? "leaf-done" : ""}${leafFresh}" ${child.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(child.fact_id)}"` : ""} title="${esc(child.full_label || child.label)}">
            <span class="leaf-check">${done ? "☑" : "☐"}</span>
            <span class="leaf-label">${esc(child.label)}</span>
            ${renderEvPills(child.evidence_ids)}
          </div>`;
        }).join("")}</div>`
      : `<div class="thinking-children thinking-children-empty"><span class="thinking-leaf-hint">${esc(codeNodes.length ? "关联下方代码模块 · 点击节点溯源" : "尚无拆分子任务")}</span></div>`;
    return `<div class="thinking-branch-row ${stateClass}">
      <div class="thinking-branch-card">
        <div class="thinking-branch-node" ${b.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(b.fact_id)}"` : ""} title="${esc(b.full_label || b.label)}">
          <span class="branch-icon">${icon}</span>
          <span class="branch-kind-chip">${kindText}</span>
          <span class="branch-tag ${stateClass}">${tagText}</span>
          <strong class="branch-label">${esc(b.label)}</strong>
          ${renderEvPills(b.evidence_ids)}
        </div>
        ${quickAction}
      </div>
      ${childrenHTML}
    </div>`;
  }).join("") : `<div class="thinking-branch-row branch-proposed"><div class="thinking-branch-card"><div class="thinking-branch-node"><span class="branch-icon">◆</span><span class="branch-tag">等待提炼</span><strong class="branch-label">写一条随手记或同步对话后，这里将实时长出分支</strong></div></div></div>`;

  const codeFooter = codeNodes.length ? `<div class="thinking-code-strip"><span class="code-strip-label">⧉ 关联代码：</span>${codeNodes.map((n) => `<span class="code-node-pill ${n.direct ? "direct" : ""}" title="${esc(n.source_ref || "")}">${esc(n.label)}</span>`).join("")}</div>` : "";
  const archive = thinking.historical_archive || {};
  const archiveItems = Array.isArray(archive.items) ? archive.items : [];
  const archiveHTML = archiveItems.length
    ? `<details class="historical-archive-capsule">
        <summary><span>▤ ${esc(archive.label || `历史文档参考（${archiveItems.length} 条）`)}</span><span class="archive-toggle-hint">默认折叠 · 点击展开核对</span></summary>
        <div class="historical-archive-list">${archiveItems.map((item) => `<button type="button" class="historical-archive-item" ${item.fact_id ? `data-fact-id="${esc(item.fact_id)}"` : ""} title="${esc(item.full_label || item.label)}"><strong>${esc(item.label)}</strong><small>${esc(item.source_ref || "项目文档")}</small></button>`).join("")}</div>
      </details>`
    : "";
  const rootStatusTag = rootStatus === "accepted" ? (isSolo ? "已定案目标" : "已确认目标") : rootStatus === "empty" ? "等待确立" : (isSolo ? "待定核心目标" : "候选核心目标");
  const rootFresh = state.freshFactIds?.has?.(root.fact_id) ? " is-fresh-node" : "";

  canvasEl.innerHTML = `<div class="thinking-tree mindmap-layout">
    <div class="thinking-root ${rootStatus === "accepted" ? "accepted" : "proposed"}${rootFresh}" ${root.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(root.fact_id)}"` : ""} title="${esc(root.full_label || root.label)}">
      <span class="thinking-root-kicker">核心目标锚点 · ${rootStatusTag}</span>
      <strong class="thinking-root-title">${esc(root.label)}</strong>
      <div class="card-pill-row">${renderEvPills(root.evidence_ids)}</div>
    </div>
    <div class="thinking-connector" aria-hidden="true"></div>
    <div class="thinking-branches">${branchHTML}</div>
  </div>${codeFooter}${archiveHTML}`;
}

function buildPopoverHTML(evidenceId, detail = null, fetchError = "") {
  const catalogEntry = (state.data?.evidence || []).find((item) => item.id === evidenceId) || {};
  const author = detail?.author || catalogEntry.author || detail?.metadata?.member_id || "source";
  const observedAt = detail?.observed_at || catalogEntry.observed_at;
  const kind = detail?.kind || catalogEntry.kind || "record";
  const sourceRef = detail?.metadata?.source_ref || catalogEntry.source_ref || "";
  const displayRef = humanSourceRef(sourceRef, kind);
  const kindLabel = evidenceKindLabel(kind, sourceRef);
  const rawQuote = detail?.content || catalogEntry.content_preview || catalogEntry.command_preview || (fetchError ? "原文摘录暂不可用，请点击下方按钮核对详情" : "正在加载原文摘录…");
  const cleanedQuote = String(rawQuote).replace(/@\[Quote\]\s*/g, "").replace(/^>+\s*/gm, "").trim();
  const quote = cleanedQuote.length > 320 ? cleanedQuote.slice(0, 318) + "…" : cleanedQuote;
  const errorNote = fetchError ? `<p class="meta-note">原文拉取受限（${esc(fetchError)}）</p>` : "";

  const linkedFacts = [...(state.data?.team?.facts || []), ...(state.data?.personal?.[state.member]?.facts || [])].filter((f) => (f.evidence_ids || []).includes(evidenceId));
  const isSuperseded = linkedFacts.some((f) => f.source_state?.status === "superseded" || Boolean(findSupersedingAcceptedFact(f)));
  const isUnavailable = linkedFacts.some((f) => f.source_state?.status === "unavailable");
  const freshnessStatus = isUnavailable ? "unavailable" : isSuperseded ? "superseded" : "current";
  const freshnessText = isUnavailable ? "● 暂不可用" : isSuperseded ? "● 已有新定案接替" : "● 当前有效";

  let linkedHintHTML = "";
  const primaryLinked = linkedFacts.find((f) => findSupersedingAcceptedFact(f)) || linkedFacts.find((f) => resolveFactStatus(f) === "conflicted");
  if (primaryLinked) {
    const sup = findSupersedingAcceptedFact(primaryLinked);
    if (sup) {
      linkedHintHTML = `<p class="meta-note">新旧接替：已被「${esc(truncateUiText(cleanUiText(sup.short_title || sup.value), 30))}」接替</p>`;
    } else {
      const other = findSubjectPeers(primaryLinked)[0];
      if (other) {
        linkedHintHTML = `<p class="meta-note">⚡ 分歧点：与「${esc(truncateUiText(cleanUiText(other.short_title || other.value), 30))}」不一致</p>`;
      }
    }
  }

  return `<div class="popover-head">
    <div class="popover-speaker">
      <span class="speaker-avatar" aria-hidden="true">🔊</span>
      <div>
        <strong class="speaker-name">● ${esc(author)}</strong>
        <span class="speaker-time">${esc(formatTime(observedAt))}${displayRef ? ` · ${esc(displayRef)}` : ""}</span>
      </div>
    </div>
    ${renderStatusBadge(freshnessStatus, freshnessText)}
  </div>
  <div class="popover-quote-box">
    <p class="popover-quote">${esc(quote)}</p>
    ${linkedHintHTML}
    ${errorNote}
  </div>
  <div class="popover-foot">
    <span class="popover-id">证据编号: ${esc(evidenceId)} · ${esc(kindLabel)}</span>
    <button type="button" class="popover-jump" data-popover-open="${esc(evidenceId)}">查看完整原文 ↗</button>
  </div>`;
}

function bindPopoverJump(popover) {
  if (!popover || typeof popover.querySelectorAll !== "function") return;
  popover.querySelectorAll("[data-popover-open]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const returnTarget = state.popoverAnchor || btn;
      hideCitationPopover();
      openEvidence(btn.dataset.popoverOpen, returnTarget);
    });
  });
}

function positionCitationPopover(popover, targetEl) {
  if (!popover?.style || typeof targetEl?.getBoundingClientRect !== "function" || typeof window === "undefined") return;
  const rect = targetEl.getBoundingClientRect();
  const vw = Number(window.innerWidth) || 1024;
  const vh = Number(window.innerHeight) || 768;
  const popW = Math.min(Number(popover.offsetWidth) || 378, Math.max(120, vw - 24));
  const popH = Math.min(Number(popover.offsetHeight) || 220, Math.max(80, vh - 24));
  const preferAbove = rect.bottom + 8 + popH > vh - 12 && rect.top - popH - 8 >= 12;
  const rawTop = preferAbove ? rect.top - popH - 8 : rect.bottom + 8;
  const top = Math.max(12, Math.min(vh - popH - 12, rawTop));
  const left = Math.max(12, Math.min(vw - popW - 12, rect.left));
  popover.style.top = `${top}px`;
  popover.style.left = `${left}px`;
}

function prefetchEvidence(evidenceId) {
  if (!evidenceId || typeof fetch !== "function" || state.evidenceCache[evidenceId] || state.evidenceCache[`_loading_${evidenceId}`] || state.evidenceCache[`_error_${evidenceId}`]) return;
  const reqProjectKey = state.projectId || "";
  state.evidenceCache[`_loading_${evidenceId}`] = true;
  apiFetch(`/api/evidence?id=${encodeURIComponent(evidenceId)}${projectQuerySuffix()}`, { timeoutMs: 5000, background: true })
    .then((detail) => {
      delete state.evidenceCache[`_loading_${evidenceId}`];
      if ((state.projectId || "") !== reqProjectKey) return;
      if (detail) {
        state.evidenceCache[evidenceId] = detail;
        const popover = document.getElementById("citation-popover");
        if (popover && !popover.hidden && state.popoverCurrentId === evidenceId) {
          popover.innerHTML = buildPopoverHTML(evidenceId, detail);
          bindPopoverJump(popover);
          positionCitationPopover(popover, state.popoverAnchor);
        }
      }
    })
    .catch((err) => {
      delete state.evidenceCache[`_loading_${evidenceId}`];
      if ((state.projectId || "") === reqProjectKey) {
        state.evidenceCache[`_error_${evidenceId}`] = err?.message || "prefetch error";
      }
    });
}

function handleProximityPrefetch(e) {
  if (!e || typeof document === "undefined" || typeof document.querySelectorAll !== "function") return;
  const clientX = e.clientX;
  const clientY = e.clientY;
  if (typeof clientX !== "number" || typeof clientY !== "number") return;
  const buttons = document.querySelectorAll("[data-evidence-id]");
  for (let i = 0; i < buttons.length; i++) {
    const btn = buttons[i];
    const evidenceId = btn?.dataset?.evidenceId;
    if (!evidenceId || typeof btn.getBoundingClientRect !== "function") continue;
    const rect = btn.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) continue;
    const margin = 10;
    if (
      clientX >= rect.left - margin &&
      clientX <= rect.right + margin &&
      clientY >= rect.top - margin &&
      clientY <= rect.bottom + margin
    ) {
      prefetchEvidence(evidenceId);
    }
  }
}

async function showCitationPopover(targetEl, evidenceId) {
  if (!evidenceId) return;
  if (state.popoverTimer) {
    clearTimeout(state.popoverTimer);
    state.popoverTimer = null;
  }
  const popover = document.getElementById("citation-popover");
  if (!popover) return;
  const reqProjectKey = state.projectId || "";
  state.popoverAnchor = targetEl;
  state.popoverCurrentId = evidenceId;
  if (popover.dataset) {
    delete popover.dataset.fetchError;
    popover.dataset.currentEvidenceId = evidenceId;
  }
  popover.innerHTML = buildPopoverHTML(evidenceId, state.evidenceCache[evidenceId] || null);
  popover.hidden = false;
  popover.setAttribute("aria-hidden", "false");
  positionCitationPopover(popover, targetEl);
  bindPopoverJump(popover);

  if (!state.evidenceCache[evidenceId]) {
    try {
      const detail = await apiFetch(`/api/evidence?id=${encodeURIComponent(evidenceId)}${projectQuerySuffix()}`, { timeoutMs: 5000, background: true });
      if ((state.projectId || "") !== reqProjectKey) return;
      if (targetEl?.isConnected === false) { hideCitationPopover(); return; }
      if (detail) {
        state.evidenceCache[evidenceId] = detail;
        if (!popover.hidden && state.popoverCurrentId === evidenceId) {
          popover.innerHTML = buildPopoverHTML(evidenceId, detail);
          bindPopoverJump(popover);
          positionCitationPopover(popover, state.popoverAnchor);
        }
      }
    } catch (_err) {
      const errMsg = _err?.message || "unavailable";
      if (popover.dataset) popover.dataset.fetchError = errMsg;
      if ((state.projectId || "") !== reqProjectKey) return;
      if (targetEl?.isConnected === false) { hideCitationPopover(); return; }
      if (!popover.hidden && state.popoverCurrentId === evidenceId) {
        popover.innerHTML = buildPopoverHTML(evidenceId, null, errMsg);
        bindPopoverJump(popover);
        positionCitationPopover(popover, state.popoverAnchor);
      }
    }
  }
}

function scheduleHidePopover() {
  if (state.popoverTimer) clearTimeout(state.popoverTimer);
  state.popoverTimer = setTimeout(() => {
    hideCitationPopover();
  }, 180);
}

function hideCitationPopover() {
  state.popoverCurrentId = null;
  const popover = document.getElementById("citation-popover");
  if (!popover) return;
  popover.hidden = true;
  popover.setAttribute("aria-hidden", "true");
}

function evidenceCard(item) {
  const links = (item.candidate_fact_ids?.length || 0) + (item.confirmed_fact_ids?.length || 0);
  const sourceKind = evidenceKindLabel(item.kind, item.source_ref);
  const displaySource = humanSourceRef(item.source_ref, item.kind) || item.author || "";
  const commandNote = item.command_preview ? `<span class="evidence-command">${esc(item.command_preview)}</span><span class="evidence-meta">${esc(commandOriginLabel(item.command_origin))} · 退出码 ${esc(Number.isInteger(item.exit_code) ? item.exit_code : '未知')}</span>` : '';
  return `<button class="evidence-item" data-evidence-id="${esc(item.id)}"><span class="evidence-dot ${safeToken(item.classification, "other")}"></span><span><span class="evidence-title">${esc(item.content_preview || item.id)}</span>${commandNote}<span class="evidence-meta">${esc(sourceKind)} · ${esc(formatTime(item.observed_at))} · ${esc(evidenceClassLabel(item.classification))} · ${esc(displaySource)}</span></span><span class="evidence-links">${links ? `${links} 条关联` : "原始"}</span></button>`;
}

function renderSessionPresence() {
  const container = document.getElementById("session-presence-bar");
  if (!container) return;
  const isSolo = effectiveWorkMode() === "solo";
  container.hidden = isSolo;
  if (isSolo) {
    container.innerHTML = "";
    return;
  }
  const presence = state.data?.session_presence;
  if (!presence) {
    container.innerHTML = "";
    return;
  }
  const isTeamActive = state.lens === "team";
  const teamPending = Number(presence.team?.pending_count) || 0;
  const teamAccepted = Number(presence.team?.accepted_count) || 0;

  const teamBadgeClass = teamAccepted > 0 ? "accepted-count" : "zero-count";
  const teamPill = `<button type="button" class="presence-pill ${isTeamActive ? 'active' : ''}" data-target-lens="team" title="切换到团队共识视图"><span class="presence-name">团队共识</span><span class="presence-badge ${teamBadgeClass}" title="${teamAccepted} 条已确认事实">${teamAccepted}</span>${teamPending > 0 ? `<span class="presence-badge pending-count" title="${teamPending} 条待核对候选">${teamPending} 待审核</span>` : ''}</button>`;

  const memberPills = (presence.members || []).map((m) => {
    const isMemberActive = state.lens === "personal" && state.member === m.member_id;
    const pulseClass = m.is_agent_session ? "agent-pulse" : "agent-pulse doc";
    const mPending = Number(m.pending_count) || 0;
    const statusTag = mPending > 0
      ? `<span class="presence-badge pending-count" title="${mPending} 条待审核候选">${mPending}</span>`
      : `<span class="presence-badge zero-count" title="无待审候选">✓</span>`;
    return `<button type="button" class="presence-pill ${isMemberActive ? 'active' : ''}" data-target-lens="personal" data-target-member="${esc(m.member_id)}" title="切换到 ${esc(m.label)} 视图"><span class="${pulseClass}"></span><span class="presence-name">${esc(m.label)}</span>${statusTag}</button>`;
  }).join("");

  container.innerHTML = teamPill + memberPills;
}

function wireEvidenceTargets(root) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root.querySelectorAll("[data-evidence-id]").forEach((button) => {
    button.onclick = (event) => {
      event?.stopPropagation?.();
      hideCitationPopover();
      openEvidence(button.dataset.evidenceId);
    };
    button.onkeydown = (event) => {
      if (event?.key === "Enter" || event?.key === " ") {
        event.preventDefault?.();
        event.stopPropagation?.();
        hideCitationPopover();
        openEvidence(button.dataset.evidenceId);
      }
    };
    button.onpointerenter = () => prefetchEvidence(button.dataset.evidenceId);
    button.onmouseenter = () => showCitationPopover(button, button.dataset.evidenceId);
    button.onmouseleave = scheduleHidePopover;
    button.onfocus = () => showCitationPopover(button, button.dataset.evidenceId);
    button.onblur = scheduleHidePopover;
  });
}

function openHandoffBrief() {
  const modal = document.getElementById("handoff-modal");
  const content = document.getElementById("handoff-content");
  if (!modal || !content) return;
  const isSolo = effectiveWorkMode() === "solo";
  const modalTitle = document.getElementById("handoff-modal-title");
  if (modalTitle) modalTitle.textContent = isSolo ? "个人上下文续写快照" : "项目交接简报";
  const modalSubtitle = document.getElementById("handoff-modal-subtitle");
  if (modalSubtitle) {
    modalSubtitle.textContent = isSolo
      ? "汇总当前已定案项目基准、待定思路与下一步待办，方便跨会话续写"
      : "汇集当前已确认团队共识、待审候选事实与下一步行动清单";
  }
  if (modal.hidden && typeof document.activeElement === "object" && document.activeElement) {
    state.lastModalTrigger = document.activeElement;
    state.lastTriggerElement = document.activeElement;
  }
  const brief = state.data?.handoff_brief;
  if (!brief) {
    content.innerHTML = `<p class="empty">${isSolo ? "暂无可用的上下文快照数据。" : "暂无可用的交接简报数据。"}</p>`;
  } else {
    const goal = brief.focus_goal || {};
    const decisions = brief.accepted_decisions || [];
    const rawCandidates = brief.pending_candidates || [];
    const todos = brief.open_todos || [];
    const codeNodes = brief.code_nodes || [];

    const briefStatus = (item) => resolveFactStatus({ id: item?.fact_id || item?.id, status: item?.status });
    const todoIdSet = new Set(todos.map((t) => t.fact_id || t.id).filter(Boolean));
    const todoValueSet = new Set(todos.map((t) => String(t.value || "").trim().toLowerCase()));
    const candidates = rawCandidates.filter((c) => {
      const cid = c.fact_id || c.id;
      if (cid) return !todoIdSet.has(cid);
      if (c.kind && c.kind !== "task") return true;
      return !todoValueSet.has(String(c.value || "").trim().toLowerCase());
    });
    const goalStatusBadge = goal.value ? renderStatusBadge(briefStatus(goal)) : "";

    const decHTML = decisions.length
      ? `<ul class="brief-item-list">${decisions.map(d => `<li class="brief-item"><strong>${esc(cleanUiText(d.clean_value || d.value))}</strong><span class="card-pill-row">${renderStatusBadge("accepted")}${renderEvPills(d.evidence_ids)}</span></li>`).join("")}</ul>`
      : `<p class="empty">${isSolo ? "暂无已定案项目基准。" : "暂无已确认共识事实。"}</p>`;

    const candHTML = candidates.length
      ? `<ul class="brief-item-list">${candidates.map(c => `<li class="brief-item"><strong>${esc(cleanUiText(c.value))} <small>(${esc(c.author)})</small></strong><span class="card-pill-row">${renderStatusBadge(briefStatus(c))}${renderEvPills(c.evidence_ids)}</span></li>`).join("")}</ul>`
      : `<p class="empty">${isSolo ? "当前无待拍板思路（待办已单列下方）。" : "当前无未决会话候选（已与行动清单合并）。"}</p>`;

    const todoHTML = todos.length
      ? `<ul class="brief-item-list">${todos.map(t => {
          const isDone = t.task_state === 'completed';
          return `<li class="brief-item"><strong>${isDone ? '☑' : '☐'} ${esc(cleanUiText(t.value))} <small>(${esc(t.author)})</small></strong><span class="card-pill-row">${renderStatusBadge(briefStatus(t))}${renderEvPills(t.evidence_ids)}</span></li>`;
        }).join("")}</ul>`
      : `<p class="empty">暂无待办任务。</p>`;

    const codeHTML = codeNodes.length
      ? `<div class="brief-code-grid">${codeNodes.map(n => `<span class="code-node-pill ${n.direct ? 'direct' : ''}">${esc(n.label)}</span>`).join("")}</div>`
      : `<p class="empty">无直接关联代码模块。</p>`;

    const nextBrief = brief.next_consensus;
    const nextBriefLine = nextBrief?.value
      ? `<p class="meta-note">当前下一步：${esc(cleanUiText(nextBrief.clean_value || nextBrief.value))}</p>`
      : "";

    content.innerHTML = `
      <section class="brief-section brief-focus-box">
        <span class="eyebrow brief-goal-eyebrow">当前核心目标</span> ${goalStatusBadge}
        <strong>${esc(cleanUiText(goal.clean_value || goal.value) || "暂无核心目标")}</strong>
        ${nextBriefLine}
        <div class="card-pill-row">${renderEvPills(goal.evidence_ids)}</div>
      </section>
      <section class="brief-section">
        <div class="brief-section-title"><span>1. ${isSolo ? "已定案项目基准" : "已确认团队共识"}</span><span class="count">${decisions.length} 条</span></div>
        ${decHTML}
      </section>
      <section class="brief-section">
        <div class="brief-section-title"><span>2. ${isSolo ? "待定思路与未拍板项" : "待确认会话候选"}</span><span class="count">${candidates.length} 条</span></div>
        ${candHTML}
      </section>
      <section class="brief-section">
        <div class="brief-section-title"><span>3. 下一步行动清单</span><span class="count">${todos.length} 项</span></div>
        ${todoHTML}
      </section>
      <section class="brief-section">
        <div class="brief-section-title"><span>4. 关联代码架构模块</span><span class="count">${codeNodes.length} 个节点</span></div>
        ${codeHTML}
      </section>
    `;
  }
  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
  document.getElementById("scrim").hidden = false;
  wireEvidenceTargets(content);
  const closeBtn = document.getElementById("handoff-close-btn");
  if (closeBtn && typeof closeBtn.focus === "function") closeBtn.focus();
}

function closeHandoffBrief() {
  const modal = document.getElementById("handoff-modal");
  if (!modal) return;
  const popover = document.getElementById("citation-popover");
  if (popover && !popover.hidden) hideCitationPopover();
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
  const drawer = document.getElementById("evidence-drawer");
  if (!drawer || drawer.hidden) document.getElementById("scrim").hidden = true;
  const target = state.lastModalTrigger;
  state.lastModalTrigger = null;
  if (target && typeof target.focus === "function") {
    target.focus();
  }
}

async function copyTextToClipboard(text) {
  if (!text) return false;
  let copied = false;
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (_err) {
      copied = false;
    }
  }
  if (!copied && typeof document !== "undefined" && document.body && typeof document.execCommand === "function") {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    try {
      document.body.appendChild?.(textarea);
      textarea.select?.();
      copied = Boolean(document.execCommand("copy"));
    } catch (_execErr) {
      copied = false;
    } finally {
      document.body.removeChild?.(textarea);
    }
  }
  return copied;
}

async function copyHandoffMarkdown() {
  const brief = state.data?.handoff_brief;
  const btn = document.getElementById("handoff-copy-btn");
  if (!brief?.markdown || !btn) return;
  state.origButtonLabels ||= Object.create(null);
  if (!state.origButtonLabels["handoff-copy-btn"]) {
    state.origButtonLabels["handoff-copy-btn"] = btn.textContent || "复制简报";
  }
  const origText = state.origButtonLabels["handoff-copy-btn"];
  const copied = await copyTextToClipboard(brief.markdown);
  if (state.copyRestoreTimer) clearTimeout(state.copyRestoreTimer);
  if (copied) {
    btn.textContent = "已复制到剪贴板";
    btn.classList?.add("is-copied");
  } else {
    btn.textContent = "复制不可用，请手动复制";
    btn.classList?.remove("is-copied");
  }
  state.copyRestoreTimer = setTimeout(() => {
    state.copyRestoreTimer = null;
    btn.textContent = origText;
    btn.classList?.remove("is-copied");
  }, 2000);
}

async function exportCognitiveAsset(format, btnId, successLabel) {
  const btn = document.getElementById(btnId);
  state.origButtonLabels ||= Object.create(null);
  if (btn && !state.origButtonLabels[btnId]) {
    state.origButtonLabels[btnId] = btn.textContent || successLabel || "导出";
  }
  try {
    const response = await apiFetch(`/api/export?format=${encodeURIComponent(format)}${projectQuerySuffix()}`, { rawResponse: true });
    const blob = typeof response?.blob === "function" ? await response.blob() : null;
    const text = blob && typeof blob.text === "function"
      ? await blob.text()
      : (typeof response?.text === "function" ? await response.text() : "");
    let downloaded = false;
    if (blob && typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const contentDisposition = response.headers?.get?.("Content-Disposition") || "";
      const match = contentDisposition.match(/filename="?([^"]+)"?/);
      link.download = match ? match[1] : `compass-${format}.md`;
      link.click?.();
      URL.revokeObjectURL?.(url);
      downloaded = true;
    }
    const copied = text ? await copyTextToClipboard(text) : false;
    const ok = downloaded || copied;
    if (btn) {
      if (copied) {
        btn.removeAttribute?.("data-clipboard-fallback");
      } else {
        btn.setAttribute?.("data-clipboard-fallback", "true");
      }
      btn.textContent = ok ? (successLabel || "已导出") : "请手动复制";
      state.exportTimers ||= Object.create(null);
      if (state.exportTimers[btnId]) clearTimeout(state.exportTimers[btnId]);
      state.exportTimers[btnId] = setTimeout(() => { btn.textContent = state.origButtonLabels[btnId] || successLabel || "导出"; }, 2000);
    }
  } catch (_err) {
    if (btn) {
      btn.textContent = "导出失败";
      state.exportTimers ||= Object.create(null);
      if (state.exportTimers[btnId]) clearTimeout(state.exportTimers[btnId]);
      state.exportTimers[btnId] = setTimeout(() => { btn.textContent = state.origButtonLabels[btnId] || "导出"; }, 2000);
    }
  }
}

function bindDynamicControls() {
  document.querySelectorAll("#guidance-extract").forEach((button) => { button.onclick = extractCandidates; });
  document.querySelectorAll("[data-chapter-id]").forEach((button) => {
    button.onclick = () => {
      state.activeChapterId = state.activeChapterId === button.dataset.chapterId ? null : button.dataset.chapterId;
      render();
    };
  });
  const clearFilterBtn = document.getElementById("thinking-clear-filter");
  if (clearFilterBtn) {
    clearFilterBtn.onclick = () => { state.activeChapterId = null; render(); };
  }
  document.querySelectorAll(".presence-pill").forEach((button) => {
    button.onclick = () => {
      const targetLens = button.dataset.targetLens;
      const targetMember = button.dataset.targetMember;
      if (targetLens === "team") {
        state.lens = "team";
      } else if (targetLens === "personal") {
        state.lens = "personal";
        if (targetMember) state.member = targetMember;
      }
      render();
    };
  });
  document.querySelectorAll("[data-anchor-edit]").forEach((button) => {
    button.onclick = () => {
      openAnchorInlineForm(button.dataset.anchorEdit, button.dataset.anchorSeed || "");
    };
  });
  document.querySelectorAll("[data-hint-action]").forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.hintAction;
      const factId = button.dataset.hintFact;
      const evId = button.dataset.hintEv;
      if (action === "edit_goal") {
        openAnchorInlineForm("goal", document.getElementById("goal-title")?.textContent || "");
      } else if (action === "edit_next") {
        openAnchorInlineForm("next_step", document.getElementById("next-consensus-title")?.textContent || "");
      } else if (action === "accept_fact" && factId) {
        acceptFact(factId, "accept_fact", { fromDrawer: false });
      } else if (action === "open_evidence" && evId) {
        openEvidence(evId);
      }
    };
  });
  document.querySelectorAll("[data-dismiss-hint]").forEach((button) => {
    button.onclick = () => {
      dismissHint(button.dataset.dismissHint);
    };
  });
  document.querySelectorAll("[data-inline-review]").forEach((button) => {
    button.onclick = (event) => {
      event?.stopPropagation?.();
      event?.preventDefault?.();
      acceptFact(button.dataset.targetId, button.dataset.inlineReview, { fromDrawer: false });
    };
    button.onkeydown = (event) => {
      if (event?.key === "Enter" || event?.key === " ") {
        event.stopPropagation?.();
      }
    };
  });
  document.querySelectorAll("[data-fact-id]").forEach((el) => {
    if (el?.dataset?.reviewId) return;
    if (typeof el?.hasAttribute === "function" && el.hasAttribute("data-review-id")) return;
    if (typeof el?.closest === "function" && el.closest("#evidence-drawer")) return;
    el.onclick = (event) => {
      if (event?.target && event.target !== el && typeof event.target.closest === "function") {
        const hit = event.target.closest("[data-inline-review], [data-evidence-id], button, a, input, textarea");
        if (hit && hit !== el) return;
      }
      openFact(el.dataset.factId);
    };
    el.onkeydown = (e) => {
      if (e?.target && e.target !== el) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openFact(el.dataset.factId);
      }
    };
  });
  wireEvidenceTargets(document);
  const popover = document.getElementById("citation-popover");
  if (popover) {
    popover.onmouseenter = () => { if (state.popoverTimer) { clearTimeout(state.popoverTimer); state.popoverTimer = null; } };
    popover.onmouseleave = scheduleHidePopover;
    popover.onfocusin = () => { if (state.popoverTimer) { clearTimeout(state.popoverTimer); state.popoverTimer = null; } };
    popover.onfocusout = scheduleHidePopover;
  }
}

function requestInlineSoloSigner(pendingAction, introText = "") {
  state.pendingSignerAction = pendingAction;
  const message = introText || "Solo 模式首次定案只需填一次你的署名（自动记住），之后点击定案立即生效。";
  openDrawer(
    "首次定案 · 填写个人署名",
    `<div class="detail-block solo-signer-box">
      <p class="empty">${esc(message)}</p>
      <label class="review-note-label">我的署名<input type="text" class="solo-signer-input" data-solo-signer-input placeholder="例如：fang 或你的名字" autocomplete="off"></label>
      <div class="solo-signer-actions">
        <button type="button" class="review-action" data-solo-signer-submit>保存署名并继续</button>
      </div>
      <p class="source-warning" data-solo-signer-error hidden></p>
    </div>`,
  );
  const signerField = document.getElementById("evidence-drawer")?.querySelector?.("[data-solo-signer-input]");
  signerField?.focus?.();
}

function bindDrawerControls() {
  const drawer = document.getElementById("evidence-drawer");
  if (!drawer || typeof drawer.querySelectorAll !== "function") return;
  drawer.querySelectorAll("[data-review-id]").forEach((button) => {
    button.onclick = () => confirmRelation(button.dataset.reviewId, button.dataset.factId);
  });
  drawer.querySelectorAll("[data-fact-review-id]").forEach((button) => {
    button.onclick = () => acceptFact(button.dataset.factReviewId, button.dataset.reviewAction || "accept_fact", { fromDrawer: true });
  });
  drawer.querySelectorAll("[data-direction-review-id]").forEach((button) => {
    button.onclick = () => acceptFact(button.dataset.directionReviewId, button.dataset.directionAction, { fromDrawer: true });
  });
  const submitSoloSigner = async () => {
    const input = drawer.querySelector("[data-solo-signer-input]");
    const errEl = drawer.querySelector("[data-solo-signer-error]");
    const signerName = String(input?.value || "").trim();
    if (!signerName) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = "请填写你的署名（如姓名或代号）。";
      }
      input?.focus?.();
      return;
    }
    writeStorage("compass_reviewer_name", signerName);
    const topReviewerEl = document.getElementById("reviewer-input");
    if (topReviewerEl) topReviewerEl.value = signerName;
    const pending = state.pendingSignerAction;
    state.pendingSignerAction = null;
    closeDrawer();
    if (!pending) return;
    if (pending.type === "accept_fact") {
      await acceptFact(pending.factId, pending.action, { fromDrawer: pending.fromDrawer, signer: signerName });
    } else if (pending.type === "confirm_relation") {
      await confirmRelation(pending.relationId, pending.factId, { signer: signerName });
    } else if (pending.type === "quick_note") {
      await submitQuickNote(null, { kind: pending.kind, text: pending.text, autoAccept: true, signer: signerName });
    }
  };
  drawer.querySelectorAll("[data-solo-signer-submit]").forEach((button) => {
    button.onclick = () => submitSoloSigner();
  });
  drawer.querySelectorAll("[data-solo-signer-input]").forEach((input) => {
    input.onkeydown = (event) => {
      if (event?.key === "Enter") {
        event.preventDefault?.();
        submitSoloSigner();
      }
    };
  });
  wireEvidenceTargets(drawer);
}

function openDrawer(title, body, triggerOverride = null) {
  const drawer = document.getElementById("evidence-drawer");
  if (drawer.hidden) {
    const activeTrigger = triggerOverride || (typeof document.activeElement === "object" ? document.activeElement : null);
    if (activeTrigger) {
      state.lastDrawerTrigger = activeTrigger;
      state.lastTriggerElement = activeTrigger;
      state.lastDrawerTriggerSpec = {
        id: activeTrigger.id || "",
        factId: activeTrigger.dataset?.factId || "",
        evidenceId: activeTrigger.dataset?.evidenceId || "",
      };
    }
  }
  drawer.hidden = false;
  document.getElementById("drawer-title").textContent = title;
  document.getElementById("drawer-body").innerHTML = body;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  document.getElementById("scrim").hidden = false;
  bindDrawerControls();
  const closeBtn = document.getElementById("drawer-close");
  if (closeBtn && typeof closeBtn.focus === "function") closeBtn.focus();
}

function openFact(factId) {
  state.evidenceRequestSeq = (state.evidenceRequestSeq || 0) + 1;
  const teamFact = (state.data.team?.facts || []).find((item) => item.id === factId);
  const personalFact = (state.data.personal?.[state.member]?.facts || []).find((item) => item.id === factId);
  const fact = state.lens === "team" ? teamFact : (personalFact || teamFact);
  if (!fact) return;
  const isSolo = effectiveWorkMode() === "solo";
  const canConfirmHere = state.lens === "team" || isSolo;
  const effectiveStatus = resolveFactStatus(fact);
  const superseder = findSupersedingAcceptedFact(fact);
  const comparisonBlock = renderDrawerConflictOrSupersedeHTML(fact, isSolo);
  const relations = [...(state.data.candidate_relations || []), ...(state.data.confirmed_relations || [])].filter((relation) => relation.fact_id === fact.id);
  const ids = [...new Set([...(fact.evidence_ids || []), ...relations.map((relation) => relation.evidence_id), ...(fact.source_state?.replacement_ids || []), ...(fact.source_state?.observation_ids || [])])];
  const direction = (state.data.team?.directions?.current || []).find((row) => row.fact_id === fact.id);
  const dirSuggestion = ["abandoned", "deferred"].includes(fact.direction_suggestion) ? fact.direction_suggestion : "";
  const directionAction = direction ? direction.direction_state === "active" ? '<p class="reviewed-note">该方案已恢复推进，旧状态保留在历史。</p>' : `<button type="button" class="review-action" data-direction-review-id="${esc(fact.id)}" data-direction-action="restore_direction">恢复推进并保留历史</button>` : dirSuggestion ? `<button type="button" class="review-action" data-direction-review-id="${esc(fact.id)}" data-direction-action="confirm_${dirSuggestion}">确认${dirSuggestion === "abandoned" ? "放弃" : "暂缓"}该方案</button>` : "";
  const rejectBtn = effectiveStatus === "rejected" ? "" : `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}" data-review-action="reject_fact">${isSolo ? "暂不采纳" : "拒绝候选"}</button>`;
  const requestBtn = effectiveStatus === "needs_evidence" ? "" : `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}" data-review-action="request_evidence">要求补证据</button>`;
  const reviewActions = canConfirmHere && !superseder && effectiveStatus !== "accepted" ? `<label class="review-note-label" for="review-note">备注说明（可选）</label><textarea id="review-note" class="review-note-input" rows="2" placeholder="${isSolo ? "定案补充说明或后续待补证据" : "拒绝原因或缺少的具体证据"}"></textarea>${rejectBtn}${requestBtn}` : "";
  const confirmLabel = isSolo && state.lens === "personal" ? "定案为项目基准" : "确认为团队事实";
  const acceptAction = state.data.project?.read_only ? `<p class="empty">当前项目为只读预览，确认操作请回到该项目的运行窗口。</p>` : superseder ? `<p class="meta-note">本条旧记录已被更新的定案接替，仅作历史保留。</p>` : !sourceCurrent(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 请核对当前来源。原确认与证据仍保留。</p>` : canConfirmHere && directionAction ? directionAction : canConfirmHere && effectiveStatus !== "accepted" ? `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}">${confirmLabel}</button>${reviewActions}` : reviewActions;
  const verifiedBlock = renderSpeculativeDetail(fact);
  const displayStatusText = superseder ? "已由新定案接替" : statusLabel(effectiveStatus);
  const drawerTitle = cleanUiText(fact.short_title || fact.clean_value || fact.value);
  openDrawer(drawerTitle, `${comparisonBlock}<div class="detail-block"><div class="detail-value">${sourceTimeHTML(fact)}</div><p class="${effectiveStatus === "accepted" ? "reviewed-note" : "meta-note"}">${esc(fact.author || "记录者")} · ${effectiveStatus === "accepted" ? (isSolo ? "已拍板定案，来源版本仍可核对" : "负责人已确认，来源版本仍可核对") : superseder ? "已由更晚定案接替" : "当前有效性待核对"}</p></div><div class="detail-block"><div class="detail-label">当前状态与范围</div><div class="detail-value">${esc(displayStatusText)} · 归属：${esc(subjectKeyLabel(fact.subject_key))}</div>${acceptAction}</div>${verifiedBlock}<div class="detail-block"><div class="detail-label">证据关联</div>${relations.length ? relations.map((relation) => `<div class="relation-item"><button type="button" class="evidence-item" data-evidence-id="${esc(relation.evidence_id)}"><span class="evidence-dot ${relation.status === "confirmed" ? "fact_source" : "execution_result"}"></span><span><span class="evidence-title">${esc(relation.basis)}</span><span class="evidence-meta">${esc(relationMethodLabel(relation.method))} · ${esc(statusLabel(relation.status))} · ${relation.score == null ? "评分未知" : `匹配度 ${esc(relation.score)}`}</span></span><span class="evidence-links">打开</span></button>${relation.status === "candidate" ? (state.data.project?.read_only ? `<span class="meta-note">只读预览，关联关系待主项目确认</span>` : `<button type="button" class="review-action" data-review-id="${esc(relation.id)}" data-fact-id="${esc(fact.id)}">确认支持关系</button>`) : `<span class="reviewed-note">${isSolo ? "已定案关联" : "负责人已确认"}</span>`}</div>`).join("") : `<p class="empty">暂未提出关联关系。</p>`}</div><div class="detail-block"><div class="detail-label">依据原文</div><div class="card-pill-row">${ids.map((eid) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(eid)}">${esc(eid)}</button>`).join("") || "证据缺口"}</div></div><details class="answer-footnotes raw-meta-fold"><summary>底层技术字段（排障核对用 · 默认折叠）</summary><div class="meta-note">记录编号：${esc(fact.id)} · 会话标识：${esc(fact.session_id || "未提供")} · 位置键：${esc(fact.subject_key || "")}</div></details>`);
}

async function acceptFact(factId, action = "accept_fact", options = {}) {
  if (state.data.project?.read_only) { openDrawer("只读项目", `<p class="empty">当前项目只读，不能执行确认或定案。</p>`); return; }
  const isSolo = effectiveWorkMode() === "solo";
  const reviewer = String(options?.signer || document.getElementById("reviewer-input")?.value || "").trim();
  if (!reviewer) {
    if (isSolo) {
      requestInlineSoloSigner({ type: "accept_fact", factId, action, fromDrawer: Boolean(options?.fromDrawer) });
      return;
    }
    openDrawer("署名确认", `<p class="empty">请先填写负责人姓名，再确认事实。</p>`);
    return;
  }
  try {
    const note = options?.fromDrawer ? (document.getElementById("review-note")?.value.trim() || "") : "";
    const payload = await apiFetch("/api/review", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, fact_id: factId, reviewer, note})});
    if (olderState(payload)) return;
    state.data = payload;
    render();
    invalidateInvestigation("确认记录已更新，请重新提问以使用最新状态。");
    const drawer = document.getElementById("evidence-drawer");
    if (options?.fromDrawer || (drawer && !drawer.hidden)) {
      openFact(factId);
    }
  } catch (error) {
    openDrawer("确认失败", `<p class="empty">${esc(error.message)}</p>`);
  }
}

async function confirmRelation(relationId, factId, options = {}) {
  if (state.data.project?.read_only) { openDrawer("只读项目", `<p class="empty">当前项目只读，不能确认关系。</p>`); return; }
  const isSolo = effectiveWorkMode() === "solo";
  const reviewer = String(options?.signer || document.getElementById("reviewer-input")?.value || "").trim();
  if (!reviewer) {
    if (isSolo) {
      requestInlineSoloSigner({ type: "confirm_relation", relationId, factId });
      return;
    }
    openDrawer("署名确认", `<p class="empty">请先填写负责人姓名，再确认这条证据关系。</p>`);
    return;
  }
  try {
    const payload = await apiFetch("/api/review", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({relation_id: relationId, reviewer}),
    });
    if (olderState(payload)) return;
    state.data = payload;
    render();
    invalidateInvestigation("证据关系确认记录已更新，请重新提问以使用最新状态。");
    openFact(factId);
  } catch (error) {
    openDrawer("确认失败", `<p class="empty">${esc(error.message)}</p>`);
  }
}

async function openEvidence(evidenceId, triggerOverride = null) {
  const reqId = (state.evidenceRequestSeq = (state.evidenceRequestSeq || 0) + 1);
  openDrawer(evidenceId, `<p class="empty">正在加载原始材料…</p>`, triggerOverride);
  const isStaleOrClosed = () => {
    const drawer = document.getElementById("evidence-drawer");
    return state.evidenceRequestSeq !== reqId || !drawer || drawer.hidden;
  };
  try {
    const evidence = await apiFetch(`/api/evidence?id=${encodeURIComponent(evidenceId)}${projectQuerySuffix()}`);
    if (isStaleOrClosed()) return;
    const paired = evidence.metadata?.paired_evidence_id;
    const pairLink = paired ? `<div class="detail-block"><div class="detail-label">关联调用与结果</div><button class="answer-evidence" data-evidence-id="${esc(paired)}">${esc(paired)}</button><p class="empty">这条关联记录执行来源，完成状态仍需核对。</p></div>` : "";
    const catalogEntry = state.data?.evidence?.find((item) => item.id === evidence.id);
    const exitCode = catalogEntry && Object.prototype.hasOwnProperty.call(catalogEntry, 'exit_code') ? catalogEntry.exit_code : evidence.metadata?.exit_code;
    const origin = catalogEntry?.command_origin || 'reported';
    const heading = origin === 'agent_report' ? '智能体命令报告' : evidence.kind === 'command_execution' ? '原生命令执行' : '命令执行报告';
    const command = (catalogEntry?.command_preview || evidence.kind === 'command_execution') ? `<div class="detail-block"><div class="detail-label">${heading}</div><div class="raw-content">${esc(JSON.stringify(evidence.metadata?.command || []))}</div><div class="detail-value">${esc(commandOriginLabel(origin))} · ${esc(evidence.metadata?.cwd || "工作目录未知")} · ${esc(evidence.metadata?.execution_status || "报告状态未提供")} · 退出码 ${esc(Number.isInteger(exitCode) ? exitCode : "未知")}</div>${evidence.metadata?.reported_source_ref ? `<p class="detail-value">Agent声明的来源 ${esc(evidence.metadata.reported_source_ref)}</p>` : ''}<p class="empty">退出码只描述这条命令或报告，测试范围、版本和任务完成仍需独立核对。</p></div>` : "";
    const isSolo = effectiveWorkMode() === "solo";
    const linkedMap = new Map();
    for (const f of [...(state.data?.team?.facts || []), ...(state.data?.personal?.[state.member]?.facts || [])]) {
      if (f?.id && (f.evidence_ids || []).includes(evidence.id) && !linkedMap.has(f.id)) {
        linkedMap.set(f.id, f);
      }
    }
    const linkedFacts = [...linkedMap.values()];
    const focusFact = linkedFacts.find((f) => Boolean(findSupersedingAcceptedFact(f))) || linkedFacts.find((f) => resolveFactStatus(f) === "conflicted") || null;
    const comparisonHTML = focusFact ? renderDrawerConflictOrSupersedeHTML(focusFact, isSolo) : "";
    const linkedSummaryHTML = linkedFacts.length
      ? `<div class="detail-block"><div class="detail-label">关联的结论卡片</div>${linkedFacts.slice(0, 3).map((f) => {
          const fSup = findSupersedingAcceptedFact(f);
          const fBadge = fSup ? renderStatusBadge("superseded", "已由新定案接替") : renderStatusBadge(resolveFactStatus(f));
          return `<div class="linked-fact-line">${fBadge} <span>${esc(cleanUiText(f.short_title || f.value))}</span></div>`;
        }).join("")}</div>`
      : "";
    const sourceChannelText = humanSourceRef(evidence.metadata?.source_ref, evidence.kind) || evidenceKindLabel(evidence.kind);
    const kindTitle = evidenceKindLabel(evidence.kind, evidence.metadata?.source_ref);
    openDrawer(`${kindTitle} · ${evidence.id}`, `${comparisonHTML}<div class="detail-block"><div class="detail-label">记录来源</div><div class="detail-value">记录方式：${esc(sourceChannelText)} · 记录人：${esc(evidence.author || "未知")} · 记录时间：${esc(formatTime(evidence.observed_at))}</div></div>${linkedSummaryHTML}${pairLink}${command}<div class="detail-block"><div class="detail-label">原始记录内容</div><div class="raw-content">${esc(evidence.content || (evidence.kind === "command_execution" ? "此命令没有文本输出" : ""))}</div></div><details class="answer-footnotes raw-meta-fold"><summary>底层技术字段（排障核对用 · 默认折叠）</summary><pre class="raw-meta-pre">${esc(JSON.stringify(evidence.metadata || {}, null, 2))}</pre></details>`);
  } catch (error) {
    if (isStaleOrClosed()) return;
    openDrawer(evidenceId, `<p class="empty">无法加载该材料：${esc(error.message)}</p>`);
  }
}

function closeDrawer() {
  state.evidenceRequestSeq = (state.evidenceRequestSeq || 0) + 1;
  const drawer = document.getElementById("evidence-drawer");
  const modal = document.getElementById("handoff-modal");
  const popover = document.getElementById("citation-popover");
  if (popover && !popover.hidden) hideCitationPopover();
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  drawer.hidden = true;
  const drawerBody = document.getElementById("drawer-body");
  if (drawerBody) drawerBody.innerHTML = "";
  if (!modal || modal.hidden) {
    document.getElementById("scrim").hidden = true;
  }
  let target = state.lastDrawerTrigger;
  const spec = state.lastDrawerTriggerSpec;
  state.lastDrawerTrigger = null;
  state.lastDrawerTriggerSpec = null;
  if (target && target.isConnected === false) {
    let reconnected = null;
    if (spec?.factId && typeof document.querySelectorAll === "function") {
      const factNodes = document.querySelectorAll("[data-fact-id]");
      for (let i = 0; i < factNodes.length; i += 1) {
        const node = factNodes[i];
        if (node?.dataset?.factId === spec.factId && node.isConnected !== false) {
          reconnected = node;
          break;
        }
      }
    } else if (spec?.evidenceId && typeof document.querySelectorAll === "function") {
      const evNodes = document.querySelectorAll("[data-evidence-id]");
      for (let i = 0; i < evNodes.length; i += 1) {
        const node = evNodes[i];
        if (node?.dataset?.evidenceId === spec.evidenceId && node.isConnected !== false) {
          reconnected = node;
          break;
        }
      }
    } else if (spec?.id && typeof document.getElementById === "function") {
      const byId = document.getElementById(spec.id);
      if (byId && byId.isConnected !== false) reconnected = byId;
    }
    target = reconnected;
  }
  if (!target || target.isConnected === false) {
    if (modal && !modal.hidden) {
      target = document.getElementById("handoff-close-btn") || document.getElementById("member-select");
    } else {
      target = document.getElementById("btn-handoff-brief") || document.getElementById("member-select");
    }
  }
  if (target && typeof target.focus === "function") {
    target.focus();
  }
}

const handoffCta = document.getElementById("btn-handoff-brief");
if (handoffCta) handoffCta.addEventListener("click", openHandoffBrief);
const handoffClose = document.getElementById("handoff-close-btn");
if (handoffClose) handoffClose.addEventListener("click", closeHandoffBrief);
const handoffModalEl = document.getElementById("handoff-modal");
if (handoffModalEl) {
  handoffModalEl.addEventListener("click", (event) => {
    if (event?.target !== handoffModalEl) return;
    const drawer = document.getElementById("evidence-drawer");
    if (drawer && !drawer.hidden) {
      closeDrawer();
      return;
    }
    closeHandoffBrief();
  });
}
const handoffCopy = document.getElementById("handoff-copy-btn");
if (handoffCopy) handoffCopy.addEventListener("click", copyHandoffMarkdown);
const handoffExportIssue = document.getElementById("handoff-export-issue-btn");
if (handoffExportIssue) handoffExportIssue.addEventListener("click", () => exportCognitiveAsset("issue", "handoff-export-issue-btn", "已导出 Issue"));
const handoffExportPr = document.getElementById("handoff-export-pr-btn");
if (handoffExportPr) handoffExportPr.addEventListener("click", () => exportCognitiveAsset("pr", "handoff-export-pr-btn", "已导出 PR"));
const handoffExportPrd = document.getElementById("handoff-export-prd-btn");
if (handoffExportPrd) handoffExportPrd.addEventListener("click", () => exportCognitiveAsset("prd", "handoff-export-prd-btn", "已导出 PRD"));
const handoffExportMindmap = document.getElementById("handoff-export-mindmap-btn");
if (handoffExportMindmap) handoffExportMindmap.addEventListener("click", () => exportCognitiveAsset("mindmap", "handoff-export-mindmap-btn", "已导出脑图"));

document.querySelectorAll(".mode-pill").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); setWorkMode(button.dataset?.workMode); }));
document.querySelectorAll(".workbench-view-btn").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); setWorkbenchView(button.dataset?.workbenchView); }));
const anchorInlineFormEl = document.getElementById("anchor-inline-form");
if (anchorInlineFormEl) anchorInlineFormEl.addEventListener("submit", saveAnchorInlineForm);
const anchorInlineCancelEl = document.getElementById("anchor-inline-cancel");
if (anchorInlineCancelEl) anchorInlineCancelEl.addEventListener("click", closeAnchorInlineForm);
const quickNoteFormEl = document.getElementById("quick-note-form");
if (quickNoteFormEl) quickNoteFormEl.addEventListener("submit", submitQuickNote);
const reviewerInputEl = document.getElementById("reviewer-input");
if (reviewerInputEl && typeof reviewerInputEl.addEventListener === "function") {
  reviewerInputEl.addEventListener("input", (event) => {
    if (reviewerInputEl.readOnly) return;
    writeStorage("compass_reviewer_name", String(event?.target?.value ?? reviewerInputEl.value ?? "").trim());
  });
}
document.querySelectorAll(".lens").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); state.lens = button.dataset.lens; render(); }));
document.querySelectorAll(".layer-choice").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); state.layer = button.dataset.layerChoice; render(); }));
document.getElementById("member-select").addEventListener("change", (event) => { state.member = event.target.value; render(); });
document.getElementById("drawer-close").addEventListener("click", closeDrawer);
document.getElementById("scrim").addEventListener("click", () => {
  const drawer = document.getElementById("evidence-drawer");
  const modal = document.getElementById("handoff-modal");
  if (drawer && !drawer.hidden) { closeDrawer(); return; }
  if (modal && !modal.hidden) { closeHandoffBrief(); }
});
async function switchLlmProfile(profileId) {
  const target = String(profileId || "").trim();
  if (!target || state.data?.sample_mode === true || state.data?.project?.read_only) return;
  const selectEl = document.getElementById("llm-profile-select");
  if (selectEl) selectEl.disabled = true;
  try {
    const payload = await apiFetch("/api/llm-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: target }),
    });
    if (!olderState(payload)) {
      state.data = payload;
      render();
      const answerEl = document.getElementById("investigation-answer");
      const qInput = document.getElementById("investigation-question");
      if (answerEl && !answerEl.hidden && qInput && qInput.value.trim()) {
        await investigateProject({ preventDefault() {} });
      }
    }
  } catch (error) {
    const statusBadge = document.getElementById("llm-status-badge");
    if (statusBadge) statusBadge.title = `切换失败：${error.message}`;
  } finally {
    if (selectEl) selectEl.disabled = false;
  }
}

document.getElementById("investigation-form").addEventListener("submit", investigateProject);
const llmProfileSelectEl = document.getElementById("llm-profile-select");
if (llmProfileSelectEl && typeof llmProfileSelectEl.addEventListener === "function") {
  llmProfileSelectEl.addEventListener("change", (event) => {
    const nextId = event?.target?.value ?? llmProfileSelectEl.value;
    switchLlmProfile(nextId);
  });
}
document.getElementById("export-state").addEventListener("click", async () => {
  try {
    const exportUrl = state.data?.project?.read_only && state.projectId ? `/api/export?project_id=${encodeURIComponent(state.projectId)}` : '/api/export';
    const response = await apiFetch(exportUrl, { rawResponse: true });
    if (typeof response?.blob === "function" && typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'compass-state.json';
      link.click?.();
      URL.revokeObjectURL?.(url);
    }
  } catch (error) {
    openDrawer('导出失败', `<p class="empty">${esc(error.message || '无法导出当前状态')}</p>`);
  }
});
document.getElementById("clear-query-stats").addEventListener("click", async () => {
  try {
    state.data = await apiFetch('/api/query-stats/clear', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    state.projectId = state.data?.project?.project_id || null;
    state.revision += 1; render();
  } catch (error) {
    openDrawer('清除失败', `<p class="empty">${esc(error.message || '无法清除调查统计')}</p>`);
  }
});
document.getElementById("project-scan-form").addEventListener("submit", scanNewProject);
document.getElementById("refresh-intake").addEventListener("click", refreshNative);
document.getElementById("rescan-project").addEventListener("click", rescanProject);
document.getElementById("extract-candidates").addEventListener("click", extractCandidates);
document.getElementById('trace-start').addEventListener('click', () => jumpTrace(false));
document.getElementById('trace-latest').addEventListener('click', () => jumpTrace(true));
setInterval(() => { if (!document.hidden) refreshNative(); }, 3000);
document.getElementById("evidence-filter").addEventListener("input", (event) => { state.evidenceQuery = event.target.value; render(); });
if (typeof document.addEventListener === "function") {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const popover = document.getElementById("citation-popover");
    const drawer = document.getElementById("evidence-drawer");
    const modal = document.getElementById("handoff-modal");
    if (popover && !popover.hidden) {
      const anchor = state.popoverAnchor;
      const active = document.activeElement;
      const insidePopover = Boolean(active && (
        (typeof popover.contains === "function" && popover.contains(active)) ||
        active?.dataset?.popoverOpen
      ));
      hideCitationPopover();
      if (insidePopover && anchor && typeof anchor.focus === "function") {
        anchor.focus();
      }
      return;
    }
    if (drawer && !drawer.hidden) { closeDrawer(); return; }
    if (modal && !modal.hidden) { closeHandoffBrief(); }
  });
}
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("pointermove", handleProximityPrefetch, { passive: true });
}
loadState().catch((error) => { document.getElementById("connection-label").textContent = `状态暂不可用：${error.message}`; });
