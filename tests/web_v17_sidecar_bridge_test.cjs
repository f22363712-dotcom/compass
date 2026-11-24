const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const appPath = process.argv[2] || "src/project_compass/web/app.js";

function makeNode(id) {
  const cls = new Set();
  return {
    id,
    innerHTML: "",
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
        if (force === undefined) { if (cls.has(k)) cls.delete(k); else cls.add(k); }
        else if (force) cls.add(k); else cls.delete(k);
      },
      add(...ks) { ks.forEach((k) => cls.add(k)); },
      remove(...ks) { ks.forEach((k) => cls.delete(k)); },
      contains(k) { return cls.has(k); },
    },
    addEventListener() {},
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return this.attributes[k]; },
    removeAttribute(k) { delete this.attributes[k]; },
    getBoundingClientRect() { return { left: 100, top: 100, right: 200, bottom: 130, width: 100, height: 30 }; },
    focus() {},
    closest() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

function runBridgeScenario({ withSidecar }) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const node = makeNode(id);
      if (id === "reviewer-input") node.value = "fang";
      if (id === "evidence-drawer") {
        node.querySelectorAll = (sel) => {
          const bodyHtml = element("drawer-body").innerHTML || "";
          const out = [];
          if (sel === "[data-dispatch-fact]") {
            for (const m of bodyHtml.matchAll(/<button[^>]*\bdata-dispatch-fact="([^"]+)"[^>]*>/g)) {
              const b = makeNode(`d-${m[1]}`);
              b.dataset.dispatchFact = m[1];
              out.push(b);
            }
          } else if (sel === "[data-dispatch-fact-target]") {
            for (const m of bodyHtml.matchAll(/<button[^>]*\bdata-dispatch-fact-target="([^"]+)"[^>]*\bdata-fact-id="([^"]+)"[^>]*>/g)) {
              const b = makeNode(`t-${m[1]}-${m[2]}`);
              b.dataset.dispatchFactTarget = m[1];
              b.dataset.factId = m[2];
              out.push(b);
            }
          }
          return out;
        };
      }
      elements.set(id, node);
    }
    return elements.get(id);
  }

  const stateAlpha = {
    project: {
      name: "alpha",
      path: "/tmp/alpha",
      project_id: "proj-alpha",
      evidence_count: 1,
      fact_count: 1,
      conflict_count: 0,
      gap_count: 0,
      read_only: false,
    },
    intake: { enabled: false },
    sample_mode: false,
    projects: [],
    priority_dispatches: [],
    personal: {
      fang: {
        facts: [{
          id: "fact-1",
          short_title: "接入原生右侧看板",
          value: "在右侧辅助栏直接呈现完整主看板并打通三档派活。",
          clean_value: "在右侧辅助栏直接呈现完整主看板并打通三档派活。",
          status: "accepted",
          kind: "task",
          subject_key: "task:sidecar",
          evidence_ids: ["ev-1"],
          source_state: { current: true },
        }],
        evidence_ids: ["ev-1"],
      },
    },
    team: {
      facts: [{
        id: "fact-1",
        short_title: "接入原生右侧看板",
        value: "在右侧辅助栏直接呈现完整主看板并打通三档派活。",
        clean_value: "在右侧辅助栏直接呈现完整主看板并打通三档派活。",
        status: "accepted",
        kind: "task",
        subject_key: "task:sidecar",
        evidence_ids: ["ev-1"],
        source_state: { current: true },
      }],
      evidence_ids: ["ev-1"],
    },
    evidence: [{ id: "ev-1", kind: "user_message", text: "接入原生右侧看板", author: "fang", metadata: {} }],
    confirmed_relations: [],
    candidate_relations: [],
    review_history: [],
    fact_reviews: [],
  };

  const stateBeta = {
    ...stateAlpha,
    project: { ...stateAlpha.project, name: "beta", path: "/tmp/beta", project_id: "proj-beta" },
  };

  let activeState = stateAlpha;
  const fetchCalls = [];
  const sidecarEvents = { artifactComments: [], sentMessages: [], startedConvs: [], workspaceCallbacks: [], copied: [] };

  const sidecarObj = withSidecar ? {
    getWorkspaceUris: async () => ["/tmp/beta"],
    onWorkspaceChange: (cb) => { sidecarEvents.workspaceCallbacks.push(cb); return () => {}; },
    ui: {
      addArtifactComment: (payload) => { sidecarEvents.artifactComments.push(payload); },
    },
    agent: {
      sendMessage: async (msg) => { sidecarEvents.sentMessages.push(msg); return { ok: true }; },
      startConversation: async (msg, title) => { sidecarEvents.startedConvs.push({ msg, title }); return { ok: true }; },
    },
  } : undefined;

  const context = {
    console,
    URLSearchParams,
    Headers,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController: typeof AbortController !== "undefined" ? AbortController : undefined,
    fetch: async (url, opts = {}) => {
      fetchCalls.push({ url, method: opts.method || "GET", headers: opts.headers || {}, body: opts.body || "" });
      if (url === "/api/projects/activate") {
        activeState = stateBeta;
        return { ok: true, status: 200, json: async () => activeState };
      }
      if (url === "/api/dispatch") {
        return { ok: true, status: 200, json: async () => ({ ...activeState, priority_dispatches: [{ fact_id: "fact-1" }] }) };
      }
      return { ok: true, status: 200, json: async () => activeState };
    },
    document: {
      hidden: false,
      body: makeNode("body"),
      activeElement: null,
      getElementById: (id) => element(id),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      createElement: () => makeNode("dyn"),
    },
    navigator: {
      clipboard: { writeText: async (txt) => { sidecarEvents.copied.push(txt); } },
    },
    window: {
      innerWidth: 680,
      location: { search: withSidecar ? "?token=test-sidecar-tok-123" : "" },
      localStorage: { getItem: () => "", setItem() {} },
      addEventListener() {},
      ...(sidecarObj ? { sidecar: sidecarObj } : {}),
    },
  };
  context.globalThis = context;
  const vmCtx = vm.createContext(context);
  vm.runInContext(fs.readFileSync(appPath, "utf8"), vmCtx);
  return { vmCtx, context, element, fetchCalls, sidecarEvents };
}

