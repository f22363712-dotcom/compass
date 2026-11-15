# Environment Check

The competition version must run from a clean checkout without private local setup.

## Required checks

- [x] Python available and version recorded
- [x] Node.js version verified
- [x] Docker daemon verified with a trivial container
- [x] Codex used for competition development; Cursor is optional
- [x] Zetaris instance or gateway access obtained
- [x] Zetaris can query at least two evidence source families
- [x] Meterless reference engine selected and implemented
- [x] One explicit model call path verified with actual usage logging
- [ ] NVIDIA Nemotron access tested if it will have a real role
- [x] `.env` ignored and `.env.example` contains placeholders only

## Historical baseline

- Python 3.11.9 selected for the project virtual environment.
- Local virtual environment created at `.venv`.
- Python package metadata added in `pyproject.toml`.
- Docker CLI 29.3.1 is installed.
- Docker daemon check failed during the initial run; a trivial container has not yet been verified.
- Node.js executable found at `<LOCAL_NODE_BIN>`; version execution did not complete during the initial check.
- Cursor 3.19.7 is installed at `%LOCALAPPDATA%\Programs\Cursor\Cursor.exe`; the executable signature is valid and signed by Anysphere, Inc.
- Cursor was launched against the ProjectCompass directory.
- The Cursor sponsor resource still states that each hackathon team receives access and marks activation as `TBC`.
- The latest HackOS `Help Cursor` message (displayed 2026-10-22 04:53 PM) says Cursor will not provide tokens or credits for the event. Participants may use the free version, and the setup guide is being updated.
- The signed-in Cursor account currently reports the `Free` plan, 0% of included usage consumed, and a displayed reset date of 2026-11-22. Cursor's current plan page labels the Free allowance as "Limited" without publishing an exact request or token count.
- Independent Git repository initialized on branch `main`.
- `.gitignore` excludes `.env`, virtual environments, local databases and generated logs.
- Package import smoke test passed with Python 3.11.9.
- Zetaris getting-started repository cloned to the ignored `.tools/` directory and checked out at `44668b267ad7ee0fae25ce7588e9620121d47cae`.
- Zetaris preflight ran successfully as a script and reported five missing configuration checks: `.env.local`, API key, username, password and REST readiness.

## Historical blockers, superseded by the October26 checks below

- Zetaris access remains unverified. Its checked-in getting-started preflight currently exits1 with5 failed checks: no local connection file, missing API key/user/password, and REST unavailable without a key. Project-root sponsor key values are placeholders, not verified credentials.
- Meterless uses the official local World Model reference with no API key. Explicit `--meterless` web investigation is implemented and verified against Lucid; setup and limits are in `METERLESS_INTEGRATION.md`.
- No Cursor subscription is required for the chosen Codex development workflow.

## Current verification, 2026-10-25

- `node --version` returned `v24.11.1`.
- `docker version --format ...` reported client/server `29.9.2`.
- `docker run --rm hello-world` succeeded. The official image digest was `sha256:11a3eb1597e864c51b3f56733cb2e8a90bf0c284bfc05f9444d81c558bc848aa`.
- Codex's explicit candidate-extraction path has one accepted real batch and actual token logging; automatic refresh does not call models.
- Native public-message intake and the local dashboard run with Python3.11. Root `.env` and all real capture/cache data remain ignored by Git.
- Zetaris read-only preflight command was `.venv/Scripts/python.exe .tools/zetaris-getting-started/scripts/preflight.py`; exit1 and the missing checks are preserved in ignored `logs/zetaris-preflight-current.txt`. Docker availability does not prove Zetaris readiness.
- Current Zetaris official guide describes an own local or AWS instance. Gateway login and user-approved personal registry acknowledgement are complete; registry login and required local preflight checks passed. Images are being pulled; no paid infrastructure was created. See `ZETARIS_LOCAL_SETUP.md`.
- Meterless reference commit `1742dec56a66e58eef9dda2d2b865823758ca8cd` passed10 upstream unit tests and8 conformance checks. Pinned setup script completed using Node24.11.1 and lockfile installation with scripts disabled.
- Real Meterless adapter/server tests passed5 checks. Lucid HTTP runs returned16 facts,2 accepted facts,16 support links,2 owner reviews and56 engine events; repeated queries kept56 events. Initial latency1900ms and warm process-per-query1549/1819ms. All queries were local and added no model requests.

## Minimum smoke-test sequence

1. Start the empty application from a clean checkout.
2. Submit one evidence event through the public API.
3. Query it through Zetaris.
4. Write and retrieve one world-state or memory item through Meterless.
5. Ask a question through the investigation path.
6. Return a structured answer with valid source references.
7. Repeat with `SAMPLE_MODE=true` and no real credentials.

Record exact commands, versions, timings and failures in this file as each check is completed.

## Current verification, 2026-10-26

The local Zetaris stack is running; official verify.sh passed9/9, including
authenticated SQL through UI/API/driver/Spark. Driver uses loopback10010 and UI
uses loopback3000. Docker was not restarted and no paid resource was created.

Actual product investigation reads54 Meterless facts/54 links/two owner reviews
and retrieves33 hash-verified sources across two Zetaris REST input families.
These are logical input families, not two independent remote databases. See
`ZETARIS_LOCAL_SETUP.md` and `VISUAL_TRACE.md` for current receipts and limits.

Independent source/client verification reuses the existing authorized backend;
full backend provisioning on another environment remains unverified. Current
main and independent extraction are disabled. The ledger has45 requests,
171643 known tokens and28 historical requests with unknown usage.

The earlier pull/preflight blockers above are historical observations, not
current failures. The source/history publication audit found private project
metadata despite zero credential-scan findings; see `PUBLICATION_AUDIT.md`.

## Historical independent source-only startup

`CLEAN_START_ACCEPTANCE.md` records snapshot334e14e tested in a new temporary
directory outside Git ancestry, using a new Python3.11.9 venv and no credentials
or private state. The README bootstrap, SAMPLE_MODE CLI and actual web
review/restart passed.106 clean checks passed and6 Meterless real-reference
checks were explicitly skipped. Root suite passed112 with its reference present.
Full sponsor bootstrap still awaits Zetaris.

