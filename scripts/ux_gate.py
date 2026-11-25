"""Reusable UX & Motion Gate for Project Compass web assets and user-facing copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = Path(__file__).resolve().with_name("ux_gate_allowlist.json")
SCAN_SUFFIXES = {".py", ".js", ".html", ".css"}
EXTRA_COPY_FILES = (
    "README.md",
    "README_EN.md",
    "agent/skills/compass/SKILL.md",
    "src/project_compass/antigravity_plugin/compass/plugin.json",
)
BLOCKING_DIALOG_RE = re.compile(
    r"(?:(?<![\w$])(?:window|self|globalThis)\s*\.\s*|(?<![.\w$]))(?:confirm|alert|prompt)\s*\("
)
TRANSITION_DECL_RE = re.compile(r"transition(?:-property)?\s*:\s*([^;{}]+)", re.IGNORECASE)
CSS_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
REDUCED_MOTION_RE = re.compile(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{", re.IGNORECASE)
KEYFRAMES_HEAD_RE = re.compile(r"@(?:-webkit-)?keyframes\s+[\w-]+\s*\{", re.IGNORECASE)


def load_allowlist(path: Path | None = None) -> dict:
    allowlist_path = path or DEFAULT_ALLOWLIST
    return json.loads(allowlist_path.read_text(encoding="utf-8"))


def _is_allowlisted(rel_path: str, line: str, rules: list[dict]) -> bool:
    norm_rel = rel_path.replace("\\", "/")
    for rule in rules:
        prefix = str(rule.get("path_prefix") or "")
        contains = str(rule.get("contains") or "")
        if prefix and not norm_rel.startswith(prefix):
            continue
        if contains and contains not in line:
            continue
        return True
    return False


def _extract_brace_body(text: str, open_brace_idx: int) -> str:
    depth = 0
    for idx in range(open_brace_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : idx]
    return text[open_brace_idx + 1 :]


def _strip_js_comments_and_strings(text: str) -> str:
    """Strip comments and string literal contents while preserving ${...} template expressions."""
    out: list[str] = []
    n = len(text)
    i = 0
    stack: list[list] = [["code", 0]]

    def _skip_quoted(start: int, quote: str) -> int:
        j = start + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == quote:
                return j + 1
            j += 1
        return n

    while i < n:
        ctx = stack[-1]
        mode = ctx[0]
        if mode == "tpl":
            ch = text[i]
            if ch == "\\":
                out.append("  ")
                i += 2
            elif ch == "$" and i + 1 < n and text[i + 1] == "{":
                out.append(" ")
                stack.append(["tpl_expr", 1])
                i += 2
            elif ch == "`":
                out.append(" ")
                stack.pop()
                i += 1
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
            continue

        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = text.find("\n", i + 2)
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif ch in ("'", '"'):
            i = _skip_quoted(i, ch)
            out.append(" ")
        elif ch == "`":
            stack.append(["tpl", 0])
            out.append(" ")
            i += 1
        elif mode == "tpl_expr" and ch == "{":
            ctx[1] += 1
            out.append(ch)
            i += 1
        elif mode == "tpl_expr" and ch == "}":
            ctx[1] -= 1
            if ctx[1] <= 0:
                stack.pop()
                out.append(" ")
            else:
                out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _extract_mcp_styles_and_app_script(mcp_html: str) -> tuple[str, str]:
    style_blocks = re.findall(r"<style>([\s\S]*?)</style>", mcp_html, re.IGNORECASE)
    style_text = "\n".join(style_blocks)
    # Only scan custom Compass app JS after the embedded ext-apps/Zod bundle marker.
    for marker in ("var uy=[", "COMPASS_LOGO_SVG"):
        idx = mcp_html.find(marker)
        if idx != -1:
            return style_text, mcp_html[idx:]
    return style_text, mcp_html


def _check_css_motion(
    label: str,
    css_text: str,
    required_tokens: list[str],
    forbidden_props: list[str],
    errors: list[str],
) -> None:
    stripped_css = CSS_COMMENT_RE.sub(" ", css_text)
    for token in required_tokens:
        if token not in stripped_css:
            errors.append(f"[motion-token] {label} is missing required CSS token: {token}")

    reduced_match = REDUCED_MOTION_RE.search(stripped_css)
    if not reduced_match:
        errors.append(f"[reduced-motion] {label} must define @media (prefers-reduced-motion: reduce)")
    else:
        reduced_block = _extract_brace_body(stripped_css, reduced_match.end() - 1)
        if "animation-duration" not in reduced_block or "transition-duration" not in reduced_block:
            errors.append(
                f"[reduced-motion] {label} reduced-motion block must clamp both animation-duration and transition-duration"
            )
        if "::view-transition-" in stripped_css and "::view-transition-" not in reduced_block:
            errors.append(
                f"[reduced-motion] {label} reduced-motion block must also disable ::view-transition-* animations"
            )

    for match in TRANSITION_DECL_RE.finditer(stripped_css):
        decl = match.group(1)
        lowered = decl.lower()
        for prop in [*forbidden_props, "all"]:
            if re.search(rf"(?<![a-z0-9-]){re.escape(prop)}(?![a-z0-9-])", lowered):
                errors.append(f"[forbidden-transition] {label} animates layout property '{prop}': {decl.strip()[:80]}")

    for kf_match in KEYFRAMES_HEAD_RE.finditer(stripped_css):
        kf_body = _extract_brace_body(stripped_css, kf_match.end() - 1)
        for prop in forbidden_props:
            if re.search(rf"(?<![a-z0-9-]){re.escape(prop)}\s*:", kf_body, re.IGNORECASE):
                errors.append(f"[forbidden-keyframes] {label} keyframe animates layout property '{prop}'")


def _scan_file_copy(
    repo_root: Path,
    file_path: Path,
    banned_terms: list[str],
    allow_rules: list[dict],
    errors: list[str],
) -> None:
    rel = file_path.relative_to(repo_root).as_posix()
    text = file_path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        hits = [term for term in banned_terms if term in line]
        if hits and not _is_allowlisted(rel, line, allow_rules):
            errors.append(f"[banned-copy] {rel}:{lineno} contains legacy term(s) {hits}: {line.strip()[:80]}")


def run_gate(repo_root: Path = REPO_ROOT, allowlist_path: Path | None = None) -> list[str]:
    cfg = load_allowlist(allowlist_path)
    banned_terms: list[str] = list(cfg.get("banned_legacy_terms") or [])
    allow_rules: list[dict] = list(cfg.get("legacy_term_allowlist") or [])
    required_tokens: list[str] = list(cfg.get("required_motion_tokens") or [])
    forbidden_props: list[str] = list(cfg.get("forbidden_transition_properties") or [])
    errors: list[str] = []

    src_root = repo_root / "src" / "project_compass"
    seen_paths: set[Path] = set()
    if src_root.exists():
        for file_path in sorted(src_root.rglob("*")):
            if not file_path.is_file() or file_path.suffix not in SCAN_SUFFIXES:
                continue
            if "__pycache__" in file_path.parts:
                continue
            seen_paths.add(file_path.resolve())
            _scan_file_copy(repo_root, file_path, banned_terms, allow_rules, errors)

    for rel_extra in EXTRA_COPY_FILES:
        extra_path = repo_root / rel_extra
        if extra_path.is_file() and extra_path.resolve() not in seen_paths:
            seen_paths.add(extra_path.resolve())
            _scan_file_copy(repo_root, extra_path, banned_terms, allow_rules, errors)

    styles_path = src_root / "web" / "styles.css"
    app_js_path = src_root / "web" / "app.js"
    index_html_path = src_root / "web" / "index.html"
    mcp_html_path = src_root / "web" / "mcp_app.html"

    if styles_path.exists():
        _check_css_motion(
            "web/styles.css",
            styles_path.read_text(encoding="utf-8"),
            required_tokens,
            forbidden_props,
            errors,
        )
    else:
        errors.append("[missing-file] src/project_compass/web/styles.css not found")

    if mcp_html_path.exists():
        mcp_text = mcp_html_path.read_text(encoding="utf-8")
        mcp_style, mcp_app_script = _extract_mcp_styles_and_app_script(mcp_text)
        _check_css_motion(
            "web/mcp_app.html",
            mcp_style,
            required_tokens,
            forbidden_props,
            errors,
        )
        sanitized_mcp = _strip_js_comments_and_strings(mcp_app_script)
        if BLOCKING_DIALOG_RE.search(sanitized_mcp):
            errors.append("[blocking-dialog] web/mcp_app.html contains forbidden confirm()/alert()/prompt() call")
    else:
        errors.append("[missing-file] src/project_compass/web/mcp_app.html not found")

    for js_or_html, label in ((app_js_path, "web/app.js"), (index_html_path, "web/index.html")):
        if not js_or_html.exists():
            continue
        sanitized = _strip_js_comments_and_strings(js_or_html.read_text(encoding="utf-8"))
        if BLOCKING_DIALOG_RE.search(sanitized):
            errors.append(f"[blocking-dialog] {label} contains forbidden confirm()/alert()/prompt() call")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project Compass UX & Motion quality gate")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root to inspect")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST, help="Path to ux_gate_allowlist.json")
    args = parser.parse_args(argv)

    errors = run_gate(args.repo_root.resolve(), args.allowlist.resolve())
    if errors:
        print(f"UX_GATE_FAILED ({len(errors)} issue(s)):")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("UX_GATE_PASSED: copy glossary, motion tokens, reduced-motion, and dialog checks clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
