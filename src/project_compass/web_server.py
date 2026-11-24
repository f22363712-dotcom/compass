from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from collections.abc import Callable
import inspect
from datetime import datetime, timezone
from threading import RLock, Timer
import webbrowser

from .agent_hints import AsyncHintCache, synthesize_investigation_summary
from .dashboard import build_dashboard_state
from .host_adapter import parse_workspace_uri
from .investigator import investigate
from .llm_connector import public_llm_status, set_active_llm_profile
from .models import EvidenceEvent, EvidenceRelation
from .agent_http import OwnerBrowserAccess, RequestTooLarge, route_agent_request
from .derived_context import DerivedContext
from .team_templates import (
    extract_priority_dispatches,
    list_team_templates,
    record_priority_dispatch,
)


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


def _parse_since_version(query_str: str) -> int | None:
    raw = parse_qs(query_str).get("since_version", [""])[0].strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


class _DashboardHandler(BaseHTTPRequestHandler):
    server: "DashboardHTTPServer"
    timeout = 10

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

    def _require_local_post_guard(
        self,
        *,
        require_json_content_type: bool = False,
    ) -> tuple[bool, tuple[int, dict] | None]:
        """Enforce loopback Host, Origin/Sec-Fetch-Site (or trusted sidecar secret), and safe Content-Type."""
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        host_header = str(self.headers.get("Host") or "").strip()
        req_ver = getattr(self, "request_version", None)
        if not host_header:
            if req_ver and req_ver != "HTTP/1.0":
                return False, (403, {"error": "local loopback host required"})
        else:
            try:
                host_only = urlparse(f"http://{host_header}").hostname or ""
            except ValueError:
                return False, (403, {"error": "local loopback host required"})
            if host_only.lower() not in local_hosts:
                return False, (403, {"error": "local loopback host required"})

        secret = getattr(self.server, "sidecar_internal_secret", None)
        provided_secret = str(self.headers.get("X-Compass-Sidecar-Secret") or "")
        client_addr = getattr(self, "client_address", None)
        client_ip = str((client_addr or ("", 0))[0] or "")
        trusted_sidecar_proxy = bool(
            secret
            and provided_secret
            and provided_secret.isascii()
            and client_ip in {"127.0.0.1", "::1"}
            and hmac.compare_digest(provided_secret, secret)
        )

        origin_header = str(self.headers.get("Origin") or "").strip()
        sec_fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if not trusted_sidecar_proxy:
            if sec_fetch_site == "cross-site":
                return False, (403, {"error": "cross-origin mutation blocked"})
            if origin_header:
                try:
                    origin_host = urlparse(origin_header).hostname or ""
                except ValueError:
                    return False, (403, {"error": "cross-origin mutation blocked"})
                if origin_host.lower() not in local_hosts:
                    return False, (403, {"error": "cross-origin mutation blocked"})

        content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type in {"text/plain", "multipart/form-data"}:
            return False, (415, {"error": "Content-Type must be application/json"})
        if content_type == "application/x-www-form-urlencoded":
            if require_json_content_type or origin_header or sec_fetch_site:
                return False, (415, {"error": "Content-Type must be application/json"})
        elif require_json_content_type and content_type != "application/json":
            return False, (415, {"error": "Content-Type must be application/json"})
        return True, None

    def _require_local_json_post(self) -> tuple[bool, tuple[int, dict] | None]:
        """Enforce JSON content-type and loopback Origin/Host (or trusted sidecar bridge secret) on mutations."""
        return self._require_local_post_guard(require_json_content_type=True)

    def _sync_server_workspace(self, *, force_derived: bool = False) -> None:
        sync = getattr(self.server, "_sync_workspace_if_changed", None)
        if callable(sync):
            sync(force_derived=force_derived)

    def _handle_quick_note(self) -> None:
        ok, err = self._require_local_json_post()
        if not ok:
            status_code, err_payload = err
            self._reject(status_code, err_payload)
            return
        if self.server.sample_mode:
            self._reject(403, {"error": "sample mode is read-only; quick notes require a real workspace"})
            return
        workspace = self.server.active_workspace()
        if workspace is None:
            self._reject(409, {"error": "quick note requires a persisted project workspace"})
            return
        try:
            payload = self._request_json()
        except RequestTooLarge:
            self._reject(413, {"error": "request exceeds bound"})
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return

        req_project_id = payload.get("project_id")
        if req_project_id is not None:
            if not isinstance(req_project_id, str):
                self._json(400, {"error": "project_id must be a string"})
                return
            if req_project_id.strip() and req_project_id.strip() != self.server.active_project_id():
                self._json(403, {"error": "cannot write quick notes to a read-only preview project"})
                return

        text = payload.get("text", "")
        kind = payload.get("kind", "decision")
        title = str(payload.get("title") or "")
        topic = str(payload.get("topic") or "")
        auto_accept = bool(payload.get("auto_accept", False))
        client_nonce = str(payload.get("client_nonce") or "")
        review_note = str(payload.get("note") or "").strip()
        reviewer = str(payload.get("reviewer") or "").strip()

        if auto_accept:
            if self.server.review_callback is None:
                self._reject(409, {"error": "review is unavailable for this dashboard"})
                return
            if self.server.agent_inbox:
                if reviewer != self.server.agent_inbox.owner_id:
                    self._json(403, {"error": "configured project owner identity required"})
                    return
            elif not reviewer:
                self._json(400, {"error": "reviewer is required when auto_accept is enabled"})
                return

        from .evidence_filters import is_public_raw_event, resolve_member_id
        from .quick_notes import append_quick_note

        with self.server.state_lock:
            self._sync_server_workspace()
            existing_members = [
                resolve_member_id(ev, session_members=self.server._session_members(), route_documents=True)
                for ev in self.server.dashboard_events
                if is_public_raw_event(ev)
            ]
            human_members = []
            for m in existing_members:
                if m and m != "project-documents" and m not in human_members:
                    human_members.append(m)
            requested_member = str(payload.get("member_id") or "").strip()
            if requested_member and requested_member in human_members:
                target_member = requested_member
            else:
                intake_member = str(self.server.intake_status.get("member_id") or "").strip()
                target_member = (
                    intake_member
                    if intake_member and intake_member not in {"project-documents", "__local_owner__"}
                    else (human_members[0] if human_members else "solo")
                )

            try:
                note_meta = append_quick_note(
                    workspace,
                    self.server.dashboard_events,
                    text=text,
                    kind=kind,
                    member_id=target_member,
                    title=title,
                    topic=topic,
                    client_nonce=client_nonce,
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except OSError:
                self._json(503, {"error": "Quick note could not be saved. Retry shortly."})
                return

            accepted = False
            warning = None
            if auto_accept:
                try:
                    callback = self.server.review_callback
                    if len(inspect.signature(callback).parameters) >= 4:
                        rev_result = callback("accept_fact", note_meta["fact_id"], reviewer, review_note)
                    else:
                        rev_result = callback("accept_fact", note_meta["fact_id"], reviewer)
                    self.server.sync_review_state(rev_result)
                    accepted = True
                except (ValueError, OSError) as exc:
                    warning = str(exc)

            self.server.record_workspace_signature()
            response_state = self.server.dashboard_state()
            response_state["quick_note"] = {
                **note_meta,
                "accepted": accepted,
                **({"warning": warning} if warning else {}),
            }
            self._json(200, response_state)

    def _handle_dispatch(self) -> None:
        ok, err = self._require_local_json_post()
        if not ok:
            status_code, err_payload = err
            self._reject(status_code, err_payload)
            return
        try:
            payload = self._request_json()
        except RequestTooLarge:
            self._reject(413, {"error": "request exceeds bound"})
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return

        req_project_id = payload.get("project_id")
        if req_project_id is not None:
            if not isinstance(req_project_id, str):
                self._json(400, {"error": "project_id must be a string"})
                return
            if req_project_id.strip() and req_project_id.strip() != self.server.active_project_id():
                self._json(403, {"error": "cannot write priority dispatches to a read-only preview project"})
                return

        fact_id = str(payload.get("fact_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        value = str(payload.get("value") or "").strip()
        evidence_ids = payload.get("evidence_ids") if payload.get("evidence_ids") is not None else []
        mode = str(payload.get("mode") or "queue").strip() or "queue"
        note = str(payload.get("note") or "").strip()
        actor = str(payload.get("reviewer") or payload.get("actor") or "").strip()

        if self.server.agent_inbox and actor != self.server.agent_inbox.owner_id:
            self._json(403, {"error": "configured project owner identity required"})
            return
        if not fact_id or not value:
            self._json(400, {"error": "fact_id and value are required"})
            return
        if not isinstance(evidence_ids, list):
            self._json(400, {"error": "evidence_ids must be a list"})
            return

        if self.server.sample_mode:
            response_state = self.server.dashboard_state()
            response_state["dispatch"] = {
                "id": "sample-dispatch",
                "fact_id": fact_id,
                "title": title or value[:28],
                "value": value,
                "evidence_ids": [str(eid) for eid in evidence_ids if str(eid).strip()],
                "actor": actor or "sample-owner",
                "mode": mode,
                "sample_mode": True,
            }
            self._json(200, response_state)
            return

        workspace = self.server.active_workspace()
        if workspace is None:
            self._reject(409, {"error": "priority dispatch requires a persisted project workspace"})
            return

        with self.server.state_lock:
            self._sync_server_workspace()
            try:
                dispatch_meta = record_priority_dispatch(
                    workspace,
                    fact_id=fact_id,
                    title=title,
                    value=value,
                    evidence_ids=evidence_ids,
                    actor=actor or "solo",
                    mode=mode,
                    note=note,
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except OSError:
                self._json(503, {"error": "Priority dispatch could not be saved. Retry shortly."})
                return
            self.server.dashboard_events[:] = workspace.load()
            self.server.record_workspace_signature()
            response_state = self.server.dashboard_state()
            response_state["dispatch"] = dispatch_meta
            self._json(200, response_state)

    def _touch_activity(self) -> None:
        cb = getattr(self.server, "activity_callback", None)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def do_GET(self) -> None:
        self._touch_activity()
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json(200, {
                "ok": True,
                "project_path": self.server.dashboard_project_path,
                "project_id": self.server.active_project_id(),
                "pid": os.getpid(),
                "sample_mode": self.server.sample_mode,
            })
            return
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
            query_map = parse_qs(parsed.query)
            project_id = query_map.get("project_id", [""])[0]
            if project_id and project_id != self.server.active_project_id():
                try:
                    self._json(200, self.server.dashboard_state_for(project_id))
                except ValueError:
                    self._json(404, {"error": "project not found"})
            else:
                since_version = _parse_since_version(parsed.query)
                if not getattr(self.server, "sample_mode", False):
                    pre_sync = getattr(self.server, "pre_sync_discovery", None)
                    if callable(pre_sync):
                        pre_sync()
                def _fetch_state():
                    return (
                        self.server.dashboard_state()
                        if since_version is None
                        else self.server.dashboard_state(since_version=since_version)
                    )
                lock = getattr(self.server, "state_lock", None)
                snap = getattr(self.server, "_latest_state_snapshot", None)
                if lock is not None:
                    acquired = lock.acquire(timeout=0.35)
                    if acquired:
                        try:
                            payload = _fetch_state()
                        finally:
                            lock.release()
                        self._json(200, payload)
                    elif snap is not None:
                        self._json(200, snap)
                    else:
                        self._json(200, _fetch_state())
                else:
                    self._json(200, _fetch_state())
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
            status = scan_job.status() if scan_job else {"state": "unavailable"}
            if status.get("state") == "complete" and status.get("project_id") == self.server.active_project_id():
                with self.server.state_lock:
                    self._sync_server_workspace(force_derived=True)
            self._json(200, status)
            return
        if parsed.path == "/api/evidence":
            query = parse_qs(parsed.query)
            evidence_id = query.get("id", [""])[0]
            project_id = query.get("project_id", [""])[0].strip()
            if project_id and project_id != self.server.active_project_id():
                try:
                    _, _, events, _, _, _, _ = self.server._load_saved_project(project_id)
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

    def _handle_activate_project(self) -> None:
        ok, err = self._require_local_json_post()
        if not ok:
            status_code, err_payload = err
            self._reject(status_code, err_payload)
            return
        if self.server.sample_mode:
            self._reject(403, {"error": "sample mode cannot switch workspaces"})
            return
        try:
            payload = self._request_json()
        except RequestTooLarge:
            self._reject(413, {"error": "request exceeds bound"})
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        raw_path = payload.get("project_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            self._json(400, {"error": "project_path is required"})
            return
        try:
            target_root = parse_workspace_uri(raw_path)
            if not target_root.is_dir():
                raise ValueError(f"project_path directory not found: {target_root}")
            self._json(200, self.server.activate_project_workspace(target_root))
        except PermissionError as exc:
            self._json(403, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        self._touch_activity()
        parsed = urlparse(self.path)
        if route_agent_request(self, parsed.path, 'POST'):
            return
        ok, err = self._require_local_post_guard(
            require_json_content_type=parsed.path in {
                '/api/notes',
                '/api/dispatch',
                '/api/projects/activate',
                '/api/projects/scan',
                '/api/llm-mode',
            }
        )
        if not ok:
            status_code, err_payload = err
            self._reject(status_code, err_payload)
            return
        if self.server.agent_inbox and parsed.path in {'/api/review', '/api/notes', '/api/dispatch', '/api/extract', '/api/rescan', '/api/refresh', '/api/projects/scan', '/api/projects/activate', '/api/query-stats/clear', '/api/llm-mode'} and not self.server.owner_access.authorized(self):
            self._reject(403, {'error': 'local owner browser confirmation required'})
            return
        if parsed.path == '/api/projects/activate':
            self._handle_activate_project()
            return
        if parsed.path == '/api/dispatch':
            self._handle_dispatch()
            return
        if parsed.path == '/api/llm-mode':
            if self.server.sample_mode:
                self._reject(409, {'error': 'sample mode uses fixed local retrieval'})
                return
            try:
                payload = self._request_json()
                if not isinstance(payload, dict):
                    raise ValueError('JSON object is required')
                profile_id = str(payload.get('profile_id', '')).strip()
                if not profile_id:
                    raise ValueError('profile_id is required')
                set_active_llm_profile(profile_id)
                with self.server.state_lock:
                    self.server.investigation_cache.clear()
                    self.server.hint_cache.clear()
                    self._json(200, self.server.dashboard_state())
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {'error': str(exc)})
            return
        if parsed.path == '/api/notes':
            self._handle_quick_note()
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
                extract_docs = bool(payload.get('extract_docs', True))
                with_code_index = bool(payload.get('with_code_index', True))
                self._json(202, self.server.project_scan_job.start(project_path, extract_docs=extract_docs, with_code_index=with_code_index))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json(400, {'error': str(exc)})
            return
        if parsed.path == '/api/projects/scan-status':
            status = self.server.project_scan_job.status() if self.server.project_scan_job else {'state': 'unavailable'}
            if status.get('state') == 'complete' and status.get('project_id') == self.server.active_project_id():
                with self.server.state_lock:
                    self._sync_server_workspace(force_derived=True)
            self._json(200, status)
            return
        if parsed.path == "/api/refresh":
            if self.server.refresh_callback is None:
                self._reject(409, {"error": "native intake is not configured for this project"})
                return
            try:
                if int(self.headers.get('Content-Length','0')) or self.headers.get('Transfer-Encoding'):
                    self._request_json()
                since_version = _parse_since_version(parsed.query)
                if not getattr(self.server, "sample_mode", False):
                    pre_sync = getattr(self.server, "pre_sync_discovery", None)
                    if callable(pre_sync):
                        pre_sync()
                with self.server.state_lock:
                    self.server.intake_status = self.server.refresh_callback()
                    self._sync_server_workspace()
                    payload = (
                        self.server.dashboard_state()
                        if since_version is None
                        else self.server.dashboard_state(since_version=since_version)
                    )
                    self._json(200, payload)
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
                    with self.server.state_lock:
                        self._sync_server_workspace()
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
    daemon_threads = True
    request_queue_size = 64

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
        auto_doc_sync: Callable[[], dict | None] | None = None,
        auto_transcript_sync: Callable[[], dict | None] | None = None,
        pre_transcript_discover: Callable[[], None] | None = None,
        sidecar_internal_secret: str | None = None,
        activity_callback: Callable[[], None] | None = None,
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
        self.auto_doc_sync = auto_doc_sync
        self.auto_transcript_sync = auto_transcript_sync
        self.pre_transcript_discover = pre_transcript_discover
        self.sidecar_internal_secret = sidecar_internal_secret
        self.activity_callback = activity_callback
        self.project_scan_status = {
            'enabled': rescan_callback is not None,
            'last_checked_at': (datetime.now(timezone.utc).isoformat() if (rescan_callback is not None and not sample_mode) else None),
        }
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
        self._workspace_signature = None
        if not self.sample_mode and self.workspace_root and self.dashboard_project_path:
            ws = self.active_workspace()
            if ws is not None and ws.exists():
                self._workspace_signature = ws.state_stat_signature()
                if self.derived_context is None:
                    from .onboarding import load_workspace_derived_context
                    self.derived_context = load_workspace_derived_context(ws)
        self.investigation_cache = {}
        self.hint_cache = AsyncHintCache()
        self.query_stats = {'total': 0, 'cache_hits': 0, 'questions': {}, 'recent': []}
        self._cached_base_state_key = None
        self._cached_base_state = None
        self._latest_state_snapshot = None
        self._cached_revision_stamp = None
        self._cached_revision_hex = None
        self._event_dict_cache: dict[tuple[int, int, int], tuple[str, int, dict]] = {}
        self._cached_derived_current: bool | None = None
        self._last_derived_check_mono: float = 0.0
        super().__init__(server_address, _DashboardHandler)

    def pre_sync_discovery(self) -> None:
        discover_fn = getattr(self, "pre_transcript_discover", None)
        if not self.sample_mode and callable(discover_fn):
            try:
                discover_fn()
            except (OSError, ValueError):
                pass

    def _session_members(self) -> dict[str, str]:
        if self.intake_status.get('enabled') and self.intake_status.get('thread_id') and self.intake_status.get('member_id'):
            return {self.intake_status['thread_id']: self.intake_status['member_id']}
        return {}

    def active_workspace(self):
        if self.sample_mode or not self.workspace_root or not self.dashboard_project_path:
            return None
        from .project_workspace import ProjectWorkspace
        try:
            return ProjectWorkspace(self.workspace_root, self.dashboard_project_path)
        except (OSError, ValueError):
            return None

    def activate_project_workspace(self, target_root: str | Path, *, workspace_root: str | Path | None = None) -> dict:
        """Dynamically switch this dashboard server to a new local project workspace."""
        with self.state_lock:
            if self.sample_mode:
                raise PermissionError("sample mode is read-only")
            if self.agent_inbox:
                raise PermissionError("cannot switch bound team agent server workspace")
            resolved = parse_workspace_uri(target_root)
            if not resolved.is_dir():
                raise ValueError(f"project_path directory not found: {resolved}")
            if self.dashboard_project_path:
                try:
                    if Path(self.dashboard_project_path).expanduser().resolve() == resolved:
                        return self.dashboard_state()
                except OSError:
                    pass
            ws_root = Path(workspace_root).expanduser().resolve() if workspace_root else (resolved / ".project-memory")
            from .cli import _review_callback
            from .local_plugin import cold_start_bootstrap_workspace
            from .onboarding import load_workspace_derived_context
            from .project_refresh import ProjectRescan
            from .project_scan_job import ProjectScanJob
            from .project_workspace import ProjectWorkspace
            from .transcript_watcher import AutoTranscriptIntake, infer_primary_human_member

            ws = ProjectWorkspace(ws_root, resolved)
            fresh_events, _ = cold_start_bootstrap_workspace(ws)
            confirmed, history, fact_reviews = ws.load_review_state() if ws.exists() else ([], [], [])
            self.dashboard_events[:] = fresh_events
            review_cb, confirmed, history, fact_reviews = _review_callback(
                self.dashboard_events,
                ws,
                str(resolved),
                confirmed,
                history,
                fact_reviews,
            )
            rescan_helper = ProjectRescan(ws, self.dashboard_events, extract_docs=True)
            human_member = infer_primary_human_member(self.dashboard_events, history)
            auto_intake = AutoTranscriptIntake(
                resolved,
                ws,
                member_id=human_member,
                initial_events=self.dashboard_events,
                include_tools=True,
            )
            tx_initial = auto_intake.initial_status(self.dashboard_events)
            self.workspace_root = ws_root
            self.dashboard_project_path = str(resolved)
            self.dashboard_confirmed_relations[:] = confirmed
            self.dashboard_review_history[:] = history
            self.dashboard_fact_reviews[:] = fact_reviews
            self.review_callback = review_cb
            self.refresh_callback = lambda: auto_intake.sync(self.dashboard_events, min_interval_sec=0.0)
            self.intake_status = tx_initial
            self.rescan_callback = rescan_helper.refresh
            self.auto_doc_sync = rescan_helper.sync_if_docs_changed
            self.auto_transcript_sync = lambda: auto_intake.sync(self.dashboard_events, min_interval_sec=1.5)
            self.pre_transcript_discover = auto_intake.pre_discover
            self.project_scan_status = {
                "enabled": True,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            }
            self.project_scan_job = ProjectScanJob(ws_root)
            self.derived_context = load_workspace_derived_context(ws)
            self._workspace_signature = ws.state_stat_signature() if ws.exists() else None
            self.investigation_cache.clear()
            self.hint_cache = AsyncHintCache()
            self._cached_base_state_key = None
            self._cached_base_state = None
            self._latest_state_snapshot = None
            self._cached_revision_stamp = None
            self._cached_revision_hex = None
            self._event_dict_cache.clear()
            self._cached_derived_current = None
            self._last_derived_check_mono = 0.0
            self.dashboard_version += 1
            self.last_dashboard_revision = None
            return self.dashboard_state()

    def record_workspace_signature(self) -> None:
        ws = self.active_workspace()
        if ws is not None and ws.exists():
            self._workspace_signature = ws.state_stat_signature()

    def _sync_workspace_if_changed(self, *, force_derived: bool = False) -> bool:
        """Reload persisted workspace state in-place when modified by another process (e.g. compass-mcp)."""
        force_reload = False
        if not self.sample_mode and callable(self.auto_doc_sync):
            try:
                scan_status = self.auto_doc_sync()
            except (OSError, ValueError):
                scan_status = None
            if isinstance(scan_status, dict):
                self.project_scan_status = scan_status
                if scan_status.get("updated"):
                    force_reload = True
        if not self.sample_mode and callable(self.auto_transcript_sync):
            try:
                tx_status = self.auto_transcript_sync()
            except (OSError, ValueError):
                tx_status = None
            if isinstance(tx_status, dict):
                self.intake_status = tx_status
                if tx_status.get("updated"):
                    force_reload = True
        ws = self.active_workspace()
        if ws is None or not ws.exists():
            return force_reload
        sig = ws.state_stat_signature()
        if sig is None:
            return force_reload
        changed = force_reload or (sig != self._workspace_signature)
        if changed:
            fresh_events = ws.load()
            confirmed, history, fact_reviews = ws.load_review_state()
            self.dashboard_events[:] = fresh_events
            self.dashboard_confirmed_relations[:] = confirmed
            self.dashboard_review_history[:] = history
            self.dashboard_fact_reviews[:] = fact_reviews
            sync_cb = getattr(self.review_callback, "sync_from_disk", None)
            if callable(sync_cb):
                sync_cb(confirmed, history, fact_reviews)
            self._workspace_signature = sig
        if force_derived or changed:
            from .onboarding import load_workspace_derived_context
            loaded_ctx = load_workspace_derived_context(ws)
            if loaded_ctx is not None:
                self.derived_context = loaded_ctx
        return changed

    def dashboard_state(self, *, since_version: int | None = None) -> dict:
        with self.state_lock:
            self._sync_workspace_if_changed()
            revision = self.state_revision()
            if self.last_dashboard_revision is not None and revision != self.last_dashboard_revision:
                self.dashboard_version += 1
            self.last_dashboard_revision = revision
            intake_payload = dict(self.intake_status)
            intake_payload['refreshable'] = self.refresh_callback is not None
            if (
                since_version is not None
                and since_version == self.dashboard_version
                and self._latest_state_snapshot is not None
            ):
                hints, hint_gen = self.hint_cache.get_or_schedule(
                    revision,
                    self._latest_state_snapshot,
                    sample_mode=self.sample_mode,
                )
                return {
                    'unchanged': True,
                    'state_version': self.dashboard_version,
                    'intake': intake_payload,
                    'project_scan': dict(self.project_scan_status),
                    'extraction': self.extraction_jobs.status() if self.extraction_jobs else {'enabled': False},
                    'agent_hints': hints,
                    'hint_generation': hint_gen,
                }
            session_members = self._session_members()
            base_key = (
                revision,
                self.dashboard_project_path,
                id(self.derived_context),
                tuple(sorted(session_members.items())),
            )
            if base_key == self._cached_base_state_key and self._cached_base_state is not None:
                result = dict(self._cached_base_state)
                if isinstance(result.get('project'), dict):
                    result['project'] = dict(result['project'])
                if self.derived_context is not None and self.dashboard_project_path and isinstance(result.get('derived_context'), dict):
                    source_path = Path(self.dashboard_project_path).resolve() / self.derived_context.source_ref
                    result['derived_context'] = dict(result['derived_context'])
                    result['derived_context']['current'] = self.derived_context.source_current(source_path)
            else:
                result = build_dashboard_state(
                    self.dashboard_events,
                    self.dashboard_project_path,
                    self.dashboard_confirmed_relations,
                    self.dashboard_review_history,
                    self.dashboard_fact_reviews,
                    session_members=session_members,
                    derived_context=self.derived_context,
                )
                result['priority_dispatches'] = extract_priority_dispatches(self.dashboard_events)
                result['team_templates'] = list_team_templates()
                if self.reason_preview:
                    result['reason_preview'] = self.reason_preview.project(self.dashboard_events)
                if self.sample_mode:
                    demo_title = next(
                        (str((ev.metadata or {}).get("demo_title") or "").strip() for ev in self.dashboard_events if (ev.metadata or {}).get("demo_title")),
                        "",
                    )
                    result['project']['name'] = demo_title or 'Sample project'
                self._cached_base_state_key = base_key
                self._cached_base_state = dict(result)

            result['intake'] = intake_payload
            result['sample_mode'] = self.sample_mode
            result['project_scan'] = dict(self.project_scan_status)
            result['state_version'] = self.dashboard_version
            result['extraction'] = self.extraction_jobs.status() if self.extraction_jobs else {'enabled': False}
            result['agent_api'] = self.agent_inbox.public_status() if self.agent_inbox else {'enabled': False}
            from .project_workspace import ProjectWorkspace
            result['projects'] = [] if self.sample_mode else (ProjectWorkspace.list_registered(self.workspace_root) if self.workspace_root else [])
            result['investigation_stats'] = self.query_statistics()
            result['llm_status'] = public_llm_status()
            hints, hint_gen = self.hint_cache.get_or_schedule(
                revision,
                result,
                sample_mode=self.sample_mode,
            )
            result['agent_hints'] = hints
            result['hint_generation'] = hint_gen
            self._latest_state_snapshot = result
            return result

    def active_project_id(self) -> str | None:
        if not self.dashboard_project_path:
            return None
        from hashlib import sha1
        return sha1(str(Path(self.dashboard_project_path).resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    def _load_saved_project(self, project_id: str):
        if self.sample_mode:
            raise ValueError("sample mode does not expose saved projects")
        from .onboarding import load_workspace_derived_context
        from .project_workspace import ProjectWorkspace
        projects = ProjectWorkspace.list_registered(self.workspace_root) if self.workspace_root else []
        entry = next((item for item in projects if item["project_id"] == project_id), None)
        if entry is None:
            raise ValueError("project not found")
        workspace = ProjectWorkspace(self.workspace_root, entry["project_path"])
        events = workspace.load()
        confirmed, history, reviews = workspace.load_review_state()
        derived_ctx = load_workspace_derived_context(workspace)
        return entry, projects, events, confirmed, history, reviews, derived_ctx

    def dashboard_state_for(self, project_id: str) -> dict:
        entry, projects, events, confirmed, history, reviews, derived_ctx = self._load_saved_project(project_id)
        payload = build_dashboard_state(
            events,
            entry["project_path"],
            confirmed,
            history,
            reviews,
            derived_context=derived_ctx,
        )
        payload["project"]["read_only"] = True
        payload["projects"] = projects
        return payload

    def investigate_for(self, project_id: str, question: str) -> dict:
        try:
            _, _, events, confirmed, _, reviews, derived_ctx = self._load_saved_project(project_id)
        except ValueError as exc:
            raise LookupError(str(exc)) from exc
        answer = investigate(events, question, reviews, list(confirmed), derived_context=derived_ctx).to_dict()
        answer["memory"] = {"enabled": False}
        answer["sample_mode"] = False
        answer["cache"] = {"hit": False, "state_revision": ""}
        llm_info = public_llm_status()
        answer["llm_status"] = llm_info
        if llm_info.get("enabled"):
            summary = synthesize_investigation_summary(question, answer)
            if summary:
                answer["semantic_summary"] = summary
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
        derived_current = self._cached_derived_current
        if self.derived_context is not None and self.dashboard_project_path:
            now_mono = time.monotonic()
            if derived_current is None or (now_mono - self._last_derived_check_mono) >= 5.0:
                derived_current = self.derived_context.source_current(
                    Path(self.dashboard_project_path).resolve() / self.derived_context.source_ref
                )
                self._cached_derived_current = derived_current
                self._last_derived_check_mono = now_mono
        else:
            derived_current = None
        stamp = (
            tuple(
                (id(ev), len(ev.metadata), len(ev.metadata.get('facts') or ()) if isinstance(ev.metadata, dict) else 0)
                for ev in self.dashboard_events
            ),
            tuple(
                (r.get('fact_id'), r.get('action'), r.get('observed_at'), r.get('reviewer'))
                for r in self.dashboard_fact_reviews
            ),
            len(self.dashboard_review_history),
            repr(self.dashboard_review_history[-1]) if self.dashboard_review_history else '',
            tuple(id(rel) for rel in self.dashboard_confirmed_relations),
            self.reason_preview.revision if self.reason_preview else None,
            derived_current,
        )
        if stamp == self._cached_revision_stamp and self._cached_revision_hex is not None:
            return self._cached_revision_hex
        if len(self._event_dict_cache) > 8192:
            self._event_dict_cache.clear()
        event_dicts = []
        for event in self.dashboard_events:
            ev_key = (
                id(event),
                len(event.metadata),
                len(event.metadata.get('facts') or ()) if isinstance(event.metadata, dict) else 0,
            )
            cached_entry = self._event_dict_cache.get(ev_key)
            if cached_entry is not None and cached_entry[0] == event.id and cached_entry[1] == len(event.content):
                event_dicts.append(cached_entry[2])
            else:
                encoded = event.to_dict()
                self._event_dict_cache[ev_key] = (event.id, len(event.content), encoded)
                event_dicts.append(encoded)
        value={'events': event_dicts,
            'reviews': self.dashboard_fact_reviews, 'history': self.dashboard_review_history,
            'relations': [relation.to_dict() for relation in self.dashboard_confirmed_relations]}
        if self.reason_preview:value['reason_preview']=self.reason_preview.revision
        if derived_current is not None:value['source_current']=derived_current
        digest = hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        self._cached_revision_stamp = stamp
        self._cached_revision_hex = digest
        return digest

    def investigate(self, question: str, current_member: str | None = None) -> dict:
        with self.state_lock:
            revision = self.state_revision()
            self.query_stats['total'] += 1
            self.query_stats['questions'][question] = self.query_stats['questions'].get(question, 0) + 1
            active_profile = "local" if self.sample_mode else str(public_llm_status().get("active_profile") or "local")
            cache_key = (revision, current_member or "", active_profile, question)
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
            llm_info = {"enabled": False, "mode": "local", "model": "", "provider_label": "本地检索"} if self.sample_mode else public_llm_status()
            answer['memory'] = {'enabled': False}
            answer['sample_mode'] = self.sample_mode
            answer['llm_status'] = llm_info
            answer['cache'] = {'hit': False, 'state_revision': revision}

        if llm_info.get("enabled") and not self.sample_mode:
            summary = synthesize_investigation_summary(question, answer)
            if summary:
                answer["semantic_summary"] = summary

        with self.state_lock:
            if revision == self.state_revision():
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
    auto_doc_sync: Callable[[], dict | None] | None = None,
    auto_transcript_sync: Callable[[], dict | None] | None = None,
    pre_transcript_discover: Callable[[], None] | None = None,
    sidecar_internal_secret: str | None = None,
    activity_callback: Callable[[], None] | None = None,
) -> DashboardHTTPServer:
    return DashboardHTTPServer(
        (host, port),
        events,
        project_path,
        confirmed_relations,
        review_history,
        fact_reviews,
        review_callback,
        refresh_callback,
        intake_status,
        sample_mode,
        rescan_callback,
        extraction_jobs,
        agent_inbox,
        reason_preview,
        workspace_root,
        project_scan_job,
        derived_context,
        auto_doc_sync=auto_doc_sync,
        auto_transcript_sync=auto_transcript_sync,
        pre_transcript_discover=pre_transcript_discover,
        sidecar_internal_secret=sidecar_internal_secret,
        activity_callback=activity_callback,
    )


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
    auto_doc_sync: Callable[[], dict | None] | None = None,
    open_browser: bool = False,
) -> None:
    server = create_dashboard_server(events, host, port, project_path, confirmed_relations, review_history, fact_reviews, review_callback, refresh_callback, intake_status, sample_mode, rescan_callback, extraction_jobs, agent_inbox, reason_preview, workspace_root, project_scan_job, derived_context, auto_doc_sync=auto_doc_sync)
    url = f"http://{host}:{server.server_address[1]}/"
    print(url, flush=True)
    browser_timer = None
    if open_browser and os.environ.get("COMPASS_NO_BROWSER", "").strip() != "1":
        def _open() -> None:
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass
        browser_timer = Timer(0.25, _open)
        browser_timer.daemon = True
        browser_timer.start()
    try:
        if extraction_jobs:
            extraction_jobs.start_scheduler()
        server.serve_forever()
    finally:
        if browser_timer is not None:
            browser_timer.cancel()
        server.server_close()
