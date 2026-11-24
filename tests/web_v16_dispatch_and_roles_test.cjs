const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const elements = new Map();
function makeNode(id, html) {
  const cls = new Set();
  return {
    id,
    innerHTML: html || "",
    textContent: "",
    value: "",
    title: "",
    hidden: false,
    readOnly: false,
    disabled: false,
    dataset: {},
    style: {},
    attributes: {},
    classList: {
      toggle(k, force) {
        if (force === undefined) {
          if (cls.has(k)) cls.delete(k);
          else cls.add(k);
        } else if (force) {
          cls.add(k);
        } else {
          cls.delete(k);
        }
      },
      add(...ks) {
        ks.forEach((k) => cls.add(k));
      },
      remove(...ks) {
        ks.forEach((k) => cls.delete(k));
      },
      contains(k) {
        return cls.has(k);
      },
    },
    addEventListener() {},
    setAttribute(k, v) {
      this.attributes[k] = String(v);
    },
    getAttribute(k) {
      return this.attributes[k];
    },
    removeAttribute(k) {
      delete this.attributes[k];
    },
    getBoundingClientRect() {
      return { left: 100, top: 120, right: 200, bottom: 148, width: 100, height: 28 };
    },
    focus() {},
    closest() {
      return null;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
  };
}

function element(id) {
  if (!elements.has(id)) {
    const node = makeNode(id, "");
    if (id === "reviewer-input") node.value = "lead";
    if (id === "evidence-drawer") {
      node.querySelectorAll = (sel) => {
        if (sel === "[data-dispatch-fact]") {
          const bodyHtml = element("drawer-body").innerHTML || "";
          const btns = [];
          for (const m of bodyHtml.matchAll(/<button[^>]*\bdata-dispatch-fact="([^"]+)"[^>]*>/g)) {
            const btn = makeNode(`drawer-dispatch-${m[1]}`, "");
            btn.dataset.dispatchFact = m[1];
            btns.push(btn);
          }
          return btns;
        }
        return [];
      };
    }
    elements.set(id, node);
  }
  return elements.get(id);
}

const initialState = {
  project: { project_id: "proj-delivery", name: "通用产品交付组", evidence_count: 3, fact_count: 2, read_only: false },
  projects: [{ project_id: "proj-delivery", project_name: "通用产品交付组" }],
  sample_mode: false,
  agent_api: {
    enabled: true,
    owner_id: "lead",
    clients: [
      {
        client_id: "planner",
        member_id: "planner",
        session_id: "session-planner",
        agent: "claude-code",
        role_label: "产品与方案席<script>alert(1)</script>",
      },
      {
        client_id: "developer",
        member_id: "developer",
        session_id: "session-developer",
        agent: "claude-code",
        role_label: "研发实现席",
      },
    ],
  },
  personal: {
    planner: {
      member_id: "planner",
      facts: [
        {
          id: "fact-dec-1",
          kind: "decision",
          subject_key: "note.decision.1",
          value: "锁定纯本地工作区台账为唯一基准存储",
          short_title: "锁定纯本地台账基准",
          status: "proposed",
          author: "planner",
          evidence_ids: ["ev-1"],
          observed_at: "2026-11-19T10:00:00Z",
        },
        {
          id: "fact-task-1",
          kind: "task",
          task_state: "pending",
          subject_key: "note.task.1",
          value: "补齐团队权限隔离与派发队列回归测试",
          short_title: "补齐权限与派发回归测试",
          status: "accepted",
          author: "planner",
          evidence_ids: ["ev-2"],
          observed_at: "2026-11-19T10:05:00Z",
        },
      ],
      evidence_ids: ["ev-1", "ev-2"],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { label: "通用产品交付试点", status: "proposed", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] },
    },
  },
  team: {
    facts: [
      {
        id: "fact-dec-1",
        kind: "decision",
        subject_key: "note.decision.1",
        value: "锁定纯本地工作区台账为唯一基准存储",
        short_title: "锁定纯本地台账基准",
        status: "proposed",
        author: "planner",
        evidence_ids: ["ev-1"],
        observed_at: "2026-11-19T10:00:00Z",
      },
      {
        id: "fact-task-1",
        kind: "task",
        task_state: "pending",
        subject_key: "note.task.1",
        value: "补齐团队权限隔离与派发队列回归测试",
        short_title: "补齐权限与派发回归测试",
        status: "accepted",
        author: "planner",
        evidence_ids: ["ev-2"],
        observed_at: "2026-11-19T10:05:00Z",
      },
    ],
    evidence_ids: ["ev-1", "ev-2"],
    conflicts: [],
    directions: { candidates: [], current: [], history: [] },
    timeline_chapters: [],
    thinking_line: { root: { label: "通用产品交付试点", status: "proposed", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] },
  },
  evidence: [
    { id: "ev-1", kind: "user_message", author: "planner", classification: "fact_source", content_preview: "锁定纯本地工作区台账为唯一基准存储", observed_at: "2026-11-19T10:00:00Z" },
    { id: "ev-2", kind: "user_message", author: "planner", classification: "fact_source", content_preview: "补齐团队权限隔离与派发队列回归测试", observed_at: "2026-11-19T10:05:00Z" },
  ],
  candidate_relations: [],
  confirmed_relations: [],
  fact_reviews: [{ action: "accept_fact", fact_id: "fact-task-1", reviewer: "lead", observed_at: "2026-11-19T10:06:00Z" }],
  review_history: [{ action: "accept_fact", fact_id: "fact-task-1", reviewer: "lead", observed_at: "2026-11-19T10:06:00Z" }],
  evidence_requests: [],
  priority_dispatches: [],
  activity_stream: [],
  agent_hints: [],
};

