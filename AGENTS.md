# Project Compass repository instructions

## Read order

Before changing product behavior or architecture, read:

1. `docs/PRODUCT_SPEC.md`
2. `docs/ROADMAP.md`
3. `DECISIONS.md`
4. `README.md`

The latest explicit user decision overrides these files. Record material scope changes in `DECISIONS.md` before implementing them.

## Product constraints

- The competition version is the complete product described in `docs/PRODUCT_SPEC.md`, delivered incrementally through the golden path in `docs/ROADMAP.md`.
- Do not add enterprise RBAC, a full plugin for every coding-agent ecosystem, autonomous code modification, or production cloud deployment during the competition.
- A personal board represents one developer and Agent session. The project board represents confirmed shared truth.
- Semantic claims remain `proposed` until confirmed by the project owner or a deterministic validation rule.
- Conflicting claims remain visible with both evidence sets. Agents must not silently overwrite another member or an accepted project fact.
- Raw evidence is append-only. Superseded or rejected facts remain in history.

## Honesty and evidence

- Do not present hidden model reasoning as evidence. Record public plans, tool calls, tool results, explicit assumptions, decisions and source references.
- Never fabricate traces, test results, source links, user impact or sponsor-technology usage.
- Distinguish assistant reports, user decisions and user acceptance.
- A successful API call proves only that the call succeeded. It does not prove product value or correctness.
- Every claimed conclusion shown to a user must link to valid evidence or display an explicit evidence gap.

## Engineering rules

- Prefer the existing local Python and web implementation until a smoke test proves a new dependency is necessary.
- Keep credentials in environment variables. Never commit `.env`, tokens, private prompts or personal project data.
- Provide a deterministic `SAMPLE_MODE=true` path for judges and clean-environment tests.
- Bound all external calls and agent loops with timeouts and retry limits.
- Add tests for success, conflict, stale evidence, permission boundaries, restart recovery and sample mode.
- Preserve backward compatibility with the existing Project Compass state format unless a migration and rollback path are documented.
- Run tests from the repository root before reporting work as complete.

## Working method

- Write or update `HANDOFF.md` before long implementation work.
- Use `DECISIONS.md` for decisions with real alternatives and consequences.
- Stop feature work at the gates in `docs/ROADMAP.md`.
- Treat event ingestion, truth promotion, conflict handling and evidence retrieval as one vertical system. Do not build disconnected demo screens.
