"""Tests for Slice 2: Deterministic Chain of Recall based on AST dependency graph."""
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from project_compass.derived_context import (
    DerivedContext,
    DerivedContextEdge,
    DerivedContextNode,
    fact_chain_of_recall,
)
from project_compass.investigator import investigate
from project_compass.models import EvidenceEvent


class SuperagentChainOfRecallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        # Create AST Nodes:
        # A caller (main.py -> run_pipeline) calls processor.py -> process_data
        # which in turn calls helper.py -> sanitize_input
        self.nodes = (
            DerivedContextNode("node-main", "function", "run_pipeline", "src/main.py", "Entry point"),
            DerivedContextNode("node-processor", "function", "process_data", "src/processor.py", "Core processing logic"),
            DerivedContextNode("node-helper", "function", "sanitize_input", "src/helper.py", "Input sanitation"),
        )
        self.edges = (
            DerivedContextEdge("edge-1", "node-main", "node-processor", "calls"),
            DerivedContextEdge("edge-2", "node-processor", "node-helper", "calls"),
        )
        self.context = DerivedContext(
            project_id="test-proj",
            source_ref="src/main.py",
            source_fingerprint="sha256:abc",
            observed_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
            nodes=self.nodes,
            edges=self.edges,
        )

    def test_chain_of_recall_traces_upstream_and_downstream(self):
        # Query chain for node-processor
        chains = self.context.chain_of_recall(node_ids={"node-processor"})
        self.assertEqual(len(chains), 1)
        res = chains[0]

        # Target node
        self.assertEqual(res["target_node"]["id"], "node-processor")
        self.assertEqual(res["target_node"]["label"], "process_data")

        # Upstream: node-main calls node-processor
        self.assertEqual(len(res["upstream_callers"]), 1)
        self.assertEqual(res["upstream_callers"][0]["node"]["id"], "node-main")
        self.assertEqual(res["upstream_callers"][0]["edge_kind"], "calls")

        # Downstream: node-processor calls node-helper
        self.assertEqual(len(res["downstream_callees"]), 1)
        self.assertEqual(res["downstream_callees"][0]["node"]["id"], "node-helper")
        self.assertEqual(res["downstream_callees"][0]["edge_kind"], "calls")

    def test_chain_of_recall_matches_source_ref_and_symbols(self):
        # Match by file path
        by_ref = self.context.chain_of_recall(source_refs={"src/processor.py"})
        self.assertEqual(len(by_ref), 1)
        self.assertEqual(by_ref[0]["target_node"]["id"], "node-processor")

        # Match by symbol name
        by_sym = self.context.chain_of_recall(symbols={"sanitize_input"})
        self.assertEqual(len(by_sym), 1)
        self.assertEqual(by_sym[0]["target_node"]["id"], "node-helper")
        # sanitize_input has node-processor as upstream caller
        self.assertEqual(by_sym[0]["upstream_callers"][0]["node"]["id"], "node-processor")

    def test_fact_chain_of_recall_penetration(self):
        # Fact -> Evidence -> AST Node -> Call chain
        events = [
            EvidenceEvent(
                "ev-commit-1",
                "session-1",
                "alice",
                "git_commit",
                "Refactor process_data logic",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"source_ref": "src/processor.py"},
            )
        ]
        fact_dict = {
            "id": "fact-proc-1",
            "subject_key": "code.processor",
            "evidence_ids": ["ev-commit-1"],
            "source_ref": "src/processor.py",
        }

        chain = fact_chain_of_recall(self.context, fact_dict, events)
        self.assertEqual(chain["fact_id"], "fact-proc-1")
        self.assertEqual(chain["evidence_ids"], ["ev-commit-1"])
        self.assertEqual(chain["source_refs"], ["src/processor.py"])
        self.assertEqual(len(chain["ast_chains"]), 1)
        self.assertEqual(chain["ast_chains"][0]["target_node"]["label"], "process_data")

    def test_investigate_penetrates_chain_of_recall(self):
        events = [
            EvidenceEvent(
                "ev-test-1",
                "session-1",
                "alice",
                "test_result",
                "test_processor passed",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"source_ref": "src/processor.py", "exit_code": 0},
            )
        ]
        answer = investigate(events, "原始测试输出 process_data", derived_context=self.context)
        self.assertTrue(len(answer.chain_of_recall) >= 1)
        target_labels = [c["target_node"]["label"] for c in answer.chain_of_recall]
        self.assertIn("process_data", target_labels)

    def test_chain_of_recall_deduplicates_multiple_edges(self):
        # Add duplicate calls edge
        duplicate_edges = self.edges + (
            DerivedContextEdge("edge-dup", "node-main", "node-processor", "calls"),
        )
        ctx = DerivedContext(
            project_id="test-proj",
            source_ref="src/main.py",
            source_fingerprint="sha256:abc",
            observed_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
            nodes=self.nodes,
            edges=duplicate_edges,
        )
        chains = ctx.chain_of_recall(node_ids={"node-processor"})
        self.assertEqual(len(chains), 1)
        # Upstream callers should be deduplicated (1 caller node, not 2)
        self.assertEqual(len(chains[0]["upstream_callers"]), 1)

    def test_chain_of_recall_matches_case_insensitive_patterns(self):
        import re
        # Pattern compiled with lowercase should match camelCase/mixedCase labels
        pattern = re.compile(r'(?<![a-z0-9_])process_data(?![a-z0-9_])')
        chains = self.context.chain_of_recall(symbols={pattern})
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["target_node"]["label"], "process_data")

    def test_investigate_normal_state_query_penetrates_fact_chain_of_recall(self):
        events = [
            EvidenceEvent(
                "ev-goal-1",
                "session-1",
                "alice",
                "assistant_message",
                "Goal: ship processor pipeline",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"facts": [{"kind": "goal", "subject_key": "project.goal", "value": "ship processor pipeline"}], "source_ref": "src/processor.py"},
            )
        ]
        answer = investigate(events, "当前状态与下一步", derived_context=self.context)
        self.assertTrue(len(answer.chain_of_recall) >= 1)
        self.assertTrue(any(c["target_node"]["label"] == "process_data" for c in answer.chain_of_recall))


if __name__ == "__main__":
    unittest.main()
