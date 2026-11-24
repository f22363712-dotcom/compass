# Decision Ledger

2026-11-20 Remediate P0–P2 defects surfaced by the Claude 8-dimension PBR read-only audit (`docs/COMPASS_V1_6_CLAUDE_REVIEW_2026-11-20.md`) while keeping L4 `contract_chains.json` and `dependencies = []` intact: (1) fix transcript session discovery via reverse 512 KB chunk scanning with directory boundary guards (`test_v16_intake_graph_advisor`), extract real `<conv-uuid>` session IDs via `infer_transcript_session_id` instead of `.system_generated`, attribute user turns and `ask_question` `GENERIC` choices (`pending_ask_question`) to the workspace human owner (`fang`, fallback `solo`) via `infer_primary_human_member`, and normalize single-owner evolution to eliminate `fang` vs `antigravity` fake conflicts; (2) bound noise in `decision_graph.py` (filter Markdown headings, interrogatives, quoted UI labels, deictic approvals, require `>= 2` alternatives for `open_fork`) and tighten `attach_decision_context` (`overlap >= 2`, `same_source`, or `adjacent (<= 2 steps) + overlap >= 1`; never attach premises onto `rejected_path`); (3) enforce evaluation honesty by labeling Track 2 as `synthetic_regression_fixture`, adding Track 4 (`v16_real_session_holdout.json`) on unmodified real-session slices, and preserving separate independent `easy-course-picker` L1–L5 baseline reporting (`L2 F1 = 0.0909` unchanged); (4) cut polling bandwidth/latency and token burn via off-lock `pre_discover()`, `?since_version=` compact delta responses (`1.3 KB / ~21 ms`, gated on `intake.refreshable` for standalone compatibility), bounded `max_initial_tool_events=240` cold backfill, indexed O(N) `_eligible_pairs`, capped dense `search_excerpt`, `AsyncHintCache` 60s project cooldown + `superseded_by_fact_id` filtering, plus Mindmap `.causal-chip` badges and simplified Chinese copy.

2026-11-20 Advance Compass v1.6 passive dual-channel intake, causal decision-premise-alternative graph, abstention-first strategist advisor, and empirical benchmark suite while strictly preserving `dependencies = []` (pure Python 3.10+ stdlib + zero-build Vanilla Web), L4 `contract_chains.json` caller boundaries, and append-only `proposed` vs owner-confirmed `accepted` governance: (1) benchmark and dissect six peer systems (`ClawMem`/`claude-mem`, `gastownhall/beads`, `mitos-adr`, `Membria`/IBIS+MADR, `divyanshailani/graph-memory`, `getzep/graphiti`) via live Gemini Ultra architectural deep dive and Exa web research—adopting byte/turn-cursor passive watching, authored-at chronology, archive/checkbox denoising, structured `settled` / `open_fork` / `rejected_path` / `premise` linkage, same-author sequential supersession normalization (eliminating single-author false conflicts without altering `fact_engine.py` L4 contracts), AST contract blast-radius nudges, and strict evidence-backed advisor abstention, while rejecting external databases, runtime JS/Go toolchains, destructive history overwrite, and hidden CoT exposure; (2) deliver pure-stdlib `decision_graph.py` + automatic throttled `TranscriptWatcher` sidecar/daemon wiring + archive-aware `doc_fact_intake.py` + upgraded local/LLM strategist hints and compact UI drawers; (3) add a reproducible 3-track v1.6 evaluation suite (passive-vs-manual intake A/B, 18-milestone golden blind test across `v1.5 baseline` vs `v1.6 local-only` vs `v1.6 hybrid LLM`, and isolated blind-critic scoring of advisor nudges). See `docs/COMPASS_V1_6_ARCHITECTURE_AND_DIFFERENTIATION_2026-11-20.md`.

2026-11-19 Advance Compass v1.5.0 four-tier cross-agent UI routing + Antigravity native Sidecar full dashboard hosting, graduated Agent dispatch, customizable team seat templates, and acoustic-foley launch video: (1) recognize connecting MCP hosts from `initialize.clientInfo`, `capabilities`, and desktop/SSH environment on `open_compass` calls only (silent on `initialize` and routine turns) and route to the optimal surface without duplicating slimmed-down views: Tier 1 Antigravity native Sidecar plugin (`compass/compass_board`, `SIDECAR_UI_ENTRYPOINT_AUX_PANE`, `sidecar://compass/compass_board/` pill) wrapping the full Compass Web dashboard with stdin-EOF teardown, loopback `X-Compass-Sidecar-Secret` + `X-Sidecar-Token` bridge, workspace-change `/api/projects/activate` sync, and 3-tier native dispatch (`addArtifactComment` pill by default, plus drawer `sendMessage` and `startConversation`); Tier 2 IDE hosts with built-in browsers (Codex desktop, Cursor, Windsurf, VS Code) launch/reuse an idle-bounded single-instance local web daemon and return its live URL; Tier 3 headless/CLI local desktop agents (Hermes local desktop, Claude Code) auto-open the system browser once per URL while SSH/CI/no-DISPLAY environments degrade cleanly to terminal URL + SSH port-forward instructions (`headless_terminal`); Tier 4 sandboxed MCP App hosts keep `ui://compass/workbench.html` + `compass_app_action` as fallback; (2) decouple strict two-tier confirmation authority (`owner` vs `member`, zero enterprise RBAC) from customizable role seats (`role_label`, `role_brief`, and 4 preset team templates: `solo`, `product_delivery`, `fullstack_engineering`, `research_lab`, plus `custom`) over authenticated HTTP team connections; (3) upgrade `compass_v14_x_launch_1080p60.mp4` audio using real recorded acoustic piano/guitar samples and physical paper/pen/keyboard/latch foley matched to the hand-drawn drafting workbench aesthetic. See `docs/archive/hackathon_and_brand/V1_5_NATIVE_PANE_AND_TEAM_ROLES_DESIGN_2026-11-19.md` and `docs/COMPASS_V1_5_MULTI_AGENT_AND_SIDECAR_BENCHMARK_2026-11-19.md`.

