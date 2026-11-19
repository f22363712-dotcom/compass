from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .codex_adapter import CodexAdapter
from .evidence_filters import parse_iso_timestamp
from .models import EvidenceEvent


_ROOT_DOC_NAMES = (
    "README.md",
    "AGENTS.md",
    "CONTEXT.md",
    "HANDOFF.md",
    "DECISIONS.md",
    "PROGRESS.md",
)
_SUBDIR_DOC_DIRS = ("docs", "docs/reviews", "docs/plans", "docs/adr")


def _id(kind: str, value: str) -> str:
    return f"scan-{kind}-{hashlib.sha1(value.encode(), usedforsecurity=False).hexdigest()[:12]}"


def _candidate_doc_paths(base: Path) -> list[Path]:
    """Return bounded, deterministic repository markdown paths without crawling asset dirs."""
    paths = [base / name for name in _ROOT_DOC_NAMES]
    for relative in _SUBDIR_DOC_DIRS:
        directory = base / relative
        if directory.is_dir() and directory.resolve().is_relative_to(base):
            paths.extend(directory.glob("*.md"))
    resolved_files: list[Path] = []
    for path in sorted(set(paths)):
        if not path.is_file() or path.name.startswith(".env"):
            continue
        try:
            if not path.resolve().is_relative_to(base):
                continue
        except OSError:
            continue
        resolved_files.append(path)
    return resolved_files


def watched_docs_signature(root: str | Path) -> tuple[tuple[str, int, int], ...] | None:
    """Return lightweight stat signature of watched markdown docs for hot-reload checks."""
    try:
        base = Path(root).resolve(strict=True)
    except OSError:
        return None
    if not base.is_dir():
        return None
    entries: list[tuple[str, int, int]] = []
    for path in _candidate_doc_paths(base):
        try:
            st = path.stat()
        except OSError:
            continue
        rel = path.relative_to(base).as_posix()
        entries.append((rel, int(st.st_size), int(st.st_mtime_ns)))
    entries.sort(key=lambda item: item[0])
    return tuple(entries)


def scan_project(root: str | Path, codex_paths: list[str | Path] | None = None, max_commits: int = 15) -> list[EvidenceEvent]:
    base = Path(root).resolve(strict=True)
    if not base.is_dir():
        raise NotADirectoryError(f"project path is not a directory: {base}")
    events: list[EvidenceEvent] = []
    now = datetime.now(timezone.utc)
    for path in _candidate_doc_paths(base):
        raw = path.read_bytes()
        content = raw.decode("utf-8", errors="replace")
        content_hash = hashlib.sha256(raw).hexdigest()
        source_ref = str(path.relative_to(base))
        events.append(EvidenceEvent(
            _id("file", source_ref + ":" + content_hash),
            "project-scan", "scanner", "file_snapshot", content, now,
            {"source_ref": source_ref, "content_hash": content_hash,
             "source_modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()},
        ))
    for path in codex_paths or []:
        events.extend(CodexAdapter.from_jsonl(path))
    try:
        repository = subprocess.run(["git", "-C", str(base), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10, check=False)
        if repository.returncode != 0:
            return events
        # Filter a subproject before the count limit; keep the original root
        # history semantics, including merges and empty release checkpoints.
        scope = [] if Path(repository.stdout.rstrip('\r\n')).resolve() == base else ["--", "."]
        # A merge with same-second commits can otherwise expose Git's tie-breaker
        # order, making the project trace change between identical scans.
        output = subprocess.run(["git", "-C", str(base), "log", "--topo-order", f"-{max_commits}", "--format=%H%x09%aI%x09%s", *scope], capture_output=True, text=True, timeout=10, check=False)
        for line in output.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                sha, observed, subject = parts
                events.append(EvidenceEvent(f"git-{sha}", "project-scan", "git", "git_commit", subject, parse_iso_timestamp(observed), {"commit": sha, "source_ref": f"git:{sha}"}))
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return events