(async () => {
  // 1. Inside Antigravity Sidecar iframe
  const sc = runBridgeScenario({ withSidecar: true });
  await new Promise((r) => setTimeout(r, 30));

  const activateCall = sc.fetchCalls.find((c) => c.url === "/api/projects/activate");
  assert.ok(activateCall, "Sidecar bridge should auto-activate workspace URI");
  assert.equal(JSON.parse(activateCall.body).project_path, "/tmp/beta");
  assert.equal(activateCall.headers["X-Sidecar-Token"] || activateCall.headers.get?.("X-Sidecar-Token"), "test-sidecar-tok-123");
  assert.equal(vm.runInContext("state.data.project.project_id", sc.vmCtx), "proj-beta");

  // Open fact drawer -> should render 3-tier sidecar buttons
  sc.context.openFact("fact-1");
  const drawerBody = sc.element("drawer-body").innerHTML;
  assert.ok(drawerBody.includes('data-dispatch-fact="fact-1"'));
  assert.ok(drawerBody.includes('data-dispatch-fact-target="send"'));
  assert.ok(drawerBody.includes('data-dispatch-fact-target="new"'));

  // Default dispatch -> addArtifactComment pill (does not disturb chat)
  await sc.context.dispatchFact("fact-1", { fromDrawer: true });
  assert.equal(sc.sidecarEvents.artifactComments.length, 1);
  assert.equal(sc.sidecarEvents.sentMessages.length, 0);

  // Send straight to current chat & new conversation window
  await sc.context.dispatchFact("fact-1", { fromDrawer: true, sidecarTarget: "send" });
  assert.equal(sc.sidecarEvents.sentMessages.length, 1);
  await sc.context.dispatchFact("fact-1", { fromDrawer: true, sidecarTarget: "new" });
  assert.equal(sc.sidecarEvents.startedConvs.length, 1);

  // 2. Standalone browser (Codex / Hermes / 8787) -> falls back to clipboard, no sidecar buttons in drawer
  const web = runBridgeScenario({ withSidecar: false });
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(web.fetchCalls.some((c) => c.url === "/api/projects/activate"), false);
  web.context.openFact("fact-1");
  assert.equal(web.element("drawer-body").innerHTML.includes("data-dispatch-fact-target"), false);
  await web.context.dispatchFact("fact-1", { fromDrawer: true });
  assert.equal(web.sidecarEvents.copied.length, 1);

  // 3. Mid-flight A -> B -> A revert race must settle back on alpha, not remain stuck on beta
  let releaseBeta;
  const raceElements = new Map();
  const raceNode = (id) => {
    if (!raceElements.has(id)) raceElements.set(id, makeNode(id));
    return raceElements.get(id);
  };
  const activatedOrder = [];
  const raceState = (projId, uri) => ({
    project: { name: projId, path: uri, project_id: projId, evidence_count: 1, fact_count: 1, conflict_count: 0, gap_count: 0, read_only: false },
    intake: { enabled: false },
    sample_mode: false,
    projects: [],
    priority_dispatches: [],
    personal: {
      fang: {
        facts: [{
          id: "fact-note",
          short_title: "保留署名备注",
          value: "首次定案填写署名时保留备注内容。",
          clean_value: "首次定案填写署名时保留备注内容。",
          status: "proposed",
          kind: "decision",
          subject_key: "decision:note",
          evidence_ids: ["ev-n"],
          source_state: { current: true },
        }],
        evidence_ids: ["ev-n"],
      },
    },
    team: {
      facts: [{
        id: "fact-note",
        short_title: "保留署名备注",
        value: "首次定案填写署名时保留备注内容。",
        clean_value: "首次定案填写署名时保留备注内容。",
        status: "proposed",
        kind: "decision",
        subject_key: "decision:note",
        evidence_ids: ["ev-n"],
        source_state: { current: true },
      }],
      evidence_ids: ["ev-n"],
    },
    evidence: [{ id: "ev-n", kind: "user_message", text: "note test", author: "fang", metadata: {} }],
    confirmed_relations: [],
    candidate_relations: [],
    review_history: [],
    fact_reviews: [],
  });
  let currentProjId = "proj-alpha";
  const raceFetchLog = [];
  const raceCtxObj = {
    console,
    URLSearchParams,
    Headers,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController: typeof AbortController !== "undefined" ? AbortController : undefined,
    fetch: async (url, opts = {}) => {
      raceFetchLog.push({ url, body: opts.body || "" });
      if (url === "/api/projects/activate") {
        const uri = JSON.parse(opts.body).project_path;
        activatedOrder.push(uri);
        if (uri === "/tmp/beta") {
          await new Promise((r) => { releaseBeta = r; });
          currentProjId = "proj-beta";
          return { ok: true, status: 200, json: async () => raceState("proj-beta", "/tmp/beta") };
        }
        currentProjId = "proj-alpha";
        return { ok: true, status: 200, json: async () => raceState("proj-alpha", "/tmp/alpha") };
      }
      return { ok: true, status: 200, json: async () => raceState(currentProjId, `/tmp/${currentProjId}`) };
    },
    document: {
      hidden: false,
      body: makeNode("body"),
      activeElement: null,
      getElementById: (id) => {
        const el = raceNode(id);
        if (id === "evidence-drawer") {
          el.querySelector = (sel) => {
            if (sel === "[data-solo-signer-input]") return raceNode("solo-signer-input-field");
            if (sel === "[data-solo-signer-error]") return raceNode("solo-signer-err");
            return null;
          };
          el.querySelectorAll = (sel) => {
            if (sel === "[data-solo-signer-submit]") {
              const btn = makeNode("solo-submit");
              raceElements.set("__soloSubmitBtn", btn);
              return [btn];
            }
            return [];
          };
        }
        return el;
      },
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      createElement: () => makeNode("dyn"),
    },
    navigator: { clipboard: { writeText: async () => {} } },
    window: {
      innerWidth: 680,
      location: { search: "" },
      localStorage: { getItem: () => "", setItem() {} },
      addEventListener() {},
      sidecar: {
        getWorkspaceUris: async () => ["/tmp/alpha"],
        onWorkspaceChange: () => () => {},
        agent: {
          sendMessage: async () => ({ ok: true }),
          // startConversation intentionally omitted to verify per-method UI gating
        },
      },
    },
  };
  raceCtxObj.globalThis = raceCtxObj;
  const raceVm = vm.createContext(raceCtxObj);
  vm.runInContext(fs.readFileSync(appPath, "utf8"), raceVm);
  await new Promise((r) => setTimeout(r, 25));

  const switchB = raceCtxObj.activateWorkspaceFromSidecarUris(["/tmp/beta"]);
  await new Promise((r) => setTimeout(r, 10));
  raceCtxObj.activateWorkspaceFromSidecarUris(["/tmp/alpha"]);
  releaseBeta();
  await switchB;
  await new Promise((r) => setTimeout(r, 25));
  assert.deepEqual(activatedOrder, ["/tmp/alpha", "/tmp/beta", "/tmp/alpha"]);
  assert.equal(vm.runInContext("state.activeWorkspaceUri", raceVm), "/tmp/alpha");
  assert.equal(vm.runInContext("state.data.project.project_id", raceVm), "proj-alpha");

  // 4. Per-method sidecar.agent gating: sendMessage present -> render "send", startConversation absent -> omit "new"
  raceNode("work-mode-select").value = "solo";
  raceCtxObj.openFact("fact-note");
  const partialBody = raceNode("drawer-body").innerHTML;
  assert.ok(partialBody.includes('data-dispatch-fact-target="send"'));
  assert.equal(partialBody.includes('data-dispatch-fact-target="new"'), false);

  // 5. Solo signer flow preserves #review-note text across inline prompt
  raceNode("reviewer-input").value = "";
  raceNode("review-note").value = "保留的关键验收备注";
  await raceCtxObj.acceptFact("fact-note", "accept_fact", { fromDrawer: true });
  assert.ok(vm.runInContext("state.pendingSignerAction", raceVm));
  assert.equal(vm.runInContext("state.pendingSignerAction.note", raceVm), "保留的关键验收备注");
  raceNode("solo-signer-input-field").value = "fang";
  const soloBtn = raceElements.get("__soloSubmitBtn");
  assert.ok(soloBtn && typeof soloBtn.onclick === "function");
  await soloBtn.onclick();
  const reviewPost = raceFetchLog.find((c) => c.url === "/api/review");
  assert.ok(reviewPost, "Solo signer submit should resume POST /api/review");
  assert.equal(JSON.parse(reviewPost.body).note, "保留的关键验收备注");

  // 6. Redundant same-project file:/// URI normalization skips duplicate /api/projects/activate
  const sameProjFetchCalls = [];
  const winAlphaPath = "C:\\Demo\\Workspace\\compass";
  const sameAlphaState = raceState("proj-win", winAlphaPath);
  const sameCtx = {
    console,
    URLSearchParams,
    Headers,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController: typeof AbortController !== "undefined" ? AbortController : undefined,
    fetch: async (url, opts = {}) => {
      sameProjFetchCalls.push({ url, body: opts.body || "" });
      return { ok: true, status: 200, json: async () => sameAlphaState };
    },
    document: {
      hidden: false,
      body: makeNode("body"),
      activeElement: null,
      getElementById: (id) => makeNode(id),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      createElement: () => makeNode("dyn"),
    },
    navigator: { clipboard: { writeText: async () => {} } },
    window: {
      innerWidth: 680,
      location: { search: "" },
      localStorage: { getItem: () => "", setItem() {} },
      addEventListener() {},
      sidecar: {
        getWorkspaceUris: async () => ["file:///c%3A/Demo/Workspace/compass/"],
        onWorkspaceChange: () => () => {},
      },
    },
  };
  sameCtx.globalThis = sameCtx;
  vm.runInContext(fs.readFileSync(appPath, "utf8"), vm.createContext(sameCtx));
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(
    sameProjFetchCalls.some((c) => c.url === "/api/projects/activate"),
    false,
    "Matching Windows file:// URI must not fire redundant /api/projects/activate",
  );

  // 6b. Returning from a read_only preview back to active workspace (or same loadedPath) MUST call /api/projects/activate
  const roSwitchCalls = [];
  const roState = raceState("proj-win", winAlphaPath);
  roState.project.read_only = true;
  roState.activeWorkspaceUri = "file:///c%3A/Demo/Workspace/compass/";
  const writableAlphaState = raceState("proj-win", winAlphaPath);
  const roCtx = {
    ...sameCtx,
    fetch: async (url, opts = {}) => {
      roSwitchCalls.push({ url, body: opts.body || "" });
      if (url === "/api/state") return { ok: true, status: 200, json: async () => roState };
      if (url === "/api/projects/activate") return { ok: true, status: 200, json: async () => writableAlphaState };
      return { ok: true, status: 200, json: async () => writableAlphaState };
    },
    window: {
      ...sameCtx.window,
      sidecar: {
        getWorkspaceUris: async () => ["file:///c%3A/Demo/Workspace/compass/"],
        onWorkspaceChange: () => () => {},
      },
    },
  };
  roCtx.globalThis = roCtx;
  const roVm = vm.createContext(roCtx);
  vm.runInContext(fs.readFileSync(appPath, "utf8"), roVm);
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(
    roSwitchCalls.some((c) => c.url === "/api/projects/activate"),
    "Returning from read_only preview must re-activate writable workspace",
  );
  assert.equal(vm.runInContext("state.data.project.read_only", roVm), false);

  // 6c. sample_mode disables quick notes and anchor edits while keeping review complete_fact enabled,
  //     and batchIgnoreFacts handles partial failure cleanly without deadlocking
  const batchPayloads = [];
  const baseBatchState = raceState("proj-batch", "/tmp/batch");
  baseBatchState.reviewer = "fang";
  baseBatchState.sample_mode = true;
  baseBatchState.next_consensus = { fact_id: "fact-next-demo", value: "Demo Next", status: "accepted", evidence_ids: ["ev-1"] };
  const batchElements = new Map();
  const batchCtx = {
    console,
    URLSearchParams,
    Headers,
    setTimeout,
    clearTimeout,
    setInterval: () => 0,
    clearInterval: () => {},
    AbortController: typeof AbortController !== "undefined" ? AbortController : undefined,
    fetch: async (url, opts = {}) => {
      if (url === "/api/review") {
        const body = JSON.parse(opts.body || "{}");
        batchPayloads.push(body);
        if (body.fact_id === "b2") {
          return { ok: false, status: 400, json: async () => ({ error: "fact already has this review status" }) };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ...baseBatchState,
            sample_mode: false,
            state_version: batchPayloads.length + 1,
            review_history: [{ action: "reject_fact", fact_id: "b1", reviewer: "fang" }],
          }),
        };
      }
      return { ok: true, status: 200, json: async () => baseBatchState };
    },
    document: {
      hidden: false,
      body: makeNode("body"),
      activeElement: null,
      getElementById: (id) => {
        if (!batchElements.has(id)) batchElements.set(id, makeNode(id));
        return batchElements.get(id);
      },
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      createElement: () => makeNode("dyn"),
    },
    navigator: { clipboard: { writeText: async () => {} } },
    window: {
      innerWidth: 680,
      location: { search: "" },
      localStorage: { getItem: () => "fang", setItem() {} },
      addEventListener() {},
    },
  };
  batchCtx.globalThis = batchCtx;
  const batchVm = vm.createContext(batchCtx);
  vm.runInContext(fs.readFileSync(appPath, "utf8"), batchVm);
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(batchElements.get("quick-note-submit").disabled, true);
  assert.equal(batchElements.get("goal-actions").innerHTML.includes('data-anchor-edit="goal"'), false);
  assert.equal(batchElements.get("next-consensus-actions").innerHTML.includes("complete_fact"), true);
  await batchVm.batchIgnoreFacts("b1,b2");
  assert.equal(batchPayloads.length, 2);
  assert.equal(vm.runInContext("state.batchIgnorePending", batchVm), false);
  assert.equal(vm.runInContext("state.data.review_history.length", batchVm), 1);

  // 7. Dark-mode preload.js isolation check in styles.css
  const cssPath = appPath.replace(/app\.js$/, "styles.css");
  const cssText = fs.readFileSync(cssPath, "utf8");
  assert.ok(cssText.includes("--c-paper:"), "styles.css must define isolated --c-paper token");
  assert.ok(cssText.includes("background-color: var(--c-paper) !important"), "body must force light paper background");
  assert.ok(cssText.includes("color: var(--c-ink) !important"), "body must force dark ink foreground");

  console.log("WEB_V17_SIDECAR_BRIDGE_PASS");
})();