2026-11-16 Advance Compass v1.2 interactive conciseness, anti-drift MCP guardrails, and live auto-growth based on `/grill-me` alignment and external agent-memory benchmark study: (1) preserve zero extra-model dependency on the synchronous MCP/recording path by piggybacking concise `short_title` generation onto the host LLM paired with deterministic `text_summary.py` title dehydration, while keeping exact raw `value`/`quote` spans untouched in the ledger and drawer; (2) fix `build_compact_project_context` baseline honesty so unconfirmed `proposed` candidates never leak into `accepted_facts`, and separate 0->1 live session decisions from legacy repo docs by folding unaccepted static-doc candidates under a collapsible mindmap `historical_archive` capsule; (3) upgrade `activity_stream.py` with true `file_change`/`test_result`/`explore` human-language translation and cross-tool consecutive read-only exploration folding; (4) introduce 1-step `record_note`, deterministic `verify_completion` completion gate with optional timeout-bounded clean-context sidecar critic (`COMPASS_CRITIC_API_KEY`, fail-warn degradation, skipped in `SAMPLE_MODE=true`), and idempotent `--init-rules` (`AGENTS.md`) onboarding; (5) enable zero-config 3s live UI auto-growth without clobbering active inputs/drawers, add narrow companion split-screen layout (`560px-959px` horizontal mindmap + top stage ordering), slim UI copy, and replace raw surface `[id]` pills with clean `依据 · N` badges while keeping raw IDs in hover/drawer. See `docs/COMPASS_V1_2_UX_AND_MCP_PLAN_2026-11-16.md`.

2026-11-15 Advance Compass v1.1 Solo-first deep loop and cognitive UI clarity: (1) upgrade `#personal-activity` into a filtered, paired, tool-collapsed `activity_stream` while preserving legacy `personal_activity` compatibility; (2) add a desktop orthogonal horizontal mindmap canvas alongside `[清单台账 | 思维脑图]` dual-view toggle + Mermaid `mindmap` export under zero runtime dependencies and strict L4 `contract_chains.json` isolation (`derive_facts` / `build_views` / `validate_candidates` callers remain unchanged); (3) introduce `POST /api/notes` backed by deterministic exact-span append-only ledger records with same-host JSON CSRF guards and single-member Solo attribution; (4) resolve Solo reviewer friction via one-time inline drawer signature persistence instead of fabricating reviewer identity; (5) add inter-process file locking and read-merge persistence for `state.json` review state plus stat-signature reload so host `compass-mcp` writes reflect immediately on dashboard refresh; (6) localize user-visible status badges and `compass-*` download fallback filenames while migrating affected `web_m3_interactions_test.cjs` assertions to semantic CSS class + Chinese text checks and gating CI on all frontend `.cjs` contracts. See `docs/COMPASS_V1_1_PLAN_AND_REVIEW_2026-11-15.md`.

2026-11-15 Reframe product positioning around a **Solo-First → Team** real-time AI coding meeting assistant & low-cognitive-load control center (`Compass`): establish `Apache-2.0` licensing, clean open-source release under GitHub repository `f22363712-dotcom/compass` with zero-breakage `compass` / `compass-mcp` CLI entry points alongside backward-compatible `project_compass` package imports, add adaptive `solo` vs `team` workflow lenses on top of the shared append-only ledger (reducing single-user ceremony while keeping explicit user confirmation and multi-member consensus intact), and separate v1.0 deterministic control & provenance from vNext proactive model health insights (style drift, unverified-assumption alerts, and duplicate-logic warnings). See `docs/PRODUCT_GOAL.md`.

2026-11-14 Roll back corpus-overfit rules introduced in `f5b84ec` and fix evaluation measurement integrity: remove gold-phrased extraction markers (`"需要提供"`, `"需要核对"`, `"作为人工验收"`, `"端到端演练"`, `"手动提交"`), the `[A-Z]\d{2,3}|case-\d{3}` regex in `ReferenceExtractor`, and question-specific Chinese stopwords in `literal_relevance.py`. `ProductAnswerer` evaluates user-visible focused output (conclusion, findings, next action, and bounded evidence gaps) rather than dumping all 60 active tasks and 36 assumptions, and L3 retrieval scores use `investigate()`'s actual returned evidence ranking. `eval/report` records `git_sha` and `gold_sha256`, exposes `--extractor builtin|reference`, and labels 0-conflict corpora as vacuous passes. Honesty of the benchmark overrides inflated scores. See `docs/PROJECT_HEALTH_AUDIT_2026-11-14.md` and `docs/REMEDIATION_EXECUTION_PLAN_2026-11-14.md`.

2026-11-14 Archive accumulated point-in-time review ledgers (`*_2026-*.md`), superseded hackathon/brand exploration files, and legacy root clutter (`HACKATHON_BRIEF.md`, `SUBMISSION_CHECKLIST.md`, `PLAN.md`, retired `requirements-zetaris.txt`) under `docs/archive/`, indexed via `docs/INDEX.md`, while strictly keeping `docs/PRODUCT_SPEC.md`, `docs/ROADMAP.md`, canonical contracts, and the protected untracked `docs/ZETARIS_DEMO_CHALLENGE_55S.md` untouched.

