const state = { data: null, lens: "personal", workMode: null, workbenchView: readStorage("compass_workbench_view") === "mindmap" ? "mindmap" : "list", member: null, evidenceQuery: "", layer: "overview", refreshing: false, quickNotePending: false, anchorEditing: null, anchorSaving: false, pendingSignerAction: null, revision: 0, investigationRequest: 0, projectId: null, activeChapterId: null, activeWorkspaceUri: "", inflightWorkspaceUri: "", pendingWorkspaceUri: "", sidecarActivating: false, freshFactIds: new Set(), freshTimer: null, evidenceCache: Object.create(null), evidenceRequestSeq: 0, popoverTimer: null, popoverAnchor: null, popoverCurrentId: null, lastTriggerElement: null, lastModalTrigger: null, lastDrawerTrigger: null, lastDrawerTriggerSpec: null, copyRestoreTimer: null, toastTimer: null, toastUndoKey: null, exportTimers: Object.create(null), delayedQueue: new Map(), armTimers: new Map(), armedKeys: new Map(), openDetails: new Set(), lastCopyRetryBrief: "", hasRenderedOnce: false, activeTransition: null };

function renderWithTransition(fn) {
  const reduceMotion = typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)")?.matches;
  const targetCount = state.data ? (activeView()?.facts?.length || 0) : 0;
  const teamCount = state.lens === "team" ? (state.data?.team?.facts?.length || 0) : 0;
  const heavyPage = (typeof document !== "undefined"
    && typeof document.querySelectorAll === "function"
    && (document.querySelectorAll(".fact-card, .review-queue-item, .decision-item, .todo-item, .thinking-branch-node")?.length || 0) > 80)
    || targetCount > 80
    || teamCount > 80;
  const canTransition = Boolean(
    state.hasRenderedOnce
    && typeof document !== "undefined"
    && !document.hidden
    && typeof document.startViewTransition === "function"
    && !reduceMotion
    && !heavyPage
  );
  if (!canTransition) {
    fn();
    return;
  }
  state.activeTransition?.skipTransition?.();
  const vt = document.startViewTransition(() => {
    fn();
  });
  state.activeTransition = vt;
  vt.ready?.catch?.(() => {});
  vt.finished?.catch?.(() => {});
  vt.finished?.finally?.(() => {
    if (state.activeTransition === vt) state.activeTransition = null;
  });
}

function makeSafeTimer(fn, ms) {
  const timer = setTimeout(fn, ms);
  if (timer && typeof timer.unref === "function") timer.unref();
  return timer;
}

function resolveSigner(isSolo, overrideSigner = "") {
  const direct = String(overrideSigner || "").trim();
  if (direct) return direct;
  const ownerId = String(state.data?.agent_api?.owner_id || "").trim();
  if (ownerId) return ownerId;
  const reviewerEl = document.getElementById("reviewer-input");
  const typed = String(reviewerEl?.value || "").trim();
  if (typed) return typed;
  if (!isSolo) return "";
  const stored = readStorage("compass_reviewer_name").trim();
  const fallbackMember = state.member && state.member !== "project-documents" ? state.member : "";
  const autoSigner = stored || String(state.data?.project?.owner_id || fallbackMember || "solo").trim() || "solo";
  if (reviewerEl && !reviewerEl.value && !reviewerEl.readOnly) {
    reviewerEl.value = autoSigner;
  }
  writeStorage("compass_reviewer_name", autoSigner);
  return autoSigner;
}

function getSidecarToken() {
  try {
    const search = typeof window !== "undefined" ? String(window.location?.search || "") : "";
    if (!search || typeof URLSearchParams !== "function") return "";
    return URLSearchParams ? (new URLSearchParams(search).get("token") || "") : "";
  } catch (_err) {
    return "";
  }
}

function hasSidecarBridge() {
  return typeof window !== "undefined" && Boolean(window.sidecar && (window.sidecar.agent || window.sidecar.ui || typeof window.sidecar.getWorkspaceUris === "function"));
}

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
  const teamClients = state.data?.agent_api?.enabled ? (state.data.agent_api.clients || []).length : 0;
  return (humanMembers.length > 1 || teamClients > 1) ? "team" : "solo";
}
function setWorkMode(mode) {
  const normalized = mode === "team" ? "team" : "solo";
  state.workMode = normalized;
  writeStorage("compass_work_mode", normalized);
  renderWithTransition(() => render());
}
function setWorkbenchView(viewMode) {
  const normalized = viewMode === "mindmap" ? "mindmap" : "list";
  state.workbenchView = normalized;
  writeStorage("compass_workbench_view", normalized);
  renderWithTransition(() => render());
}

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
const label = (kind) => ({goal:"核心目标", task:"待办事项", decision:"方案决定", assumption:"未验证前提"}[kind] || kind || "记录");
const statusLabel = (status) => ({
  accepted: "已确认",
  confirmed: "已确认",
  dialogue_decided: "对话已定",
  completed: "已完成",
  proposed: "待确认",
  candidate: "待确认",
  conflicted: "存在分歧",
  rejected: "已忽略",
  needs_evidence: "待补证据",
  needs_more_evidence: "待补证据",
  superseded: "已有新版本",
  deferred: "已暂缓",
  abandoned: "已放弃",
  raw: "原始记录",
  pending: "待处理",
  active: "进行中",
}[status] || status || "待确认");
const safeToken = (value, fallback = "pending") => {
  const raw = String(value ?? "");
  return /^[a-z0-9_-]+$/i.test(raw) ? raw : fallback;
};
const STATUS_BADGE_MAP = Object.assign(Object.create(null), {
  accepted: { cls: "is-accepted", text: "已确认", title: "你或团队已确认采用" },
  confirmed: { cls: "is-accepted", text: "已确认", title: "你或团队已确认采用" },
  dialogue_decided: { cls: "is-dialogue", text: "对话已定", title: "在对话中明确同意过的记录，可正式确认或撤回" },
  completed: { cls: "is-accepted", text: "已完成", title: "该事项已标记完成" },
  current: { cls: "is-accepted", text: "● 当前最新", title: "对应原始记录仍为当前最新版本" },
  conflicted: { cls: "is-conflicted", text: "存在分歧", title: "同一主题下存在不同说法，点击可对照选择" },
  blocked: { cls: "is-conflicted", text: "受阻", title: "推进受阻" },
  unavailable: { cls: "is-conflicted", text: "● 来源缺失", title: "原文件或记录来源暂不可用" },
  rejected: { cls: "is-rejected", text: "已忽略", title: "已暂不采用，原始记录仍保留在档案中" },
  abandoned: { cls: "is-rejected", text: "已放弃", title: "已明确确认放弃该方向" },
  needs_evidence: { cls: "is-warn", text: "待补证据", title: "需要补充更多依据后才能确认" },
  needs_more_evidence: { cls: "is-warn", text: "待补证据", title: "需要补充更多依据后才能确认" },
  superseded: { cls: "is-warn", text: "已有新版本", title: "已有更新的确认记录接替" },
  deferred: { cls: "is-warn", text: "已暂缓", title: "当前暂缓推进" },
  proposed: { cls: "is-proposed", text: "待确认", title: "等待你确认或忽略" },
  candidate: { cls: "is-proposed", text: "待确认", title: "关联关系尚待确认" },
  raw: { cls: "is-proposed", text: "原始记录", title: "尚未整理为结论的原始来源" },
  pending: { cls: "is-proposed", text: "待处理", title: "等待处理" },
  active: { cls: "is-info", text: "进行中", title: "正在推进中" },
  relation_confirmed: { cls: "is-info", text: "关系已确认", title: "依据与结论的关联已确认" },
  recommended: { cls: "is-info", text: "系统推荐", title: "系统基于已有记录给出的参考建议" },
});
function getBadgeMeta(status) {
  const key = String(status || "proposed").toLowerCase();
  return Object.prototype.hasOwnProperty.call(STATUS_BADGE_MAP, key)
    ? STATUS_BADGE_MAP[key]
    : { cls: "is-proposed", text: key ? statusLabel(key) : "待确认", title: "" };
}
function renderStatusBadge(status, customLabel = "", customTitle = "") {
  const meta = getBadgeMeta(status);
  const titleAttr = customTitle || meta.title ? ` title="${esc(customTitle || meta.title)}"` : "";
  return `<span class="status-badge ${meta.cls}"${titleAttr}>${esc(customLabel || meta.text)}</span>`;
}
function resolveFactStatus(fact) {
  if (!fact) return "proposed";
  const factId = fact.id || fact.fact_id;
  if (factId && state.delayedQueue?.has?.(`reject_fact:${factId}`)) {
    return "rejected";
  }
  if (factId) {
    const history = state.data?.review_history || [];
    for (let i = history.length - 1; i >= 0; i -= 1) {
      const item = history[i];
      if (item?.fact_id === factId && item.action !== "confirm_relation") {
        if (item.action === "reject_fact") return "rejected";
        if (item.action === "accept_fact") return "accepted";
        if (item.action === "request_evidence") return "needs_evidence";
        break;
      }
    }
  }
  if (fact.status === "accepted") return "accepted";
  if (!factId) return fact.status || "proposed";
  if ((state.data?.team?.facts || []).some((f) => f?.id === factId && f.status === "accepted")) {
    return "accepted";
  }
  return fact.status || "proposed";
}
function isFactVisuallyCompleted(fact) {
  if (!fact) return false;
  const factId = fact.id || fact.fact_id;
  if (factId && state.delayedQueue?.has?.(`complete_fact:${factId}`)) return true;
  return Boolean(fact.completed || fact.task_state === "completed" || fact.task_state === "reported_complete");
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
  if (key === "project.next_step") return "当前下一步";
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
      <div class="detail-label">新旧版本接替说明</div>
      <p class="drawer-comparison-lead">「${esc(subjectKeyLabel(fact.subject_key))}」已有一条更新确认的新记录，本条旧记录仅作历史保留，当前已不构成未决分歧。</p>
      <div class="drawer-vs-grid">
        <div class="drawer-vs-pane">
          <span class="conflict-stance-label">历史旧记录</span>
          <strong>${esc(oldText)}</strong>
          <small>${esc(fact.author || "记录者")} · ${sourceTimeHTML(fact)}</small>
          <div class="card-pill-row">${evButtons(fact.evidence_ids)}</div>
        </div>
        <div class="drawer-vs-pane is-accepted">
          <div class="conflict-pane-head"><span class="conflict-stance-label">当前生效新版本</span>${renderStatusBadge("accepted", "已确认")}</div>
          <strong>${esc(newText)}</strong>
          <small>${esc(superseder.author || "确认人")} · ${sourceTimeHTML(superseder)}</small>
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
      ? `<button type="button" class="mini-btn accept-btn" data-fact-review-id="${esc(item.id)}">✓ 选这一条</button>`
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
    <div class="detail-label">分歧对照（为什么标为存在分歧？）</div>
    <p class="drawer-comparison-lead">同一「${esc(subjectKeyLabel(fact.subject_key))}」下存在两条不同说法，尚未最终统一：</p>
    <div class="drawer-vs-grid">${paneFor(fact, "方案 A（当前查看）")}${paneFor(other, "方案 B（另一方记录）")}</div>
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
const sourceNote = (fact) => fact.source_state?.status === "superseded" ? "原文件已更新，请核对" : fact.source_state?.status === "unavailable" ? "来源当前不可用，请核对" : "";
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
    const sidecarToken = getSidecarToken();
    let mergedHeaders = fetchOptions.headers;
    if (sidecarToken) {
      if (typeof Headers !== "undefined" && fetchOptions.headers instanceof Headers) {
        const nextHeaders = new Headers(fetchOptions.headers);
        if (!nextHeaders.has("X-Sidecar-Token")) nextHeaders.set("X-Sidecar-Token", sidecarToken);
        mergedHeaders = nextHeaders;
      } else {
        const baseHeaders = { ...(fetchOptions.headers || {}) };
        if (!("X-Sidecar-Token" in baseHeaders) && !("x-sidecar-token" in baseHeaders)) {
          baseHeaders["X-Sidecar-Token"] = sidecarToken;
        }
        mergedHeaders = baseHeaders;
      }
    }
    const response = await fetch(url, {
      cache: "no-store",
      ...fetchOptions,
      ...(mergedHeaders !== undefined ? { headers: mergedHeaders } : {}),
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
        if (state.delayedQueue?.size) await flushDelayedReviews({ keepalive: true });
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
  if (acceptLabel) acceptLabel.textContent = isSolo ? "同时标记为已确认" : "同时确认为项目已确认事项";
  if (acceptWrap) acceptWrap.hidden = Boolean(state.data?.agent_api?.enabled);
  if (!form) return;
  const readOnly = Boolean(state.data?.project?.read_only);
  const sampleMode = Boolean(state.data?.sample_mode);
  const notesDisabled = readOnly || sampleMode;
  form.classList?.toggle?.("is-readonly", notesDisabled);
  if (kindSelect) kindSelect.disabled = notesDisabled || state.quickNotePending;
  if (input) {
    input.disabled = notesDisabled || state.quickNotePending;
    input.placeholder = sampleMode ? "演示样例暂不支持新增随手记（可体验上方按钮与导图）" : readOnly ? "只读历史项目不可写入随手记，请切回当前运行项目" : (isSolo ? "随手记一条想法、前提或待办，自动沉淀可溯源记录…" : "随手记一条想法、前提或待办，先记为个人待确认…");
  }
  if (acceptBox) acceptBox.disabled = notesDisabled || state.quickNotePending;
  if (submitBtn) submitBtn.disabled = notesDisabled || state.quickNotePending;
  if (feedback && notesDisabled && !feedback.textContent) {
    feedback.textContent = sampleMode ? "演示样例不支持新增随手记" : "只读项目不可新增随手记";
  }
}

async function submitQuickNote(event, overrides = {}) {
  event?.preventDefault?.();
  if (state.quickNotePending) return;
  const feedback = document.getElementById("quick-note-feedback");
  if (state.data?.project?.read_only || state.data?.sample_mode) {
    if (feedback) feedback.textContent = state.data?.sample_mode ? "演示样例不支持新增随手记。" : "当前项目为只读模式，不能添加随手记。";
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
  const signerValue = autoAccept
    ? resolveSigner(isSolo, overrides.signer)
    : String(overrides.signer || reviewerInput?.value || readStorage("compass_reviewer_name") || "").trim();
  if (autoAccept && !signerValue) {
    if (feedback) feedback.textContent = "请先在上方填写负责人姓名后再直接确认，或取消勾选仅记为待确认。";
    showCompassToast("请先填写负责人姓名，再直接标记为已确认", { tone: "error" });
    reviewerInput?.focus?.();
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
        ? `已记为待确认（${warn}）`
        : payload?.quick_note?.accepted
          ? `✓ 已记入并确认为${label(kind)}`
          : `✓ 已记为待确认${label(kind)}`;
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

function getClientRoleMap() {
  const map = new Map();
  const clients = state.data?.agent_api?.clients;
  if (Array.isArray(clients)) {
    clients.forEach((client) => {
      if (client?.member_id && client?.role_label) {
        map.set(String(client.member_id), String(client.role_label));
      }
    });
  }
  return map;
}

function renderMemberPicker(members) {
  const picker = document.getElementById("member-picker");
  const select = document.getElementById("member-select");
  const isSolo = effectiveWorkMode() === "solo";
  const roleMap = getClientRoleMap();
  const nonDocMembers = members.filter((member) => member !== "project-documents");
  picker.hidden = state.lens !== "personal" || (isSolo && nonDocMembers.length <= 1);
  select.innerHTML = members.length
    ? members.map((member) => {
        if (member === "project-documents") return `<option value="${esc(member)}">项目材料</option>`;
        const roleLabel = roleMap.get(member);
        return `<option value="${esc(member)}">${esc(roleLabel ? `${member} · ${roleLabel}` : member)}</option>`;
      }).join("")
    : `<option value="">暂无成员数据</option>`;
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
      ? "新项目已就绪 · 对话或随手记下第 1 个目标，思维导图将实时生长。"
      : "项目已就绪 · 接入成员会话后自动记录已确认事项与证据轨迹。";
  }
  const teamFacts = data.team?.facts || [];
  const acceptedCount = teamFacts.filter((f) => resolveFactStatus(f) === "accepted" && sourceCurrent(f)).length;
  const pendingActiveCount = teamFacts.filter((f) => !f.is_historical_doc && ["decision", "assumption", "goal"].includes(f.kind) && !["accepted", "dialogue_decided", "rejected"].includes(resolveFactStatus(f))).length;
  const todoCount = teamFacts.filter((f) => !f.is_historical_doc && f.kind === "task" && !isFactVisuallyCompleted(f) && resolveFactStatus(f) !== "rejected").length;
  return isSolo
    ? `当前 ${acceptedCount} 项已确认 · ${pendingActiveCount} 项待确认 · ${todoCount} 项待办，点击任意节点查看原文。`
    : `双视角共享账本 · ${acceptedCount} 项已确认事项 · ${pendingActiveCount} 项待确认。`;
}

function applyModeLexicon(isSolo, workbenchView) {
  const lexicon = {
    "reviewer-field-tag": isSolo ? "我的署名" : "负责人",
    "toolbar-note": isSolo ? "只留已确认事项 · 待确认不混入正式目标" : "待确认想法需负责人确认 · 原始记录追加保留",
    "lens-personal-btn": isSolo ? "实时纪要 · 待确认想法" : "个人视图",
    "lens-team-btn": "已确认事项",
    "handoff-brief-label": isSolo ? "续写快照" : "交接简报",
    "goal-kicker": "核心目标",
    "hero-copy": computeHeroSummary(isSolo),
    "legend-accepted-title": "已确认依据",
    "legend-accepted-desc": isSolo ? "你已确认的结论与依据关联。" : "负责人已经确认的结论与依据关联。",
    "legend-candidate-desc": isSolo ? "AI 或会话提炼的待确认关联，留待你确认。" : "材料可能支持该结论，仍待确认。",
    "activity-kicker": isSolo ? "会话动态" : "推进动态",
    "personal-todos-kicker": isSolo ? "待办事项" : "待办清单",
    "personal-decisions-kicker": isSolo ? "待确认想法" : "待确认事项",
    "solo-baseline-kicker": "已确认事项",
    "conflict-kicker": isSolo ? "变更与历史" : "分歧对照与历史",
    "review-queue-kicker": isSolo ? "待确认" : "待确认队列",
    "trace-confirm-note": isSolo ? "确认状态单独标记 · 时间顺序不代表因果" : "负责人确认单独标记 · 时间顺序不代表因果",
    "thinking-kicker": isSolo && workbenchView === "mindmap"
      ? "思维导图 · 生长视图"
      : "阶段演进",
  };
  Object.entries(lexicon).forEach(([id, text]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  });
}

function showCompassToast(message, options = {}) {
  const toast = document.getElementById("compass-toast");
  if (!toast) return;
  const text = String(message || "");
  if (state.toastTimer) {
    clearTimeout(state.toastTimer);
    state.toastTimer = null;
  }
  toast.hidden = !text;
  if (!text) {
    state.toastUndoKey = null;
    toast.innerHTML = "";
    toast.textContent = "";
    return;
  }
  state.toastUndoKey = options?.undoKey || null;
  toast.className = `compass-toast${options?.tone === "error" ? " is-error" : ""}`;
  const actions = Array.isArray(options?.actions) ? options.actions.filter((a) => a && a.label) : [];
  if (!actions.length) {
    toast.innerHTML = "";
    toast.textContent = text;
  } else {
    if (toast.dataset) toast.dataset.toastMessage = text;
    const btnsHtml = actions.map((a, idx) => `<button type="button" class="toast-action-btn" data-toast-action-idx="${idx}">${esc(a.label)}</button>`).join("");
    toast.innerHTML = `<span class="toast-msg">${esc(text)}</span>${btnsHtml}<button type="button" class="toast-close-btn" data-toast-close aria-label="关闭提示">×</button>`;
    if (typeof toast.querySelectorAll === "function") {
      toast.querySelectorAll("[data-toast-action-idx]").forEach((btn) => {
        btn.onclick = () => {
          const idx = Number(btn.dataset?.toastActionIdx);
          const act = actions[idx];
          if (act && typeof act.onClick === "function") act.onClick();
        };
      });
      toast.querySelectorAll("[data-toast-close]").forEach((btn) => {
        btn.onclick = () => showCompassToast("");
      });
    }
  }
  const duration = Number.isFinite(options?.durationMs) ? options.durationMs : (actions.length ? 5500 : 4000);
  if (duration > 0) {
    state.toastTimer = makeSafeTimer(() => {
      state.toastTimer = null;
      state.toastUndoKey = null;
      const cur = document.getElementById("compass-toast");
      if (cur) cur.hidden = true;
    }, duration);
  }
}

async function commitDelayedReview(key, commitOptions = {}) {
  const entry = state.delayedQueue?.get?.(key);
  if (!entry || entry.committed) return false;
  entry.committed = true;
  if (entry.timer) clearTimeout(entry.timer);
  state.delayedQueue.delete(key);
  const hadUndoToast = state.toastUndoKey === key;
  if (entry.projectId && state.projectId && entry.projectId !== state.projectId) {
    if (hadUndoToast) showCompassToast("");
    return false;
  }
  try {
    const payload = await apiFetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: entry.action, fact_id: entry.factId, reviewer: entry.reviewer, note: entry.note }),
      ...(commitOptions?.keepalive ? { keepalive: true } : {}),
    });
    if (payload && !olderState(payload)) {
      state.data = payload;
    }
    if (hadUndoToast) {
      if (commitOptions?.keepalive) showCompassToast("已自动提交刚才的操作", { durationMs: 2500 });
      else showCompassToast("");
    }
    render();
    invalidateInvestigation(entry.action === "complete_fact" ? "已标记为完成，请重新查询以使用最新状态。" : "记录状态已更新，请重新查询以使用最新状态。");
    return true;
  } catch (error) {
    render();
    showCompassToast(`操作提交失败：${error.message}`, { tone: "error" });
    return false;
  }
}

