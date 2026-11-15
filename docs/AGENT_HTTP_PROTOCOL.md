# Local Agent HTTP protocol

Status2026-10-25. Optional normalized event adapter for the existing local board.
Normal first use remains project scan and the selected native Codex connector.
This protocol does not require users to export an entire transcript first.

## Enable one explicitly bound client

Create an ignored private config in ProjectCompass, replacing the project path
and identities below. Each client must have a distinct member/session/client ID.
Generate a random token in the process environment or ignored root `.env`. Config
stores its environment-variable name only; inline secret values are rejected.
Never paste a token into a prompt, commit or screenshot.
The example is synthetic and is not a real project report.

```python
from pathlib import Path
import json, secrets
project = Path('D:/Projects/your-project').resolve(strict=True)
private = Path('.project-memory/agent-access.json')
private.parent.mkdir(parents=True, exist_ok=True)
token_name = 'PROJECT_COMPASS_AGENT_' + secrets.token_hex(4).upper() + '_TOKEN'
config = {
    'schema_version': 1, 'project_path': str(project), 'owner_id': 'project-owner',
    'clients': [{'client_id': 'coding-agent-a', 'member_id': 'Agent context A',
                 'session_id': 'your-agent-session-id', 'agent': 'codex',
                 'token_env': token_name}]
}
with private.open('x', encoding='utf8') as handle:
    json.dump(config, handle, ensure_ascii=False, indent=2)
with Path('.env').open('a', encoding='utf8') as handle:
    handle.write('\n' + token_name + '=' + secrets.token_urlsafe(32) + '\n')
print(private)  # path only
```

From the repository root with `PYTHONPATH=src`, use the existing scan/open command
and add `--agent-access-file .project-memory/agent-access.json --web`. The config
must name that exact project. Real Agent clients are rejected in sample mode;
the server stays bound to loopback. Do not use a shared example token.

The local browser's owner identity is fixed to the configured owner. Opening the
local UI issues a per-launch HttpOnly SameSite=Strict cookie. Review requires that
cookie, the exact local Origin and the configured reviewer. Any Authorization
header is rejected on owner write routes. Owner cookies never appear in JSON or
client config. Refresh, scans and explicit model jobs use the same owner channel.

This separates normal protocol capabilities on a trusted personal computer. It
does not isolate programs that already control the user's local browser/files.
The existing local read routes remain readable from that computer. This is not
enterprise authentication or a remote multi-user deployment.

## Routes

| Method/path | Capability | Result |
| --- | --- | --- |
| GET `/api/agent/state` | client Bearer token | Current shared state, no tokens |
| POST `/api/agent/events` | client Bearer token | Canonical IDs and appended count |
| POST `/api/agent/proposals` | client Bearer token | Exact-source proposed records |
| GET `/api/evidence?id=ID` | existing local read | Original source record |
| POST `/api/review` | local owner browser | Existing owner review workflow |

Agent writes reject browser Origin headers. There is no CORS enablement or retry
loop. Responses use401 for missing/bad Agent credentials,403 for denied capability,
404 when disabled/unknown,400 for invalid input or identity conflict, and413 above
256KiB. A request contains1..20 entries. Invalid batches append nothing.

## Evidence body

```json
{
  "schema_version": 1,
  "events": [{
    "id": "external-event-001",
    "type": "assistant_message",
    "timestamp": "2026-10-25T08:00:00Z",
    "content": "Browser fixture passed; device verification remains pending.",
    "source_ref": "reported-transcript.jsonl:7"
  }]
}
```

Supported types are `assistant_message`, `tool_call`, `tool_result`, `test_result`
and `file_change`. `user_message` is not accepted as an authenticated human
decision; native human capture remains separate. ID and timezone-aware timestamp
are required. Content must be nonempty text, at most48000 characters. Optional
`tool`, `command`, integer `exit_code` and bounded `files` are public report fields.
Command text is at most16000 serialized characters; recognized sensitive switches
in argv or ordinary shell strings reject the batch. Sensitive markers and known
configured credentials are screened. This is not universal secret sanitization.

Member/session/Agent identity comes from private config. Author, metadata.facts,
owner status and arbitrary metadata fields are rejected. The original source_ref
is stored as `reported_source_ref`, a client claim, never a server-verified path.
Canonical provenance uses `agent://CLIENT/CANONICAL_ID`; no reported path is opened.

IDs are namespaced by project, client and external ID. Exact retries append0.
Changing content, metadata or timestamp under the same ID rejects the whole batch.
Publication does not call a model, execute a command, modify the scanned project
or prove that a reported test/task succeeded.

## Candidate body

Use a canonical source ID returned by the event endpoint, or another readable raw
source already in this project. The quote must occur exactly in its content.

```json
{
  "schema_version": 1,
  "proposals": [{
    "id": "external-proposal-001",
    "source_id": "CANONICAL_SOURCE_ID",
    "kind": "task",
    "subject_key": "device-verification",
    "quote": "Browser fixture passed; device verification remains pending.",
    "task_state": "pending"
  }]
}
```

Kind is goal/task/decision/assumption. Optional task_state is pending/active/
blocked/reported_complete/unknown. There is no accepted status input. Existing
source-span validation is reused. The authenticated Agent owns the proposal,
while original source attribution remains unchanged. Agent tool/test/file reports
remain assistant reports; directly captured native execution is labeled execution
record. A source quote and an owner acceptance are distinct events.

## Minimal non-browser client

An Agent integration can use any local HTTP client. This synthetic Python example
loads the private token without printing it and performs one request, no redirects.
The payload file contains an evidence or proposal body as above.

```python
import http.client, json, os
from pathlib import Path
from project_compass.env_loader import load_env_file
load_env_file(Path('.env'))
config = json.loads(Path('.project-memory/agent-access.json').read_text('utf8'))
client = next(c for c in config['clients'] if c['client_id'] == 'coding-agent-a')
body = Path('public-events.json').read_bytes()
connection = http.client.HTTPConnection('127.0.0.1', 8787, timeout=10)
connection.request('POST', '/api/agent/events', body, {
    'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ[client['token_env']]
})
response = connection.getresponse()
print(response.status, response.read().decode('utf8'))  # IDs/errors only
connection.close()
```

## Real acceptance and limits

The selected Lucid root conversation explicitly links a validation Agent context;
its native header names the same project. Only that bounded context was read.
Four public assistant messages and30 command reports were normalized through HTTP.
Two complete historical report quotes were submitted as unaccepted assumptions.
This is exact-source selection by the validation client, not a claim that a model
automatically understood the new context or that another human joined the team.

Root and validation Agent contexts now have separate visible provenance. The latter
contains34 sources/2 candidates; the whole board has975 visible sources/34 statements
and2 original owner reviews. All978 pre-slice internal records and review hashes
match. Replays append0 without rewriting state. Agent attempts to review or start
a model job return403. Private config, source receipts and screenshots stay ignored.

The peer's historical candidate has a different APK hash from the latest accepted
Lucid document. It is not current-package verification. Native test coverage,
complete semantic history and real multi-human collaboration remain separate
acceptance items. No phone, source edit or model request occurred in this slice.