2026-11-14 Unify the entire dashboard UI on Swiss Bauhaus / Neo-Brutalism with complete `:root` CSS tokens (spacing, radius, type scale >= 12px, WCAG AA contrast >= 4.5:1), remove all legacy dark-green `#0d6e52` and soft blurred shadows, replace hardcoded `"100% 绿灯"` badge text with evidence-linked or gap-explicit verification badges, and express cognitive states (`accepted`, `proposed`, `conflicted`, `needs_evidence`, `superseded`) through one shared renderer and side-by-side split conflict comparison.

2026-11-14 Use controlled A/B experiments orchestrated via `run_workflow` with independent blind multi-agent review for uncertain engineering/UX trade-offs: (1) pure-stdlib SQLite FTS5 trigram BM25 vs clean 2-gram IDF literal retrieval, and (2) Swiss Neo-Brutalism first-screen triage hierarchy & layout variants verified on live browser screenshots. Decisions and experiment ledgers are preserved in `docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md` and `docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md`.

2026-11-10 the evaluation benchmark is a first-class product asset with five
layers, not a test folder. L1 structure, L4 contract and L5 adversarial never
call a model and gate CI; L2 extraction and L3 handoff run on both a
deterministic track and a model track over one gold set and one scorer. Gold is
authored independently of Compass output and anchored to real source text, so
the build fails loudly when an anchor drifts. Hard metrics protect product red
lines; soft metrics rank iteration work. Baseline (2026-11-10): red lines all
green, extraction F1 0.068, retrieval hit rate 0.214, answer accuracy 0.500 —
the product is honest but not yet queryable. See docs/EVAL_FRAMEWORK.md,
docs/EVAL_REPORT.md and docs/COMPASS_ITERATION_PLAN.md.

2026-11-10 ProjectCompass produces its own code-structure graph through
`project_compass.code_index` using the standard-library `ast` module only: no
Rust kernel, no tree-sitter, no SQLite, no file watcher, no new dependency. The
`understand-anything` payload shape stays the seam so an externally produced
graph can still be read. The graph is conservative — an ambiguous call target
creates no edge — because a wrong edge is worse than a missing one for contract
risk. Files that cannot be parsed are reported, never skipped silently.

2026-11-10 Code Graph (colbymchenry/codegraph, MIT) is borrowed as product
judgment, not as a runtime dependency: one strong tool over a menu of
overlapping tools, surgical one-call context, explicit index staleness, and
affected-test lookup are adopted; the Rust/ SQLite / file-watcher stack is not,
because it collides with the local-first zero-database and zero-dependency
rules. See docs/CODEGRAPH_BORROWING.md.

2026-11-03 external comparison with Egonex-AI/Understand-Anything keeps the
ProjectCompass core centered on Agent collaboration facts, evidence, owner
confirmation and conflict history. Code-structure graphs may be consumed later
as read-only `derived_context`; they cannot create accepted Team truth. Borrow
plugin distribution, incremental analysis, guided tours and a read-only viewer;
do not copy the multi-agent graph pipeline or treat graph size as evidence
quality. See `docs/EXTERNAL_PROJECT_UNDERSTAND_ANYTHING_REVIEW_2026-11-03.md`.

2026-10-26 explicit standalone human first/priority tasks receive a conservative
whole-message rule fallback when optional semantic extraction omits them. Exact
quotes stay proposed, full scope restrictions and source time remain attached.
Separate user-task-rules progress cannot advance model coverage or reset budgets.
Main rollout preserves1038 existing records/2 reviews and appends1 proposed task;
model omission/semantic and causal completeness remain open. Review/correction
and actual sources are recorded in docs/EXPLICIT_USER_TASKS.md.

2026-10-26 direction rule scheduling uses oldest-pending bounded windows and
content-keyed durable progress instead of repeatedly inspecting only the latest
fixed prefix. Direction progress is stored separately from model semantic
coverage. Exact proposals persist before progress is acknowledged; completion
never promotes team truth. This repairs the approved large-context requirement,
with no new model calls. See docs/DIRECTION_SCAN_PROGRESS.md and the direction
scan progress plan. Three newly recovered assistant deferrals remain proposed
after verified main rollout; all previous evidence records and owner reviews
remain preserved. See docs/REAL_INPUT_ACCEPTANCE_AUDIT.md for current state.

2026-10-25 native tool trace is an explicit --codex-tools option for the already
selected project/thread. Capture only bounded complete text call/result pairs,
linked by original call ID, with conservative sensitive/non-text filtering and
an initial latest200-pair backfill window. Keep exact sources and owner history.
Do not promote a task from a printed success/exit code or claim complete execution
history. The adapter targets the observed local format and exposes filter gaps.

2026-10-25 personal evidence correction includes a member's captured public records
before semantic extraction and preserves explicit source ownership. Extraction
identity is only a fallback for legacy sources without member metadata. The UI
defaults to a connected member, preserves manual selection, and scopes the spine
to owned/direct/confirmed support sources. Team investigation and the complete
project catalog remain shared. This is the approved view boundary, not an ACL change.

Legacy source ownership may additionally use an explicitly selected and
project-validated Codex thread binding before extractor fallback. This fills
missing view identity without rewriting immutable records or cursor fingerprints;
an already explicit source member still wins. Existing persisted proposal
attribution remains unchanged on replay.