function undoDelayedReview(key) {
  const entry = state.delayedQueue?.get?.(key);
  if (!entry) return false;
  if (entry.timer) clearTimeout(entry.timer);
  state.delayedQueue.delete(key);
  render();
  showCompassToast("已撤销，记录已恢复", { durationMs: 2500 });
  return true;
}

function queueDelayedFactReview(factId, action, options = {}) {
  if (state.data?.project?.read_only) {
    showCompassToast("当前项目为只读，无法修改状态", { tone: "error" });
    return;
  }
  const isSolo = effectiveWorkMode() === "solo";
  const reviewer = resolveSigner(isSolo, options?.signer);
  if (!reviewer) {
    showCompassToast("请先填写负责人姓名，再执行操作", { tone: "error" });
    document.getElementById("reviewer-input")?.focus?.();
    return;
  }
  const note = options?.note !== undefined
    ? String(options.note)
    : (options?.fromDrawer ? (document.getElementById("review-note")?.value.trim() || "") : "");
  const key = `${action}:${factId}`;
  const prev = state.delayedQueue.get(key);
  if (prev?.timer) clearTimeout(prev.timer);
  const timer = makeSafeTimer(() => { commitDelayedReview(key); }, 5000);
  state.delayedQueue.set(key, {
    key,
    factId,
    action,
    isWithdraw: Boolean(options?.isWithdraw),
    reviewer,
    note,
    projectId: state.projectId,
    timer,
    committed: false,
  });
  const drawer = document.getElementById("evidence-drawer");
  if (options?.fromDrawer && drawer && !drawer.hidden) {
    closeDrawer();
  }
  render();
  const labelText = action === "complete_fact"
    ? "已标记为完成（5秒内可撤销）"
    : options?.isWithdraw
      ? "已撤回确认，保留原始记录（5秒内可撤销）"
      : "已忽略该条记录，保留原始档案（5秒内可撤销）";
  showCompassToast(labelText, {
    durationMs: 5500,
    undoKey: key,
    actions: [{ label: "撤销", onClick: () => undoDelayedReview(key) }],
  });
}

async function flushDelayedReviews(options = {}) {
  const keys = [...(state.delayedQueue?.keys?.() || [])];
  if (!keys.length) return [];
  const settled = await Promise.allSettled(keys.map((key) => commitDelayedReview(key, options)));
  return settled.map((item) => (item.status === "fulfilled" ? item.value : false));
}

function syncArmedButtons() {
  state.armedKeys ||= new Map();
  const now = Date.now();
  for (const [k, info] of [...state.armedKeys.entries()]) {
    if (!info || info.expiresAt <= now) state.armedKeys.delete(k);
  }
  if (typeof document?.querySelectorAll === "function") {
    document.querySelectorAll("[data-batch-ignore-ids]").forEach((button) => {
      const info = state.armedKeys.get("batch-ignore-stale");
      if (!info) return;
      if (button.dataset) {
        button.dataset.armed = "true";
        button.dataset.origLabel ||= button.textContent || info.origLabel || "";
      }
      button.textContent = info.armedText;
    });
  }
  const clearBtn = typeof document?.getElementById === "function" ? document.getElementById("clear-query-stats") : null;
  const clearInfo = state.armedKeys.get("clear-query-stats");
  if (clearBtn && clearInfo) {
    if (clearBtn.dataset) {
      clearBtn.dataset.armed = "true";
      clearBtn.dataset.origLabel ||= clearBtn.textContent || clearInfo.origLabel || "";
    }
    clearBtn.textContent = clearInfo.armedText;
  }
}

function armConfirmButton(button, armedText, onConfirmed, options = {}) {
  if (!button) return;
  const armKey = options.armKey || button.id || armedText;
  state.armedKeys ||= new Map();
  const existingEntry = state.armedKeys.get(armKey);
  const isArmed = button.dataset?.armed === "true" || Boolean(existingEntry && existingEntry.expiresAt > Date.now());
  if (isArmed) {
    if (button.dataset) button.dataset.armed = "false";
    const existingTimer = state.armTimers.get(armKey);
    if (existingTimer) {
      clearTimeout(existingTimer);
      state.armTimers.delete(armKey);
    }
    state.armedKeys.delete(armKey);
    const restoreLabel = options.origLabel || button.dataset?.origLabel || existingEntry?.origLabel || "";
    if (restoreLabel && button.textContent !== restoreLabel) {
      button.textContent = restoreLabel;
    }
    onConfirmed();
    return;
  }
  const origLabel = button.textContent || "";
  if (button.dataset) {
    button.dataset.armed = "true";
    button.dataset.origLabel = origLabel;
  }
  button.textContent = armedText;
  const existing = state.armTimers.get(armKey);
  if (existing) clearTimeout(existing);
  state.armedKeys.set(armKey, { armedText, origLabel, expiresAt: Date.now() + 3000 });
  const timer = makeSafeTimer(() => {
    state.armTimers.delete(armKey);
    state.armedKeys.delete(armKey);
    const liveBtn = armKey === "clear-query-stats"
      ? (typeof document?.getElementById === "function" ? document.getElementById("clear-query-stats") : button)
      : (armKey === "batch-ignore-stale" && typeof document?.querySelector === "function" ? document.querySelector("[data-batch-ignore-ids]") || button : button);
    if (liveBtn?.dataset) liveBtn.dataset.armed = "false";
    if (liveBtn) liveBtn.textContent = origLabel;
  }, 3000);
  state.armTimers.set(armKey, timer);
}

function formatDispatchBrief(fact) {
  const title = cleanUiText(fact.short_title || fact.clean_value || fact.value || "已确认事项");
  const value = cleanUiText(fact.value || title);
  const evIds = Array.isArray(fact.evidence_ids) ? fact.evidence_ids.filter(Boolean) : [];
  const evLine = evIds.length ? `\n依据编号：${evIds.join("、")}` : "";
  return `【Compass 已确认推进】${title}\n确认内容：${value}${evLine}\n请按此已确认事项执行，不要偏离或回退。`;
}

