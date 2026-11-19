from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
import time

from .doc_fact_intake import record_document_candidates
from .onboarding import build_and_save_workspace_code_index
from .project_scanner import scan_project
from .project_workspace import ProjectWorkspace

DEFAULT_SCAN_TIMEOUT_SECONDS = 120.0


class ProjectScanJob:
    def __init__(self, workspace_root, *, timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self._lock = Lock()
        self._started_monotonic: float | None = None
        self._run_seq = 0
        self._status = {"state": "idle", "stage": "idle", "project_path": None, "error": None}

    def _set_stage(self, run_seq: int, stage: str, **extra) -> None:
        with self._lock:
            if self._run_seq != run_seq:
                return
            self._status.update({"stage": stage, **extra})

    def start(
        self,
        project_path,
        *,
        extract_docs: bool = True,
        with_code_index: bool = True,
    ) -> dict:
        project = Path(project_path).expanduser().resolve(strict=True)
        if not project.is_dir():
            raise ValueError("project_path must be a directory")
        with self._lock:
            now_mono = time.monotonic()
            timed_out = (
                self._status["state"] == "running"
                and self._started_monotonic is not None
                and (now_mono - self._started_monotonic) > self.timeout_seconds
            )
            if self._status["state"] == "running" and not timed_out:
                return dict(self._status)
            self._run_seq += 1
            run_seq = self._run_seq
            self._started_monotonic = now_mono
            self._status = {
                "state": "running",
                "stage": "scanning",
                "project_path": str(project),
                "extract_docs": bool(extract_docs),
                "with_code_index": bool(with_code_index),
                "error": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        Thread(
            target=self._run,
            args=(project, run_seq, bool(extract_docs), bool(with_code_index)),
            daemon=True,
        ).start()
        return self.status()

    def _run(self, project: Path, run_seq: int, extract_docs: bool, with_code_index: bool) -> None:
        warnings: list[str] = []
        doc_candidates_added = 0
        code_index_nodes = 0
        try:
            workspace = ProjectWorkspace(self.workspace_root, project)
            scanned_events = scan_project(project)
            workspace.save(scanned_events, {"source": "web_project_scan"}, complete_scan=True)
            events = workspace.load()

            if extract_docs:
                self._set_stage(run_seq, "extracting_docs", project_id=workspace.project_id)
                try:
                    doc_status = record_document_candidates(events, workspace)
                    doc_candidates_added = int(doc_status.get("new_doc_proposals", 0))
                except Exception as doc_exc:
                    warnings.append(f"文档候选提取已降级跳过: {doc_exc}")

            if with_code_index:
                self._set_stage(run_seq, "indexing_code", project_id=workspace.project_id)
                try:
                    index_payload = build_and_save_workspace_code_index(
                        workspace,
                        strict_syntax=False,
                        max_files=800,
                    )
                    code_index_nodes = len(index_payload.get("nodes") or [])
                    warnings.extend(str(w) for w in (index_payload.get("warnings") or [])[:5])
                except Exception as idx_exc:
                    warnings.append(f"代码结构索引已降级跳过（无结构索引）: {idx_exc}")

            events = workspace.load()
            result = {
                "state": "complete",
                "stage": "complete",
                "project_path": str(project),
                "project_id": workspace.project_id,
                "evidence_count": len(events),
                "doc_candidates_added": doc_candidates_added,
                "code_index_nodes": code_index_nodes,
                "warnings": warnings,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        except Exception as exc:
            result = {
                "state": "failed",
                "stage": "failed",
                "project_path": str(project),
                "error": str(exc),
                "warnings": warnings,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        with self._lock:
            if self._run_seq == run_seq:
                self._started_monotonic = None
                self._status = result

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)
