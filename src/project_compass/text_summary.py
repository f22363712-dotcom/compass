"""Deterministic human-readable title summarization and legacy doc classification (pure stdlib).

Produces concise mindmap/card display titles (`short_title`) while keeping raw ledger
`value` and `quote` strings completely unmodified for audit drawers and exact-span checks.
Strictly standalone: never imports fact/view/extraction core engines.
"""

from __future__ import annotations

import re
from typing import Any

_LEADING_QUOTE_MENTION_RE = re.compile(r"@\[Quote\]\s*")
_ASK_UI_PREFIX_RE = re.compile(r"^\s*A\d+:\s*(?:\(Recommended\)\s*)?", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_PREFIX_RE = re.compile(r"^\s*(?:>{1,3}|#{1,6}|[-*+]|\d+[.)]|\[[ xX]\])\s*")
_LEADING_DATE_RE = re.compile(
    r"^\s*[\[(]?\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"[\])]?[\s:：\-·|,]*"
)
_LABEL_PREFIX_RE = re.compile(
    r"^(?:project\s+goal|core\s+goal|decision|assumption|task|goal|next\s+step|"
    r"核心目标|项目目标|核心焦点|关键基准|目标|决策|"
    r"(?:前置条件|隐含前提|关键前提|核心假设|当前假设|基本假设|前提条件|前提|假设)(?:是|为|在于)?|"
    r"待办|下一步|状态[：:]\s*开发目标[，,]?)\s*[:：]?\s*",
    re.IGNORECASE,
)
_STATUS_SUFFIX_RE = re.compile(r"\s*\[(?:proposed|accepted|conflicted|rejected|pending|completed)\]\s*$", re.IGNORECASE)
_REPO_PATH_RE = re.compile(r"(?:[A-Za-z]:)?(?:[A-Za-z0-9_.-]+[\\/])+(?=[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}\b)")
_QUOTED_PHRASE_RE = re.compile(r"「([^「」]{6,40})」")

_STATIC_DOC_AUTHORS = frozenset({"project-documents"})
_STATIC_DOC_SOURCE_KINDS = frozenset({"file_snapshot", "document", "doc_scan"})
_STATIC_DOC_REF_FILES = frozenset({
    "readme.md",
    "decisions.md",
    "handoff.md",
    "product_spec.md",
    "product_goal.md",
    "roadmap.md",
    "architecture.md",
    "changelog.md",
})


