const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const appPath = process.argv[2];
const htmlPath = path.join(path.dirname(appPath), "index.html");
const appSource = fs.readFileSync(appPath, "utf8");
const htmlSource = fs.readFileSync(htmlPath, "utf8");

function buildTestHarness(options = {}) {
  const staticIds = new Set([...htmlSource.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
  const elements = new Map();
  const listeners = new Map();
  const activeState = { element: null };
  let fetchMode = options.fetchMode || "ok";
  const requests = [];

  function parseControls(containerId, html) {
    const out = {
      inlineReview: [],
      factCards: [],
      evidenceTargets: [],
      popoverOpen: [],
      factReviewBtns: [],
      reviewBtns: [],
      projectBtns: [],
      presencePills: [],
      chapterBtns: [],
    };
    if (!html) return out;
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-inline-review="([^"]+)"([^>]*)>/g)) {
      const full = m[0];
      const targetId = (full.match(/\bdata-target-id="([^"]+)"/) || [])[1] || "";
      out.inlineReview.push(makeVirtualNode(`${containerId}:inline:${m[3]}:${targetId}`, { inlineReview: m[3], targetId }, "BUTTON", true));
    }
    const factNodeCache = new Map();
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-fact-id="([^"]+)"([^>]*)>/g)) {
      const full = m[0];
      const reviewId = (full.match(/\bdata-review-id="([^"]+)"/) || [])[1] || "";
      const ds = reviewId ? { factId: m[3], reviewId } : { factId: m[3] };
      const node = makeVirtualNode(`${containerId}:fact:${m[3]}:${reviewId}`, ds, m[1].toUpperCase(), false);
      if (reviewId) {
        node.attributes["data-review-id"] = reviewId;
        out.reviewBtns.push(node);
        factNodeCache.set(`${m[3]}:${reviewId}`, node);
      }
      out.factCards.push(node);
    }
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-review-id="([^"]+)"([^>]*)>/g)) {
      const full = m[0];
      const factId = (full.match(/\bdata-fact-id="([^"]+)"/) || [])[1] || "";
      if (!factNodeCache.has(`${factId}:${m[3]}`)) {
        const node = makeVirtualNode(`${containerId}:revrel:${m[3]}:${factId}`, { reviewId: m[3], factId }, m[1].toUpperCase(), false);
        node.attributes["data-review-id"] = m[3];
        out.reviewBtns.push(node);
      }
    }
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-project-id="([^"]+)"([^>]*)>/g)) {
      out.projectBtns.push(makeVirtualNode(`${containerId}:proj:${m[3]}`, { projectId: m[3] }, m[1].toUpperCase(), false));
    }
    for (const m of html.matchAll(/<button([^>]*?)\bclass="[^"]*\bpresence-pill\b[^"]*"([^>]*)>/g)) {
      const full = m[0];
      const targetLens = (full.match(/\bdata-target-lens="([^"]+)"/) || [])[1] || "";
      const targetMember = (full.match(/\bdata-target-member="([^"]+)"/) || [])[1] || "";
      out.presencePills.push(makeVirtualNode(`${containerId}:pres:${targetLens}:${targetMember}`, { targetLens, targetMember }, "BUTTON", false));
    }
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-evidence-id="([^"]+)"([^>]*)>/g)) {
      out.evidenceTargets.push(makeVirtualNode(`${containerId}:ev:${m[3]}`, { evidenceId: m[3] }, m[1].toUpperCase(), false));
    }
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-popover-open="([^"]+)"([^>]*)>/g)) {
      out.popoverOpen.push(makeVirtualNode(`${containerId}:pop:${m[3]}`, { popoverOpen: m[3] }, "BUTTON", false));
    }
    for (const m of html.matchAll(/<button([^>]*?)\bdata-fact-review-id="([^"]+)"([^>]*)>/g)) {
      const action = (m[0].match(/\bdata-review-action="([^"]+)"/) || [])[1] || "accept_fact";
      out.factReviewBtns.push(makeVirtualNode(`${containerId}:rev:${m[2]}:${action}`, { factReviewId: m[2], reviewAction: action }, "BUTTON", false));
    }
    for (const m of html.matchAll(/<(\w+)([^>]*?)\bdata-chapter-id="([^"]+)"([^>]*)>/g)) {
      out.chapterBtns.push(makeVirtualNode(`${containerId}:chap:${m[3]}`, { chapterId: m[3] }, m[1].toUpperCase(), false));
    }
    return out;
  }

  function makeVirtualNode(key, dataset, tagName, isInlineChild) {
    const classes = new Set();
    const node = {
      id: key,
      tagName,
      dataset: { ...dataset },
      style: {},
      attributes: {},
      classList: {
        add: (...c) => c.forEach((x) => classes.add(x)),
        remove: (...c) => c.forEach((x) => classes.delete(x)),
        toggle: (x, force) => {
          const on = force === undefined ? !classes.has(x) : Boolean(force);
          if (on) classes.add(x);
          else classes.delete(x);
          return on;
        },
        contains: (x) => classes.has(x),
      },
      focus() {
        activeState.element = node;
      },
      addEventListener(type, fn) {
        this[`on${type}`] = fn;
      },
      setAttribute(k, v) {
        this.attributes[k] = String(v);
      },
      hasAttribute(k) {
        return Object.prototype.hasOwnProperty.call(this.attributes, k);
      },
      closest(sel) {
        if (isInlineChild && sel.includes("data-inline-review")) return node;
        if (containerKeyStartsWithDrawer(key) && sel === "#evidence-drawer") return { id: "evidence-drawer" };
        return null;
      },
      getBoundingClientRect() {
        return node._rect || { top: 20, bottom: 40, left: 20, right: 80, width: 60, height: 20 };
      },
    };
    return node;
  }
  function containerKeyStartsWithDrawer(key) {
    return typeof key === "string" && key.startsWith("drawer-body:");
  }

  function element(id) {
    if (id === "review-note") {
      const body = elements.get("drawer-body");
      if (!body || !String(body._html || "").includes('id="review-note"')) return null;
      if (!body._noteEl) {
        body._noteEl = { id: "review-note", value: "", classList: makeVirtualNode("rn", {}, "TEXTAREA", false).classList };
      }
      return body._noteEl;
    }
    if (!elements.has(id)) {
      const classes = new Set();
      let _html = "";
      let _parsed = parseControls(id, "");
      const el = {
        id,
        dataset: {},
        style: {},
        attributes: {},
        textContent: id === "handoff-copy-btn" ? "复制简报" : id === "handoff-export-prd-btn" ? "导出 PRD" : "",
        value: "",
        hidden: id === "handoff-modal" || id === "evidence-drawer" || id === "citation-popover" || id === "scrim",
        readOnly: false,
        disabled: false,
        scrollLeft: 0,
        scrollWidth: 400,
        clientWidth: 400,
        offsetWidth: id === "citation-popover" ? 360 : 200,
        offsetHeight: id === "citation-popover" ? 160 : 100,
        classList: {
          add: (...c) => c.forEach((x) => classes.add(x)),
          remove: (...c) => c.forEach((x) => classes.delete(x)),
          toggle: (x, force) => {
            const on = force === undefined ? !classes.has(x) : Boolean(force);
            if (on) classes.add(x);
            else classes.delete(x);
            return on;
          },
          contains: (x) => classes.has(x),
        },
        get innerHTML() {
          return _html;
        },
        set innerHTML(val) {
          _html = String(val ?? "");
          el._html = _html;
          if (id === "drawer-body") el._noteEl = null;
          _parsed = parseControls(id, _html);
        },
        setAttribute(k, v) {
          el.attributes[k] = String(v);
        },
        getAttribute(k) {
          return el.attributes[k];
        },
        contains(targetNode) {
          if (!targetNode) return false;
          if (targetNode === el) return true;
          return typeof targetNode.id === "string" && targetNode.id.startsWith(`${id}:`);
        },
        focus() {
          activeState.element = el;
        },
        select() {},
        click() {},
        append(child) {
          if (child?.textContent) _html += child.textContent;
        },
        prepend() {},
        appendChild() {},
        removeChild() {},
        addEventListener(type, fn) {
          listeners.set(`${id}:${type}`, fn);
          el[`on${type}`] = fn;
        },
        querySelector() {
          return makeVirtualNode(`${id}:qs`, {}, "DIV", false);
        },
        querySelectorAll(sel) {
          if (id === "evidence-drawer") return elements.get("drawer-body")?.querySelectorAll(sel) || [];
          if (id === "handoff-modal") return elements.get("handoff-content")?.querySelectorAll(sel) || [];
          if (sel === "[data-inline-review]") return _parsed.inlineReview;
          if (sel === "[data-fact-id]") return _parsed.factCards;
          if (sel === "[data-evidence-id]") return _parsed.evidenceTargets;
          if (sel === "[data-popover-open]") return _parsed.popoverOpen;
          if (sel === "[data-fact-review-id]") return _parsed.factReviewBtns;
          if (sel === "[data-review-id]") return _parsed.reviewBtns;
          if (sel === "[data-project-id]") return _parsed.projectBtns;
          if (sel === ".presence-pill") return _parsed.presencePills;
          if (sel === "[data-chapter-id]") return _parsed.chapterBtns;
          return [];
        },
      };
      el._getParsed = () => _parsed;
      elements.set(id, el);
    }
    return elements.get(id);
  }

  for (const id of staticIds) element(id);

  const docListeners = {};
  const goalSurface = makeVirtualNode("goal-surface", {}, "SECTION", false);
  const lensPersonalBtn = makeVirtualNode("lens-personal", { lens: "personal" }, "BUTTON", false);
  const lensTeamBtn = makeVirtualNode("lens-team", { lens: "team" }, "BUTTON", false);
  const layerChoiceBtns = ["overview", "process", "source"].map((layer) => makeVirtualNode(`layer-${layer}`, { layerChoice: layer }, "BUTTON", false));
  const documentMock = {
    hidden: false,
    body: element("doc-body"),
    get activeElement() {
      return activeState.element;
    },
    execCommand: options.execCommand || (() => false),
    getElementById: element,
    querySelector(sel) {
      if (sel === ".goal-surface") return goalSurface;
      return null;
    },
    querySelectorAll(sel) {
      if (sel === ".lens") return [lensPersonalBtn, lensTeamBtn];
      if (sel === ".layer-choice") return layerChoiceBtns;
      const out = [];
      for (const el of elements.values()) {
        if (typeof el.querySelectorAll === "function") out.push(...el.querySelectorAll(sel));
      }
      return out;
    },
    createElement(tag) {
      return makeVirtualNode(`created:${tag}:${Math.random()}`, {}, tag.toUpperCase(), false);
    },
    addEventListener(type, fn) {
      docListeners[type] = fn;
    },
  };

  const windowMock = {
    innerWidth: options.innerWidth || 1440,
    innerHeight: options.innerHeight || 900,
    localStorage: options.localStorage,
    addEventListener() {},
  };

  const baseState = options.state || {
    project: { project_id: "proj-1", name: "M3 Test", read_only: false, evidence_count: 2, fact_count: 4 },
    projects: [
      { project_id: "proj-1", project_name: "M3 Test" },
      { project_id: "proj-2", project_name: "Secondary ReadOnly" },
      { project_id: "proj-bad", project_name: "Broken Project" },
    ],
    sample_mode: false,
    personal: {
      alice: {
        member_id: "alice",
        facts: [
          { id: "goal-a", kind: "goal", subject_key: "project.goal", value: "Ship A", status: "accepted", evidence_ids: ["e1"], observed_at: "2026-11-14T08:00:00Z" },
        ],
        evidence_ids: ["e1"],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: { root: { fact_id: "goal-a", label: "Ship A", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
      },
      bob: {
        member_id: "bob",
        facts: [
          { id: "goal-b", kind: "goal", subject_key: "project.goal", value: "Ship B", status: "conflicted", evidence_ids: ["e2"], observed_at: "2026-11-14T08:01:00Z" },
          { id: "task-b", kind: "task", subject_key: "task.auth", value: "尚未通过测试 password 已实现 [blocked]", task_state: "blocked", status: "proposed", evidence_ids: ["e2"], observed_at: "2026-11-14T08:02:00Z" },
          { id: "dec-b", kind: "decision", subject_key: "dec.store", value: "Use local JSON", status: "proposed", evidence_ids: ["e2"], observed_at: "2026-11-14T08:03:00Z" },
        ],
        evidence_ids: ["e2"],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [{ chapter_id: "c1", sequence: "01", title: "Phase 1", status: 'bad" onclick="alert(1)', count: '<img src=x>', fact_ids: ["task-b"] }],
        thinking_line: {
          root: { fact_id: "goal-b", label: "Ship B", status: "conflicted", evidence_ids: ["e2"] },
          branches: [
            {
              fact_id: "dec-b",
              label: "Use local JSON",
              status: "proposed",
              state: "active",
              evidence_ids: ["e2"],
              children: [
                { fact_id: "task-b", label: "Accepted pending task", status: "accepted", task_state: "pending", evidence_ids: ["e2"] },
              ],
            },
          ],
          reversals: [],
          code_nodes: [],
        },
      },
    },
    personal_activity: [
      { member_id: "bob", last_event_id: "e2", last_event_kind: "user_message", last_event_at: "2026-11-14T08:01:00Z", last_event_preview: "Ship B quote", event_count: 1 },
    ],
    team: {
      facts: [
        { id: "goal-a", kind: "goal", subject_key: "project.goal", value: "Ship A", status: "accepted", author: "alice", evidence_ids: ["e1"], observed_at: "2026-11-14T08:00:00Z" },
        { id: "goal-b", kind: "goal", subject_key: "project.goal", value: "Ship B", status: "conflicted", author: "bob", evidence_ids: ["e2"], observed_at: "2026-11-14T08:01:00Z" },
        { id: "task-b", kind: "task", subject_key: "task.auth", value: "尚未通过测试 password 已实现 [blocked]", task_state: "blocked", status: "proposed", author: "bob", evidence_ids: ["e2"], observed_at: "2026-11-14T08:02:00Z" },
        { id: "dec-b", kind: "decision", subject_key: "dec.store", value: "Use local JSON", status: "accepted", author: "bob", evidence_ids: ["e2"], observed_at: "2026-11-14T08:03:00Z" },
      ],
      evidence_ids: ["e1", "e2"],
      conflicts: [
        {
          subject_key: "project.goal",
          speculative_recommendation: {
            recommended_fact_id: "goal-a",
            recommended_value: "Ship A",
            hypothetical_resolution: "Ship A",
            confidence: "high",
            score: '<script>9</script>',
            tie: false,
            speculative_verified: true,
            evidence_ids: ["e1"],
          },
          sides: [
            { fact_id: "goal-a", value: "Ship A", status: "accepted", author: "alice", evidence_ids: ["e1"], observed_at: "2026-11-14T08:00:00Z" },
            { fact_id: "goal-b", value: "Ship B", status: "conflicted", author: "bob", evidence_ids: ["e2"], observed_at: "2026-11-14T08:01:00Z" },
          ],
        },
      ],
      directions: { candidates: [], current: [], history: [] },
      timeline_chapters: [],
      thinking_line: { root: { fact_id: "goal-a", label: "Ship A", status: "accepted", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
    },
    evidence: [
      { id: "e1", kind: "assistant_message", author: "alice", classification: "fact_source", content_preview: "Ship A quote", observed_at: "2026-11-14T08:00:00Z" },
      { id: "e2", kind: "user_message", author: "bob", classification: "fact_source", content_preview: "Ship B quote", observed_at: "2026-11-14T08:01:00Z" },
    ],
    candidate_relations: [
      { id: "rel-1", fact_id: "task-b", evidence_id: "e2", status: "candidate", method: "quote_match", basis: "Direct test log", score: 0.91 },
    ],
    confirmed_relations: [],
    review_history: [],
    fact_reviews: [],
    session_presence: { team: { accepted_count: 2, pending_count: 1 }, members: [{ member_id: "bob", label: "bob", is_agent_session: true, pending_count: 1 }] },
    handoff_brief: {
      focus_goal: { value: "Ship A", evidence_ids: ["e1"] },
      accepted_decisions: [{ value: "Use local JSON", evidence_ids: ["e2"] }],
      pending_candidates: [],
      open_todos: [{ value: "尚未通过测试 password 已实现 [blocked]", task_state: "blocked", author: "bob", evidence_ids: ["e2"] }],
      code_nodes: [],
      markdown: "# Brief",
    },
    intake: { enabled: false },
  };

  let slowResolve = null;
  let slowReject = null;
  let slowPopErrReject = null;
  const fetchFn = async (url, fetchOpts = {}) => {
    requests.push({ url, method: fetchOpts.method || "GET", body: fetchOpts.body || null });
    if (url.includes("project_id=proj-bad")) {
      return { ok: false, status: 503, headers: { get: () => "application/json" }, json: async () => ({ error: "Project unavailable" }) };
    }
    if (url.startsWith("/api/state") && url.includes("project_id=proj-2")) {
      const roState = structuredClone(baseState);
      roState.project = { ...roState.project, project_id: "proj-2", name: "Secondary ReadOnly", read_only: true };
      return { ok: true, status: 200, json: async () => roState };
    }
    if (url.startsWith("/api/state")) return { ok: true, status: 200, json: async () => structuredClone(baseState) };
    if (url.startsWith("/api/review")) {
      return { ok: true, status: 200, json: async () => structuredClone(baseState) };
    }
    if (url === "/api/investigate") {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          conclusion: "Secondary answer",
          goal: "Ship A",
          active_tasks: ["t1"],
          evidence_ids: ["e1"],
          next_action: "verify",
          acceptance_condition: "pass",
          conflicts: [{ subject_key: "project.goal", sides: [{ fact_id: "goal-b", status: "conflicted", value: "Ship B", evidence_ids: ["e2"] }] }],
          findings: [{ fact_id: "task-b", claim_type: "assistant_report", status: "proposed", quote: "test", evidence_ids: ["e2"] }],
        }),
      };
    }
    if (url.startsWith("/api/export")) {
      if (options.failExport) {
        return { ok: false, status: 500, headers: { get: () => "application/json" }, json: async () => ({ error: "export failed" }) };
      }
      return {
        ok: true,
        status: 200,
        headers: { get: () => 'attachment; filename="handoff-prd.md"' },
        blob: async () => ({ text: async () => "# PRD EXPORT" }),
      };
    }
    if (url === "/api/evidence?id=e-slow") {
      return new Promise((resolve, reject) => {
        slowResolve = () => resolve({ ok: true, status: 200, json: async () => ({ id: "e-slow", kind: "assistant_message", author: "slow", content: "SLOW CONTENT", metadata: {} }) });
        slowReject = () => reject(Object.assign(new Error("late timeout"), { name: "AbortError" }));
      });
    }
    if (url.startsWith("/api/evidence?id=e-slow-err")) {
      return new Promise((_, reject) => {
        slowPopErrReject = () => reject(new Error("late 404 not found"));
      });
    }
    if (url.startsWith("/api/evidence?id=e-404") || url.startsWith("/api/evidence?id=e-err-pop")) {
      return { ok: false, status: 404, json: async () => ({ error: 'Evidence missing <img src=x onerror=alert(1)>' }) };
    }
    if (url === "/api/evidence?id=e-timeout") {
      return Promise.reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
    }
    const rawId = url.split("id=")[1] || "e1";
    const id = decodeURIComponent(rawId.split("&")[0] || "e1");
    const suffix = url.includes("project_id=proj-2") ? ":proj-2" : "";
    return { ok: true, status: 200, json: async () => ({ id, kind: "assistant_message", author: "fast", content: `CONTENT:${id}${suffix}`, metadata: {} }) };
  };

  const context = vm.createContext({
    console,
    AbortController,
    setTimeout,
    clearTimeout,
    setInterval() {},
    document: documentMock,
    window: windowMock,
    navigator: options.navigator,
    fetch: options.noFetch ? undefined : fetchFn,
  });

  if (options.initialFetch) {
    vm.runInContext(appSource, context);
  }
  return {
    context,
    element,
    documentMock,
    windowMock,
    docListeners,
    goalSurface,
    layerChoiceBtns,
    activeState,
    baseState,
    makeVirtualNode,
    requests,
    getSlowResolve: () => slowResolve,
    getSlowReject: () => slowReject,
    getSlowPopErrReject: () => slowPopErrReject,
    flush: async () => {
      for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
    },
  };
}

