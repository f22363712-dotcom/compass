const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

const appPath = process.argv[2] || path.join(__dirname, "..", "src", "project_compass", "web", "app.js");

function parseButtonsFromHtml(html) {
  const buttons = [];
  const btnRe = /<button([^>]*)>([\s\S]*?)<\/button>/gi;
  let m;
  while ((m = btnRe.exec(String(html || ""))) !== null) {
    const attrs = m[1] || "";
    const text = m[2] || "";
    const dataset = {};
    const attrRe = /data-([a-z0-9-]+)(?:="([^"]*)")?/gi;
    let am;
    while ((am = attrRe.exec(attrs)) !== null) {
      const camel = am[1].replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
      dataset[camel] = am[2] !== undefined ? am[2] : "";
    }
    buttons.push({ attrs, text, textContent: text, dataset, onclick: null, onkeydown: null });
  }
  return buttons;
}

function createV19Harness({ failNextReview = false } = {}) {
  const elements = new Map();
  const storageMap = new Map();
  const requests = [];
  let shouldFailReview = failNextReview;

  function makeEl(id) {
    const cls = new Set();
    let html = "";
    let parsedBtns = [];
    const obj = {
      id,
      value: "",
      textContent: "",
      hidden: id === "compass-toast" || id === "evidence-drawer" || id === "handoff-modal",
      disabled: false,
      readOnly: false,
      open: false,
      dataset: {},
      style: {},
      classList: {
        toggle(k, force) {
          force === undefined ? (cls.has(k) ? cls.delete(k) : cls.add(k)) : force ? cls.add(k) : cls.delete(k);
        },
        add(...ks) { ks.forEach((k) => cls.add(k)); },
        remove(...ks) { ks.forEach((k) => cls.delete(k)); },
        contains(k) { return cls.has(k); },
      },
      addEventListener(type, fn) { this["on" + type] = fn; },
      setAttribute() {},
      removeAttribute() {},
      focus() {},
      append() {},
      appendChild() {},
      querySelector(sel) {
        if (sel === ".investigation-stale-banner") {
          return html.includes("investigation-stale-banner") ? { remove() { html = html.replace(/<div class="investigation-stale-banner"[\s\S]*?<\/div>\s*/i, ""); } } : null;
        }
        return null;
      },
      querySelectorAll(sel) {
        if (sel === "[data-toast-action-idx]") return parsedBtns.filter((b) => "toastActionIdx" in b.dataset);
        if (sel === "[data-toast-close]") return parsedBtns.filter((b) => "toastClose" in b.dataset);
        if (sel === "[data-rerun-investigate]") return parsedBtns.filter((b) => "rerunInvestigate" in b.dataset);
        if (sel === "[data-dismiss-stale]") return parsedBtns.filter((b) => "dismissStale" in b.dataset);
        return [];
      },
    };
    Object.defineProperty(obj, "innerHTML", {
      get() { return html; },
      set(v) {
        html = String(v ?? "");
        parsedBtns = parseButtonsFromHtml(html);
      },
    });
    obj._parsed = () => parsedBtns;
    return obj;
  }

  function el(id) {
    if (!elements.has(id)) elements.set(id, makeEl(id));
    return elements.get(id);
  }

  const nowTs = Date.now();
  const freshIso = new Date(nowTs - 60 * 1000).toISOString();
  const staleIso = new Date(nowTs - 96 * 3600 * 1000).toISOString();

  const initialState = {
    state_version: 1,
    sample_mode: false,
    project: { project_id: "proj-v19", name: "Compass v19", evidence_count: 2, fact_count: 4, read_only: false },
    projects: [{ project_id: "proj-v19", project_name: "Compass v19" }],
    intake: { enabled: false },
    personal: {
      fang: {
        member_id: "fang",
        facts: [
          { id: "f-goal", kind: "goal", subject_key: "project.goal", value: "打造丝滑交互体验", short_title: "打造丝滑交互体验", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: freshIso },
          { id: "f-pend", kind: "decision", subject_key: "dec.1", value: "使用延时撤销保护防误触", short_title: "使用延时撤销保护防误触", status: "proposed", author: "fang", evidence_ids: ["e1", "e2", "e3", "e4", "e5", "e6"], observed_at: freshIso },
          { id: "f-dial", kind: "decision", subject_key: "dec.2", value: "在对话中已拍板统一用语", short_title: "在对话中已定统一用语", status: "dialogue_decided", author: "fang", evidence_ids: ["e1"], observed_at: freshIso },
          { id: "f-old", kind: "decision", subject_key: "dec.old", value: "四天前的旧待确认想法", short_title: "四天前的旧待确认想法", status: "proposed", author: "fang", evidence_ids: ["e2"], observed_at: staleIso },
        ],
        evidence_ids: ["e1", "e2"],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: { root: { fact_id: "f-goal", label: "打造丝滑交互体验", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
      },
    },
    team: {
      facts: [
        { id: "f-goal", kind: "goal", subject_key: "project.goal", value: "打造丝滑交互体验", short_title: "打造丝滑交互体验", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: freshIso },
      ],
      evidence_ids: ["e1", "e2"],
      conflicts: [],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "f-goal", label: "打造丝滑交互体验", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
    },
    evidence: [
      { id: "e1", kind: "user_message", author: "fang", content_preview: "alpha evidence item", observed_at: freshIso },
      { id: "e2", kind: "user_message", author: "fang", content_preview: "beta evidence item", observed_at: freshIso },
    ],
    candidate_relations: [],
    confirmed_relations: [],
    review_history: [],
    fact_reviews: [],
    team_review_queue: [],
    priority_dispatches: [],
  };

  let curState = structuredClone(initialState);

  const documentMock = {
    hidden: false,
    body: makeEl("body"),
    activeElement: null,
    getElementById: el,
    querySelector: () => null,
    querySelectorAll(sel) {
      if (sel === "[data-inline-review]") {
        const out = [];
        for (const id of ["personal-decision-list", "solo-baseline-list", "personal-todo-list"]) {
          const btns = parseButtonsFromHtml(el(id).innerHTML).filter((b) => "inlineReview" in b.dataset);
          out.push(...btns);
        }
        return out;
      }
      if (sel === "[data-batch-ignore-ids]") {
        return parseButtonsFromHtml(el("personal-decision-list").innerHTML).filter((b) => "batchIgnoreIds" in b.dataset);
      }
      return [];
    },
    addEventListener() {},
    createElement: (tag) => makeEl("created-" + tag),
  };

  const context = vm.createContext({
    console,
    AbortController,
    URLSearchParams,
    Headers,
    setTimeout,
    clearTimeout,
    setInterval() { return 0; },
    clearInterval() {},
    navigator: { clipboard: { writeText: async () => {} } },
    window: {
      location: { search: "" },
      localStorage: {
        getItem: (k) => (storageMap.has(k) ? storageMap.get(k) : null),
        setItem: (k, v) => storageMap.set(k, String(v)),
      },
      addEventListener() {},
    },
    document: documentMock,
    fetch: async (url, opts = {}) => {
      requests.push({ url: String(url), opts });
      if (String(url) === "/api/review") {
        if (shouldFailReview) {
          shouldFailReview = false;
          return { ok: false, status: 500, json: async () => ({ error: "模拟写入失败" }) };
        }
        const body = JSON.parse(opts.body || "{}");
        curState = structuredClone(curState);
        curState.state_version += 1;
        curState.review_history.push({ action: body.action, fact_id: body.fact_id, reviewer: body.reviewer, observed_at: freshIso });
        return { ok: true, status: 200, json: async () => structuredClone(curState) };
      }
      if (String(url) === "/api/query-stats/clear") {
        curState = structuredClone(curState);
        curState.state_version += 1;
        curState.investigation_stats = { total: 0, cache_hits: 0, unique_questions: 0, repeated_questions: [] };
        return { ok: true, status: 200, json: async () => structuredClone(curState) };
      }
      if (String(url) === "/api/investigate") {
        return { ok: true, status: 200, json: async () => ({ goal: "打造丝滑交互体验", semantic_summary: "当前进展顺利", conclusion: "OK", next_action: "继续", active_tasks: [], evidence_ids: ["e1"], conflicts: [], evidence_gaps: [], findings: [] }) };
      }
      return { ok: true, status: 200, json: async () => structuredClone(curState) };
    },
  });
  context.globalThis = context;
  vm.runInContext(fs.readFileSync(appPath, "utf8"), context);

  return {
    el,
    context,
    requests,
    setCurState(next) { curState = structuredClone(next); },
    flush: async () => { for (let i = 0; i < 6; i += 1) await new Promise((r) => setImmediate(r)); },
  };
}

async function main() {
  const h = createV19Harness();
  await h.flush();

  // 1. Overflow badge (+2) for >4 evidence items
  const decHtml = h.el("personal-decision-list").innerHTML;
  assert.ok(decHtml.includes("依据 · 4") && decHtml.includes("+2"), "Expected +2 overflow pill for 6 evidence items");
  assert.ok(!decHtml.includes("依据 · 5"), "Must cap direct pills at 4");

  // 2. dialogue_decided renders in solo-baseline-list with 对话已定 & ✕ 撤回 (NOT in pending list!)
  assert.ok(!decHtml.includes("在对话中已定统一用语"), "dialogue_decided leaked into pending decisions list");
  const baseHtml = h.el("solo-baseline-list").innerHTML;
  assert.ok(baseHtml.includes("对话已定") && baseHtml.includes("is-dialogue"), "dialogue_decided missing distinct badge");
  assert.ok(baseHtml.includes("✕ 撤回") && baseHtml.includes('data-withdraw-confirmed="true"'), "Confirmed/dialogue item missing withdraw button");

  // 3. Delayed commit 5s undo: card click reject -> 0 POSTs -> hidden immediately -> undo restores -> reject again -> flushDelayedReviews sends 1 POST
  h.requests.length = 0;
  vm.runInContext('queueDelayedFactReview("f-pend", "reject_fact", { fromDrawer: false })', h.context);
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 0, "Delayed reject must NOT POST immediately");
  assert.ok(!h.el("personal-decision-list").innerHTML.includes("使用延时撤销保护防误触"), "Pending item did not optimistically vanish");
  assert.equal(h.el("compass-toast").hidden, false);
  const undoBtn = h.el("compass-toast").querySelectorAll("[data-toast-action-idx]")[0];
  assert.ok(undoBtn && undoBtn.textContent.includes("撤销"), "Undo action button missing from delayed toast");
  undoBtn.onclick();
  assert.ok(h.el("personal-decision-list").innerHTML.includes("使用延时撤销保护防误触"), "Undo did not restore item immediately");
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 0, "Undo leaked a POST");

  vm.runInContext('queueDelayedFactReview("f-pend", "reject_fact", { fromDrawer: false })', h.context);
  await vm.runInContext("flushDelayedReviews()", h.context);
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 1, "Flush did not commit queued reject_fact");

  // 4. 2-click arming on batch ignore button (armConfirmButton) & #clear-query-stats
  const batchReqsBefore = h.requests.length;
  const mockBatchBtn = { id: "batch-mock", dataset: {}, textContent: "✕ 一键全部忽略（1 条）" };
  let batchConfirmedRuns = 0;
  h.context.mockBatchBtn = mockBatchBtn;
  h.context.runArmedBatch = () => { batchConfirmedRuns += 1; };
  vm.runInContext('armConfirmButton(mockBatchBtn, "再次点击确认忽略（1 条）", runArmedBatch, { armKey: "batch-test" })', h.context);
  assert.equal(batchConfirmedRuns, 0, "1st batch-ignore click executed without arming confirm");
  assert.equal(mockBatchBtn.dataset.armed, "true");
  assert.ok(mockBatchBtn.textContent.includes("再次点击确认忽略"));
  vm.runInContext('armConfirmButton(mockBatchBtn, "再次点击确认忽略（1 条）", runArmedBatch, { armKey: "batch-test" })', h.context);
  assert.equal(batchConfirmedRuns, 1, "2nd batch-ignore click did not execute confirmed callback");
  assert.equal(h.requests.length, batchReqsBefore);

  // #clear-query-stats requires 2 clicks
  h.el("clear-query-stats").onclick();
  await h.flush();
  assert.equal(h.requests.filter((r) => r.url === "/api/query-stats/clear").length, 0, "1st click cleared stats without confirmation");
  h.el("clear-query-stats").onclick();
  await h.flush();
  assert.equal(h.requests.filter((r) => r.url === "/api/query-stats/clear").length, 1, "2nd click did not clear stats");

  // 5. Partial #evidence-spine filtering does NOT clobber #fact-list
  h.el("fact-list").innerHTML = "SENTINEL_KEEP_FACT_LIST";
  h.el("evidence-filter").oninput({ target: { value: "beta" } });
  assert.equal(h.el("fact-list").innerHTML, "SENTINEL_KEEP_FACT_LIST", "Evidence filter re-rendered whole page");
  assert.ok(h.el("evidence-spine").innerHTML.includes("beta evidence item") && !h.el("evidence-spine").innerHTML.includes("alpha evidence item"), "Evidence filter did not filter spine");
  assert.equal(h.el("spine-count").textContent, "1/2");

  // 6. UX-10 Non-destructive investigation stale banner preserves existing answer and wired evidence nodes
  h.el("investigation-question").value = "进度如何？";
  await vm.runInContext("investigateProject({ preventDefault() {} })", h.context);
  assert.ok(h.el("investigation-answer").innerHTML.includes("当前进展顺利"));
  assert.ok(h.el("investigation-answer").innerHTML.includes('data-evidence-id="'), "Expected evidence target inside investigation answer");
  const mockEvNode = { dataset: { evidenceId: "ev-1" }, preservedSentinel: true };
  h.el("investigation-answer").__mockPreservedNode = mockEvNode;
  vm.runInContext('invalidateInvestigation("新确认已入库")', h.context);
  const afterStale = h.el("investigation-answer").innerHTML;
  assert.ok(afterStale.includes("当前进展顺利"), "invalidateInvestigation wiped visible answer!");
  assert.ok(afterStale.includes('data-evidence-id="'), "invalidateInvestigation dropped evidence targets!");
  assert.ok(afterStale.includes("investigation-stale-banner") && afterStale.includes("重新查询"), "Missing stale banner rerun action");

  // 7. Solo empty reviewer auto-resolves without opening drawer, and error uses toast instead of drawer
  h.el("reviewer-input").value = "";
  await vm.runInContext('acceptFact("f-dial", "accept_fact", { fromDrawer: false })', h.context);
  assert.equal(h.el("evidence-drawer").hidden, true, "Solo auto-signer opened drawer unexpectedly");
  assert.ok(h.el("reviewer-input").value.length > 0, "Solo auto-signer did not fill reviewer input");

  const hErr = createV19Harness({ failNextReview: true });
  await hErr.flush();
  await vm.runInContext('acceptFact("f-pend", "accept_fact", { fromDrawer: false })', hErr.context);
  assert.equal(hErr.el("evidence-drawer").hidden, true, "Error opened interrupting drawer instead of toast");
  assert.equal(hErr.el("compass-toast").hidden, false, "Error did not display toast");
  assert.ok(hErr.el("compass-toast").className.includes("is-error"), "Error toast missing is-error style");

  // 8. P1-1: keepalive flush replaces/clears stale undo toast instead of leaving dead undo button
  vm.runInContext('queueDelayedFactReview("f-pend", "reject_fact", { fromDrawer: false })', h.context);
  assert.equal(h.el("compass-toast").hidden, false);
  assert.ok(h.el("compass-toast").innerHTML.includes("撤销"), "Expected undo button right after queueing reject");
  const reqBeforeKeepalive = h.requests.filter((r) => r.url === "/api/review").length;
  await vm.runInContext("flushDelayedReviews({ keepalive: true })", h.context);
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, reqBeforeKeepalive + 1, "keepalive flush did not commit");
  assert.ok(!h.el("compass-toast").innerHTML.includes("撤销"), "Dead undo button remained after keepalive flush");

  // 9. P1-4: passive poll projectSwitched cancels stale delayedQueue instead of posting old fact_id to new project
  const hSwitch = createV19Harness();
  await hSwitch.flush();
  vm.runInContext('queueDelayedFactReview("f-pend", "reject_fact", { fromDrawer: false })', hSwitch.context);
  assert.equal(vm.runInContext("state.delayedQueue.size", hSwitch.context), 1);
  const reqBeforeSwitch = hSwitch.requests.filter((r) => r.url === "/api/review").length;
  hSwitch.setCurState({
    ...JSON.parse(vm.runInContext("JSON.stringify(state.data)", hSwitch.context)),
    state_version: 99,
    project: { project_id: "proj-new-b", name: "New Project B", path: "/tmp/proj-b", read_only: false, evidence_count: 1, fact_count: 1 },
    personal: {
      fang: { member_id: "fang", facts: [], evidence_ids: [], directions: { candidates: [], current: [], history: [] }, timeline_chapters: [], thinking_line: { root: { label: "New Goal", status: "proposed", evidence_ids: [] }, branches: [], reversals: [], code_nodes: [] } },
    },
    team: { facts: [], evidence_ids: [], conflicts: [], directions: { candidates: [], current: [], history: [] }, timeline_chapters: [], thinking_line: { root: null, branches: [], reversals: [], code_nodes: [] } },
  });
  await vm.runInContext("refreshNative({ backgroundPoll: true })", hSwitch.context);
  assert.equal(vm.runInContext("state.projectId", hSwitch.context), "proj-new-b");
  assert.equal(vm.runInContext("state.delayedQueue.size", hSwitch.context), 0, "Stale delayedQueue survived projectSwitched");
  assert.equal(hSwitch.requests.filter((r) => r.url === "/api/review").length, reqBeforeSwitch, "projectSwitched posted old project fact_id to /api/review");

  console.log("WEB_V19_UX_ROUND1_PASS");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
