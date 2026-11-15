"""Command line entry point for the ProjectCompass evaluation benchmark.

::

    python -m project_compass.eval build --spec ... --source-root ... --out ...
    python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker
    python -m project_compass.eval run --corpus ... --harness claude --out report.json

``run`` without ``--harness`` uses the deterministic track: no model is called,
so the result is reproducible and belongs in CI. ``run --harness NAME`` adds
the model track on top of it.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

from .build_cli import main as build_main
from .corpus import load_corpus
from .layers.base import HIGHER, LayerResult, Metric
from .layers.l1_structure import run_structure
from .layers.l2_extraction import run_extraction
from .layers.l3_handoff import AgentAnswerer, ProductAnswerer, run_handoff
from .layers.l4_contract import load_contract_cases, run_contract
from .layers.l5_adversarial import load_adversarial_cases, run_adversarial
from .report import EvalReport, compare, render_markdown

DEFAULT_CORPUS = "tests/fixtures/benchmark/easy-course-picker"
DEFAULT_CONTRACTS = "tests/fixtures/benchmark/contract_chains.json"
DEFAULT_ADVERSARIAL_CORPUS = "tests/fixtures/benchmark/adversarial"
DEFAULT_ADVERSARIAL_CASES = "tests/fixtures/benchmark/adversarial_cases.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project_compass.eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a de-identified corpus")
    build.add_argument("--spec", required=True, help="path to the corpus specification")
    build.add_argument("--source-root", required=True, help="root of the real project material")
    build.add_argument("--out", required=True, help="output directory for the corpus")
    build.add_argument("--report", default=None, help="path of the de-identification summary")
    build.set_defaults(handler=_handle_build)

    run = sub.add_parser("run", help="run the evaluation layers")
    run.add_argument("--corpus", default=DEFAULT_CORPUS, help="corpus directory")
    run.add_argument(
        "--contracts",
        default=DEFAULT_CONTRACTS,
        help="contract expectation file for the structure layer",
    )
    run.add_argument(
        "--source-root",
        default=".",
        help="root of the project source tree to index for the contract layer",
    )
    run.add_argument(
        "--extractor",
        choices=("reference", "builtin"),
        default="reference",
        help="deterministic extractor track when --harness is not set (default: reference)",
    )
    run.add_argument(
        "--harness",
        default=None,
        help="name of an external harness preset (for example claude) to add the model track",
    )
    run.add_argument(
        "--harness-command",
        default=None,
        help="explicit command for the harness, as one shell-free argument string",
    )
    run.add_argument(
        "--adversarial-corpus",
        default=DEFAULT_ADVERSARIAL_CORPUS,
        help="corpus used by the adversarial layer",
    )
    run.add_argument(
        "--adversarial-cases",
        default=DEFAULT_ADVERSARIAL_CASES,
        help="attack expectation file for the adversarial layer",
    )
    run.add_argument("--out", default=None, help="write the JSON report here")
    run.add_argument("--markdown", default=None, help="write the Markdown report here")
    run.add_argument("--baseline", default=None, help="compare against this report")
    run.set_defaults(handler=_handle_run)

    return parser


def _handle_build(args) -> int:
    argv = [
        "--spec",
        args.spec,
        "--source-root",
        args.source_root,
        "--out",
        args.out,
    ]
    if args.report:
        argv.extend(["--report", args.report])
    return build_main(argv)


def _git_short_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        sha = (proc.stdout or "").strip()
        return sha or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _gold_sha256_prefix(corpus_dir: str | Path) -> str:
    gold_path = Path(corpus_dir) / "gold.json"
    if not gold_path.exists():
        return "unknown"
    return sha256(gold_path.read_bytes()).hexdigest()[:12]


def _handle_run(args) -> int:
    from ..code_index import CodeIndexError, build_code_index
    from ..derived_context import DerivedContext, DerivedContextError
    from .layers.l2_extraction import extract_and_validate
    from .runners import BatchedExtractor, CommandRunner, ReferenceExtractor, RunnerSpec, builtin_rule_extractor

    corpus = load_corpus(args.corpus)
    layers = []
    track: dict[str, str] = {
        "git_sha": _git_short_sha(),
        "gold_sha256": _gold_sha256_prefix(args.corpus),
    }

    if args.harness:
        command = args.harness_command.split() if args.harness_command else None
        if command:
            runner = CommandRunner(RunnerSpec(name=args.harness, command=tuple(command)))
        else:
            from .runners import HARNESS_PRESETS

            preset = HARNESS_PRESETS.get(args.harness)
            if preset is None:
                print(f"unknown harness preset: {args.harness}", file=sys.stderr)
                return 1
            runner = CommandRunner(RunnerSpec(name=args.harness, command=preset))
        extractor = BatchedExtractor(runner)
        answerer = AgentAnswerer(runner)
        track["extractor"] = args.harness
        track["answerer"] = args.harness
        extractor_result = extractor.extract(list(corpus.events))
    elif getattr(args, "extractor", "reference") == "builtin":
        answerer = None
        extractor_result = builtin_rule_extractor(list(corpus.events))
        track["extractor"] = extractor_result.name
        track["answerer"] = "product-investigator"
    else:
        extractor = BatchedExtractor(ReferenceExtractor())
        answerer = None
        track["extractor"] = extractor.name
        track["answerer"] = "product-investigator"
        extractor_result = extractor.extract(list(corpus.events))

    outcome = extract_and_validate(corpus, extractor_result)
    enriched = [*corpus.events, *outcome.proposals]

    layers.append(run_structure(corpus, events=enriched))
    layers.append(run_extraction(corpus, extractor_result=extractor_result, outcome=outcome))

    contract_path = Path(args.contracts)
    if contract_path.exists():
        try:
            payload = build_code_index(args.source_root, project_id="project-compass")
            context = DerivedContext.from_understand_anything(
                payload, project_id="project-compass", project_root=args.source_root
            )
        except (CodeIndexError, DerivedContextError, ValueError) as exc:
            print(f"code index failed: {exc}", file=sys.stderr)
            layers.append(
                LayerResult(
                    layer="L4",
                    title="契约层：调用链追踪",
                    metrics=(
                        Metric(
                            "index_ready",
                            0.0,
                            1.0,
                            HIGHER,
                            hard=True,
                            detail=f"代码索引构建失败: {exc}",
                        ),
                    ),
                    notes=(f"L4 skipped due to index error: {exc}",),
                )
            )
        else:
            layers.append(run_contract(context, load_contract_cases(contract_path)))
    else:
        print(f"contract expectations not found at {contract_path}; L4 failed", file=sys.stderr)
        layers.append(
            LayerResult(
                layer="L4",
                title="契约层：调用链追踪",
                metrics=(
                    Metric(
                        "fixtures_present",
                        0.0,
                        1.0,
                        HIGHER,
                        hard=True,
                        detail=f"缺失必需的 L4 契约夹具: {contract_path}",
                    ),
                ),
            )
        )

    layers.append(
        run_handoff(
            corpus,
            events=enriched,
            answerer=answerer or ProductAnswerer(enriched),
        )
    )

    adversarial_path = Path(args.adversarial_cases)
    adversarial_corpus_path = Path(args.adversarial_corpus)
    if adversarial_path.exists() and (adversarial_corpus_path / "events.json").exists():
        adversarial_corpus = load_corpus(adversarial_corpus_path)
        layers.append(
            run_adversarial(adversarial_corpus, load_adversarial_cases(adversarial_path))
        )
    else:
        print(
            f"adversarial fixtures not found at {adversarial_path}; L5 failed",
            file=sys.stderr,
        )
        layers.append(
            LayerResult(
                layer="L5",
                title="对抗层：投毒、未核准写入与超界访问",
                metrics=(
                    Metric(
                        "fixtures_present",
                        0.0,
                        1.0,
                        HIGHER,
                        hard=True,
                        detail=f"缺失必需的 L5 对抗夹具: {adversarial_path}",
                    ),
                ),
            )
        )
    layers.sort(key=lambda layer: layer.layer)

    report = EvalReport(corpus=corpus.name, track=track, layers=layers)
    comparison = None
    if args.baseline and Path(args.baseline).exists():
        comparison = compare(report, EvalReport.load(args.baseline))

    if args.out:
        report.write(args.out)
    if args.markdown:
        target = Path(args.markdown)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(report, comparison=comparison), encoding="utf-8")

    for layer in layers:
        state = "PASS" if layer.passed else "FAIL"
        print(f"[{state}] {layer.layer} {layer.title}")
        for metric in layer.metrics:
            mark = "ok" if metric.passed else ("--" if not metric.hard else "!!")
            print(f"       {mark} {metric.name} = {metric.value:.4f} ({metric.detail})")
    scorecard = report.quality_scorecard
    print(f"red_line_gate: {'PASS' if report.passed else 'FAIL'}")
    print(
        f"quality_grade: {scorecard['tier']} ({scorecard['score']:.1f}/100, "
        f"{'PASS' if scorecard['quality_passed'] else 'NEEDS_IMPROVEMENT'})"
    )
    print(f"overall: {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
