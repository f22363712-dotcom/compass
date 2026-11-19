from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence_filters import atomic_write_text, interprocess_file_lock, parse_iso_timestamp, path_lock
from .evidence_store import EvidenceStore
from .models import EvidenceEvent, EvidenceRelation


class ProjectWorkspace:
    """Local registry for projects scanned by ProjectCompass."""

    def __init__(self, workspace_root: str | Path, project_path: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_path = Path(project_path).expanduser().resolve(strict=True)
        if not self.project_path.is_dir():
            raise NotADirectoryError(f"project path is not a directory: {self.project_path}")
        self.project_id = hashlib.sha1(str(self.project_path).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    @property
    def state_path(self) -> Path:
        return self.workspace_root / "projects" / self.project_id / "state.json"

    @property
    def registry_path(self) -> Path:
        return self.workspace_root / "registry.json"

    @classmethod
    def list_registered(cls, workspace_root: str | Path) -> list[dict[str, Any]]:
        """Return the persisted project discovery index in stable order."""
        registry_path = Path(workspace_root).expanduser().resolve() / "registry.json"
        with path_lock(registry_path):
            if not registry_path.exists():
                return []
            try:
                value = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid ProjectCompass registry: {registry_path}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"invalid ProjectCompass registry: {registry_path}")
            projects: list[dict[str, Any]] = []
            for project_id, item in value.items():
                if not isinstance(item, dict):
                    raise ValueError(f"invalid registry entry: {project_id}")
                required = {"project_id", "project_path", "project_name", "state_path", "saved_at"}
                if not required.issubset(item):
                    raise ValueError(f"invalid registry entry: {project_id}")
                if item["project_id"] != project_id:
                    raise ValueError(f"registry id mismatch: {project_id}")
                if not Path(item["project_path"]).is_dir() or not Path(item["state_path"]).is_file():
                    continue
                projects.append({key: item[key] for key in required})
            return sorted(projects, key=lambda item: (str(item["project_name"]).casefold(), str(item["project_id"])))

    def exists(self) -> bool:
        return self.state_path.is_file()

    def save(self, events: list[EvidenceEvent], metadata: dict[str, Any] | None = None, *, complete_scan: bool = False) -> Path:
        saved_at = datetime.now(timezone.utc).isoformat()
        incoming = EvidenceStore(events).list()
        # Acquire registry_path before state_path everywhere to keep multi-lock ordering acyclic.
        with interprocess_file_lock(self.registry_path), interprocess_file_lock(self.state_path):
            previous = self._read_state() if self.exists() else None
            merged = EvidenceStore(self.load() if previous is not None else [])
            known = {event.id: event for event in merged.list()}
            current_files = {}
            for event in merged.list():
                if event.kind == "file_snapshot":
                    current_files[event.metadata.get("source_ref")] = event.id
                elif event.kind == "file_observation":
                    current_files[event.metadata.get("source_ref")] = event.metadata.get("source_id")
                elif event.kind == 'file_unavailable':
                    current_files[event.metadata.get('source_ref')] = None
            for event in incoming:
                existing = known.get(event.id)
                if existing is not None:
                    if (existing.content, existing.kind, existing.author, existing.session_id) != (event.content, event.kind, event.author, event.session_id):
                        raise ValueError(f"evidence id already exists with different content: {event.id}")
                    source_ref = event.metadata.get("source_ref")
                    if event.kind == "file_snapshot" and current_files.get(source_ref) != event.id:
                        digest = hashlib.sha256(f"{saved_at}:{source_ref}:{event.id}".encode()).hexdigest()[:24]
                        merged.append(EvidenceEvent(f"observation-{digest}", "project-scan", "scanner", "file_observation", "",
                            parse_iso_timestamp(saved_at), {"source_ref": source_ref, "source_id": event.id}))
                        current_files[source_ref] = event.id
                    continue
                merged.append(event)
                known[event.id] = event
                if event.kind == "file_snapshot":
                    current_files[event.metadata.get("source_ref")] = event.id
            if complete_scan:
                present = {event.metadata.get('source_ref') for event in incoming if event.kind == 'file_snapshot'}
                for source_ref, source_id in current_files.items():
                    if source_id and source_ref not in present:
                        digest = hashlib.sha256(f'{saved_at}:{source_ref}:unavailable'.encode()).hexdigest()[:24]
                        merged.append(EvidenceEvent(f'unavailable-{digest}', 'project-scan', 'scanner', 'file_unavailable',
                            f'File not available in the latest complete scan: {source_ref}', parse_iso_timestamp(saved_at),
                            {'source_ref': source_ref, 'source_id': source_id, 'reason': 'not_present_in_complete_scan'}))
            record = {
                "schema_version": 1,
                "project_id": self.project_id,
                "project_path": str(self.project_path),
                "saved_at": saved_at,
                "metadata": dict(metadata or {}),
                "events": [event.to_dict() for event in merged.list()],
            }
            if previous is not None:
                record["confirmed_relations"] = list(previous.get("confirmed_relations", []))
                record["review_history"] = list(previous.get("review_history", []))
                record["fact_reviews"] = list(previous.get("fact_reviews", []))
            # Serialize the canonical state before publishing the registry so malformed
            # payloads never leave registry.json ahead of persisted state.
            state_json = json.dumps(record, ensure_ascii=False, indent=2)
            registry = self._read_registry()
            registry[self.project_id] = {
                "project_id": self.project_id,
                "project_path": str(self.project_path),
                "project_name": self.project_path.name or str(self.project_path),
                "state_path": str(self.state_path),
                "saved_at": saved_at,
            }
            atomic_write_text(self.registry_path, json.dumps(registry, ensure_ascii=False, indent=2))
            self._write_state(state_json)
            return self.state_path

    def load(self) -> list[EvidenceEvent]:
        with path_lock(self.state_path):
            record = self._read_state()
            return EvidenceStore([EvidenceEvent.from_dict(value) for value in record["events"]]).list()

    def metadata(self) -> dict[str, Any]:
        with path_lock(self.state_path):
            record = self._read_state()
            return {
                "project_id": record.get("project_id"),
                "project_path": record.get("project_path"),
                "project_name": self.project_path.name or str(self.project_path),
                "saved_at": record.get("saved_at"),
            }

    @staticmethod
    def _merge_unique_dicts(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[Any] = set()
        for item in [*(existing or []), *(incoming or [])]:
            copy_item = dict(item)
            key = key_fn(copy_item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(copy_item)
        return merged

    def state_stat_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.state_path.stat()
        except OSError:
            return None
        return (int(stat.st_mtime_ns), int(stat.st_size))

    def merge_and_save_review_state(
        self,
        confirmed_relations: list[EvidenceRelation],
        review_history: list[dict[str, Any]],
        fact_reviews: list[dict[str, Any]] | None = None,
    ) -> tuple[list[EvidenceRelation], list[dict[str, Any]], list[dict[str, Any]]]:
        """Merge append-only review state with concurrent disk updates and persist atomically."""
        with interprocess_file_lock(self.state_path):
            record = self._read_state()
            existing_rel = [EvidenceRelation.from_dict(value) for value in record.get("confirmed_relations", [])]
            merged_rel: list[EvidenceRelation] = []
            seen_rel_ids: set[str] = set()
            for rel in [*existing_rel, *confirmed_relations]:
                if rel.id in seen_rel_ids:
                    continue
                seen_rel_ids.add(rel.id)
                merged_rel.append(rel)

            merged_history = self._merge_unique_dicts(
                list(record.get("review_history", [])),
                [dict(item) for item in review_history],
                lambda item: (
                    str(item.get("action") or ""),
                    str(item.get("fact_id") or ""),
                    str(item.get("relation_id") or ""),
                    str(item.get("reviewer") or ""),
                    str(item.get("observed_at") or ""),
                ),
            )
            merged_fact_reviews = self._merge_unique_dicts(
                list(record.get("fact_reviews", [])),
                [dict(item) for item in (fact_reviews or [])],
                lambda item: (
                    str(item.get("fact_id") or ""),
                    str(item.get("action") or ""),
                    str(item.get("reviewer") or ""),
                    str(item.get("observed_at") or ""),
                ),
            )
            record["confirmed_relations"] = [relation.to_dict() for relation in merged_rel]
            record["review_history"] = merged_history
            record["fact_reviews"] = merged_fact_reviews
            self._write_state(record)
            return merged_rel, merged_history, merged_fact_reviews

    def save_review_state(
        self,
        confirmed_relations: list[EvidenceRelation],
        review_history: list[dict[str, Any]],
        fact_reviews: list[dict[str, Any]] | None = None,
        *,
        merge_existing: bool = False,
    ) -> Path:
        if merge_existing:
            self.merge_and_save_review_state(confirmed_relations, review_history, fact_reviews)
            return self.state_path
        with interprocess_file_lock(self.state_path):
            record = self._read_state()
            record["confirmed_relations"] = [relation.to_dict() for relation in confirmed_relations]
            record["review_history"] = [dict(item) for item in review_history]
            record["fact_reviews"] = [dict(item) for item in (fact_reviews or [])]
            self._write_state(record)
            return self.state_path

    def load_review_state(self) -> tuple[list[EvidenceRelation], list[dict[str, Any]], list[dict[str, Any]]]:
        with path_lock(self.state_path):
            record = self._read_state()
            raw_relations = record.get("confirmed_relations", [])
            raw_history = record.get("review_history", [])
            raw_fact_reviews = record.get("fact_reviews", [])
            if not isinstance(raw_relations, list) or not isinstance(raw_history, list) or not isinstance(raw_fact_reviews, list):
                raise ValueError(f"invalid ProjectCompass review state: {self.state_path}")
            return (
                [EvidenceRelation.from_dict(value) for value in raw_relations],
                [dict(item) for item in raw_history],
                [dict(item) for item in raw_fact_reviews],
            )

    def _read_state(self) -> dict[str, Any]:
        if not self.exists():
            raise FileNotFoundError(
                f"no saved ProjectCompass state for {self.project_path}; run --scan first"
            )
        record = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("events"), list):
            raise ValueError(f"invalid ProjectCompass state: {self.state_path}")
        if record.get("project_id") != self.project_id:
            raise ValueError(f"state belongs to a different project: {self.state_path}")
        return record

    def _write_state(self, record: dict[str, Any] | str) -> None:
        payload = record if isinstance(record, str) else json.dumps(record, ensure_ascii=False, indent=2)
        atomic_write_text(self.state_path, payload)

    def _read_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {}
        value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"invalid ProjectCompass registry: {self.registry_path}")
        return value

    def compact_context(self, member_id: str, session_id: str, agent: str) -> dict[str, Any]:
        """Produce an Inline & Spill compact context from local persisted state."""
        from .dashboard import build_dashboard_state
        from .plugin_protocol import ProjectContext, build_compact_project_context

        events = self.load() if self.exists() else []
        confirmed, history, fact_reviews = self.load_review_state() if self.exists() else ([], [], [])
        state = build_dashboard_state(
            events,
            project_path=str(self.project_path),
            confirmed_relations=confirmed,
            review_history=history,
            fact_reviews=fact_reviews,
        )
        ctx = ProjectContext.for_project(self.project_path, member_id, session_id, agent)
        return build_compact_project_context(ctx, state, events)

