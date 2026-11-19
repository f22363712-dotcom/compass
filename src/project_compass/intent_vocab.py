"""Shared bilingual intent keyword vocabularies for query routing and rule-based intake."""

from __future__ import annotations

import re

GAP_QUERY_TERMS = (
    "缺证",
    "证据缺口",
    "缺什么证据",
    "还缺什么",
    "缺少证据",
    "missing evidence",
    "evidence gap",
)

MEMBER_UNFINISHED_TERMS = ("未完成", "阻塞", "还剩", "unfinished", "blocked", "pending")
MEMBER_NEXT_TERMS = ("下一步", "接下来", "next")
MEMBER_TASK_TERMS = ("任务", "task", "todo")
MEMBER_DECISION_TERMS = ("决策", "决定", "decision")
MEMBER_ASSUMPTION_TERMS = ("前提", "假设", "assumption")

DIRECTION_QUERY_TERMS = ("方向", "决策", "direction", "decision", "changed")
BLOCKED_QUERY_TERMS = ("阻塞", "未完成", "未验证", "blocked", "untrusted")
WHY_STATE_QUERY_TERMS = ("为什么", "why", "状态", "state", "依据", "证据", "evidence", "support")
GENERAL_QUESTION_TERMS = (
    "哪些",
    "哪个",
    "什么",
    "怎么",
    "如何",
    "多少",
    "谁",
    "？",
    "?",
    "what",
    "which",
    "how",
    "who",
)
TRANSLATION_EXCLUSION_TERMS = ("translate", "翻译", "rewrite", "改写")

RECENT_COMPLETED_QUERY_TERMS = (
    "最近完成",
    "刚完成",
    "刚做完",
    "完成了什么",
    "完成了哪些",
    "做完了什么",
    "最新完成",
    "近期完成",
    "最新进展",
    "最近进展",
    "recently completed",
    "what was completed",
    "recent progress",
)
_RECENT_COMPLETED_EXCLUSIONS = ("未完成", "还没完成", "尚未完成", "unfinished", "not completed", "pending")
_RECENT_COMPLETED_RE = re.compile(
    r"(?:最近|近期|刚刚|刚才|最新|今天).{0,8}(?:完成|做完|交付|落地|跑通)",
    re.I,
)


def is_recent_completed_query(question: str) -> bool:
    """Return True when the user is specifically asking what has recently been completed."""
    q = str(question or "").strip()
    if not q:
        return False
    lower = q.casefold()
    if any(term in lower for term in _RECENT_COMPLETED_EXCLUSIONS):
        return False
    return any(term in lower for term in RECENT_COMPLETED_QUERY_TERMS) or bool(_RECENT_COMPLETED_RE.search(q))
