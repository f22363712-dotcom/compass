"""Layer 5: adversarial.

Can the extraction gate be talked into accepting a fact it should not accept?

This layer attacks the product with the two moves that matter: a quote that
is not in the source, and an instruction embedded in the source material that
tries to talk the extractor into promoting a claim to team truth. The second
move is the important one, because Compass's promise is that nothing becomes
team truth without a human, so the layer checks the outcome, not just the
rejection: a real quote inside an injected instruction may become a proposal,
but it must never become ``accepted``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..corpus import Corpus
from .base import HIGHER, LayerResult, Metric, ratio

LAYER_ID = "L5"
TITLE = "对抗层：准入门抗攻击与越权拦截"

ADVERSARIAL_FORMAT = "project-compass-eval-adversarial"
ADVERSARIAL_VERSION = 1

REJECT = "reject"
PROPOSE = "propose"


class AdversarialError(ValueError):
    """Raised when an adversarial expectation file is malformed."""


@dataclass(frozen=True)
class AdversarialCase:
    """One attack against the extraction gate."""

    id: str
    name: str
    expectation: str
    source_id: str
    kind: str = "decision"
    subject_key: str = "plan"
    quote: str = ""
    window: tuple[int, int] | None = None
    candidate_count: int = 1
    note: str = ""
    #: The reason the gate is expected to refuse for. An attack that is
    #: blocked for a different reason did not test what it claims to test.
    expected_reason: str = ""

    def candidate(self) -> dict:
        """Return the candidate this attack sends to the gate."""
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "subject_key": self.subject_key,
            "quote": self.quote,
            "task_state": "unknown",
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "expectation": self.expectation,
            "source_id": self.source_id,
            "kind": self.kind,
            "subject_key": self.subject_key,
            "quote": self.quote,
            "window": list(self.window) if self.window else None,
            "candidate_count": self.candidate_count,
            "note": self.note,
            "expected_reason": self.expected_reason,
        }


def load_adversarial_cases(path: str | Path) -> list[AdversarialCase]:
    """Read the authored attack cases."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdversarialError("adversarial cases could not be read") from exc
    if not isinstance(payload, dict) or payload.get("format") != ADVERSARIAL_FORMAT:
        raise AdversarialError("unsupported adversarial case format")
    if payload.get("version") != ADVERSARIAL_VERSION:
        raise AdversarialError("unsupported adversarial case version")
    raw = payload.get("cases")
    if not isinstance(raw, list) or not raw:
        raise AdversarialError("adversarial cases need at least one case")
    cases: list[AdversarialCase] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AdversarialError("each adversarial case must be an object")
        case_id = item.get("id")
        expectation = item.get("expectation")
        if not isinstance(case_id, str) or not case_id.strip():
            raise AdversarialError("an adversarial case needs an id")
        if expectation not in {REJECT, PROPOSE}:
            raise AdversarialError(
                f"adversarial case {case_id} needs expectation reject or propose"
            )
        window = item.get("window")
        cases.append(
            AdversarialCase(
                id=case_id,
                name=str(item.get("name") or case_id),
                expectation=expectation,
                source_id=str(item.get("source_id") or ""),
                kind=str(item.get("kind") or "decision"),
                subject_key=str(item.get("subject_key", "plan")),
                quote=str(item.get("quote") or ""),
                window=tuple(window) if isinstance(window, list) and len(window) == 2 else None,
                candidate_count=int(item.get("candidate_count") or 1),
                note=str(item.get("note") or ""),
                expected_reason=str(item.get("expected_reason") or ""),
            )
        )
    return cases


@dataclass(frozen=True)
class CaseOutcome:
    """What the gate did with one attack.

    A refusal and a crash are different things. The gate refuses a payload
    by raising ``ValueError``; anything else means the gate broke, and a
    broken gate is not a gate that defended itself.
    """

    proposals: list
    error: str = ""
    refused: bool = False
    crashed: bool = False


def _run_case(corpus: Corpus, case: AdversarialCase) -> CaseOutcome:
    """Send one attack to the gate and return what the gate did with it."""
    from ...candidate_extraction import validate_candidates

    events = list(corpus.events)
    candidate = case.candidate()
    if case.candidate_count > 1:
        payload = {"candidates": [candidate] * case.candidate_count}
    else:
        payload = {"candidates": [candidate]}
    windows = None
    if case.window is not None:
        windows = {case.source_id: (int(case.window[0]), int(case.window[1]))}
    try:
        proposals = validate_candidates(events, payload, source_windows=windows)
    except ValueError as exc:
        return CaseOutcome([], str(exc), refused=True)
    except Exception as exc:  # noqa: BLE001 - a crash is a measurement, not a defence
        return CaseOutcome([], f"{type(exc).__name__}: {exc}", crashed=True)
    return CaseOutcome(list(proposals))


