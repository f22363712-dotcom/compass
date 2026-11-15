from __future__ import annotations

from pathlib import Path
import tempfile

from .models import EvidenceEvent
from .native_codex import NativeCodexIntake
from .project_workspace import ProjectWorkspace


class CodexPluginBridge:
    """Read one real Codex rollout and submit its public messages through a plugin adapter."""

    def __init__(self, adapter, sessions_root, project_path, thread_id: str, member_id: str):
        self.adapter = adapter
        self.sessions_root = Path(sessions_root).expanduser().resolve(strict=True)
        self.project_path = Path(project_path).expanduser().resolve(strict=True)
        self.thread_id = thread_id
        self.member_id = member_id.strip()
        if not self.member_id or self.adapter.context.project_path != str(self.project_path):
            raise ValueError("Codex plugin context does not match the project")
        if self.adapter.context.session_id != thread_id or self.adapter.context.member_id != self.member_id:
            raise ValueError("Codex plugin context does not match the session")
        self._reader_tmp = tempfile.TemporaryDirectory(prefix="project-compass-plugin-reader-")
        self._reader_workspace = ProjectWorkspace(self._reader_tmp.name, self.project_path)
        self._reader_workspace.save([])
        self._reader_events = []
        self._reader = NativeCodexIntake(self.sessions_root, self.project_path, self.thread_id, self.member_id)
        self._submitted_ids: set[str] = set()

    def sync(self) -> dict:
        # shortcut: each tick rereads the selected bounded rollout; upgrade to byte-offset cursors when long-lived sessions or multi-project watchers make this I/O visible.
        reader_status = self._reader.sync(self._reader_workspace, self._reader_events)
        submitted = 0
        results = []
        for event in self._reader_events:
            if event.kind not in {"user_message", "assistant_message"}:
                continue
            if event.id in self._submitted_ids:
                continue
            author = self.member_id if event.kind == "user_message" else self.adapter.context.agent
            plugin_event = EvidenceEvent(
                id=f"codex-plugin-{event.id}", session_id=event.session_id, author=author,
                kind=event.kind, content=event.content, observed_at=event.observed_at,
                metadata=dict(event.metadata),
            )
            result = self.adapter.append_event(plugin_event)
            submitted += int(result.get("appended", 0))
            self._submitted_ids.add(event.id)
            results.append(result)
        return {"thread_id": self.thread_id, "captured_messages": reader_status.get("captured_messages", 0),
                "submitted": submitted, "results": results, "reader": reader_status}

    def close(self) -> None:
        if self._reader_tmp is not None:
            self._reader_tmp.cleanup()
            self._reader_tmp = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