function decisionActionBar(fact, isSolo, effectiveStatus) {
  if (effectiveStatus === "accepted" || effectiveStatus === "dialogue_decided") {
    const isDialogue = effectiveStatus === "dialogue_decided";
    const confirmBtn = isDialogue && !state.data.project?.read_only
      ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="正式确认为项目核心记录">✓ 确认</button>`
      : "";
    const dispatchBtn = !state.data.project?.read_only
      ? `<button type="button" class="mini-btn dispatch-btn" data-dispatch-fact="${esc(fact.id)}" title="加入待优先处理并发送或复制给 AI">${isDialogue ? "✓ 确认并发给 AI" : "↗ 发给 AI 执行"}</button>`
      : "";
    const withdrawBtn = !state.data.project?.read_only
      ? `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-withdraw-confirmed="true" data-target-id="${esc(fact.id)}" title="从已确认列表中撤回（原始记录仍保留）">✕ 撤回</button>`
      : "";
    const statusBadge = isDialogue
      ? renderStatusBadge("dialogue_decided", "对话已定")
      : renderStatusBadge("accepted", "✓ 已确认");
    return `<span class="in-card-actions">${statusBadge}${confirmBtn}${dispatchBtn}${withdrawBtn}</span>`;
  }
  if (state.data.project?.read_only) return "";
  const acceptBtn = canInlineAcceptFact(fact)
    ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="标记为已确认事项">✓ 确认</button>`
    : "";
  const dispatchBtn = canInlineAcceptFact(fact)
    ? `<button type="button" class="mini-btn dispatch-btn" data-dispatch-fact="${esc(fact.id)}" title="确认后加入待优先处理并发给 AI">✓ 确认并发给 AI</button>`
    : "";
  const rejectBtn = effectiveStatus === "rejected"
    ? ""
    : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="忽略此条记录（5秒内可撤销，原始记录保留）">✕ 忽略</button>`;
  return (acceptBtn || dispatchBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${dispatchBtn}${rejectBtn}</span>` : "";
}

function renderCausalChipStripHTML(fact) {
  const dc = fact?.decision_context;
  if (!dc || typeof dc !== "object") return "";
  const chips = [];
  if (dc.stage === "open_fork" && Array.isArray(dc.alternatives) && dc.alternatives.length) {
    chips.push(`<span class="causal-chip is-fork">多选方案 · ${dc.alternatives.length}项</span>`);
  } else if (dc.stage === "rejected_path") {
    return `<div class="causal-chip-row"><span class="causal-chip is-rejected">已排除方案</span></div>`;
  }
  if (Array.isArray(dc.premises) && dc.premises.length) {
    const prem = dc.premises[0];
    const pCls = prem.status === "verified" ? "is-premise-ok" : prem.status === "invalidated" ? "is-premise-bad" : "is-premise";
    const pText = prem.status === "verified" ? "前提已核实" : prem.status === "invalidated" ? "前提不成立" : "前提待核实";
    chips.push(`<span class="causal-chip ${pCls}">${esc(pText)} · ${esc(truncateUiText(cleanUiText(prem.title || ""), 16))}</span>`);
  }
  if (Array.isArray(dc.rejected_paths) && dc.rejected_paths.length && dc.stage !== "rejected_path") {
    chips.push(`<span class="causal-chip is-rejected">已淘汰对比 · ${dc.rejected_paths.length}项</span>`);
  }
  return chips.length ? `<div class="causal-chip-row">${chips.join("")}</div>` : "";
}

function renderCausalDrawerSectionHTML(fact) {
  const dc = fact?.decision_context;
  if (!dc || typeof dc !== "object") return "";
  const blocks = [];
  if (Array.isArray(dc.alternatives) && dc.alternatives.length) {
    blocks.push(`<div class="detail-block"><div class="detail-label">多个备选方案</div><div class="causal-drawer-group">${dc.alternatives.map((alt) => `<div class="causal-drawer-item">${esc(cleanUiText(alt))}</div>`).join("")}</div></div>`);
  }
  if (dc.stage === "rejected_path" || dc.rejection_reason) {
    const reasonText = dc.rejection_reason ? cleanUiText(dc.rejection_reason) : "已记录为明确排除的路径";
    blocks.push(`<div class="detail-block"><div class="detail-label">已排除方案与原因</div><div class="causal-drawer-item">${esc(reasonText)}</div></div>`);
  }
  if (Array.isArray(dc.premises) && dc.premises.length) {
    blocks.push(`<div class="detail-block"><div class="detail-label">依赖前提条件</div><div class="causal-drawer-group">${dc.premises.map((p) => {
      const tag = p.status === "verified" ? "已核实" : p.status === "invalidated" ? "不成立" : "未验证";
      return `<div class="causal-drawer-item"><strong>[${esc(tag)}]</strong> ${esc(cleanUiText(p.title || ""))} ${renderEvPills(p.evidence_ids)}</div>`;
    }).join("")}</div></div>`);
  }
  if (Array.isArray(dc.rejected_paths) && dc.rejected_paths.length) {
    blocks.push(`<div class="detail-block"><div class="detail-label">关联已淘汰方案</div><div class="causal-drawer-group">${dc.rejected_paths.map((r) => `<div class="causal-drawer-item"><strong>${esc(cleanUiText(r.title || ""))}</strong> · 原因：${esc(cleanUiText(r.reason || "已排除"))} ${renderEvPills(r.evidence_ids)}</div>`).join("")}</div></div>`);
  }
  return blocks.join("");
}

function renderDecisionCardHTML(fact, isSolo) {
  const effectiveStatus = resolveFactStatus(fact);
  const superseder = findSupersedingAcceptedFact(fact);
  const typeTag = fact.kind === "goal"
    ? (effectiveStatus === "accepted" ? "已确认核心目标" : "核心目标候选")
    : fact.kind === "task"
      ? (effectiveStatus === "accepted" ? "已确认行动项" : "待办事项")
      : fact.kind === "decision"
        ? (effectiveStatus === "accepted" ? "已确认方案决定" : effectiveStatus === "dialogue_decided" ? "对话已定方案" : fact.decision_context?.stage === "open_fork" ? "多个备选方案" : fact.decision_context?.stage === "rejected_path" ? "已排除方案" : "待确认方案决定")
        : (fact.decision_context?.premise_status === "verified" || effectiveStatus === "accepted" ? "已核实前提" : fact.decision_context?.premise_status === "invalidated" ? "前提不成立" : "未验证前提");
  const inlineTriage = superseder ? "" : decisionActionBar(fact, isSolo, effectiveStatus);
  const displayTitle = fact.short_title || fact.clean_value || cleanUiText(fact.value);
  const freshCls = state.freshFactIds?.has?.(fact.id) ? " is-fresh-node" : "";
  const statusPill = superseder
    ? renderStatusBadge("superseded", "已有新版本接替")
    : renderStatusBadge(effectiveStatus);
  const subText = superseder
    ? `已被新确认「${truncateUiText(cleanUiText(superseder.short_title || superseder.value), 30)}」接替 · ${fact.evidence_ids?.length || 0} 条依据`
    : `${statusLabel(effectiveStatus)} · ${fact.evidence_ids?.length || 0} 条依据`;
  const conflictHint = superseder ? "" : renderCardConflictHintHTML(fact, isSolo);
  const causalChips = renderCausalChipStripHTML(fact);
  return `<div class="decision-item${freshCls}" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${typeTag}</strong><span>${esc(displayTitle)}</span><small>${esc(subText)}</small>${conflictHint}${causalChips}<div class="card-pill-row">${statusPill}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
}

function openAnchorInlineForm(targetKind, initialText = "") {
  if (state.data?.project?.read_only || state.data?.sample_mode) return;
  const form = document.getElementById("anchor-inline-form");
  const input = document.getElementById("anchor-inline-input");
  const saveBtn = document.getElementById("anchor-inline-save");
  if (!form || !input) return;
  state.anchorEditing = targetKind === "goal" ? "goal" : "next_step";
  form.hidden = false;
  input.value = cleanUiText(initialText);
  input.placeholder = state.anchorEditing === "goal"
    ? "输入一句话核心目标（约10～25字），回车即确认…"
    : "输入一句当前下一步计划，回车即锁定…";
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
  if (state.anchorSaving || !state.anchorEditing || state.data?.project?.read_only || state.data?.sample_mode) return;
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
  const signer = resolveSigner(isSolo);
  if (!signer) {
    showCompassToast("请先填写负责人姓名", { tone: "error" });
    reviewerEl?.focus?.();
    return;
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
    if (noteEl) noteEl.textContent = `保存失败：${error.message}`;
    showCompassToast(`保存失败：${error.message}`, { tone: "error" });
  } finally {
    state.anchorSaving = false;
    if (saveBtn) saveBtn.disabled = false;
  }
}

const hintCategoryLabel = (cat) => ({ "盲区预警": "踩坑提醒", "待定锚点": "还没定目标", "未验前提": "待核实假设", "方案权衡": "方案对比" }[cat] || cat || "提示");

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
    modeEl.textContent = hints.some((h) => h.source === "llm") ? "AI 提醒" : "规则提醒";
  }
  listEl.innerHTML = hints.slice(0, 3).map((hint) => {
    const badgeCls = hint.level === "warn" ? "is-warn" : (hint.source === "llm" ? "is-info" : "is-proposed");
    const evId = (hint.evidence_ids && hint.evidence_ids[0]) ? hint.evidence_ids[0] : "";
    const actionBtn = hint.action_label
      ? `<button type="button" class="mini-btn accept-btn" data-hint-action="${esc(hint.action_kind || "")}" data-hint-fact="${esc(hint.fact_id || "")}" data-hint-ev="${esc(evId)}">${esc(hint.action_label)}</button>`
      : "";
    const evLinks = evId ? renderEvPills([evId]) : "";
    return `<div class="agent-hint-card level-${safeToken(hint.level, "info")}">
      <div class="agent-hint-body">
        <span class="status-badge ${badgeCls}">${esc(hintCategoryLabel(hint.category))}</span>
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
    goalActionBtns.push(`<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(goal.id)}" title="确认为核心目标">✓ 确认为核心目标</button>`);
  }
  if (!state.data?.project?.read_only && !state.data?.sample_mode) {
    const goalSeed = goal ? (goal.short_title || goal.clean_value || cleanUiText(goal.value)) : "";
    goalActionBtns.push(`<button type="button" class="mini-btn" data-anchor-edit="goal" data-anchor-seed="${esc(goalSeed)}">${goal ? "✎ 改写确认" : "✎ 设定目标"}</button>`);
  }
  if (goalActionBtns.length) {
    goalActions.push(`<div class="in-card-actions">${goalActionBtns.join("")}</div>`);
  }
  const goalActionsEl = document.getElementById("goal-actions");
  if (goalActionsEl) goalActionsEl.innerHTML = goalActions.join("");

  const rawNextItem = state.data?.next_consensus || state.data?.handoff_brief?.next_consensus || null;
  const rawNextStatus = rawNextItem ? resolveFactStatus({ id: rawNextItem.fact_id, status: rawNextItem.status }) : "empty";
  const nextCompleted = Boolean(rawNextItem && isFactVisuallyCompleted(rawNextItem));
  const nextItem = (rawNextStatus === "rejected" || nextCompleted) ? null : rawNextItem;
  const nextTitleEl = document.getElementById("next-consensus-title");
  const nextNoteEl = document.getElementById("next-consensus-note");
  const nextStatusEl = document.getElementById("next-consensus-status");
  const nextActionsEl = document.getElementById("next-consensus-actions");

  const resolvedStatus = nextItem ? rawNextStatus : "empty";
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
      nextStatusEl.textContent = "待确认参考";
      nextStatusEl.className = "status-pill status-badge is-proposed";
    } else {
      nextStatusEl.textContent = isNextAccepted ? "已确认 · 下一步" : "待确认 · 下一步";
      nextStatusEl.className = `status-pill status-badge ${isNextAccepted ? "accepted is-accepted" : "is-proposed"}`;
    }
  }
  if (nextNoteEl) {
    if (!nextItem) {
      nextNoteEl.textContent = "历史旧计划不自动当成下一步，点击下方用一句话锁定当前焦点。";
    } else if (nextItem.is_candidate_suggestion) {
      nextNoteEl.textContent = "当前暂无独立下一步任务，暂展示最近一条活跃想法供参考；可直接改写保存。";
    } else {
      nextNoteEl.textContent = isNextAccepted
        ? "已确认为当前下一步 · 完成或更换目标时可随时更新"
        : "待确认下一步工作 · 确认后全站同步对齐";
    }
  }
  if (nextActionsEl) {
    const nextParts = [];
    if (nextItem?.evidence_ids?.length) {
      nextParts.push(`<div class="card-pill-row">${renderEvPills(nextItem.evidence_ids)}</div>`);
    }
    const nextBtns = [];
    if (nextItem && !isNextAccepted && !nextItem.is_candidate_suggestion && nextItem.fact_id && !state.data?.project?.read_only) {
      nextBtns.push(`<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(nextItem.fact_id)}">✓ 确认为下一步</button>`);
    }
    if (nextItem && !nextItem.is_candidate_suggestion && nextItem.fact_id && !state.data?.project?.read_only) {
      nextBtns.push(`<button type="button" class="mini-btn" data-inline-review="complete_fact" data-target-id="${esc(nextItem.fact_id)}" title="标记这项已完成，不再当成当前下一步">✓ 标记已完成</button>`);
    }
    if (!state.data?.project?.read_only && !state.data?.sample_mode) {
      const nextSeed = nextItem ? (nextItem.short_title || nextItem.clean_value || cleanUiText(nextItem.value)) : "";
      nextBtns.push(`<button type="button" class="mini-btn" data-anchor-edit="next_step" data-anchor-seed="${esc(nextSeed)}">${nextItem ? "✎ 改写确认" : "✎ 设定下一步"}</button>`);
    }
    if (nextBtns.length) nextParts.push(`<div class="in-card-actions">${nextBtns.join("")}</div>`);
    nextActionsEl.innerHTML = nextParts.join("");
  }

  const inlineForm = document.getElementById("anchor-inline-form");
  if (inlineForm) {
    inlineForm.hidden = !state.anchorEditing || Boolean(state.data?.project?.read_only || state.data?.sample_mode);
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

function snapshotOpenDetailsState() {
  state.openDetails ||= new Set();
  if (typeof document.querySelectorAll !== "function") return;
  document.querySelectorAll("details[data-details-key]").forEach((el) => {
    const key = el.dataset?.detailsKey;
    if (!key) return;
    if (el.open) state.openDetails.add(key);
    else state.openDetails.delete(key);
  });
}

function restoreOpenDetailsState() {
  if (!state.openDetails?.size || typeof document.querySelectorAll !== "function") return;
  document.querySelectorAll("details[data-details-key]").forEach((el) => {
    const key = el.dataset?.detailsKey;
    if (key && state.openDetails.has(key)) el.open = true;
  });
}

function getCurrentEvidenceList() {
  if (!state.data) return [];
  const view = activeView();
  const facts = view.facts || [];
  const factIds = new Set(facts.map((fact) => fact.id));
  const sourceIds = new Set(view.evidence_ids || []);
  facts.forEach((fact) => [...(fact.evidence_ids || []), ...(fact.source_state?.replacement_ids || []), ...(fact.source_state?.observation_ids || [])].forEach((id) => sourceIds.add(id)));
  (state.data.confirmed_relations || []).filter((relation) => factIds.has(relation.fact_id)).forEach((relation) => sourceIds.add(relation.evidence_id));
  const catalog = state.data.evidence || [];
  return state.lens === "team" ? catalog : catalog.filter((item) => sourceIds.has(item.id));
}

function renderEvidenceSpine() {
  const spineEl = document.getElementById("evidence-spine");
  if (!spineEl || !state.data) return;
  const evidence = getCurrentEvidenceList();
  const query = state.evidenceQuery.trim().toLowerCase();
  const visibleEvidence = query ? evidence.filter((item) => `${item.id} ${item.content_preview} ${item.search_excerpt || ""} ${item.command_preview || ""} ${item.source_ref || ""} ${item.author || ""}`.toLowerCase().includes(query)) : evidence;
  const spineCountEl = document.getElementById("spine-count");
  if (spineCountEl) spineCountEl.textContent = query ? `${visibleEvidence.length}/${evidence.length}` : evidence.length;
  const filterEl = document.getElementById("evidence-filter");
  if (filterEl && filterEl.value !== state.evidenceQuery) filterEl.value = state.evidenceQuery;
  const evidencePageSize = 50;
  const renderedEvidence = visibleEvidence.slice(0, evidencePageSize);
  const hiddenEvidenceCount = visibleEvidence.length - renderedEvidence.length;
  const evidenceLimitNote = hiddenEvidenceCount > 0
    ? `<p class="empty">当前显示 ${renderedEvidence.length} 条，另有 ${hiddenEvidenceCount} 条可继续缩小筛选；完整原文可从过程层来源打开。</p>`
    : "";
  spineEl.innerHTML = renderedEvidence.length
    ? renderedEvidence.map(evidenceCard).join("") + evidenceLimitNote
    : `<p class="empty">没有匹配的原始记录。</p>`;
  wireEvidenceTargets(spineEl);
}

function render() {
  if (!state.data) return;
  snapshotOpenDetailsState();
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
      ? "实时思维导图 · 点击任意节点查看原文或确认"
      : "待确认想法与已确认事项分栏核对 · 支持随手记与一键确认";
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
  reviewer.placeholder = isSolo ? "我的署名（自动记忆）" : "填写姓名后可确认事项";
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
    guidance.innerHTML = `<span>${lead}${extractionEnabled ? (isSolo ? "可以启动一批候选整理，结果仍需你确认。" : "可以启动一批候选整理，结果仍需负责人确认。") : "当前服务未启用候选整理，请用 --enable-extraction 重启。"}</span>${extractionEnabled ? '<button type="button" id="guidance-extract">整理一批新材料</button>' : ""}`;
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
  const liveActiveGoals = facts.filter((fact) => fact.kind === "goal" && fact.author !== "project-documents" && sourceCurrent(fact) && resolveFactStatus(fact) !== "rejected");
  const allCurrentGoals = facts.filter((fact) => fact.kind === "goal" && sourceCurrent(fact));
  const allActiveGoals = allCurrentGoals.filter((fact) => resolveFactStatus(fact) !== "rejected");
  const activeFallbackGoal = state.lens === "personal" && view.fallback_goal && resolveFactStatus(view.fallback_goal) !== "rejected" ? view.fallback_goal : null;
  const personalGoal = acceptedGoals[acceptedGoals.length - 1] || liveActiveGoals[liveActiveGoals.length - 1] || allActiveGoals[allActiveGoals.length - 1] || null;
  const goal = personalGoal || activeFallbackGoal || allCurrentGoals[allCurrentGoals.length - 1] || (state.lens === "personal" ? view.fallback_goal : null) || null;

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
  document.getElementById("evidence-kicker").textContent = state.lens === "team" ? "已确认事项依据" : state.member === "project-documents" ? "项目材料档案" : (isSolo ? "实时行动记录" : "个人证据链");
  const goalEffectiveStatus = goal ? resolveFactStatus(goal) : "proposed";
  const isGoalAccepted = Boolean(goal && goalEffectiveStatus === "accepted");
  const goalBadgeMeta = getBadgeMeta(goalEffectiveStatus);

  document.getElementById("goal-title").textContent = goal ? (goal.short_title || goal.clean_value || cleanUiText(goal.value)) : "暂未设定核心目标";
  document.getElementById("goal-note").textContent = goal
    ? `${isGoalAccepted ? "已确认为核心目标" : (isSolo ? "待确认目标想法 · 尚未确认" : "待确认目标 · 尚未经负责人确认")} · ${goal.evidence_ids?.length || 0} 条依据 · ${sourceTimeText(goal)}${isGoalAccepted ? "" : " · 当前有效性待确认"}`
    : state.data.project?.fact_count ? "请在下方或思维导图确认核心目标，或在随手记补全一条。" : "记一条随手记或用助手记下第 1 个目标，思维导图会自动生长。";
  const goalStatusEl = document.getElementById("goal-status");
  goalStatusEl.textContent = isGoalAccepted
    ? "已确认 · 核心目标"
    : goalEffectiveStatus === "rejected"
      ? "已忽略"
      : `${statusLabel(goalEffectiveStatus)} · 待确认`;
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
  if (scopeTag) scopeTag.textContent = state.lens === "team" ? "已确认事项范围" : (isSolo ? "当前项目范围" : "个人视图范围");
  renderSessionPresence();
  renderTimelineAndThinkingLine(view, facts);
  const activeChapter = (view.timeline_chapters || []).find((ch) => ch.chapter_id === state.activeChapterId);
  const chapterFactSet = activeChapter ? new Set(activeChapter.fact_ids || []) : null;
  const filterByChapter = (items) => chapterFactSet ? items.filter((item) => chapterFactSet.has(item.id || item.fact_id)) : items;
  document.getElementById("facts-kicker").textContent = state.lens === "team" ? "已确认事项" : state.member === "project-documents" ? "项目材料提取" : "待确认与近期记录";
  document.getElementById("facts-count").textContent = facts.length;
  document.getElementById("spine-count").textContent = query ? `${visibleEvidence.length}/${evidence.length}` : evidence.length;
  document.getElementById("metrics").innerHTML = [
    metric(facts.length, state.lens === "team" ? "已确认记录" : state.member === "project-documents" ? "材料记录" : (isSolo ? "个人记录" : "个人待确认")),
    metric(tasks, "待办事项"),
    metric(candidates, "待确认关联"),
    metric((state.data.team?.facts || []).filter((fact) => fact.status === "accepted" && sourceCurrent(fact)).length, "已确认事项"),
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
    const accepted = effectiveStatus === "accepted" || effectiveStatus === "dialogue_decided";
    const rejected = effectiveStatus === "rejected";
    const isCompleted = isFactVisuallyCompleted(fact);
    let inlineTriage = "";
    if (accepted) {
      const dispatchBtn = !state.data.project?.read_only && !isCompleted
        ? `<button type="button" class="mini-btn dispatch-btn" data-dispatch-fact="${esc(fact.id)}" title="加入待优先处理并发送或复制给 AI">${effectiveStatus === "dialogue_decided" ? "✓ 确认并发给 AI" : "↗ 发给 AI 执行"}</button>`
        : "";
      const completeBtn = !state.data.project?.read_only && !isCompleted
        ? `<button type="button" class="mini-btn" data-inline-review="complete_fact" data-target-id="${esc(fact.id)}" title="标记已完成（5秒内可撤销）">✓ 标记已完成</button>`
        : "";
      const withdrawBtn = !state.data.project?.read_only
        ? `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-withdraw-confirmed="true" data-target-id="${esc(fact.id)}" title="从已确认列表中撤回">✕ 撤回</button>`
        : "";
      const doneBadge = renderStatusBadge(isCompleted ? "completed" : effectiveStatus, isCompleted ? "✓ 已完成" : (effectiveStatus === "dialogue_decided" ? "对话已定" : "✓ 已确认"));
      inlineTriage = `<span class="in-card-actions">${doneBadge}${completeBtn}${dispatchBtn}${withdrawBtn}</span>`;
    } else if (!state.data.project?.read_only && !isCompleted) {
      const acceptBtn = canInlineAcceptFact(fact) ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="标记为已确认">✓ 确认</button>` : "";
      const dispatchBtn = canInlineAcceptFact(fact) ? `<button type="button" class="mini-btn dispatch-btn" data-dispatch-fact="${esc(fact.id)}" title="确认后加入待优先处理，同时发给 AI">✓ 确认并发给 AI</button>` : "";
      const rejectBtn = rejected ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="忽略此待办（5秒内可撤销）">✕ 忽略</button>`;
      inlineTriage = (acceptBtn || dispatchBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${dispatchBtn}${rejectBtn}</span>` : "";
    }
    const freshCls = state.freshFactIds?.has?.(fact.id) ? " is-fresh-node" : "";
    const statusText = statusLabel(effectiveStatus);
    const conflictHint = renderCardConflictHintHTML(fact, isSolo);
    return `<div class="todo-item${freshCls}" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${isCompleted ? "☑" : "☐"} ${esc(fact.short_title || fact.clean_value || cleanUiText(fact.value))}</strong><span>进度：${isCompleted ? "已完成" : esc(taskStateLabel(fact.task_state))} · ${esc(statusText)} · ${fact.evidence_ids?.length || 0} 条依据</span>${conflictHint}<div class="card-pill-row">${renderStatusBadge(effectiveStatus)}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
  };
  const supersededOpen = state.openDetails?.has?.("superseded-todos") ? " open" : "";
  const supersededHTML = supersededTodos.length
    ? `<details class="superseded-todos-fold" data-details-key="superseded-todos"${supersededOpen}><summary>历史已接替记录（${supersededTodos.length} 条 · 默认折叠）</summary><div class="superseded-todos-list">${supersededTodos.map(({ fact, superseder }) => {
        const supTitle = truncateUiText(cleanUiText(superseder.short_title || superseder.value), 34);
        return `<div class="todo-item is-superseded-todo" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>☐ ${esc(fact.short_title || fact.clean_value || cleanUiText(fact.value))}</strong><span>已被新确认「${esc(supTitle)}」接替 · ${fact.evidence_ids?.length || 0} 条依据</span><div class="card-pill-row">${renderStatusBadge("superseded", "已有新版本接替")}${renderEvPills(fact.evidence_ids)}</div></div>`;
      }).join("")}</div></details>`
    : "";
  document.getElementById("personal-todo-list").innerHTML = activeTodos.length
    ? activeTodos.map(renderTodoCard).join("") + supersededHTML
    : (supersededHTML || `<p class="empty">${isSolo ? "暂无待办事项，可在上方随手记选择「待办事项」添加。" : "当前成员暂无待办。"}</p>`);
  const evidenceRequests = state.lens === "personal" ? (state.data.evidence_requests || []).filter((request) => request.member_id === state.member) : [];
  document.getElementById("personal-evidence-requests").hidden = state.lens !== "personal" || evidenceRequests.length === 0;
  document.getElementById("evidence-request-count").textContent = evidenceRequests.length;
  document.getElementById("evidence-request-list").innerHTML = evidenceRequests.length ? evidenceRequests.map((request) => `<button type="button" class="evidence-request-item" data-fact-id="${esc(request.fact_id)}"><strong>${esc(request.value)}</strong><span>${request.status === "ready_for_review" ? "已有新依据，可重新核对" : "等待补充依据"} · ${request.new_evidence_ids?.length || 0} 条新增 · ${esc(request.note || (isSolo ? "待补充验证依据" : "负责人未填写说明"))}</span></button>`).join("") : `<p class="empty">当前成员没有待补证据任务。</p>`;
  const allDecisions = state.lens === "personal" ? filterByChapter(facts.filter((fact) => fact.kind === "decision" || fact.kind === "assumption")) : [];
  document.getElementById("personal-decisions").hidden = state.lens !== "personal";
  const decisionsCountEl = document.getElementById("personal-decisions-count");
  if (isSolo) {
    const pendingItems = allDecisions.filter((fact) => {
      const st = resolveFactStatus(fact);
      if (st === "accepted" || st === "dialogue_decided" || st === "rejected") return false;
      if (isFactVisuallyCompleted(fact)) return false;
      if (fact.superseded_by_fact_id || fact.decision_context?.stage === "rejected_path") return false;
      if (findSupersedingAcceptedFact(fact)) return false;
      return true;
    });
    const newestPendingTs = pendingItems.reduce((mx, f) => Math.max(mx, factEffectiveTimestamp(f)), 0);
    const staleCutoffMs = 72 * 3600 * 1000;
    const activePending = [];
    const stalePending = [];
    pendingItems.forEach((fact) => {
      const ts = factEffectiveTimestamp(fact);
      if (newestPendingTs > 0 && ts > 0 && newestPendingTs - ts > staleCutoffMs) {
        stalePending.push(fact);
      } else {
        activePending.push(fact);
      }
    });
    const pendingDecs = activePending.filter((fact) => fact.kind === "decision");
    const pendingAssumps = activePending.filter((fact) => fact.kind === "assumption");
    if (decisionsCountEl) decisionsCountEl.textContent = activePending.length;
    const sections = [];
    if (pendingDecs.length) {
      sections.push(`<div class="decision-group"><h3 class="decision-group-head">待确认方案决定 (${pendingDecs.length})</h3>${pendingDecs.map((fact) => renderDecisionCardHTML(fact, true)).join("")}</div>`);
    }
    if (pendingAssumps.length) {
      sections.push(`<div class="decision-group"><h3 class="decision-group-head">未验证前提 (${pendingAssumps.length})</h3>${pendingAssumps.map((fact) => renderDecisionCardHTML(fact, true)).join("")}</div>`);
    }
    if (stalePending.length) {
      const staleOpen = state.openDetails?.has?.("stale-pending") ? " open" : "";
      const batchBtn = !state.data.project?.read_only
        ? `<div class="in-card-actions"><button type="button" class="mini-btn reject-btn" data-batch-ignore-ids="${esc(stalePending.map((f) => f.id).join(","))}">✕ 一键全部忽略（${stalePending.length} 条）</button></div>`
        : "";
      sections.push(`<details class="superseded-todos-fold stale-pending-fold" data-details-key="stale-pending"${staleOpen}><summary>更早未处理（${stalePending.length} 条 · 超过 72 小时）</summary><div class="superseded-todos-list">${batchBtn}${stalePending.map((fact) => renderDecisionCardHTML(fact, true)).join("")}</div></details>`);
    }
    document.getElementById("personal-decision-list").innerHTML = sections.length
      ? sections.join("")
      : `<p class="empty">当前没有待确认想法或未验证前提 · 已确认事项见下方，或用上方随手记快速新增。</p>`;
  } else {
    if (decisionsCountEl) decisionsCountEl.textContent = allDecisions.length;
    document.getElementById("personal-decision-list").innerHTML = allDecisions.length
      ? allDecisions.map((fact) => renderDecisionCardHTML(fact, false)).join("")
      : `<p class="empty">当前成员暂无方案决定或未验证前提。</p>`;
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
        .filter((fact) => ["accepted", "dialogue_decided"].includes(resolveFactStatus(fact)) && sourceCurrent(fact))
        .sort((a, b) => (kindRank[a.kind] ?? 9) - (kindRank[b.kind] ?? 9));
      if (baselineCount) baselineCount.textContent = baselineFacts.length;
      baselineList.innerHTML = baselineFacts.length
        ? baselineFacts.map((fact) => renderDecisionCardHTML(fact, true)).join("")
        : `<p class="empty">尚无已确认事项 · 可在上方卡片点击「✓ 确认」或在随手记勾选「同时标记为已确认」。</p>`;
    }
  }
  const dispatchSurface = document.getElementById("priority-dispatch-surface");
  const dispatchList = document.getElementById("priority-dispatch-list");
  const dispatchCount = document.getElementById("priority-dispatch-count");
  if (dispatchSurface && dispatchList) {
    const dispatches = Array.isArray(state.data?.priority_dispatches) ? state.data.priority_dispatches : [];
    dispatchSurface.hidden = dispatches.length === 0;
    if (dispatchCount) dispatchCount.textContent = dispatches.length;
    dispatchList.innerHTML = dispatches.length
      ? dispatches.map((item) => `<div class="decision-item priority-dispatch-item"><strong>⚡ ${esc(item.title || "待优先处理事项")}</strong><span>${esc(item.value || "")}</span><small>发送人：${esc(item.actor || "owner")} · ${esc(formatTime(item.observed_at))}</small><div class="card-pill-row">${renderEvPills(item.evidence_ids)}</div></div>`).join("")
      : "";
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
          const acceptBtn = allowAccept && qStatus !== "accepted" ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(item.fact_id)}" title="标记为已确认">✓ 确认</button>` : "";
          const rejectBtn = qStatus === "rejected"
            ? ""
            : qStatus === "accepted" || qStatus === "dialogue_decided"
              ? `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-withdraw-confirmed="true" data-target-id="${esc(item.fact_id)}" title="撤回确认">✕ 撤回</button>`
              : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(item.fact_id)}" title="忽略">✕ 忽略</button>`;
          inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
        }
        return `<div class="review-queue-item" role="button" tabindex="0" data-fact-id="${esc(item.fact_id)}">${renderStatusBadge(item.status, item.status === "conflicted" ? "存在分歧" : item.status === "needs_evidence" ? "待补证据" : "待确认")}<span class="review-queue-main"><strong>${esc(item.value)}</strong><small>${esc(item.reason)} · ${esc(item.author || "作者未提供")} · ${item.evidence_count} 条证据 · ${item.candidate_relation_count} 条待确认关联</small><span class="card-pill-row">${renderEvPills(qFact?.evidence_ids)}</span>${inlineTriage}</span></div>`;
      }).join("")
    : `<p class="empty">${isSolo ? "当前没有待确认条目。" : "当前没有待负责人确认的事项。"}</p>`;
  document.getElementById("fact-list").innerHTML = facts.length ? facts.map((fact) => factCard(fact, relations)).join("") : `<p class="empty">当前视图还没有结构化记录。原始记录仍可在下方查看。</p>`;
  renderTrace(facts, relations, evidence);
  renderDirections(view.directions || {candidates:[],current:[],history:[]}, state.lens === "team");
  renderReasonPreview();
  renderTeamHistory();
  renderEvidenceSpine();
  document.querySelectorAll(".lens").forEach((button) => button.classList.toggle("active", button.dataset.lens === state.lens));
  renderMemberPicker(Object.keys(state.data.personal || {}));
  bindDynamicControls();
  restoreOpenDetailsState();
  state.hasRenderedOnce = true;
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
    const intakePart = !sample && intake?.enabled ? `已同步对话 ${intake.captured_messages || 0} 条` : "";
    const parts = [intakePart, hhmm ? `同步 ${hhmm}` : ""].filter(Boolean);
    syncEl.hidden = parts.length === 0;
    syncEl.textContent = parts.length ? `· ${parts.join(" · ")}` : "";
  }
  document.getElementById("intake-bar").hidden = !sample && !intake?.enabled && !api?.enabled && !ruleScan?.enabled && !userScan?.enabled;
  document.getElementById("refresh-intake").hidden = sample;
  if (sample) {
    document.getElementById("intake-status").textContent = "合成样例供试用。包含两名成员和一组冲突，审核仅保存在独立样例工作区，不代表真实项目验收或赞助服务已连接。";
    return;
  }
  const clientLabels = (api?.clients || []).map((c) => (c?.role_label ? `${c.member_id}(${c.role_label})` : c?.member_id)).filter(Boolean);
  const apiNote = api?.enabled ? `Agent HTTP 已启用 · ${api.clients?.length || 0} 个 Agent 席位${clientLabels.length ? `（${clientLabels.join("、")}）` : ""}可提交证据与候选。` : '';
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

