"""Export a scrubbed, single-commit open-source repository without touching source git history."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

EXCLUDED_TOP_DIRS = {
    ".git",
    ".goal",
    ".agents",
    "devpost",
    "submission",
    ".release-export",
    ".venv",
    "venv",
    "build",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tools",
    ".superpowers",
    ".deck-build",
    ".playwright-mcp",
}

EXCLUDED_REL_PREFIXES = (
    "docs/archive",
    "docs/reviews/v1.8-baseline",
    "logs",
    "tests/fixtures/benchmark/local-specs",
)

EXCLUDED_REL_FILES = {
    "docs/ZETARIS_DEMO_CHALLENGE_55S.md",
    "docs/GITHUB_PORTFOLIO_CURATION_2026-11-15.md",
    "devpost/learner-profile.md",
}

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# Privacy & credential leak regex gate checked on exported UTF-8 files
# Note: regex literals avoid embedding banned strings literally in source.
LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows_user_path", re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}(?!<|your|example|someone)", re.IGNORECASE)),
    ("windows_user_posix", re.compile(r"[A-Za-z]:/Users/(?!<|your|example|someone)", re.IGNORECASE)),
    ("file_uri_windows_drive", re.compile(r"file:///[A-Za-z]:/", re.IGNORECASE)),
    ("openai_secret_token", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github_pat_token", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("legacy_machine_handle", re.compile("206" + "51")),
)


def _should_skip_rel(rel: str, is_dir: bool) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    if name in EXCLUDED_DIR_NAMES or name.endswith(".egg-info"):
        return True
    if parts[0] in EXCLUDED_TOP_DIRS or parts[0].startswith(".project-memory"):
        return True
    for prefix in EXCLUDED_REL_PREFIXES:
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    if rel in EXCLUDED_REL_FILES:
        return True
    if not is_dir:
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            return True
        if name.endswith((".pyc", ".pyo", ".sqlite3", ".sqlite3-shm", ".sqlite3-wal")):
            return True
    return False


def _remove_readonly(func, path, _exc_info) -> None:
    try:
        Path(path).chmod(stat.S_IWRITE)
    except OSError:
        pass
    func(path)


def scan_tree_for_leaks(root: Path, *, ignore_rel: set[str] | None = None) -> list[str]:
    """Return a list of leak findings (pattern:relpath:line_no) across UTF-8 text files."""
    findings: list[str] = []
    skipped = ignore_rel or set()
    base = root.resolve()
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        rel_dir = Path(dirpath).relative_to(base).as_posix()
        for filename in sorted(filenames):
            rel = filename if rel_dir == "." else f"{rel_dir}/{filename}"
            if rel in skipped:
                continue
            path = Path(dirpath) / filename
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                for label, pattern in LEAK_PATTERNS:
                    if pattern.search(line):
                        findings.append(f"{label}:{rel}:{line_no}")
    return findings


def export_public_release(repo_root: Path, output_dir: Path, *, init_git: bool = True) -> dict[str, object]:
    """Copy a scrubbed clean tree into output_dir, verify zero leaks, and optionally init a single commit."""
    src_root = Path(repo_root).expanduser().resolve(strict=True)
    dst_root = Path(output_dir).expanduser().resolve()

    if dst_root == src_root or dst_root in src_root.parents:
        raise ValueError(f"Refusing to export into repository root or ancestor: {dst_root}")
    if src_root in dst_root.parents and ".release-export" not in dst_root.relative_to(src_root).parts:
        raise ValueError(f"Refusing to export inside workspace outside .release-export/: {dst_root}")

    if dst_root.exists():
        shutil.rmtree(dst_root, onerror=_remove_readonly)
    dst_root.mkdir(parents=True, exist_ok=True)

    copied_files = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        rel_dir = Path(dirpath).relative_to(src_root).as_posix()
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _should_skip_rel(name if rel_dir == "." else f"{rel_dir}/{name}", True)
        )
        for name in dirnames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            (dst_root / rel).mkdir(parents=True, exist_ok=True)
        for filename in sorted(filenames):
            rel = filename if rel_dir == "." else f"{rel_dir}/{filename}"
            if _should_skip_rel(rel, False):
                continue
            target = dst_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(dirpath) / filename, target)
            copied_files += 1

    # Keep empty logs/.gitkeep placeholder if present in source or standard layout
    logs_gitkeep = dst_root / "logs" / ".gitkeep"
    logs_gitkeep.parent.mkdir(parents=True, exist_ok=True)
    logs_gitkeep.write_text("", encoding="utf-8")

    # Strip internal /goal execution block from exported AGENTS.md while keeping shared rules
    exported_agents = dst_root / "AGENTS.md"
    if exported_agents.is_file():
        agents_text = exported_agents.read_text(encoding="utf-8")
        cleaned_agents = re.sub(
            r"\n*<!-- goal-setup:begin -->[\s\S]*?<!-- goal-setup:end -->\s*",
            "\n",
            agents_text,
        ).rstrip()
        exported_agents.write_bytes(
            (f"{cleaned_agents}\n" if cleaned_agents else "").encode("utf-8")
        )

    for forbidden_rel in EXCLUDED_REL_FILES:
        if (dst_root / forbidden_rel).exists():
            raise ValueError(f"Protected or private file must not exist in public export: {forbidden_rel}")

    leaks = scan_tree_for_leaks(dst_root)
    if leaks:
        raise ValueError(f"Privacy/secret leak gate blocked export: {leaks[:5]}")

    commit_sha: str | None = None
    if init_git:
        try:
            subprocess.run(["git", "init", "-b", "main"], cwd=dst_root, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            subprocess.run(["git", "init"], cwd=dst_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=dst_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Project Compass Contributors"], cwd=dst_root, check=True)
        subprocess.run(["git", "config", "user.email", "opensource@project-compass.local"], cwd=dst_root, check=True)
        subprocess.run(["git", "add", "."], cwd=dst_root, check=True)
        subprocess.run(
            ["git", "commit", "-m", "chore(release): initial open-source release v1.0.0 (Apache-2.0)"],
            cwd=dst_root,
            check=True,
            capture_output=True,
            text=True,
        )
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=dst_root, check=True, capture_output=True, text=True)
        commit_sha = res.stdout.strip()

    return {
        "output_dir": str(dst_root),
        "copied_files": copied_files,
        "leaks_found": 0,
        "commit_sha": commit_sha,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a clean single-commit public release of Project Compass")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default=".release-export/project-compass-public")
    parser.add_argument("--no-git", action="store_true", help="Copy scrubbed files without initializing a git commit")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).expanduser().resolve()
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = (repo_root / out_path).resolve()

    summary = export_public_release(repo_root, out_path, init_git=not args.no_git)
    print(f"Exported clean release ({summary['copied_files']} files, commit={summary['commit_sha']}) -> {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
