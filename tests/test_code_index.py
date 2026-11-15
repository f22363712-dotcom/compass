"""Tests for the standard-library code-structure producer."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from project_compass.code_index import (
    CodeIndexError,
    build_code_index,
    code_index_summary,
    iter_python_files,
)
from project_compass.derived_context import DerivedContext

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "src"


class TempTreeTest(unittest.TestCase):
    """The producer must work on a tree that is not this repository."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "pkg" / "core.py").write_text(
            "def helper(value):\n"
            "    return value + 1\n"
            "\n"
            "class Service:\n"
            "    def run(self):\n"
            "        return helper(1)\n",
            encoding="utf-8",
        )
        (self.root / "pkg" / "app.py").write_text(
            "from pkg.core import Service\n"
            "\n"
            "def main():\n"
            "    return Service().run()\n",
            encoding="utf-8",
        )
        (self.root / "pkg" / "broken.py").write_text("def (:\n", encoding="utf-8")
        self.addCleanup(self._temp.cleanup)

    def test_unparsable_file_is_rejected_loudly(self) -> None:
        with self.assertRaises(CodeIndexError):
            build_code_index(self.root)

    def test_iter_python_files_skips_generated_folders(self) -> None:
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "junk.py").write_text("x = 1\n", encoding="utf-8")
        found = {path.relative_to(self.root).as_posix() for path in iter_python_files(self.root)}
        self.assertIn("pkg/core.py", found)
        self.assertNotIn("pkg/__pycache__/junk.py", found)


