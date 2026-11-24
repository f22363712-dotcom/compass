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
      title: "",
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
      prepend() { throw new Error("source_warnings must not prepend to the top of #investigation-answer"); },
      querySelector(sel) {
        if (sel === ".answer-evidence-list") return element(id + "-child");
        return element(id + "-q");
      },
      querySelectorAll() { return []; },
    });
  }
  return elements.get(id);
}

const requests = [];
const stateDay1 = {
  project: { project_id: "proj-v14", name: "Compass v14", evidence_count: 1, fact_count: 2, read_only: false },
  projects: [{ project_id: "proj-v14", project_name: "Compass v14" }],
  project_scan: { enabled: true, last_checked_at: "2026-11-17T11:20:00Z", updated: false },
  sample_mode: false,
  llm_status: {
    enabled: true,
    mode: "cloud_llm",
    model: "MiniMax-M3.1-Flash",
    provider_label: "AI 辅助 · MiniMax-M3.1-Flash",
    active_profile: "minimax-m3.1-flash",
    profiles: [
      { id: "minimax-m3.1-flash", label: "MiniMax-M3.1-Flash", mode: "cloud_llm", model: "MiniMax-M3.1-Flash" },
      { id: "deepseek-chat", label: "DeepSeek-Chat", mode: "cloud_llm", model: "deepseek-chat" },
      { id: "local", label: "本地检索", mode: "local", model: "" },
    ],
  },
  next_consensus: {
    fact_id: "f-next",
    kind: "task",
    value: "完成双极速模型横评并封板 v1.4",
    short_title: "完成双极速模型横评并封板 v1.4",
    status: "accepted",
    evidence_ids: ["e1"],
  },
  personal: {
    fang: {
      member_id: "fang",
      facts: [
        { id: "g1", kind: "goal", subject_key: "project.goal", value: "打造低认知负载项目掌控台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:00:00Z" },
      ],
      evidence_ids: ["e1"],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "g1", label: "打造低认知负载项目掌控台", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
    },
  },
  team: {
    facts: [
      { id: "g1", kind: "goal", subject_key: "project.goal", value: "打造低认知负载项目掌控台", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-16T07:00:00Z" },
    ],
    evidence_ids: ["e1"],
    conflicts: [],
    directions: { candidates: [], current: [], history: [] },
    timeline_chapters: [],
    thinking_line: { root: { fact_id: "g1", label: "打造低认知负载项目掌控台", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
  },
  evidence: [{ id: "e1", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "摘要", observed_at: "2026-11-16T07:00:00Z" }],
  candidate_relations: [],
  confirmed_relations: [],
  fact_reviews: [],
  review_history: [],
  evidence_requests: [],
  activity_stream: [],
  agent_hints: [],
};

const stateDeepSeek = {
  ...stateDay1,
  llm_status: {
    ...stateDay1.llm_status,
    model: "deepseek-chat",
    provider_label: "AI 辅助 · deepseek-chat",
    active_profile: "deepseek-chat",
  },
};

const context = vm.createContext({
  console,
  AbortController,
  setTimeout,
  clearTimeout,
  setInterval() {},
  window: { localStorage: { getItem: () => "", setItem: () => {} }, addEventListener() {} },
  document: {
    hidden: false,
    body: { dataset: {} },
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: (tag) => element("created-" + tag),
    addEventListener() {},
  },
  fetch: async (url, opts = {}) => {
    requests.push({ url, opts });
    if (url === "/api/llm-mode") {
      return { ok: true, json: async () => stateDeepSeek };
    }
    if (url === "/api/investigate") {
      return {
        ok: true,
        json: async () => ({
          semantic_summary: "当前核心目标是打造低认知负载掌控台；下一步是完成双极速模型横评并封板 v1.4。",
          conclusion: "兼容总结",
          goal: "打造低认知负载项目掌控台",
          next_action: "完成双极速模型横评并封板 v1.4",
          next_action_status: "accepted",
          acceptance_condition: "通过全量测试",
          evidence_ids: ["e1"],
          completed_items: [
            { fact_id: "c1", kind: "task", status: "reported_complete", observed_at: "2026-11-17T10:00:00Z", evidence_ids: ["e1"], quote: "2026-11-17 完成核心文档自动热同步" },
          ],
          findings: [],
          conflicts: [],
          evidence_gaps: ["边界说明"],
          source_warnings: [
            { fact_id: "old-doc-1", status: "proposed", evidence_ids: ["e1"], source_state: { status: "superseded", replacement_ids: [], observation_ids: [] } },
          ],
        }),
      };
    }
    return { ok: true, json: async () => stateDay1 };
  },
});

async function main() {
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await new Promise((r) => setTimeout(r, 20));

  // Verify topbar model selector renders options & selects active_profile
  const selectEl = element("llm-profile-select");
  assert.equal(selectEl.hidden, false);
  assert.equal(selectEl.value, "minimax-m3.1-flash");
  assert.ok(selectEl.innerHTML.includes("DeepSeek-Chat") && selectEl.innerHTML.includes("本地检索"));

  // Verify topbar sync time indicator renders cleanly
  const syncEl = element("sync-time-label");
  assert.equal(syncEl.hidden, false);
  assert.ok(syncEl.textContent.includes("· 同步 "));

  // Verify pyramid answer places semantic_summary -> completed_items -> takeaways (current goal + settled next step) BEFORE evidence and folds source_warnings at the bottom!
  element("investigation-question").value = "最近完成的工作是什么";
  await vm.runInContext("investigateProject({ preventDefault() {} })", context);
  const invHtml = element("investigation-answer").innerHTML;
  const idxSummary = invHtml.indexOf("answer-semantic-summary");
  const idxCompleted = invHtml.indexOf("is-completed-focus");
  const idxGoal = invHtml.indexOf("打造低认知负载项目掌控台");
  const idxNext = invHtml.indexOf("takeaway-next-text");
  const idxEv = invHtml.indexOf("answer-evidence-section");
  const idxWarn = invHtml.indexOf("answer-warnings-fold");
  assert.ok(
    idxSummary >= 0 && idxCompleted > idxSummary && idxGoal > idxCompleted && idxNext > idxGoal && idxEv > idxNext && idxWarn > idxEv,
    "Pyramid visual hierarchy order with completed_items violated"
  );
  assert.ok(invHtml.includes("近期已完成事项") && invHtml.includes("2026-11-17 完成核心文档自动热同步"));
  assert.ok(invHtml.includes("历史来源变动复核明细（1 项 · 默认折叠）"));
  assert.ok(!invHtml.includes('answer-warnings-fold" open'));

  // Verify switching model posts to /api/llm-mode and auto-refreshes open investigation
  await vm.runInContext('switchLlmProfile("deepseek-chat")', context);
  assert.ok(requests.some((r) => r.url === "/api/llm-mode" && r.opts.body.includes("deepseek-chat")));
  assert.equal(element("llm-status-badge").textContent, "AI 辅助 · deepseek-chat");
  assert.ok(requests.filter((r) => r.url === "/api/investigate").length >= 2, "Switching model should refresh open answer");

  console.log("v1.4 pyramid answer, bottom folded source_warnings & runtime model switcher verified.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