2026-10-25 live extraction reuses the existing GPT6.1 Sol Medium provider in a
single background job, with explicit web activation and optional automatic ticks.
Default per-start budget admits at most2 batches, stopping at80000 known tokens
after usage is reported; a request may cross that threshold. Unknown usage stops
further admissions. Polling itself is model-free. Owner history remains canonical,
proposals stay proposed, and source cursors advance only after durable persistence.
Legacy progress was recovered only after a full reconstructed prompt hash matched
the old response cache, not inferred from its positive candidate count.

2026-10-25 source-currentness correction keeps historical owner acceptance while
marking replaced or unavailable file evidence as needing review. Current focus,
active tasks and recommendations cannot rely on such a source. Complete scans
may append unavailability observations; ordinary evidence/proposal saves may not.
The manual web rescan is model-free and read-only for the scanned repository.
Source identity restoration means the original document bytes are current again;
it does not establish runtime verification or semantic truth. See the
source-currentness plan and PRODUCT_SPEC.md evidence rules.

2026-10-25 Zetaris uses the official local JDBC driver in a bounded process to
retrieve immutable cited material from project-record and public-message REST
families. Meterless supplies facts/support links; canonical owner reviews remain
authoritative. Returned source identities, exact payloads and digests must all
match before investigation proceeds. Enabled failure returns503 and concurrent
state changes return409. This replaces neither extraction nor semantic review.
Per-revision tables avoid per-evidence metadata; unchanged snapshots reuse their
registered sources. Old metadata remains pending future lifecycle work. Discovery
after a competing CREATE accepts only an already committed matching definition.
Evidence is in `docs/ZETARIS_LOCAL_SETUP.md` and the Zetaris plan/test ledger.

2026-10-25 incremental extraction records project-scoped inspected ranges only
after proposal persistence. Shared root-level progress was rejected because
identical normalized records in two projects could skip one project's material.
Exact old response caches remain reusable after current-window validation.
Activation stays explicit; no autonomous model loop is introduced in this slice.
Recovery reuses an identical persisted proposal and its existing attribution;
changing the extracting process's member ID cannot reassign that record.

2026-10-25 startup correction uses `SAMPLE_MODE=true` as a source default only;
an explicit real-project source always takes precedence. The web fixture runs in
an isolated sample workspace and labels synthetic data. Fixture input rejects
model, sponsor and native-capture flags. This preserves existing real-project
commands while making the previously required no-credential trial usable.

2026-10-25 sponsor continuation adopts the official Meterless World Model local
reference as an explicit, rebuildable investigation memory projection. Existing
evidence and owner reviews remain authoritative. Automatic Meterless fact winner
selection is excluded. The alternative cloud API path is unnecessary for this
reference. Pin and tests are recorded in
`docs/superpowers/plans/2026-10-25-meterless-world-model.md`.