class ProducerTest(unittest.TestCase):
    """The payload must satisfy the reader that already exists in the product."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "pkg" / "core.py").write_text(
            "def helper(value):\n"
            "    return value + 1\n"
            "\n"
            "class Service:\n"
            "    def run(self):\n"
            "        return helper(1)\n",
            encoding="utf-8",
        )
        (self.root / "pkg" / "app.py").write_text(
            "from pkg.core import Service\n"
            "\n"
            "def main():\n"
            "    return Service().run()\n",
            encoding="utf-8",
        )
        self.addCleanup(self._temp.cleanup)

    def test_payload_is_readable_by_the_existing_reader(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        context = DerivedContext.from_understand_anything(
            payload, project_id="demo", project_root=self.root
        )
        self.assertGreater(len(context.nodes), 0)
        self.assertGreater(len(context.edges), 0)

    def test_calls_edge_is_created_between_functions(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        calls = [
            edge
            for edge in payload["edges"]
            if edge["type"] == "calls" and edge["source"].endswith("::main") and edge["target"].endswith("::Service")
        ]
        self.assertTrue(calls, "main must be linked to the imported class")

    def test_local_call_inside_a_method_is_resolved(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        calls = [
            edge
            for edge in payload["edges"]
            if edge["type"] == "calls" and edge["source"].endswith("::Service.run")
        ]
        self.assertTrue(calls, "the method must be linked to the helper it calls")

    def test_contains_edge_links_file_to_symbols(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        contains = [edge for edge in payload["edges"] if edge["type"] == "contains"]
        self.assertTrue(contains)
        targets = {edge["target"] for edge in contains}
        self.assertIn("symbol:pkg/core.py::helper", targets)
        self.assertIn("symbol:pkg/core.py::Service", targets)

    def test_imports_edge_links_two_files(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        imports = [edge for edge in payload["edges"] if edge["type"] == "imports"]
        self.assertTrue(imports, "an imported local module must create an imports edge")

    def test_source_refs_stay_inside_the_project_root(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        for node in payload["nodes"]:
            self.assertFalse(Path(node["filePath"]).is_absolute())
            self.assertNotIn("..", Path(node["filePath"]).parts)

    def test_payload_is_json_serialisable(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        restored = json.loads(json.dumps(payload))
        self.assertEqual(restored["format"], "understand-anything")

    def test_summary_counts_nodes_and_edges(self) -> None:
        payload = build_code_index(self.root, project_id="demo")
        summary = code_index_summary(payload)
        self.assertEqual(summary["nodes"], len(payload["nodes"]))
        self.assertEqual(summary["edges"], len(payload["edges"]))
        self.assertIn("file", summary["node_kinds"])
        self.assertEqual(summary["files_skipped"], 0)

    def test_a_file_that_cannot_be_read_is_reported_not_hidden(self) -> None:
        """A file missing from the graph is a missing edge, so it must show."""
        (self.root / "pkg" / "broken.py").write_bytes(b"\xff\xfe\x00binary")
        payload = build_code_index(self.root, project_id="demo")
        summary = code_index_summary(payload)
        self.assertEqual(summary["files_skipped"], 1)
        self.assertIn("not-utf8", summary["skipped_reasons"])
        skipped = {item["path"] for item in payload["files_skipped"]}
        self.assertIn("pkg/broken.py", skipped)
        context = DerivedContext.from_understand_anything(
            payload, project_id="demo", project_root=self.root
        )
        self.assertTrue(context.nodes)

    def test_fingerprint_changes_when_a_source_changes(self) -> None:
        first = build_code_index(self.root, project_id="demo")["source_fingerprint"]
        (self.root / "pkg" / "core.py").write_text("def helper(value):\n    return value + 2\n", encoding="utf-8")
        second = build_code_index(self.root, project_id="demo")["source_fingerprint"]
        self.assertNotEqual(first, second)

    def test_index_of_this_repository_loads(self) -> None:
        payload = build_code_index(SOURCE_ROOT, project_id="project-compass")
        context = DerivedContext.from_understand_anything(
            payload, project_id="project-compass", project_root=SOURCE_ROOT
        )
        labels = {node.label for node in context.nodes}
        self.assertIn("derive_facts", labels)
        self.assertIn("build_views", labels)

    def test_a_call_inside_a_closure_is_still_a_caller(self) -> None:
        """A nested function is a real caller, so its edge must survive."""
        (self.root / "pkg" / "closure.py").write_text(
            "def target():\n    return 1\n", encoding="utf-8"
        )
        (self.root / "pkg" / "worker.py").write_text(
            "from pkg.closure import target\n\n\n"
            "def drive():\n"
            "    def inner():\n"
            "        return target()\n"
            "    return inner()\n",
            encoding="utf-8",
        )
        payload = build_code_index(self.root, project_id="demo")
        calls = [
            edge
            for edge in payload["edges"]
            if edge["type"] == "calls" and edge["target"].endswith("::target")
        ]
        self.assertTrue(calls, "the closure must be linked to the function it calls")
        nodes = {node["id"] for node in payload["nodes"]}
        for edge in calls:
            self.assertIn(edge["source"], nodes)
            self.assertIn(edge["target"], nodes)

    def test_long_qualified_names_stay_inside_the_reader_limit(self) -> None:
        """An edge id is built from two node ids and must stay readable."""
        long_name = "a_very_long_test_method_name_" + "x" * 120
        (self.root / "pkg" / "long.py").write_text(
            f"class Holder:\n    def {long_name}(self):\n        return 1\n", encoding="utf-8"
        )
        payload = build_code_index(self.root, project_id="demo")
        for node in payload["nodes"]:
            self.assertLessEqual(len(node["id"]), 120)
        for edge in payload["edges"]:
            self.assertLessEqual(len(edge["id"]), 256)
        context = DerivedContext.from_understand_anything(
            payload, project_id="demo", project_root=self.root
        )
        self.assertTrue(context.nodes)


class CallChainTest(unittest.TestCase):
    """The graph must actually answer a chain question, not merely exist."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = build_code_index(SOURCE_ROOT, project_id="project-compass")
        cls.context = DerivedContext.from_understand_anything(
            cls.payload, project_id="project-compass", project_root=SOURCE_ROOT
        )

    def test_chain_of_recall_finds_callers_and_callees(self) -> None:
        chains = self.context.chain_of_recall(symbols={"derive_facts"})
        self.assertTrue(chains, "derive_facts must be locatable by symbol")
        target = chains[0]["target_node"]
        self.assertEqual(target["label"], "derive_facts")

    def test_multihop_chain_reports_upstream_callers(self) -> None:
        node_id = next(node.id for node in self.context.nodes if node.label == "derive_facts")
        chain = self.context.get_multihop_call_chain(node_id, depth=3)
        self.assertGreater(chain["upstream_count"], 0, "derive_facts has callers in this repository")

    def test_unknown_symbol_returns_empty_chain(self) -> None:
        chain = self.context.get_multihop_call_chain("symbol:missing.py::nope", depth=2)
        self.assertEqual(chain["upstream_count"], 0)
        self.assertEqual(chain["downstream_count"], 0)


if __name__ == "__main__":
    unittest.main()
