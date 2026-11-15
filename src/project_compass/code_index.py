"""Produce a code-structure graph from Python sources using the standard library.

The rest of Project Compass can *read* an imported code-structure graph
(``derived_context``), but nothing could *produce* one, so the structure layer
had no input. This module closes that gap with ``ast`` alone: no runtime
dependency, no index server, no watcher.

The emitted payload uses the ``understand-anything`` schema that
``derived_context.from_understand_anything`` already accepts, so the output of
this module can be imported without any change to the reader.

The graph is deliberately conservative. A call edge is created only when the
callee is unambiguous inside the project; an unresolved attribute call is
skipped rather than guessed, because a wrong edge is worse than a missing one
for a contract-risk analysis.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

from .limits import MAX_EDGES, MAX_ID, MAX_NODES

UA_FORMAT = "understand-anything"
UA_VERSION = 1

SKIP_DIRECTORIES = frozenset(
    {
        "__pycache__",
        "node_modules",
        "site-packages",
        "dist",
        "build",
    }
)

#: Directory names that are never part of a project's own source.
_VENDORED_NAME_HINTS = ("venv", "site-packages", "node_modules")


def _is_vendored(name: str) -> bool:
    """Return whether a directory holds third-party or generated code."""
    if name.startswith("."):
        return True
    lowered = name.lower()
    return any(hint in lowered for hint in _VENDORED_NAME_HINTS)


class CodeIndexError(ValueError):
    """Raised when a source tree cannot be indexed."""


@dataclass
class _Module:
    """One parsed Python file and the symbols it defines."""

    path: Path
    rel: str
    tree: ast.Module
    source: str
    functions: dict[str, str] = field(default_factory=dict)
    classes: dict[str, str] = field(default_factory=dict)
    methods: dict[str, dict[str, str]] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    module_imports: set[str] = field(default_factory=set)
    #: Every defined symbol by qualified name, with its kind and its parent.
    symbols: dict[str, tuple[str, str, str]] = field(default_factory=dict)


def iter_python_files(root: str | Path) -> list[Path]:
    """List the Python files of a tree, skipping vendored and generated folders."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise CodeIndexError(f"code index root is not a directory: {root}")
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            name for name in dirnames if not _is_vendored(name) and name not in SKIP_DIRECTORIES
        )
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                found.append(Path(dirpath) / filename)
    return sorted(found)


def _package_of(rel: str) -> list[str]:
    """Return the package parts a relative file belongs to."""
    parts = rel.split("/")[:-1]
    return [part for part in parts if part]


def _module_candidates(parts: list[str]) -> list[str]:
    """Return the file paths a dotted module path may live in."""
    if not parts:
        return []
    dotted = "/".join(parts)
    return [f"{dotted}.py", f"{dotted}/__init__.py"]