| Date | Decision | Consequence | Evidence / rationale | Status |
| --- | --- | --- | --- | --- |
| 2026-10-22 | Target 2–4 developers on one project using coding agents | Keeps collaboration model concrete and testable | Confirmed in product-design discussion | Accepted |
| 2026-10-22 | Use personal boards plus a shared project board | Separates session context from accepted team truth | Confirmed in product-design discussion | Accepted |
| 2026-10-22 | Raw evidence is append-only; semantic claims require promotion | Protects traceability and prevents silent overwrite | Confirmed in product-design discussion | Accepted |
| 2026-10-22 | Preserve conflicting claims until owner resolution | Makes disagreement visible and auditable | Confirmed in product-design discussion | Accepted |
| 2026-10-22 | Model collaboration on a minimal GitHub-like review flow | Reuses familiar review, conflict and protected-branch semantics | GitHub official review and protected-branch documentation | Accepted |
| 2026-10-22 | Show public execution traces, not hidden chain-of-thought | Keeps evidence demonstrable and avoids misrepresentation | Product integrity and event-model requirements | Accepted |
| 2026-10-22 | Build the final version through one golden path | Prevents disconnected prototypes and late architecture failure | Hackathon time-box and 25/50/80 gates | Accepted |
| 2026-10-23 | Implement the first golden path with a deterministic local engine and JSON state | Makes the evidence chain runnable without model credits or private sponsor credentials | Confirmed implementation design; `docs/superpowers/plans/2026-10-23-golden-path.md` | Accepted |
| 2026-10-24 | Use Jev as an optional evidence-link suggestion layer with a deterministic fallback | Keeps the core path runnable without external credentials while allowing bounded semantic association proposals | User confirmed; TypeSafe Jev returns typed decisions and probabilities, while ProjectCompass keeps owner confirmation authoritative | Accepted |
| 2026-10-24 | Separate evidence inventory, candidate relations and confirmed relations | Prevents raw scanned materials from being presented as already-proven support for a fact | Current scan output has six inventory IDs but fact citations only point to `codex-e1`; `docs/superpowers/specs/2026-10-24-evidence-linking-design.md` | Accepted |
| 2026-10-24 | Use a web dashboard as the competition surface with a local ProjectCompass launcher | Keeps the demo shareable and readable while allowing arbitrary local projects to be scanned without writing into them | User confirmed final boundary; `devpost/spec.md` layered views and local run contract | Accepted |
| 2026-10-24 | Persist scanned project state under ProjectCompass `.project-memory`, keyed by canonical project path | Allows a project to be reopened without rescanning and keeps the scanned project read-only | User confirmed arbitrary project start, scan, persistence and reopen; `docs/superpowers/plans/2026-10-24-project-workspace.md` | Accepted |
| 2026-10-24 | Load optional API credentials from ProjectCompass root `.env`, with process variables taking precedence | Supports local Jev testing without placing secrets in the scanned project or Git; `--env-file` can select another local file | `src/project_compass/env_loader.py`; `tests/test_env_loader.py`; `.gitignore` | Accepted |
| 2026-10-24 | Treat the Lucid conversation as scan context for `D:\Lucid-Attention-Agent`, not as imported transcript evidence | Keeps the scan truthful until a public JSONL export is provided; the current scan contains project files and Git evidence only | `D:\Lucid-Attention-Agent`; local dashboard scan on port 8788; 54 evidence items, 0 derived facts | Accepted |
| 2026-10-24 | Keep deterministic evidence linking as the default; call JEV only through explicit `--jev` | The current repository `.env` value returns 401, historical successful calls total 4,857 known tokens, and the adapter only re-scores deterministic pairs rather than proving new recall | JEV evaluation sub-agent report; `logs/model-usage.jsonl`; deterministic fallback remains complete | Accepted |
| 2026-10-24 | Project the owner's accepted fact into Team truth while retaining every conflicting side and review history | Team truth shows one current `accepted` side plus historical `conflicted` sides; Personal view remains unchanged | `docs/superpowers/specs/2026-10-24-team-truth-projection-design.md`; browser verification on port 8790 | Accepted |
| 2026-10-24 | Use deterministic evidence linking as the simulated JEV-like judgment in the first board | It reduces token use and keeps evidence decisions explainable; real JEV stays behind explicit `--jev` for experiments | `docs/superpowers/specs/2026-10-24-investigation-ui-design.md`; JEV evaluation report | Accepted |
| 2026-10-24 | Put investigation Q&A inside Team truth and link every answer evidence ID to the original drawer | The demo path answers current state and next action without making the user search the evidence spine manually | `/api/investigate`; browser verification on port 8790 | Accepted |
| 2026-10-25 | Treat the Lucid public-message capture as a failed real-data baseline, not a successful end-to-end demo | Do not inject hand-authored facts or promote reports to conceal missing semantic extraction | Ignored local real-input REPORT.md; 249 public messages, 303 total evidence, 0 facts | Verified failure retained |
| 2026-10-25 | Return explicit evidence gaps when facts are missing; preserve raw evidence across rescans and content-address file revisions | No unsupported claim of accepted Team truth; changes retain distinct evidence identities | tests/test_real_input_safety.py and tests/test_project_workspace.py; Lucid rerun has 341 records, 0 facts and explicit gaps | Safety rerun verified; semantic acceptance failed |
| 2026-10-25 | Keep the web/local product shape while treating Zetaris and Meterless as final-submission requirements | Old command-line POC notes do not waive sponsor integration or real-input acceptance | Official rules 5.1 and 6, checked 2026-10-25; docs/COMPETITION_ALIGNMENT.md | Requirements verified, integrations incomplete |
| 2026-10-25 | Add an explicit bounded Codex candidate extractor within the approved real-intake requirement | Exact quotes are validated against raw sources; ordinary scans remain offline, all semantic output stays proposed | docs/superpowers/plans/2026-10-25-real-candidate-extraction.md; 16 real candidates from 60 selected prefixes, 0 owner acceptances | Bounded candidate batch verified, full acceptance incomplete |
| 2026-10-25 | Separate proposal identity from shared semantic subject, prefer recent pending evidence, and append file re-observation on content rollback | Conflicting reports stay visible, old content snapshots remain immutable, extraction follows current observed file content | Independent review; tests/test_candidate_extraction.py and tests/test_project_workspace.py RED then GREEN | Review findings fixed |
| 2026-10-25 | Capture only an explicitly selected, project-bound native Codex conversation and refresh it through the local board | Removes transcript export for public messages, retains original evidence/reviews, skips hidden/sensitive/control records; refresh never starts a model request | docs/superpowers/plans/2026-10-25-native-codex-intake.md; corrected Lucid248 messages,341 visible sources,2 accepted facts retained | Native public-message path verified; automatic semantic extraction and tool payloads incomplete |

2026-10-25 tool-trace verification keeps the direct-reference syntax subset rather
than executing JavaScript to discover tool names. A fresh review reproduced alias
bypass and silent saved-ID rewrite. Both now fail safely before persistence;
observed saved identities are compared before privacy/window filtering. Exact
public tool pairs remain raw provenance, not automatically promoted test facts.
Actual report-read navigation and JDBC retrieval passed; typed native command
events and other developer conversations remain explicit coverage gaps. See
`docs/NATIVE_TOOL_TRACE.md` and the170-test root verification.

2026-10-25 native command event correction extends the existing --codex-tools
option to observed typed CommandExecution completions. Store exact output plus
public command/cwd/status/exit/duration metadata in a separate bounded200-record
window. Typed identities stay separate from wrapper pair identities; no shared
identity exists to justify collapsing them. Exit status describes the recorded
command, never task completion or current-package test acceptance. Existing owner
facts and private/excluded native fields remain untouched. Plan is
`docs/superpowers/plans/2026-10-25-native-command-events.md`.

2026-10-25 normalized Agent intake uses optional project-bound HTTP clients in the
existing loopback server. Their reports and exact-source proposals stay unaccepted.
Owner review is a separate browser capability when the API is enabled, with fixed
configured owner attribution. Tokens remain private local config and are never
returned or logged. Same-OS code with full user privileges is not a security
isolation boundary. Native human messages remain distinct from Agent submissions.
Plan: `docs/superpowers/plans/2026-10-25-agent-http-inbox.md`.

