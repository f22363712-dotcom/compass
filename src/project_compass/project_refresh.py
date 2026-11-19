from datetime import datetime, timezone
import time

from .candidate_extraction import current_file_snapshots
from .doc_fact_intake import record_document_candidates
from .project_scanner import scan_project, watched_docs_signature


class ProjectRescan:
    """Explicit model-free scan; caller serializes canonical workspace changes."""

    def __init__(self, workspace, events, *, extract_docs: bool = False):
        self.workspace = workspace
        self.events = events
        self.extract_docs = bool(extract_docs)
        self._last_doc_sig = (
            watched_docs_signature(workspace.project_path)
            if workspace and getattr(workspace, "project_path", None)
            else None
        )
        self._last_sig_check_mono = 0.0

    def refresh(self):
        before = {event.metadata.get('source_ref'): event.id for event in current_file_snapshots(self.events)}
        previous_ids = {event.id for event in self.events}
        scanned = scan_project(self.workspace.project_path)
        self.workspace.save(scanned, {'source': 'complete_rescan'}, complete_scan=True)
        self.events[:] = self.workspace.load()
        new_doc_proposals = 0
        if self.extract_docs:
            doc_res = record_document_candidates(self.events, self.workspace)
            new_doc_proposals = int(doc_res.get('new_doc_proposals', 0))
        self._last_doc_sig = watched_docs_signature(self.workspace.project_path)
        self._last_sig_check_mono = time.monotonic()
        after = {event.metadata.get('source_ref'): event.id for event in current_file_snapshots(self.events)}
        payload = {
            'enabled': True,
            'last_checked_at': datetime.now(timezone.utc).isoformat(),
            'updated': previous_ids != {event.id for event in self.events},
            'file_count': len(after),
            'changed_files': sum(before[p] != after[p] for p in before.keys() & after.keys()),
            'new_files': len(after.keys() - before.keys()),
            'unavailable_files': len(before.keys() - after.keys()),
            'scope': 'configured document paths and Git; no model call; unavailability is not proof of deletion',
        }
        if self.extract_docs:
            payload['new_doc_proposals'] = new_doc_proposals
        return payload

    def sync_if_docs_changed(self, min_interval_sec: float = 1.5):
        """Incrementally rescan and extract docs when watched markdown stats change."""
        project_root = getattr(self.workspace, "project_path", None) if self.workspace else None
        if not project_root:
            return None
        now_mono = time.monotonic()
        if self._last_sig_check_mono and (now_mono - self._last_sig_check_mono) < min_interval_sec:
            return None
        self._last_sig_check_mono = now_mono
        cur_sig = watched_docs_signature(project_root)
        if cur_sig is None or cur_sig == self._last_doc_sig:
            return None
        try:
            return self.refresh()
        except OSError:
            return None