def _strip_markdown_noise(text: str) -> str:
    cleaned = _LEADING_QUOTE_MENTION_RE.sub("", str(text or ""))
    cleaned = _ASK_UI_PREFIX_RE.sub("", cleaned)
    cleaned = _MD_LINK_RE.sub(r"\1", cleaned)
    for _ in range(3):
        updated = _MD_PREFIX_RE.sub("", cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = _STATUS_SUFFIX_RE.sub("", cleaned)
    return cleaned


def _strip_markup(text: str) -> str:
    cleaned = _strip_markdown_noise(text)
    cleaned = _REPO_PATH_RE.sub("", cleaned)
    return " ".join(cleaned.split()).strip()


def clean_display_text(raw_text: Any, *, max_chars: int = 0) -> str:
    """Remove noisy markdown checkboxes/asterisks/code ticks while preserving meaning."""
    cleaned = " ".join(_strip_markdown_noise(str(raw_text or "")).split()).strip()
    if max_chars > 0 and len(cleaned) > max_chars:
        return _smart_truncate(cleaned, max_chars)
    return cleaned


def _smart_truncate(text: str, max_chars: int) -> str:
    limit = max(6, int(max_chars))
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    # Avoid cutting in the middle of an ASCII word if a nearby space exists.
    if cut and cut[-1].isascii() and text[limit - 1].isascii() and " " in cut:
        last_space = cut.rfind(" ")
        if last_space >= max(4, limit // 2):
            cut = cut[:last_space]
    cut = cut.rstrip(" ,，、:：;；-—·(（[「『“\"+/&")
    if not cut:
        cut = text[: limit - 1].rstrip()
    return cut + "…"


def summarize_node_title(
    raw_text: Any,
    explicit_title: Any = None,
    *,
    max_chars: int = 22,
) -> str:
    """Distill raw ledger prose or dates/code blocks into a clean short display title."""
    if isinstance(explicit_title, str) and explicit_title.strip():
        explicit_clean = _strip_markup(explicit_title)
        if explicit_clean:
            return _smart_truncate(explicit_clean, max_chars)

    cleaned = _strip_markup(str(raw_text or ""))
    if not cleaned:
        return "待补充摘要"

    for _ in range(3):
        stripped_date = _LEADING_DATE_RE.sub("", cleaned).strip()
        if stripped_date == cleaned:
            break
        cleaned = stripped_date or cleaned

    cleaned = _LABEL_PREFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        cleaned = _strip_markup(str(raw_text or ""))

    # Extract concise framed definition phrase (e.g. X 是...「核心定义」：长句展开).
    quoted_match = _QUOTED_PHRASE_RE.search(cleaned[:56])
    if quoted_match:
        prefix_before_quote = cleaned[: quoted_match.start()]
        unclosed_paren = (
            prefix_before_quote.count("（") > prefix_before_quote.count("）")
            or prefix_before_quote.count("(") > prefix_before_quote.count(")")
        )
        has_colon_before = "：" in prefix_before_quote or ":" in prefix_before_quote
        has_definitional_intro = any(tok in prefix_before_quote for tok in ("是", "围绕", "打造", "定位"))
        if not unclosed_paren and not has_colon_before and has_definitional_intro:
            phrase = quoted_match.group(1).strip()
            if 6 <= len(phrase) <= max(max_chars, 28):
                return _smart_truncate(phrase, max_chars)

    # Prefer the lead sentence before verbose explanation separators.
    sentences = re.split(r"(?<=[。！？!?])\s*|(?<=\.)(?<!\d\.)(?<!No\.)(?<!e\.g\.)(?<!i\.e\.)\s+(?=[A-Z\u4e00-\u9fff])|；\s*", cleaned)
    first_clause = next((seg.strip("。；; ") for seg in sentences if seg and seg.strip()), cleaned)
    if len(first_clause) < 5 and len(sentences) > 1:
        second = sentences[1].strip("。；; ")
        if second:
            first_clause = f"{first_clause}：{second}" if first_clause else second

    if len(first_clause) > max_chars:
        for sep in ("：", ":", "——", "（", "("):
            if sep in first_clause:
                head = first_clause.split(sep, 1)[0].strip()
                tail = first_clause.split(sep, 1)[1].strip()
                if sep in ("：", ":"):
                    if len(head) >= max(8, max_chars // 2):
                        first_clause = head
                        break
                    if len(head) <= 3 and tail:
                        first_clause = tail
                        break
                elif len(head) >= 8:
                    first_clause = head
                    break

    return _smart_truncate(first_clause.strip("。；; "), max_chars)


def is_historical_doc_fact(fact: dict[str, Any]) -> bool:
    """Return True for unconfirmed facts extracted statically from legacy repository docs."""
    if not isinstance(fact, dict):
        return False
    if fact.get("status") == "accepted":
        return False
    if fact.get("kind") == "goal":
        return False
    author = str(fact.get("author") or "").strip().lower()
    if author in _STATIC_DOC_AUTHORS:
        return True
    claim_type = str(fact.get("claim_type") or "").strip().lower()
    source_kind = str(fact.get("source_kind") or "").strip().lower()
    evidence_ids = [str(eid) for eid in (fact.get("evidence_ids") or []) if eid]
    source_ref = str(fact.get("source_ref") or "").replace("\\", "/").strip().lower()
    is_scan_source = any(eid.startswith("scan-file-") for eid in evidence_ids)
    is_doc_ref = source_ref.startswith("docs/") or (source_ref.rsplit("/", 1)[-1] in _STATIC_DOC_REF_FILES)
    if is_scan_source or source_kind in _STATIC_DOC_SOURCE_KINDS:
        return True
    if claim_type == "document" and is_doc_ref:
        return True
    return False


def _is_source_current(fact: dict[str, Any]) -> bool:
    source_status = (fact.get("source_state") or {}).get("status")
    return source_status not in {"superseded", "unavailable"}


def _is_unconfirmed_doc_origin(fact: dict[str, Any]) -> bool:
    if fact.get("status") == "accepted":
        return False
    if is_historical_doc_fact(fact):
        return True
    author = str(fact.get("author") or "").strip().lower()
    if author in _STATIC_DOC_AUTHORS:
        return True
    evidence_ids = [str(eid) for eid in (fact.get("evidence_ids") or []) if eid]
    return any(eid.startswith("scan-file-") for eid in evidence_ids)


def select_primary_goal(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose one consistent core goal across dashboard, mindmap, briefs, and investigation."""
    eligible = [
        f
        for f in (facts or [])
        if isinstance(f, dict)
        and f.get("kind") == "goal"
        and f.get("status") != "rejected"
        and _is_source_current(f)
    ]
    if not eligible:
        return None
    accepted = next((f for f in reversed(eligible) if f.get("status") == "accepted"), None)
    if accepted is not None:
        return accepted
    live = next((f for f in reversed(eligible) if not _is_unconfirmed_doc_origin(f)), None)
    return live or eligible[-1]


def select_next_consensus(facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose current next-step consensus, isolating unconfirmed legacy doc checklists."""
    eligible = [
        f
        for f in (facts or [])
        if isinstance(f, dict)
        and f.get("status") != "rejected"
        and not f.get("completed")
        and f.get("task_state") not in {"completed", "reported_complete"}
        and _is_source_current(f)
    ]
    open_tasks = [f for f in eligible if f.get("kind") == "task"]
    for predicate in (
        lambda f: f.get("subject_key") == "project.next_step" and f.get("status") == "accepted",
        lambda f: f.get("status") == "accepted" and not _is_unconfirmed_doc_origin(f),
        lambda f: f.get("subject_key") == "project.next_step",
        lambda f: not _is_unconfirmed_doc_origin(f),
    ):
        hit = next((f for f in reversed(open_tasks) if predicate(f)), None)
        if hit is not None:
            return hit

    pending_cand = next(
        (
            f
            for f in reversed(eligible)
            if not _is_unconfirmed_doc_origin(f)
            and f.get("kind") in {"decision", "assumption"}
            and f.get("status") in {"proposed", "conflicted"}
        ),
        None,
    )
    if pending_cand is not None:
        return {**pending_cand, "is_candidate_suggestion": True}
    return None
