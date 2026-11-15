"""Layer 4: contract risk.

When a core function changes, who is affected?

This layer needs a code-structure graph, which is the part of the product
that had no producer until ``project_compass.code_index`` was written. The
layer measures two things: whether the graph can locate a symbol and trace
its callers, and whether the index is still fresh enough to be trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .base import HIGHER, LayerResult, Metric, ratio

LAYER_ID = "L4"
TITLE = "契约层：调用链追踪"

CONTRACT_FORMAT = "project-compass-eval-contracts"
CONTRACT_VERSION = 1


class ContractError(ValueError):
    """Raised when a contract expectation file is malformed."""


@dataclass(frozen=True)
class ContractCase:
    """One authored expectation about a symbol's blast radius."""

    id: str
    symbol: str
    source_ref: str
    expected_caller_modules: tuple[str, ...]
    expected_callee_modules: tuple[str, ...]
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "source_ref": self.source_ref,
            "expected_caller_modules": list(self.expected_caller_modules),
            "expected_callee_modules": list(self.expected_callee_modules),
            "note": self.note,
        }


def load_contract_cases(path: str | Path) -> list[ContractCase]:
    """Read the authored contract expectations."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("contract expectations could not be read") from exc
    if not isinstance(payload, dict) or payload.get("format") != CONTRACT_FORMAT:
        raise ContractError("unsupported contract expectation format")
    if payload.get("version") != CONTRACT_VERSION:
        raise ContractError("unsupported contract expectation version")
    raw = payload.get("cases")
    if not isinstance(raw, list) or not raw:
        raise ContractError("contract expectations need at least one case")
    cases: list[ContractCase] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ContractError("each contract case must be an object")
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ContractError("a contract case needs a symbol")
        cases.append(
            ContractCase(
                id=str(item.get("id") or symbol),
                symbol=symbol.strip(),
                source_ref=str(item.get("source_ref") or ""),
                expected_caller_modules=tuple(item.get("expected_caller_modules") or ()),
                expected_callee_modules=tuple(item.get("expected_callee_modules") or ()),
                note=str(item.get("note") or ""),
            )
        )
    return cases


def run_contract(context, cases: list[ContractCase], *, depth: int = 3) -> LayerResult:
    """Measure symbol location, caller tracing and index freshness."""
    from ...derived_context import analyze_contract_risk

    nodes_by_id = {node.id: node for node in context.nodes}
    by_label: dict[str, list] = {}
    for node in context.nodes:
        by_label.setdefault(node.label, []).append(node)

    located = 0
    caller_hits = 0
    caller_total = 0
    risk_reported = 0
    details: list[dict] = []

    for case in cases:
        candidates = by_label.get(case.symbol, [])
        if case.source_ref:
            candidates = [
                node for node in candidates if node.source_ref.replace("\\", "/") == case.source_ref.replace("\\", "/")
            ] or candidates
        if not candidates:
            details.append({"case": case.id, "located": False, "note": "symbol not found in the index"})
            continue
        located += 1
        node = candidates[0]
        chain = context.get_multihop_call_chain(node.id, depth=depth)
        caller_modules = {
            item["node"]["source_ref"].replace("\\", "/")
            for item in chain["upstream"]
        }
        callee_modules = {
            item["node"]["source_ref"].replace("\\", "/")
            for item in chain["downstream"]
        }
        found_callers = [ref for ref in case.expected_caller_modules if ref in caller_modules]
        found_callees = [ref for ref in case.expected_callee_modules if ref in callee_modules]
        caller_total += len(case.expected_caller_modules)
        caller_hits += len(found_callers)
        risks = analyze_contract_risk(context, node_id=node.id, depth=depth)
        if risks:
            risk_reported += 1
        details.append(
            {
                "case": case.id,
                "located": True,
                "symbol": case.symbol,
                "upstream_count": chain["upstream_count"],
                "downstream_count": chain["downstream_count"],
                "expected_callers": list(case.expected_caller_modules),
                "found_callers": found_callers,
                "missing_callers": [
                    ref for ref in case.expected_caller_modules if ref not in caller_modules
                ],
                "expected_callees": list(case.expected_callee_modules),
                "found_callees": found_callees,
                "risk_level": risks[0]["risk_level"] if risks else "none",
                "note": case.note,
            }
        )

    metrics = (
        Metric(
            "symbol_locatable",
            ratio(located, len(cases)),
            1.0,
            HIGHER,
            hard=True,
            detail="每个受测符号都能在索引里定位",
        ),
        Metric(
            "caller_trace_recall",
            ratio(caller_hits, caller_total),
            1.0,
            HIGHER,
            hard=True,
            detail=f"{caller_hits}/{caller_total} 个预期调用方被追到",
        ),
        Metric(
            "risk_reported",
            ratio(risk_reported, len(cases)),
            1.0,
            HIGHER,
            hard=True,
            detail="每个有调用方的符号都给出契约风险",
        ),
    )

    return LayerResult(
        layer=LAYER_ID,
        title=TITLE,
        metrics=metrics,
        details={
            "cases": details,
            "nodes": len(context.nodes),
            "edges": len(context.edges),
            "source_fingerprint": context.source_fingerprint,
        },
        notes=("本层度量结构图本身，不度量事实层。",),
    )
