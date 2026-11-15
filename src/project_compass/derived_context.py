"""Read-only validation for imported code-structure context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


from .evidence_filters import parse_iso_timestamp
from .limits import (
    MAX_EDGES,
    MAX_FINGERPRINT,
    MAX_LABEL,
    MAX_NODE_ID,
    MAX_NODES,
    MAX_SOURCE_REF,
    MAX_SUMMARY,
)

SCHEMA_VERSION = 1
NODE_KINDS = {"file", "module", "function", "class", "domain", "unknown"}
EDGE_KINDS = {"imports", "calls", "contains", "belongs_to", "unknown"}
UA_FORMAT = "understand-anything"
UA_VERSIONS = {1, "1", "1.0"}
UA_NODE_KIND_MAP = {
    "file": "file",
    "module": "module",
    "package": "module",
    "directory": "module",
    "function": "function",
    "method": "function",
    "class": "class",
    "interface": "class",
    "struct": "class",
    "domain": "domain",
    "concept": "domain",
    "unknown": "unknown",
}
UA_EDGE_KIND_MAP = {
    "imports": "imports",
    "exports": "imports",
    "depends_on": "imports",
    "calls": "calls",
    "invokes": "calls",
    "contains": "contains",
    "defines": "contains",
    "belongs_to": "belongs_to",
    "member_of": "belongs_to",
    "in_domain": "belongs_to",
    "unknown": "unknown",
}


class DerivedContextError(ValueError):
    """Raised when a derived context payload is unsafe or inconsistent."""


@dataclass(frozen=True)
class DerivedContextNode:
    id: str
    kind: str
    label: str
    source_ref: str
    summary: str | None = None
    origin: str = "derived_context"

    def to_dict(self) -> dict[str, Any]:
        value = {"id": self.id, "kind": self.kind, "label": self.label, "source_ref": self.source_ref, "origin": self.origin}
        if self.summary is not None:
            value["summary"] = self.summary
        return value


@dataclass(frozen=True)
class DerivedContextEdge:
    id: str
    from_id: str
    to_id: str
    kind: str
    origin: str = "derived_context"

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "from_id": self.from_id, "to_id": self.to_id, "kind": self.kind, "origin": self.origin}


@dataclass(frozen=True)
class DerivedContext:
    project_id: str
    source_ref: str
    source_fingerprint: str
    observed_at: datetime
    nodes: tuple[DerivedContextNode, ...]
    edges: tuple[DerivedContextEdge, ...]
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, project_id: str, project_root: str | Path | None = None) -> "DerivedContext":
        if not isinstance(payload, dict):
            raise DerivedContextError("derived context must be an object")
        if payload.get("format") == UA_FORMAT and "schema_version" not in payload:
            return cls.from_understand_anything(payload, project_id=project_id, project_root=project_root)
        return cls._from_canonical_dict(payload, project_id=project_id, project_root=project_root)

    @classmethod
    def from_understand_anything(cls, payload: dict[str, Any], *, project_id: str, project_root: str | Path | None = None) -> "DerivedContext":
        """Adapt an external Understand-Anything knowledge-graph JSON into read-only DerivedContext."""
        if not isinstance(payload, dict):
            raise DerivedContextError("derived context must be an object")
        if payload.get("format") != UA_FORMAT or payload.get("version", 1) not in UA_VERSIONS:
            raise DerivedContextError("unsupported derived context schema")
        payload_root = _first_present(payload, ("project_root", "projectRoot"))
        if payload_root is not None:
            if not isinstance(payload_root, str) or not payload_root.strip():
                raise DerivedContextError("derived context project_root is invalid")
            if project_root is not None:
                if Path(payload_root).expanduser().resolve() != Path(project_root).expanduser().resolve():
                    raise DerivedContextError("derived context project mismatch")
        raw_nodes = payload.get("nodes")
        raw_edges = _first_present(payload, ("edges", "links"))
        if not isinstance(raw_nodes, list) or len(raw_nodes) > MAX_NODES:
            raise DerivedContextError("derived context nodes are invalid or exceed the limit")
        if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
            raise DerivedContextError("derived context edges are invalid or exceed the limit")
        nodes: list[dict[str, Any]] = []
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                raise DerivedContextError("derived context node must be an object")
            raw_kind = _first_present(raw, ("type", "kind"))
            mapped_kind = UA_NODE_KIND_MAP.get(raw_kind) if isinstance(raw_kind, str) else None
            if mapped_kind is None:
                raise DerivedContextError("derived context node kind is invalid")
            node_entry: dict[str, Any] = {
                "id": raw.get("id"),
                "kind": mapped_kind,
                "label": _first_present(raw, ("name", "label")),
                "source_ref": _normalize_relative_ref(_first_present(raw, ("filePath", "path", "source_ref"))),
            }
            summary = _first_present(raw, ("summary", "description"))
            if summary is not None:
                node_entry["summary"] = summary
            nodes.append(node_entry)
        edges: list[dict[str, Any]] = []
        for raw in raw_edges:
            if not isinstance(raw, dict):
                raise DerivedContextError("derived context edge must be an object")
            raw_kind = _first_present(raw, ("type", "relation", "kind"))
            mapped_kind = UA_EDGE_KIND_MAP.get(raw_kind) if isinstance(raw_kind, str) else None
            if mapped_kind is None:
                raise DerivedContextError("derived context edge kind is invalid")
            from_id = _first_present(raw, ("source", "from", "from_id"))
            to_id = _first_present(raw, ("target", "to", "to_id"))
            edge_id = raw.get("id")
            if edge_id is None and isinstance(from_id, str) and isinstance(to_id, str) and isinstance(raw_kind, str):
                edge_id = f"{from_id}->{to_id}:{raw_kind}"
            edges.append({
                "id": edge_id,
                "from_id": from_id,
                "to_id": to_id,
                "kind": mapped_kind,
            })
        normalized = {
            "schema_version": SCHEMA_VERSION,
            "project_id": _first_present(payload, ("project_id", "projectId")),
            "source_ref": _normalize_relative_ref(_first_present(payload, ("source_ref", "sourceRef", "entryFile"))),
            "source_fingerprint": _first_present(payload, ("source_fingerprint", "sourceFingerprint", "sourceHash")),
            "observed_at": _first_present(payload, ("observed_at", "generatedAt", "analyzedAt")),
            "nodes": nodes,
            "edges": edges,
        }
        return cls._from_canonical_dict(normalized, project_id=project_id, project_root=project_root)

    @classmethod
    def _from_canonical_dict(cls, payload: dict[str, Any], *, project_id: str, project_root: str | Path | None = None) -> "DerivedContext":
        if not isinstance(payload, dict):
            raise DerivedContextError("derived context must be an object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise DerivedContextError("unsupported derived context schema")
        if not isinstance(project_id, str) or not project_id.strip():
            raise DerivedContextError("project id is required")
        if payload.get("project_id") != project_id:
            raise DerivedContextError("derived context project mismatch")
        source_ref = _bounded_text(payload.get("source_ref"), "source_ref", MAX_SOURCE_REF)
        _validate_project_ref(source_ref, "source_ref", project_root)
        fingerprint = _bounded_text(payload.get("source_fingerprint"), "source_fingerprint", MAX_FINGERPRINT)
        observed_at = _timestamp(payload.get("observed_at"))
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        if not isinstance(raw_nodes, list) or len(raw_nodes) > MAX_NODES:
            raise DerivedContextError("derived context nodes are invalid or exceed the limit")
        if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
            raise DerivedContextError("derived context edges are invalid or exceed the limit")

        nodes: list[DerivedContextNode] = []
        node_ids: set[str] = set()
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                raise DerivedContextError("derived context node must be an object")
            node_id = _bounded_text(raw.get("id"), "node id", MAX_NODE_ID)
            if node_id in node_ids:
                raise DerivedContextError("derived context contains duplicate node ids")
            kind = raw.get("kind")
            if kind not in NODE_KINDS:
                raise DerivedContextError("derived context node kind is invalid")
            label = _bounded_text(raw.get("label"), "node label", MAX_LABEL)
            node_source = _bounded_text(raw.get("source_ref"), "node source_ref", MAX_SOURCE_REF)
            _validate_project_ref(node_source, "node source_ref", project_root)
            summary = raw.get("summary")
            if summary is not None:
                summary = _bounded_text(summary, "node summary", MAX_SUMMARY)
            node_ids.add(node_id)
            nodes.append(DerivedContextNode(node_id, kind, label, node_source, summary))

        edges: list[DerivedContextEdge] = []
        edge_ids: set[str] = set()
        for raw in raw_edges:
            if not isinstance(raw, dict):
                raise DerivedContextError("derived context edge must be an object")
            edge_id = _bounded_text(raw.get("id"), "edge id", MAX_NODE_ID)
            if edge_id in edge_ids:
                raise DerivedContextError("derived context contains duplicate edge ids")
            from_id = _bounded_text(raw.get("from_id"), "edge from_id", MAX_NODE_ID)
            to_id = _bounded_text(raw.get("to_id"), "edge to_id", MAX_NODE_ID)
            if from_id not in node_ids or to_id not in node_ids:
                raise DerivedContextError("derived context edge points to an unknown node")
            kind = raw.get("kind")
            if kind not in EDGE_KINDS:
                raise DerivedContextError("derived context edge kind is invalid")
            edge_ids.add(edge_id)
            edges.append(DerivedContextEdge(edge_id, from_id, to_id, kind))

        return cls(project_id, source_ref, fingerprint, observed_at, tuple(nodes), tuple(edges))

    @classmethod
    def load(cls, path: str | Path, *, project_id: str, project_root: str | Path | None = None) -> "DerivedContext":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DerivedContextError("derived context file could not be read") from exc
        return cls.from_dict(payload, project_id=project_id, project_root=project_root)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "source_ref": self.source_ref,
            "source_fingerprint": self.source_fingerprint,
            "observed_at": self.observed_at.isoformat(),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def source_current(self, path: str | Path) -> bool:
        """Return whether the imported source still has the recorded fingerprint."""
        try:
            return fingerprint_source(path) == self.source_fingerprint
        except (OSError, ValueError):
            return False

    def related_projection(self, source_refs: set[str] | frozenset[str]) -> tuple[tuple[DerivedContextNode, ...], tuple[DerivedContextEdge, ...]]:
        """Return a deterministic connected read projection for source references."""
        wanted = set(source_refs)
        direct = {node.id for node in self.nodes if node.source_ref in wanted}
        connected = set(direct)
        changed = True
        while changed:
            changed = False
            for edge in self.edges:
                if edge.from_id in connected or edge.to_id in connected:
                    before = len(connected)
                    connected.update((edge.from_id, edge.to_id))
                    changed = changed or len(connected) != before
        nodes = tuple(node for node in self.nodes if node.id in connected)
        edges = tuple(edge for edge in self.edges if edge.from_id in connected and edge.to_id in connected)
        return nodes, edges

    def chain_of_recall(
        self,
        *,
        source_refs: set[str] | frozenset[str] = (),
        symbols: set[str] | frozenset[str] = (),
        node_ids: set[str] | frozenset[str] = (),
    ) -> list[dict[str, Any]]:
        """Perform deterministic chain of recall: locate nodes and trace upstream callers & downstream callees."""
        nodes_by_id = {node.id: node for node in self.nodes}
        source_ref_set = {ref.replace("\\", "/").strip().casefold() for ref in source_refs if isinstance(ref, str) and ref}
        symbol_set = {sym.strip().casefold() for sym in symbols if isinstance(sym, str) and sym}
        symbol_patterns = [sym for sym in symbols if hasattr(sym, "search")]
        wanted_node_ids = set(node_ids)

        # 1. Match Direct AST Nodes
        matched_nodes: list[DerivedContextNode] = []
        for node in self.nodes:
            if node.id in wanted_node_ids:
                matched_nodes.append(node)
                continue
            normalized_ref = node.source_ref.replace("\\", "/").casefold()
            if source_ref_set and any(normalized_ref == ref or normalized_ref.endswith("/" + ref) or ref.endswith("/" + normalized_ref) for ref in source_ref_set):
                matched_nodes.append(node)
                continue
            if symbol_set and node.label.casefold() in symbol_set:
                matched_nodes.append(node)
                continue
            if symbol_patterns and any(
                p.search(node.label) or p.search(node.label.casefold())
                or p.search(node.source_ref) or p.search(node.source_ref.casefold())
                for p in symbol_patterns
            ):
                matched_nodes.append(node)
                continue

        if len(matched_nodes) > 10:
            functions_classes = [n for n in matched_nodes if n.kind in {"function", "class"}]
            if functions_classes:
                matched_nodes = functions_classes[:10]
            else:
                matched_nodes = matched_nodes[:10]

        # 2. Build incoming and outgoing edge index
        incoming_edges: dict[str, list[DerivedContextEdge]] = {}
        outgoing_edges: dict[str, list[DerivedContextEdge]] = {}
        for edge in self.edges:
            outgoing_edges.setdefault(edge.from_id, []).append(edge)
            incoming_edges.setdefault(edge.to_id, []).append(edge)

        # 3. For each matched node, trace Upstream Callers and Downstream Callees
        results: list[dict[str, Any]] = []
        for node in matched_nodes:
            upstream_edges = incoming_edges.get(node.id, [])
            upstream_callers = []
            seen_caller_ids = set()
            for edge in upstream_edges:
                caller = nodes_by_id.get(edge.from_id)
                if caller and caller.id != node.id and caller.id not in seen_caller_ids:
                    seen_caller_ids.add(caller.id)
                    upstream_callers.append({
                        "node": caller.to_dict(),
                        "edge_kind": edge.kind,
                        "edge_id": edge.id,
                    })

            downstream_edges = outgoing_edges.get(node.id, [])
            downstream_callees = []
            seen_callee_ids = set()
            for edge in downstream_edges:
                callee = nodes_by_id.get(edge.to_id)
                if callee and callee.id != node.id and callee.id not in seen_callee_ids:
                    seen_callee_ids.add(callee.id)
                    downstream_callees.append({
                        "node": callee.to_dict(),
                        "edge_kind": edge.kind,
                        "edge_id": edge.id,
                    })

            results.append({
                "target_node": node.to_dict(),
                "upstream_callers": upstream_callers[:8],
                "downstream_callees": downstream_callees[:8],
                "upstream_count": len(upstream_callers),
                "downstream_count": len(downstream_callees),
                "chain_summary": f"[{node.kind}] {node.label} ({node.source_ref}) <- callers({len(upstream_callers)}) / -> callees({len(downstream_callees)})",
            })

        return results

    def get_multihop_call_chain(
        self,
        node_id: str,
        depth: int = 2,
        *,
        max_nodes: int = 20,
        edge_kinds: tuple[str, ...] = ("calls", "imports", "depends_on"),
    ) -> dict[str, Any]:
        """Traverse upstream callers and downstream callees up to `depth` levels (default 2, max 5).
        
        Guaranteed bounded recursion (max `max_nodes` distinct nodes) to prevent cycle explosions.
        """
        nodes_by_id = {node.id: node for node in self.nodes}
        target = nodes_by_id.get(node_id)
        if target is None:
            return {
                "target_node": None,
                "depth": depth,
                "max_nodes": max_nodes,
                "upstream": [],
                "downstream": [],
                "upstream_count": 0,
                "downstream_count": 0,
                "impacted_nodes": [],
            }

        bounded_depth = max(1, min(depth, 5))
        node_limit = max(1, min(max_nodes, 100))
        allowed_kinds = set(edge_kinds) if edge_kinds else EDGE_KINDS

        # Build adjacency maps
        incoming: dict[str, list[DerivedContextEdge]] = {}
        outgoing: dict[str, list[DerivedContextEdge]] = {}
        for edge in self.edges:
            if edge.kind in allowed_kinds or not edge_kinds:
                outgoing.setdefault(edge.from_id, []).append(edge)
                incoming.setdefault(edge.to_id, []).append(edge)

        # 1. Upstream Traversal (Callers/dependents of target)
        upstream: list[dict[str, Any]] = []
        upstream_visited: set[str] = {target.id}
        queue: list[tuple[str, int]] = [(target.id, 0)]
        while queue and len(upstream) < node_limit:
            curr_id, curr_hop = queue.pop(0)
            if curr_hop >= bounded_depth:
                continue
            for edge in incoming.get(curr_id, []):
                caller_id = edge.from_id
                if caller_id not in upstream_visited and caller_id in nodes_by_id:
                    upstream_visited.add(caller_id)
                    caller_node = nodes_by_id[caller_id]
                    upstream.append({
                        "node": caller_node.to_dict(),
                        "hop": curr_hop + 1,
                        "edge_kind": edge.kind,
                        "edge_id": edge.id,
                        "caller_id": caller_id,
                        "callee_id": curr_id,
                    })
                    queue.append((caller_id, curr_hop + 1))
                    if len(upstream) >= node_limit:
                        break

        # 2. Downstream Traversal (Callees called by target)
        downstream: list[dict[str, Any]] = []
        downstream_visited: set[str] = {target.id}
        queue = [(target.id, 0)]
        while queue and len(downstream) < node_limit:
            curr_id, curr_hop = queue.pop(0)
            if curr_hop >= bounded_depth:
                continue
            for edge in outgoing.get(curr_id, []):
                callee_id = edge.to_id
                if callee_id not in downstream_visited and callee_id in nodes_by_id:
                    downstream_visited.add(callee_id)
                    callee_node = nodes_by_id[callee_id]
                    downstream.append({
                        "node": callee_node.to_dict(),
                        "hop": curr_hop + 1,
                        "edge_kind": edge.kind,
                        "edge_id": edge.id,
                        "caller_id": curr_id,
                        "callee_id": callee_id,
                    })
                    queue.append((callee_id, curr_hop + 1))
                    if len(downstream) >= node_limit:
                        break

        impacted = [item["node"] for item in upstream]

        return {
            "target_node": target.to_dict(),
            "depth": bounded_depth,
            "max_nodes": node_limit,
            "upstream": upstream,
            "downstream": downstream,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "impacted_nodes": impacted,
        }


def analyze_contract_risk(
    derived_context: DerivedContext,
    *,
    node_id: str | None = None,
    source_ref: str | None = None,
    symbol: str | None = None,
    change_hint: str | None = None,
    depth: int = 2,
    max_nodes: int = 20,
) -> list[dict[str, Any]]:
    """Identify downstream/caller contract break risks when a core function/class is modified."""
    targets: list[DerivedContextNode] = []
    nodes_by_id = {node.id: node for node in derived_context.nodes}
    if node_id and node_id in nodes_by_id:
        targets.append(nodes_by_id[node_id])
    elif symbol or source_ref:
        norm_ref = source_ref.replace("\\", "/").casefold() if source_ref else None
        norm_sym = symbol.casefold() if symbol else None
        for node in derived_context.nodes:
            if norm_sym and node.label.casefold() == norm_sym:
                targets.append(node)
                continue
            if norm_ref and (node.source_ref.replace("\\", "/").casefold() == norm_ref or norm_ref.endswith("/" + node.source_ref.replace("\\", "/").casefold())):
                if node.kind in {"function", "class"}:
                    targets.append(node)

    risks: list[dict[str, Any]] = []
    seen_target_ids: set[str] = set()
    for target in targets:
        if target.id in seen_target_ids:
            continue
        seen_target_ids.add(target.id)
        chain = derived_context.get_multihop_call_chain(target.id, depth=depth, max_nodes=max_nodes)
        impacted = chain.get("impacted_nodes", [])
        if impacted or chain.get("upstream_count", 0) > 0:
            risk_level = "high" if len(impacted) >= 3 else "medium" if impacted else "low"
            risks.append({
                "target_node": target.to_dict(),
                "risk_level": risk_level,
                "warning": f"Contract risk: modification of [{target.kind}] {target.label} may affect {len(impacted)} upstream caller(s)",
                "affected_nodes": impacted[:max_nodes],
                "affected_count": len(impacted),
                "multihop_chain": chain,
                "change_hint": change_hint or "",
            })
    return risks


def fact_chain_of_recall(
    derived_context: DerivedContext,
    fact: Any,
    events: list[Any],
    *,
    symbols: set[str] | frozenset[str] = (),
) -> dict[str, Any]:
    """Establish deterministic Fact -> Evidence -> AST Node -> Upstream/Downstream chain."""
    evidence_ids = getattr(fact, "evidence_ids", ()) or []
    if isinstance(fact, dict):
        fact_id = fact.get("id") or fact.get("fact_id")
        subject_key = fact.get("subject_key")
        fact_ref = fact.get("source_ref")
        evidence_ids = fact.get("evidence_ids", ()) or []
    else:
        fact_id = getattr(fact, "id", None)
        subject_key = getattr(fact, "subject_key", None)
        fact_ref = getattr(fact, "source_ref", None)
    sources = {getattr(e, "id", None): e for e in events}
    backing_events = [sources[eid] for eid in evidence_ids if eid in sources]
    source_refs = set()
    if fact_ref:
        source_refs.add(fact_ref)
    for ev in backing_events:
        ref = getattr(ev, "metadata", {}).get("source_ref") if hasattr(ev, "metadata") else None
        if ref:
            source_refs.add(ref)

    ast_chains = derived_context.chain_of_recall(source_refs=source_refs, symbols=symbols)
    return {
        "fact_id": fact_id,
        "subject_key": subject_key,
        "evidence_ids": list(evidence_ids),
        "source_refs": sorted(source_refs),
        "ast_chains": ast_chains,
    }



def fingerprint_file(path: str | Path) -> str:
    """Hash a local source file without changing it or following a network path."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def fingerprint_source(path: str | Path) -> str:
    """Hash a local file or Python source tree matching code_index.build_code_index."""
    target = Path(path).expanduser()
    if target.is_dir():
        from .code_index import iter_python_files

        base = target.resolve()
        sources: dict[str, str] = {}
        for item in iter_python_files(base):
            rel = item.relative_to(base).as_posix()
            try:
                sources[rel] = item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        digest = hashlib.sha256()
        for rel in sorted(sources):
            digest.update(rel.encode("utf-8"))
            digest.update(sources[rel].encode("utf-8"))
        return "sha256:" + digest.hexdigest()
    return fingerprint_file(target)


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _normalize_relative_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if Path(value).is_absolute() or value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":"):
        return value
    return value.replace("\\", "/")


def _bounded_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DerivedContextError(f"derived context {field} is invalid")
    return value


def _validate_project_ref(value: str, field: str, project_root: str | Path | None) -> None:
    if project_root is None:
        return
    if Path(value).is_absolute() or value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":"):
        raise DerivedContextError(f"derived context {field} leaves the project root")
    root = Path(project_root).expanduser().resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DerivedContextError(f"derived context {field} leaves the project root") from exc


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise DerivedContextError("derived context observed_at is invalid")
    try:
        stamp = parse_iso_timestamp(value)
    except ValueError as exc:
        raise DerivedContextError("derived context observed_at is invalid") from exc
    if stamp.tzinfo is None:
        raise DerivedContextError("derived context observed_at requires a timezone")
    return stamp
