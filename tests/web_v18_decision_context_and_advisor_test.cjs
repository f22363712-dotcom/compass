const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const appPath = process.argv[2] || "src/project_compass/web/app.js";
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const cls = new Set();
    elements.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      value: "",
      placeholder: "",
      checked: false,
      disabled: false,
      readOnly: false,
      hidden: false,
      dataset: {},
      attributes: {},
      classList: {
        toggle(k, force) { force === undefined ? (cls.has(k) ? cls.delete(k) : cls.add(k)) : (force ? cls.add(k) : cls.delete(k)); },
        add(...ks) { ks.forEach((k) => cls.add(k)); },
        remove(...ks) { ks.forEach((k) => cls.delete(k)); },
        contains(k) { return cls.has(k); },
      },
      addEventListener(type, fn) { this["on" + type] = fn; },
      setAttribute(k, v) { this.attributes[k] = String(v); },
      removeAttribute(k) { delete this.attributes[k]; },
      focus() {},
      append() {},
      appendChild() {},
      prepend() {},
      querySelector(sel) {
        if (sel === ".answer-evidence-list") return element(id + "-child");
        if (sel === ".answer-grid .detail-value") return element(id + "-grid-val");
        return element(id + "-q");
      },
      querySelectorAll() { return []; },
    });
  }
  return elements.get(id);
}

const storage = new Map();
const initialState = {
  project: { project_id: "proj-v16", name: "Compass v16", evidence_count: 2, fact_count: 2, read_only: false },
  projects: [{ project_id: "proj-v16", project_name: "Compass v16" }],
  sample_mode: false,
  project_scan: { enabled: true, last_checked_at: "2026-11-20T09:00:00Z" },
  intake: { enabled: true, refreshable: false, channel: "antigravity", member_id: "fang", captured_messages: 7, direction_scan: { enabled: false }, user_task_scan: { enabled: false } },
  llm_status: { enabled: false, mode: "local", model: null, provider_label: "本地检索" },
  next_consensus: { fact_id: "f-next", kind: "task", value: "验证因果抽屉", short_title: "验证因果抽屉", status: "accepted", evidence_ids: ["e1"] },
  agent_hints: [
    { id: "h-prem", category: "未验前提", level: "warn", text: "方案前提尚未核实", evidence_ids: ["e1"], fact_id: "f-fork", action_kind: "open_fact", action_label: "核查前提", source: "local" },
    { id: "h-blind", category: "盲区预警", level: "warn", text: "疑似重提已否决方案", evidence_ids: ["e2"], fact_id: "f-fork", action_kind: "open_fact", action_label: "对照原由", source: "local" },
  ],
  personal: {
    fang: {
      member_id: "fang",
      facts: [
        { id: "f-goal", kind: "goal", subject_key: "project.goal", value: "零依赖掌控台", short_title: "零依赖掌控台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-20T08:00:00Z" },
        {
          id: "f-fork",
          kind: "decision",
          subject_key: "decision.fork.abc",
          value: "刷新策略在三秒轮询与 SSE 间权衡",
          short_title: "刷新策略待权衡",
          status: "proposed",
          author: "fang",
          evidence_ids: ["e2"],
          observed_at: "2026-11-20T08:05:00Z",
          decision_context: {
            stage: "open_fork",
            alternatives: ["方案 A: 三秒轮询", "方案 B: 长连接 SSE"],
            premises: [{ fact_id: "f-prem", title: "构建耗时 < 200ms", status: "unverified", evidence_ids: ["e1"] }],
            rejected_paths: [{ fact_id: "f-rej", title: "放弃外部向量库", reason: "破坏零依赖", evidence_ids: ["e2"] }],
          },
        },
      ],
      evidence_ids: ["e1", "e2"],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: {
        root: { fact_id: "f-goal", label: "零依赖掌控台", status: "accepted", evidence_ids: ["e1"] },
        branches: [
          {
            branch_id: "dec-f-fork",
            fact_id: "f-fork",
            kind: "decision",
            state: "chosen",
            causal_stage: "open_fork",
            fork_count: 2,
            premise_state: "unverified",
            status: "proposed",
            label: "刷新策略待权衡",
            full_label: "刷新策略在三秒轮询与 SSE 间权衡",
            evidence_ids: ["e2"],
            children: [],
          },
        ],
        reversals: [],
        code_nodes: [],
      },
    },
  },
  state_version: 3,
  team: {
    facts: [
      { id: "f-goal", kind: "goal", subject_key: "project.goal", value: "零依赖掌控台", short_title: "零依赖掌控台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-20T08:00:00Z" },
      {
        id: "f-fork",
        kind: "decision",
        subject_key: "decision.fork.abc",
        value: "刷新策略在三秒轮询与 SSE 间权衡",
        short_title: "刷新策略待权衡",
        status: "proposed",
        author: "fang",
        evidence_ids: ["e2"],
        observed_at: "2026-11-20T08:05:00Z",
        decision_context: {
          stage: "open_fork",
          alternatives: ["方案 A: 三秒轮询", "方案 B: 长连接 SSE"],
          premises: [{ fact_id: "f-prem", title: "构建耗时 < 200ms", status: "unverified", evidence_ids: ["e1"] }],
          rejected_paths: [{ fact_id: "f-rej", title: "放弃外部向量库", reason: "破坏零依赖", evidence_ids: ["e2"] }],
        },
      },
    ],
    evidence_ids: ["e1", "e2"],
    conflicts: [],
    directions: { candidates: [], current: [], history: [] },
    timeline_chapters: [],
    thinking_line: { root: { fact_id: "f-goal", label: "零依赖掌控台", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
  },
  evidence: [
    { id: "e1", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "目标", observed_at: "2026-11-20T08:00:00Z" },
    { id: "e2", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "选型分叉", observed_at: "2026-11-20T08:05:00Z" },
  ],
  candidate_relations: [],
  confirmed_relations: [],
  review_history: [],
  fact_reviews: [],
  session_presence: { team: { accepted_count: 1, pending_count: 1 }, members: [] },
  handoff_brief: { focus_goal: { value: "零依赖掌控台", status: "accepted", evidence_ids: ["e1"] }, next_consensus: { value: "验证因果抽屉", status: "accepted" }, accepted_decisions: [], pending_candidates: [], open_todos: [], code_nodes: [], markdown: "# Brief" },
};

const requestedUrls = [];
const context = vm.createContext({
  console,
  AbortController,
  setTimeout,
  clearTimeout,
  setInterval() {},
  window: {
    localStorage: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)) },
    addEventListener() {},
  },
  document: {
    hidden: false,
    body: { dataset: {} },
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => element("created-" + Math.random()),
    addEventListener: () => {},
  },
  fetch: async (url) => {
    requestedUrls.push(String(url));
    const body = String(url).includes("since_version=")
      ? {
          unchanged: true,
          state_version: 3,
          intake: { ...initialState.intake, captured_messages: 8 },
          project_scan: initialState.project_scan,
          llm_status: initialState.llm_status,
          agent_hints: initialState.agent_hints,
          hint_generation: 1,
        }
      : initialState;
    return {
      ok: true,
      json: async () => body,
      text: async () => JSON.stringify(body),
    };
  },
});