def _file_id(rel: str) -> str:
    """Return a bounded node id for a file."""
    candidate = f"file:{rel}"
    if len(candidate) <= MAX_ID:
        return candidate
    digest = hashlib.sha1(rel.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"file:{digest}"


def _symbol_id(rel: str, qualname: str) -> str:
    """Return a stable, bounded node id for a symbol.

    The reader refuses identifiers longer than 256 characters and builds an
    edge id out of two node ids, so a symbol id has to stay well below that.
    A long qualified name is therefore replaced by a digest: the id stays
    unique and stable, and the readable label stays on the node itself.
    """
    candidate = f"symbol:{rel}::{qualname}"
    if len(candidate) <= MAX_ID:
        return candidate
    digest = hashlib.sha1(qualname.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    shortened = f"symbol:{rel}::{digest}"
    if len(shortened) <= MAX_ID:
        return shortened
    rel_digest = hashlib.sha1(rel.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"symbol:{rel_digest}#{digest}"


class _Resolver:
    """Resolve a call target to a node id inside the indexed project."""

    def __init__(self, modules: dict[str, _Module]) -> None:
        self.modules = modules

    def resolve_name(self, module: _Module, name: str, *, scope_class: str | None) -> str | None:
        """Resolve a bare name used inside a function or class body."""
        if scope_class:
            method = module.methods.get(scope_class, {}).get(name)
            if method:
                return method
        own = module.functions.get(name)
        if own:
            return own
        imported = module.imports.get(name)
        if imported:
            return imported
        klass = module.classes.get(name)
        if klass:
            return klass
        return None

    def resolve_attribute(self, module: _Module, node: ast.Attribute, *, scope_class: str | None) -> str | None:
        """Resolve ``value.attr`` when the receiver is a known class."""
        receiver_name: str | None = None
        if isinstance(node.value, ast.Name):
            receiver_name = node.value.id
            if receiver_name in {"self", "cls"}:
                if scope_class:
                    method = module.methods.get(scope_class, {}).get(node.attr)
                    if method:
                        return method
                return None
        elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            receiver_name = node.value.func.id

        if receiver_name is None:
            return None
        receiver = self.resolve_name(module, receiver_name, scope_class=scope_class)
        if receiver is None:
            return None
        for candidate in self.modules.values():
            for class_name, class_id in candidate.classes.items():
                if class_id == receiver:
                    method = candidate.methods.get(class_name, {}).get(node.attr)
                    if method:
                        return method
        return None


def _collect_imports(module: _Module, modules: dict[str, _Module]) -> None:
    """Map imported local names to the node ids they refer to.

    Imports are collected from the whole module, not only from its top level,
    because this codebase imports inside functions to break import cycles.
    A function-level import is a real dependency and a real caller edge.
    """
    package = _package_of(module.rel)
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                target = _resolve_module_file(parts, modules)
                if target:
                    module.module_imports.add(_file_id(target))
                    module.imports.setdefault(alias.asname or parts[0], _file_id(target))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base: list[str] = []
            else:
                base = package[: len(package) - (node.level - 1)]
            module_parts = [*base, *(node.module.split(".") if node.module else [])]
            target_file = _resolve_module_file(module_parts, modules)
            if target_file:
                module.module_imports.add(_file_id(target_file))
            for alias in node.names:
                if alias.name == "*":
                    continue
                symbol = _resolve_symbol_target([*module_parts, alias.name], modules)
                if symbol:
                    module.imports[alias.asname or alias.name] = symbol


def _resolve_module_file(parts: list[str], modules: dict[str, _Module]) -> str | None:
    """Return the relative path of a local module addressed by dotted parts."""
    for candidate in _module_candidates(parts):
        if candidate in modules:
            return candidate
    return None


def _resolve_symbol_target(parts: list[str], modules: dict[str, _Module]) -> str | None:
    """Resolve ``package.module.symbol`` to a function or class node id."""
    if len(parts) < 2:
        return None
    target = _resolve_module_file(parts[:-1], modules)
    if target is None:
        return None
    module = modules[target]
    name = parts[-1]
    return module.functions.get(name) or module.classes.get(name)


def _collect_definitions(module: _Module) -> None:
    """Record the functions, classes and methods a module defines.

    Nested functions are recorded as well. A closure that calls a core
    function is a real caller, and leaving it out would understate the blast
    radius of the very change the contract layer is meant to warn about.
    """
    for qualname, kind, parent in _walk_definitions(module.tree):
        symbol_id = _symbol_id(module.rel, qualname)
        module.symbols[qualname] = (symbol_id, kind, parent)
        if kind == "class":
            if parent:
                continue
            module.classes[qualname] = symbol_id
        elif parent and "." not in parent:
            module.methods.setdefault(parent, {})[qualname.split(".", 1)[1]] = symbol_id
        elif not parent:
            module.functions[qualname] = symbol_id


def _walk_definitions(tree: ast.Module):
    """Yield ``(qualified_name, kind, parent)`` for every definition."""

    def visit(body, prefix: str):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                yield qualname, "class", prefix
                yield from visit(node.body, qualname)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{node.name}" if prefix else node.name
                kind = "method" if prefix and "." not in prefix else "function"
                yield qualname, kind, prefix
                yield from visit(node.body, qualname)

    yield from visit(tree.body, "")


def _collect_calls(module: _Module, resolver: _Resolver) -> list[tuple[str, str]]:
    """Return ``(caller_id, callee_id)`` pairs found in a module."""
    edges: list[tuple[str, str]] = []

    def visit(
        current: ast.AST,
        scope_class: str | None,
        scope_function: str | None,
        prefix: str,
    ) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.ClassDef):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                visit(child, child.name, scope_function, qualname)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                caller = _symbol_id(module.rel, qualname)
                visit(child, scope_class, caller, qualname)
                continue
            if isinstance(child, ast.Call):
                callee = None
                if isinstance(child.func, ast.Name):
                    callee = resolver.resolve_name(module, child.func.id, scope_class=scope_class)
                elif isinstance(child.func, ast.Attribute):
                    callee = resolver.resolve_attribute(module, child.func, scope_class=scope_class)
                if callee and scope_function:
                    edges.append((scope_function, callee))
            visit(child, scope_class, scope_function, prefix)

    visit(module.tree, None, None, "")
    return edges


def build_code_index(root: str | Path, *, project_id: str | None = None) -> dict:
    """Build a code-structure graph for a Python source tree.

    The result is an ``understand-anything`` payload, so it can be handed to
    ``DerivedContext.from_understand_anything`` without conversion.
    """
    base = Path(root).expanduser().resolve()
    files = iter_python_files(base)
    modules: dict[str, _Module] = {}
    skipped: list[dict] = []
    for path in files:
        rel = path.relative_to(base).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # A file that is not UTF-8 text is not Python source in practice,
            # but it must not vanish silently: a file missing from the graph is
            # a missing edge, and a missing edge is an understated blast
            # radius. The gap is reported instead of being hidden.
            skipped.append({"path": rel, "reason": "not-utf8"})
            continue
        except OSError as exc:
            raise CodeIndexError(f"source file could not be read: {rel}") from exc
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            raise CodeIndexError(f"source file could not be parsed: {rel}") from exc
        modules[rel] = _Module(path=path, rel=rel, tree=tree, source=source)

    resolver = _Resolver(modules)
    for module in modules.values():
        _collect_definitions(module)
    for module in modules.values():
        _collect_imports(module, modules)

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_edges: set[str] = set()

    def add_edge(from_id: str, to_id: str, kind: str) -> None:
        edge_id = f"{from_id}->{to_id}:{kind}"
        if edge_id in seen_edges:
            return
        seen_edges.add(edge_id)
        edges.append({"id": edge_id, "source": from_id, "target": to_id, "type": kind})

    for module in modules.values():
        file_node = _file_id(module.rel)
        nodes.append(
            {
                "id": file_node,
                "type": "file",
                "name": module.rel,
                "filePath": module.rel,
                "summary": f"{len(module.source.splitlines())} lines",
            }
        )
        for qualname, (symbol_id, kind, parent) in module.symbols.items():
            label = qualname.rsplit(".", 1)[-1]
            nodes.append(
                {"id": symbol_id, "type": kind, "name": label, "filePath": module.rel}
            )
            if parent:
                add_edge(_symbol_id(module.rel, parent), symbol_id, "contains")
            else:
                add_edge(file_node, symbol_id, "contains")

    for module in modules.values():
        file_node = _file_id(module.rel)
        for target in module.module_imports:
            add_edge(file_node, target, "imports")
        for source_id, target_id in _collect_calls(module, resolver):
            add_edge(source_id, target_id, "calls")

    warnings: list[str] = []
    truncated = False
    if len(nodes) > MAX_NODES:
        warnings.append(f"nodes truncated from {len(nodes)} to {MAX_NODES}")
        nodes = nodes[:MAX_NODES]
        truncated = True

    known = {node["id"] for node in nodes}
    edges = [edge for edge in edges if edge["source"] in known and edge["target"] in known]
    if len(edges) > MAX_EDGES:
        warnings.append(f"edges truncated from {len(edges)} to {MAX_EDGES}")
        edges = edges[:MAX_EDGES]
        truncated = True

    fingerprint = hashlib.sha256()
    for rel in sorted(modules):
        fingerprint.update(rel.encode("utf-8"))
        fingerprint.update(modules[rel].source.encode("utf-8"))

    return {
        "format": UA_FORMAT,
        "version": UA_VERSION,
        "project_id": project_id or base.name,
        "project_root": base.as_posix(),
        "source_ref": ".",
        "source_fingerprint": "sha256:" + fingerprint.hexdigest(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "files_indexed": len(modules),
        "files_skipped": skipped,
        "truncated": truncated,
        "warnings": warnings,
        "nodes": nodes,
        "edges": edges,
    }


def code_index_summary(payload: dict) -> dict:
    """Summarise an index payload for a report or a CLI."""
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    skipped = payload.get("files_skipped") or []
    kinds: dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("type", "unknown"))
        kinds[kind] = kinds.get(kind, 0) + 1
    edge_kinds: dict[str, int] = {}
    for edge in edges:
        kind = str(edge.get("type", "unknown"))
        edge_kinds[kind] = edge_kinds.get(kind, 0) + 1
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "node_kinds": dict(sorted(kinds.items())),
        "edge_kinds": dict(sorted(edge_kinds.items())),
        "source_fingerprint": payload.get("source_fingerprint"),
        "files_indexed": payload.get("files_indexed", len(nodes)),
        "files_skipped": len(skipped),
        "skipped_reasons": sorted({str(item.get("reason", "")) for item in skipped}),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="project_compass.code_index", description=__doc__)
    parser.add_argument("--root", default=".", help="source tree to index")
    parser.add_argument("--project-id", default=None, help="optional ProjectCompass workspace project_id to embed")
    parser.add_argument("--out", required=True, help="path of the JSON payload to write")
    args = parser.parse_args(argv)

    payload = build_code_index(args.root, project_id=args.project_id)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = code_index_summary(payload)
    print(f"wrote {target}: {summary['nodes']} nodes, {summary['edges']} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
