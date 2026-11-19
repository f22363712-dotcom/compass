"""Shared project onboarding helpers for doc extraction and isolated AST index storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .code_index import build_code_index
from .derived_context import DerivedContext, DerivedContextError
from .evidence_filters import atomic_write_text
from .project_workspace import ProjectWorkspace

CODE_INDEX_FILENAME = "code-index.json"


def workspace_code_index_path(workspace: ProjectWorkspace) -> Path:
    """Always store generated AST graphs inside Compass's own workspace directory."""
    return workspace.state_path.parent / CODE_INDEX_FILENAME


def build_and_save_workspace_code_index(
    workspace: ProjectWorkspace,
    *,
    strict_syntax: bool = False,
    max_files: int | None = 800,
) -> dict[str, Any]:
    """Build the Python AST graph for ``workspace.project_path`` and store it isolated."""
    payload = build_code_index(
        workspace.project_path,
        project_id=workspace.project_id,
        strict_syntax=strict_syntax,
        max_files=max_files,
    )
    target = workspace_code_index_path(workspace)
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def load_workspace_derived_context(workspace: ProjectWorkspace) -> DerivedContext | None:
    """Load the persisted workspace AST DerivedContext if present and valid."""
    target = workspace_code_index_path(workspace)
    if not target.is_file():
        return None
    try:
        return DerivedContext.load(
            target,
            project_id=workspace.project_id,
            project_root=workspace.project_path,
        )
    except (OSError, ValueError, DerivedContextError, json.JSONDecodeError):
        return None