Agent HTTP final correction stores only token_env references in persistent client
configuration, following the repository environment-credential rule. The runtime
loads credentials from process variables/root.env; inline persisted token values
are rejected. Same sensitive-switch detection now covers HTTP and native shell
strings. Agent-origin test/tool/file claims remain assistant reports, never project
documents. The current raw records and two owner acceptances are unchanged.

2026-10-26 startup verification uses at most3 GET-only transport attempts with
8s abort deadlines and250/750ms backoff. HTTP/JSON/schema failures remain explicit;
write/model/review requests are never retried by initial-state recovery. The
original browser fault cause remains unproven; a separate synthetic delayed-read
probe confirms actual browser recovery without real project mutation.

Independent client acceptance uses new source/venv/pinned sponsor clients and an
explicit private backup, while reusing the authorized Zetaris backend and host
Python/Java. Existing Docker resources are preserved. Full backend provisioning
and public-content/history audit remain separate pending checks. Evidence is in
`docs/CLEAN_START_ACCEPTANCE.md`; no new owner acceptance or model call occurred.

2026-10-26 member questions use deterministic full-known-identity lookup and the
existing source/member binding before any extra model. Unknown/ambiguous identity
requests ask for a name. Raw-only public excerpts are labeled raw, with source
times and original links. Member-only findings retain other members' same-subject
owner-confirmed conflicts as context; an opposing accepted state blocks obsolete
recommendations. No source write, new acceptance or model call occurs. This does
not establish full semantic recall. See `docs/MEMBER_INVESTIGATION.md`.

2026-10-26 protocol correction excludes exactly one recognized whole control
envelope from message speech/model input, with record-kind boundaries preserving
document/command quotations. Raw history and owner facts remain unchanged; legacy
control-backed claims require source review and cannot supply current work.
The real pending queue loses27884chars of control input, without a measured token
saving or new semantic coverage. See `docs/CONTROL_MESSAGE_PROVENANCE.md`.

2026-10-26 sponsor scope follows the existing required evidence-ID set rather
than shipping all project material to every query. Memory/full project state,
immutable leases, revision409 and exact payload verification remain authoritative.
Input bytes dropped3667574->96295 for the checked same15 citations. Avoid new
result cache/JVM lifecycle now; cold connection variance remains measured risk.
See `docs/JDBC_PERFORMANCE.md` for timings and limits, not a latency guarantee.

2026-10-26 user confirmed the abandoned-direction boundary: only explicit
abandonment or deferral statements enter the owner-reviewed shared list; unused
undiscussed Agent proposals stay personal candidates. Restoration retains history.
The implementation uses existing decision quotes and review events rather than
inferring abandonment from silence. Legacy acceptances do not acquire a direction
state retroactively. Design docs/superpowers/specs/2026-10-26-direction-history-design.md.


2026-10-26 cached-reason preview remains a source-bound, read-only proposal surface.
It uses the already-authorized single extraction snapshot; no new model request,
canonical fact or owner review is admitted. General generation and owner reason
acceptance remain open. Quote validity does not establish causal truth. Local
binding, changed-source quarantine and matching-member why scope are mandatory.
See docs/superpowers/plans/2026-10-26-reason-preview.md.

2026-10-26 Git scope correction preserves root merge/empty checkpoint history,
while subdirectory intake only reads commits touching that directory before the
history bound. Historical evidence is not deleted. Public packaging uses a private
source-only candidate without old Git history; current working repository remains
uncleared for public push. Candidate45a4b54 and all gates are recorded in
docs/PORTABLE_SOURCE_CANDIDATE.md. No publication or first-party license chosen.

2026-10-26 first-load performance correction uses per-read preparation rather than
persistent cached state or relaxed request deadlines. The real complete projection
is byte-equal, existing relations/owner status unchanged. Measured main reads are
595/706/658ms versus10414/11862/12587ms. No semantic coverage claim or stable SLA.
Current private source candidate681bf15 supersedes45a4b54; public approval pending.
See docs/DASHBOARD_READ_PERFORMANCE.md.

2026-10-26 user explicitly chose automatic batched backfill of eligible older
records rather than fetching them only after a historical question. The user
requested research on memory growth and progressive disclosure versus retrieval.
This confirms the intake preference, not a new semantic architecture or model
budget. Research and a proposed design are in docs/MEMORY_ARCHITECTURE_RESEARCH.md.
No backfill, capture-cap change or runtime rollout was performed in this research.

2026-10-27 user approved the layered memory plan for the competition release.
The first implementation keeps raw history append-only, backfills eligible native
tool and command records in 50-item batches, persists `native-backfill.json`, and
shows overview/process/source reading layers. No new semantic model is enabled.
Focused and full regression checks passed: 355 tests. Canonical Lucid state and
model-usage hashes are unchanged. The official event page lists the hard
submission deadline as 2026-10-27 23:45 UTC (2026-10-28 07:45 Asia/Shanghai).

2026-11-04 user approved retiring legacy competition sponsor modules (`zetaris_provider`,
`zetaris_worker`, `meterless_memory`, `jev_provider`) that have no irreplaceable value
for the local-first product, keeping ProjectCompass 1.0 pure Python + local ledger +
zero-build Web UI. User also approved absorbing core UX patterns from AI meeting-note
assistants (Qwen/Tongyi Tingwu chapter timeline & thinking line, Granola hover citation
popovers) and GitHub/Linear project collaboration (Session Presence pills, in-card quick
triage to promote candidates to Team truth, and 1-Minute Handoff Brief). Raw evidence
remains append-only and candidate facts still require explicit review before entering
Team truth. See `docs/PRODUCT_1_0_BENCHMARK_AND_DESIGN_BLUEPRINT_2026-11-04.md`.

