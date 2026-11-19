const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const appPath = process.argv[2];
const htmlPath = path.join(path.dirname(appPath), "index.html");
const appSource = fs.readFileSync(appPath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");

function createHarness(initialState) {
  let currentState = JSON.parse(JSON.stringify(initialState));
  const storage = new Map();
  const requests = [];
  const downloads = [];
  const elements = new Map();
  const staticIds = new Set([...htmlSource.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

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
      checked: id === "scan-extract-docs" || id === "scan-code-index",
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
      addEventListener: (ev, cb) => { node[`on${ev}`] = cb; },
      setAttribute: (k, v) => { node.attributes[k] = String(v); },
      removeAttribute: (k) => { delete node.attributes[k]; },
      append: () => {},
      prepend: () => {},
      appendChild: () => {},
      removeChild: () => {},
      select: () => {},
      click: () => { if (typeof node.onclick === "function") return node.onclick({ preventDefault() {}, stopPropagation() {} }); },
      querySelector: (sel) => node.querySelectorAll(sel)[0] || null,
      querySelectorAll: (sel) => {
        const html = (id === "evidence-drawer" ? element("drawer-body").innerHTML : node.innerHTML) || "";
        if (node._cachedHtml !== html) {
          node._cachedHtml = html;
          node._cachedNodes = new Map();
        }
        const getCached = (key, ds) => {
          if (!node._cachedNodes.has(key)) node._cachedNodes.set(key, makeNode(key, ds));
          return node._cachedNodes.get(key);
        };
        const found = [];
        if (sel === "[data-solo-signer-input]") {
          if (html.includes("data-solo-signer-input")) {
            return [getCached(`${id}:signer-input`, {})];
          }
          return [];
        }
        if (sel === "[data-solo-signer-submit]") {
          if (html.includes("data-solo-signer-submit")) {
            return [getCached(`${id}:signer-submit`, {})];
          }
          return [];
        }
        if (sel === "[data-solo-signer-error]") {
          if (html.includes("data-solo-signer-error")) {
            return [getCached(`${id}:signer-error`, {})];
          }
          return [];
        }
        if (sel === "[data-inline-review]") {
          for (const m of html.matchAll(/<button[^>]*data-inline-review="([^"]+)"[^>]*data-target-id="([^"]+)"/g)) {
            found.push(getCached(`${id}:inline:${m[2]}:${m[1]}`, { inlineReview: m[1], targetId: m[2] }));
          }
        }
        return found;
      },
    };
    node.classList = makeClassList(node);
    return node;
  }

  function element(id) {
    if (!elements.has(id)) elements.set(id, makeNode(id));
    return elements.get(id);
  }

  const workbenchBtns = [makeNode("view-list-btn", { workbenchView: "list" }), makeNode("view-mindmap-btn", { workbenchView: "mindmap" })];
  elements.set("view-list-btn", workbenchBtns[0]);
  elements.set("view-mindmap-btn", workbenchBtns[1]);

  const modeBtns = [makeNode("mode-solo-btn", { workMode: "solo" }), makeNode("mode-team-btn", { workMode: "team" })];
  const lensBtns = [makeNode("lens-personal-btn", { lens: "personal" }), makeNode("lens-team-btn", { lens: "team" })];
  elements.set("lens-personal-btn", lensBtns[0]);
  elements.set("lens-team-btn", lensBtns[1]);
  const layerBtns = [makeNode("layer-overview-btn", { layerChoice: "overview" })];

  const documentMock = {
    hidden: false,
    body: { dataset: {}, appendChild() {}, removeChild() {} },
    activeElement: null,
    getElementById: element,
    querySelector: (sel) => {
      if (sel.startsWith("#")) return element(sel.slice(1));
      if (sel === ".goal-surface") return element("__goal-surface");
      return null;
    },
    querySelectorAll: (sel) => {
      if (sel === ".mode-pill") return modeBtns;
      if (sel === ".workbench-view-btn") return workbenchBtns;
      if (sel === ".lens") return lensBtns;
      if (sel === ".layer-choice") return layerBtns;
      if (sel === "[data-inline-review]") {
        return [
          ...element("personal-decision-list").querySelectorAll(sel),
          ...element("personal-todo-list").querySelectorAll(sel),
          ...element("thinking-line-canvas").querySelectorAll(sel),
          ...element("goal-actions").querySelectorAll(sel),
        ];
      }
      return [];
    },
    createElement: (tag) => {
      const n = makeNode(`created:${tag}`);
      if (tag === "a") {
        n.click = () => downloads.push(n.download);
      }
      return n;
    },
    addEventListener: () => {},
  };

  let scanPollStep = 0;
  const fetchMock = async (url, opts = {}) => {
    requests.push({ url, method: opts.method || "GET", body: opts.body || null, headers: opts.headers || {} });
    if (url.startsWith("/api/state")) {
      return { ok: true, json: async () => JSON.parse(JSON.stringify(currentState)) };
    }
    if (url.startsWith("/api/export")) {
      return {
        ok: true,
        headers: { get: () => "" },
        blob: async () => ({ text: async () => "mindmap\n  root((Test Goal))" }),
      };
    }
    if (url === "/api/notes") {
      const body = JSON.parse(opts.body);
      const newFact = {
        id: "fact-note-1",
        kind: body.kind,
        subject_key: `note.${body.kind}.new`,
        value: body.text,
        status: body.auto_accept ? "accepted" : "proposed",
        author: body.member_id || "fang",
        evidence_ids: ["ev-note-1"],
        observed_at: "2026-11-15T12:05:00Z",
      };
      currentState.state_version += 1;
      currentState.project.fact_count += 1;
      currentState.personal.fang.facts.push(newFact);
      currentState.team.facts.push(newFact);
      if (newFact.kind === "decision" || newFact.kind === "assumption") {
        currentState.personal.fang.thinking_line.branches.push({
          fact_id: newFact.id,
          kind: newFact.kind,
          label: newFact.value,
          status: newFact.status,
          state: "active",
          evidence_ids: ["ev-note-1"],
          children: [],
        });
      }
      currentState.activity_stream.unshift({
        id: "act-note-1",
        member_id: "fang",
        action_kind: "note",
        action_label: "随手记",
        summary: body.text,
        observed_at: "2026-11-15T12:05:00Z",
        exit_code: null,
        evidence_ids: ["ev-note-1"],
        primary_evidence_id: "ev-note-1",
        collapsed_count: 1,
      });
      return {
        ok: true,
        json: async () => ({
          ...JSON.parse(JSON.stringify(currentState)),
          quick_note: { fact_id: newFact.id, kind: newFact.kind, accepted: Boolean(body.auto_accept) },
        }),
      };
    }
    if (url === "/api/review") {
      const body = JSON.parse(opts.body);
      currentState.state_version += 1;
      for (const list of [currentState.personal.fang.facts, currentState.team.facts]) {
        const target = list.find((f) => f.id === body.fact_id);
        if (target) target.status = "accepted";
      }
      currentState.review_history.push({
        action: body.action || "accept_fact",
        fact_id: body.fact_id,
        reviewer: body.reviewer,
        observed_at: "2026-11-15T12:06:00Z",
      });
      return { ok: true, json: async () => JSON.parse(JSON.stringify(currentState)) };
    }
    if (url === "/api/projects/scan") {
      scanPollStep = 0;
      return { ok: true, json: async () => ({ state: "scanning", stage: "scanning" }) };
    }
    if (url === "/api/projects/scan-status") {
      scanPollStep += 1;
      if (scanPollStep === 1) return { ok: true, json: async () => ({ state: "running", stage: "extracting_docs" }) };
      if (scanPollStep === 2) return { ok: true, json: async () => ({ state: "running", stage: "indexing_code" }) };
      return { ok: true, json: async () => ({ state: "complete", stage: "complete", project_id: "compass-v11", project_path: "C:/repo", warnings: [] }) };
    }
    return { ok: true, json: async () => currentState };
  };

  const context = vm.createContext({
    console,
    AbortController,
    URL: { createObjectURL: () => "blob:mock-url", revokeObjectURL: () => {} },
    setTimeout: (cb, ms) => { if (ms <= 250) cb(); return 1; },
    clearTimeout: () => {},
    setInterval: () => 1,
    window: {
      localStorage: {
        getItem: (k) => (storage.has(k) ? storage.get(k) : null),
        setItem: (k, v) => storage.set(k, String(v)),
      },
      addEventListener: () => {},
    },
    navigator: { clipboard: { writeText: async () => {} } },
    document: documentMock,
    fetch: fetchMock,
  });

  vm.runInContext(appSource, context);
  return {
    context,
    element,
    storage,
    requests,
    downloads,
    staticIds,
    documentMock,
    workbenchBtns,
    setStateMutator: (fn) => fn(currentState),
    flush: () => new Promise((r) => setImmediate(r)),
  };
}

async function main() {
  const sampleSoloState = {
    state_version: 1,
    project: { project_id: "p1", name: "compass", read_only: false, evidence_count: 4, fact_count: 5 },
    projects: [{ project_id: "p1", project_name: "compass" }],
    sample_mode: false,
    intake: { enabled: false },
    agent_api: { enabled: false },
    personal: {
      fang: {
        member_id: "fang",
        evidence_ids: ["e1", "e2", "e3", "e4"],
        facts: [
          { id: "g1", kind: "goal", subject_key: "project.goal", value: "把 Solo 与脑图做透", status: "accepted", evidence_ids: ["e1"], observed_at: "2026-11-15T10:00:00Z" },
          { id: "d-acc", kind: "decision", subject_key: "dec.lock", value: "使用文件锁保护并发写盘", status: "accepted", evidence_ids: ["e1"], observed_at: "2026-11-15T10:05:00Z" },
          { id: "d-pend", kind: "decision", subject_key: "dec.view", value: "提供台账与正交脑图切换", status: "proposed", evidence_ids: ["e2"], observed_at: "2026-11-15T10:10:00Z" },
          { id: "a-pend", kind: "assumption", subject_key: "assump.ci", value: "全部 .cjs 测试均可脱离浏览器跑通", status: "proposed", evidence_ids: ["e3"], observed_at: "2026-11-15T10:15:00Z" },
          { id: "t-pend", kind: "task", subject_key: "task.ci", value: "把 17 个 .cjs 测试接入 CI", status: "proposed", task_state: "pending", evidence_ids: ["e4"], observed_at: "2026-11-15T10:20:00Z" },
        ],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: {
          root: { fact_id: "g1", label: "把 Solo 与脑图做透", status: "accepted", evidence_ids: ["e1"] },
          branches: [
            { fact_id: "d-pend", kind: "decision", label: "提供台账与正交脑图切换", status: "proposed", state: "active", evidence_ids: ["e2"], children: [{ fact_id: "t-pend", label: "把 17 个 .cjs 测试接入 CI", task_state: "pending", evidence_ids: ["e4"] }] },
            { fact_id: "d-acc", kind: "decision", label: "使用文件锁保护并发写盘", status: "accepted", state: "active", evidence_ids: ["e1"], children: [] },
          ],
          reversals: [],
          code_nodes: [{ label: "web_server.py", direct: true, source_ref: "src/project_compass/web_server.py" }],
        },
      },
    },
    team: {
      facts: [
        { id: "g1", kind: "goal", subject_key: "project.goal", value: "把 Solo 与脑图做透", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-15T10:00:00Z" },
        { id: "d-acc", kind: "decision", subject_key: "dec.lock", value: "使用文件锁保护并发写盘", status: "accepted", author: "fang", evidence_ids: ["e1"], observed_at: "2026-11-15T10:05:00Z" },
        { id: "d-pend", kind: "decision", subject_key: "dec.view", value: "提供台账与正交脑图切换", status: "proposed", author: "fang", evidence_ids: ["e2"], observed_at: "2026-11-15T10:10:00Z" },
      ],
      evidence_ids: ["e1", "e2", "e3", "e4"],
      conflicts: [],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "g1", label: "把 Solo 与脑图做透", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
    },
    activity_stream: [
      { id: "act-1", member_id: "fang", action_kind: "note", action_label: "随手记", summary: "先确认跨进程锁合同", observed_at: "2026-11-15T10:22:00Z", exit_code: null, evidence_ids: ["e1"], primary_evidence_id: "e1", collapsed_count: 1 },
      { id: "act-2", member_id: "fang", action_kind: "tool", action_label: "调用工具 · read_file", summary: "连续读取项目模块", observed_at: "2026-11-15T10:21:00Z", exit_code: 0, evidence_ids: ["e2", "e3"], primary_evidence_id: "e2", collapsed_count: 3 },
      { id: "act-3", member_id: "fang", action_kind: "test", action_label: "运行测试", summary: "python -m unittest tests.test_dashboard", observed_at: "2026-11-15T10:20:00Z", exit_code: 1, evidence_ids: ["e4"], primary_evidence_id: "e4", collapsed_count: 1 },
    ],
    personal_activity: [],
    evidence: [
      { id: "e1", kind: "user_message", author: "fang", classification: "fact_source", content_preview: "doc 1", observed_at: "2026-11-15T10:00:00Z" },
      { id: "e2", kind: "tool_call", author: "fang", classification: "execution_result", content_preview: "tool 2", observed_at: "2026-11-15T10:10:00Z" },
      { id: "e3", kind: "tool_result", author: "fang", classification: "execution_result", content_preview: "tool 3", observed_at: "2026-11-15T10:15:00Z" },
      { id: "e4", kind: "command_execution", author: "fang", classification: "execution_result", content_preview: "pytest failed", exit_code: 1, observed_at: "2026-11-15T10:20:00Z" },
    ],
    candidate_relations: [],
    confirmed_relations: [],
    review_history: [],
    fact_reviews: [],
    team_review_queue: [],
    handoff_brief: { focus_goal: { fact_id: "g1", value: "把 Solo 与脑图做透", status: "accepted", evidence_ids: ["e1"] }, accepted_decisions: [], pending_candidates: [], open_todos: [], code_nodes: [], markdown: "# Brief" },
  };

  const h = createHarness(sampleSoloState);
  await h.flush();

  // 1. Static HTML contract check for new v1.1 IDs
  for (const reqId of ["quick-note-form", "quick-note-kind", "quick-note-input", "quick-note-accept", "workbench-view-bar", "view-list-btn", "view-mindmap-btn", "solo-baseline-surface", "solo-baseline-list", "scan-extract-docs", "scan-code-index", "handoff-export-mindmap-btn"]) {
    assert.ok(h.staticIds.has(reqId), `index.html missing v1.1 id=${reqId}`);
  }

  // 2. Solo lexicon & pending vs baseline split
  assert.equal(h.documentMock.body.dataset.workMode, "solo");
  assert.ok(!h.element("review-queue-kicker").textContent.includes("负责人核对"), "Solo leaked 负责人核对");
  assert.ok(!h.element("lens-team-btn").textContent.includes("团队共识"), "Solo leaked 团队共识");
  assert.ok(!h.element("legend-accepted-desc").textContent.includes("负责人"), "Solo legend leaked 负责人");

  const decHTML = h.element("personal-decision-list").innerHTML;
  assert.ok(decHTML.includes("待拍板决策") && decHTML.includes("提供台账与正交脑图切换"), "Pending decisions missing group heading");
  assert.ok(decHTML.includes("未验证前提") && decHTML.includes("全部 .cjs 测试均可脱离浏览器跑通"), "Pending assumptions missing group heading");
  assert.ok(!decHTML.includes("使用文件锁保护并发写盘"), "Accepted baseline leaked into pending list");

  assert.equal(h.element("solo-baseline-surface").hidden, false, "Solo baseline surface hidden in personal lens");
  const baseHTML = h.element("solo-baseline-list").innerHTML;
  assert.ok(baseHTML.includes("使用文件锁保护并发写盘") && baseHTML.includes("把 Solo 与脑图做透"), "Solo baseline list missing accepted items");

  vm.runInContext('state.lens = "team"; render();', h.context);
  assert.equal(h.element("team-review-queue").hidden, true, "Empty review queue remained visible in Solo baseline lens");
  vm.runInContext('state.lens = "personal"; render();', h.context);

  // 3. Readable activity_stream rendering & zero nested buttons
  const actHTML = h.element("personal-activity-list").innerHTML;
  assert.ok(actHTML.includes("随手记") && actHTML.includes("连续 3 步") && actHTML.includes("退出码 1"), "Activity stream missing Chinese action/collapse/exit badges");
  assert.ok(!actHTML.includes("<button"), "Activity card must not nest <button>");
  assert.equal(h.element("activity-count").textContent, 3);

  // 4. Dual [清单台账 | 思维脑图] toggle, orthogonal mindmap markup & compass-* exports
  assert.equal(h.documentMock.body.dataset.workbenchView, "list");
  h.workbenchBtns[1].click();
  assert.equal(h.documentMock.body.dataset.workbenchView, "mindmap");
  assert.equal(h.storage.get("compass_workbench_view"), "mindmap");
  assert.ok(h.element("thinking-kicker").textContent.includes("思维脑图"));
  const treeHTML = h.element("thinking-line-canvas").innerHTML;
  assert.ok(treeHTML.includes("thinking-tree mindmap-layout") && treeHTML.includes("thinking-branch-actions"), "Mindmap layout classes missing");

  await vm.runInContext('exportCognitiveAsset("mindmap", "handoff-export-mindmap-btn", "已导出脑图")', h.context);
  assert.ok(h.requests.some((r) => r.url === "/api/export?format=mindmap"), "Mindmap export did not call format=mindmap");
  assert.ok(h.downloads.includes("compass-mindmap.md"), "Fallback export filename did not use compass- prefix");
  await h.element("export-state").click();
  await h.flush();
  assert.ok(h.downloads.includes("compass-state.json"), "State export filename did not use compass-state.json");

  // 5. Quick-note submission preserves Solo mode & updates mindmap/activity/pending list
  h.element("quick-note-kind").value = "assumption";
  h.element("quick-note-input").value = "桌面端优先正交脑图降低记忆负荷";
  await h.element("quick-note-form").onsubmit({ preventDefault() {} });
  const noteReq = h.requests.find((r) => r.url === "/api/notes");
  assert.ok(noteReq, "Quick note form did not POST /api/notes");
  assert.equal(JSON.parse(noteReq.body).kind, "assumption");
  assert.equal(h.element("quick-note-input").value, "", "Quick note input was not cleared");
  assert.equal(vm.runInContext("effectiveWorkMode()", h.context), "solo", "Quick note flipped Solo into Team");
  assert.ok(h.element("personal-decision-list").innerHTML.includes("桌面端优先正交脑图降低记忆负荷"));
  assert.ok(h.element("thinking-line-canvas").innerHTML.includes("桌面端优先正交脑图降低记忆负荷"));

  // 6. One-time inline Solo signer vs repeated click & Team empty guard
  h.element("reviewer-input").value = "";
  const pendingInlineBtn = h.element("personal-decision-list").querySelectorAll("[data-inline-review]")[0];
  pendingInlineBtn.click();
  await h.flush();
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 0, "Empty Solo signer sent POST /api/review prematurely");
  assert.equal(h.element("evidence-drawer").hidden, false, "Solo inline signer did not open drawer");
  const signerInput = h.element("evidence-drawer").querySelector("[data-solo-signer-input]");
  const signerSubmit = h.element("evidence-drawer").querySelector("[data-solo-signer-submit]");
  assert.ok(signerInput && signerSubmit, "Inline Solo signer controls missing in drawer");
  signerInput.value = "fang";
  await signerSubmit.click();
  await h.flush();
  assert.equal(h.storage.get("compass_reviewer_name"), "fang");
  assert.equal(h.element("reviewer-input").value, "fang");
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 1, "Submitting inline Solo signer did not auto-resume acceptFact");

  // Second inline accept executes with zero modal/drawer friction
  const secondInlineBtn = h.element("personal-todo-list").querySelectorAll("[data-inline-review]")[0];
  secondInlineBtn.click();
  await h.flush();
  assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 2, "Second Solo accept failed to proceed directly without prompting");

  // Switch to Team mode -> empty reviewer must trigger Team reviewer prompt
  vm.runInContext('setWorkMode("team");', h.context);
  h.element("reviewer-input").value = "";
  await vm.runInContext('acceptFact("fact-note-1", "accept_fact", { fromDrawer: false })', h.context);
  assert.ok(h.element("drawer-body").innerHTML.includes("请先填写负责人姓名"), "Team mode did not enforce reviewer name");

  // Read-only disables quick note bar
  vm.runInContext('state.data.project.read_only = true; render();', h.context);
  assert.equal(h.element("quick-note-submit").disabled, true);

  // 7. Web project scan sends checkboxes & renders stage labels
  vm.runInContext('state.data.project.read_only = false; render();', h.context);
  h.element("project-path-input").value = "C:/demo-v11";
  h.element("scan-extract-docs").checked = true;
  h.element("scan-code-index").checked = true;
  await h.element("project-scan-form").onsubmit({ preventDefault() {} });
  const scanReq = h.requests.find((r) => r.url === "/api/projects/scan");
  assert.ok(scanReq, "Scan form did not POST /api/projects/scan");
  const scanBody = JSON.parse(scanReq.body);
  assert.equal(scanBody.extract_docs, true);
  assert.equal(scanBody.with_code_index, true);
  assert.ok(h.element("project-scan-result").textContent.includes("已保存 C:/repo"));

  console.log("v1.1 Solo workbench, activity stream, quick notes, inline signer, mindmap toggle & scan tests passed.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