function bindInvestigationBanner(panel) {
  if (!panel || typeof panel.querySelectorAll !== "function") return;
  panel.querySelectorAll("[data-rerun-investigate]").forEach((btn) => {
    btn.onclick = () => investigateProject({ preventDefault() {} });
  });
  panel.querySelectorAll("[data-dismiss-stale]").forEach((btn) => {
    btn.onclick = () => {
      const banner = panel.querySelector?.(".investigation-stale-banner");
      if (banner?.remove) banner.remove();
      else panel.innerHTML = String(panel.innerHTML || "").replace(/<div class="investigation-stale-banner"[\s\S]*?<\/div>\s*/i, "");
    };
  });
}

function invalidateInvestigation(message) {
  state.revision += 1;
  const panel = document.getElementById("investigation-answer");
  if (!panel) return;
  const raw = String(panel.innerHTML || "");
  const hasAnswer = !panel.hidden && (
    raw.includes("answer-key-takeaways") ||
    raw.includes("answer-semantic-summary") ||
    raw.includes("answer-conclusion")
  );
  if (hasAnswer) {
    const banner = `<div class="investigation-stale-banner" role="status"><span>${esc(message)}</span><span class="investigation-stale-actions"><button type="button" class="mini-btn accept-btn" data-rerun-investigate>重新查询</button><button type="button" class="icon-button" data-dismiss-stale aria-label="收起提示">×</button></span></div>`;
    if (typeof panel.insertAdjacentHTML === "function") {
      const oldBanner = panel.querySelector?.(".investigation-stale-banner");
      if (oldBanner?.remove) oldBanner.remove();
      else panel.innerHTML = raw.replace(/<div class="investigation-stale-banner"[\s\S]*?<\/div>\s*/i, "");
      panel.insertAdjacentHTML("afterbegin", banner);
      bindInvestigationBanner(panel);
      wireEvidenceTargets(panel);
      return;
    }
    const cleaned = raw.replace(/<div class="investigation-stale-banner"[\s\S]*?<\/div>\s*/i, "");
    panel.innerHTML = banner + cleaned;
    bindInvestigationBanner(panel);
    wireEvidenceTargets(panel);
    bindDynamicControls();
    return;
  }
  const wasLoading = raw.includes("正在按证据链调查");
  if (wasLoading || !panel.hidden) panel.hidden = false;
  panel.innerHTML = `<p class="empty">${esc(message)}</p>`;
}

