const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const appPath = process.argv[2];
const htmlPath = path.join(path.dirname(appPath), "index.html");
const appSource = fs.readFileSync(appPath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");

function makeHarness(initialState) {
  let currentState = JSON.parse(JSON.stringify(initialState));
  const elements = new Map();
  const requests = [];
  const intervals = [];

  function makeClassList(node) {
    const set = new Set();
    return {
      add: (...cls) => { cls.forEach((c) => c && set.add(c)); node.className = [...set].join(" "); },
      remove: (...cls) => { cls.forEach((c) => set.delete(c)); node.className = [...set].join(" "); },
      toggle: (cls, force) => {
        if (force === undefined) {
          if (set.has(cls)) set.delete(cls); else set.add(cls);
        } else if (force) set.add(cls);
        else set.delete(cls);
        node.className = [...set].join(" ");
        return set.has(cls);
      },
      contains: (cls) => set.has(cls) || String(node.className || "").split(/\s+/).includes(cls),
    };
  }

  function makeNode(id, dataset = {}) {
    const node = {
      id,
      dataset: { ...dataset },
      innerHTML: "",
      textContent: "",
      value: "",
      checked: false,
      hidden: false,
      disabled: false,
      readOnly: false,
      placeholder: "",
      className: "",
      attributes: {},
      scrollLeft: 0,
      scrollWidth: 400,
      clientWidth: 200,
      focus: () => {},
      click: () => { if (typeof node.onclick === "function") return node.onclick({ preventDefault() {}, stopPropagation() {} }); },
      addEventListener: (ev, cb) => { node[`on${ev}`] = cb; },
      setAttribute: (k, v) => { node.attributes[k] = String(v); },
      removeAttribute: (k) => { delete node.attributes[k]; },
      append: () => {},
      prepend: () => {},
      appendChild: () => {},
      removeChild: () => {},
      querySelector: () => null,
      querySelectorAll: () => [],
    };
    node.classList = makeClassList(node);
    return node;
  }

  function element(id) {
    if (!elements.has(id)) elements.set(id, makeNode(id));
    return elements.get(id);
  }

  const workbenchBtns = [
    makeNode("view-list-btn", { workbenchView: "list" }),
    makeNode("view-mindmap-btn", { workbenchView: "mindmap" }),
  ];
  elements.set("view-list-btn", workbenchBtns[0]);
  elements.set("view-mindmap-btn", workbenchBtns[1]);

  const context = vm.createContext({
    console,
    AbortController,
    setTimeout,
    clearTimeout,
    setInterval: (cb, ms) => { intervals.push({ cb, ms }); return intervals.length; },
    URL: { createObjectURL: () => "blob:v12", revokeObjectURL: () => {} },
    window: { localStorage: { getItem: () => null, setItem: () => {} }, addEventListener: () => {} },
    document: {
      hidden: false,
      body: { dataset: {}, appendChild() {}, removeChild() {} },
      activeElement: null,
      getElementById: element,
      querySelector: (sel) => (sel.startsWith("#") ? element(sel.slice(1)) : null),
      querySelectorAll: (sel) => (sel === ".workbench-view-btn" ? workbenchBtns : []),
      createElement: (tag) => makeNode(`created:${tag}`),
      addEventListener: () => {},
    },
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => JSON.parse(JSON.stringify(currentState)) };
    },
  });

  vm.runInContext(appSource, context);
  return {
    context,
    element,
    requests,
    intervals,
    workbenchBtns,
    setState: (next) => { currentState = JSON.parse(JSON.stringify(next)); },
    flush: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

async function main() {
  // 1. HTML copy slimming guard
  assert.ok(!htmlSource.includes("Ask Compass"), "index.html still contains Ask Compass");
  assert.ok(htmlSource.includes("查证据</button>"), "index.html missing 查证据 submit label");
  assert.ok(!htmlSource.includes("核心焦点 //"), "index.html still has verbose // kicker");

  // 2. Empty 0->1 project welcome + fallback goal + zero-config live auto-growth
  const emptyState = {
    state_version: 1,
    project: { project_id: "p0", name: "fresh-app", read_only: false, evidence_count: 0, fact_count: 0 },
    projects: [],
    sample_mode: false,
    intake: { enabled: false },
    agent_api: { enabled: false },
    personal: {
      fang: {
        member_id: "fang",
        evidence_ids: [],
        facts: [],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: {
          root: { fact_id: null, label: "核心目标待确定", status: "empty", evidence_ids: [] },
          branches: [],
          historical_archive: { count: 0, label: "", items: [] },
          reversals: [],
          code_nodes: [],
        },
      },
    },
    team: { facts: [], evidence_ids: [], conflicts: [], directions: { candidates: [], current: [], history: [] }, timeline_chapters: [], thinking_line: { root: { label: "核心目标待确定", status: "empty", evidence_ids: [] }, branches: [], historical_archive: { count: 0, label: "", items: [] }, reversals: [], code_nodes: [] } },
    activity_stream: [],
    personal_activity: [],
    evidence: [],
    candidate_relations: [],
    confirmed_relations: [],
    review_history: [],
    fact_reviews: [],
    team_review_queue: [],
    handoff_brief: { focus_goal: { fact_id: null, value: "核心目标待确定", status: "empty", evidence_ids: [] }, accepted_decisions: [], pending_candidates: [], open_todos: [], code_nodes: [], markdown: "" },
  };

  const h = makeHarness(emptyState);
  await h.flush();

  assert.ok(h.element("hero-copy").textContent.includes("新项目已就绪"), "Empty 0->1 welcome copy missing");
  assert.equal(h.element("goal-title").textContent, "核心目标待确定");
  assert.equal(h.intervals[0].ms, 3000, "Live polling interval must be 3000ms");

  // Switch to mindmap & simulate user typing a quick note AND having drawer open
  h.workbenchBtns[1].click();
  h.element("quick-note-input").value = "正在输入中的想法不被轮询清空";
  h.element("evidence-drawer").hidden = false;
  h.element("drawer-body").innerHTML = "<p>正在核对的原文证据</p>";

  // Simulate external MCP record_note + legacy repo archive arriving while intake/extraction are off (zero-config)
  const grownState = {
    ...emptyState,
    state_version: 2,
    project: { project_id: "p0", name: "fresh-app", read_only: false, evidence_count: 2, fact_count: 2 },
    personal: {
      fang: {
        member_id: "fang",
        evidence_ids: ["scan-file-deadbeef1234", "note-live-1"],
        fallback_goal: { id: "g-team", kind: "goal", value: "打造零配置实时记忆工作台", short_title: "零配置实时记忆工作台", status: "accepted", evidence_ids: ["note-live-1"] },
        facts: [
          { id: "d-live", kind: "decision", subject_key: "note.decision.1", value: "采用单文件标准库记录思路", short_title: "单文件标准库记思路", status: "proposed", author: "fang", evidence_ids: ["note-live-1"] },
        ],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: {
          root: { fact_id: "g-team", label: "零配置实时记忆工作台", status: "accepted", evidence_ids: ["note-live-1"] },
          branches: [
            { branch_id: "b1", fact_id: "d-live", kind: "decision", state: "chosen", status: "proposed", label: "单文件标准库记思路", full_label: "采用单文件标准库记录思路", evidence_ids: ["note-live-1"], children: [] },
          ],
          historical_archive: {
            count: 1,
            label: "历史文档参考（1 条）",
            items: [{ fact_id: "f-doc", kind: "decision", status: "proposed", label: "历史文档去日期短标题", full_label: "2026-10-26 long raw text", source_ref: "DECISIONS.md", evidence_ids: ["scan-file-deadbeef1234"] }],
          },
          reversals: [],
          code_nodes: [],
        },
      },
    },
    team: {
      facts: [
        { id: "g-team", kind: "goal", subject_key: "project.goal", value: "打造零配置实时记忆工作台", short_title: "零配置实时记忆工作台", status: "accepted", author: "fang", evidence_ids: ["note-live-1"] },
        { id: "d-live", kind: "decision", subject_key: "note.decision.1", value: "采用单文件标准库记录思路", short_title: "单文件标准库记思路", status: "proposed", author: "fang", evidence_ids: ["note-live-1"] },
        { id: "f-doc", kind: "decision", subject_key: "doc.1", value: "2026-10-26 long raw text", short_title: "历史文档去日期短标题", status: "proposed", author: "project-documents", is_historical_doc: true, evidence_ids: ["scan-file-deadbeef1234"] },
      ],
      evidence_ids: ["scan-file-deadbeef1234", "note-live-1"],
      conflicts: [],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "g-team", label: "零配置实时记忆工作台", status: "accepted", evidence_ids: ["note-live-1"] }, branches: [], historical_archive: { count: 0, label: "", items: [] }, reversals: [], code_nodes: [] },
    },
    activity_stream: [
      { id: "note-live-1", member_id: "fang", action_kind: "note", action_label: "随手记", summary: "单文件标准库记思路", observed_at: "2026-11-16T04:00:00Z", exit_code: null, evidence_ids: ["note-live-1"], primary_evidence_id: "note-live-1", collapsed_count: 1 },
    ],
    evidence: [
      { id: "scan-file-deadbeef1234", kind: "file_snapshot", author: "project-documents", content_preview: "doc" },
      { id: "note-live-1", kind: "user_message", author: "fang", content_preview: "采用单文件标准库记录思路" },
    ],
  };

  h.setState(grownState);
  await h.intervals[0].cb();
  await h.flush();

  assert.equal(h.requests.filter((u) => u === "/api/state").length, 2, "Zero-config polling did not call GET /api/state");
  assert.equal(h.element("quick-note-input").value, "正在输入中的想法不被轮询清空", "Polling clobbered user input!");
  assert.equal(h.element("evidence-drawer").hidden, false, "Polling closed active drawer!");
  assert.equal(h.element("goal-title").textContent, "零配置实时记忆工作台", "Personal view did not inherit fallback_goal");
  assert.ok(h.element("hero-copy").textContent.includes("1 项已定案 · 1 项待拍板"), `Unexpected hero copy: ${h.element("hero-copy").textContent}`);

  const decHTML = h.element("personal-decision-list").innerHTML;
  assert.ok(decHTML.includes("依据 · 1"), "Ev pill did not render human 依据 · 1 badge");
  assert.ok(!decHTML.includes("[note-live-1]") && !decHTML.includes("[scan-file-deadbeef1234]"), "Card surface exposed raw bracketed evidence ID");
  assert.ok(decHTML.includes("is-fresh-node"), "Newly arrived decision card missing is-fresh-node highlight");

  const treeHTML = h.element("thinking-line-canvas").innerHTML;
  assert.ok(treeHTML.includes("单文件标准库记思路"), "Mindmap missing concise branch short_title");
  assert.ok(treeHTML.includes("is-fresh-node"), "Mindmap missing fresh highlight class");
  assert.ok(treeHTML.includes('class="historical-archive-capsule"'), "Mindmap missing collapsible historical archive capsule");
  assert.ok(treeHTML.includes("历史文档参考（1 条）") && !treeHTML.includes("2026-10-26 long raw text</strong"), "Archive exposed raw date wall on main title");

  console.log("v1.2 UI copy slimming, human ev pills, historical archive capsule, fallback goal & live auto-growth tests passed.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
