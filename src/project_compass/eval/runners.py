"""Pluggable runners for the parts of the benchmark that need a model.

The benchmark deliberately separates two things:

* what the *product* does with material (Layers 1, 2 and 4 need no model), and
* what a *model* does with the product (extraction quality and answer quality).

Everything in this module is the seam between the two. A runner is any
process that reads one JSON request on stdin and writes one JSON response on
stdout, so a harness only has to be wrapped once and then works for Claude,
Codex, DeepSeek, or any other agent the team uses.

The request and response contracts are deliberately tiny:

``extract``
    request ``{"task": "extract", "sources": [{"id", "kind", "content"}]}``
    response ``{"candidates": [{"source_id", "kind", "subject_key", "quote"}]}``

``answer``
    request ``{"task": "answer", "question", "context"}``
    response ``{"answer": "..."}``

Both responses are fed back into the product's own validation, so a runner
cannot make the product accept something the product would not accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys

from ..limits import DEFAULT_HARNESS_TIMEOUT_S, MAX_CANDIDATES_PER_PAYLOAD, MAX_SOURCE_CHARS
from ..models import EvidenceEvent

DEFAULT_TIMEOUT = DEFAULT_HARNESS_TIMEOUT_S


class RunnerError(RuntimeError):
    """Raised when a runner cannot produce a usable response."""


@dataclass(frozen=True)
class ExtractorResult:
    """What an extractor produced for one corpus."""

    name: str
    payload: dict
    error: str = ""
    proposals: tuple = ()
    candidates: int = 0
    rejected: int = 0

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(frozen=True)
class RunnerSpec:
    """How to start one external harness."""

    name: str
    command: tuple[str, ...]
    timeout: int = DEFAULT_TIMEOUT
    env: dict = field(default_factory=dict)

    def argv(self) -> list[str]:
        return [os.path.expandvars(part) for part in self.command]


def _source_payload(events: list[EvidenceEvent]) -> list[dict]:
    """Prepare sources for a model, bounded so a request stays affordable."""
    sources = []
    for event in events:
        if event.kind not in {"assistant_message", "user_message", "file_snapshot"}:
            continue
        content = event.content.strip()
        if not content:
            continue
        sources.append(
            {
                "id": event.id,
                "kind": event.kind,
                "member_id": event.metadata.get("member_id", ""),
                "observed_at": event.observed_at.isoformat(),
                "content": content[:MAX_SOURCE_CHARS],
            }
        )
    return sources


class CommandRunner:
    """Drive an external harness through the JSON request/response contract."""

    def __init__(self, spec: RunnerSpec) -> None:
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    def _call(self, request: dict) -> dict:
        payload = json.dumps(request, ensure_ascii=False)
        environment = {**os.environ, **self.spec.env}
        try:
            completed = subprocess.run(
                self.spec.argv(),
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.spec.timeout,
                env=environment,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise RunnerError(f"harness command was not found: {self.spec.command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"harness timed out after {self.spec.timeout}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or (completed.stdout or "").strip()
            raise RunnerError(
                f"harness exited with {completed.returncode}: {detail[:400]}"
            )
        text = completed.stdout.strip()
        if not text:
            raise RunnerError("harness produced no output")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RunnerError(f"harness output was not JSON: {text[:200]}") from exc

    def extract(self, events: list[EvidenceEvent]) -> ExtractorResult:
        """Ask the harness for candidate facts and return its raw payload."""
        request = {"task": "extract", "sources": _source_payload(events)}
        try:
            response = self._call(request)
        except RunnerError as exc:
            return ExtractorResult(name=self.spec.name, payload={}, error=str(exc))
        candidates = response.get("candidates")
        if not isinstance(candidates, list):
            return ExtractorResult(
                name=self.spec.name,
                payload={},
                error="harness response did not contain a candidates list",
            )
        return ExtractorResult(name=self.spec.name, payload={"candidates": candidates})

    def answer(self, question: str, context: dict) -> tuple[str, str]:
        """Ask the harness a question and return ``(answer, error)``."""
        request = {"task": "answer", "question": question, "context": context}
        try:
            response = self._call(request)
        except RunnerError as exc:
            return "", str(exc)
        answer = response.get("answer")
        if not isinstance(answer, str):
            return "", "harness response did not contain an answer string"
        return answer, ""


class ReferenceExtractor:
    """A deterministic stand-in for a model, used to keep the benchmark runnable.

    It is intentionally generic: it looks for sentences that carry a
    decision, an obligation or an open assumption, and quotes them exactly.
    It knows nothing about the gold set, so a recall number it produces is a
    measurement rather than a rehearsal.
    """

    NAME = "reference-rules-v1"
    name = NAME
    MARKERS = (
        "决定", "确定", "确认", "采用", "选择", "改为", "不再", "必须", "不得", "禁止",
        "负责", "承接", "交付", "截止", "约定", "计划", "先", "暂不", "未确认",
        "待确认", "待核实", "尚未", "不可核实", "假设", "前提", "按", "需要",
    )

    def __init__(self, *, max_candidates: int = 24, max_quote: int = 400) -> None:
        self.max_candidates = max_candidates
        self.max_quote = max_quote

    def extract(self, events: list[EvidenceEvent]) -> ExtractorResult:
        candidates: list[dict] = []
        seen_quotes: set[str] = set()
        for event in events:
            if event.kind not in {"assistant_message", "user_message"}:
                continue
            for sentence in self._sentences(event.content):
                if sentence.startswith(("#", "`", "<", "|")):
                    continue
                if not any(marker in sentence for marker in self.MARKERS):
                    continue
                quote = sentence.strip()[: self.max_quote]
                if len(quote) < 6 or quote in seen_quotes:
                    continue
                seen_quotes.add(quote)
                kind = self._kind(quote)
                candidates.append(
                    {
                        "source_id": event.id,
                        "kind": kind,
                        "subject_key": f"{kind}:{event.id[:12]}:{len(candidates)}",
                        "quote": quote,
                        "task_state": "unknown",
                    }
                )
                if len(candidates) >= self.max_candidates:
                    return ExtractorResult(name=self.NAME, payload={"candidates": candidates})
        return ExtractorResult(name=self.NAME, payload={"candidates": candidates})

    @staticmethod
    def _sentences(text: str) -> list[str]:
        parts = []
        for line in text.splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if not line or line.startswith("## ["):
                continue
            for piece in line.split("。"):
                piece = piece.strip()
                if piece:
                    parts.append(piece)
        return parts

    @staticmethod
    def _kind(quote: str) -> str:
        if any(marker in quote for marker in ("待确认", "待核实", "尚未", "不可核实", "假设", "前提")):
            return "assumption"
        if any(marker in quote for marker in ("负责", "承接", "交付", "截止", "计划", "先")):
            return "task"
        if any(marker in quote for marker in ("决定", "确定", "确认", "采用", "选择", "改为", "不再", "约定")):
            return "decision"
        return "goal"


class BatchedExtractor:
    """Run an extractor over the corpus the way the product really does.

    The product never hands a whole project to a model: it selects a bounded
    batch, lets the model quote inside that window, validates the quotes
    against the window, and then advances a cursor. This wrapper reproduces
    that loop, so a benchmark number reflects the real extraction pipeline
    rather than an unbounded idealisation.

    The inner extractor receives only the batch window, and its quotes are
    validated against the same window, so a quote from an unseen part of a
    source cannot slip in.
    """

    def __init__(self, inner, *, max_chars: int = 18000, max_batches: int = 64) -> None:
        self.inner = inner
        self.max_chars = max_chars
        self.max_batches = max_batches
        self.batches = 0

    @property
    def name(self) -> str:
        return getattr(self.inner, "name", None) or getattr(self.inner, "NAME", "batched")

    @staticmethod
    def _validate_against_sources(
        sources: list, accepted: list[dict], windows: dict
    ) -> tuple[list, int]:
        """Validate the accepted candidates against the immutable sources.

        The product validates one model payload at a time and refuses a
        payload with more than 24 candidates. A model that ignores that limit
        must not be able to abort the whole benchmark, so the candidates are
        validated in payloads of the size the product would use.

        When a payload is refused, the candidates inside it are checked one
        by one, so a single unusable quote costs exactly one candidate instead
        of the whole payload. That keeps the measurement honest: the number
        of rejected candidates is the number the product would really refuse.
        """
        from ..candidate_extraction import validate_candidates

        kept: list = []
        dropped = 0
        for start in range(0, len(accepted), MAX_CANDIDATES_PER_PAYLOAD):
            chunk = accepted[start : start + MAX_CANDIDATES_PER_PAYLOAD]
            try:
                kept.extend(
                    validate_candidates(
                        sources, {"candidates": chunk}, source_windows=windows
                    )
                )
                continue
            except (ValueError, TypeError, KeyError):
                pass
            for candidate in chunk:
                try:
                    kept.extend(
                        validate_candidates(
                            sources, {"candidates": [candidate]}, source_windows=windows
                        )
                    )
                except (ValueError, TypeError, KeyError):
                    dropped += 1
        return kept, dropped

    def extract(self, events: list[EvidenceEvent]) -> ExtractorResult:
        from ..candidate_extraction import select_batch, validate_candidates
        from ..extraction_progress import source_key

        sources = list(events)
        cursors: dict[str, int] = {}
        proposals: list = []
        offered = 0
        rejected = 0
        errors: list[str] = []
        self.batches = 0

        for _ in range(self.max_batches):
            batch = select_batch(sources, self.max_chars, cursors=cursors)
            if not batch:
                break
            self.batches += 1
            windows = {
                event.id: (
                    event.metadata["_extraction_window_start"],
                    event.metadata["_extraction_window_end"],
                )
                for event in batch
            }
            result = self.inner.extract(batch)
            if not result.ok:
                errors.append(result.error)
                break
            candidates = result.payload.get("candidates") or []
            offered += len(candidates)

            # The product validates each candidate against the window it was
            # shown, then against the immutable source with the window bounds.
            accepted: list[dict] = []
            for candidate in candidates:
                try:
                    validate_candidates(batch, {"candidates": [candidate]})
                except (ValueError, TypeError, KeyError):
                    rejected += 1
                else:
                    accepted.append(candidate)
            if accepted:
                validated, dropped = self._validate_against_sources(sources, accepted, windows)
                proposals.extend(validated)
                rejected += dropped

            for event in batch:
                start, end = windows[event.id]
                cursors[source_key(event)] = end

        error = errors[0] if errors else ""
        return ExtractorResult(
            name=self.name,
            payload={"candidates": []},
            error=error,
            proposals=tuple(proposals),
            candidates=offered,
            rejected=rejected,
        )


def builtin_rule_extractor(events: list[EvidenceEvent]) -> ExtractorResult:
    """Run the product's own deterministic extraction rules over the corpus.

    The rules are the ones the product ships with (user task directives and
    explicit direction markers), so this measures built-in coverage rather
    than a benchmark stand-in.
    """
    from ..direction_intake import record_direction_candidates
    from ..user_task_intake import record_user_task_candidates

    working = list(events)
    try:
        record_direction_candidates(working)
        record_user_task_candidates(working)
    except Exception as exc:  # noqa: BLE001 - the benchmark must report, not crash
        return ExtractorResult(name="builtin-rules", payload={}, error=str(exc))
    proposals = [event for event in working if event.kind == "fact_proposal"]
    candidates = []
    for proposal in proposals:
        for fact in proposal.metadata.get("facts", []):
            candidates.append(
                {
                    "source_id": fact.get("source_id"),
                    "kind": fact.get("kind"),
                    "subject_key": fact.get("subject_key"),
                    "quote": fact.get("quote"),
                    "task_state": fact.get("task_state", "unknown"),
                }
            )
    return ExtractorResult(name="builtin-rules", payload={"candidates": candidates})


#: Ready-made command templates. Each harness needs one thin wrapper that
#: speaks the JSON contract above; the wrapper is what differs between tools.
HARNESS_PRESETS: dict[str, tuple[str, ...]] = {
    "api": (sys.executable, "-m", "project_compass.eval.harness", "api"),
    "claude": ("python", "-m", "project_compass.eval.harness", "claude"),
    "codex": ("python", "-m", "project_compass.eval.harness", "codex"),
    "custom": ("python", "-m", "project_compass.eval.harness", "custom"),
}


def runner_for(name: str, command: tuple[str, ...] | None = None) -> CommandRunner:
    """Build a runner from a preset name or an explicit command."""
    if command:
        return CommandRunner(RunnerSpec(name=name, command=tuple(command)))
    preset = HARNESS_PRESETS.get(name)
    if preset is None:
        raise RunnerError(f"unknown harness preset: {name}")
    return CommandRunner(RunnerSpec(name=name, command=preset))


def default_runner() -> BatchedExtractor:
    """The extractor used when no harness is named: the batched reference extractor."""
    return BatchedExtractor(ReferenceExtractor())


def harness_script_path() -> Path:
    """Return the path of the JSON harness wrapper, for documentation."""
    return Path(__file__).with_name("harness.py")
