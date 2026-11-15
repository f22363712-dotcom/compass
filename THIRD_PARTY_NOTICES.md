# Third-party notices

Project Compass first-party source code is licensed under the **Apache License, Version 2.0**
(see [`LICENSE`](LICENSE)). This notice file preserves attribution for upstream
build-process skill files and historical reference notes without reassigning licenses
to third-party work.

## Devpost Learn AI Basics Skill Pack

Local workflow copies under `.agents/skills/` and `agent/skills/` originate from
[challengepost/learn-ai-basics](https://github.com/challengepost/learn-ai-basics).
The source/file hashes are recorded in `skills-lock.json`. The upstream MIT
license, including its copyright and permission notice, is preserved in
[licenses/learn-ai-basics-MIT.txt](licenses/learn-ai-basics-MIT.txt).
These skills are optional authoring tools and are excluded from runtime execution
and clean public release packages.

## Historical Reference Components (Retired in v1.0)

### Meterless

The historical competition setup script (archived under
`docs/archive/competition_legacy/`) referenced Meterless at commit
`1742dec56a66e58eef9dda2d2b865823758ca8cd` (upstream Apache-2.0). No upstream
Meterless source or binaries are vendored in this repository.

### Zetaris and JDBC clients

Historical competition documentation referenced optional external Zetaris / JDBC
packages (`JayDeBeApi`, `JPype1`, `packaging`). No vendor archives, credentials,
or binaries are distributed in this repository, and runtime Project Compass v1.0
uses pure Python standard library (`dependencies = []`).
