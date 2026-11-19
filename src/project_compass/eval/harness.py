"""A thin JSON wrapper around a coding-agent CLI.

The benchmark does not care which agent answers a question, only that the
answer comes back through a stable contract. This module is that contract's
side of the seam: it reads one JSON request on stdin, calls the selected CLI
once, and writes one JSON response on stdout.

Usage::

    echo '{"task": "answer", "question": "..."}' | python -m project_compass.eval.harness claude

Supported backends:

``claude``
    the Claude Code CLI, ``claude -p``
``codex``
    the Codex CLI, ``codex exec``
``custom``
    whatever ``PROJECT_COMPASS_HARNESS_CMD`` names; the prompt is passed as
    the single argument, so any wrapper script works.

The wrapper never invents content: if the model does not return usable JSON,
the response carries an error and the benchmark records a failure instead of
a fabricated score.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from ..limits import DEFAULT_HARNESS_TIMEOUT_S
from ..llm_connector import chat_completion_text, extract_json_object

EXTRACT_PROMPT = """\
You are extracting high-signal candidate facts from a project conversation log.

Return ONLY a JSON object with this exact shape:
{"candidates": [{"source_id": "<id>", "kind": "goal|task|decision|assumption",
"subject_key": "<short stable topic>", "quote": "<an exact verbatim span copied from the source>"}]}

Rules:
- The quote MUST be copied character for character from the content of the matching source_id.
- Every candidate MUST carry the exact source_id of that source.
- Prefer concrete, settled goals, architectural/workflow decisions, specific assigned tasks, and open assumptions. Skip trivial greetings or generic chatter.
- Do not invent facts that are not written in the source.
- Return 1 to 10 high-signal candidates per batch (at most 24).
- Keep internal reasoning concise and output ONLY the JSON object.

SOURCES:
"""

ANSWER_PROMPT = """\
You are answering a question about a project using only the supplied JSON context.

Answer concisely in the same language as the question. Directly include concrete terms, entity names, numbers, and rules from the context, and cite the relevant [evidence_id] tokens that appear in the context. Never invent an evidence ID not present in the context. If the context lacks the answer, state what is missing instead of guessing.

CONTEXT:
"""


def _read_request() -> dict:
    text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("no request was received on stdin")
    try:
        request = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"the request was not JSON: {exc}")
    if not isinstance(request, dict):
        raise SystemExit("the request must be a JSON object")
    return request


def _call_cli(backend: str, prompt: str, timeout: int, *, max_tokens: int = 900) -> str:
    if backend in {"api", "minimax", "ollama"}:
        reply, err = chat_completion_text(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            timeout=float(timeout),
            temperature=0.0,
        )
        if err:
            raise SystemExit(f"api harness failed: {err}")
        return reply
    if backend == "claude":
        command = ["claude", "-p", prompt]
    elif backend == "codex":
        command = ["codex", "exec", prompt]
    else:
        template = os.environ.get("PROJECT_COMPASS_HARNESS_CMD", "").strip()
        if not template:
            raise SystemExit("PROJECT_COMPASS_HARNESS_CMD is not set for the custom backend")
        command = [*template.split(), prompt]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"the harness exited with {completed.returncode}: {completed.stderr.strip()[:400]}"
        )
    return completed.stdout


def _extract_json(text: str) -> dict | None:
    """Find one JSON object in a model answer, tolerating thinking blocks and code fences."""
    return extract_json_object(text)


def _render_sources(sources: list[dict]) -> str:
    parts = []
    for source in sources:
        parts.append(
            f"### source_id: {source.get('id', '')}\n{source.get('content', '')}"
        )
    return "\n\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    backend = args[0] if args else "custom"
    timeout = int(os.environ.get("PROJECT_COMPASS_HARNESS_TIMEOUT", str(DEFAULT_HARNESS_TIMEOUT_S)))
    request = _read_request()
    task = request.get("task")

    try:
        if task == "extract":
            sources = request.get("sources") or []
            if not sources:
                print(json.dumps({"candidates": []}))
                return 0
            prompt = EXTRACT_PROMPT + _render_sources(sources)
            raw = _call_cli(backend, prompt, timeout, max_tokens=8192)
            parsed = _extract_json(raw)
            if parsed is None or not isinstance(parsed.get("candidates"), list):
                print(json.dumps({"error": "the model did not return a candidates list"}))
                return 1
            print(json.dumps({"candidates": parsed["candidates"]}, ensure_ascii=False))
            return 0
        if task == "answer":
            question = str(request.get("question", ""))
            context = request.get("context") or {}
            prompt = (
                ANSWER_PROMPT
                + json.dumps(context, ensure_ascii=False, indent=2)
                + f"\n\nQUESTION:\n{question}\n"
            )
            raw = _call_cli(backend, prompt, timeout, max_tokens=3000)
            print(json.dumps({"answer": raw.strip()}, ensure_ascii=False))
            return 0
    except SystemExit:
        raise
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "the harness timed out"}))
        return 1

    print(json.dumps({"error": f"unknown task: {task}"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
