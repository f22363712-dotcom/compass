"""Shared bilingual intent keyword vocabularies for query routing and rule-based intake."""

from __future__ import annotations

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
