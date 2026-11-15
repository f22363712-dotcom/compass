import json
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from project_compass import cli
from project_compass.doc_fact_intake import record_document_candidates
from project_compass.evidence_store import EvidenceStore
from project_compass.fact_engine import derive_facts
from project_compass.investigator import investigate
from project_compass.models import FactStatus
from project_compass.project_scanner import scan_project
from project_compass.project_workspace import ProjectWorkspace


REPO_ROOT = Path(__file__).resolve().parents[1]


class DogfoodAndDocIntakeTest(unittest.TestCase):
    def test_doc_fact_intake_extracts_exact_spans_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            (root / "README.md").write_text(
                "# Demo Compass\n\nBuild an immutable local-first evidence compass for coding agents.\n",
                encoding="utf-8",
            )
            (root / "DECISIONS.md").write_text(
                "# Decisions\n\n2026-11-14 Adopted SQLite FTS5 trigram BM25 retrieval with pure-Python fallback after A/B benchmark evaluation.\n",
                encoding="utf-8",
            )
            (root / "HANDOFF.md").write_text(
                "# Handoff\n\n- [x] Ship Swiss Neo-Brutalism dashboard grid\n- [ ] Add repository LICENSE before public release\n",
                encoding="utf-8",
            )
            ws_root = Path(directory) / "ws"
            events = scan_project(root)
            workspace = ProjectWorkspace(ws_root, root)
            workspace.save(events, {"source": "scan"}, complete_scan=True)
            events = workspace.load()

            first = record_document_candidates(events, workspace)
            self.assertTrue(first["updated"])
            self.assertEqual(first["new_doc_proposals"], 4)

            facts = derive_facts(events)
            kinds = {f.kind.value for f in facts}
            self.assertEqual(kinds, {"goal", "decision", "task"})
            self.assertTrue(all(f.status is FactStatus.PROPOSED for f in facts))
            self.assertTrue(all(f.claim_type == "document_statement" for f in facts))

            second = record_document_candidates(events, workspace)
            self.assertFalse(second["updated"])
            self.assertEqual(second["new_doc_proposals"], 0)

    def test_cli_scan_extract_docs_and_with_code_index_exports_prd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample_py"
            (root / "pkg").mkdir(parents=True)
            (root / "README.md").write_text(
                "# PyRepo\n\nProvide verifiable dependency graphs and decision provenance for multi-agent coding.\n",
                encoding="utf-8",
            )
            (root / "DECISIONS.md").write_text(
                "2026-11-14 Keep runtime pure standard library with zero third-party packages.\n",
                encoding="utf-8",
            )
            (root / "pkg" / "engine.py").write_text(
                "def helper():\n    return 1\n\ndef run():\n    return helper()\n",
                encoding="utf-8",
            )
            ws_root = Path(directory) / "ws"
            out = StringIO()
            with redirect_stdout(out):
                rc = cli.main(
                    [
                        "--scan",
                        str(root),
                        "--workspace-root",
                        str(ws_root),
                        "--extract-docs",
                        "--with-code-index",
                        "--export-format",
                        "json",
                    ]
                )
            self.assertEqual(rc, 0)
            exported = json.loads(out.getvalue())
            state = exported["state"]
            self.assertGreaterEqual(state["project"]["fact_count"], 2)
            self.assertTrue(state["derived_context"]["enabled"])
            self.assertGreaterEqual(len(state["derived_context"]["nodes"]), 3)

    def test_sample_mode_rejects_extract_docs_and_with_code_index(self):
        self.assertEqual(cli.main(["--sample", "--extract-docs"]), 2)
        self.assertEqual(cli.main(["--sample", "--with-code-index"]), 2)

    def test_public_dogfood_example_loads_detects_conflicts_and_answers_questions(self):
        fixture = REPO_ROOT / "examples" / "dogfood_project_compass.json"
        self.assertTrue(fixture.is_file())
        events = EvidenceStore.load(fixture).list()
        facts = derive_facts(events)
        conflicted_keys = {f.subject_key for f in facts if f.status is FactStatus.CONFLICTED}
        self.assertIn("arch.retriever_backend", conflicted_keys)
        self.assertIn("ui.design_system", conflicted_keys)
        answer = investigate(events, "为什么检索器采用了 SQLite FTS5 Trigram BM25？")
        result = answer.to_dict()
        self.assertTrue(result["evidence_ids"])
        self.assertTrue(result["conclusion"])


if __name__ == "__main__":
    unittest.main()