let currentState = structuredClone(initialState);
const apiRequests = [];
const copiedPayloads = [];

const context = vm.createContext({
  console,
  AbortController,
  setTimeout,
  clearTimeout,
  setInterval() {},
  navigator: {
    clipboard: {
      async writeText(text) {
        copiedPayloads.push(text);
      },
    },
  },
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
  fetch: async (url, init = {}) => {
    const reqUrl = String(url);
    const body = init.body ? JSON.parse(init.body) : null;
    apiRequests.push({ url: reqUrl, method: init.method || "GET", body });

    if (reqUrl === "/api/review") {
      const targetId = body.fact_id;
      currentState = structuredClone(currentState);
      for (const f of currentState.team.facts) {
        if (f.id === targetId) f.status = "accepted";
      }
      for (const f of currentState.personal.planner.facts) {
        if (f.id === targetId) f.status = "accepted";
      }
      currentState.fact_reviews.push({ action: "accept_fact", fact_id: targetId, reviewer: body.reviewer, observed_at: "2026-11-19T10:10:00Z" });
      currentState.review_history.push({ action: "accept_fact", fact_id: targetId, reviewer: body.reviewer, observed_at: "2026-11-19T10:10:00Z" });
      return { ok: true, json: async () => structuredClone(currentState) };
    }
    if (reqUrl === "/api/dispatch") {
      currentState = structuredClone(currentState);
      currentState.priority_dispatches.unshift({
        id: `dispatch-${currentState.priority_dispatches.length + 1}`,
        fact_id: body.fact_id,
        title: body.title,
        value: body.value,
        evidence_ids: body.evidence_ids || [],
        actor: body.reviewer || "lead",
        mode: body.mode || "queue",
        observed_at: "2026-11-19T10:11:00Z",
      });
      return { ok: true, json: async () => structuredClone(currentState) };
    }
    return { ok: true, json: async () => structuredClone(currentState) };
  },
});

async function main() {
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
  await new Promise((r) => setTimeout(r, 20));

  // 1. Multi-seat team badges render role_label alongside member_id and escape XSS cleanly
  const presenceHtml = element("session-presence-bar").innerHTML;
  assert.equal(element("session-presence-bar").hidden, false, "Multi-seat team mode should show presence bar");
  assert.ok(presenceHtml.includes("planner"), "planner member_id missing from presence pill");
  assert.ok(presenceHtml.includes("产品与方案席&lt;script&gt;alert(1)&lt;/script&gt;"), "role_label not rendered or not escaped");
  assert.ok(!presenceHtml.includes("<script>alert(1)</script>"), "Unescaped script tag in role_label!");
  assert.ok(presenceHtml.includes("developer") && presenceHtml.includes("研发实现席"), "Unposted team seat missing from presence bar");

  // 2. Decision card and todo card render "✓ 确认并交给 AI" button
  const decHtml = element("personal-decision-list").innerHTML;
  const todoHtml = element("personal-todo-list").innerHTML;
  assert.ok(decHtml.includes('data-dispatch-fact="fact-dec-1"') && decHtml.includes("✓ 确认并交给 AI"));
  assert.ok(todoHtml.includes('data-dispatch-fact="fact-task-1"') && todoHtml.includes("✓ 确认并交给 AI"));

  // 3. Opening fact drawer renders "✓ 确认并交给 AI" button cleanly
  await vm.runInContext('openFact("fact-dec-1")', context);
  const drawerHtml = element("drawer-body").innerHTML;
  assert.ok(drawerHtml.includes('data-dispatch-fact="fact-dec-1"') && drawerHtml.includes("✓ 确认并交给 AI"));

  // 4. Triggering dispatchFact on unaccepted decision calls /api/review + /api/dispatch + clipboard + toast
  await vm.runInContext('dispatchFact("fact-dec-1", { fromDrawer: true })', context);
  const mutatingCalls = apiRequests.filter((r) => r.method === "POST");
  assert.deepEqual(
    mutatingCalls.map((c) => c.url),
    ["/api/review", "/api/dispatch"],
    "Unaccepted item should call /api/review then /api/dispatch",
  );
  assert.equal(mutatingCalls[0].body.fact_id, "fact-dec-1");
  assert.equal(mutatingCalls[1].body.fact_id, "fact-dec-1");
  assert.equal(mutatingCalls[1].body.reviewer, "lead");
  assert.equal(copiedPayloads.length, 1);
  assert.ok(copiedPayloads[0].includes("【Compass 已定案推进】") && copiedPayloads[0].includes("ev-1"));
  assert.equal(element("compass-toast").hidden, false);
  assert.equal(element("compass-toast").textContent, "已确认并加入优先执行列表（指令已复制）");
  assert.equal(element("priority-dispatch-surface").hidden, false);
  assert.ok(element("priority-dispatch-list").innerHTML.includes("锁定纯本地台账基准"));

  // 5. Triggering dispatchFact on already-accepted task skips /api/review and calls only /api/dispatch
  apiRequests.length = 0;
  await vm.runInContext('dispatchFact("fact-task-1", { fromDrawer: false })', context);
  const secondCalls = apiRequests.filter((r) => r.method === "POST");
  assert.deepEqual(
    secondCalls.map((c) => c.url),
    ["/api/dispatch"],
    "Already-accepted item should skip /api/review and call only /api/dispatch",
  );
  assert.equal(copiedPayloads.length, 2);
  assert.ok(copiedPayloads[1].includes("补齐权限与派发回归测试") && copiedPayloads[1].includes("ev-2"));

  console.log("v1.5/v1.6 web dispatch button, clipboard brief, toast & role_label XSS escaping verified.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
