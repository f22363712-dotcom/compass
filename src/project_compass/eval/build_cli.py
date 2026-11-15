"""Build a de-identified benchmark corpus from an authored specification.

Usage::

    python -m project_compass.eval build \
        --spec tests/fixtures/benchmark/local-specs/easy_course_picker.json \
        --source-root "D:/Projects/easy-course-picker" \
        --out tests/fixtures/benchmark/easy-course-picker

The specification names facts and questions that a human believes the product
should find, anchored to distinctive text in the real source material. The
builder resolves every anchor against the raw source and fails loudly when an
anchor cannot be found, so a gold set can never drift away from reality.

The specification itself names real people and therefore stays outside the
repository: only the de-identified corpus is committed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .builder import BuildError, build_corpus_from_spec, load_spec
from .corpus import write_corpus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project_compass.eval build", description=__doc__)
    parser.add_argument("--spec", required=True, help="path to the corpus specification")
    parser.add_argument("--source-root", required=True, help="root of the real project material")
    parser.add_argument("--out", required=True, help="output directory for the corpus")
    parser.add_argument(
        "--report",
        default=None,
        help="optional path for the commit-safe de-identification summary "
        "(defaults to <out>/deidentification.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = load_spec(args.spec)
    try:
        result = build_corpus_from_spec(spec, source_root=args.source_root)
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    write_corpus(out, result.corpus)
    report_path = Path(args.report) if args.report else out / "deidentification.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {"anchors": result.anchor_report, "deidentification": result.summary},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = result.summary
    print(f"corpus: {result.corpus.name}")
    print(f"  entries parsed : {result.anchor_report['entries']}")
    print(f"  events written : {result.anchor_report['events']}")
    print(f"  gold facts     : {result.anchor_report['facts']}")
    print(f"  gold questions : {result.anchor_report['questions']}")
    print(f"  members        : {summary['member_count']}")
    print(f"  replacements   : {summary['total_replacements']}")
    print(f"  output         : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
