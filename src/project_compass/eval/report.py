"""Assemble evaluation results into a comparable, reviewable report.

A benchmark only helps if two runs can be compared. The report keeps every
number keyed by layer and metric name, so a later run can be diffed against
a baseline without anybody re-reading the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from .layers.base import LayerResult

REPORT_FORMAT = "project-compass-eval-report"
REPORT_VERSION = 1


@dataclass
class EvalReport:
    """One complete evaluation run."""

    corpus: str
    track: dict = field(default_factory=dict)
    layers: list[LayerResult] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(layer.passed for layer in self.layers)

    @property
    def quality_scorecard(self) -> dict:
        """Compute independent quality grade from non-hard (intelligence) metrics."""
        core_names = (
            "extraction_f1",
            "evidence_coverage",
            "retrieval_hit_rate",
            "answer_accuracy",
        )
        found = []
        for name in core_names:
            m = self.metric(name)
            if m is not None:
                found.append(m.value)
        if not found:
            soft = [
                metric.value
                for layer in self.layers
                for metric in layer.metrics
                if not metric.hard
            ]
            found = soft
        score = round((sum(found) / len(found)) * 100.0, 2) if found else 0.0
        if score >= 75.0:
            tier = "Tier 1 (Production Ready)"
        elif score >= 45.0:
            tier = "Tier 2 (Developing)"
        else:
            tier = "Tier 3 (Baseline)"
        return {
            "score": score,
            "tier": tier,
            "quality_passed": score >= 60.0,
            "metrics_counted": len(found),
        }

    def metric(self, name: str):
        for layer in self.layers:
            metric = layer.metric(name)
            if metric is not None:
                return metric
        return None

    def to_dict(self) -> dict:
        hard = [
            metric
            for layer in self.layers
            for metric in layer.metrics
            if metric.hard
        ]
        q_card = self.quality_scorecard
        return {
            "format": REPORT_FORMAT,
            "version": REPORT_VERSION,
            "corpus": self.corpus,
            "generated_at": self.generated_at,
            "track": dict(self.track),
            "passed": self.passed,
            "red_line_passed": self.passed,
            "quality_grade": q_card,
            "summary": {
                "layers": len(self.layers),
                "layers_passed": sum(1 for layer in self.layers if layer.passed),
                "hard_metrics_passed": sum(1 for metric in hard if metric.passed),
                "hard_metrics_total": len(hard),
                "quality_score": q_card["score"],
                "quality_tier": q_card["tier"],
            },
            "layers": [layer.to_dict() for layer in self.layers],
            "notes": list(self.notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "EvalReport":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != REPORT_FORMAT:
            raise ValueError("unsupported report format")
        layers = []
        for item in payload.get("layers", []):
            metrics = tuple(
                _metric_from_dict(metric) for metric in item.get("metrics", [])
            )
            layers.append(
                LayerResult(
                    layer=item.get("layer", ""),
                    title=item.get("title", ""),
                    metrics=metrics,
                    details=item.get("details") or {},
                    notes=tuple(item.get("notes") or ()),
                )
            )
        return cls(
            corpus=payload.get("corpus", ""),
            track=payload.get("track") or {},
            layers=layers,
            generated_at=payload.get("generated_at", ""),
            notes=list(payload.get("notes") or []),
        )


def _metric_from_dict(payload: dict):
    from .layers.base import Metric

    return Metric(
        name=payload.get("name", ""),
        value=float(payload.get("value", 0.0)),
        threshold=float(payload.get("threshold", 0.0)),
        direction=payload.get("direction", "higher"),
        hard=bool(payload.get("hard", True)),
        detail=payload.get("detail", ""),
    )


def compare(report: EvalReport, baseline: EvalReport) -> dict:
    """Diff two runs metric by metric.

    The comparison is deliberately about direction, not about raw numbers: a
    metric that should go up and grew is an improvement, and one that should
    go down and shrank is an improvement too.
    """
    current = {
        (layer.layer, metric.name): metric for layer in report.layers for metric in layer.metrics
    }
    previous = {
        (layer.layer, metric.name): metric for layer in baseline.layers for metric in layer.metrics
    }
    rows = []
    for key in sorted(current):
        now = current[key]
        before = previous.get(key)
        if before is None:
            rows.append(
                {
                    "layer": key[0],
                    "metric": key[1],
                    "baseline": None,
                    "current": now.value,
                    "delta": None,
                    "direction": "new",
                }
            )
            continue
        delta = now.value - before.value
        if now.direction == "higher":
            trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        else:
            trend = "down" if delta < 0 else "up" if delta > 0 else "flat"
        rows.append(
            {
                "layer": key[0],
                "metric": key[1],
                "baseline": before.value,
                "current": now.value,
                "delta": round(delta, 4),
                "direction": trend,
            }
        )
    return {
        "baseline_at": baseline.generated_at,
        "current_at": report.generated_at,
        "metrics": rows,
    }


def render_markdown(report: EvalReport, *, comparison: dict | None = None) -> str:
    """Render a report as Markdown that a reviewer can read without the code."""
    lines: list[str] = []
    lines.append(f"# Compass 测评报告 · {report.corpus}")
    lines.append("")
    q_card = report.quality_scorecard
    lines.append(f"- 运行时间：{report.generated_at}")
    lines.append(f"- 安全红线闸门 (Red-Line Gate)：{'PASS（通过，零越权/零崩溃）' if report.passed else 'FAIL（未通过）'}")
    lines.append(f"- 智能质量评级 (Quality Grade)：{q_card['score']:.2f} / 100 · {q_card['tier']}")
    track = report.track
    if track:
        described = "，".join(f"{key}={value}" for key, value in sorted(track.items()))
        lines.append(f"- 轨道：{described}")
    lines.append("")

    for layer in report.layers:
        state = "通过" if layer.passed else "未通过"
        lines.append(f"## {layer.layer} {layer.title} — {state}")
        lines.append("")
        lines.append("| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |")
        lines.append("|---|---|---|---|---|---|---|")
        for metric in layer.metrics:
            lines.append(
                f"| `{metric.name}` | {metric.value:.4f} | {metric.threshold} | "
                f"{metric.direction} | {'是' if metric.hard else '否'} | "
                f"{'通过' if metric.passed else '未通过'} | {metric.detail} |"
            )
        lines.append("")
        for note in layer.notes:
            lines.append(f"> {note}")
        if layer.notes:
            lines.append("")

    if comparison:
        lines.append("## 与基线对比")
        lines.append("")
        lines.append("| 层 | 指标 | 基线 | 当前 | 变化 | 走向 |")
        lines.append("|---|---|---|---|---|---|")
        for row in comparison.get("metrics", []):
            baseline = row["baseline"]
            delta = row["delta"]
            lines.append(
                f"| {row['layer']} | `{row['metric']}` | "
                f"{'-' if baseline is None else f'{baseline:.4f}'} | {row['current']:.4f} | "
                f"{'-' if delta is None else f'{delta:+.4f}'} | {row['direction']} |"
            )
        lines.append("")

    if report.notes:
        lines.append("## 备注")
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
