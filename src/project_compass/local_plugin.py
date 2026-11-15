from __future__ import annotations

import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agent_inbox import AgentInbox
from .dashboard import build_dashboard_state
from .investigator import investigate
from .plugin_protocol import (
    FactProposal,
    ProjectContext,
    StateQuery,
    build_compact_project_context,
    evidence_event_to_protocol_dict,
    validate_protocol_version,
)


class PluginRequestError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


class LocalPluginAdapter:
    """Small MCP-style local adapter over the existing project-bound Agent API."""

    METHODS = {"project.context", "evidence.append", "state.query", "fact.propose"}
    STATE_SCOPES = {"team", "personal", "evidence", "requests", "history"}

    def __init__(self, base_url: str, context: ProjectContext, token: str, *, timeout: float = 5.0, workspace=None):
        if not isinstance(base_url, str) or not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("local plugin adapter requires a loopback HTTP URL")
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
            raise ValueError("invalid plugin credential")
        self.base_url = base_url.rstrip("/")
        self.context = context
        self.token = token
        self.timeout = timeout
        self.workspace = workspace
        self._cached_context: dict | None = None

    def dispatch(self, method: str, params: dict) -> dict:
        if method not in self.METHODS:
            raise ValueError(f"unsupported plugin method: {method}")
        if not isinstance(params, dict):
            raise ValueError("plugin params must be an object")
        if method == "project.context":
            if not params.get("refresh") and self._cached_context is not None:
                return self._cached_context
            try:
                state = self._get("/api/agent/state")
                compact = build_compact_project_context(self.context, state)
            except Exception:
                if self.workspace is not None and hasattr(self.workspace, "compact_context"):
                    compact = self.workspace.compact_context(
                        member_id=self.context.member_id,
                        session_id=self.context.session_id,
                        agent=self.context.agent,
                    )
                else:
                    compact = self.context.to_dict()
            self._cached_context = compact
            return compact
        if method == "evidence.append":
            envelope = params.get("event")
            if not isinstance(envelope, dict):
                raise ValueError("evidence.append requires an event envelope")
            validate_protocol_version(envelope.get("schema_version"))
            project_id = envelope.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("plugin event project mismatch")
            event = envelope.get("event")
            if not isinstance(event, dict):
                raise ValueError("plugin event must be an object")
            result = self._post("/api/agent/events", {"schema_version": 1, "events": [event]})
            self._cached_context = None
            return result
        if method == "state.query":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("state query project mismatch")
            question = params.get("question") or params.get("evidence_id") or params.get("id") or ""
            query = StateQuery(self.context, question, tuple(params.get("scopes", ("team", "personal", "evidence"))))
            unknown = set(query.scopes) - self.STATE_SCOPES
            if unknown:
                raise ValueError("unsupported state query scope")
            response = self._post("/api/agent/query", {"question": query.question})
            if not isinstance(response.get("state"), dict) or not isinstance(response.get("answer"), dict):
                raise PluginRequestError(None, "ProjectCompass plugin returned an invalid query result")
            result = self._project_state(response["state"], query)
            result["answer"] = self._structure_answer(response["answer"], response["state"], query)
            result["investigation_stats"] = response["state"].get("investigation_stats", {})
            return result
        if method == "fact.propose":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("fact proposal project mismatch")
            proposal = dict(params)
            proposal.pop("project_id", None)
            validate_protocol_version(proposal.get("schema_version"))
            proposal["proposals"] = proposal.get("proposals", [])
            result = self._post("/api/agent/proposals", {"schema_version": 1, "proposals": proposal["proposals"]})
            self._cached_context = None
            return result
        raise AssertionError("unreachable")

    def append_event(self, event) -> dict:
        return self.dispatch("evidence.append", {"event": evidence_event_to_protocol_dict(event, self.context)})

    def query_state(self, query: StateQuery) -> dict:
        return self.dispatch("state.query", query.to_payload())

    def propose_fact(self, proposal: FactProposal) -> dict:
        return self.dispatch("fact.propose", proposal.to_payload())

    def _project_state(self, payload: dict, query: StateQuery) -> dict:
        """Return a bounded, member-scoped view for an Agent query."""
        result = {
            "schema_version": query.context.schema_version,
            "project": payload.get("project", {}),
            "state_version": payload.get("state_version"),
            "question": query.question,
            "scopes": list(query.scopes),
        }
        selected_ids: set[str] = set()
        if "team" in query.scopes:
            result["team"] = payload.get("team", {})
            selected_ids.update(result["team"].get("evidence_ids", []))
        if "personal" in query.scopes:
            personal = payload.get("personal", {}).get(query.context.member_id, {"member_id": query.context.member_id, "facts": [], "evidence_ids": []})
            result["personal"] = personal
            selected_ids.update(personal.get("evidence_ids", []))
        if "requests" in query.scopes:
            requests = [item for item in payload.get("evidence_requests", []) if item.get("member_id") == query.context.member_id]
            result["evidence_requests"] = requests
            for item in requests:
                selected_ids.update(item.get("requested_evidence_ids", []))
                selected_ids.update(item.get("new_evidence_ids", []))
        if "history" in query.scopes:
            result["review_history"] = payload.get("review_history", [])
        if "evidence" in query.scopes:
            catalog = payload.get("evidence", [])
            result["evidence"] = [item for item in catalog if not selected_ids or item.get("id") in selected_ids]
            result["candidate_relations"] = [item for item in payload.get("candidate_relations", []) if not selected_ids or item.get("evidence_id") in selected_ids]
            result["confirmed_relations"] = [item for item in payload.get("confirmed_relations", []) if not selected_ids or item.get("evidence_id") in selected_ids]
        return result

    @staticmethod
    def _structure_answer(answer: dict, state: dict, query: StateQuery) -> dict:
        """Expose stable categories so an Agent does not infer meaning from prose."""
        team = state.get("team", {})
        facts = [
            {
                "id": fact.get("id"), "kind": fact.get("kind"),
                "subject_key": fact.get("subject_key"), "value": fact.get("value"),
                "status": fact.get("status"), "evidence_ids": fact.get("evidence_ids", []),
            }
            for fact in team.get("facts", [])
            if fact.get("status") in {"accepted", "conflicted", "proposed"}
        ]
        evidence = {item.get("id"): item for item in state.get("evidence", [])}
        relation_by_evidence = {}
        for relation in state.get("confirmed_relations", []) + state.get("candidate_relations", []):
            relation_by_evidence.setdefault(relation.get("evidence_id"), []).append({
                "fact_id": relation.get("fact_id"), "status": relation.get("status"),
                "basis": relation.get("basis"),
            })
        supporting = []
        for evidence_id in answer.get("evidence_ids", []):
            item = evidence.get(evidence_id, {"id": evidence_id})
            supporting.append({
                "id": evidence_id, "preview": item.get("content_preview"),
                "author": item.get("author"), "observed_at": item.get("observed_at"),
                "relations": relation_by_evidence.get(evidence_id, []),
            })
        gaps = list(answer.get("evidence_gaps", []))
        gaps.extend({"fact_id": request.get("fact_id"), "status": request.get("status"), "note": request.get("note", "")}
                    for request in state.get("evidence_requests", []) if request.get("status") != "ready_for_review")
        return {
            **answer,
            "current_facts": facts,
            "supporting_evidence": supporting,
            "conflicts": answer.get("conflicts", []),
            "evidence_gaps": gaps,
            "chain_of_recall": answer.get("chain_of_recall", []),
            "next": {
                "text": answer.get("next_action", ""),
                "status": answer.get("next_action_status"),
                "basis": answer.get("next_action_basis"),
            },
            "query_scope": list(query.scopes),
            "query_stats": state.get("investigation_stats", {}),
        }

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}

    def _get(self, path: str) -> dict:
        request = Request(self.base_url + path, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            raise PluginRequestError(status, "ProjectCompass plugin request failed") from exc

    def _post(self, path: str, payload: dict) -> dict:
        request = Request(self.base_url + path, data=json.dumps(payload).encode("utf-8"), headers=self._headers(), method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            raise PluginRequestError(status, "ProjectCompass plugin request failed") from exc


class WorkspaceMCPAdapter:
    """Zero-config local adapter backed directly by a bound ProjectWorkspace."""

    METHODS = LocalPluginAdapter.METHODS
    STATE_SCOPES = LocalPluginAdapter.STATE_SCOPES

    def __init__(self, workspace, context: ProjectContext):
        if context.member_id in {"project-documents", "__local_owner__"}:
            raise ValueError("invalid MCP local member_id")
        self.workspace = workspace
        self.context = context
        self._cached_context: dict | None = None
        self._ephemeral_token = secrets.token_urlsafe(32)
        self._client = None
        self._inbox: AgentInbox | None = None

    def _ensure_inbox(self) -> tuple[AgentInbox, object]:
        if not self.workspace.exists():
            self.workspace.save([])
        events = self.workspace.load()
        if self._inbox is None:
            config = {
                "schema_version": 1,
                "project_path": str(self.workspace.project_path),
                "owner_id": "__local_owner__",
                "clients": [
                    {
                        "client_id": f"mcp-{self.context.agent}",
                        "member_id": self.context.member_id,
                        "session_id": self.context.session_id,
                        "agent": self.context.agent,
                        "token": self._ephemeral_token,
                    }
                ],
            }
            self._inbox = AgentInbox(config, self.workspace, events)
            self._client = self._inbox.clients[0]
        else:
            self._inbox.events[:] = events
        return self._inbox, self._client

    def _load_full_state(self) -> tuple[list, dict, list, list]:
        events = self.workspace.load() if self.workspace.exists() else []
        confirmed, history, fact_reviews = self.workspace.load_review_state() if self.workspace.exists() else ([], [], [])
        state = build_dashboard_state(
            events,
            project_path=str(self.workspace.project_path),
            confirmed_relations=confirmed,
            review_history=history,
            fact_reviews=fact_reviews,
        )
        return events, state, confirmed, fact_reviews

    def dispatch(self, method: str, params: dict) -> dict:
        if method not in self.METHODS:
            raise ValueError(f"unsupported plugin method: {method}")
        if not isinstance(params, dict):
            raise ValueError("plugin params must be an object")
        if method == "project.context":
            if not params.get("refresh") and self._cached_context is not None:
                return self._cached_context
            compact = self.workspace.compact_context(
                member_id=self.context.member_id,
                session_id=self.context.session_id,
                agent=self.context.agent,
            )
            self._cached_context = compact
            return compact
        if method == "evidence.append":
            envelope = params.get("event")
            if not isinstance(envelope, dict):
                raise ValueError("evidence.append requires an event envelope")
            validate_protocol_version(envelope.get("schema_version"))
            project_id = envelope.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("plugin event project mismatch")
            event = envelope.get("event")
            if not isinstance(event, dict):
                raise ValueError("plugin event must be an object")
            inbox, client = self._ensure_inbox()
            result = inbox.append_events(client, {"schema_version": 1, "events": [event]})
            self._cached_context = None
            return result
        if method == "state.query":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("state query project mismatch")
            question = params.get("question") or params.get("evidence_id") or params.get("id") or ""
            query = StateQuery(self.context, question, tuple(params.get("scopes", ("team", "personal", "evidence"))))
            unknown = set(query.scopes) - self.STATE_SCOPES
            if unknown:
                raise ValueError("unsupported state query scope")
            events, state, confirmed, fact_reviews = self._load_full_state()
            answer = investigate(
                events,
                query.question,
                confirmed_relations=confirmed,
                fact_reviews=fact_reviews,
                current_member=self.context.member_id,
            )
            answer_dict = answer.to_dict() if hasattr(answer, "to_dict") else answer
            result = LocalPluginAdapter._project_state(self, state, query)
            result["answer"] = LocalPluginAdapter._structure_answer(answer_dict, state, query)
            result["investigation_stats"] = state.get("investigation_stats", {})
            return result
        if method == "fact.propose":
            project_id = params.get("project_id") or self.context.project_id
            if project_id != self.context.project_id:
                raise ValueError("fact proposal project mismatch")
            validate_protocol_version(params.get("schema_version"))
            proposals = params.get("proposals", [])
            inbox, client = self._ensure_inbox()
            result = inbox.propose(client, {"schema_version": 1, "proposals": proposals})
            self._cached_context = None
            return result
        raise AssertionError("unreachable")

    def append_event(self, event) -> dict:
        return self.dispatch("evidence.append", {"event": evidence_event_to_protocol_dict(event, self.context)})

    def query_state(self, query: StateQuery) -> dict:
        return self.dispatch("state.query", query.to_payload())

    def propose_fact(self, proposal: FactProposal) -> dict:
        return self.dispatch("fact.propose", proposal.to_payload())
