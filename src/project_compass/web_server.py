from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from collections.abc import Callable
import inspect
from datetime import datetime, timezone
from threading import RLock

from .dashboard import build_dashboard_state
from .investigator import investigate
from .models import EvidenceEvent, EvidenceRelation
from .agent_http import OwnerBrowserAccess, RequestTooLarge, route_agent_request
from .derived_context import DerivedContext


STATIC_ROOT = Path(__file__).parent / "web"
STATIC_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/logo.svg": ("logo.svg", "image/svg+xml; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml; charset=utf-8"),
}

ReviewCallback = Callable[..., dict]


class InvestigationStateChanged(RuntimeError):
    pass


class _DashboardHandler(BaseHTTPRequestHandler):
    server: "DashboardHTTPServer"

    def log_message(self, *_args) -> None:
        return

    def _send(self, status: int, body: str, content_type: str, headers=None) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _reject(self, status, payload):
        # Closing with unread request bytes can reset the connection on Windows,
        # hiding an otherwise valid401/403 response from the submitting client.
        if self.command == 'POST':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                # Discard modest over-limit bodies without parsing them. Keep a
                # separate1MiB/1s drain ceiling for untrusted oversized requests.
                if 0 < length <= 1024 * 1024:
                    self.connection.settimeout(1)
                    self.rfile.read(length)
            except (OSError, ValueError):
                pass
        self.close_connection = True
        self._json(status, payload)

    def _request_json(self) -> dict:
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('chunked requests are unsupported')
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError('invalid request length')
        if length > 256 * 1024:
            raise RequestTooLarge('request exceeds bound')
        self.connection.settimeout(5)
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if route_agent_request(self, parsed.path, 'GET'):
            return
        if parsed.path in STATIC_ASSETS:
            headers = {}
            if parsed.path == '/' and self.server.agent_inbox:
                if not self.server.owner_access.bootstrap_allowed(self):
                    self._json(403, {'error': 'open the local ProjectCompass address directly'})
                    return
                headers['Set-Cookie'] = self.server.owner_access.cookie_header()
            filename, content_type = STATIC_ASSETS[parsed.path]
            self._send(200, (STATIC_ROOT / filename).read_text(encoding="utf-8"), content_type, headers)
            return
        if parsed.path == "/api/state":
            project_id = parse_qs(parsed.query).get("project_id", [""])[0]
            if project_id:
                try:
                    self._json(200, self.server.dashboard_state_for(project_id))
                except ValueError:
                    self._json(404, {"error": "project not found"})
            else:
                self._json(200, self.server.dashboard_state())
            return
        if parsed.path == "/api/export":
            if self.server.agent_inbox and not self.server.owner_access.authorized(self):
                self._reject(403, {'error': 'local owner browser confirmation required'})
                return
            from .cognitive_export import export_state_by_format
            query = parse_qs(parsed.query)
            fmt = query.get("format", ["json"])[0]
            project_id = query.get("project_id", [""])[0].strip()
            if project_id and project_id != self.server.active_project_id():
                try:
                    export_state = self.server.dashboard_state_for(project_id)
                except ValueError:
                    self._json(404, {"error": "project not found"})
                    return
            else:
                export_state = self.server.dashboard_state()
            body, content_type, filename = export_state_by_format(export_state, fmt)
            self._send(200, body, content_type, {'Content-Disposition': f'attachment; filename="{filename}"'})
            return
        if parsed.path == "/api/projects":
            if self.server.sample_mode or not self.server.workspace_root:
                self._json(200, [])
                return
            from .project_workspace import ProjectWorkspace
            self._json(200, ProjectWorkspace.list_registered(self.server.workspace_root))
            return
        if parsed.path == "/api/projects/scan-status":
            scan_job = None if self.server.sample_mode else self.server.project_scan_job
            self._json(200, scan_job.status() if scan_job else {"state": "unavailable"})
            return
        if parsed.path == "/api/evidence":
            query = parse_qs(parsed.query)
            evidence_id = query.get("id", [""])[0]
            project_id = query.get("project_id", [""])[0].strip()
            if project_id and project_id != self.server.active_project_id():
                try:
                    _, _, events, _, _, _ = self.server._load_saved_project(project_id)
                except ValueError:
                    self._json(404, {"error": "project not found"})
                    return
            else:
                events = self.server.dashboard_events
            event = next((event for event in events if event.id == evidence_id), None)
            if event is None:
                self._json(404, {"error": "evidence not found", "evidence_id": evidence_id})
                return
            self._json(200, event.to_dict())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if route_agent_request(self, parsed.path, 'POST'):
            return
        if self.server.agent_inbox and parsed.path in {'/api/review', '/api/extract', '/api/rescan', '/api/refresh', '/api/projects/scan', '/api/query-stats/clear'} and not self.server.owner_access.authorized(self):
            self._reject(403, {'error': 'local owner browser confirmation required'})
            return
        if parsed.path == '/api/extract':
            jobs = self.server.extraction_jobs
            if jobs is None:
                self._reject(409, {'error': 'live extraction is not enabled for this dashboard'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                payload = self._request_json() if length or self.headers.get('Transfer-Encoding') else {}
                if set(payload) - {'member_id'} or ('member_id' in payload and (
                        not isinstance(payload['member_id'], str) or not payload['member_id'].strip()
                        or len(payload['member_id']) > 160)):
                    raise ValueError('invalid extraction scope')
                started = jobs.start(focus_member=payload['member_id']) if 'member_id' in payload else jobs.start()
                self._json(202 if started else 409, {'started': started, 'extraction': jobs.status(),
                    **({} if started else {'error': '提取正在运行、没有新文本或已达到本次启动预算，请查看整理状态。'})})
            except (OSError, ValueError) as exc:
                self._json(400, {'error': type(exc).__name__ + ': extraction request or progress unavailable'})
            return
        if parsed.path == '/api/rescan':
            if self.server.rescan_callback is None:
                self._reject(409, {'error': 'project rescan is not configured for this dashboard'})
                return
            try:
                if int(self.headers.get('Content-Length','0')) or self.headers.get('Transfer-Encoding'):
                    self._request_json()
                with self.server.state_lock:
                    self.server.project_scan_status = self.server.rescan_callback()
                    self._json(200, self.server.dashboard_state())
            except RequestTooLarge:
                self._reject(413, {'error':'request exceeds bound'})
            except (OSError, ValueError) as exc:
                self._json(400, {'error': str(exc)})
            return
        if parsed.path == '/api/projects/scan':
            try:
                payload = self._request_json()
                project_path = Path(str(payload.get('project_path', ''))).expanduser().resolve(strict=True)
                if not project_path.is_dir() or self.server.project_scan_job is None:
                    raise ValueError('project scan is not configured')
                self._json(202, self.server.project_scan_job.start(project_path))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {'error': str(exc)})
            return
        if parsed.path == '/api/projects/scan-status':
            self._json(200, self.server.project_scan_job.status() if self.server.project_scan_job else {'state': 'unavailable'})
            return
        if parsed.path == "/api/refresh":
            if self.server.refresh_callback is None:
                self._reject(409, {"error": "native intake is not configured for this project"})
                return
            try:
                if int(self.headers.get('Content-Length','0')) or self.headers.get('Transfer-Encoding'):
                    self._request_json()
                with self.server.state_lock:
                    self.server.intake_status = self.server.refresh_callback()
                    self._json(200, self.server.dashboard_state())
            except RequestTooLarge:
                self._reject(413, {'error':'request exceeds bound'})
            except (OSError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            return
        if parsed.path == "/api/query-stats/clear":
            self.server.clear_query_statistics()
            self._json(200, self.server.dashboard_state())
            return
        if parsed.path == "/api/investigate":
            try:
                payload = self._request_json()
                if not isinstance(payload, dict):
                    raise ValueError("JSON object is required")
                raw_question = payload.get("question", "")
                if not isinstance(raw_question, str) or not raw_question.strip():
                    raise ValueError("question is required")
                question = raw_question.strip()
                raw_project_id = payload.get("project_id", "")
                if raw_project_id is None:
                    project_id = ""
                elif isinstance(raw_project_id, str):
                    project_id = raw_project_id.strip()
                else:
                    raise ValueError("project_id must be a string")
                if project_id and project_id != self.server.active_project_id():
                    self._json(200, self.server.investigate_for(project_id, question))
                else:
                    self._json(200, self.server.investigate(question, current_member=self.server.intake_status.get('member_id')))
            except InvestigationStateChanged as exc:
                self._json(409, {'error': str(exc)})
            except LookupError as exc:
                self._json(404, {"error": str(exc)})
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            return
        if parsed.path != "/api/review":
            self._reject(404, {"error": "not found"})
            return
        if self.server.review_callback is None:
            self._reject(409, {"error": "review is unavailable for this dashboard"})
            return
        try:
            payload = self._request_json()
            action = str(payload.get("action", "confirm_relation"))
            target_id = str(payload.get("relation_id" if action == "confirm_relation" else "fact_id", ""))
            reviewer = str(payload.get("reviewer", ""))
            note = str(payload.get("note", "")).strip()
            if self.server.agent_inbox and reviewer != self.server.agent_inbox.owner_id:
                self._json(403, {'error': 'configured project owner identity required'})
                return
            if not target_id:
                raise ValueError("relation_id or fact_id is required")
            with self.server.state_lock:
                try:
                    callback = self.server.review_callback
                    if len(inspect.signature(callback).parameters) >= 4:
                        result = callback(action, target_id, reviewer, note)
                    else:
                        result = callback(action, target_id, reviewer)
                except OSError:
                    self._json(503, {'error': 'Review could not be saved. Refresh the board before explicitly retrying.'})
                    return
                self.server.sync_review_state(result)
                self._json(200, self.server.dashboard_state())
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        events: list[EvidenceEvent],
        project_path: str | None = None,
        confirmed_relations=(),
        review_history=(),
        fact_reviews=(),
        review_callback: ReviewCallback | None = None,
        refresh_callback: Callable[[], dict] | None = None,
        intake_status: dict | None = None,
        sample_mode: bool = False,
        rescan_callback: Callable[[], dict] | None = None,
        extraction_jobs=None,
        agent_inbox=None,
        reason_preview=None,
        workspace_root=None,
        project_scan_job=None,
        derived_context: DerivedContext | None = None,
    ):
        if reason_preview and (sample_mode or not reason_preview.matches_project(project_path)):
            raise ValueError('reason preview requires its bound real project')
        if agent_inbox and (server_address[0] not in {'127.0.0.1', 'localhost'} or sample_mode or
                            project_path is None or Path(project_path).resolve() != agent_inbox.workspace.project_path or
                            events is not agent_inbox.events):
            raise ValueError('Agent API requires the same persisted project and loopback-only real dashboard')
        self.state_lock = RLock()
        self.dashboard_events = events
        self.dashboard_project_path = project_path
        self.dashboard_confirmed_relations = list(confirmed_relations)
        self.dashboard_review_history = list(review_history)
        self.dashboard_fact_reviews = list(fact_reviews)
        self.review_callback = review_callback
        self.refresh_callback = refresh_callback
        self.intake_status = dict(intake_status or {"enabled": False})
        self.sample_mode = sample_mode
        self.rescan_callback = rescan_callback
        self.project_scan_status = {'enabled': rescan_callback is not None, 'last_checked_at': None}
        self.extraction_jobs = extraction_jobs
        self.agent_inbox = agent_inbox
        self.reason_preview = reason_preview
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.project_scan_job = project_scan_job
        self.derived_context = derived_context
        self.owner_access = OwnerBrowserAccess() if agent_inbox else None
        if extraction_jobs:
            extraction_jobs.bind(self.state_lock)
        self.dashboard_version = 0
        self.last_dashboard_revision = None
        self.investigation_cache = {}
        self.query_stats = {'total': 0, 'cache_hits': 0, 'questions': {}, 'recent': []}
        super().__init__(server_address, _DashboardHandler)

    def dashboard_state(self) -> dict:
        with self.state_lock:
            revision = self.state_revision()
            if self.last_dashboard_revision is not None and revision != self.last_dashboard_revision:
                self.dashboard_version += 1
            self.last_dashboard_revision = revision
            result = {**build_dashboard_state(
                self.dashboard_events,
                self.dashboard_project_path,
                self.dashboard_confirmed_relations,
                self.dashboard_review_history,
                self.dashboard_fact_reviews,
                session_members={self.intake_status['thread_id']: self.intake_status['member_id']}
                    if self.intake_status.get('enabled') and self.intake_status.get('thread_id') and self.intake_status.get('member_id') else {},
                derived_context=self.derived_context,
            ), "intake": dict(self.intake_status), "sample_mode": self.sample_mode,
                'project_scan': dict(self.project_scan_status), 'state_version': self.dashboard_version,
                'extraction': self.extraction_jobs.status() if self.extraction_jobs else {'enabled': False}}
            result['agent_api'] = self.agent_inbox.public_status() if self.agent_inbox else {'enabled': False}
            from .project_workspace import ProjectWorkspace
            result['projects'] = [] if self.sample_mode else (ProjectWorkspace.list_registered(self.workspace_root) if self.workspace_root else [])
            if self.reason_preview:
                result['reason_preview']=self.reason_preview.project(self.dashboard_events)
            if self.sample_mode:
                result['project']['name'] = 'Sample project'
            result['investigation_stats'] = self.query_statistics()
            return result

    def active_project_id(self) -> str | None:
        if not self.dashboard_project_path:
            return None
        from hashlib import sha1
        return sha1(str(Path(self.dashboard_project_path).resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    def _load_saved_project(self, project_id: str):
        if self.sample_mode:
            raise ValueError("sample mode does not expose saved projects")
        from .project_workspace import ProjectWorkspace
        projects = ProjectWorkspace.list_registered(self.workspace_root) if self.workspace_root else []
        entry = next((item for item in projects if item["project_id"] == project_id), None)
        if entry is None:
            raise ValueError("project not found")
        workspace = ProjectWorkspace(self.workspace_root, entry["project_path"])
        events = workspace.load()
        confirmed, history, reviews = workspace.load_review_state()
        return entry, projects, events, confirmed, history, reviews

    def dashboard_state_for(self, project_id: str) -> dict:
        entry, projects, events, confirmed, history, reviews = self._load_saved_project(project_id)
        payload = build_dashboard_state(events, entry["project_path"], confirmed, history, reviews)
        payload["project"]["read_only"] = True
        payload["projects"] = projects
        return payload

    def investigate_for(self, project_id: str, question: str) -> dict:
        try:
            _, _, events, confirmed, _, reviews = self._load_saved_project(project_id)
        except ValueError as exc:
            raise LookupError(str(exc)) from exc
        answer = investigate(events, question, reviews, list(confirmed)).to_dict()
        answer["memory"] = {"enabled": False}
        answer["sample_mode"] = False
        answer["cache"] = {"hit": False, "state_revision": ""}
        return answer

    def sync_review_state(self, payload: dict) -> None:
        raw_relations = payload.get("confirmed_relations", [])
        raw_history = payload.get("review_history", [])
        raw_fact_reviews = payload.get("fact_reviews", [])
        if not isinstance(raw_relations, list) or not isinstance(raw_history, list) or not isinstance(raw_fact_reviews, list):
            raise ValueError("review response has invalid state")
        self.dashboard_confirmed_relations = [EvidenceRelation.from_dict(value) for value in raw_relations]
        self.dashboard_review_history = [dict(value) for value in raw_history]
        self.dashboard_fact_reviews = [dict(value) for value in raw_fact_reviews]

    def server_close(self):
        if self.extraction_jobs:
            self.extraction_jobs.close()
        super().server_close()

    def state_revision(self):
        value={'events': [event.to_dict() for event in self.dashboard_events],
            'reviews': self.dashboard_fact_reviews, 'history': self.dashboard_review_history,
            'relations': [relation.to_dict() for relation in self.dashboard_confirmed_relations]}
        if self.reason_preview:value['reason_preview']=self.reason_preview.revision
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()

    def investigate(self, question: str, current_member: str | None = None) -> dict:
        with self.state_lock:
            revision = self.state_revision()
            self.query_stats['total'] += 1
            self.query_stats['questions'][question] = self.query_stats['questions'].get(question, 0) + 1
            cache_key = (revision, current_member or "", question)
            if cache_key in self.investigation_cache:
                self.query_stats['cache_hits'] += 1
                cached = deepcopy(self.investigation_cache[cache_key])
                cached["cache"] = {"hit": True, "state_revision": revision}
                self._record_query(question, revision, True, len(cached.get('evidence_gaps', [])))
                return cached
            events = [EvidenceEvent.from_dict(event.to_dict()) for event in self.dashboard_events]
            reviews = [dict(review) for review in self.dashboard_fact_reviews]
            relations = list(self.dashboard_confirmed_relations)
            options = {'session_members': {self.intake_status['thread_id']: self.intake_status['member_id']}
                           if self.intake_status.get('enabled') and self.intake_status.get('thread_id') and self.intake_status.get('member_id') else {}}
            answer = investigate(events, question, reviews, relations, current_member=current_member, derived_context=self.derived_context, **options).to_dict()
            if self.reason_preview:
                answer = self.reason_preview.for_answer(answer, events)
            if revision != self.state_revision():
                raise InvestigationStateChanged('Project state changed during investigation. Ask again for the current state.')
            answer['memory'] = {'enabled': False}
            answer['sample_mode'] = self.sample_mode
            answer['cache'] = {'hit': False, 'state_revision': revision}
            self._record_query(question, revision, False, len(answer.get('evidence_gaps', [])))
            self.investigation_cache[cache_key] = deepcopy(answer)
            if len(self.investigation_cache) > 32:
                self.investigation_cache.pop(next(iter(self.investigation_cache)))
            return answer

    def query_statistics(self) -> dict:
        with self.state_lock:
            repeated = [
                {'question': question, 'count': count}
                for question, count in sorted(self.query_stats['questions'].items(), key=lambda item: (-item[1], item[0]))
                if count > 1
            ][:10]
            return {
                'total': self.query_stats['total'],
                'cache_hits': self.query_stats['cache_hits'],
                'unique_questions': len(self.query_stats['questions']),
                'repeated_questions': repeated,
                'recent_queries': list(self.query_stats['recent']),
            }

    def clear_query_statistics(self) -> None:
        with self.state_lock:
            self.query_stats = {'total': 0, 'cache_hits': 0, 'questions': {}, 'recent': []}
            self.investigation_cache.clear()

    def _record_query(self, question: str, revision: str, cache_hit: bool, gap_count: int) -> None:
        self.query_stats['recent'].append({
            'question': question[:200],
            'state_revision': revision,
            'cache_hit': cache_hit,
            'evidence_gap_count': gap_count,
            'at': datetime.now(timezone.utc).isoformat(),
        })
        del self.query_stats['recent'][:-20]


def create_dashboard_server(
    events: list[EvidenceEvent],
    host: str = "127.0.0.1",
    port: int = 8787,
    project_path: str | None = None,
    confirmed_relations=(),
    review_history=(),
    fact_reviews=(),
    review_callback: ReviewCallback | None = None,
    refresh_callback: Callable[[], dict] | None = None,
    intake_status: dict | None = None,
    sample_mode: bool = False,
    rescan_callback: Callable[[], dict] | None = None,
    extraction_jobs=None,
    agent_inbox=None,
    reason_preview=None,
    workspace_root=None,
    project_scan_job=None,
    derived_context: DerivedContext | None = None,
) -> DashboardHTTPServer:
    return DashboardHTTPServer((host, port), events, project_path, confirmed_relations, review_history, fact_reviews, review_callback, refresh_callback, intake_status, sample_mode, rescan_callback, extraction_jobs, agent_inbox, reason_preview, workspace_root, project_scan_job, derived_context)


def run_dashboard(
    events: list[EvidenceEvent],
    project_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8787,
    confirmed_relations=(),
    review_history=(),
    fact_reviews=(),
    review_callback: ReviewCallback | None = None,
    refresh_callback: Callable[[], dict] | None = None,
    intake_status: dict | None = None,
    sample_mode: bool = False,
    rescan_callback: Callable[[], dict] | None = None,
    extraction_jobs=None,
    agent_inbox=None,
    reason_preview=None,
    workspace_root=None,
    project_scan_job=None,
    derived_context: DerivedContext | None = None,
) -> None:
    server = create_dashboard_server(events, host, port, project_path, confirmed_relations, review_history, fact_reviews, review_callback, refresh_callback, intake_status, sample_mode, rescan_callback, extraction_jobs, agent_inbox, reason_preview, workspace_root, project_scan_job, derived_context)
    print(f"http://{host}:{server.server_address[1]}/", flush=True)
    try:
        if extraction_jobs:
            extraction_jobs.start_scheduler()
        server.serve_forever()
    finally:
        server.server_close()
