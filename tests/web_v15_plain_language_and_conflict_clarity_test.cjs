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
      hidden: false,
      dataset: {},
      style: {},
      offsetWidth: 320,
      offsetHeight: 180,
      attributes: {},
      classList: {
        toggle(k, force) { force === undefined ? (cls.has(k) ? cls.delete(k) : cls.add(k)) : (force ? cls.add(k) : cls.delete(k)); },
        add(...ks) { ks.forEach((k) => cls.add(k)); },
        remove(...ks) { ks.forEach((k) => cls.delete(k)); },
        contains(k) { return cls.has(k); },
      },
      addEventListener() {},
      setAttribute(k, v) { this.attributes[k] = String(v); },
      removeAttribute(k) { delete this.attributes[k]; },
      getBoundingClientRect() { return { left: 100, top: 120, right: 200, bottom: 148, width: 100, height: 28 }; },
      focus() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    });
  }
  return elements.get(id);
}

const statePayload = {
  project: { project_id: "proj-v15", name: "Compass v15 UX", evidence_count: 4, fact_count: 4, read_only: false },
  projects: [{ project_id: "proj-v15", project_name: "Compass v15 UX" }],
  sample_mode: false,
  personal: {
    fang: {
      member_id: "fang",
      facts: [
        // 1. Superseded earlier next_step task
        {
          id: "old-next",
          kind: "task",
          task_state: "pending",
          subject_key: "project.next_step",
          value: "完成 v1.3 看板实测与三方基准验收",
          status: "conflicted",
          author: "fang",
          evidence_ids: ["note-old"],
          observed_at: "2026-11-16T08:27:41Z",
        },
        // 2. Newer accepted next_step fact
        {
          id: "new-next",
          kind: "task",
          task_state: "pending",
          subject_key: "project.next_step",
          value: "审阅漫剧演示剧本并发布 v1.4.0",
          status: "accepted",
          author: "fang",
          evidence_ids: ["note-new"],
          observed_at: "2026-11-17T11:13:23Z",
        },
        // 3. True unresolved conflict on dec.db (same/newer post-accept divergence or unaccepted two-way)
        {
          id: "db-a",
          kind: "decision",
          subject_key: "dec.db",
          value: "使用纯本地 JSON 文件账本",
          status: "accepted",
          author: "fang",
          evidence_ids: ["ev-dba"],
          observed_at: "2026-11-17T08:00:00Z",
        },
        {
          id: "db-b",
          kind: "decision",
          subject_key: "dec.db",
          value: "改用远程云端数据库存储",
          status: "conflicted",
          author: "alice",
          evidence_ids: ["ev-dbb"],
          observed_at: "2026-11-17T09:00:00Z",
        },
      ],
      evidence_ids: ["note-old", "note-new", "ev-dba", "ev-dbb"],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { label: "项目目标", status: "empty", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] },
    },
  },
  team: {
    facts: [
      {
        id: "old-next",
        kind: "task",
        task_state: "pending",
        subject_key: "project.next_step",
        value: "完成 v1.3 看板实测与三方基准验收",
        status: "conflicted",
        author: "fang",
        evidence_ids: ["note-old"],
        observed_at: "2026-11-16T08:27:41Z",
      },
      {
        id: "new-next",
        kind: "task",
        task_state: "pending",
        subject_key: "project.next_step",
        value: "审阅漫剧演示剧本并发布 v1.4.0",
        status: "accepted",
        author: "fang",
        evidence_ids: ["note-new"],
        observed_at: "2026-11-17T11:13:23Z",
      },
      {
        id: "db-a",
        kind: "decision",
        subject_key: "dec.db",
        value: "使用纯本地 JSON 文件账本",
        status: "accepted",
        author: "fang",
        evidence_ids: ["ev-dba"],
        observed_at: "2026-11-17T08:00:00Z",
      },
      {
        id: "db-b",
        kind: "decision",
        subject_key: "dec.db",
        value: "改用远程云端数据库存储",
        status: "conflicted",
        author: "alice",
        evidence_ids: ["ev-dbb"],
        observed_at: "2026-11-17T09:00:00Z",
      },
    ],
    evidence_ids: ["note-old", "note-new", "ev-dba", "ev-dbb"],
    conflicts: [],
    directions: { candidates: [], current: [], history: [] },
    timeline_chapters: [],
    thinking_line: { root: { label: "项目目标", status: "empty", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] },
  },
  evidence: [
    { id: "note-old", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "完成 v1.3 看板实测与三方基准验收", source_ref: "web://quick-note", observed_at: "2026-11-16T08:27:41Z" },
    { id: "note-new", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "审阅漫剧演示剧本并发布 v1.4.0", source_ref: "web://quick-note", observed_at: "2026-11-17T11:13:23Z" },
    { id: "ev-dba", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "使用纯本地 JSON 文件账本", source_ref: "web://quick-note", observed_at: "2026-11-17T08:00:00Z" },
    { id: "ev-dbb", kind: "assistant_message", author: "alice", classification: "fact_source", content_preview: "改用远程云端数据库存储", source_ref: "mcp://record-note", observed_at: "2026-11-17T09:00:00Z" },
  ],
  evidence_records: {
    "note-old": { id: "note-old", kind: "user_message", author: "fang", content: "完成 v1.3 看板实测与三方基准验收", observed_at: "2026-11-16T08:27:41Z", metadata: { source_ref: "web://quick-note", note_kind: "task" } },
    "ev-dbb": { id: "ev-dbb", kind: "assistant_message", author: "alice", content: "改用远程云端数据库存储", observed_at: "2026-11-17T09:00:00Z", metadata: { source_ref: "mcp://record-note", note_kind: "decision" } },
  },
  candidate_relations: [],
  confirmed_relations: [],
  fact_reviews: [],
  review_history: [],
  evidence_requests: [],
  activity_stream: [],
  agent_hints: [],
};

