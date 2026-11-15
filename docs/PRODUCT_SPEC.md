# Project Compass Product Specification

Status: competition specification, confirmed 2026-10-22

## Product statement

Project Compass is a shared project-state service for teams building with coding agents.

Each developer gets a personal work board generated from their Agent session. Confirmed facts flow into a shared project board. Developers and Agents can then investigate why the project changed, verify current claims, resolve conflicts, and identify the next useful action.

The product is similar to an AI meeting-notes assistant in that it records work continuously. It goes beyond a meeting summary by connecting intent and conversation to code, tests, decisions, abandoned work and evidence.

## Target user

- A team of 2–4 developers working on the same software project.
- Each developer uses Codex, Cursor, Claude Code or another coding Agent.
- The project lasts several days and spans multiple Agent sessions.
- Work includes human decisions, Agent proposals, code changes and test results.
- One project owner confirms accepted shared facts.
- Other members can submit evidence and correction proposals.

Managers, cross-functional product roles and large organizations are outside the first competition release.

## User problem

When developers switch projects, resume an Agent session or hand work to another person, they cannot reliably reconstruct:

- why the project started;
- the current goal and scope;
- which decisions changed;
- which approaches were abandoned;
- what remains unfinished or unverified;
- which current claims conflict with each other;
- which next action is supported by current evidence.

Existing coding Agents can summarize project documents on demand. That baseline remains manual, repeatedly consumes context, reflects stale documents and does not preserve a team-wide evidence history.

## Core experience

### Historical memory layers

- Older eligible public records are imported in resumable bounded batches after the initial connection.
- Each project exposes collection progress separately from semantic organization progress.
- The default board starts with current project state and confirmed decisions. A process layer expands themes and source relationships. A source layer opens exact original messages, tool output and command metadata.
- Exact names, paths and IDs can reach raw source directly. No summary or derived fact can make the append-only source archive unreachable.
- Backfilled history cannot silently change Team truth. New facts remain candidates until the existing owner review rules accept them.
- No new semantic model is required for the first backfill and layered-view release.

### Personal work board

Shows the current Agent session's:

- objective;
- public execution trace;
- tool calls and results;
- decision candidates;
- tasks and acceptance state;
- unverified assumptions;
- evidence links.

### Project board

Shows the shared project's:

- current goal and scope;
- active work and owners;
- accepted decisions;
- open questions;
- abandoned or deferred directions;
- unresolved conflicts;
- latest evidence and stale claims;
- version history.

### Investigation Agent

Answers user questions by querying current facts and raw evidence. It returns:

- a concise answer;
- supporting evidence;
- conflicting evidence;
- unresolved gaps;
- one recommended next action and its acceptance condition.

## Golden task

After returning to a multi-day project, a user asks:

> Why is the project in its current state, and what should happen next?

The system must return the following in one interface:

1. A concise conclusion.
2. The current goal and active tasks.
3. Key evidence supporting the conclusion.
4. Unverified assumptions.
5. Conflicting claims, when present.
6. One next action with an acceptance condition.

This task is the acceptance gate for the complete competition product. It exercises ingestion, personal state, evidence linkage, conflict detection, owner confirmation, project projection and investigation.

## Final competition scope

### 1. Agent event intake

- Connect at least one real development Agent from Codex, Cursor or Claude Code.
- Provide a normalized event protocol for the others.
- Expose MCP or HTTP access for Agents to submit events and read project state.

### 2. Personal work board

- Live or near-live session timeline.
- Structured current state.
- Evidence drawer.
- Proposed decisions, tasks and assumptions.

### 3. Project board

- Team-level current truth.
- Active work and ownership.
- Open decisions.
- Conflicts and stale facts.
- Abandoned directions.
- Version history.

### 4. Truth and conflict system

- Append-only raw evidence.
- Candidate semantic facts in `proposed` state.
- Candidate evidence relations may be suggested by Jev or deterministic rules; they remain unconfirmed until review.
- Owner confirmation or deterministic checks for accepted facts.
- Concurrent conflicting reports remain visible.
- Agents cannot overwrite accepted facts silently.

### 5. Investigation

Support at least three question types:

- why the direction changed;
- what is currently blocked or untrusted;
- what should happen next and what evidence supports it.