async function main() {
  vm.runInContext(fs.readFileSync(appPath, "utf8"), context, { filename: appPath });
  await new Promise((r) => setTimeout(r, 30));

  const syncLabel = element("sync-time-label").textContent;
  assert.match(syncLabel, /已同步对话 7 条/);
  const pendingHtml = element("personal-decision-list").innerHTML;
  assert.match(pendingHtml, /多选方案/);
  assert.match(pendingHtml, /前提待核实/);
  const mindmapHtml = element("thinking-line-canvas").innerHTML;
  assert.match(mindmapHtml, /多选 · 2/);
  assert.match(mindmapHtml, /前提待核实/);
  const hintsHtml = element("agent-hints-list").innerHTML;
  assert.match(hintsHtml, /待核实假设/);
  assert.match(hintsHtml, /踩坑提醒/);
  assert.match(hintsHtml, /data-hint-action="open_fact"/);

  await vm.runInContext("refreshNative({ backgroundPoll: true })", context);
  assert.equal(requestedUrls[requestedUrls.length - 1], "/api/state?since_version=3");
  assert.match(element("sync-time-label").textContent, /已同步对话 8 条/);

  vm.runInContext('openFact("f-fork")', context);
  const drawerHtml = element("drawer-body").innerHTML;
  assert.match(drawerHtml, /多个备选方案/);
  assert.match(drawerHtml, /方案 A: 三秒轮询/);
  assert.match(drawerHtml, /依赖前提条件/);
  assert.match(drawerHtml, /关联已淘汰方案/);
  assert.match(drawerHtml, /破坏零依赖/);
  console.log("web_v18_decision_context_and_advisor_test PASSED");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
