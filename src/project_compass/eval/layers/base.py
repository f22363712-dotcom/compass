"""Shared result types for the evaluation layers.

A layer measures one dimension of the product. Every metric carries its own
threshold and direction, so a layer can be judged without reading the code
that produced it. A metric marked ``hard`` must pass for the layer to pass;
soft metrics are recorded for ranking and iteration, not for gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HIGHER = "higher"
LOWER = "lower"


@dataclass(frozen=True)
class Metric:
    """One measured number with the bar it has to clear."""

    name: str
    value: float
    threshold: float
    direction: str = HIGHER
    hard: bool = True
    detail: str = ""

    @property
    def passed(self) -> bool:
        if self.direction == HIGHER:
            return self.value >= self.threshold
        return self.value <= self.threshold

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(float(self.value), 4),
            "threshold": self.threshold,
            "direction": self.direction,
            "hard": self.hard,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LayerResult:
    """The outcome of one evaluation layer."""

    layer: str
    title: str
    metrics: tuple[Metric, ...] = ()
    details: dict = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(metric.passed for metric in self.metrics if metric.hard)

    def metric(self, name: str) -> Metric | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "title": self.title,
            "passed": self.passed,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "details": self.details,
            "notes": list(self.notes),
        }


def ratio(numerator: int, denominator: int) -> float:
    """Return a safe ratio; an empty denominator is zero, never an error."""
    if not denominator:
        return 0.0
    return numerator / denominator
