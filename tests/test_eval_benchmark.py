"""Tests for the ProjectCompass evaluation benchmark.

The benchmark is only worth trusting if its own machinery is tested: a scorer
that is too generous would turn a bad product into a good report. These tests
cover the gold format, the corpus format, the de-identification step, the
deterministic scorers, the corpus builder and every evaluation layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from project_compass.eval.corpus import (
    Corpus,
    CorpusError,
    Deidentifier,
    corpus_from_payload,
    load_corpus,
    write_corpus,
)
from project_compass.eval.gold import GoldError, GoldFact, GoldQuestion, GoldSet
from project_compass.eval.layers.l1_structure import run_structure
from project_compass.eval.layers.l2_extraction import extract_and_validate, run_extraction
from project_compass.eval.layers.l3_handoff import Answer, ProductAnswerer, run_handoff
from project_compass.eval.layers.l4_contract import load_contract_cases, run_contract
from project_compass.eval.layers.l5_adversarial import load_adversarial_cases
from project_compass.eval.report import EvalReport, compare, render_markdown
from project_compass.eval.scorers import (
    match_fact,
    score_answer,
    score_extraction,
    score_retrieval,
)
from project_compass.models import CandidateFact, EvidenceEvent, FactKind, FactStatus

OBSERVED = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def event(
    event_id: str,
    *,
    member: str = "member-1",
    kind: str = "assistant_message",
    content: str = "内容",
    facts: list | None = None,
    session: str | None = None,
) -> EvidenceEvent:
    """Build one corpus-style evidence event."""
    metadata = {"member_id": member, "role": "assistant", "source_ref": "test.md"}
    if facts is not None:
        metadata["facts"] = facts
    return EvidenceEvent(
        id=event_id,
        session_id=session or f"session-{member}",
        author=member,
        kind=kind,
        content=content,
        observed_at=OBSERVED,
        metadata=metadata,
    )


def fact_metadata(
    *, kind: str = "decision", value: str = "值", subject_key: str = "topic"
) -> dict:
    """Build one metadata fact entry the way the product persists them."""
    return {"kind": kind, "subject_key": subject_key, "value": value, "quote": value}


def candidate(
    fact_id: str,
    *,
    value: str,
    evidence_ids: tuple[str, ...],
    quote: str = "",
    subject_key: str = "topic",
    kind: str = "decision",
) -> CandidateFact:
    """Build one predicted fact for the scorer tests."""
    return CandidateFact(
        id=fact_id,
        kind=FactKind(kind),
        subject_key=subject_key,
        value=value,
        status=FactStatus.PROPOSED,
        evidence_ids=evidence_ids,
        author="member-1",
        observed_at=OBSERVED,
        quote=quote or value,
    )


class GoldSetTest(unittest.TestCase):
    """The gold format is the anchor of every number in the report."""

    def test_round_trip(self) -> None:
        gold = GoldSet(
            facts=(
                GoldFact(
                    id="g1",
                    kind="decision",
                    subject_key="decision:g1",
                    value="采用方案 A",
                    evidence_ids=("ev-1",),
                    required_terms=("方案 A",),
                ),
            ),
            questions=(
                GoldQuestion(
                    id="q1",
                    scope="team",
                    question="采用了哪个方案？",
                    evidence_ids=("ev-1",),
                    required_terms=("方案 A",),
                ),
            ),
        )
        restored = GoldSet.from_dict(gold.to_dict())
        self.assertEqual(restored.facts[0].value, "采用方案 A")
        self.assertEqual(restored.questions[0].scope, "team")

    def test_rejects_unknown_kind(self) -> None:
        payload = {
            "format": "project-compass-eval-gold",
            "version": 1,
            "meta": {},
            "facts": [
                {
                    "id": "g1",
                    "kind": "rumour",
                    "value": "x",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "questions": [],
        }
        with self.assertRaises(GoldError):
            GoldSet.from_dict(payload)

    def test_rejects_duplicate_ids(self) -> None:
        payload = {
            "format": "project-compass-eval-gold",
            "version": 1,
            "meta": {},
            "facts": [
                {"id": "g1", "kind": "goal", "value": "x", "evidence_ids": ["ev-1"]},
                {"id": "g1", "kind": "goal", "value": "y", "evidence_ids": ["ev-1"]},
            ],
            "questions": [],
        }
        with self.assertRaises(GoldError):
            GoldSet.from_dict(payload)

    def test_rejects_unknown_format(self) -> None:
        with self.assertRaises(GoldError):
            GoldSet.from_dict({"format": "something-else", "version": 1, "facts": [], "questions": []})


class CorpusTest(unittest.TestCase):
    """A corpus must refuse to load when its anchors point nowhere."""

    def _payload(self) -> tuple[dict, dict]:
        events = {
            "format": "project-compass-eval-corpus",
            "version": 1,
            "name": "demo",
            "meta": {},
            "events": [event("ev-1", content="原始内容").to_dict()],
        }
        gold = {
            "format": "project-compass-eval-gold",
            "version": 1,
            "meta": {},
            "facts": [
                {
                    "id": "g1",
                    "kind": "goal",
                    "value": "x",
                    "evidence_ids": ["ev-1"],
                    "required_terms": ["x"],
                }
            ],
            "questions": [
                {
                    "id": "q1",
                    "scope": "team",
                    "question": "q",
                    "evidence_ids": ["ev-1"],
                    "required_terms": ["内容"],
                }
            ],
        }
        return events, gold

    def test_round_trip(self) -> None:
        events, gold = self._payload()
        corpus = corpus_from_payload(events, gold)
        self.assertEqual(corpus.name, "demo")
        self.assertEqual(corpus.event_by_id("ev-1").content, "原始内容")
        with tempfile.TemporaryDirectory() as directory:
            write_corpus(directory, corpus)
            restored = load_corpus(directory)
        self.assertEqual(restored.gold.facts[0].id, "g1")

    def test_rejects_unknown_anchor(self) -> None:
        events, gold = self._payload()
        gold["facts"][0]["evidence_ids"] = ["ev-missing"]
        with self.assertRaises(CorpusError):
            corpus_from_payload(events, gold)

    def test_rejects_duplicate_event_ids(self) -> None:
        events, gold = self._payload()
        events["events"].append(event("ev-1", content="另一段").to_dict())
        with self.assertRaises(CorpusError):
            corpus_from_payload(events, gold)

    def test_rejects_empty_event_list(self) -> None:
        events, gold = self._payload()
        events["events"] = []
        with self.assertRaises(CorpusError):
            corpus_from_payload(events, gold)


class DeidentifierTest(unittest.TestCase):
    """De-identification is the only step allowed to rewrite source text."""

    def test_alias_replaces_name_in_text(self) -> None:
        deidentifier = Deidentifier()
        alias = deidentifier.alias("张三")
        text = deidentifier.text("张三 负责交付")
        self.assertNotIn("张三", text)
        self.assertIn(alias, text)

    def test_ascii_alias_respects_word_boundaries(self) -> None:
        deidentifier = Deidentifier()
        alias = deidentifier.alias("Fang")
        text = deidentifier.text("Fangwei 和 Fang 一起")
        self.assertIn("Fangwei", text)
        self.assertIn(alias, text)
        self.assertNotIn(" Fang ", text)

    def test_registered_labels_are_replaced_even_without_an_author_entry(self) -> None:
        deidentifier = Deidentifier()
        deidentifier.register_labels({"Fang": "Fang", "Fang侧": "Fang"})
        deidentifier.alias("Fang")
        text = deidentifier.text("Fang侧 补充了一条")
        self.assertNotIn("Fang侧", text)

    def test_url_is_replaced_before_absolute_path(self) -> None:
        deidentifier = Deidentifier()
        text = deidentifier.text("见 https://example.com/a/b")
        self.assertIn("<url>", text)
        self.assertNotIn("example.com", text)

    def test_email_and_home_path_are_removed(self) -> None:
        deidentifier = Deidentifier()
        text = deidentifier.text("a@b.com 与 C:/Users/someone/x")
        self.assertIn("<email>", text)
        self.assertNotIn("a@b.com", text)
        self.assertNotIn("someone", text)

    def test_summary_never_contains_real_names(self) -> None:
        deidentifier = Deidentifier()
        deidentifier.alias("张三")
        deidentifier.text("张三 负责")
        summary = deidentifier.summary()
        self.assertNotIn("张三", json.dumps(summary, ensure_ascii=False))
        self.assertEqual(summary["member_count"], 1)


class ScorerTest(unittest.TestCase):
    """The scorers decide every number, so they are held to strict rules."""

    def test_match_requires_terms_and_shared_evidence(self) -> None:
        gold = GoldFact(
            id="g1",
            kind="decision",
            subject_key="decision:g1",
            value="采用方案 A",
            evidence_ids=("ev-1",),
            required_terms=("方案 A",),
        )
        matched = match_fact(
            candidate("f1", value="采用方案 A", evidence_ids=("ev-1",)), gold
        )
        self.assertTrue(matched.matched)
        wrong_evidence = match_fact(
            candidate("f1", value="采用方案 A", evidence_ids=("ev-9",)), gold
        )
        self.assertFalse(wrong_evidence.matched)
        missing_term = match_fact(
            candidate("f1", value="采用方案 B", evidence_ids=("ev-1",)), gold
        )
        self.assertFalse(missing_term.matched)
        self.assertIn("方案 A", missing_term.missing_terms)

    def test_forbidden_term_breaks_a_match(self) -> None:
        gold = GoldFact(
            id="g1",
            kind="decision",
            subject_key="decision:g1",
            value="采用方案 A",
            evidence_ids=("ev-1",),
            required_terms=("方案 A",),
            forbidden_terms=("方案 B",),
        )
        result = match_fact(
            candidate("f1", value="采用方案 A 和方案 B", evidence_ids=("ev-1",)), gold
        )
        self.assertFalse(result.matched)

    def test_one_candidate_can_only_claim_one_gold_fact(self) -> None:
        gold = [
            GoldFact(
                id="g1",
                kind="decision",
                subject_key="decision:g1",
                value="采用方案 A",
                evidence_ids=("ev-1",),
                required_terms=("方案 A",),
            ),
            GoldFact(
                id="g2",
                kind="decision",
                subject_key="decision:g2",
                value="采用方案 A",
                evidence_ids=("ev-1",),
                required_terms=("方案 A",),
            ),
        ]
        score = score_extraction(
            [candidate("f1", value="采用方案 A", evidence_ids=("ev-1",))], gold
        )
        self.assertEqual(score.matched, 1)
        self.assertEqual(len(score.missed), 1)
        self.assertEqual(score.precision, 1.0)
        self.assertEqual(score.recall, 0.5)

    def test_retrieval_rank_respects_the_cutoff(self) -> None:
        question = GoldQuestion(
            id="q1",
            scope="team",
            question="q",
            evidence_ids=("ev-2",),
        )
        inside = score_retrieval(["ev-1", "ev-2"], question, cutoff=5)
        self.assertEqual(inside.rank, 2)
        outside = score_retrieval(["ev-1"] * 10 + ["ev-2"], question, cutoff=5)
        self.assertIsNone(outside.rank)
        self.assertEqual(outside.reciprocal_rank, 0.0)

    def test_answer_needs_terms_and_real_evidence(self) -> None:
        question = GoldQuestion(
            id="q1",
            scope="team",
            question="q",
            evidence_ids=("ev-1",),
            required_terms=("方案 A",),
        )
        good = score_answer("我们采用方案 A。[ev-1abcdef]", question, known_evidence_ids={"ev-1abcdef"})
        self.assertTrue(good.correct)
        missing = score_answer("还没有结论。[ev-1abcdef]", question, known_evidence_ids={"ev-1abcdef"})
        self.assertFalse(missing.correct)
        invented = score_answer("我们采用方案 A。[ev-999999ff]", question, known_evidence_ids={"ev-1abcdef"})
        self.assertFalse(invented.correct)
        self.assertEqual(invented.cited_unknown_evidence, ("ev-999999ff",))


class BuilderTest(unittest.TestCase):
    """The builder resolves anchors against real text and fails loudly."""

    def _source(self, directory: Path) -> Path:
        source = directory / "conversation.md"
        source.write_text(
            "\n".join(
                [
                    "## [2026-03-01 09:00] 张三 · agent=codex",
                    "- 决策：采用方案 A",
                    "- 待办：补齐文档",
                    "",
                    "## [2026-03-02 10:00] 李四",
                    "- 决策：改为方案 B",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return source

    def _spec(self) -> dict:
        return {
            "name": "demo",
            "sources": {"conversation": "conversation.md"},
            "member_aliases": {"张三": "张三", "李四": "李四"},
            "facts": [
                {
                    "id": "g1",
                    "kind": "decision",
                    "value": "采用方案 A",
                    "anchors": ["采用方案 A"],
                    "required_terms": ["方案 A"],
                }
            ],
            "questions": [
                {
                    "id": "q1",
                    "scope": "team",
                    "question": "采用了哪个方案？",
                    "anchors": ["采用方案 A"],
                    "required_terms": ["方案 A"],
                }
            ],
        }

    def test_builds_a_deidentified_corpus(self) -> None:
        from project_compass.eval.builder import build_corpus_from_spec

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._source(root)
            result = build_corpus_from_spec(self._spec(), source_root=root)
        corpus = result.corpus
        self.assertEqual(len(corpus.events), 2)
        self.assertEqual(len(corpus.gold.facts), 1)
        self.assertNotIn("张三", json.dumps(corpus.meta, ensure_ascii=False))
        for member_event in corpus.events:
            self.assertNotIn("张三", member_event.content)
            self.assertNotIn("李四", member_event.content)
        self.assertNotIn("张三", json.dumps(result.summary, ensure_ascii=False))

    def test_missing_anchor_fails_the_build(self) -> None:
        from project_compass.eval.builder import BuildError, build_corpus_from_spec

        spec = self._spec()
        spec["facts"][0]["anchors"] = ["不存在的原文"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._source(root)
            with self.assertRaises(BuildError):
                build_corpus_from_spec(spec, source_root=root)

    def test_required_term_must_exist_in_the_anchored_source(self) -> None:
        from project_compass.eval.builder import BuildError, build_corpus_from_spec

        spec = self._spec()
        spec["facts"][0]["required_terms"] = ["方案 Z"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._source(root)
            with self.assertRaises(BuildError):
                build_corpus_from_spec(spec, source_root=root)


class StructureLayerTest(unittest.TestCase):
    """Layer 1 guards ownership and the two layers of truth."""

    def _corpus(self, events) -> Corpus:
        return Corpus(name="demo", events=tuple(events), gold=GoldSet())

    def test_ownership_and_isolation_hold(self) -> None:
        events = [
            event("ev-1", member="member-1", content="原始内容一"),
            event("ev-2", member="member-2", content="原始内容二"),
        ]
        result = run_structure(self._corpus(events))
        self.assertTrue(result.passed)
        self.assertEqual(result.metric("evidence_owner").value, 1.0)
        self.assertEqual(result.metric("fact_isolation").value, 1.0)

    def test_a_conflict_stays_visible_in_the_team_view(self) -> None:
        events = [
            event(
                "ev-1",
                member="member-1",
                content="原始内容一",
                facts=[fact_metadata(value="采用方案 A", subject_key="decision:plan")],
            ),
            event(
                "ev-2",
                member="member-2",
                content="原始内容二",
                facts=[fact_metadata(value="采用方案 B", subject_key="decision:plan")],
            ),
        ]
        result = run_structure(self._corpus(events))
        self.assertEqual(result.metric("conflict_visibility").value, 1.0)
        self.assertIn("decision:plan", result.details["conflicted_subjects"])

    def test_nothing_is_promoted_without_a_human_record(self) -> None:
        events = [
            event(
                "ev-1",
                member="member-1",
                content="原始内容一",
                facts=[fact_metadata(value="采用方案 A", subject_key="decision:plan")],
            )
        ]
        result = run_structure(self._corpus(events))
        self.assertEqual(result.metric("no_unconfirmed_promotion").value, 1.0)
        self.assertEqual(result.metric("team_view_coverage").value, 1.0)


class ExtractionLayerTest(unittest.TestCase):
    """Layer 2 separates a weak extractor from a broken contract."""

    def _corpus(self, events) -> Corpus:
        return Corpus(name="demo", events=tuple(events), gold=GoldSet())

    def test_a_quote_outside_the_source_is_rejected(self) -> None:
        from project_compass.eval.runners import ExtractorResult

        events = [event("ev-1", content="原始内容一")]
        corpus = self._corpus(events)
        result = ExtractorResult(
            name="broken",
            payload={
                "candidates": [
                    {
                        "source_id": "ev-1",
                        "kind": "decision",
                        "subject_key": "plan",
                        "quote": "这句话并不存在于原文",
                    }
                ]
            },
        )
        outcome = extract_and_validate(corpus, result)
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(outcome.proposals, ())
        layer = run_extraction(corpus, extractor_result=result, outcome=outcome)
        self.assertFalse(layer.passed)

    def test_an_exact_quote_is_accepted_and_scored(self) -> None:
        from project_compass.eval.runners import ExtractorResult

        events = [event("ev-1", content="原始内容一，采用方案 A")]
        corpus = self._corpus(
            events
        )
        result = ExtractorResult(
            name="good",
            payload={
                "candidates": [
                    {
                        "source_id": "ev-1",
                        "kind": "decision",
                        "subject_key": "plan",
                        "quote": "采用方案 A",
                    }
                ]
            },
        )
        outcome = extract_and_validate(corpus, result)
        self.assertEqual(len(outcome.proposals), 1)
        self.assertEqual(outcome.rejected, 0)
        layer = run_extraction(corpus, extractor_result=result, outcome=outcome)
        self.assertEqual(layer.metric("contract_accept_rate").value, 1.0)
        self.assertEqual(layer.metric("evidence_attachment").value, 1.0)


class HandoffLayerTest(unittest.TestCase):
    """Layer 3 measures whether the right answer is reachable."""

    def test_a_stub_answerer_scores_against_the_gold_terms(self) -> None:
        events = [event("conv-0123456789ab", content="采用方案 A 的记录")]
        gold = GoldSet(
            questions=(
                GoldQuestion(
                    id="q1",
                    scope="team",
                    question="采用了哪个方案？",
                    evidence_ids=("conv-0123456789ab",),
                    required_terms=("方案 A",),
                ),
            )
        )
        corpus = Corpus(name="demo", events=tuple(events), gold=gold)

        class Stub:
            name = "stub"

            def answer(self, question, context):
                return Answer(text="我们采用方案 A。[conv-0123456789ab]")

        layer = run_handoff(corpus, answerer=Stub())
        self.assertEqual(layer.metric("answer_accuracy").value, 1.0)
        self.assertEqual(layer.metric("evidence_validity").value, 1.0)

    def test_the_product_answerer_runs_without_raising(self) -> None:
        events = [event("ev-1", content="采用方案 A 的记录")]
        gold = GoldSet(
            questions=(
                GoldQuestion(
                    id="q1",
                    scope="team",
                    question="采用了哪个方案？",
                    evidence_ids=("ev-1",),
                    required_terms=("方案 A",),
                ),
            )
        )
        corpus = Corpus(name="demo", events=tuple(events), gold=gold)
        layer = run_handoff(corpus, answerer=ProductAnswerer(events))
        self.assertEqual(layer.details["errors"], [])


class ContractLayerTest(unittest.TestCase):
    """Layer 4 needs a code index, which the product only just gained."""

    def test_symbols_are_located_and_callers_traced(self) -> None:
        from project_compass.code_index import build_code_index
        from project_compass.derived_context import DerivedContext

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pkg").mkdir()
            (root / "pkg" / "core.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8"
            )
            (root / "pkg" / "caller.py").write_text(
                "from pkg.core import target\n\n\ndef drive():\n    return target()\n",
                encoding="utf-8",
            )
            payload = build_code_index(root, project_id="demo")
            context = DerivedContext.from_understand_anything(
                payload, project_id="demo", project_root=str(root)
            )
            cases = [
                {
                    "id": "c1",
                    "symbol": "target",
                    "source_ref": "pkg/core.py",
                    "expected_caller_modules": ["pkg/caller.py"],
                    "expected_callee_modules": [],
                }
            ]
            layer = run_contract(context, load_contract_cases_from(cases))
        self.assertEqual(layer.metric("symbol_locatable").value, 1.0)
        self.assertEqual(layer.metric("caller_trace_recall").value, 1.0)


def load_contract_cases_from(cases: list[dict]):
    """Turn case dictionaries into contract cases without touching the disk."""
    from project_compass.eval.layers.l4_contract import ContractCase

    return [
        ContractCase(
            id=item["id"],
            symbol=item["symbol"],
            source_ref=item.get("source_ref", ""),
            expected_caller_modules=tuple(item.get("expected_caller_modules") or ()),
            expected_callee_modules=tuple(item.get("expected_callee_modules") or ()),
        )
        for item in cases
    ]


class RunnerTest(unittest.TestCase):
    """The reference extractor must quote the source exactly."""

    def test_reference_extractor_quotes_real_text(self) -> None:
        from project_compass.eval.runners import ReferenceExtractor

        events = [
            event("ev-1", content="我们决定采用方案 A。\n无关的一段闲聊。"),
            event("ev-2", content="李四负责在下周交付文档。"),
        ]
        result = ReferenceExtractor().extract(events)
        self.assertTrue(result.ok)
        for candidate_item in result.payload["candidates"]:
            source = next(item for item in events if item.id == candidate_item["source_id"])
            self.assertIn(candidate_item["quote"], source.content)

    def test_batched_extraction_respects_the_candidate_cap(self) -> None:
        from project_compass.eval.runners import BatchedExtractor, ReferenceExtractor

        content = "\n".join(f"我们决定第 {index} 件事。" for index in range(60))
        events = [event("ev-1", content=content)]
        extractor = BatchedExtractor(ReferenceExtractor(), max_chars=100000)
        result = extractor.extract(events)
        self.assertTrue(result.ok)
        self.assertLessEqual(result.candidates, 24)
        self.assertTrue(result.proposals)


class ReportTest(unittest.TestCase):
    """A report is only useful when two runs can be compared."""

    def test_compare_reports_direction(self) -> None:
        from project_compass.eval.layers.base import LayerResult, Metric

        baseline = EvalReport(
            corpus="demo",
            layers=[
                LayerResult(
                    layer="L1",
                    title="结构层",
                    metrics=(Metric("evidence_owner", 0.5, 1.0),),
                )
            ],
        )
        current = EvalReport(
            corpus="demo",
            layers=[
                LayerResult(
                    layer="L1",
                    title="结构层",
                    metrics=(Metric("evidence_owner", 1.0, 1.0),),
                )
            ],
        )
        comparison = compare(current, baseline)
        row = comparison["metrics"][0]
        self.assertEqual(row["direction"], "up")
        self.assertEqual(row["delta"], 0.5)

    def test_markdown_mentions_every_metric(self) -> None:
        from project_compass.eval.layers.base import LayerResult, Metric

        report = EvalReport(
            corpus="demo",
            layers=[
                LayerResult(
                    layer="L1",
                    title="结构层",
                    metrics=(Metric("evidence_owner", 1.0, 1.0, detail="每条证据都有归属"),),
                )
            ],
        )
        text = render_markdown(report)
        self.assertIn("evidence_owner", text)
        self.assertIn("每条证据都有归属", text)

    def test_report_round_trip(self) -> None:
        from project_compass.eval.layers.base import LayerResult, Metric

        report = EvalReport(
            corpus="demo",
            layers=[
                LayerResult(
                    layer="L1",
                    title="结构层",
                    metrics=(Metric("evidence_owner", 1.0, 1.0),),
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report.write(path)
            restored = EvalReport.load(path)
        self.assertEqual(restored.corpus, "demo")
        self.assertEqual(restored.metric("evidence_owner").value, 1.0)


class AdversarialLayerTest(unittest.TestCase):
    """Layer 5 attacks the gate and the promotion rule."""

    def _fixtures(self):
        root = Path(__file__).resolve().parent / "fixtures" / "benchmark"
        corpus = load_corpus(root / "adversarial")
        cases = load_adversarial_cases(root / "adversarial_cases.json")
        return corpus, cases

    def test_every_attack_is_blocked_and_nothing_is_promoted(self) -> None:
        from project_compass.eval.layers.l5_adversarial import run_adversarial

        corpus, cases = self._fixtures()
        layer = run_adversarial(corpus, cases)
        self.assertTrue(layer.passed)
        self.assertEqual(layer.metric("attack_rejection_rate").value, 1.0)
        self.assertEqual(layer.metric("no_promotion_under_attack").value, 1.0)
        self.assertEqual(layer.metric("injection_held_at_proposed").value, 1.0)

    def test_the_injected_instruction_becomes_a_proposal_only(self) -> None:
        from project_compass.eval.layers.l5_adversarial import run_adversarial

        corpus, cases = self._fixtures()
        layer = run_adversarial(corpus, cases)
        injection = [item for item in layer.details["cases"] if item["case"] == "injection-in-source"]
        self.assertEqual(len(injection), 1)
        self.assertGreaterEqual(injection[0]["proposals"], 1)
        self.assertEqual(injection[0]["promoted_to_team_truth"], [])

    def test_a_fabricated_quote_is_blocked(self) -> None:
        from project_compass.eval.layers.l5_adversarial import run_adversarial

        corpus, cases = self._fixtures()
        layer = run_adversarial(corpus, cases)
        fabricated = [item for item in layer.details["cases"] if item["case"] == "fabricated-quote"]
        self.assertTrue(fabricated[0]["blocked"])
        self.assertTrue(fabricated[0]["error"])


class CommittedCorpusTest(unittest.TestCase):
    """The corpus committed to the repository must stay usable and clean."""

    def test_corpus_loads_with_its_gold_set(self) -> None:
        root = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "easy-course-picker"
        if not (root / "events.json").exists():
            self.skipTest("the benchmark corpus has not been built in this checkout")
        corpus = load_corpus(root)
        self.assertGreaterEqual(len(corpus.gold.facts), 10)
        self.assertGreaterEqual(len(corpus.gold.questions), 10)
        self.assertTrue(corpus.gold.questions_for_scope("team"))
        self.assertTrue(corpus.gold.questions_for_scope("personal"))

    def test_corpus_carries_no_real_member_names(self) -> None:
        root = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "easy-course-picker"
        if not (root / "events.json").exists():
            self.skipTest("the benchmark corpus has not been built in this checkout")
        corpus = load_corpus(root)
        for member_event in corpus.events:
            self.assertNotIn("member-3", member_event.metadata.get("member_id", ""))
            self.assertNotIn("@", member_event.content.split(" ")[0])

    def test_contract_expectations_are_loadable(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "benchmark"
            / "contract_chains.json"
        )
        cases = load_contract_cases(path)
        self.assertTrue(cases)
        for case in cases:
            self.assertTrue(case.symbol)


class PBRRegressionTest(unittest.TestCase):
    """Regression tests T1-T6 and harness contract checks from the PBR review."""

    def test_t1_empty_answer_fails_l3_answers_produced(self) -> None:
        class EmptyAnswerer:
            name = "empty-answerer"

            def answer(self, question, context):
                return Answer(text="")

        corpus = Corpus(
            name="empty-answer",
            events=(event("ev-1", content="我们决定使用 SQLite 存储状态。"),),
            gold=GoldSet(
                questions=(
                    GoldQuestion(
                        id="q-1",
                        scope="team",
                        question="用什么存储状态？",
                        evidence_ids=("ev-1",),
                        required_terms=("SQLite",),
                    ),
                )
            ),
        )
        layer = run_handoff(corpus, answerer=EmptyAnswerer())
        by_name = {m.name: m for m in layer.metrics}
        self.assertIn("answers_produced", by_name)
        self.assertTrue(by_name["answers_produced"].hard)
        self.assertEqual(by_name["answers_produced"].value, 0.0)
        self.assertFalse(layer.passed)

    def test_t2_accepted_fact_without_review_fails_l1_without_crash(self) -> None:
        from unittest.mock import patch

        ev = event("ev-acc", content="直接写入已确认状态")
        corpus = Corpus(name="unreviewed", events=(ev,), gold=GoldSet())
        fake_views = {
            "personal": {
                "member-1": {"evidence_ids": ["ev-acc"], "facts": []},
            },
            "team": {
                "facts": [
                    {
                        "id": "fact-unreviewed",
                        "status": "accepted",
                        "subject_key": "storage",
                    }
                ],
                "conflicts": [],
            },
        }
        with patch("project_compass.projections.build_views", return_value=fake_views):
            layer = run_structure(corpus)
        by_name = {m.name: m for m in layer.metrics}
        self.assertEqual(by_name["no_unconfirmed_promotion"].value, 0.0)
        self.assertFalse(layer.passed)

    def test_t3_wrong_rejection_reason_fails_l5_case(self) -> None:
        from project_compass.eval.layers.l5_adversarial import AdversarialCase, run_adversarial

        corpus = Corpus(
            name="adv-reason",
            events=(event("conv-1", content="合法引文内容在这里。"),),
            gold=GoldSet(),
        )
        case = AdversarialCase(
            id="wrong-reason-case",
            name="错误理由测试",
            expectation="reject",
            source_id="conv-1",
            kind="decision",
            subject_key="plan",
            quote="不存在的引文",
            expected_reason="some unrelated validation error",
        )
        layer = run_adversarial(corpus, [case])
        by_name = {m.name: m for m in layer.metrics}
        self.assertEqual(by_name["attack_rejection_rate"].value, 0.0)
        self.assertFalse(layer.passed)
        self.assertFalse(layer.details["cases"][0]["blocked"])

    def test_t4_dual_gate_decouples_red_line_and_quality_grade(self) -> None:
        from project_compass.eval.layers.base import HIGHER, LayerResult, Metric

        l1 = LayerResult(
            layer="L1",
            title="结构层",
            metrics=(Metric("no_crash", 1.0, 1.0, HIGHER, hard=True),),
        )
        l2 = LayerResult(
            layer="L2",
            title="抽取层",
            metrics=(
                Metric("candidate_gate_pass", 1.0, 1.0, HIGHER, hard=True),
                Metric("f1", 0.2, 0.5, HIGHER, hard=False),
            ),
        )
        report = EvalReport(corpus="dual-gate", track={"extractor": "ref"}, layers=(l1, l2))
        self.assertTrue(report.passed)
        scorecard = report.quality_scorecard
        self.assertFalse(scorecard["quality_passed"])
        self.assertEqual(scorecard["tier"], "Tier 3 (Baseline)")
        payload = report.to_dict()
        self.assertTrue(payload["red_line_passed"])
        self.assertIn("quality_grade", payload)
        md = render_markdown(report)
        self.assertIn("Red-Line Gate", md)
        self.assertIn("Quality Grade", md)

    def test_t5_missing_required_fixtures_fail_cli_exit_code(self) -> None:
        from project_compass.eval.__main__ import main as eval_main

        root = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "easy-course-picker"
        if not (root / "events.json").exists():
            self.skipTest("easy-course-picker corpus not present")
        rc = eval_main(
            [
                "run",
                "--corpus",
                str(root),
                "--contracts",
                str(root / "nonexistent_contracts.json"),
                "--adversarial-cases",
                str(root / "nonexistent_adversarial.json"),
            ]
        )
        self.assertEqual(rc, 1)

    def test_t6_deidentifier_pre_issues_aliases_for_body_mentions(self) -> None:
        from project_compass.eval.adapters import conversation_events, parse_sync_conversation

        raw = (
            "## [2026-03-01 09:00] Alice · agent=codex\n"
            "- 进展：与 Bob 讨论了接口定义。\n\n"
            "## [2026-03-01 10:00] Bob · agent=claude\n"
            "- 进展：确认接口。\n"
        )
        entries = parse_sync_conversation(raw)
        deid = Deidentifier()
        deid.register_labels({"Alice": "Alice", "Bob": "Bob"})
        events = conversation_events(entries, deidentifier=deid, source_ref="sync.md")
        self.assertNotIn("Bob", events[0].content)
        self.assertNotIn("Alice", events[0].content)
        self.assertIn("member-2", events[0].content)

    def test_p1e_harness_stdin_stdout_contract(self) -> None:
        import io
        from unittest.mock import patch
        from project_compass.eval import harness

        extract_req = json.dumps({"task": "extract", "sources": [{"id": "s1", "content": "hello"}]})
        out = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(extract_req)),
            patch("sys.stdout", out),
            patch.object(harness, "_call_cli", return_value='{"candidates": [{"source_id": "s1"}]}'),
        ):
            rc = harness.main(["custom"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), {"candidates": [{"source_id": "s1"}]})

        answer_req = json.dumps({"task": "answer", "question": "why?", "context": {"k": "v"}})
        out2 = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(answer_req)),
            patch("sys.stdout", out2),
            patch.object(harness, "_call_cli", return_value="  because ev-1  "),
        ):
            rc2 = harness.main(["custom"])
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(out2.getvalue()), {"answer": "because ev-1"})

    def test_p1j_gold_validation_requires_non_empty_terms(self) -> None:
        with self.assertRaises(GoldError):
            GoldFact.from_dict(
                {
                    "id": "gf-empty",
                    "kind": "decision",
                    "value": "val",
                    "evidence_ids": ["ev-1"],
                    "required_terms": [],
                }
            )
        with self.assertRaises(GoldError):
            GoldQuestion.from_dict(
                {
                    "id": "gq-empty",
                    "scope": "team",
                    "question": "what?",
                    "evidence_ids": ["ev-1"],
                    "required_terms": [],
                    "accepted_answers": [],
                }
            )

    def test_p1k_score_extraction_uses_maximum_bipartite_matching(self) -> None:
        # g1 matches p1 and p2; g2 matches only p1. Greedy would pair g1->p1 and miss g2.
        g1 = GoldFact(
            id="g1",
            kind="decision",
            subject_key="k1",
            value="alpha",
            evidence_ids=("ev-1",),
            required_terms=("alpha",),
        )
        g2 = GoldFact(
            id="g2",
            kind="decision",
            subject_key="k2",
            value="alpha beta",
            evidence_ids=("ev-1",),
            required_terms=("alpha", "beta"),
        )
        p1 = CandidateFact(
            id="p1",
            kind=FactKind.DECISION,
            subject_key="k2",
            value="alpha beta",
            status=FactStatus.PROPOSED,
            author="member-1",
            evidence_ids=["ev-1"],
            observed_at=OBSERVED,
            quote="alpha beta",
        )
        p2 = CandidateFact(
            id="p2",
            kind=FactKind.DECISION,
            subject_key="k1",
            value="alpha",
            status=FactStatus.PROPOSED,
            author="member-1",
            evidence_ids=["ev-1"],
            observed_at=OBSERVED,
            quote="alpha",
        )
        score = score_extraction([p1, p2], [g1, g2])
        self.assertEqual(score.matched, 2)
        self.assertEqual(score.missed, ())


class M0EvalIntegrityTest(unittest.TestCase):
    """Ensure benchmark integrity fixes from M0 hold across extractor/answerer paths."""

    def test_batched_extractor_reports_inner_name_and_default_runner_works(self) -> None:
        from project_compass.eval.runners import BatchedExtractor, ReferenceExtractor, default_runner

        batched = BatchedExtractor(ReferenceExtractor())
        self.assertEqual(batched.name, "reference-rules-v1")
        default = default_runner()
        self.assertEqual(default.name, "reference-rules-v1")

    def test_product_answerer_does_not_dump_unrelated_active_tasks_and_assumptions(self) -> None:
        # Build an event with many proposed tasks/assumptions; answer must stay focused
        facts_meta = [
            {
                "kind": "goal",
                "subject_key": "goal:main",
                "value": "完成核心看板",
                "quote": "完成核心看板",
            },
            {
                "kind": "task",
                "subject_key": "task:unrelated-noise",
                "value": "无关嘈杂待办哨兵词XYZZY",
                "quote": "无关嘈杂待办哨兵词XYZZY",
                "task_state": "pending",
            },
            {
                "kind": "assumption",
                "subject_key": "assumption:unrelated-noise",
                "value": "无关嘈杂前提哨兵词QWERTY",
                "quote": "无关嘈杂前提哨兵词QWERTY",
            },
            {
                "kind": "decision",
                "subject_key": "decision:storage",
                "value": "决定使用纯标准库方案",
                "quote": "决定使用纯标准库方案",
            },
        ]
        ev = event("ev-focus", content="完成核心看板；决定使用纯标准库方案。", facts=facts_meta)
        # Fill 4 extra recent task events so unrelated task is pushed out of top 3 findings
        extras = [
            event(
                f"ev-extra-{idx}",
                content=f"决定补充文档第 {idx} 项",
                facts=[
                    {
                        "kind": "decision",
                        "subject_key": f"decision:extra-{idx}",
                        "value": f"决定补充文档第 {idx} 项",
                        "quote": f"决定补充文档第 {idx} 项",
                    }
                ],
            )
            for idx in range(4)
        ]
        answerer = ProductAnswerer([ev, *extras])
        answer = answerer.answer("团队做了什么决定，为什么？", {})
        self.assertNotIn("无关嘈杂前提哨兵词QWERTY", answer.text)
        ranked = answerer.rank_for_question("团队做了什么决定，为什么？")
        self.assertIsInstance(ranked, list)

    def test_vacuous_conflict_metrics_are_labeled(self) -> None:
        ev = event(
            "ev-no-conflict",
            content="我们决定使用标准库。",
            facts=[{"kind": "decision", "subject_key": "d1", "value": "使用标准库", "quote": "使用标准库"}],
        )
        corpus = Corpus(name="no-conflict", events=(ev,), gold=GoldSet())
        l1 = run_structure(corpus)
        detail = l1.metric("conflict_visibility").detail
        self.assertIn("空洞通过", detail)
        self.assertTrue(any("vacuous_conflict_check" in note for note in l1.notes))

    def test_eval_cli_supports_builtin_extractor_and_records_provenance(self) -> None:
        from project_compass.eval.__main__ import main as eval_main

        root = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "easy-course-picker"
        if not (root / "events.json").exists():
            self.skipTest("easy-course-picker corpus not present")
        with tempfile.TemporaryDirectory() as directory:
            out_json = Path(directory) / "builtin_report.json"
            rc = eval_main(
                [
                    "run",
                    "--corpus",
                    str(root),
                    "--extractor",
                    "builtin",
                    "--out",
                    str(out_json),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["track"]["extractor"], "builtin-rules")
            self.assertTrue(payload["track"].get("gold_sha256"))
            self.assertTrue(payload["track"].get("git_sha"))


if __name__ == "__main__":
    unittest.main()
