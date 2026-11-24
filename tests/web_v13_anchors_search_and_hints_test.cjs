const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

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

const requests = [];
const storage = new Map();
const initialState = {
  project: { project_id: "proj-v13", name: "Compass v13", evidence_count: 1, fact_count: 2, read_only: false },
  projects: [{ project_id: "proj-v13", project_name: "Compass v13" }],
  sample_mode: false,
  llm_status: { enabled: true, mode: "cloud_llm", model: "MiniMax-M2.7", provider_label: "AI 辅助 · MiniMax-M2.7" },
  next_consensus: {
    fact_id: "f-next",
    kind: "task",
    value: "完成双锚点交互走查",
    clean_value: "完成双锚点交互走查",
    short_title: "完成双锚点交互走查",
    status: "accepted",
    evidence_ids: ["e1"],
  },
  agent_hints: [
    {
      id: "hint-1",
      category: "推进建议",
      level: "info",
      text: "建议补全搜索回归验证",
      evidence_ids: ["e1"],
      action_kind: "open_evidence",
      action_label: "查看依据",
      source: "llm",
    },
  ],
  personal: {
    fang: {
      member_id: "fang",
      facts: [
        { id: "g1", kind: "goal", subject_key: "project.goal", value: "打造高掌控工作台", short_title: "打造高掌控工作台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:00:00Z" },
        { id: "f-next", kind: "task", subject_key: "project.next_step", value: "完成双锚点交互走查", short_title: "完成双锚点交互走查", status: "accepted", task_state: "pending", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:01:00Z" },
      ],
      evidence_ids: ["e1"],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "g1", label: "打造高掌控工作台", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
    },
  },
  team: {
    facts: [
      { id: "g1", kind: "goal", subject_key: "project.goal", value: "打造高掌控工作台", short_title: "打造高掌控工作台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:00:00Z" },
      { id: "f-next", kind: "task", subject_key: "project.next_step", value: "完成双锚点交互走查", short_title: "完成双锚点交互走查", status: "accepted", task_state: "pending", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:01:00Z" },
    ],
    evidence_ids: ["e1"],
    conflicts: [],
    directions: { candidates: [], current: [], history: [] },
    timeline_chapters: [],
    thinking_line: { root: { fact_id: "g1", label: "打造高掌控工作台", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
  },
  evidence: [
    { id: "e1", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "摘要", search_excerpt: "详细正文包含正交思维脑图关键词", observed_at: "2026-11-16T07:00:00Z" },
  ],
  candidate_relations: [],
  confirmed_relations: [],
  review_history: [],
  fact_reviews: [],
  session_presence: { team: { accepted_count: 2, pending_count: 0 }, members: [] },
  handoff_brief: { focus_goal: { value: "打造高掌控工作台", status: "accepted", evidence_ids: ["e1"] }, next_consensus: { value: "完成双锚点交互走查", status: "accepted" }, accepted_decisions: [], pending_candidates: [], open_todos: [], code_nodes: [], markdown: "# Brief" },
  intake: { enabled: false },
};

const context = vm.createContext({
  console,
  AbortController,
  setTimeout,
  clearTimeout,
  setInterval() {},
  window: {
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
    },
    addEventListener() {},
  },
  document: {
    hidden: false,
    body: { dataset: {} },
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => element("created-" + Math.random()),
    addEventListener() {},
  },
  fetch: async (url, opts = {}) => {
    requests.push({ url, opts });
    if (url === "/api/notes") {
      const body = JSON.parse(opts.body);
      return {
        ok: true,
        json: async () => ({
          ...initialState,
          next_consensus: {
            fact_id: "f-next-2",
            kind: "task",
            value: body.text,
            clean_value: body.text,
            short_title: body.text,
            status: "accepted",
            evidence_ids: ["e2"],
          },
          quick_note: { accepted: true, kind: body.kind },
        }),
      };
    }
    return { ok: true, json: async () => initialState };
  },
});

async function main() {
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await new Promise((r) => setTimeout(r, 20));

  assert.equal(element("llm-status-badge").textContent, "AI 辅助 · MiniMax-M2.7");
  assert.equal(element("goal-title").textContent, "打造高掌控工作台");
  assert.equal(element("next-consensus-title").textContent, "完成双锚点交互走查");

  const hintsHtml = element("agent-hints-list").innerHTML;
  assert.ok(hintsHtml.includes("建议补全搜索回归验证"));
  assert.ok(!hintsHtml.includes("军师") && !hintsHtml.includes("锦囊"));

  // Dismiss hint persists in localStorage and hides surface when none remain
  vm.runInContext('dismissHint("hint-1")', context);
  assert.equal(element("agent-hints-surface").hidden, true);

  // Full-text search_excerpt matching works in #evidence-filter
  vm.runInContext('state.evidenceQuery = "正交思维脑图"; render();', context);
  assert.equal(element("spine-count").textContent, "1/1");

  // Inline next_step edit submits POST /api/notes with topic=next_step & auto_accept=true
  vm.runInContext('openAnchorInlineForm("next_step", "旧焦点")', context);
  element("anchor-inline-input").value = "发布 v1.3 对比评测";
  await vm.runInContext("saveAnchorInlineForm({ preventDefault() {} })", context);
  const noteReq = requests.find((r) => r.url === "/api/notes");
  assert.ok(noteReq, "saveAnchorInlineForm did not submit /api/notes");
  const parsedBody = JSON.parse(noteReq.opts.body);
  assert.equal(parsedBody.kind, "task");
  assert.equal(parsedBody.topic, "next_step");
  assert.equal(parsedBody.auto_accept, true);
  assert.equal(element("next-consensus-title").textContent, "发布 v1.3 对比评测");

  // renderInvestigation renders semantic_summary cleanly
  context.ansFixture = {
    conclusion: "匹配成功",
    semantic_summary: "已采纳正交脑图作为右侧主视图。",
    goal: "打造高掌控工作台",
    next_action: "**完成发布**",
    acceptance_condition: "通过全部校验",
    active_tasks: [],
    evidence_ids: ["e1"],
    findings: [],
    conflicts: [],
    evidence_gaps: ["补充说明"],
  };
  vm.runInContext("renderInvestigation(ansFixture)", context);
  const invHtml = element("investigation-answer").innerHTML;
  assert.ok(invHtml.includes("语义归纳") && invHtml.includes("已采纳正交脑图作为右侧主视图"));
  assert.ok(!invHtml.includes("**完成发布**"));

  console.log("v1.3 dual anchors, Agent hints, inline next_step save, search_excerpt & semantic summary verified.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