async function main() {
  // 1 & 2 & 3 & 4 & 11: Goal cross-ID conflict isolation, read_only honesty, task regex removal, resolveFactStatus, XSS escaping
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();

    vm.runInContext('state.lens = "personal"; state.member = "bob"; render();', h.context);
    assert.ok(h.element("goal-status").textContent.includes("存在分歧") && !h.element("goal-status").classList.contains("is-accepted"), "Conflicted member B goal did not show conflicted Chinese status");
    assert.ok(h.goalSurface.classList.contains("is-conflicted"), "Goal surface missing is-conflicted class");
    assert.equal(h.baseState.personal.bob.facts[0].status, "conflicted");

    const todoHtml = h.element("personal-todo-list").innerHTML;
    assert.ok(todoHtml.includes("☐"), "Blocked task with substring was falsely checked");
    assert.ok(!todoHtml.includes("☑"), "Blocked task rendered ☑");
    assert.ok(!todoHtml.includes("任务状态：已实现"), "Blocked task claimed 已实现");

    const decHtml = h.element("personal-decision-list").innerHTML;
    assert.ok(decHtml.includes("✓ 已确认") && decHtml.includes("is-accepted") && !decHtml.includes(">待确认<"), "Accepted team fact in personal list showed contradictory unaccepted badge");

    // Read-only project must NEVER emit false ✓ 团队事实 for unaccepted task-b
    vm.runInContext("state.data.project.read_only = true; render();", h.context);
    const roTodoHtml = h.element("personal-todo-list").innerHTML;
    assert.ok(!roTodoHtml.includes("✓ 团队事实"), "Read-only mode falsely promoted unaccepted task");

    // Rejected fact omits duplicate reject button
    vm.runInContext('state.data.project.read_only = false; state.data.review_history = [{ action: "reject_fact", fact_id: "task-b", reviewer: "lead" }]; render();', h.context);
    const rejTodoHtml = h.element("personal-todo-list").innerHTML;
    assert.ok(rejTodoHtml.includes("is-rejected") && rejTodoHtml.includes("已忽略"), "Rejected status missing on personal task card");
    assert.ok(!rejTodoHtml.includes('data-inline-review="reject_fact"'), "Duplicate reject button remained on rejected card");

    // XSS & attribute escaping
    const timelineHtml = h.element("chapter-timeline").innerHTML;
    assert.ok(!timelineHtml.includes('onclick="alert(1)"'), "Timeline status broke attribute boundary");
    assert.ok(timelineHtml.includes("&lt;img src=x&gt;"), "Timeline count was not escaped");
    assert.ok(timelineHtml.includes("chapter-node pending"), "Invalid timeline status token did not fall back to pending");

    vm.runInContext('state.lens = "team"; render();', h.context);
    const conflictHtml = h.element("conflict-list").innerHTML;
    assert.ok(conflictHtml.includes("&lt;script&gt;9&lt;/script&gt;") && !conflictHtml.includes("<script>9</script>"), "rec.score was not escaped");
    vm.runInContext('state.data.team.facts[2].direction_suggestion = "evil\\" onclick=\\"x()"; openFact("task-b");', h.context);
    assert.ok(!h.element("drawer-body").innerHTML.includes('confirm_evil"'), "Unsanitized direction_suggestion injected attribute");
  }

  // 5 & 7: Stale #review-note isolation & nested inline-review keyboard guard
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();
    vm.runInContext('state.lens = "team"; render(); document.getElementById("reviewer-input").value = "Alice"; openFact("task-b");', h.context);
    const noteEl = h.documentMock.getElementById("review-note");
    assert.ok(noteEl, "#review-note missing inside team drawer");
    noteEl.value = "DO NOT LEAK THIS NOTE";
    vm.runInContext("closeDrawer();", h.context);
    assert.equal(h.element("drawer-body").innerHTML, "", "closeDrawer did not clear #drawer-body");
    assert.equal(h.documentMock.getElementById("review-note"), null, "Stale #review-note remained after closeDrawer");

    vm.runInContext('state.lens = "personal"; state.member = "bob"; render();', h.context);
    const todoParsed = h.element("personal-todo-list")._getParsed();
    const outerCard = todoParsed.factCards[0];
    const inlineAccept = todoParsed.inlineReview.find((b) => b.dataset.inlineReview === "accept_fact");
    let stopped = false;
    inlineAccept.onkeydown({ key: "Enter", stopPropagation: () => { stopped = true; } });
    assert.ok(stopped, "Inline review button did not stop Enter keydown propagation");
    outerCard.onkeydown({ key: "Enter", target: inlineAccept, preventDefault() {} });
    assert.equal(h.element("evidence-drawer").hidden, true, "Outer card hijacked Enter on nested inline button");

    await inlineAccept.onclick({ stopPropagation() {}, preventDefault() {} });
    await h.flush();
    assert.equal(h.element("evidence-drawer").hidden, true, "Inline triage unexpectedly forced open #evidence-drawer");
    const reviewReq = h.requests.find((r) => r.url === "/api/review");
    assert.ok(reviewReq && JSON.parse(reviewReq.body).note === "", "Drawer note leaked into inline triage submission");
  }

  // 6: Modal auto-focus, nested drawer z-order preservation, and topmost-only Escape stack
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();
    const briefBtn = h.element("btn-handoff-brief");
    briefBtn.focus();
    vm.runInContext("openHandoffBrief();", h.context);
    assert.equal(h.element("handoff-modal").hidden, false);
    assert.equal(h.activeState.element, h.element("handoff-close-btn"), "openHandoffBrief did not move focus inside modal");
    assert.ok(!h.element("handoff-content").innerHTML.includes("☑"), "Handoff brief used unsafe regex on blocked task");

    const modalPill = h.element("handoff-content")._getParsed().evidenceTargets[0];
    modalPill.focus();
    await modalPill.onclick({ stopPropagation() {} });
    assert.equal(h.element("evidence-drawer").hidden, false, "Drawer did not open from modal pill");
    assert.equal(h.element("handoff-modal").hidden, false, "Opening drawer closed parent handoff modal");
    assert.equal(h.activeState.element, h.element("drawer-close"), "Drawer did not focus close button");

    h.docListeners.keydown({ key: "Escape" });
    assert.equal(h.element("evidence-drawer").hidden, true, "First Escape did not close drawer");
    assert.equal(h.element("handoff-modal").hidden, false, "First Escape prematurely closed parent modal");
    assert.equal(h.activeState.element, modalPill, "Closing nested drawer did not restore focus to modal evidence pill");

    h.docListeners.keydown({ key: "Escape" });
    assert.equal(h.element("handoff-modal").hidden, true, "Second Escape did not close handoff modal");
    assert.equal(h.element("scrim").hidden, true, "Scrim remained visible after all overlays closed");
    assert.equal(h.activeState.element, briefBtn, "Closing handoff modal did not restore focus to trigger button");
  }

  // 8: Popover vertical clamping on small viewport, race guard, and background error isolation
  {
    const h = buildTestHarness({ initialFetch: true, innerHeight: 180, innerWidth: 390 });
    await h.flush();
    const anchor = { getBoundingClientRect: () => ({ top: 150, bottom: 170, left: 20, right: 80 }) };
    const pSlow = h.context.showCitationPopover(anchor, "e-slow");
    const pFast = h.context.showCitationPopover(anchor, "e1");
    await pFast;
    const topPx = Number.parseFloat(h.element("citation-popover").style.top);
    assert.ok(topPx >= 12, `Popover top clamped below 12px: ${topPx}`);
    h.getSlowResolve()();
    await pSlow;
    assert.ok(h.element("citation-popover").innerHTML.includes("CONTENT:e1"), "Slow response overwrote current popover evidence");

    await h.context.showCitationPopover(anchor, "e-timeout");
    assert.equal(h.element("connection-label").textContent, "本地工作区", "Background popover timeout polluted global connection banner");
  }

  // 9 & 10 & 12: copyHandoffMarkdown honesty, exportCognitiveAsset zero ReferenceError, STATUS_BADGE_MAP prototype safety, prefetch fetch guard
  {
    let execCalled = false;
    const h = buildTestHarness({ initialFetch: true, execCommand: () => { execCalled = true; return false; } });
    await h.flush();
    await vm.runInContext("copyHandoffMarkdown()", h.context);
    assert.ok(execCalled);
    assert.ok(!h.element("handoff-copy-btn").textContent.includes("已复制"), "Failed copy fallback reported false success");

    await vm.runInContext("exportCognitiveAsset('prd', 'handoff-export-prd-btn', '已导出 PRD')", h.context);
    assert.equal(h.element("handoff-export-prd-btn").textContent, "请手动复制", "exportCognitiveAsset falsely reported success when neither download nor clipboard succeeded");
    assert.equal(h.element("handoff-export-prd-btn").getAttribute("data-clipboard-fallback"), "true");

    const badge = vm.runInContext('renderStatusBadge("constructor")', h.context);
    assert.ok(badge.includes("is-proposed") && !badge.includes("undefined"), `Prototype lookup polluted badge: ${badge}`);

    const hNoFetch = buildTestHarness({ noFetch: true, initialFetch: false });
    vm.runInContext(appSource.replace(/loadState\(\)\.catch[\s\S]*$/m, ""), hNoFetch.context);
    vm.runInContext('prefetchEvidence("e99")', hNoFetch.context);
    const hasLoadingKey = vm.runInContext('Object.prototype.hasOwnProperty.call(state.evidenceCache, "_loading_e99")', hNoFetch.context);
    assert.equal(hasLoadingKey, false, "prefetchEvidence leaked _loading_ key when fetch was unavailable");
  }

  // 13: Thinking Tree completion honesty, accessibility attrs, North Star rejected state, & non-nested div buttons
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();
    vm.runInContext('state.lens = "personal"; state.member = "bob"; render();', h.context);
    const treeHtml = h.element("thinking-line-canvas").innerHTML;
    assert.ok(treeHtml.includes("☐") && !treeHtml.includes("☑") && !treeHtml.includes("leaf-done"), "Accepted pending child in Thinking Tree falsely marked completed");
    assert.ok(treeHtml.includes("已确认"), "Thinking Tree branch did not inherit accepted status from resolveFactStatus");
    assert.ok(treeHtml.includes('class="thinking-leaf " role="button" tabindex="0" data-fact-id="task-b"'), "Interactive Thinking Tree leaf missing role=button/tabindex=0");
    assert.ok(treeHtml.includes('class="thinking-branch-node" role="button" tabindex="0" data-fact-id="dec-b"'), "Interactive Thinking Tree branch missing role=button/tabindex=0");
    assert.ok(treeHtml.includes('class="thinking-root proposed" role="button" tabindex="0" data-fact-id="goal-b"'), "Interactive Thinking Tree root missing role=button/tabindex=0");

    const actHtml = h.element("personal-activity-list").innerHTML;
    assert.ok(actHtml.includes('<div class="activity-item" role="button" tabindex="0"') && !actHtml.includes('<button'), "activity-item nested button inside button");
    const factListHtml = h.element("fact-list").innerHTML;
    assert.ok(factListHtml.includes('<div class="fact-card" role="button" tabindex="0"') && !factListHtml.includes('<button'), "fact-card nested button inside button");

    vm.runInContext('state.data.personal.bob.facts[0].status = "rejected"; render();', h.context);
    assert.equal(h.element("goal-status").textContent, "已忽略");
    assert.ok(h.goalSurface.classList.contains("is-rejected"), "Rejected North Star goal missing .is-rejected class");
    assert.ok(!h.goalSurface.classList.contains("is-proposed"), "Rejected North Star goal still carried .is-proposed");
  }

  // 14: Conflict speculative recommendation fallback + right-pane goal-b targeting + .presence-pill switch
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();
    vm.runInContext('state.lens = "team"; delete state.data.team.conflicts[0].speculative_recommendation.evidence_ids; render(); document.getElementById("reviewer-input").value = "Lead";', h.context);
    const conflictHtml = h.element("conflict-list").innerHTML;
    assert.ok(!conflictHtml.includes("unlinked"), "Missing rec.evidence_ids fell back to unlinked despite sides match");
    assert.ok(conflictHtml.includes('data-evidence-id="e1"'), "Speculative recommendation badge missing evidence link");

    const inlineBtns = h.element("conflict-list")._getParsed().inlineReview;
    assert.equal(inlineBtns.length, 1, "Accepted left side should not show duplicate accept button; right conflicted side should");
    assert.equal(inlineBtns[0].dataset.targetId, "goal-b", "Conflict right pane button did not target goal-b");
    inlineBtns[0].onclick({ stopPropagation() {}, preventDefault() {} });
    await h.flush();
    const goalReq = h.requests.find((r) => r.url === "/api/review");
    assert.equal(JSON.parse(goalReq.body).fact_id, "goal-b");

    const pills = h.element("session-presence-bar")._getParsed().presencePills;
    const bobPill = pills.find((p) => p.dataset.targetMember === "bob");
    assert.ok(bobPill, "Presence pill for bob missing");
    bobPill.onclick();
    assert.equal(vm.runInContext("state.lens", h.context), "personal");
    assert.equal(vm.runInContext("state.member", h.context), "bob");
  }

  // 15: Blank reviewer guard, bindDynamicControls NOT hijacking Confirm support, & loadProjects error rollback
  {
    const h = buildTestHarness({ initialFetch: true });
    await h.flush();
    vm.runInContext('state.lens = "personal"; state.member = "bob"; document.getElementById("reviewer-input").value = ""; render();', h.context);
    const inlineAccept = h.element("personal-todo-list")._getParsed().inlineReview[0];
    inlineAccept.onclick({ stopPropagation() {}, preventDefault() {} });
    await h.flush();
    assert.equal(h.requests.filter((r) => r.url === "/api/review").length, 0, "Blank reviewer still posted /api/review");
    assert.equal(h.element("compass-toast").hidden, false, "Blank reviewer did not show toast warning");
    assert.ok(h.element("compass-toast").textContent.includes("请先填写负责人姓名"), "Blank reviewer toast missing reviewer guidance");
    assert.equal(h.element("evidence-drawer").hidden, true, "Blank reviewer unexpectedly opened interrupting drawer");

    vm.runInContext('state.lens = "team"; document.getElementById("reviewer-input").value = "Alice"; render(); openFact("task-b");', h.context);
    const confirmSupportBtn = h.element("drawer-body")._getParsed().reviewBtns[0];
    assert.ok(confirmSupportBtn && confirmSupportBtn.dataset.reviewId === "rel-1", "Confirm support button missing in drawer");
    vm.runInContext("bindDynamicControls();", h.context);
    confirmSupportBtn.onclick();
    await h.flush();
    const relReq = h.requests.find((r) => r.url === "/api/review" && JSON.parse(r.body).relation_id === "rel-1");
    assert.ok(relReq, "bindDynamicControls overwrote drawer Confirm support [data-review-id][data-fact-id] handler");

    const badProjBtn = h.element("project-list")._getParsed().projectBtns.find((b) => b.dataset.projectId === "proj-bad");
    assert.ok(badProjBtn, "Broken project choice button missing");
    await badProjBtn.onclick();
    assert.equal(vm.runInContext("state.projectId", h.context), "proj-1", "loadProjects did not roll back state.projectId on error");
    assert.ok(h.element("connection-label").textContent.includes("切换项目失败"), "Project switch failure did not surface connection error");
  }

  // 16: Layered backdrop click priority, openEvidence async/close race, popover jump/Esc focus return & right-edge clamp, export failure
  {
    const h = buildTestHarness({ initialFetch: true, innerWidth: 420, innerHeight: 300, failExport: true });
    await h.flush();
    vm.runInContext("openHandoffBrief();", h.context);
    const modalPill = h.element("handoff-content")._getParsed().evidenceTargets[0];
    modalPill.focus();
    await modalPill.onclick({ stopPropagation() {} });
    assert.equal(h.element("handoff-modal").hidden, false);
    assert.equal(h.element("evidence-drawer").hidden, false);

    // Click on #handoff-modal backdrop MUST close topmost #evidence-drawer first
    h.element("handoff-modal").onclick({ target: h.element("handoff-modal") });
    assert.equal(h.element("evidence-drawer").hidden, true, "Clicking modal backdrop did not close topmost drawer first");
    assert.equal(h.element("handoff-modal").hidden, false, "Clicking modal backdrop while drawer open closed parent modal underneath");
    vm.runInContext("closeHandoffBrief();", h.context);

    // openEvidence race: slow -> closeDrawer -> late resolve AND late reject must NOT reopen closed drawer
    const pSlowClose = h.context.openEvidence("e-slow");
    vm.runInContext("closeDrawer();", h.context);
    h.getSlowResolve()();
    await pSlowClose;
    assert.equal(h.element("evidence-drawer").hidden, true, "Late slow evidence resolution reopened closed drawer");

    const pSlowSwitch = h.context.openEvidence("e-slow");
    const pFastSwitch = h.context.openEvidence("e1");
    await pFastSwitch;
    h.getSlowReject()();
    await pSlowSwitch;
    assert.ok(h.element("drawer-body").innerHTML.includes("CONTENT:e1"), "Late slow evidence error overwrote newer evidence drawer");
    vm.runInContext("closeDrawer();", h.context);

    // Popover right-edge clamp, Esc inside popover focus restoration, & .popover-jump -> closeDrawer focus restoration
    const rightAnchor = h.makeVirtualNode("anchor-pill", { evidenceId: "e1" }, "SPAN", false);
    rightAnchor._rect = { top: 40, bottom: 60, left: 390, right: 416 };
    rightAnchor.focus();
    await h.context.showCitationPopover(rightAnchor, "e1");
    const leftPx = Number.parseFloat(h.element("citation-popover").style.left);
    assert.ok(leftPx >= 12 && leftPx + 360 <= 420 - 12, `Popover left not clamped inside right viewport edge: left=${leftPx}`);

    const jumpBtn = h.element("citation-popover")._getParsed().popoverOpen[0];
    jumpBtn.id = "citation-popover:pop:e1";
    jumpBtn.focus();
    h.docListeners.keydown({ key: "Escape" });
    assert.equal(h.element("citation-popover").hidden, true, "Escape did not hide citation popover");
    assert.equal(h.activeState.element, rightAnchor, "Escape inside popover did not restore focus to anchor");

    await h.context.showCitationPopover(rightAnchor, "e1");
    await h.element("citation-popover")._getParsed().popoverOpen[0].onclick({ stopPropagation() {} });
    assert.equal(h.element("evidence-drawer").hidden, false);
    vm.runInContext("closeDrawer();", h.context);
    assert.equal(h.activeState.element, rightAnchor, "Closing drawer opened via popover-jump did not return focus to anchor");

    await vm.runInContext("exportCognitiveAsset('prd', 'handoff-export-prd-btn', '已导出 PRD')", h.context);
    assert.equal(h.element("handoff-export-prd-btn").textContent, "导出失败", "Failed export did not show 导出失败");
  }

  // 17: Round 3 P1 contracts (Personal North Star, detached trigger recovery, brief fact_id dedup + badges, layer-choice, conflict/trace resolveFactStatus, stale/direction inline hide, evidence_requests + XSS)
  {
    const h = buildTestHarness({
      initialFetch: true,
      navigator: { clipboard: { writeText: async () => {} } },
    });
    await h.flush();

    // Personal North Star resolves team acceptance even when personal fact copy says proposed
    vm.runInContext(`
      state.lens = "personal";
      state.member = "bob";
      state.data.personal.bob.facts.unshift({ id: "goal-team-acc", kind: "goal", subject_key: "project.goal", value: "Accepted Team Goal", status: "proposed", evidence_ids: ["e1"], observed_at: "2026-11-14T08:00:00Z" });
      state.data.team.facts.push({ id: "goal-team-acc", kind: "goal", subject_key: "project.goal", value: "Accepted Team Goal", status: "accepted", evidence_ids: ["e1"], observed_at: "2026-11-14T08:00:00Z" });
      render();
    `, h.context);
    assert.equal(h.element("goal-title").textContent, "Accepted Team Goal", "Personal North Star did not prefer team-accepted goal via resolveFactStatus");
    assert.ok(String(h.element("goal-status").className || "").includes("is-accepted") && h.element("goal-status").textContent.includes("已"), "Personal North Star did not display confirmed badge");

    // Stale source & direction_suggestion hide inline accept while keeping non-stale reject; evidence_requests missing new_evidence_ids safe + XSS escaped
    vm.runInContext(`
      state.data.personal.bob.facts.push(
        { id: "task-stale", kind: "task", subject_key: "task.stale", value: "Stale task", status: "proposed", source_state: { status: "superseded" }, evidence_ids: ["e2"], observed_at: "2026-11-14T08:04:00Z" },
        { id: "dec-dir", kind: "decision", subject_key: "dec.dir", value: "Deferred dir", status: "proposed", direction_suggestion: "deferred", evidence_ids: ["e2"], observed_at: "2026-11-14T08:05:00Z" }
      );
      state.data.evidence_requests = [{ member_id: "bob", fact_id: "task-b", value: "Req <img src=x onerror=alert(1)>", status: "pending", note: "<script>bad</script>" }];
      render();
    `, h.context);
    const staleInline = h.element("personal-todo-list")._getParsed().inlineReview;
    assert.ok(!staleInline.some((n) => n.dataset.targetId === "task-stale" && n.dataset.inlineReview === "accept_fact"), "Stale task still showed inline accept");
    assert.ok(staleInline.some((n) => n.dataset.targetId === "task-stale" && n.dataset.inlineReview === "reject_fact"), "Stale task should still allow reject");
    const dirInline = h.element("personal-decision-list")._getParsed().inlineReview;
    assert.ok(!dirInline.some((n) => n.dataset.targetId === "dec-dir" && n.dataset.inlineReview === "accept_fact"), "direction_suggestion decision still showed inline accept");
    assert.ok(!h.element("evidence-request-list").innerHTML.includes("<script>"), "XSS in evidence_requests note not escaped");

    // Layer choice updates body dataset.layer & active class; chapter filter + clear button
    h.layerChoiceBtns[1].onclick();
    assert.equal(h.documentMock.body.dataset.layer, "process", ".layer-choice click did not update document.body.dataset.layer");
    assert.ok(h.layerChoiceBtns[1].classList.contains("active"), ".layer-choice did not toggle active class");
    const chapBtn = h.element("chapter-timeline")._getParsed().chapterBtns[0];
    assert.ok(chapBtn, "Timeline chapter button missing");
    chapBtn.onclick();
    assert.equal(vm.runInContext("state.activeChapterId", h.context), "c1", "Chapter click did not set state.activeChapterId");
    h.element("thinking-clear-filter").onclick();
    assert.equal(vm.runInContext("state.activeChapterId", h.context), null, "Clear chapter filter did not reset activeChapterId");

    // Detached trigger focus recovery after render()
    const detachedTrigger = h.element("personal-todo-list")._getParsed().factCards.find((n) => n.dataset.factId === "task-b");
    detachedTrigger.focus();
    h.context.openDrawer("Task B", "<p>detail</p>", detachedTrigger);
    detachedTrigger.isConnected = false;
    vm.runInContext("render();", h.context);
    vm.runInContext("closeDrawer();", h.context);
    assert.notEqual(h.activeState.element, detachedTrigger, "closeDrawer focused detached DOM trigger");
    assert.equal(h.activeState.element.dataset.factId, "task-b", "closeDrawer did not reconnect focus to replacement task-b card");

    // Detached trigger that disappears across view switch falls back safely
    const vanishTrigger = h.makeVirtualNode("vanished", { factId: "nonexistent-after-switch" }, "DIV", false);
    vanishTrigger.focus();
    h.context.openDrawer("Vanish", "<p>body</p>", vanishTrigger);
    vanishTrigger.isConnected = false;
    vm.runInContext("closeDrawer();", h.context);
    assert.equal(h.activeState.element, h.element("btn-handoff-brief"), "closeDrawer did not fall back to safe control when trigger vanished");

    // Handoff brief fact_id dedup preserves non-task overlapping wording + status badges + XSS escape + clipboard success + #scrim priority
    vm.runInContext(`
      state.data.handoff_brief = {
        focus_goal: { fact_id: "goal-b", value: "Brief Goal <img src=x onerror=alert(1)>", status: "conflicted", evidence_ids: ["e2"] },
        accepted_decisions: [{ value: "Confirmed dec", evidence_ids: ["e1"] }],
        pending_candidates: [
          { fact_id: "task-b", kind: "task", value: "Shared wording", status: "proposed", author: "bob", evidence_ids: ["e2"] },
          { fact_id: "dec-overlap", kind: "decision", value: "Shared wording", status: "rejected", author: "bob <script>", evidence_ids: ["e2"] }
        ],
        open_todos: [{ fact_id: "task-b", value: "Shared wording", task_state: "blocked", status: "proposed", author: "bob", evidence_ids: ["e2"] }],
        code_nodes: [],
        markdown: "# Brief"
      };
      state.data.review_history = [
        { action: "reject_fact", fact_id: "dec-overlap" },
        { action: "reject_fact", fact_id: "goal-b" }
      ];
      state.lens = "team";
      render();
      openHandoffBrief();
    `, h.context);
    const briefHtml = h.element("handoff-content").innerHTML;
    assert.ok(briefHtml.includes("dec-overlap") || briefHtml.includes("is-rejected"), "Handoff brief did not show rejected badge on dec-overlap");
    assert.ok(briefHtml.includes("Shared wording"), "Non-task candidate with overlapping wording was dropped");
    assert.equal((briefHtml.match(/Shared wording/g) || []).length, 2, "Duplicate task-b should be deduped while dec-overlap kept (exact 2 occurrences)");
    assert.ok(!briefHtml.includes("<img") && !briefHtml.includes("<script>"), "XSS in handoff brief not escaped");
    await vm.runInContext("copyHandoffMarkdown()", h.context);
    assert.equal(h.element("handoff-copy-btn").textContent, "已复制到剪贴板", "Clipboard copy success text missing");

    h.context.openDrawer("On top", "<p>top</p>");
    h.element("scrim").onclick();
    assert.equal(h.element("evidence-drawer").hidden, true, "First scrim click did not close topmost drawer");
    assert.equal(h.element("handoff-modal").hidden, false, "First scrim click closed underlying modal");
    h.element("scrim").onclick();
    assert.equal(h.element("handoff-modal").hidden, true, "Second scrim click did not close modal");

    // Conflict pane & trace resolveFactStatus sync after reject_fact on goal-b
    assert.ok(h.element("conflict-list").innerHTML.includes("is-rejected"), "Conflict pane did not reflect reject_fact from review_history");
    assert.ok(h.element("trace-track").innerHTML.includes("is-rejected"), "Trace fact did not reflect reject_fact from review_history");

    // resolveFactStatus must not match undefined === undefined when id/fact_id is omitted
    vm.runInContext('state.data.team.facts.push({ kind: "goal", value: "Broken", status: "accepted" }); state.data.review_history.push({ action: "reject_fact" });', h.context);
    const idlessStatus = vm.runInContext('resolveFactStatus({ status: "conflicted" })', h.context);
    assert.equal(idlessStatus, "conflicted", "resolveFactStatus matched undefined === undefined across missing-id entries");
  }

  // 18: Secondary read-only project cache clearing & project_id scoping + prefetch 0x0/_error_ guards + popover race/404/no-dataset
  {
    const h = buildTestHarness({
      initialFetch: true,
      navigator: { clipboard: { writeText: async () => {} } },
    });
    await h.flush();

    // Put e1 in cache, then switch to read-only proj-2 -> cache cleared & project_id appended on evidence/export/investigate
    vm.runInContext('state.evidenceCache["e1"] = { id: "e1", content: "STALE" };', h.context);
    const proj2Btn = h.element("project-list")._getParsed().projectBtns.find((b) => b.dataset.projectId === "proj-2");
    assert.ok(proj2Btn, "Secondary project button missing");
    await proj2Btn.onclick();
    assert.equal(vm.runInContext('state.projectId', h.context), "proj-2");
    assert.equal(vm.runInContext('Boolean(state.evidenceCache["e1"])', h.context), false, "Switching project did not clear evidenceCache");

    await h.context.openEvidence("e1");
    assert.ok(h.requests.some((r) => r.url === "/api/evidence?id=e1&project_id=proj-2"), "openEvidence omitted project_id for read_only project");
    await vm.runInContext("exportCognitiveAsset('prd', 'handoff-export-prd-btn', '已导出 PRD')", h.context);
    assert.ok(h.requests.some((r) => r.url === "/api/export?format=prd&project_id=proj-2"), "exportCognitiveAsset omitted project_id");
    assert.equal(h.element("handoff-export-prd-btn").textContent, "已导出 PRD", "exportCognitiveAsset did not report success when clipboard writeText succeeded");
    h.element("export-state").onclick();
    await h.flush();
    assert.ok(h.requests.some((r) => r.url === "/api/export?project_id=proj-2"), "#export-state omitted project_id");
    h.element("investigation-question").value = "status?";
    await vm.runInContext("investigateProject({ preventDefault() {} })", h.context);
    const invReq = h.requests.find((r) => r.url === "/api/investigate");
    assert.ok(invReq && JSON.parse(invReq.body).project_id === "proj-2", "investigateProject omitted project_id");
    const invHtml = h.element("investigation-answer").innerHTML;
    assert.ok(invHtml.includes("status-badge"), "renderInvestigation did not render status badges");

    // Proximal 0x0 node skipped + _error_ blocks repeat prefetch
    const zeroBtn = h.makeVirtualNode("zero-ev", { evidenceId: "e-zero" }, "SPAN", false);
    zeroBtn._rect = { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 };
    const errBtn = h.makeVirtualNode("err-ev", { evidenceId: "e-err-pop" }, "SPAN", false);
    errBtn._rect = { top: 0, bottom: 20, left: 0, right: 40, width: 40, height: 20 };
    const origQsa = h.documentMock.querySelectorAll;
    h.documentMock.querySelectorAll = (sel) => sel === "[data-evidence-id]" ? [zeroBtn, errBtn] : origQsa(sel);
    h.context.handleProximityPrefetch({ clientX: 5, clientY: 5 });
    await h.flush();
    assert.equal(h.requests.filter((r) => r.url.includes("e-zero")).length, 0, "0x0 element triggered prefetch");
    const errCountAfterFirst = h.requests.filter((r) => r.url.includes("e-err-pop")).length;
    assert.equal(errCountAfterFirst, 1);
    h.context.handleProximityPrefetch({ clientX: 5, clientY: 5 });
    await h.flush();
    assert.equal(h.requests.filter((r) => r.url.includes("e-err-pop")).length, 1, "_error_ did not stop repeat prefetch");
    h.documentMock.querySelectorAll = origQsa;

    // Popover 404 message (with XSS escaped) & late reject race guard & missing popover.dataset resilience
    const anchor = h.makeVirtualNode("pop-anchor", { evidenceId: "e-404" }, "SPAN", false);
    await h.context.showCitationPopover(anchor, "e-404");
    const popHtml404 = h.element("citation-popover").innerHTML;
    assert.ok(popHtml404.includes("原文摘录暂不可用"), "Popover 404 did not show unavailable message");
    assert.ok(!popHtml404.includes("<img"), "Popover 404 error leaked unescaped HTML");

    const slowErrPromise = h.context.showCitationPopover(anchor, "e-slow-err");
    await h.context.showCitationPopover(anchor, "e1");
    h.getSlowPopErrReject()();
    await slowErrPromise;
    assert.ok(h.element("citation-popover").innerHTML.includes("CONTENT:e1"), "Late 404 popover rejection overwrote active e1 popover");

    delete h.element("citation-popover").dataset;
    await h.context.showCitationPopover(anchor, "e1");
    assert.equal(h.element("citation-popover").hidden, false, "showCitationPopover failed without popover.dataset");
  }

  // 19: Solo vs Team route adaptive rendering, single-user drawer commit, & localStorage reviewer memory
  {
    const store = new Map();
    const localStorageMock = {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
    };
    const soloState = {
      project: { project_id: "solo-1", name: "Solo Workspace", read_only: false, evidence_count: 1, fact_count: 2 },
      projects: [{ project_id: "solo-1", project_name: "Solo Workspace" }],
      sample_mode: false,
      personal: {
        me: {
          member_id: "me",
          facts: [
            { id: "g1", kind: "goal", subject_key: "project.goal", value: "Build Compass", status: "proposed", evidence_ids: ["e1"], observed_at: "2026-11-15T01:00:00Z" },
            { id: "d1", kind: "decision", subject_key: "dec.mode", value: "Prefer Solo Mode First", status: "proposed", evidence_ids: ["e1"], observed_at: "2026-11-15T01:02:00Z" },
          ],
          evidence_ids: ["e1"],
          directions: { candidates: [], current: [], history: [] },
          timeline_chapters: [],
          thinking_line: { root: { fact_id: "g1", label: "Build Compass", status: "proposed", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
        },
      },
      personal_activity: [
        { member_id: "me", last_event_id: "e1", last_event_kind: "user_message", last_event_at: "2026-11-15T01:00:00Z", last_event_preview: "Solo note", event_count: 1 },
      ],
      team: {
        facts: [
          { id: "g1", kind: "goal", subject_key: "project.goal", value: "Build Compass", status: "proposed", author: "me", evidence_ids: ["e1"], observed_at: "2026-11-15T01:00:00Z" },
          { id: "d1", kind: "decision", subject_key: "dec.mode", value: "Prefer Solo Mode First", status: "proposed", author: "me", evidence_ids: ["e1"], observed_at: "2026-11-15T01:02:00Z" },
        ],
        evidence_ids: ["e1"],
        conflicts: [],
        directions: { candidates: [], current: [], history: [] },
        timeline_chapters: [],
        thinking_line: { root: { fact_id: "g1", label: "Build Compass", status: "proposed", evidence_ids: ["e1"] }, branches: [], reversals: [], code_nodes: [] },
      },
      evidence: [{ id: "e1", kind: "user_message", author: "me", classification: "fact_source", content_preview: "Solo note", observed_at: "2026-11-15T01:00:00Z" }],
      candidate_relations: [],
      confirmed_relations: [],
      review_history: [],
      fact_reviews: [],
      session_presence: { team: { accepted_count: 0, pending_count: 2 }, members: [{ member_id: "me", label: "me", is_agent_session: true, pending_count: 2 }] },
      handoff_brief: { focus_goal: { value: "Build Compass", evidence_ids: ["e1"] }, accepted_decisions: [], pending_candidates: [], open_todos: [], code_nodes: [], markdown: "# Solo Brief" },
      intake: { enabled: false },
    };

    const h = buildTestHarness({ initialFetch: true, state: soloState, localStorage: localStorageMock });
    await h.flush();

    assert.equal(vm.runInContext("effectiveWorkMode()", h.context), "solo", "Single-member workspace did not default to solo mode");
    assert.equal(h.element("session-presence-bar").hidden, true, "Solo mode did not hide multi-member presence bar");
    assert.equal(h.element("member-picker").hidden, true, "Solo mode did not hide member picker");
    assert.equal(h.element("lens-personal-btn").textContent, "实时纪要 · 待确认想法");
    assert.equal(h.element("lens-team-btn").textContent, "已确认事项");

    // Solo mode allows committing directly from personal drawer without switching to team lens
    vm.runInContext('openFact("d1");', h.context);
    assert.ok(h.element("drawer-body").innerHTML.includes("✓ 确认"), "Solo personal drawer missing confirm button");

    // Reviewer signature input is persisted to localStorage and restored cleanly on reload
    h.element("reviewer-input").oninput({ target: { value: "Fang" } });
    assert.equal(store.get("compass_reviewer_name"), "Fang");

    // Switching to Team route restores presence bar and Team consensus copy
    vm.runInContext('setWorkMode("team");', h.context);
    assert.equal(vm.runInContext("effectiveWorkMode()", h.context), "team");
    assert.equal(store.get("compass_work_mode"), "team");
    assert.equal(h.element("session-presence-bar").hidden, false, "Team mode did not restore presence bar");
    assert.equal(h.element("lens-team-btn").textContent, "已确认事项");

    // Verify localStorage restores remembered signature on fresh boot when readOnly is false
    const hReload = buildTestHarness({ initialFetch: true, state: soloState, localStorage: localStorageMock });
    await hReload.flush();
    assert.equal(hReload.element("reviewer-input").value, "Fang", "Remembered reviewer signature was not restored from localStorage");
    assert.equal(vm.runInContext("effectiveWorkMode()", hReload.context), "team", "Remembered work mode was not restored from localStorage");
  }

  console.log("All 19 M3 interaction, honesty, overlay, scoping, Solo/Team mode, security and Node VM contracts passed.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