const context = vm.createContext({
  console,
  AbortController,
  setTimeout,
  clearTimeout,
  setInterval() {},
  window: { localStorage: { getItem: () => "", setItem: () => {} }, innerWidth: 1440, innerHeight: 900, addEventListener() {} },
  document: {
    hidden: false,
    body: { dataset: {} },
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: (tag) => element("created-" + tag),
    addEventListener() {},
  },
  fetch: async (url) => {
    if (String(url).startsWith("/api/evidence")) {
      const id = decodeURIComponent(String(url).split("id=")[1].split("&")[0]);
      return { ok: true, json: async () => statePayload.evidence_records[id] };
    }
    return { ok: true, json: async () => statePayload };
  },
});

async function main() {
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await new Promise((r) => setTimeout(r, 20));

  // 1. Active todo list excludes superseded old task & folds it cleanly at bottom without false conflict badge
  const todoHtml = element("personal-todo-list").innerHTML;
  assert.equal(element("personal-todos-count").textContent, 1, "Only active todo count should display");
  assert.ok(!todoHtml.includes("任务状态：pending"), "Raw English task_state 'pending' leaked into todo card");
  assert.ok(todoHtml.includes("进度：待推进"), "Plain-language Chinese todo progress missing");
  assert.ok(todoHtml.includes("superseded-todos-fold") && todoHtml.includes("历史已接替记录（1 条 · 默认折叠）"));
  assert.ok(todoHtml.includes("已由新定案接替") && !todoHtml.includes('data-target-id="old-next"'));

  // 2. True conflict decision card displays explicit conflict point digest naming opposing claim
  const decHtml = element("personal-decision-list").innerHTML;
  assert.ok(decHtml.includes("card-conflict-digest") && decHtml.includes("使用纯本地 JSON 文件账本"));

  // 3. Hover popover strips web://quick-note and user_message, translates to Chinese & indicates supersede/conflict
  await vm.runInContext('showCitationPopover(document.getElementById("anchor-pop"), "note-old")', context);
  const popHtml = element("citation-popover").innerHTML;
  assert.ok(!popHtml.includes("web://quick-note") && !popHtml.includes("user_message"), "Raw URL/kind leaked in citation popover");
  assert.ok(popHtml.includes("网页随手记") && popHtml.includes("随手记") && popHtml.includes("已有新定案接替"));

  // 4. Opening old superseded evidence opens drawer with clear Old-vs-New comparison AND folds technical metadata
  await vm.runInContext('openEvidence("note-old")', context);
  const oldDrawer = element("drawer-body").innerHTML;
  assert.ok(oldDrawer.includes("新旧计划接替说明") && oldDrawer.includes("审阅漫剧演示剧本并发布 v1.4.0"));
  assert.ok(!oldDrawer.includes("web://quick-note · fang"), "Raw URL/author line should be replaced by human Chinese");
  assert.ok(oldDrawer.includes("raw-meta-fold") && oldDrawer.includes("底层技术字段（排障核对用 · 默认折叠）"));
  assert.ok(!oldDrawer.includes('raw-meta-fold" open'));

  // 5. Opening true conflict evidence surfaces side-by-side Claim A vs Claim B right at top of drawer
  await vm.runInContext('openEvidence("ev-dbb")', context);
  const conflictDrawer = element("drawer-body").innerHTML;
  assert.ok(conflictDrawer.includes("分歧双方对照（为什么标为存在分歧？）"));
  assert.ok(conflictDrawer.includes("主张 A（当前查看）") && conflictDrawer.includes("主张 B（另一方记录）"));
  assert.ok(conflictDrawer.includes("改用远程云端数据库存储") && conflictDrawer.includes("使用纯本地 JSON 文件账本"));

  console.log("Plain-language UI, supersede folding, true conflict drawer comparison & metadata collapse verified.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
