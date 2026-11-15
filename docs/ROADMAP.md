# Project Compass Competition Roadmap

Last updated: 2026-10-22

## Strategy

Build one vertical product spine first. Every later feature extends that same spine:

`evidence intake → personal board → candidate facts → evidence and consistency checks → owner confirmation → project board → investigation`

The golden path is the first end-to-end proof. It is also the architecture used by the final competition version.

## Time gates

All external deadlines are UTC. Beijing times are shown for execution.

| Gate | UTC | Beijing | Required state |
| --- | --- | --- | --- |
| Build window | 2026-10-22 00:00 | 2026-10-22 08:00 | Started |
| 25% gate | 2026-10-23 11:56:15 | 2026-10-23 19:56:15 | Real input reaches evidence-backed answer |
| 50% gate | 2026-10-24 23:52:30 | 2026-10-25 07:52:30 | New feature work stops |
| 80% gate | 2026-10-26 19:00 | 2026-10-27 03:00 | Submission hardening only |
| Submission close | 2026-10-27 23:45 | 2026-10-28 07:45 | Final package submitted |

Recomputed2026-10-26 from the verified official143h45m window. The previous80%
row was8 hours late; official final deadline is unchanged. Correcting approved
but missing behavior is required before product acceptance; do not expand scope.

## Phase 0: Contract and environment smoke test

Target: 2026-10-22

- Freeze the product scope in `PRODUCT_SPEC.md`.
- Create a clean standalone repository.
- Verify Python, Node and Docker availability; Cursor is optional after the sponsor update.
- Prove one Zetaris query over at least two sources.
- Prove one Meterless H-MEM or World Model component with a test generator.
- Verify one model call path and usage logging.
- Confirm no real credentials enter Git.

Exit condition: the two required sponsor technologies are verified independently;
the optional model path has usage logging when enabled. NVIDIA use is conditional
on an actual contribution under the verified rules, not a third mandatory layer.

## Phase 1: Golden vertical path

Target: complete before the 25% gate.

Input:

- one anonymized real project;
- two Agent sessions;
- Git changes, tests and project notes;
- one conflicting task status.

User question:

> Why is the project in its current state, and what should happen next?

Output:

- concise conclusion;
- current goal and active tasks;
- evidence links;
- unresolved assumptions;
- both sides of the conflict;
- one next action and acceptance condition.

Exit condition: the path runs from captured raw evidence to an evidence-backed answer without hand-written output.

## Phase 2: Complete personal board and shared-state protocol

Target: 2026-10-23 to 2026-10-24

- Normalize Agent events.
- Implement a real adapter for the first Agent ecosystem.
- Provide adapters or documented event import for the other two.
- Add MCP or HTTP endpoints:
  - append evidence;
  - propose fact;
  - read current project state;
  - query evidence;
  - confirm or reject a proposal.
- Build the personal board from the same API.
- Record stale evidence and changed source behavior.

## Phase 3: Project board, ownership and conflict

Target: finish before the 50% gate.

- Add project-level projection.
- Add owner confirmation and member suggestions.
- Preserve conflict versions and audit history.
- Prevent accepted facts from silent overwrite.
- Add two-member demonstration using separate profiles or test clients.
- Add a minimal review flow modeled on GitHub pull requests.

## Phase 4: Investigation depth and scale

Target: 2026-10-25 to 2026-10-26

- Implement the three supported question types.
- Add evidence sufficiency checks.
- Add conflict and stale-claim checks.
- Test with a larger frozen fixture covering hundreds of events.
- Measure latency, unsupported claims and source coverage.
- Keep synthetic scale fixtures separate from real user evidence.

## Phase 5: Sponsor-technology integration

Target: 2026-10-25 and 2026-10-26

- Make Zetaris load-bearing for cross-source queries or the semantic layer.
- Use the smallest useful Meterless engine set.
- Record that the project was developed with Codex; keep the development transcript and repository evidence for submission.
- Add NVIDIA Nemotron only if it provides a real evaluator or reasoning role.
- Route sponsor integrations through adapters with timeouts and sample-mode fallbacks.

## Phase 6: Final competition package

Target: after the 80% gate

- Freeze product features.
- Run unit, integration, restart, conflict, permission and sample-mode tests.
- Perform the full validation flow from a clean clone.
- Scan the Git history, logs, screenshots and video for secrets.
- Produce the 1–4 minute demo video.
- Produce the slide deck.
- Complete README, architecture, limitations and pre-existing-work disclosure.
- Verify all links in a private browser window.
- Submit with at least several hours of margin.

## Final hardening slice: bounded history and layered reading

Target: before the 2026-10-27 23:45 UTC submission close

- Continue eligible public tool and command history in resumable batches after the initial window.
- Expose batch progress, remaining records and last read time without claiming semantic completeness.
- Add explicit overview, process and source reading layers to the existing dashboard.
- Keep raw evidence append-only, owner review authoritative and new semantic model calls disabled.

Exit condition: repeated refresh imports the next bounded historical batch without duplicate evidence, restart reopens the saved progress, and a user can move from current state to process details to exact source text in one local dashboard.

## Post-golden-path order

After the golden path works, proceed in this order:

1. Expand event capture.
2. Add personal-board structure and evidence drill-down.
3. Add candidate-to-accepted fact promotion.
4. Add conflicting claims and audit history.
5. Add shared project ownership and confirmation.
6. Add investigation question types.
7. Add scale and source-staleness checks.
8. Improve visual hierarchy and navigation.
9. Package the project for independent execution.

Do not reverse this order. UI polish cannot precede trustworthy state. Additional Agent connectors cannot precede the normalized event protocol. More agents cannot precede conflict and ownership rules.

## Scope freeze

These items remain outside the competition release across all phases:

- enterprise RBAC;
- complete live support for every Agent ecosystem;
- autonomous source-code modification or deployment;
- organization-wide analytics;
- production multi-region infrastructure;
- hidden chain-of-thought display;
- replacement of Git or project-management systems.

