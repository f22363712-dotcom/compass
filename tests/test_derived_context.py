import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from project_compass.derived_context import DerivedContext, DerivedContextError, fingerprint_file


def payload():
    return {
        "schema_version": 1,
        "project_id": "project-1",
        "source_ref": ".ua/knowledge-graph.json",
        "source_fingerprint": "sha256:abc",
        "observed_at": "2026-11-04T09:00:00+08:00",
        "nodes": [
            {"id": "file:src/main.py", "kind": "file", "label": "src/main.py", "source_ref": "src/main.py"},
            {"id": "fn:main", "kind": "function", "label": "main", "source_ref": "src/main.py", "summary": "Entry point."},
        ],
        "edges": [{"id": "edge-1", "from_id": "file:src/main.py", "to_id": "fn:main", "kind": "contains"}],
    }


class DerivedContextTests(unittest.TestCase):
    def test_valid_payload_is_immutable_and_round_trips(self):
        context = DerivedContext.from_dict(payload(), project_id="project-1")
        self.assertEqual(context.project_id, "project-1")
        self.assertEqual(context.edges[0].kind, "contains")
        self.assertEqual(context.nodes[0].origin, "derived_context")
        self.assertEqual(context.edges[0].to_dict()["origin"], "derived_context")
        self.assertEqual(context.to_dict()["source_ref"], ".ua/knowledge-graph.json")
        with self.assertRaises(AttributeError):
            context.project_id = "other"

    def test_project_mismatch_and_unknown_edge_are_rejected(self):
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_dict(payload(), project_id="project-2")
        invalid = payload(); invalid["edges"][0]["to_id"] = "missing"
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_dict(invalid, project_id="project-1")

    def test_duplicate_nodes_unknown_schema_and_naive_timestamp_are_rejected(self):
        duplicate = payload(); duplicate["nodes"].append(dict(duplicate["nodes"][0]))
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_dict(duplicate, project_id="project-1")
        unknown = payload(); unknown["schema_version"] = 2
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_dict(unknown, project_id="project-1")
        naive = payload(); naive["observed_at"] = "2026-11-04T09:00:00"
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_dict(naive, project_id="project-1")

    def test_load_rejects_malformed_file_without_network_or_project_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(DerivedContextError):
                DerivedContext.load(path, project_id="project-1")

    def test_source_fingerprint_detects_change_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            path.write_text(json.dumps(payload()), encoding="utf-8")
            value = payload(); value["source_fingerprint"] = fingerprint_file(path)
            context = DerivedContext.from_dict(value, project_id="project-1")
            self.assertTrue(context.source_current(path))
            path.write_text(json.dumps({"changed": True}), encoding="utf-8")
            self.assertFalse(context.source_current(path))
            path.unlink()
            self.assertFalse(context.source_current(path))

    def test_project_root_rejects_absolute_and_parent_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            parent = payload(); parent["source_ref"] = "../secret.json"
            with self.assertRaises(DerivedContextError):
                DerivedContext.from_dict(parent, project_id="project-1", project_root=root)
            absolute = payload(); absolute["nodes"][0]["source_ref"] = str(Path(directory) / "outside.py")
            with self.assertRaises(DerivedContextError):
                DerivedContext.from_dict(absolute, project_id="project-1", project_root=root)

    def test_minimal_fixture_is_a_valid_read_only_graph(self):
        fixture = Path(__file__).parent / "fixtures" / "derived_context_minimal.json"
        context = DerivedContext.load(fixture, project_id="project-1")
        self.assertEqual([node.kind for node in context.nodes], ["file", "function"])
        self.assertEqual(context.edges[0].kind, "contains")

    def test_related_projection_is_source_scoped_and_does_not_mutate_context(self):
        fixture = Path(__file__).parent / "fixtures" / "derived_context_minimal.json"
        context = DerivedContext.load(fixture, project_id="project-1")
        nodes, edges = context.related_projection({"src/main.py"})
        self.assertEqual([node.id for node in nodes], ["file:src/main.py", "fn:main"])
        self.assertEqual([edge.id for edge in edges], ["edge-1"])
        self.assertEqual(len(context.nodes), 2)

    def test_understand_anything_adapter_maps_external_fields_and_keeps_read_only_origin(self):
        ua_payload = {
            "format": "understand-anything",
            "version": "1.0",
            "projectId": "project-1",
            "entryFile": "src\\project_compass\\cli.py",
            "sourceHash": "sha256:123456",
            "generatedAt": "2026-11-04T10:30:00Z",
            "nodes": [
                {
                    "id": "file:cli",
                    "type": "file",
                    "name": "cli.py",
                    "filePath": "src\\project_compass\\cli.py",
                    "description": "CLI entrypoint.",
                    "status": "accepted",
                },
                {
                    "id": "method:main",
                    "type": "method",
                    "name": "main",
                    "filePath": "src/project_compass/cli.py",
                },
                {
                    "id": "domain:intake",
                    "type": "concept",
                    "name": "Evidence Intake",
                    "path": "src/project_compass/cli.py",
                },
            ],
            "links": [
                {"source": "file:cli", "target": "method:main", "type": "defines"},
                {"source": "method:main", "target": "domain:intake", "relation": "in_domain"},
            ],
        }
        context = DerivedContext.from_dict(ua_payload, project_id="project-1")
        self.assertEqual(context.source_ref, "src/project_compass/cli.py")
        self.assertEqual([node.kind for node in context.nodes], ["file", "function", "domain"])
        self.assertEqual(context.nodes[0].source_ref, "src/project_compass/cli.py")
        self.assertEqual(context.nodes[0].summary, "CLI entrypoint.")
        self.assertEqual(context.nodes[0].origin, "derived_context")
        self.assertNotIn("status", context.nodes[0].to_dict())
        self.assertEqual([edge.kind for edge in context.edges], ["contains", "belongs_to"])
        self.assertEqual(context.edges[0].id, "file:cli->method:main:defines")
        self.assertEqual(context.edges[0].origin, "derived_context")

    def test_understand_anything_adapter_rejects_mismatch_escaping_paths_and_invalid_kinds(self):
        base = {
            "format": "understand-anything",
            "version": 1,
            "projectId": "project-1",
            "entryFile": "src/main.py",
            "sourceHash": "sha256:abc",
            "generatedAt": "2026-11-04T10:30:00+08:00",
            "nodes": [{"id": "n1", "type": "file", "name": "main.py", "filePath": "src/main.py"}],
            "edges": [],
        }
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_understand_anything(base, project_id="project-2")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            other = Path(directory) / "other"
            root.mkdir()
            other.mkdir()
            wrong_root = dict(base, projectRoot=str(other))
            with self.assertRaises(DerivedContextError):
                DerivedContext.from_understand_anything(wrong_root, project_id="project-1", project_root=root)
            escaping = dict(base, nodes=[{"id": "n1", "type": "file", "name": "s", "filePath": "../secret.py"}])
            with self.assertRaises(DerivedContextError):
                DerivedContext.from_understand_anything(escaping, project_id="project-1", project_root=root)
        blank_primary = dict(
            base,
            nodes=[{"id": "n1", "type": "file", "name": "s", "filePath": "", "source_ref": "src/main.py"}],
        )
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_understand_anything(blank_primary, project_id="project-1")
        bad_node = dict(base, nodes=[{"id": "n1", "type": "executable", "name": "s", "filePath": "src/main.py"}])
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_understand_anything(bad_node, project_id="project-1")
        bad_edge = dict(base, edges=[{"source": "n1", "target": "n1", "type": "mutates_truth"}])
        with self.assertRaises(DerivedContextError):
            DerivedContext.from_understand_anything(bad_edge, project_id="project-1")


if __name__ == "__main__":
    unittest.main()