2026-11-14 M2 remediation converged shared limits (`limits.py`), public/control filters,
member attribution, ISO-8601 `'Z'` parsing, and thread-safe atomic writes (`evidence_filters.py`),
and shared bilingual intent keywords (`intent_vocab.py`); fixed `investigator.py` duplicate
`derive_facts` calls and quadratic conflict grouping; and adopted Candidate Beta (stdlib
SQLite `:memory:` FTS5 trigram BM25 with smooth log-IDF and automatic pure-Python
OperationalError/NUL fallback) after a controlled A/B experiment and two-critic blind review
(`easy-course-picker` L3 `retrieval_hit_rate` `0.2857 -> 0.3571`, `retrieval_mrr`
`0.2321 -> 0.2560`, zero unit regressions; `answer_accuracy` unchanged at `0.2857`).
See `docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md`.

2026-11-14 M3 UI overhaul adopted Swiss Bauhaus / Neo-Brutalism via controlled
A/B implementation (`Design Alpha` command ledger vs `Design Beta` asymmetric
`5fr/7fr` editorial grid) under identical `--paper`/`--navy`/`--orange` WCAG AA
tokens and a unified `app.js` boundary (`apiFetch`, `STATUS_BADGE_MAP`,
`renderStatusBadge`, honest zero-count styling, Split A-vs-B conflict panes,
`Esc`/focus restoration, viewport-clamped citation popover). Three independent
blind `research` Critics selected `Design Beta` 3:0 (`5.0 vs 7.4`, `4.8 vs 7.3`,
`4.8 vs 7.0`). Final synthesis eliminated orphan 5-KPI cells (`repeat(5, 1fr)` /
`2+2+1`), de-boxed secondary sections via `.ledger-band`, promoted Workbench &
Team Truth Matrix to the top fold, fixed a `html { font-size: 16px }` root rem
bug (`0.75rem === 12px` everywhere) caught in Round 1 (`9.1/8.9/9.1`), and passed
Round 2 unanimous blind review at `9.3 / 9.3 / 9.3` (mean `9.30/10`) with zero
third-party dependencies. See `docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md` and
`docs/UI_STYLE_GUIDE_MANUAL.md`.

### 2026-11-15: Deterministic self-dogfooding intake (`--extract-docs`) & repo code-index binding (`--with-code-index`)

- **Context**: Running `scan_project` alone on a local repository without an LLM API key only yielded raw `file_snapshot` / `git_commit` evidence (`fact_count == 0`), and `build_code_index` defaulted `project_id` to the folder basename instead of `ProjectWorkspace`'s SHA-1 `project_id`, preventing seamless real-project self-dogfooding.
- **Decision**:
  - Added deterministic, model-free `doc_fact_intake.py` (`RULE = "doc-structure-v1"`) behind opt-in CLI flag `--extract-docs`, extracting exact source-span `goal`, `decision`, and `task` candidates from markdown documents (`README.md`, `PRODUCT_GOAL.md`, `PRODUCT_SPEC.md`, `DECISIONS.md`, `HANDOFF.md`, etc.) with crash-safe cursor tracking.
  - Added optional `--project-id` parameter to `code_index.py` and opt-in `--with-code-index` flag to `cli.py` so `--web` and `--export-format` bind `DerivedContext` directly to the active workspace's `project_id`.
  - Kept `--sample` strictly isolated and model-free (explicitly rejecting `--extract-docs` and `--with-code-index`).
  - Documented the full O1–O4 open-source checklist, live dogfooding run, and 16-item UI/export placeholder ledger in `docs/OPEN_SOURCE_AND_DOGFOODING_PLAN_2026-11-15.md` before committing UI/repo cleanup changes.

### 2026-11-15: Open-source release license (Apache-2.0), clean single-commit export & O1–O3 remediation

- **Context**: Preparing Project Compass for public GitHub / PyPI / MCP Registry hosting required choosing an authoritative first-party license, eliminating machine-local privacy paths and legacy competition scaffolding from the public tree, enabling zero-config local MCP startup, fixing directory freshness/ordering in `DerivedContext`, and clearing 16 UI/export template placeholders.
- **Decision**:
  - **License (`O1`)**: Adopt **Apache-2.0** (matching `server.json`) via root `LICENSE`, complete `pyproject.toml` `[build-system]` and `web/*` package data, unify `__version__ = "1.0.0"` across package & MCP `serverInfo`, and expose all 4 tools in `server.json`.
  - **Clean Public Export (`O2`)**: Scrub local username/host paths in active docs, archive legacy competition scripts and `devpost/` under `docs/archive/competition_legacy/`, preserve `codex/evidence-links` history locally without destructive rewrites or pushes, and ship a non-destructive `scripts/export_public_release.py` emitter producing a clean single-commit `main` repository under ignored `.release-export/` guarded by automated leak regex checks.
  - **Zero-Config UX & Placeholder Cleanup (`O3`)**: Add `WorkspaceMCPAdapter` in `local_plugin.py`/`mcp_server.py` so `uvx project-compass-mcp --project-path .` runs directly against `ProjectWorkspace` when `--base-url` is omitted (while still enforcing bearer tokens whenever `--base-url` is provided); support directory hashing in `DerivedContext.source_current` and prioritize evidence-linked/`src/` AST nodes before dashboard truncation; clear all 16 placeholders across `cognitive_export.py`, `dashboard.py`, `sample_data.py`, `transcript_watcher.py`, `web/index.html`, and `web/app.js`; refresh `docs/images/*` screenshots and bilingual READMEs.

### 2026-11-16: v1.3 Governance Unification, Unified Open LLM Connector & Concise `Agent 提示`

