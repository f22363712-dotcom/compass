from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread
from datetime import datetime, timezone

from .project_scanner import scan_project
from .project_workspace import ProjectWorkspace


class ProjectScanJob:
    def __init__(self, workspace_root):
        self.workspace_root = Path(workspace_root).resolve()
        self._lock = Lock()
        self._status = {"state": "idle", "project_path": None, "error": None}

    def start(self, project_path) -> dict:
        project = Path(project_path).expanduser().resolve(strict=True)
        if not project.is_dir():
            raise ValueError("project_path must be a directory")
        with self._lock:
            if self._status["state"] == "running":
                return dict(self._status)
            self._status = {"state": "running", "project_path": str(project), "error": None, "started_at": datetime.now(timezone.utc).isoformat()}
        Thread(target=self._run, args=(project,), daemon=True).start()
        return self.status()

    def _run(self, project: Path) -> None:
        try:
            workspace = ProjectWorkspace(self.workspace_root, project)
            workspace.save(scan_project(project), {"source": "web_project_scan"}, complete_scan=True)
            events = workspace.load()
            result = {"state": "complete", "project_path": str(project), "project_id": workspace.project_id,
                      "evidence_count": len(events), "completed_at": datetime.now(timezone.utc).isoformat(), "error": None}
        except Exception as exc:
            result = {"state": "failed", "project_path": str(project), "error": str(exc), "completed_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self._status = result

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)