### 6. Collaboration and delivery

- Two or more member views.
- Owner confirmation authority.
- Evidence and conflict history.
- Sample mode with no live credentials.
- Clean-clone startup.
- Docker or an equivalent documented reproducible environment.

## State model

| Layer | Examples | Write behavior |
| --- | --- | --- |
| Evidence | Message, commit, file snapshot, test result, tool event | Append-only |
| Candidate fact | Goal, decision, task, assumption, relationship | Proposed by member or Agent |
| Accepted fact | Current goal, accepted decision, verified task, resolved conflict | Owner or deterministic rule |
| Historical state | Superseded, rejected, deferred or restored fact | New status event; old record retained |

## Promotion rules

Automatically record:

- chats and Agent messages;
- Git commits, diffs and file changes;
- test executions;
- tool calls and run logs.

Automatically propose:

- new tasks;
- new assumptions;
- new decisions;
- completion reports;
- inferred causal relationships.

Require owner confirmation:

- changing the project goal;
- accepting or superseding a material decision;
- marking a task complete;
- resolving conflicting reports;
- restoring an abandoned direction.

Deterministic facts may auto-confirm. For example, a commit or failed test can be verified automatically. That does not prove a task is complete or a decision is correct.

## Conflict rules

- Preserve every conflicting report and its evidence.
- Mark the project board as conflicted.
- Show source Agent, author, evidence and observation time for every side.
- The owner confirms the resulting current fact.
- Preserve the conflict and resolution in history.
- Agents can submit evidence or suggestions. They cannot silently overwrite another member's fact.

## GitHub-inspired workflow

| GitHub concept | Project Compass equivalent |
| --- | --- |
| Commit | Immutable evidence event |
| Branch | Personal board or Agent session |
| Pull request | Proposed change to project state |
| Review comment | Evidence, challenge or correction |
| Approve | Owner accepts a proposed fact |
| Request changes | Request more evidence or investigation |
| Status checks | Citation, test and consistency checks |
| Protected branch | Accepted project truth |
| Merge conflict | Conflicting claims about one fact |
| Timeline | Decision, conflict and confirmation history |
| Stale review | Accepted fact becomes stale after new evidence |

The competition release implements the smallest useful subset of these rules. Organization hierarchies, custom enterprise roles and complex approval chains are excluded.

## Evidence rules

- Candidate facts require at least one valid source.
- Unavailable or changed sources mark dependent claims as needing review.
- Answers separate facts, user decisions, Agent proposals, reports and inference.
- Missing evidence is displayed as a gap.
- Raw materials, candidate relations and confirmed evidence relations are displayed as separate states.
- Hidden model reasoning is not stored or presented as evidence.
- Public plans, actions, tool outputs, assumptions and decision summaries form the execution trace.

## Sponsor technology responsibilities

- Zetaris: federated access and semantic queries across project evidence sources.
- Meterless: shared memory, world state and long-task reasoning support where required.
- Cursor: optional development tool after the official sponsor update; this project uses Codex as its primary development Agent.
- NVIDIA: optional Nemotron evaluator or other role that provides genuine value.

Sponsor integration must affect the workflow. A mention or static label is insufficient.

## Non-goals for the competition release

- Enterprise administration or organization-wide RBAC.
- Full production plugin coverage across every Agent ecosystem.
- Autonomous merging, deployment or source-code modification.
- Production-grade multi-region cloud infrastructure.
- Exposing hidden chain-of-thought.
- Replacing GitHub issues, project management tools or source control.

## Acceptance criteria

1. A user can ingest evidence from at least two Agent sessions.
2. The personal board updates from captured events without manual transcript copying.
3. A candidate decision can be proposed, reviewed and accepted by the owner.
4. Two conflicting reports remain visible until resolved.
5. Accepted facts cannot be overwritten silently by an Agent.
6. The investigation Agent answers the golden task with valid evidence links.
7. Superseded decisions and conflicts remain visible in history.
8. `SAMPLE_MODE=true` works without private credentials.
9. The repository starts from a clean checkout using the README.
10. The demo shows one real project scenario with two user or Agent contexts and verifiable sources.

## Competition boundary

The final competition version includes all six modules above with a confined demonstration scope. It must be demonstrable and honest, not a claim of production readiness.