async function refreshNative(options = {}) {
  if (!state.data || state.data.sample_mode === true || state.data.project?.read_only || state.refreshing) return;
  state.refreshing = true;
  const refreshBtn = document.getElementById("refresh-intake");
  if (refreshBtn) refreshBtn.disabled = true;
  try {
    const useRefresh = state.data.intake?.refreshable !== false && Boolean(state.data.intake?.enabled || state.data.intake?.direction_scan?.enabled || state.data.intake?.user_task_scan?.enabled);
    const supportsDelta = typeof state.data.intake?.refreshable === "boolean" && Number.isInteger(state.data.state_version);
    const deltaQuery = (options?.backgroundPoll === true && supportsDelta)
      ? `?since_version=${encodeURIComponent(state.data.state_version)}`
      : "";
    const payload = useRefresh
      ? await apiFetch(`/api/refresh${deltaQuery}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
      : await apiFetch(`/api/state${deltaQuery}`, { background: true });
    if (olderState(payload)) return;
    const prevHintSig = `${state.data.hint_generation || 0}:${(state.data.agent_hints || []).map((h) => h.id).join(",")}`;
    const nextHintSig = `${payload.hint_generation || 0}:${(payload.agent_hints || []).map((h) => h.id).join(",")}`;
    if (payload?.unchanged === true) {
      if (payload.intake) state.data.intake = payload.intake;
      if (payload.project_scan) state.data.project_scan = payload.project_scan;
      if (payload.extraction) state.data.extraction = payload.extraction;
      if (payload.llm_status) state.data.llm_status = payload.llm_status;
      renderIntake();
      renderExtraction();
      if (nextHintSig !== prevHintSig) {
        state.data.agent_hints = payload.agent_hints;
        state.data.hint_generation = payload.hint_generation;
        renderAgentHints(effectiveWorkMode() === "solo");
        bindDynamicControls();
      }
      return;
    }
    const prevActSig = `${state.data.activity_stream?.[0]?.id || ""}:${state.data.activity_stream?.length || 0}`;
    const nextActSig = `${payload.activity_stream?.[0]?.id || ""}:${payload.activity_stream?.length || 0}`;
    const evidenceChanged = payload.project.evidence_count !== state.data.project.evidence_count;
    const reviewChanged = (payload.review_history?.length || 0) !== (state.data.review_history?.length || 0);
    const dispatchChanged = (payload.priority_dispatches?.length || 0) !== (state.data.priority_dispatches?.length || 0);
    const candidatesChanged = payload.project.fact_count !== state.data.project.fact_count;
    const projectSwitched = Boolean(payload.project?.project_id && state.data.project?.project_id && payload.project.project_id !== state.data.project.project_id);
    const versionChanged = payload.state_version !== state.data.state_version;
    const activityChanged = prevActSig !== nextActSig;
    if (projectSwitched || evidenceChanged || reviewChanged || dispatchChanged || candidatesChanged || versionChanged || activityChanged) {
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
      let discardedPendingCount = 0;
      if (projectSwitched && payload.project?.project_id) {
        if (state.delayedQueue?.size) {
          discardedPendingCount = state.delayedQueue.size;
          for (const queued of state.delayedQueue.values()) {
            if (queued?.timer) clearTimeout(queued.timer);
          }
          state.delayedQueue.clear();
          if (state.toastUndoKey) showCompassToast("");
        }
        state.projectId = payload.project.project_id;
        state.activeWorkspaceUri = payload.project.path || state.activeWorkspaceUri;
        state.evidenceCache = Object.create(null);
      }
      render();
      if (projectSwitched) {
        showCompassToast?.(discardedPendingCount ? "检测到工作区切换，已自动同步当前项目（已取消旧项目未提交的延时操作）" : "检测到工作区切换，已自动同步当前项目");
      }
      invalidateInvestigation(projectSwitched ? "检测到工作区切换，请重新提问以使用新项目状态。" : candidatesChanged ? "新候选已更新，原始材料和负责人确认记录保留，请重新提问。" : evidenceChanged ? payload.intake?.new_tool_records ? "已接入工具记录，原有事实与确认历史保留，请重新提问。" : "已接入新消息。原有事实与确认记录保留，新材料需提取后再重新调查。" : "项目状态或负责人确认记录已更新，请重新提问以使用最新状态。");
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

const directionLabel = (value) => ({abandoned:'已放弃',deferred:'已暂缓',active:'已恢复推进'}[value] || '状态待确认');
const directionCandidateLabel = (value) => ({abandoned:'放弃表述',deferred:'暂缓表述'}[value] || '状态待确认');
function directionStateText(fact) {
  const current=(state.data?.team?.directions?.current || []).find((row)=>row.fact_id===fact.id);
  return current ? `方向状态：${directionLabel(current.direction_state)} · 保留原始表述` : '';
}
function directionFindingMeta(item) {
  if (!item.direction_state) return '';
  return `<p class="${item.status === 'accepted' ? 'reviewed-note' : 'meta-note'}">${esc(item.status === 'proposed' ? directionCandidateLabel(item.direction_state) : directionLabel(item.direction_state))} · ${item.status === 'proposed' ? '待确认方向' : item.current ? '当前确认' : '历史确认'} · 下方保留原始表述</p>`;
}

function renderDirections(directions, isTeam) {
  const surface = document.getElementById("direction-surface");
  if (!surface) return;
  const isSolo = effectiveWorkMode() === "solo";
  const current = directions.current || [], history = directions.history || [];
  const rows = isTeam ? current.filter((row) => row.direction_state !== "active") : directions.candidates || [];
  document.getElementById("direction-title").textContent = isTeam ? "舍弃与暂缓方向" : "方向状态待确认";
  document.getElementById("direction-count").textContent = rows.length;
  document.getElementById("direction-note").textContent = isTeam
    ? (isSolo ? "清单仅收录你明确确认的方向。恢复及旧状态保留在下方历史。" : "清单仅收录负责人明确确认的方向。恢复及旧状态保留在下方历史。")
    : "明确表述仍需确认后才生效。未被采用的建议不会自动归为已放弃。";
  const entry = (row, historical = false) => `<div class="direction-entry"><div class="detail-label">${esc(!isTeam && row.status === "proposed" ? directionCandidateLabel(row.direction_state) : directionLabel(row.direction_state))} · ${historical ? (row.current ? "当前确认" : "历史确认") : isTeam ? "已确认" : "待确认"}</div><button type="button" class="direction-open" data-fact-id="${esc(row.fact_id)}">${esc(row.quote)}</button><p class="meta-note">${esc(row.member_id || "")} · ${sourceTimeHTML(row)}</p>${row.reviewed_by ? `<p class="reviewed-note">${esc(row.reviewed_by)} · ${esc(formatTime(row.reviewed_at))}</p>` : ""}<div>${(row.evidence_ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("")}</div>${sourceNote(row) ? `<p class="source-warning">${esc(sourceNote(row))}</p>` : ""}</div>`;
  document.getElementById("direction-list").innerHTML = rows.length ? rows.map((row) => entry(row)).join("") : `<p class="empty">${isTeam ? "尚无当前已确认的放弃或暂缓方向。" : "尚无可归类的明确方向表述。可继续查看待确认事项和原始来源。"}</p>`;
  document.getElementById("direction-history").innerHTML = isTeam && history.length ? `<div class="history-label">方向状态历史 · ${history.length}</div>${history.map((row) => entry(row, true)).join("")}` : "";
}

function reasonPreviewHTML(preview) {
  const isSolo = effectiveWorkMode() === "solo";
  const rows = preview?.candidates || [], gaps = preview?.gaps || [];
  const links = (ids) => (ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("");
  const target = (row) => `<button type="button" class="reason-target" data-fact-id="${esc(row.target_fact_id)}">对应陈述 · ${esc(row.target_quote)}</button>`;
  const quotes = (items, qLabel) => !items?.length ? "" : `<details class="reason-sources"><summary>${esc(qLabel)} · ${items.length}</summary>${items.map((q) => `<div class="detail-block"><p class="meta-note">${esc(q.member_id)} · ${esc(claimLabel(q.claim_type))} · ${esc(q.reported_by)} · ${sourceTimeHTML(q)}</p><pre class="reason-quote">${esc(q.quote)}</pre>${links([q.source_id])}</div>`).join("")}</details>`;
  return `<p class="empty">${isSolo ? "仅供参考 · 待你确认。引文匹配仅核对出处，原因联系仍需复核。" : "仅供参考 · 待负责人确认。引文匹配仅核对出处，原因联系仍需复核。"}</p>${preview?.unavailable_targets ? `<p class="source-warning">${esc(preview.unavailable_targets)} 项目标或来源已变化，相关预览暂未展示。</p>` : ""}${rows.map((row) => `<article class="reason-card"><div class="detail-label">${row.relation_type_suggested === "hypothesized_reason" ? "系统推测原因" : "来源说明待确认"} · 待确认</div>${target(row)}<p class="detail-value">${esc(row.summary)}</p>${row.assumptions?.length ? `<div class="reason-assumptions"><strong>前提条件</strong>${row.assumptions.map((a) => `<p>${esc(a)}</p>`).join("")}</div>` : ""}${quotes(row.source_quotes, "原文引文")}${quotes(row.counter_evidence, "反向或替代线索")}<p class="meta-note">生成模型 ${esc(row.model || "")}</p></article>`).join("")}${gaps.map((gap) => `<div class="reason-gap">${target(gap)}<p class="detail-label">所选材料中的缺证说明</p><p class="detail-value">${esc(gap.text)}</p>${links(gap.scope_source_ids)}</div>`).join("")}${!rows.length && !gaps.length ? '<p class="empty">当前问题或视图没有匹配的原因说明，可继续核对原始材料。</p>' : ""}`;
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
  const scopeLabel = answer.scope ? (isSolo ? "个人记录" : "成员记录") : (isSolo ? "核心目标" : "核心目标");
  const basis = answer.next_action_basis;
  const actionLabel = answer.next_action_status === "accepted" ? "已确认下一步" : basis ? "待确认下一步" : "下一步动作";
  const basisHTML = basis ? `<div class="detail-block"><p class="meta-note">${sourceTimeHTML(basis)} · ${esc(basis.member_id || "")} · ${esc(claimLabel(basis.claim_type))}</p>${basis.status === "accepted" ? `<p class="reviewed-note">${esc(basis.reviewed_by || "owner")} · ${sourceTimeHTML({observed_at: basis.reviewed_at}, "确认时间")}</p>` : '<p class="source-warning">待确认来源的当前版本需核对，历史任务不会自动成为当前确认。</p>'}${evidenceLinks(basis.evidence_ids || [])}</div>` : "";
  const conflicts = answer.conflicts || [];
  const sourceWarnings = Array.isArray(answer.source_warnings) ? answer.source_warnings : [];
  const acceptedWarnCount = sourceWarnings.filter((item) => item?.status === "accepted").length;
  const goalUpdatedBadge = acceptedWarnCount > 0 ? '<span class="status-badge is-warn">原文件已更新</span>' : "";
  const displayGoal = cleanUiText(answer.goal);
  const shortGoal = truncateUiText(displayGoal, 64);
  const displayNextAction = cleanUiText(answer.next_action);
  const hasSettledNext = answer.next_action_status === "accepted";
  const nextBadgeStatus = hasSettledNext ? "accepted" : (answer.next_action_status || (basis ? "proposed" : "info"));
  const nextBadgeText = hasSettledNext ? "已确认" : (basis ? "待确认" : "指引");
  const hasEmptyNext = !displayNextAction || /尚未提取|暂未设定|未找到/.test(displayNextAction);
  const editNextBtn = (!state.data?.project?.read_only && hasEmptyNext)
    ? '<button type="button" class="mini-btn accept-btn" data-anchor-edit="next_step" data-anchor-seed="">✎ 设定下一步</button>'
    : "";

  const summaryHTML = answer.semantic_summary
    ? `<div class="answer-semantic-summary"><span class="status-badge is-accepted">智能摘要</span><p>${esc(cleanUiText(answer.semantic_summary))}</p></div>`
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

const _relationMapCache = new WeakMap();

function relationsByFactId(relations) {
  if (!Array.isArray(relations) || relations.length === 0) return new Map();
  let cached = _relationMapCache.get(relations);
  if (cached) return cached;
  cached = new Map();
  for (const relation of relations) {
    const fid = relation?.fact_id;
    if (!fid) continue;
    let bucket = cached.get(fid);
    if (!bucket) {
      bucket = [];
      cached.set(fid, bucket);
    }
    bucket.push(relation);
  }
  _relationMapCache.set(relations, cached);
  return cached;
}

function buildTraceGroups(facts, relations, catalog, reviews, teamFacts) {
  const sources = new Map(catalog.map((item) => [item.id, item]));
  const team = new Map(teamFacts.map((fact) => [fact.id, fact]));
  const relByFact = relationsByFactId(relations);
  const acceptedByFact = new Map();
  for (const review of reviews || []) {
    if (review?.action !== 'accept_fact' || !review?.fact_id) continue;
    let list = acceptedByFact.get(review.fact_id);
    if (!list) {
      list = [];
      acceptedByFact.set(review.fact_id, list);
    }
    list.push(review);
  }
  const groups = new Map();
  const timestamp = (record) => hasSourceTime(record) ? new Date(record.observed_at).getTime() : Infinity;
  for (const fact of facts) {
    const subject = fact.subject_key || fact.id;
    if (!groups.has(subject)) groups.set(subject, {subject, facts: [], time: Infinity, latestTime: -Infinity});
    const related = relByFact.get(fact.id) || [];
    const ids = [...new Set([...(fact.evidence_ids || []), ...related.map((relation) => relation.evidence_id)])];
    const citations = ids.filter((id) => sources.has(id)).map((id) => ({source: sources.get(id),
      confirmed: related.some((relation) => relation.evidence_id === id && relation.status === 'confirmed')}));
    const accepted = acceptedByFact.get(fact.id) || [];
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
      <div class="trace-sources">${shownCitations.map(({source, confirmed}) => `<div class="trace-citation"><button class="trace-source" data-evidence-id="${esc(source.id)}"><span class="fact-kind">原始来源</span><span class="trace-copy">${esc(source.content_preview || source.id)}</span><span class="trace-meta">${esc(source.author || '作者未提供')} · ${esc(source.kind || '来源记录')}</span><span class="trace-meta">${sourceTimeHTML({...source, source_kind: source.kind})}</span></button><div class="trace-wire ${confirmed ? 'confirmed' : 'candidate'}"><span>${confirmed ? '支持关系已确认' : '引用关联待确认'}</span></div></div>`).join('')}
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
  const note = ids.length ? "关联测试记录退出码为 0（仅证明该次执行记录通过，请点击上方证据核对覆盖范围）" : "关联测试曾通过，但未附带可溯源测试证据 ID";
  return `<div class="detail-block"><div class="detail-label">校验与证据关联</div><div class="detail-value">${esc(note)}</div>${pills}</div>`;
}

function factCard(fact, relations) {
  const related = relationsByFactId(relations).get(fact.id) || [];
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
    ? `<div class="card-conflict-digest is-superseded">已被新确认「${esc(truncateUiText(cleanUiText(superseder.short_title || superseder.value), 32))}」接替</div>`
    : renderCardConflictHintHTML(fact, effectiveWorkMode() === "solo");
  const badgeHtml = superseder
    ? renderStatusBadge("superseded", "已有新版本接替")
    : renderStatusBadge(currentStatus);
  const causalChips = renderCausalChipStripHTML(fact);
  return `<div class="fact-card" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><div class="fact-main"><div class="fact-kind">${esc(label(fact.kind))}${verifiedBadge}</div><div class="fact-value">${esc(fact.value)}</div><div class="fact-meta">${esc(claimLabel(fact.claim_type))}${author} · ${related.length} 条关联</div><div class="fact-meta">${sourceTimeHTML(fact)}${effectiveStatus === 'accepted' || superseder ? '' : ' · 当前有效性待确认'}</div>${conflictHint}${causalChips}${directionStateText(fact) ? `<div class="fact-meta">${esc(directionStateText(fact))}</div>` : ''}${sourceNote(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 原记录保留</p>` : ""}</div>${badgeHtml}</div>`;
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
    const recHTML = rec ? `<div class="conflict-speculative-rec"><strong>系统参考建议:</strong> ${esc(rec.hypothetical_resolution || rec.recommended_value)}${recVerified} <span class="rec-meta">(${esc(rec.confidence)} 置信度 · ${esc(rec.score ?? "")}分，${isSolo ? "以你的最终选择为准" : "最终以负责人确认为准"})</span></div>` : "";
    const sideCards = sides.map((side, idx) => {
      const recBadge = side.speculative_status === "recommended" ? renderStatusBadge("recommended", "系统推荐") : "";
      const verifiedBadge = renderSpeculativeBadge(side);
      const matchedFact = teamFacts.find((f) => f.id === side.fact_id || (f.subject_key === conflict.subject_key && f.value === side.value && f.author === side.author));
      const sideStatus = resolveFactStatus(matchedFact || (side.fact_id ? { id: side.fact_id, status: side.status } : side));
      const inlineBtn = matchedFact && sideStatus !== "accepted" && canInlineAcceptFact(matchedFact)
        ? `<div class="conflict-pane-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(matchedFact.id)}" title="选择并确认此方案">✓ 选这一条 (${String.fromCharCode(65 + idx)})</button></div>`
        : "";
      const sideTag = `<span class="conflict-stance-label">方案 ${String.fromCharCode(65 + idx)}</span>`;
      const divider = idx === 0 && sides.length > 1 ? `<div class="conflict-vs-divider" aria-hidden="true"><span>VS</span></div>` : "";
      const paneClass = sideStatus === "accepted" ? "is-accepted" : sideStatus === "rejected" ? "is-rejected" : sideStatus === "needs_evidence" ? "is-needs-evidence" : "is-conflicted";
      return `<article class="conflict-side-pane ${paneClass}"><div class="conflict-pane-head">${sideTag}${renderStatusBadge(sideStatus)}${recBadge}${verifiedBadge}</div><div class="conflict-pane-value">${esc(side.value)}</div><div class="conflict-meta">${esc(side.author || "unknown")} · ${sourceTimeHTML(side)}</div><div class="card-pill-row">${renderEvPills(side.evidence_ids)}</div>${inlineBtn}</article>${divider}`;
    }).join("");
    return `<div class="conflict-card"><div class="conflict-card-head"><span class="conflict-key">${esc(conflict.subject_key)}</span><span class="conflict-count-tag">${sides.length} 处说法不一致 · 原文同时保留</span></div>${recHTML}<div class="conflict-vs-grid">${sideCards}</div></div>`;
  }).join("") : `<p class="empty">当前没有前后分歧记录。</p>`;
  const actionLabels = {
    accept_fact: "确认事项",
    confirm_relation: "确认依据关联",
    confirm_abandoned: "确认放弃方向",
    confirm_deferred: "确认暂缓方向",
    restore_direction: "恢复方向",
    reject_fact: "忽略 / 撤回",
    request_evidence: "标记待补证据",
    complete_fact: "标记已完成",
  };
  document.getElementById("history-list").innerHTML = history.length ? `<div class="history-label">${isSolo ? "操作记录" : "确认历史"}</div>${history.map((entry) => `<div class="history-item"><strong>${esc(actionLabels[entry.action] || entry.action)}</strong><span>${esc(entry.value || entry.fact_id || entry.relation_id || "")} · ${esc(entry.reviewer || "owner")} · ${entry.evidence_ids?.length || 0} 条证据 · ${esc(formatTime(entry.observed_at))}${entry.evidence_request_id ? " · 已处理补证请求" : ""}${entry.resolved_relation_ids?.length ? ` · ${entry.resolved_relation_ids.length} 条关联已确认` : ""}${entry.note ? ` · ${esc(entry.note)}` : ""}</span></div>`).join("")}` : "";
}

function renderEvPills(ids) {
  const validAll = (ids || []).filter(Boolean);
  if (!validAll.length) return "";
  const shown = validAll.slice(0, 4);
  const pills = shown.map((id, idx) => `<span class="ev-pill" role="button" tabindex="0" data-evidence-id="${esc(id)}" title="悬停预览原文，点击查看出处 (${esc(id)})">依据 · ${idx + 1}</span>`).join("");
  const extra = validAll.length > 4
    ? `<span class="ev-pill ev-pill-overflow" title="共 ${validAll.length} 条依据，点击卡片查看全部">+${validAll.length - 4}</span>`
    : "";
  return pills + extra;
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
    revBadge.textContent = `${reversals.length} 处原文件已更新，请核对`;
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

  const root = thinking.root || { label: "核心目标待确定", status: "empty", evidence_ids: [] };
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
    const kindText = b.kind === "assumption" ? "未验证前提" : b.causal_stage === "rejected_path" ? "已排除方案" : "方案决定";
    const tagText = b.causal_stage === "rejected_path" ? "已排除" : b.state === "abandoned" ? "已放弃" : b.state === "deferred" ? "已暂缓" : branchStatus === "accepted" ? "已确认" : branchStatus === "dialogue_decided" ? "对话已定" : "待确认";
    const causalChips = [];
    if (b.causal_stage === "open_fork" && (b.fork_count || 0) >= 2) {
      causalChips.push(`<span class="causal-chip is-fork">多选 · ${esc(b.fork_count)}</span>`);
    }
    if (b.premise_state === "invalidated") {
      causalChips.push('<span class="causal-chip is-premise-bad">前提不成立</span>');
    } else if (b.premise_state === "unverified") {
      causalChips.push('<span class="causal-chip is-premise">前提待核实</span>');
    } else if (b.premise_state === "verified") {
      causalChips.push('<span class="causal-chip is-premise-ok">前提已核实</span>');
    }
    const causalChipsHTML = causalChips.join("");
    const canQuickAccept = Boolean(b.fact_id && !state.data?.project?.read_only && branchStatus !== "accepted" && !isDropped && (isSolo || state.lens === "team"));
    const quickAction = canQuickAccept
      ? `<div class="thinking-branch-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(b.fact_id)}">✓ 确认</button></div>`
      : "";
    const childrenHTML = (b.children || []).length
      ? `<div class="thinking-children">${b.children.map((child) => {
          const done = isFactVisuallyCompleted(child);
          const leafFresh = state.freshFactIds?.has?.(child.fact_id) ? " is-fresh-node" : "";
          return `<div class="thinking-leaf ${done ? "leaf-done" : ""}${leafFresh}" ${child.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(child.fact_id)}"` : ""} title="${esc(child.full_label || child.label)}">
            <span class="leaf-check">${done ? "☑" : "☐"}</span>
            <span class="leaf-label">${esc(child.label)}</span>
            ${renderEvPills(child.evidence_ids)}
          </div>`;
        }).join("")}</div>`
      : `<div class="thinking-children thinking-children-empty"><span class="thinking-leaf-hint">${esc(codeNodes.length ? "关联下方代码模块 · 点击节点查看原文" : "尚无拆分子任务")}</span></div>`;
    return `<div class="thinking-branch-row ${stateClass}">
      <div class="thinking-branch-card">
        <div class="thinking-branch-node" ${b.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(b.fact_id)}"` : ""} title="${esc(b.full_label || b.label)}">
          <span class="branch-icon">${icon}</span>
          <span class="branch-kind-chip">${kindText}</span>
          <span class="branch-tag ${stateClass}">${tagText}</span>
          <strong class="branch-label">${esc(b.label)}</strong>
          ${causalChipsHTML}
          ${renderEvPills(b.evidence_ids)}
        </div>
        ${quickAction}
      </div>
      ${childrenHTML}
    </div>`;
  }).join("") : `<div class="thinking-branch-row branch-proposed"><div class="thinking-branch-card"><div class="thinking-branch-node"><span class="branch-icon">◆</span><span class="branch-tag">等待提炼</span><strong class="branch-label">记一条随手记或同步对话后，这里将实时长出分支</strong></div></div></div>`;

  const codeFooter = codeNodes.length ? `<div class="thinking-code-strip"><span class="code-strip-label">⧉ 关联代码：</span>${codeNodes.map((n) => `<span class="code-node-pill ${n.direct ? "direct" : ""}" title="${esc(n.source_ref || "")}">${esc(n.label)}</span>`).join("")}</div>` : "";
  const archive = thinking.historical_archive || {};
  const archiveItems = Array.isArray(archive.items) ? archive.items : [];
  const archiveOpen = state.openDetails?.has?.("historical-archive") ? " open" : "";
  const archiveHTML = archiveItems.length
    ? `<details class="historical-archive-capsule" data-details-key="historical-archive"${archiveOpen}>
        <summary><span>▤ ${esc(archive.label || `历史文档参考（${archiveItems.length} 条）`)}</span><span class="archive-toggle-hint">默认折叠 · 点击展开核对</span></summary>
        <div class="historical-archive-list">${archiveItems.map((item) => `<button type="button" class="historical-archive-item" ${item.fact_id ? `data-fact-id="${esc(item.fact_id)}"` : ""} title="${esc(item.full_label || item.label)}"><strong>${esc(item.label)}</strong><small>${esc(item.source_ref || "项目文档")}</small></button>`).join("")}</div>
      </details>`
    : "";
  const rootStatusTag = rootStatus === "accepted" ? "已确认目标" : rootStatus === "empty" ? "待设定" : "待确认核心目标";
  const rootFresh = state.freshFactIds?.has?.(root.fact_id) ? " is-fresh-node" : "";

  canvasEl.innerHTML = `<div class="thinking-tree mindmap-layout">
    <div class="thinking-root ${rootStatus === "accepted" ? "accepted" : "proposed"}${rootFresh}" ${root.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(root.fact_id)}"` : ""} title="${esc(root.full_label || root.label)}">
      <span class="thinking-root-kicker">核心目标 · ${rootStatusTag}</span>
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
  const freshnessText = isUnavailable ? "● 暂不可用" : isSuperseded ? "● 已有新版本接替" : "● 当前有效";

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
  const rawPresence = state.data?.session_presence;
  const apiClients = state.data?.agent_api?.enabled ? (state.data.agent_api.clients || []) : [];
  if (!rawPresence && !apiClients.length) {
    container.innerHTML = "";
    return;
  }
  const presence = rawPresence || { team: { accepted_count: 0, pending_count: 0 }, members: [] };
  const isTeamActive = state.lens === "team";
  const teamPending = Number(presence.team?.pending_count) || 0;
  const teamAccepted = Number(presence.team?.accepted_count) || 0;

  const teamBadgeClass = teamAccepted > 0 ? "accepted-count" : "zero-count";
  const teamPill = `<button type="button" class="presence-pill ${isTeamActive ? 'active' : ''}" data-target-lens="team" title="切换到已确认事项视图"><span class="presence-name">已确认事项</span><span class="presence-badge ${teamBadgeClass}" title="${teamAccepted} 条已确认事项">${teamAccepted}</span>${teamPending > 0 ? `<span class="presence-badge pending-count" title="${teamPending} 条待确认">${teamPending} 待确认</span>` : ''}</button>`;

  const roleMap = getClientRoleMap();
  const seenMembers = new Set();
  const mergedMembers = [];
  (presence.members || []).forEach((m) => {
    if (m?.member_id) {
      seenMembers.add(m.member_id);
      mergedMembers.push(m);
    }
  });
  (state.data?.agent_api?.clients || []).forEach((c) => {
    if (c?.member_id && !seenMembers.has(c.member_id)) {
      seenMembers.add(c.member_id);
      mergedMembers.push({
        member_id: c.member_id,
        label: c.member_id,
        is_agent_session: true,
        pending_count: 0,
      });
    }
  });

  const memberPills = mergedMembers.map((m) => {
    const isMemberActive = state.lens === "personal" && state.member === m.member_id;
    const pulseClass = m.is_agent_session ? "agent-pulse" : "agent-pulse doc";
    const mPending = Number(m.pending_count) || 0;
    const roleLabel = roleMap.get(m.member_id) || "";
    const roleBadge = roleLabel ? `<span class="presence-role">${esc(roleLabel)}</span>` : "";
    const statusTag = mPending > 0
      ? `<span class="presence-badge pending-count" title="${mPending} 条待确认">${mPending}</span>`
      : `<span class="presence-badge zero-count" title="无待确认">✓</span>`;
    const pillTitle = roleLabel ? `切换到 ${m.label}（${roleLabel}）视图` : `切换到 ${m.label} 视图`;
    return `<button type="button" class="presence-pill ${isMemberActive ? 'active' : ''}" data-target-lens="personal" data-target-member="${esc(m.member_id)}" title="${esc(pillTitle)}"><span class="${pulseClass}"></span><span class="presence-name">${esc(m.label)}</span>${roleBadge}${statusTag}</button>`;
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
      ? "汇总当前已确认事项、待确认想法与下一步待办，方便跨会话续写"
      : "汇集当前已确认事项、待确认记录与下一步行动清单";
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
      : `<p class="empty">暂无已确认事项。</p>`;

    const candHTML = candidates.length
      ? `<ul class="brief-item-list">${candidates.map(c => `<li class="brief-item"><strong>${esc(cleanUiText(c.value))} <small>(${esc(c.author)})</small></strong><span class="card-pill-row">${renderStatusBadge(briefStatus(c))}${renderEvPills(c.evidence_ids)}</span></li>`).join("")}</ul>`
      : `<p class="empty">${isSolo ? "当前无待确认想法（待办已单列下方）。" : "当前无未决会话待确认（已与行动清单合并）。"}</p>`;

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
        <div class="brief-section-title"><span>1. 已确认事项</span><span class="count">${decisions.length} 条</span></div>
        ${decHTML}
      </section>
      <section class="brief-section">
        <div class="brief-section-title"><span>2. 待确认想法</span><span class="count">${candidates.length} 条</span></div>
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
      } else if (action === "open_fact" && factId) {
        openFact(factId);
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
      const action = button.dataset.inlineReview;
      const targetId = button.dataset.targetId;
      if (action === "reject_fact" || action === "complete_fact") {
        queueDelayedFactReview(targetId, action, {
          fromDrawer: false,
          isWithdraw: button.dataset.withdrawConfirmed === "true",
        });
      } else {
        acceptFact(targetId, action, { fromDrawer: false });
      }
    };
    button.onkeydown = (event) => {
      if (event?.key === "Enter" || event?.key === " ") {
        event.stopPropagation?.();
      }
    };
  });
  document.querySelectorAll("[data-batch-ignore-ids]").forEach((button) => {
    button.onclick = (event) => {
      event?.stopPropagation?.();
      event?.preventDefault?.();
      const ids = button.dataset.batchIgnoreIds || "";
      const count = ids ? ids.split(",").filter(Boolean).length : 0;
      armConfirmButton(button, `再次点击确认忽略（${count} 条）`, () => {
        batchIgnoreFacts(ids);
      }, { armKey: "batch-ignore-stale" });
    };
  });
  syncArmedButtons();
  document.querySelectorAll("details[data-details-key]").forEach((el) => {
    el.ontoggle = () => {
      const key = el.dataset?.detailsKey;
      if (!key) return;
      state.openDetails ||= new Set();
      if (el.open) state.openDetails.add(key);
      else state.openDetails.delete(key);
    };
  });
  document.querySelectorAll("[data-dispatch-fact]").forEach((button) => {
    button.onclick = (event) => {
      event?.stopPropagation?.();
      event?.preventDefault?.();
      dispatchFact(button.dataset.dispatchFact, { fromDrawer: false });
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
        const hit = event.target.closest("[data-inline-review], [data-dispatch-fact], [data-evidence-id], button, a, input, textarea");
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

function bindDrawerControls() {
  const drawer = document.getElementById("evidence-drawer");
  if (!drawer || typeof drawer.querySelectorAll !== "function") return;
  drawer.querySelectorAll("[data-review-id]").forEach((button) => {
    button.onclick = () => confirmRelation(button.dataset.reviewId, button.dataset.factId);
  });
  drawer.querySelectorAll("[data-fact-review-id]").forEach((button) => {
    button.onclick = () => acceptFact(button.dataset.factReviewId, button.dataset.reviewAction || "accept_fact", { fromDrawer: true });
  });
  drawer.querySelectorAll("[data-dispatch-fact]").forEach((button) => {
    button.onclick = () => dispatchFact(button.dataset.dispatchFact, { fromDrawer: true });
  });
  drawer.querySelectorAll("[data-dispatch-fact-target]").forEach((button) => {
    button.onclick = () => dispatchFact(button.dataset.factId, {
      fromDrawer: true,
      sidecarTarget: button.dataset.dispatchFactTarget,
    });
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
      await acceptFact(pending.factId, pending.action, {
        fromDrawer: pending.fromDrawer,
        signer: signerName,
        note: pending.note,
      });
    } else if (pending.type === "dispatch_fact") {
      await dispatchFact(pending.factId, {
        fromDrawer: pending.fromDrawer,
        signer: signerName,
        sidecarTarget: pending.sidecarTarget,
        note: pending.note,
      });
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
  const isSettled = effectiveStatus === "accepted" || effectiveStatus === "dialogue_decided";
  const rejectBtn = effectiveStatus === "rejected"
    ? ""
    : isSettled
      ? `<button type="button" class="review-action reject-btn" data-fact-review-id="${esc(fact.id)}" data-review-action="reject_fact">✕ 撤回确认</button>`
      : `<button type="button" class="review-action reject-btn" data-fact-review-id="${esc(fact.id)}" data-review-action="reject_fact">✕ 忽略此条</button>`;
  const requestBtn = effectiveStatus === "needs_evidence" || effectiveStatus === "accepted" ? "" : `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}" data-review-action="request_evidence">要求补证据</button>`;
  const reviewActions = canConfirmHere && !superseder ? `${effectiveStatus !== "accepted" ? `<label class="review-note-label" for="review-note">备注说明（可选）</label><textarea id="review-note" class="review-note-input" rows="2" placeholder="补充确认备注或忽略原因"></textarea>` : ""}${rejectBtn}${requestBtn}` : "";
  const confirmLabel = effectiveStatus === "dialogue_decided" ? "✓ 正式确认为核心事项" : "✓ 确认";
  const inSidecar = hasSidecarBridge();
  const canSidecarSend = inSidecar && typeof window.sidecar?.agent?.sendMessage === "function";
  const canSidecarNew = inSidecar && typeof window.sidecar?.agent?.startConversation === "function";
  const dispatchBtn = !state.data.project?.read_only && !superseder && sourceCurrent(fact) && effectiveStatus !== "rejected"
    ? `<button type="button" class="review-action dispatch-btn" data-dispatch-fact="${esc(fact.id)}">${effectiveStatus === "accepted" ? "↗ 发给 AI 执行" : "✓ 确认并发给 AI"}</button>`
    : "";
  const sidecarDispatchBtns = dispatchBtn
    ? `${canSidecarSend ? `<button type="button" class="review-action sidecar-dispatch-btn" data-dispatch-fact-target="send" data-fact-id="${esc(fact.id)}">立即发入当前对话</button>` : ""}${canSidecarNew ? `<button type="button" class="review-action sidecar-dispatch-btn" data-dispatch-fact-target="new" data-fact-id="${esc(fact.id)}">新开窗口专办</button>` : ""}`
    : "";
  const fullDispatchBtns = `${dispatchBtn}${sidecarDispatchBtns}`;
  const acceptAction = state.data.project?.read_only ? `<p class="empty">当前项目为只读模式，确认操作请回到该项目的运行窗口。</p>` : superseder ? `<p class="meta-note">本条旧记录已被更新的确认接替，仅作历史保留。</p>` : !sourceCurrent(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 请核对当前来源。原确认与证据仍保留。</p>` : canConfirmHere && directionAction ? `${directionAction}${fullDispatchBtns}` : canConfirmHere && effectiveStatus !== "accepted" ? `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}">${confirmLabel}</button>${fullDispatchBtns}${reviewActions}` : `${fullDispatchBtns}${reviewActions}`;
  const verifiedBlock = renderSpeculativeDetail(fact);
  const causalDrawerBlock = renderCausalDrawerSectionHTML(fact);
  const displayStatusText = superseder ? "已有新版本接替" : statusLabel(effectiveStatus);
  const drawerTitle = cleanUiText(fact.short_title || fact.clean_value || fact.value);
  openDrawer(drawerTitle, `${comparisonBlock}${causalDrawerBlock}<div class="detail-block"><div class="detail-value">${sourceTimeHTML(fact)}</div><p class="${isSettled ? "reviewed-note" : "meta-note"}">${esc(fact.author || "记录者")} · ${effectiveStatus === "accepted" ? "已确认，来源版本仍可核对" : effectiveStatus === "dialogue_decided" ? "已在对话中明确同意" : superseder ? "已有新版本接替" : "当前有效性待确认"}</p></div><div class="detail-block"><div class="detail-label">当前状态与归属</div><div class="detail-value">${esc(displayStatusText)} · 归属：${esc(subjectKeyLabel(fact.subject_key))}</div>${acceptAction}</div>${verifiedBlock}<div class="detail-block"><div class="detail-label">依据关联</div>${relations.length ? relations.map((relation) => `<div class="relation-item"><button type="button" class="evidence-item" data-evidence-id="${esc(relation.evidence_id)}"><span class="evidence-dot ${relation.status === "confirmed" ? "fact_source" : "execution_result"}"></span><span><span class="evidence-title">${esc(relation.basis)}</span><span class="evidence-meta">${esc(relationMethodLabel(relation.method))} · ${esc(statusLabel(relation.status))} · ${relation.score == null ? "评分未知" : `匹配度 ${esc(relation.score)}`}</span></span><span class="evidence-links">打开</span></button>${relation.status === "candidate" ? (state.data.project?.read_only ? `<span class="meta-note">只读模式，关联关系待主项目确认</span>` : `<button type="button" class="review-action" data-review-id="${esc(relation.id)}" data-fact-id="${esc(fact.id)}">确认支持关系</button>`) : `<span class="reviewed-note">关联已确认</span>`}</div>`).join("") : `<p class="empty">暂未提出关联关系。</p>`}</div><div class="detail-block"><div class="detail-label">依据原文</div><div class="card-pill-row">${ids.map((eid) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(eid)}">${esc(eid)}</button>`).join("") || "证据缺口"}</div></div><details class="answer-footnotes raw-meta-fold"><summary>底层技术字段（排障核对用 · 默认折叠）</summary><div class="meta-note">记录编号：${esc(fact.id)} · 会话标识：${esc(fact.session_id || "未提供")} · 位置键：${esc(fact.subject_key || "")}</div></details>`);
}

async function batchIgnoreFacts(rawIds) {
  if (state.data?.project?.read_only || state.batchIgnorePending) return;
  const ids = String(rawIds || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (!ids.length) return;
  const isSolo = effectiveWorkMode() === "solo";
  const reviewer = resolveSigner(isSolo);
  if (!reviewer) {
    showCompassToast("请先填写负责人姓名，再批量忽略", { tone: "error" });
    document.getElementById("reviewer-input")?.focus?.();
    return;
  }
  state.batchIgnorePending = true;
  let latest = null;
  let succeeded = 0;
  let skipped = 0;
  let failed = 0;
  let lastErrorMsg = "";
  try {
    for (const factId of ids) {
      try {
        const payload = await apiFetch("/api/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "reject_fact", fact_id: factId, reviewer, note: "超过72小时批量忽略" }),
        });
        if (payload && !olderState(payload)) latest = payload;
        succeeded += 1;
      } catch (err) {
        const msg = String(err?.message || "");
        if (msg.includes("already has this review status")) {
          skipped += 1;
        } else {
          failed += 1;
          lastErrorMsg = msg;
        }
      }
    }
  } finally {
    state.batchIgnorePending = false;
    if (latest && !olderState(latest)) {
      state.data = latest;
      render();
      invalidateInvestigation("已批量忽略更早未处理条目，原始记录仍保留在档案中。");
    }
    if (failed === 0 && (succeeded > 0 || skipped > 0)) {
      showCompassToast?.(`已忽略 ${succeeded + skipped} 条更早记录（新忽略 ${succeeded} 条）`);
    } else if (succeeded > 0 || skipped > 0) {
      showCompassToast?.(`已忽略 ${succeeded} 条，另有 ${failed} 条失败：${lastErrorMsg || "请重试"}`, { tone: "error" });
    } else if (failed > 0) {
      showCompassToast?.(`批量忽略失败：${lastErrorMsg || "请重试"}`, { tone: "error" });
    }
  }
}

const inFlightReviewIds = new Set();

async function acceptFact(factId, action = "accept_fact", options = {}) {
  if (!factId || inFlightReviewIds.has(factId)) return;
  if (state.data.project?.read_only) {
    showCompassToast("当前项目为只读，不能修改状态", { tone: "error" });
    return;
  }
  const isSolo = effectiveWorkMode() === "solo";
  const note = options?.note !== undefined
    ? String(options.note)
    : (options?.fromDrawer ? (document.getElementById("review-note")?.value.trim() || "") : "");
  const reviewer = resolveSigner(isSolo, options?.signer);
  if (!reviewer) {
    showCompassToast("请先填写负责人姓名，再确认事项", { tone: "error" });
    document.getElementById("reviewer-input")?.focus?.();
    return;
  }
  inFlightReviewIds.add(factId);
  const matchingBtns = typeof document.querySelectorAll === "function"
    ? [...document.querySelectorAll("[data-inline-review]")].filter((btn) => btn.dataset?.targetId === factId)
    : [];
  matchingBtns.forEach((btn) => { btn.disabled = true; });
  try {
    const payload = await apiFetch("/api/review", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({action, fact_id: factId, reviewer, note})});
    if (olderState(payload)) return;
    state.data = payload;
    render();
    invalidateInvestigation(action === "complete_fact" ? "已标记为完成，请重新查询以使用最新状态。" : "确认状态已更新，请重新查询以使用最新状态。");
    if (action === "complete_fact") {
      showCompassToast?.("已标记为完成，不再作为当前下一步");
    } else if (action === "accept_fact") {
      showCompassToast?.("✓ 已确认，已加入已确认事项", {
        actions: [{ label: "撤回", onClick: () => acceptFact(factId, "reject_fact", { signer: reviewer }) }],
      });
    } else if (action === "reject_fact") {
      showCompassToast?.("已从当前列表中移除，原始记录仍保留在档案中");
    }
    const drawer = document.getElementById("evidence-drawer");
    if (options?.fromDrawer || (drawer && !drawer.hidden)) {
      openFact(factId);
    }
  } catch (error) {
    showCompassToast(`操作失败：${error.message}`, { tone: "error" });
  } finally {
    inFlightReviewIds.delete(factId);
    matchingBtns.forEach((btn) => {
      if (btn.isConnected) btn.disabled = false;
    });
  }
}

async function dispatchFact(factId, options = {}) {
  if (!factId || inFlightReviewIds.has(factId)) return;
  if (state.data?.project?.read_only) {
    showCompassToast("当前项目为只读，不能加入待优先处理", { tone: "error" });
    return;
  }
  const teamFact = (state.data?.team?.facts || []).find((item) => item.id === factId);
  const personalFact = (state.data?.personal?.[state.member]?.facts || []).find((item) => item.id === factId);
  const fact = state.lens === "team" ? (teamFact || personalFact) : (personalFact || teamFact);
  if (!fact) return;
  const isSolo = effectiveWorkMode() === "solo";
  const effectiveStatus = resolveFactStatus(fact);
  const reviewNote = options?.note !== undefined
    ? String(options.note)
    : (options?.fromDrawer ? (document.getElementById("review-note")?.value.trim() || "") : "");
  const reviewer = resolveSigner(isSolo, options?.signer);
  if (effectiveStatus !== "accepted" && !reviewer) {
    showCompassToast("确认并发给 AI 前，请先在工具栏填写负责人姓名", { tone: "error" });
    document.getElementById("reviewer-input")?.focus?.();
    return;
  }
  inFlightReviewIds.add(factId);
  const matchingBtns = typeof document.querySelectorAll === "function"
    ? [
        ...[...document.querySelectorAll("[data-dispatch-fact]")].filter((btn) => btn.dataset?.dispatchFact === factId),
        ...[...document.querySelectorAll("[data-inline-review]")].filter((btn) => btn.dataset?.targetId === factId),
      ]
    : [];
  matchingBtns.forEach((btn) => { btn.disabled = true; });
  try {
    if (effectiveStatus !== "accepted") {
      const reviewPayload = await apiFetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "accept_fact", fact_id: factId, reviewer, note: reviewNote }),
      });
      if (reviewPayload && !olderState(reviewPayload)) {
        state.data = reviewPayload;
      }
    }
    const inSidecar = hasSidecarBridge();
    const sidecarTarget = String(options?.sidecarTarget || "").trim();
    const dispatchMode = inSidecar ? (sidecarTarget ? `sidecar_${sidecarTarget}` : "sidecar_pill") : "queue";
    const title = cleanUiText(fact.short_title || fact.clean_value || fact.value || "").slice(0, 60);
    const value = cleanUiText(fact.value || title);
    const evidenceIds = Array.isArray(fact.evidence_ids) ? fact.evidence_ids : [];
    const actor = reviewer || (isSolo ? "solo" : "owner");
    const dispatchPayload = await apiFetch("/api/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fact_id: factId,
        title,
        value,
        evidence_ids: evidenceIds,
        reviewer: actor,
        mode: dispatchMode,
        note: reviewNote,
      }),
    });
    if (dispatchPayload && !olderState(dispatchPayload)) {
      state.data = dispatchPayload;
    }
    const brief = formatDispatchBrief(fact);
    state.lastCopyRetryBrief = brief;
    let toastMsg = "";
    let toastActions = [];
    if (inSidecar && sidecarTarget === "send" && typeof window.sidecar.agent?.sendMessage === "function") {
      await window.sidecar.agent.sendMessage(brief);
      toastMsg = "已发入当前对话";
    } else if (inSidecar && sidecarTarget === "new" && typeof window.sidecar.agent?.startConversation === "function") {
      await window.sidecar.agent.startConversation(brief, title || "Compass 任务");
      toastMsg = "已新开对话发给 AI";
    } else if (inSidecar && typeof window.sidecar.ui?.addArtifactComment === "function") {
      window.sidecar.ui.addArtifactComment({
        uri: state.data?.project?.path || "compass://workbench",
        comment: brief,
        pageTitle: title || "Compass 待优先处理",
      });
      toastMsg = "已放进对话输入框，确认后发送";
    } else if (inSidecar && typeof window.sidecar.agent?.sendMessage === "function") {
      await window.sidecar.agent.sendMessage(brief);
      toastMsg = "已发入当前对话";
    } else {
      const copied = await copyTextToClipboard(brief);
      if (copied) {
        toastMsg = "已确认并加入待优先处理（指令已复制）";
      } else {
        toastMsg = "已加入待优先处理，剪贴板受限，点击右侧复制";
        toastActions = [{
          label: "复制指令",
          onClick: async () => {
            const retried = await copyTextToClipboard(brief);
            if (retried) {
              showCompassToast("指令已复制到剪贴板");
            } else {
              openDrawer("手动复制指令", `<div class="copy-fallback-box"><p class="empty">自动复制受限，请全选下方内容复制发送给 AI：</p><textarea class="copy-fallback-pre" readonly>${esc(brief)}</textarea></div>`);
            }
          },
        }];
      }
    }
    render();
    invalidateInvestigation("已确认并加入待优先处理，请重新查询以使用最新状态。");
    const drawer = document.getElementById("evidence-drawer");
    if (options?.fromDrawer || (drawer && !drawer.hidden)) {
      openFact(factId);
    }
    showCompassToast(toastMsg, toastActions.length ? { durationMs: 6500, actions: toastActions } : {});
  } catch (error) {
    showCompassToast(`发送失败：${error.message}`, { tone: "error" });
  } finally {
    inFlightReviewIds.delete(factId);
    matchingBtns.forEach((btn) => {
      if (btn.isConnected) btn.disabled = false;
    });
  }
}

async function confirmRelation(relationId, factId, options = {}) {
  if (state.data.project?.read_only) {
    showCompassToast("当前项目为只读，不能确认关联", { tone: "error" });
    return;
  }
  const isSolo = effectiveWorkMode() === "solo";
  const reviewer = resolveSigner(isSolo, options?.signer);
  if (!reviewer) {
    showCompassToast("请先填写负责人姓名，再确认这条关联", { tone: "error" });
    document.getElementById("reviewer-input")?.focus?.();
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
    invalidateInvestigation("依据关联确认状态已更新，请重新查询以使用最新状态。");
    openFact(factId);
  } catch (error) {
    showCompassToast(`确认失败：${error.message}`, { tone: "error" });
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
          const fBadge = fSup ? renderStatusBadge("superseded", "已有新版本接替") : renderStatusBadge(resolveFactStatus(f));
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
if (handoffExportMindmap) handoffExportMindmap.addEventListener("click", () => exportCognitiveAsset("mindmap", "handoff-export-mindmap-btn", "已导出思维导图"));

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
document.querySelectorAll(".lens").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); renderWithTransition(() => { state.lens = button.dataset.lens; render(); }); }));
document.querySelectorAll(".layer-choice").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); renderWithTransition(() => { state.layer = button.dataset.layerChoice; render(); }); }));
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
    showCompassToast(`导出失败：${error.message || "无法导出当前状态"}`, { tone: "error" });
  }
});
const clearStatsBtn = document.getElementById("clear-query-stats");
clearStatsBtn.addEventListener("click", () => {
  armConfirmButton(clearStatsBtn, "再次点击确认清除", async () => {
    try {
      state.data = await apiFetch('/api/query-stats/clear', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      state.projectId = state.data?.project?.project_id || null;
      state.revision += 1; render();
      showCompassToast("已清除本次检索统计");
    } catch (error) {
      showCompassToast(`清除失败：${error.message || "无法清除检索统计"}`, { tone: "error" });
    }
  }, { armKey: "clear-query-stats" });
});
document.getElementById("project-scan-form").addEventListener("submit", scanNewProject);
document.getElementById("refresh-intake").addEventListener("click", refreshNative);
document.getElementById("rescan-project").addEventListener("click", rescanProject);
document.getElementById("extract-candidates").addEventListener("click", extractCandidates);
document.getElementById('trace-start').addEventListener('click', () => jumpTrace(false));
document.getElementById('trace-latest').addEventListener('click', () => jumpTrace(true));
setInterval(() => { if (!document.hidden) refreshNative({ backgroundPoll: true }); }, 3000);
document.getElementById("evidence-filter").addEventListener("input", (event) => { state.evidenceQuery = event.target.value; renderEvidenceSpine(); });
if (typeof document.addEventListener === "function") {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flushDelayedReviews({ keepalive: true });
  });
}
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
  window.addEventListener("pagehide", () => { flushDelayedReviews({ keepalive: true }); });
}

function normalizeWorkspaceComparisonKey(raw) {
  let text = String(raw || "").trim();
  if (!text) return "";
  if (/^file:\/\//i.test(text)) {
    text = text.replace(/^file:\/\/(?:localhost)?/i, "");
    try {
      text = decodeURIComponent(text);
    } catch (_err) {
      // Preserve raw string when URI percent-encoding is incomplete.
    }
    text = text.replace(/^\/([A-Za-z]:)/, "$1");
  }
  text = text.replace(/\\/g, "/").replace(/\/+$/, "");
  if (/^[A-Za-z]:\//.test(text)) {
    text = text.toLowerCase();
  }
  return text;
}

async function activateWorkspaceFromSidecarUris(uris) {
  if (!Array.isArray(uris) || !uris.length) return;
  const firstUri = String(uris.find((u) => typeof u === "string" && u.trim()) || "").trim();
  if (!firstUri) return;
  if (state.data?.sample_mode === true) return;
  if (state.sidecarActivating) {
    if (firstUri === state.inflightWorkspaceUri) {
      state.pendingWorkspaceUri = "";
    } else {
      state.pendingWorkspaceUri = firstUri;
    }
    return;
  }
  const isReadOnlyPreview = Boolean(state.data?.project?.read_only);
  if (!isReadOnlyPreview && firstUri === state.activeWorkspaceUri) return;
  const loadedPath = state.data?.project?.path || "";
  if (!isReadOnlyPreview && loadedPath && normalizeWorkspaceComparisonKey(firstUri) === normalizeWorkspaceComparisonKey(loadedPath)) {
    state.activeWorkspaceUri = firstUri;
    return;
  }
  state.sidecarActivating = true;
  state.inflightWorkspaceUri = firstUri;
  try {
    if (state.delayedQueue?.size) await flushDelayedReviews({ keepalive: true });
    const payload = await apiFetch("/api/projects/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_path: firstUri }),
    });
    if (payload && !olderState(payload)) {
      state.activeWorkspaceUri = firstUri;
      const prevId = state.data?.project?.project_id || null;
      state.data = payload;
      state.projectId = payload.project?.project_id || null;
      state.evidenceCache = Object.create(null);
      state.evidenceRequestSeq = (state.evidenceRequestSeq || 0) + 1;
      state.activeChapterId = null;
      state.revision += 1;
      loadProjects();
      render();
      if (prevId && state.projectId && prevId !== state.projectId) {
        invalidateInvestigation("已跟随左侧窗口切换项目工作区，请重新提问以使用新项目状态。");
        showCompassToast?.("已自动切换到当前打开的项目工作区");
      }
    }
  } catch (err) {
    const conn = document.getElementById("connection-label");
    if (conn) conn.textContent = "工作区切换失败 · 请刷新重试";
    showCompassToast?.(`切换项目工作区失败：${err?.message || "请重试"}`);
  } finally {
    state.sidecarActivating = false;
    state.inflightWorkspaceUri = "";
    const queued = String(state.pendingWorkspaceUri || "").trim();
    state.pendingWorkspaceUri = "";
    if (queued && queued !== state.activeWorkspaceUri) {
      activateWorkspaceFromSidecarUris([queued]);
    }
  }
}

function initSidecarBridge() {
  if (!hasSidecarBridge()) return;
  if (typeof window.sidecar.onWorkspaceChange === "function") {
    window.sidecar.onWorkspaceChange((uris) => {
      activateWorkspaceFromSidecarUris(uris);
    });
  }
  if (typeof window.sidecar.getWorkspaceUris === "function") {
    Promise.resolve(window.sidecar.getWorkspaceUris())
      .then((uris) => activateWorkspaceFromSidecarUris(uris))
      .catch((err) => {
        const conn = document.getElementById("connection-label");
        if (conn && !state.data) conn.textContent = `工作区联动暂不可用：${err?.message || "请重试"}`;
      });
  }
}

loadState()
  .then(() => {
    initSidecarBridge();
  })
  .catch((error) => {
    const conn = document.getElementById("connection-label");
    if (conn) conn.textContent = `状态暂不可用：${error.message}`;
  });