- **Context**: Live usage surfaced four UX friction points (divergent doc-goal selection & lack of inline goal/next-step confirmation, legacy `*PLAN*.md` checkboxes polluting `next_action` and `handoff_brief.open_todos`, keyword queries without question words being rejected by `investigator.py`, and compound Chinese questions mis-triggering `member_choice`), while validating whether plugging an optional external model improves benchmark semantic scores without sacrificing deterministic zero-dependency defaults or L4 blast-radius contracts.
- **Decision**:
  - **Unified Zero-Dependency Model Connector (`llm_connector.py`)**: Support both user-configured OpenAI-compatible cloud APIs (MiniMax `MiniMax-M2.7`, DeepSeek, OpenAI via env vars or `COMPASS_LLM_KEY_FILE`) and keyless local endpoints (`Ollama` on loopback) using pure stdlib `urllib.request`, automatically stripping model `<think>...</think>` drafts, never exposing secrets in public state, and failing closed in `SAMPLE_MODE=true`. Reject training custom weights or hosting a central proxy API in the open-source core.
  - **Governance & Dual Anchor Alignment**: Separate static `project-documents` / `*PLAN*.md` checkboxes from active live consensus (`select_primary_goal` + `select_next_consensus`), support inline 1-sentence goal & `topic="next_step"` quick-notes with frictionless Solo owner acceptance, unify 1-box keyword search + Q&A (promoting full-text raw excerpts into `findings` and fixing compound-clause member scoping), and expand `#evidence-filter` search excerpts up to 2,000 chars.
  - **Understated `Agent 提示` (`agent_hints.py`)**: Provide instant deterministic local hints paired with bounded async cached LLM hints (`AsyncHintCache`) and concise investigation synthesis (`semantic_summary`), synced into MCP `nudge_lines` and verified against the 5-layer evaluation benchmark (`deterministic v1.3` vs `MiniMax-M2.7` `--harness api`).

### 2026-11-16: v1.4 Multi-Model Benchmark Seal, Pyramid Answer UI & Runtime Engine Switcher

- **Context**: Testing user-provided `MiniMax-M3.1-Flash` and `DeepSeek-Chat` alongside existing baselines surfaced both UX and protocol insights: (1) unaccepted legacy doc `source_warnings` prepended above investigation conclusions buried the settled goal and next step; (2) `MiniMax-M3.1-Flash` defaults to heavy adaptive thinking tokens that exhausted bounded UI/eval budgets until tuned with `reasoning_effort="low"`; and (3) users need a clear v1.x freeze boundary rather than chasing static keyword benchmark numbers indefinitely.
- **Decision**:
  - **v1.x Feature Seal**: Freeze the core local-first ledger, governance, mindmap, and pluggable connector after completing v1.4 UX and multi-model benchmarking; shift next phase to real new-project dogfooding and split-screen live growth validation.
  - **Inverted-Pyramid Answer Card (`web/app.js`, `investigator.py`)**: Render `semantic_summary` (or conclusion) plus highlighted `当前目标` and `已确认下一步` takeaways first, move compact core findings below, collapse `source_warnings` and boundary notes at the bottom by default, and keep `project.goal` + settled `project.next_step` surfaced on compound queries even when unrelated subjects carry open conflicts.
  - **Multi-Credential Profiles & Runtime Switching (`llm_connector.py`, `web_server.py`)**: Support multi-line `key:value` and bare-key files via `COMPASS_LLM_KEY_FILES`, pass `reasoning_effort="low"` only on `m3.1-flash` models while lifting token caps safely, and expose memory-only runtime switching (`POST /api/llm-mode`) across `MiniMax-M3.1-Flash`, `MiniMax-M2.7`, `DeepSeek-Chat`, and offline `local` retrieval without storing secrets or URLs in public state. Select `MiniMax-M3.1-Flash` (`low` effort) as the default interactive dashboard profile based on `1.0000` evidence validity (`0` fabricated IDs), top L2 F1 (`0.1525`), and fast response (`~1.7–3.2s`), while keeping `DeepSeek-Chat` (`63.16%` recall, `101.5s` full suite, `0.9286` evidence validity) one click away. See `docs/COMPASS_V1_4_MODEL_BENCHMARK_AND_UX_SEAL_2026-11-16.md`.

### 2026-11-21: Two-Stage Public Release Split (`Stage A` v1.6.1 China Seed Release + `get-compass` Org Migration Strategy)

- **Context**: Real-project Sidecar usage exposed stale drift nudges over completed plans, pending backlog inflation from ephemeral `ask_question` prompts, missing clickable links on `verify_completion` reminders, `examples/` path failure in wheel installs, and identity/privacy friction from hosting under the personal `f22363712-dotcom` GitHub handle.
- **Decision**:
  - **Two-Stage Release**: Execute **Stage A** first (China seed launch on Xiaohongshu & Bilibili with simplified Chinese UI, `--demo` podcast-clipper showcase, zero-jargon copy, `.gitignore` `.project-memory/` automation, and `v1.6.1` zero-config packaging/Registry alignment); defer **Stage B** (English UI/i18n, interactive GitHub Pages demo, and Product Hunt / HN / Reddit global launch) until real seed-user feedback arrives.
  - **GitHub Org & Brand Separation**: Keep internal brand name **Compass** (`get-compass` verified available on both GitHub Org & PyPI; do not touch git remotes automatically) while ensuring public URLs remain cleanly switchable upon user org creation. See `docs/STAGE_A_EXECUTION_AND_LAUNCH_PLAYBOOK_2026-11-21.md`.
