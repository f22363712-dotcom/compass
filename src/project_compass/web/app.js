const state = { data: null, lens: "personal", workMode: null, member: null, evidenceQuery: "", layer: "overview", refreshing: false, revision: 0, investigationRequest: 0, projectId: null, activeChapterId: null, evidenceCache: Object.create(null), evidenceRequestSeq: 0, popoverTimer: null, popoverAnchor: null, popoverCurrentId: null, lastTriggerElement: null, lastModalTrigger: null, lastDrawerTrigger: null, lastDrawerTriggerSpec: null, copyRestoreTimer: null, exportTimers: Object.create(null) };

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

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
const label = (kind) => ({goal:"Goal", task:"Task", decision:"Decision", assumption:"Assumption"}[kind] || kind || "Material");
const statusLabel = (status) => status === "accepted" ? "confirmed" : status || "proposed";
const safeToken = (value, fallback = "pending") => {
  const raw = String(value ?? "");
  return /^[a-z0-9_-]+$/i.test(raw) ? raw : fallback;
};
const STATUS_BADGE_MAP = Object.assign(Object.create(null), {
  accepted: { cls: "is-accepted", text: "confirmed" },
  confirmed: { cls: "is-accepted", text: "confirmed" },
  completed: { cls: "is-accepted", text: "completed" },
  current: { cls: "is-accepted", text: "● CURRENT" },
  conflicted: { cls: "is-conflicted", text: "conflicted" },
  blocked: { cls: "is-conflicted", text: "blocked" },
  unavailable: { cls: "is-conflicted", text: "● UNAVAILABLE" },
  rejected: { cls: "is-rejected", text: "rejected" },
  abandoned: { cls: "is-rejected", text: "abandoned" },
  needs_evidence: { cls: "is-warn", text: "needs evidence" },
  needs_more_evidence: { cls: "is-warn", text: "needs evidence" },
  superseded: { cls: "is-warn", text: "superseded" },
  deferred: { cls: "is-warn", text: "deferred" },
  proposed: { cls: "is-proposed", text: "proposed" },
  candidate: { cls: "is-proposed", text: "candidate" },
  raw: { cls: "is-proposed", text: "raw" },
  pending: { cls: "is-proposed", text: "pending" },
  active: { cls: "is-info", text: "active" },
  relation_confirmed: { cls: "is-info", text: "relation confirmed" },
  recommended: { cls: "is-info", text: "系统推荐" },
});
function getBadgeMeta(status) {
  const key = String(status || "proposed").toLowerCase();
  return Object.prototype.hasOwnProperty.call(STATUS_BADGE_MAP, key)
    ? STATUS_BADGE_MAP[key]
    : { cls: "is-proposed", text: key || "proposed" };
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
const formatTime = (value) => { if (!value) return "time unavailable"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", {hour12: false}); };
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

async function scanNewProject(event) {
  event.preventDefault();
  const result = document.getElementById("project-scan-result");
  const projectPath = document.getElementById("project-path-input").value.trim();
  if (!projectPath) { result.textContent = "请填写目录"; return; }
  result.textContent = "正在扫描…";
  try {
    await apiFetch("/api/projects/scan", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({project_path: projectPath})});
    result.textContent = "扫描中…";
    let completed = false;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      const status = await apiFetch("/api/projects/scan-status");
      if (status.state === "failed") throw new Error(status.error || "扫描失败");
      if (status.state === "complete") { completed = true; state.projectId = status.project_id; await loadState(); result.textContent = `已保存 ${status.project_path}`; loadProjects(); break; }
    }
    if (!completed) result.textContent = "扫描仍在进行，可稍后刷新页面查看状态。";
  } catch (error) {
    result.textContent = error.message;
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

function render() {
  if (!state.data) return;
  const isSolo = effectiveWorkMode() === "solo";
  if (document.body?.dataset) {
    document.body.dataset.layer = state.layer;
    document.body.dataset.workMode = isSolo ? "solo" : "team";
  }
  document.querySelectorAll(".mode-pill").forEach((button) => button.classList?.toggle?.("active", button.dataset?.workMode === (isSolo ? "solo" : "team")));
  document.querySelectorAll(".layer-choice").forEach((button) => button.classList?.toggle?.("active", button.dataset?.layerChoice === state.layer));
  const submit=document.getElementById('investigate-submit');
  if (submit) submit.disabled=false;
  const reviewer = document.getElementById('reviewer-input');
  reviewer.readOnly = state.data.agent_api?.enabled === true || state.data.project?.read_only === true;
  if (reviewer.readOnly) {
    reviewer.value = state.data.agent_api?.owner_id || "";
  } else if (!reviewer.value) {
    const savedReviewer = readStorage("compass_reviewer_name").trim();
    if (savedReviewer) reviewer.value = savedReviewer;
  }
  const reviewerTag = document.getElementById("reviewer-field-tag");
  if (reviewerTag) reviewerTag.textContent = isSolo ? "我的署名" : "负责人";
  reviewer.placeholder = isSolo ? "输入你的署名（自动记住）" : "填写姓名后可确认事实";
  const toolbarNote = document.getElementById("toolbar-note");
  if (toolbarNote) toolbarNote.textContent = isSolo ? "实时记录人机共创轨迹 · 待定思路定案后沉淀为项目基准" : "候选关系需负责人确认 · 原始证据追加保留";
  const lensPersonalBtn = document.getElementById("lens-personal-btn");
  if (lensPersonalBtn) lensPersonalBtn.textContent = isSolo ? "实时纪要 · 待定思路" : "个人视图 · 个人看板";
  const lensTeamBtn = document.getElementById("lens-team-btn");
  if (lensTeamBtn) lensTeamBtn.textContent = isSolo ? "项目基准 · 已定案" : "团队共识 · 事实基准";
  const handoffBriefLabel = document.getElementById("handoff-brief-label");
  if (handoffBriefLabel) handoffBriefLabel.textContent = isSolo ? "上下文快照" : "交接简报";
  const heroCopy = document.getElementById("hero-copy");
  if (heroCopy) {
    heroCopy.textContent = isSolo
      ? "人与 AI 结对开发的实时交互纪要：直观追踪你的行动轨迹、待定思路与已定案项目基准，随时溯源原文与代码结构。"
      : "基于国际主义栅格系统的双视角工作台：明确区分个人推进候选与负责人确认的团队共识，所有结论均溯源至原始证据。";
  }
  selectAvailableMember();
  renderIntake();
  renderProjectScan();
  renderDerivedContext();
  renderExtraction();
  const guidance = document.getElementById('candidate-guidance');
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
    guidance.innerHTML = `<span>${lead}${extractionEnabled ? '可以启动一批候选整理，结果仍需负责人确认。' : '当前服务未启用候选整理，请用 --enable-extraction 重启。'}</span>${extractionEnabled ? '<button type="button" id="guidance-extract">整理一批新材料</button>' : ''}`;
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
  const visibleEvidence = query ? evidence.filter((item) => `${item.id} ${item.content_preview} ${item.command_preview || ''} ${item.source_ref || ""} ${item.author || ""}`.toLowerCase().includes(query)) : evidence;
  const candidates = relations.filter((relation) => relation.status === "candidate" && factIds.has(relation.fact_id)).length;
  const tasks = facts.filter((fact) => fact.kind === "task").length;
  const unlinkedEvidence = evidence.filter((item) => !(item.candidate_fact_ids?.length || item.confirmed_fact_ids?.length)).length;
  const goal = facts.find((fact) => fact.kind === "goal" && resolveFactStatus(fact) === "accepted" && sourceCurrent(fact)) || [...facts].reverse().find((fact) => fact.kind === "goal" && sourceCurrent(fact));

  document.getElementById("project-title").textContent = state.data.project?.name || "Compass";
  document.getElementById("evidence-count").textContent = state.data.project?.evidence_count ?? catalog.length;
  document.getElementById("evidence-kicker").textContent = state.lens === "team" ? (isSolo ? "项目基准证据" : "团队共识证据") : state.member === "project-documents" ? "项目材料档案" : (isSolo ? "实时行动记录" : "个人证据链");
  const goalEffectiveStatus = goal ? resolveFactStatus(goal) : "proposed";
  const isGoalAccepted = Boolean(goal && goalEffectiveStatus === "accepted");
  const goalBadgeMeta = getBadgeMeta(goalEffectiveStatus);

  document.getElementById("goal-title").textContent = goal?.value || "此视图尚无目标候选";
  document.getElementById("goal-note").textContent = goal
    ? `${isGoalAccepted ? (isSolo ? "已定案为核心目标" : "已确认为团队目标") : (isSolo ? "待定目标思路 · 尚未拍板定案" : "候选目标 · 尚未经负责人确认为团队共识")} · ${goal.evidence_ids?.length || 0} 条直接证据 · ${sourceTimeText(goal)}${isGoalAccepted ? "" : " · 有效性待核对"}`
    : state.data.project?.fact_count ? "可查看本视图的任务和证据，或切换团队视图。" : "当前尚无候选事实：可执行 compass --scan . --extract-docs 提取文档目标，或展开下方工具栏扫描接入。";
  const goalStatusEl = document.getElementById("goal-status");
  goalStatusEl.textContent = isGoalAccepted
    ? "confirmed · 已确认目标"
    : goalEffectiveStatus === "rejected"
      ? "rejected · 已拒绝"
      : `${statusLabel(goalEffectiveStatus)} · ${isSolo ? "待定案" : "待负责人确认"}`;
  goalStatusEl.className = `status-pill status-badge ${isGoalAccepted ? "accepted " : ""}${goalBadgeMeta.cls}`;
  const goalSurface = typeof document.querySelector === "function" ? document.querySelector(".goal-surface") : null;
  if (goalSurface?.classList) {
    goalSurface.classList.toggle("is-accepted", isGoalAccepted);
    goalSurface.classList.toggle("is-conflicted", !isGoalAccepted && goalEffectiveStatus === "conflicted");
    goalSurface.classList.toggle("is-rejected", !isGoalAccepted && goalEffectiveStatus === "rejected");
    goalSurface.classList.toggle("is-proposed", !isGoalAccepted && goalEffectiveStatus !== "conflicted" && goalEffectiveStatus !== "rejected");
  }

  const goalActions = [];
  if (goal?.evidence_ids?.length) {
    goalActions.push(`<div class="card-pill-row">${renderEvPills(goal.evidence_ids)}</div>`);
  }
  if (goal && !isGoalAccepted && canInlineAcceptFact(goal)) {
    goalActions.push(`<div class="in-card-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(goal.id)}" title="${isSolo ? "定案为核心目标" : "确认为团队核心目标"}">${isSolo ? "✓ 定案为核心目标" : "✓ 确认为团队目标"}</button></div>`);
  }
  document.getElementById("goal-actions").innerHTML = goalActions.join("");
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
  const activities = (state.data.personal_activity || []).filter((item) => state.lens === "team" || !state.member || item.member_id === state.member);
  document.getElementById("personal-activity-list").innerHTML = activities.length ? activities.map((item) => `<div class="activity-item" role="button" tabindex="0" data-evidence-id="${esc(item.last_event_id)}"><strong>${esc(item.member_id)}</strong><span>${esc(item.last_event_kind || "event")} · ${esc(formatTime(item.last_event_at))}</span><small>${esc(item.last_event_preview || "")} · ${item.event_count} 条 · 查看原文</small><div class="card-pill-row">${renderEvPills([item.last_event_id])}</div></div>`).join("") : `<p class="empty">暂无 Agent 活动。</p>`;
  const todos = state.lens === "personal" ? filterByChapter(facts.filter((fact) => fact.kind === "task")) : [];
  document.getElementById("personal-todos").hidden = state.lens !== "personal";
  document.getElementById("personal-todo-list").innerHTML = todos.length ? todos.map((fact) => {
    const effectiveStatus = resolveFactStatus(fact);
    const accepted = effectiveStatus === "accepted";
    const rejected = effectiveStatus === "rejected";
    const isCompleted = fact.task_state === "completed";
    let inlineTriage = "";
    if (accepted) {
      inlineTriage = `<span class="in-card-actions">${renderStatusBadge("accepted", isSolo ? "✓ 已定案" : "✓ 团队事实")}</span>`;
    } else if (!state.data.project?.read_only) {
      const acceptBtn = canInlineAcceptFact(fact) ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="${isSolo ? "定案为项目基准" : "采纳为团队任务"}">${isSolo ? "✓ 定案" : "✓ 采纳"}</button>` : "";
      const rejectBtn = rejected ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="驳回候选">✕ 驳回</button>`;
      inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
    }
    return `<div class="todo-item" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${isCompleted ? '☑' : '☐'} ${esc(fact.value)}</strong><span>任务状态：${isCompleted ? "已实现" : esc(fact.task_state || "待推进")} · 事实状态：${esc(statusLabel(effectiveStatus))} · ${fact.evidence_ids?.length || 0} 条证据</span><div class="card-pill-row">${renderStatusBadge(effectiveStatus)}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
  }).join("") : `<p class="empty">当前成员暂无待办候选。</p>`;
  const evidenceRequests = state.lens === "personal" ? (state.data.evidence_requests || []).filter((request) => request.member_id === state.member) : [];
  document.getElementById("personal-evidence-requests").hidden = state.lens !== "personal" || evidenceRequests.length === 0;
  document.getElementById("evidence-request-count").textContent = evidenceRequests.length;
  document.getElementById("evidence-request-list").innerHTML = evidenceRequests.length ? evidenceRequests.map((request) => `<button type="button" class="evidence-request-item" data-fact-id="${esc(request.fact_id)}"><strong>${esc(request.value)}</strong><span>${request.status === "ready_for_review" ? "已有新证据，可重新核对" : "等待新证据"} · ${request.new_evidence_ids?.length || 0} 条新增 · ${esc(request.note || "负责人未填写说明")}</span></button>`).join("") : `<p class="empty">当前成员没有待补证据任务。</p>`;
  const decisions = state.lens === "personal" ? filterByChapter(facts.filter((fact) => fact.kind === "decision" || fact.kind === "assumption")) : [];
  document.getElementById("personal-decisions").hidden = state.lens !== "personal";
  document.getElementById("personal-decision-list").innerHTML = decisions.length ? decisions.map((fact) => {
    const effectiveStatus = resolveFactStatus(fact);
    const accepted = effectiveStatus === "accepted";
    const rejected = effectiveStatus === "rejected";
    let inlineTriage = "";
    if (accepted) {
      inlineTriage = `<span class="in-card-actions">${renderStatusBadge("accepted", isSolo ? "✓ 已定案基准" : "✓ 已确认共识")}</span>`;
    } else if (!state.data.project?.read_only) {
      const acceptBtn = canInlineAcceptFact(fact) ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(fact.id)}" title="${isSolo ? "定案为项目基准" : "确认为团队共识"}">${isSolo ? "✓ 定案基准" : "✓ 确认决策"}</button>` : "";
      const rejectBtn = rejected ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(fact.id)}" title="驳回候选">✕ 驳回</button>`;
      inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
    }
    return `<div class="decision-item" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><strong>${fact.kind === "decision" ? "决策" : "未验证前提"}</strong><span>${esc(fact.value)}</span><small>${esc(statusLabel(effectiveStatus))} · ${fact.evidence_ids?.length || 0} 条证据</small><div class="card-pill-row">${renderStatusBadge(effectiveStatus)}${renderEvPills(fact.evidence_ids)}</div>${inlineTriage}</div>`;
  }).join("") : `<p class="empty">当前成员暂无决策或未验证前提。</p>`;
  const reviewQueue = filterByChapter(state.data.team_review_queue || []);
  const reviewSurface = document.getElementById("team-review-queue");
  reviewSurface.hidden = state.lens !== "team";
  document.getElementById("team-review-count").textContent = reviewQueue.length;
  document.getElementById("team-review-list").innerHTML = state.lens !== "team" ? "" : reviewQueue.length
    ? reviewQueue.map((item) => {
        const qFact = (state.data.team?.facts || []).find((f) => f.id === item.fact_id);
        let inlineTriage = "";
        if (!state.data.project?.read_only) {
          const allowAccept = qFact ? canInlineAcceptFact(qFact) : true;
          const qStatus = qFact ? resolveFactStatus(qFact) : item.status;
          const acceptBtn = allowAccept && qStatus !== "accepted" ? `<button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(item.fact_id)}" title="直接确认入库">✓ 确认</button>` : "";
          const rejectBtn = qStatus === "rejected" ? "" : `<button type="button" class="mini-btn reject-btn" data-inline-review="reject_fact" data-target-id="${esc(item.fact_id)}" title="驳回">✕ 驳回</button>`;
          inlineTriage = (acceptBtn || rejectBtn) ? `<span class="in-card-actions">${acceptBtn}${rejectBtn}</span>` : "";
        }
        return `<div class="review-queue-item" role="button" tabindex="0" data-fact-id="${esc(item.fact_id)}">${renderStatusBadge(item.status, item.status === "conflicted" ? "冲突" : item.status === "needs_evidence" ? "补证据" : "待确认")}<span class="review-queue-main"><strong>${esc(item.value)}</strong><small>${esc(item.reason)} · ${esc(item.author || "作者未提供")} · ${item.evidence_count} 条证据 · ${item.candidate_relation_count} 条候选关系</small><span class="card-pill-row">${renderEvPills(qFact?.evidence_ids)}</span>${inlineTriage}</span></div>`;
      }).join("")
    : `<p class="empty">当前没有待负责人核对的团队事实。</p>`;
  document.getElementById("fact-list").innerHTML = facts.length ? facts.map((fact) => factCard(fact, relations)).join("") : `<p class="empty">当前视图还没有结构化事实。原始材料仍可在证据脊柱中查看。</p>`;
  renderTrace(facts, relations, evidence);
  renderDirections(view.directions || {candidates:[],current:[],history:[]}, state.lens === 'team');
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
  if ((!state.data?.intake?.enabled && !state.data?.intake?.direction_scan?.enabled && !state.data?.intake?.user_task_scan?.enabled && !state.data?.extraction?.enabled && !state.data?.agent_api?.enabled) || state.refreshing) return;
  state.refreshing = true;
  document.getElementById("refresh-intake").disabled = true;
  try {
    const useRefresh = state.data.intake?.enabled || state.data.intake?.direction_scan?.enabled || state.data.intake?.user_task_scan?.enabled;
    const payload = useRefresh
      ? await apiFetch("/api/refresh", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"})
      : await apiFetch("/api/state");
    if (olderState(payload)) return;
    const evidenceChanged = payload.project.evidence_count !== state.data.project.evidence_count;
    const reviewChanged = payload.review_history.length !== state.data.review_history.length;
    const candidatesChanged = payload.project.fact_count !== state.data.project.fact_count;
    const versionChanged = payload.state_version !== state.data.state_version;
    if (evidenceChanged || reviewChanged || candidatesChanged || versionChanged) {
      state.data = payload;
      render();
      invalidateInvestigation(candidatesChanged ? "新候选已更新，原始材料和负责人确认记录保留，请重新提问。" : evidenceChanged ? payload.intake?.new_tool_records ? "已接入工具记录，原有事实与确认历史保留，请重新提问。" : "已接入新消息。原有事实与确认记录保留，新材料需提取后再重新调查。" : "项目状态或负责人确认记录已更新，请重新提问以使用最新状态。");
    } else {
      state.data.intake = payload.intake;
      state.data.extraction = payload.extraction;
      renderIntake();
      renderExtraction();
    }
  } catch (error) {
    document.getElementById("intake-status").textContent = `会话刷新失败，已保存内容保留。${error.message}`;
  } finally {
    state.refreshing = false;
    document.getElementById("refresh-intake").disabled = false;
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
  const surface=document.getElementById('direction-surface');
  if (!surface) return;
  const current=directions.current || [], history=directions.history || [];
  const rows=isTeam ? current.filter((row)=>row.direction_state !== 'active') : directions.candidates || [];
  document.getElementById('direction-title').textContent=isTeam ? '舍弃与暂缓方向' : '方向状态候选';
  document.getElementById('direction-count').textContent=rows.length;
  document.getElementById('direction-note').textContent=isTeam ? '清单仅收录负责人明确确认的方向。恢复及旧状态保留在下方历史。' : '明确表述仍是候选。未被采用的建议不会自动归为已放弃。';
  const entry=(row, historical=false)=>`<div class="direction-entry"><div class="detail-label">${esc(!isTeam && row.status === 'proposed' ? directionCandidateLabel(row.direction_state) : directionLabel(row.direction_state))} · ${historical ? row.current ? '当前确认' : '历史确认' : isTeam ? '负责人已确认' : '待负责人确认'}</div><button type="button" class="direction-open" data-fact-id="${esc(row.fact_id)}">${esc(row.quote)}</button><p class="meta-note">${esc(row.member_id || '')} · ${sourceTimeHTML(row)}</p>${row.reviewed_by ? `<p class="reviewed-note">${esc(row.reviewed_by)} · ${esc(formatTime(row.reviewed_at))}</p>` : ''}<div>${(row.evidence_ids || []).map((id)=>`<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join('')}</div>${sourceNote(row) ? `<p class="source-warning">${esc(sourceNote(row))}</p>` : ''}</div>`;
  document.getElementById('direction-list').innerHTML=rows.length ? rows.map((row)=>entry(row)).join('') : `<p class="empty">${isTeam ? '尚无当前已确认的放弃或暂缓方向。' : '尚无可归类的明确方向表述。可继续查看个人候选和原始来源。'}</p>`;
  document.getElementById('direction-history').innerHTML=isTeam && history.length ? `<div class="history-label">方向状态历史 · ${history.length}</div>${history.map((row)=>entry(row,true)).join('')}` : '';
}

function reasonPreviewHTML(preview) {
  const rows=preview?.candidates || [], gaps=preview?.gaps || [];
  const links=(ids)=>(ids || []).map((id)=>`<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join('');
  const target=(row)=>`<button type="button" class="reason-target" data-fact-id="${esc(row.target_fact_id)}">对应陈述 · ${esc(row.target_quote)}</button>`;
  const quotes=(items,label)=>!items?.length ? '' : `<details class="reason-sources"><summary>${esc(label)} · ${items.length}</summary>${items.map((q)=>`<div class="detail-block"><p class="meta-note">${esc(q.member_id)} · ${esc(claimLabel(q.claim_type))} · ${esc(q.reported_by)} · ${sourceTimeHTML(q)}</p><pre class="reason-quote">${esc(q.quote)}</pre>${links([q.source_id])}</div>`).join('')}</details>`;
  return `<p class="empty">只读预览 · 待负责人核对。引文匹配仅核对出处，原因联系与模型分类仍需核对。</p>${preview?.unavailable_targets ? `<p class="source-warning">${esc(preview.unavailable_targets)} 项目标或来源已变化，相关预览暂未展示。</p>` : ''}${rows.map((row)=>`<article class="reason-card"><div class="detail-label">${row.relation_type_suggested==='hypothesized_reason' ? '推断假说' : '来源说明候选'} · 待核对</div>${target(row)}<p class="detail-value">${esc(row.summary)}</p>${row.assumptions?.length ? `<div class="reason-assumptions"><strong>推断前提</strong>${row.assumptions.map((a)=>`<p>${esc(a)}</p>`).join('')}</div>` : ''}${quotes(row.source_quotes,'原文引文')}${quotes(row.counter_evidence,'反向或替代线索')}<p class="meta-note">生成模型 ${esc(row.model || '')}</p></article>`).join('')}${gaps.map((gap)=>`<div class="reason-gap">${target(gap)}<p class="detail-label">所选材料中的缺证说明</p><p class="detail-value">${esc(gap.text)}</p>${links(gap.scope_source_ids)}</div>`).join('')}${!rows.length&&!gaps.length ? '<p class="empty">当前问题或视图没有匹配的原因预览，可继续核对原始材料。</p>' : ''}`;
}

function renderReasonPreview() {
  const surface=document.getElementById('reason-preview-surface');
  if (!surface) return;
  const preview=state.data?.reason_preview;surface.hidden=!preview?.enabled;
  if (!preview?.enabled) return;
  const selected={...preview,candidates:(preview.candidates || []).filter((r)=>state.lens==='team'||r.member_id===state.member),gaps:(preview.gaps || []).filter((r)=>state.lens==='team'||r.member_id===state.member)};
  document.getElementById('reason-preview-count').textContent=selected.candidates.length;
  document.getElementById('reason-preview-list').innerHTML=reasonPreviewHTML(selected);
}

function renderInvestigation(answer) {
  const panel = document.getElementById("investigation-answer");
  panel.hidden = false;
  const evidenceLinks = (ids) => (ids || []).map((id) => `<button type="button" class="answer-evidence" data-evidence-id="${esc(id)}">${esc(id)}</button>`).join("");
  const scopeLabel = answer.scope ? "成员记录" : "当前团队状态";
  const basis = answer.next_action_basis;
  const actionLabel = answer.next_action_status === 'accepted' ? '已确认下一步' : basis ? '候选下一步' : '下一步动作';
  const basisHTML = basis ? `<div class="detail-block"><p class="meta-note">${sourceTimeHTML(basis)} · ${esc(basis.member_id || '')} · ${esc(claimLabel(basis.claim_type))}</p>${basis.status === 'accepted' ? `<p class="reviewed-note">${esc(basis.reviewed_by || 'owner')} · ${sourceTimeHTML({observed_at:basis.reviewed_at}, '负责人确认时间')}</p>` : '<p class="source-warning">候选来源的当前版本需核对，历史任务不会自动成为当前确认。</p>'}${evidenceLinks(basis.evidence_ids || [])}</div>` : '';
  const activeTasks = answer.active_tasks || [];
  const conflicts = answer.conflicts || [];
  panel.innerHTML = `<div class="answer-conclusion">${esc(answer.conclusion)}</div><div class="answer-grid"><div><div class="detail-label">${scopeLabel}</div><div class="detail-value">${esc(answer.goal)} · ${activeTasks.map(esc).join(" · ") || "暂无进行中任务"}</div></div><div><div class="detail-label">依据与证据链</div><div class="answer-evidence-list">${evidenceLinks(answer.evidence_ids)}</div></div><div><div class="detail-label">${actionLabel}</div><div class="detail-value">${esc(answer.next_action)}</div>${basisHTML}</div><div><div class="detail-label">验收条件</div><div class="detail-value">${esc(answer.acceptance_condition)}</div></div></div>${conflicts.length ? `<div class="answer-conflicts"><div class="detail-label">分歧历史</div>${conflicts.map((conflict) => `<div class="answer-conflict"><strong>${esc(conflict.subject_key)}</strong>${(conflict.sides || []).map((side) => { const sideStatus = resolveFactStatus(side.fact_id ? { id: side.fact_id, status: side.status } : side); return `<span>${renderStatusBadge(sideStatus)} ${esc(side.value)} · ${sourceTimeHTML(side)} · ${evidenceLinks(side.evidence_ids)}</span>`; }).join("")}</div>`).join("")}</div>` : ""}`;
  if (answer.cache) {
    const cacheNote = document.createElement("p");
    cacheNote.className = "meta-note";
    cacheNote.textContent = answer.cache.hit ? "当前状态下复用的调查结果" : "刚刚完成的调查";
    panel.appendChild(cacheNote);
  }
  if (answer.findings?.length) {
    panel.querySelector(".answer-evidence-list").innerHTML = answer.findings.map((item) => {
      const itemStatus = item.fact_id || item.id ? resolveFactStatus({ id: item.fact_id || item.id, status: item.status }) : item.status;
      return `<div class="detail-block"><div class="detail-label">${esc(claimLabel(item.claim_type))} ${renderStatusBadge(itemStatus)}</div>${rawFindingMeta(item)}${directionFindingMeta(item)}${item.member_id ? `<p class="meta-note">${esc(item.member_id)} · ${sourceTimeHTML(item)}</p>` : ""}${item.reviewed_by ? `<p class="reviewed-note">${esc(item.reviewed_by)} · ${esc(formatTime(item.reviewed_at))}</p>` : ""}<p class="detail-value">${esc(item.quote)}</p>${item.excerpt_truncated ? '<p class="meta-note">原文摘录，完整内容可从来源打开。</p>' : ""}${evidenceLinks(item.evidence_ids)}</div>`;
    }).join("");
    panel.querySelector(".answer-grid .detail-value").textContent = answer.scope ? answer.goal : `${answer.goal} · ${answer.active_tasks.length} 条任务声明，原文见下方看板。`;
  }
  if (answer.source_warnings?.length) {
    const warning = document.createElement("div");
    warning.className = "source-warning";
    warning.innerHTML = `<div class="detail-label">来源变更，需复核</div>${answer.source_warnings.map((item) => `<p>${esc(item.fact_id)} · ${esc(item.source_state.status)} · 历史确认 ${esc(item.status)}</p>${evidenceLinks([...item.evidence_ids, ...item.source_state.replacement_ids, ...item.source_state.observation_ids])}`).join("")}`;
    panel.prepend(warning);
  }
  if (answer.next_action_status) {
    const action = document.createElement("p");
    action.className = answer.next_action_status === "accepted" ? "reviewed-note" : "meta-note";
    action.textContent = answer.next_action_status === "accepted" ? "下一步已由负责人确认" : "下一步仍为待确认建议";
    panel.append(action);
  }
  if (answer.evidence_gaps?.length) {
    const gaps = document.createElement("div");
    gaps.className = "answer-conflicts";
    gaps.innerHTML = `<div class="detail-label">证据缺口</div>${answer.evidence_gaps.map((gap) => `<p class="detail-value">${esc(gap)}</p>`).join("")}`;
    panel.prepend(gaps);
  }
  if (answer.reason_preview?.enabled) {
    const reasons=document.createElement('div');reasons.className='answer-conflicts';
    reasons.innerHTML=`<div class="detail-label">原因候选预览</div>${reasonPreviewHTML(answer.reason_preview)}`;
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
  const currentStatus = effectiveStatus === "accepted" ? "accepted"
    : effectiveStatus === "conflicted" ? "conflicted"
      : effectiveStatus === "rejected" ? "rejected"
        : effectiveStatus === "needs_evidence" ? "needs_evidence"
          : confirmed ? "relation_confirmed" : "candidate";
  const author = fact.author ? ` · ${esc(fact.author)}` : "";
  const verifiedBadge = renderSpeculativeBadge(fact);
  return `<div class="fact-card" role="button" tabindex="0" data-fact-id="${esc(fact.id)}"><div class="fact-main"><div class="fact-kind">${esc(label(fact.kind))}${verifiedBadge}</div><div class="fact-value">${esc(fact.value)}</div><div class="fact-meta">${esc(claimLabel(fact.claim_type))}${author} · ${related.length} 条关联</div><div class="fact-meta">${sourceTimeHTML(fact)}${effectiveStatus === 'accepted' ? '' : ' · 当前有效性待核对'}</div>${directionStateText(fact) ? `<div class="fact-meta">${esc(directionStateText(fact))}</div>` : ''}${sourceNote(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 原记录保留</p>` : ""}</div>${renderStatusBadge(currentStatus)}</div>`;
}

function renderTeamHistory() {
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
    const recHTML = rec ? `<div class="conflict-speculative-rec"><strong>系统启发式建议:</strong> ${esc(rec.hypothetical_resolution || rec.recommended_value)}${recVerified} <span class="rec-meta">(${esc(rec.confidence)} 置信度 · ${esc(rec.score ?? "")}分，最终以负责人裁决为准)</span></div>` : "";
    const sideCards = sides.map((side, idx) => {
      const recBadge = side.speculative_status === "recommended" ? renderStatusBadge("recommended", "系统推荐") : "";
      const verifiedBadge = renderSpeculativeBadge(side);
      const matchedFact = teamFacts.find((f) => f.id === side.fact_id || (f.subject_key === conflict.subject_key && f.value === side.value && f.author === side.author));
      const sideStatus = resolveFactStatus(matchedFact || (side.fact_id ? { id: side.fact_id, status: side.status } : side));
      const inlineBtn = matchedFact && sideStatus !== "accepted" && canInlineAcceptFact(matchedFact)
        ? `<div class="conflict-pane-actions"><button type="button" class="mini-btn accept-btn" data-inline-review="accept_fact" data-target-id="${esc(matchedFact.id)}" title="采纳此方立场为团队事实">✓ 采纳立场 ${String.fromCharCode(65 + idx)}</button></div>`
        : "";
      const sideTag = `<span class="conflict-stance-label">立场 ${String.fromCharCode(65 + idx)}</span>`;
      const divider = idx === 0 && sides.length > 1 ? `<div class="conflict-vs-divider" aria-hidden="true"><span>VS</span></div>` : "";
      const paneClass = sideStatus === "accepted" ? "is-accepted" : sideStatus === "rejected" ? "is-rejected" : sideStatus === "needs_evidence" ? "is-needs-evidence" : "is-conflicted";
      return `<article class="conflict-side-pane ${paneClass}"><div class="conflict-pane-head">${sideTag}${renderStatusBadge(sideStatus)}${recBadge}${verifiedBadge}</div><div class="conflict-pane-value">${esc(side.value)}</div><div class="conflict-meta">${esc(side.author || "unknown")} · ${sourceTimeHTML(side)}</div><div class="card-pill-row">${renderEvPills(side.evidence_ids)}</div>${inlineBtn}</article>${divider}`;
    }).join("");
    return `<div class="conflict-card"><div class="conflict-card-head"><span class="conflict-key">${esc(conflict.subject_key)}</span><span class="conflict-count-tag">${sides.length} 立场对峙 · 证据同时保留</span></div>${recHTML}<div class="conflict-vs-grid">${sideCards}</div></div>`;
  }).join("") : `<p class="empty">当前没有冲突记录。</p>`;
    document.getElementById("history-list").innerHTML = history.length ? `<div class="history-label">审核历史</div>${history.map((entry) => `<div class="history-item"><strong>${esc(({accept_fact:'确认团队事实',confirm_relation:'确认证据关系',confirm_abandoned:'确认放弃方向',confirm_deferred:'确认暂缓方向',restore_direction:'恢复方向',reject_fact:'拒绝候选',request_evidence:'要求补证据'})[entry.action] || entry.action)}</strong><span>${esc(entry.value || entry.fact_id || entry.relation_id || "")} · ${esc(entry.reviewer || "owner")} · ${entry.evidence_ids?.length || 0} 条证据 · ${esc(formatTime(entry.observed_at))}${entry.evidence_request_id ? " · 已处理补证请求" : ""}${entry.resolved_relation_ids?.length ? ` · ${entry.resolved_relation_ids.length} 条关系已确认` : ""}${entry.note ? ` · ${esc(entry.note)}` : ""}</span></div>`).join("")}` : "";
}

function renderEvPills(ids) {
  const valid = (ids || []).filter(Boolean).slice(0, 4);
  if (!valid.length) return "";
  return valid.map((id) => `<span class="ev-pill" role="button" tabindex="0" data-evidence-id="${esc(id)}" title="悬停预览原文，点击打开证据详情">[${esc(id)}]</span>`).join("");
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

  const root = thinking.root || { label: "等待目标候选", status: "empty", evidence_ids: [] };
  const rootStatus = root.fact_id ? resolveFactStatus({ id: root.fact_id, status: root.status }) : (root.status || "empty");
  const branches = thinking.branches || [];
  const codeNodes = thinking.code_nodes || [];

  const isSolo = effectiveWorkMode() === "solo";
  const branchHTML = branches.length ? branches.map((b) => {
    const branchStatus = b.fact_id ? resolveFactStatus({ id: b.fact_id, status: b.status }) : (b.status || "proposed");
    const isDropped = b.state === "abandoned" || b.state === "deferred";
    const icon = b.state === "abandoned" ? "✕" : b.state === "deferred" ? "⏸" : branchStatus === "accepted" ? "✓" : "◆";
    const stateClass = isDropped ? "branch-dropped" : branchStatus === "accepted" ? "branch-accepted" : "branch-proposed";
    const tagText = b.state === "abandoned" ? "已舍弃" : b.state === "deferred" ? "已暂缓" : branchStatus === "accepted" ? (isSolo ? "已定案基准" : "团队共识") : (isSolo ? "待定思路" : "候选状态");
    const childrenHTML = (b.children || []).length ? `<div class="thinking-children">${b.children.map((child) => {
      const done = child.task_state === "completed";
      return `<div class="thinking-leaf ${done ? "leaf-done" : ""}" ${child.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(child.fact_id)}"` : ""}>
        <span class="leaf-check">${done ? "☑" : "☐"}</span>
        <span class="leaf-label">${esc(child.label)}</span>
        ${renderEvPills(child.evidence_ids)}
      </div>`;
    }).join("")}</div>` : "";
    return `<div class="thinking-branch-row ${stateClass}">
      <div class="thinking-branch-node" ${b.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(b.fact_id)}"` : ""}>
        <span class="branch-icon">${icon}</span>
        <span class="branch-tag ${stateClass}">${tagText}</span>
        <strong class="branch-label">${esc(b.label)}</strong>
        ${renderEvPills(b.evidence_ids)}
      </div>
      ${childrenHTML}
    </div>`;
  }).join("") : `<div class="thinking-branch-row branch-proposed"><div class="thinking-branch-node"><span class="branch-icon">◆</span><span class="branch-tag">等待提炼</span><strong class="branch-label">从会话对话或项目扫描中提取决策与任务分支后自动连线</strong></div></div>`;

  const codeFooter = codeNodes.length ? `<div class="thinking-code-strip"><span class="code-strip-label">⧉ 关联代码结构 (DerivedContext)：</span>${codeNodes.map((n) => `<span class="code-node-pill ${n.direct ? "direct" : ""}" title="${esc(n.source_ref || "")}">${esc(n.label)}</span>`).join("")}</div>` : "";

  canvasEl.innerHTML = `<div class="thinking-tree">
    <div class="thinking-root ${rootStatus === "accepted" ? "accepted" : "proposed"}" ${root.fact_id ? `role="button" tabindex="0" data-fact-id="${esc(root.fact_id)}"` : ""}>
      <span class="thinking-root-kicker">核心目标锚点</span>
      <strong class="thinking-root-title">${esc(root.label)}</strong>
      <div class="card-pill-row">${renderEvPills(root.evidence_ids)}</div>
    </div>
    <div class="thinking-connector" aria-hidden="true"></div>
    <div class="thinking-branches">${branchHTML}</div>
  </div>${codeFooter}`;
}

function buildPopoverHTML(evidenceId, detail = null, fetchError = "") {
  const catalogEntry = (state.data?.evidence || []).find((item) => item.id === evidenceId) || {};
  const author = detail?.author || catalogEntry.author || detail?.metadata?.member_id || "source";
  const observedAt = detail?.observed_at || catalogEntry.observed_at;
  const kind = detail?.kind || catalogEntry.kind || "record";
  const sourceRef = detail?.metadata?.source_ref || catalogEntry.source_ref || "";
  const rawQuote = detail?.content || catalogEntry.content_preview || catalogEntry.command_preview || (fetchError ? "原文摘录暂不可用，请点击下方按钮核对详情" : "正在加载原文摘录…");
  const cleanedQuote = String(rawQuote).replace(/@\[Quote\]\s*/g, "").replace(/^>+\s*/gm, "").trim();
  const quote = cleanedQuote.length > 320 ? cleanedQuote.slice(0, 318) + "…" : cleanedQuote;
  const errorNote = fetchError ? `<p class="meta-note">原文拉取受限（${esc(fetchError)}）</p>` : "";

  const linkedFacts = [...(state.data?.team?.facts || []), ...(state.data?.personal?.[state.member]?.facts || [])].filter((f) => (f.evidence_ids || []).includes(evidenceId));
  const isSuperseded = linkedFacts.some((f) => f.source_state?.status === "superseded");
  const isUnavailable = linkedFacts.some((f) => f.source_state?.status === "unavailable");
  const freshnessStatus = isUnavailable ? "unavailable" : isSuperseded ? "superseded" : "current";
  const freshnessText = isUnavailable ? "● 暂不可用" : isSuperseded ? "● 已替代" : "● 当前有效";

  return `<div class="popover-head">
    <div class="popover-speaker">
      <span class="speaker-avatar" aria-hidden="true">🔊</span>
      <div>
        <strong class="speaker-name">● ${esc(author)}</strong>
        <span class="speaker-time">${esc(formatTime(observedAt))}${sourceRef ? ` · ${esc(sourceRef)}` : ""}</span>
      </div>
    </div>
    ${renderStatusBadge(freshnessStatus, freshnessText)}
  </div>
  <div class="popover-quote-box">
    <p class="popover-quote">${esc(quote)}</p>
    ${errorNote}
  </div>
  <div class="popover-foot">
    <span class="popover-id">证据编号: ${esc(evidenceId)} · ${esc(kind)}</span>
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
  const sourceKind = ({assistant_message:"助手发言",user_message:"用户发言",tool_call:"工具调用",tool_result:"工具结果",command_execution:"命令执行"})[item.kind] || item.kind || "来源记录";
  const commandNote = item.command_preview ? `<span class="evidence-command">${esc(item.command_preview)}</span><span class="evidence-meta">${esc(commandOriginLabel(item.command_origin))} · 退出码 ${esc(Number.isInteger(item.exit_code) ? item.exit_code : '未知')}</span>` : '';
  return `<button class="evidence-item" data-evidence-id="${esc(item.id)}"><span class="evidence-dot ${safeToken(item.classification, "other")}"></span><span><span class="evidence-title">${esc(item.content_preview || item.id)}</span>${commandNote}<span class="evidence-meta">${esc(sourceKind)} · ${esc(formatTime(item.observed_at))} · ${esc(item.classification)} · ${esc(item.source_ref || item.author)}</span></span><span class="evidence-links">${links ? `${links} 条关联` : "原始"}</span></button>`;
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
      ? `<ul class="brief-item-list">${decisions.map(d => `<li class="brief-item"><strong>${esc(d.value)}</strong><span class="card-pill-row">${renderStatusBadge("accepted")}${renderEvPills(d.evidence_ids)}</span></li>`).join("")}</ul>`
      : `<p class="empty">暂无已确认共识事实。</p>`;

    const candHTML = candidates.length
      ? `<ul class="brief-item-list">${candidates.map(c => `<li class="brief-item"><strong>${esc(c.value)} <small>(${esc(c.author)})</small></strong><span class="card-pill-row">${renderStatusBadge(briefStatus(c))}${renderEvPills(c.evidence_ids)}</span></li>`).join("")}</ul>`
      : `<p class="empty">当前无未决会话候选（已与行动清单合并）。</p>`;

    const todoHTML = todos.length
      ? `<ul class="brief-item-list">${todos.map(t => {
          const isDone = t.task_state === 'completed';
          return `<li class="brief-item"><strong>${isDone ? '☑' : '☐'} ${esc(t.value)} <small>(${esc(t.author)})</small></strong><span class="card-pill-row">${renderStatusBadge(briefStatus(t))}${renderEvPills(t.evidence_ids)}</span></li>`;
        }).join("")}</ul>`
      : `<p class="empty">暂无待办任务。</p>`;

    const codeHTML = codeNodes.length
      ? `<div class="brief-code-grid">${codeNodes.map(n => `<span class="code-node-pill ${n.direct ? 'direct' : ''}">${esc(n.label)}</span>`).join("")}</div>`
      : `<p class="empty">无直接关联代码模块。</p>`;

    content.innerHTML = `
      <section class="brief-section brief-focus-box">
        <span class="eyebrow brief-goal-eyebrow">当前核心目标</span> ${goalStatusBadge}
        <strong>${esc(goal.value || "暂无核心目标")}</strong>
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
      link.download = match ? match[1] : `project-compass-${format}.md`;
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

function bindDrawerControls() {
  const drawer = document.getElementById("evidence-drawer");
  if (!drawer || typeof drawer.querySelectorAll !== "function") return;
  drawer.querySelectorAll("[data-review-id]").forEach((button) => {
    button.onclick = () => confirmRelation(button.dataset.reviewId, button.dataset.factId);
  });
  drawer.querySelectorAll("[data-fact-review-id]").forEach((button) => {
    button.onclick = () => acceptFact(button.dataset.factReviewId, button.dataset.reviewAction || 'accept_fact', { fromDrawer: true });
  });
  drawer.querySelectorAll('[data-direction-review-id]').forEach((button) => {
    button.onclick = () => acceptFact(button.dataset.directionReviewId, button.dataset.directionAction, { fromDrawer: true });
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
  const relations = [...(state.data.candidate_relations || []), ...(state.data.confirmed_relations || [])].filter((relation) => relation.fact_id === fact.id);
  const ids = [...new Set([...(fact.evidence_ids || []), ...relations.map((relation) => relation.evidence_id), ...(fact.source_state?.replacement_ids || []), ...(fact.source_state?.observation_ids || [])])];
  const direction=(state.data.team?.directions?.current || []).find((row)=>row.fact_id===fact.id);
  const dirSuggestion = ["abandoned", "deferred"].includes(fact.direction_suggestion) ? fact.direction_suggestion : "";
  const directionAction=direction ? direction.direction_state === 'active' ? '<p class="reviewed-note">该方案已恢复推进，旧状态保留在历史。</p>' : `<button type="button" class="review-action" data-direction-review-id="${esc(fact.id)}" data-direction-action="restore_direction">恢复推进并保留历史</button>` : dirSuggestion ? `<button type="button" class="review-action" data-direction-review-id="${esc(fact.id)}" data-direction-action="confirm_${dirSuggestion}">确认${dirSuggestion==='abandoned' ? '放弃' : '暂缓'}该方案</button>` : '';
  const rejectBtn = effectiveStatus === "rejected" ? "" : `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}" data-review-action="reject_fact">拒绝候选</button>`;
  const requestBtn = effectiveStatus === "needs_evidence" ? "" : `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}" data-review-action="request_evidence">要求补证据</button>`;
  const reviewActions = canConfirmHere && effectiveStatus !== "accepted" ? `<label class="review-note-label" for="review-note">审核说明（可选）</label><textarea id="review-note" class="review-note-input" rows="2" placeholder="${isSolo ? "定案补充说明或后续待补证据" : "拒绝原因或缺少的具体证据"}"></textarea>${rejectBtn}${requestBtn}` : "";
  const confirmLabel = isSolo && state.lens === "personal" ? "定案为项目基准" : "确认为团队事实";
  const acceptAction = state.data.project?.read_only ? `<p class="empty">当前项目为只读预览，审核请回到该项目的运行窗口。</p>` : !sourceCurrent(fact) ? `<p class="source-warning">${esc(sourceNote(fact))} · 请核对当前来源。原确认与证据仍保留。</p>` : canConfirmHere && directionAction ? directionAction : canConfirmHere && effectiveStatus !== "accepted" ? `<button type="button" class="review-action" data-fact-review-id="${esc(fact.id)}">${confirmLabel}</button>${reviewActions}` : reviewActions;
  const verifiedBlock = renderSpeculativeDetail(fact);
  openDrawer(fact.value, `<div class="detail-block"><div class="detail-value">${sourceTimeHTML(fact)}</div><p class="${effectiveStatus === "accepted" ? "reviewed-note" : "meta-note"}">${esc(fact.session_id || "会话未提供")} · ${effectiveStatus === "accepted" ? (isSolo ? "已拍板定案，来源版本仍可核对" : "负责人已确认，来源版本仍可核对") : "当前有效性待核对"}</p></div><div class="detail-block"><div class="detail-label">事实状态</div><div class="detail-value">${esc(statusLabel(effectiveStatus))} · ${esc(fact.subject_key)}</div>${acceptAction}</div>${verifiedBlock}<div class="detail-block"><div class="detail-label">证据关联</div>${relations.length ? relations.map((relation) => `<div class="relation-item"><button type="button" class="evidence-item" data-evidence-id="${esc(relation.evidence_id)}"><span class="evidence-dot ${relation.status === "confirmed" ? "fact_source" : "execution_result"}"></span><span><span class="evidence-title">${esc(relation.basis)}</span><span class="evidence-meta">${esc(relation.method)} · ${esc(relation.status)} · ${relation.score == null ? "评分未知" : `评分 ${esc(relation.score)}`}</span></span><span class="evidence-links">打开</span></button>${relation.status === "candidate" ? (state.data.project?.read_only ? `<span class="meta-note">只读预览，关联关系待主项目确认</span>` : `<button type="button" class="review-action" data-review-id="${esc(relation.id)}" data-fact-id="${esc(fact.id)}">确认支持关系</button>`) : `<span class="reviewed-note">负责人已确认</span>`}</div>`).join("") : `<p class="empty">暂未提出关联关系。</p>`}</div><div class="detail-block"><div class="detail-label">来源证据编号</div><div class="detail-value">${ids.map(esc).join(" · ") || "证据缺口"}</div></div>`);
}

async function acceptFact(factId, action = 'accept_fact', options = {}) {
  if (state.data.project?.read_only) { openDrawer("只读项目", `<p class="empty">当前项目只读，不能进行负责人确认。</p>`); return; }
  const reviewer = document.getElementById("reviewer-input").value.trim();
  if (!reviewer) {
    openDrawer("署名确认", `<p class="empty">请先填写负责人姓名（个人路线填你自己的署名即可，会自动记住），再确认事实。</p>`);
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

async function confirmRelation(relationId, factId) {
  if (state.data.project?.read_only) { openDrawer("只读项目", `<p class="empty">当前项目只读，不能确认关系。</p>`); return; }
  const reviewer = document.getElementById("reviewer-input").value.trim();
  if (!reviewer) {
    openDrawer("署名确认", `<p class="empty">请先填写负责人姓名（个人路线填你自己的署名即可，会自动记住），再确认这条证据关系。</p>`);
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
    openDrawer("负责人确认失败", `<p class="empty">${esc(error.message)}</p>`);
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
    openDrawer(evidence.id, `<div class="detail-block"><div class="detail-label">来源</div><div class="detail-value">${esc(evidence.metadata?.source_ref || evidence.kind)} · ${esc(evidence.author)} · ${esc(evidence.observed_at)}</div></div>${pairLink}${command}<div class="detail-block"><div class="detail-label">原始材料</div><div class="raw-content">${esc(evidence.content || (evidence.kind === "command_execution" ? "此命令没有文本输出" : ""))}</div></div><div class="detail-block"><div class="detail-label">公开元数据</div><div class="detail-value">${esc(JSON.stringify(evidence.metadata || {}, null, 2))}</div></div>`);
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

document.querySelectorAll(".mode-pill").forEach((button) => button.addEventListener("click", () => { hideCitationPopover(); setWorkMode(button.dataset?.workMode); }));
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
document.getElementById("investigation-form").addEventListener("submit", investigateProject);
document.getElementById("export-state").addEventListener("click", async () => {
  try {
    const exportUrl = state.data?.project?.read_only && state.projectId ? `/api/export?project_id=${encodeURIComponent(state.projectId)}` : '/api/export';
    const response = await apiFetch(exportUrl, { rawResponse: true });
    if (typeof response?.blob === "function" && typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'project-compass-state.json';
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
setInterval(() => { if (!document.hidden) refreshNative(); }, 5000);
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