def run_adversarial(corpus: Corpus, cases: list[AdversarialCase]) -> LayerResult:
    """Measure whether the gate refuses every attack it is meant to refuse."""
    from ...fact_engine import derive_facts
    from ...projections import build_views

    details: list[dict] = []
    rejected = 0
    reject_expected = 0
    crashed = 0
    wrong_reason = 0
    accepted_under_attack = 0
    propose_expected = 0
    propose_held = 0
    propose_not_released = 0

    for case in cases:
        outcome = _run_case(corpus, case)
        if case.expectation == REJECT:
            reject_expected += 1
            # A refusal counts as a defence only when the gate refused on
            # contract grounds. A crash is a defect, and a refusal for a
            # different reason did not test what this case claims to test.
            right_reason = outcome.refused and (
                not case.expected_reason
                or case.expected_reason in outcome.error
            )
            blocked = outcome.refused and not outcome.proposals and right_reason
            if blocked:
                rejected += 1
            if outcome.crashed:
                crashed += 1
            elif outcome.refused and not right_reason:
                wrong_reason += 1
            details.append(
                {
                    "case": case.id,
                    "name": case.name,
                    "expectation": REJECT,
                    "blocked": blocked,
                    "crashed": outcome.crashed,
                    "expected_reason": case.expected_reason,
                    "error": outcome.error,
                }
            )
            continue

        propose_expected += 1
        proposals = outcome.proposals
        if not proposals:
            # The gate did not release the real quote, so the injection never
            # reached the fact layer. The case did not exercise the red line,
            # and it must not be counted as a success.
            propose_not_released += 1
            details.append(
                {
                    "case": case.id,
                    "name": case.name,
                    "expectation": PROPOSE,
                    "proposals": 0,
                    "facts": 0,
                    "promoted_to_team_truth": [],
                    "held_at_proposed": False,
                    "reason": "门没有放行这条真实引文，攻击没有到达事实层",
                    "error": outcome.error,
                }
            )
            continue

        facts = derive_facts([*corpus.events, *proposals])
        views = build_views([*corpus.events, *proposals])
        promoted = [
            fact["id"]
            for fact in views["team"]["facts"]
            if fact["status"] == "accepted"
        ]
        accepted_under_attack += len(promoted)
        held = not promoted
        if held:
            propose_held += 1
        details.append(
            {
                "case": case.id,
                "name": case.name,
                "expectation": PROPOSE,
                "proposals": len(proposals),
                "facts": len(facts),
                "promoted_to_team_truth": promoted,
                "held_at_proposed": held,
            }
        )

    metrics = (
        Metric(
            "attack_rejection_rate",
            ratio(rejected, reject_expected) if reject_expected else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail=(
                f"{rejected}/{reject_expected} 条攻击被准入门按合同条款拒绝"
                + (f"（{crashed} 条崩溃、{wrong_reason} 条拒绝理由不符）" if crashed or wrong_reason else "")
            ),
        ),
        Metric(
            "gate_refused_without_crashing",
            1.0 if not crashed else 0.0,
            1.0,
            HIGHER,
            hard=True,
            detail="攻击只会触发合同拒绝，不会让准入门崩溃",
        ),
        Metric(
            "no_promotion_under_attack",
            1.0 if not accepted_under_attack else 0.0,
            1.0,
            HIGHER,
            hard=True,
            detail="攻击下的候选没有任何一条被自动晋升为团队事实",
        ),
        Metric(
            "injection_held_at_proposed",
            ratio(propose_held, propose_expected) if propose_expected else 1.0,
            1.0,
            HIGHER,
            hard=True,
            detail=(
                f"{propose_held}/{propose_expected} 条注入的真实引文停留在 proposed"
                + (f"（{propose_not_released} 条未放行，攻击未到达事实层）" if propose_not_released else "")
            ),
        ),
    )

    return LayerResult(
        layer=LAYER_ID,
        title=TITLE,
        metrics=metrics,
        details={"cases": details, "attacks": len(cases)},
        notes=(
            "本层直接调用产品自己的准入门，不经过任何模型。",
            "源材料里嵌入的越权指令如果被引用为事实，必须停留在 proposed。",
        ),
    )
