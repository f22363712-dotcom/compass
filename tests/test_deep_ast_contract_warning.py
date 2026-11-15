"""Tests for Module 1: Deep AST Multi-hop Topology Penetration & Contract Warning."""
from datetime import datetime, timezone
import unittest

from project_compass.derived_context import (
    DerivedContext,
    DerivedContextEdge,
    DerivedContextNode,
    analyze_contract_risk,
)
from project_compass.investigator import investigate
from project_compass.models import EvidenceEvent
from project_compass.raw_source_investigation import extend_raw_sources


class DeepASTContractWarningTests(unittest.TestCase):
    def setUp(self):
        # Topology:
        # A (run_app) -> calls -> B (service_handler) -> calls -> C (core_compute) -> calls -> D (low_level_math)
        # Also E (aux_tool) -> calls -> C (core_compute)
        self.nodes = (
            DerivedContextNode("node-A", "function", "run_app", "src/app.py", "Application runner"),
            DerivedContextNode("node-B", "function", "service_handler", "src/service.py", "Service API handler"),
            DerivedContextNode("node-C", "function", "core_compute", "src/compute.py", "Core computation engine"),
            DerivedContextNode("node-D", "function", "low_level_math", "src/math_lib.py", "Low level math helper"),
            DerivedContextNode("node-E", "function", "aux_tool", "src/tool.py", "Auxiliary tool"),
        )
        self.edges = (
            DerivedContextEdge("edge-ab", "node-A", "node-B", "calls"),
            DerivedContextEdge("edge-bc", "node-B", "node-C", "calls"),
            DerivedContextEdge("edge-cd", "node-C", "node-D", "calls"),
            DerivedContextEdge("edge-ec", "node-E", "node-C", "calls"),
        )
        self.context = DerivedContext(
            project_id="test-proj-ast",
            source_ref="src/app.py",
            source_fingerprint="sha256:112233",
            observed_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            nodes=self.nodes,
            edges=self.edges,
        )

    def test_multihop_call_chain_penetrates_up_and_downstream(self):
        """Query multi-hop from node-C with depth=2."""
        res = self.context.get_multihop_call_chain("node-C", depth=2)
        self.assertIsNotNone(res["target_node"])
        self.assertEqual(res["target_node"]["id"], "node-C")

        # Upstream callers: 1-hop is node-B and node-E; 2-hop is node-A (calling node-B)
        upstream_ids = {u["node"]["id"] for u in res["upstream"]}
        self.assertIn("node-B", upstream_ids)
        self.assertIn("node-E", upstream_ids)
        self.assertIn("node-A", upstream_ids)
        self.assertEqual(res["upstream_count"], 3)

        # Check hops
        hops = {u["node"]["id"]: u["hop"] for u in res["upstream"]}
        self.assertEqual(hops["node-B"], 1)
        self.assertEqual(hops["node-E"], 1)
        self.assertEqual(hops["node-A"], 2)

        # Downstream callees: 1-hop is node-D
        downstream_ids = {d["node"]["id"] for d in res["downstream"]}
        self.assertEqual(downstream_ids, {"node-D"})
        self.assertEqual(res["downstream"][0]["hop"], 1)

        # Impacted nodes: all callers who depend on C's contract
        impacted_ids = {n["id"] for n in res["impacted_nodes"]}
        self.assertEqual(impacted_ids, {"node-B", "node-E", "node-A"})

    def test_multihop_call_chain_depth_boundary(self):
        """Depth=1 should only retrieve immediate 1-hop callers."""
        res = self.context.get_multihop_call_chain("node-C", depth=1)
        upstream_ids = {u["node"]["id"] for u in res["upstream"]}
        self.assertEqual(upstream_ids, {"node-B", "node-E"})
        self.assertNotIn("node-A", upstream_ids)

    def test_multihop_cycle_prevention_and_node_limit(self):
        """Cyclic dependency graph: A -> B -> C -> A."""
        cyclic_nodes = (
            DerivedContextNode("c-A", "function", "fn_a", "src/a.py"),
            DerivedContextNode("c-B", "function", "fn_b", "src/b.py"),
            DerivedContextNode("c-C", "function", "fn_c", "src/c.py"),
        )
        cyclic_edges = (
            DerivedContextEdge("e-ab", "c-A", "c-B", "calls"),
            DerivedContextEdge("e-bc", "c-B", "c-C", "calls"),
            DerivedContextEdge("e-ca", "c-C", "c-A", "calls"),
        )
        ctx = DerivedContext(
            project_id="test-cyclic",
            source_ref="src/a.py",
            source_fingerprint="sha256:cyc",
            observed_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
            nodes=cyclic_nodes,
            edges=cyclic_edges,
        )

        # Should safely terminate without recursion error
        res = ctx.get_multihop_call_chain("c-A", depth=5)
        self.assertEqual(res["upstream_count"], 2)
        self.assertEqual(res["downstream_count"], 2)

        # Test bounded max_nodes
        res_limited = ctx.get_multihop_call_chain("c-A", depth=5, max_nodes=1)
        self.assertLessEqual(len(res_limited["upstream"]), 1)
        self.assertLessEqual(len(res_limited["downstream"]), 1)

    def test_multihop_unknown_node_returns_safe_empty(self):
        res = self.context.get_multihop_call_chain("missing-node", depth=2)
        self.assertIsNone(res["target_node"])
        self.assertEqual(res["upstream"], [])
        self.assertEqual(res["downstream"], [])
        self.assertEqual(res["impacted_nodes"], [])

    def test_analyze_contract_risk(self):
        """Detect downstream contract risk when core_compute is modified."""
        risks = analyze_contract_risk(
            self.context,
            symbol="core_compute",
            change_hint="Refactor core_compute signature: add timeout param",
            depth=2,
        )
        self.assertEqual(len(risks), 1)
        risk = risks[0]
        self.assertEqual(risk["target_node"]["id"], "node-C")
        self.assertEqual(risk["target_node"]["label"], "core_compute")
        self.assertEqual(risk["risk_level"], "high")  # >= 3 affected nodes
        self.assertEqual(risk["affected_count"], 3)
        affected_ids = {n["id"] for n in risk["affected_nodes"]}
        self.assertEqual(affected_ids, {"node-B", "node-E", "node-A"})
        self.assertIn("core_compute", risk["warning"])

    def test_raw_source_investigation_contract_risk_penetration(self):
        """When an event modifies a function, extend_raw_sources surfaces contract_risk."""
        events = [
            EvidenceEvent(
                "ev-test-refactor",
                "session-1",
                "alice",
                "test_result",
                "refactor core_compute signature parameter validation failed",
                datetime(2026, 11, 9, tzinfo=timezone.utc),
                {"source_ref": "src/compute.py", "exit_code": 1},
            )
        ]
        answer = investigate(events, "原始测试输出 core_compute", derived_context=self.context)
        # Verify contract_risk in answer
        self.assertTrue(len(answer.contract_risk) >= 1)
        risk = answer.contract_risk[0]
        self.assertEqual(risk["target_node"]["label"], "core_compute")
        self.assertTrue(risk["affected_count"] >= 2)

        # Verify to_dict serialization
        d = answer.to_dict()
        self.assertIn("contract_risk", d)
        self.assertEqual(len(d["contract_risk"]), len(answer.contract_risk))
        self.assertEqual(d["contract_risk"][0]["target_node"]["id"], "node-C")


if __name__ == "__main__":
    unittest.main()
