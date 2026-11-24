"""Pure-stdlib causal decision, premise, alternative, and rejected-path graph layer.

Strictly isolated from fact_engine / projections / candidate_extraction so L4
contract blast-radius chains remain untouched.
"""

from __future__ import annotations

from hashlib import sha1
import json
import re
from typing import Any, Callable

from .evidence_filters import as_utc_timestamp, is_public_raw_event
from .llm_connector import chat_completion_text, extract_json_object, resolve_llm_config
from .models import EvidenceEvent
from .text_summary import clean_display_text, is_historical_doc_fact, summarize_node_title

_MAX_ITEM_CHARS = 240
_MAX_FORK_BLOCK_CHARS = 420
_CONTEXT_TAG_RE = re.compile(r"<(?:CONTEXT_SUMMARY|METADATA)>.*?</(?:CONTEXT_SUMMARY|METADATA)>", re.DOTALL | re.IGNORECASE)
_XML_TAG_RE = re.compile(r"</?[A-Za-z_][A-Za-z0-9_:-]*(?:\s+[^>]*)?>")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_QUOTED_UI_MENTION_RE = re.compile(r"「[^」\n]{1,48}」|“[^”\n]{1,48}”")
_INTERROGATIVE_RE = re.compile(
    r"(?:[？?]\s*$|(?:\b(?:right|should\s+we)\s*\?$)|"
    r"(?:对吧|是吧|好吗|行吗|要不要|能不能|是不是|是否需要|怎么验证|如何安排|怎么查看)[？?：:\s]*$)",
    re.IGNORECASE,
)
_ASK_CHOICE_LINE_RE = re.compile(r"^A\d+:\s*(?:\(Recommended\)\s*)?(\S.+)$", re.IGNORECASE)
_LOW_SIGNAL_CHOICE_PREFIX_RE = re.compile(
    r"^(?:[1-4一二三四](?:[和、,，\s]+[1-4一二三四])*(?:吧)?(?=$|[，,。！!\s])|"
    r"(?:选(?:择)?|定)\s*(?:第?\s*[1-4一二三四A-D]|路线\s*[1-4一二三四]|这个|推荐)|"
    r"采用(?:这个)?推荐(?:的)?(?:方案|路线)?|"
    r"(?:清晰[合理妥当]*[，,]?\s*|我)?批准(?![^。\n]{0,10}[·；;])|"
    r"好的|没问题|同意|收到|先在本地|顺手帮我|查看我的)",
    re.IGNORECASE,
)
_EPHEMERAL_ASK_ACTION_RE = re.compile(
    r"(?:重试\s*\d*\s*次|分小?段注入|核心切片|切片|点掉[^。，,\n]{0,12}弹窗|关掉[^。，,\n]{0,12}弹窗|"
    r"退回本地只读|跳过本轮|单次(?:测|注入)|先看一眼|帮我运行|重启(?:一下)?进程|批准动工|启动盲审)",
    re.IGNORECASE,
)
_DURABLE_CHOICE_SIGNAL_RE = re.compile(
    r"(?:统一(?:使用|采用)|以后(?:都|一律)|永久|坚持零依赖|放弃引入|不引入|默认启用|"
    r"采用[^。，,\n]{2,20}(?:架构|路线|协议|存储|方案|框架))",
    re.IGNORECASE,
)
_USER_CLAUSE_SETTLED_RE = re.compile(
    r"(?:^|[，,；;]\s*)(?:(?:以后都|一律|默认|统一)(?:使用|用|采用|走)[^。！？!\n，,]{3,80}|"
    r"(?:别|不要)[^。！？!\n]{2,36}(?:就|只)(?:做|用|走|保持)[^。！？!\n]{2,60})",
    re.IGNORECASE,
)
_CHINESE_GENERIC_BIGRAMS = frozenset({
    "我们", "你们", "他们", "这个", "那个", "这样", "方案", "路线", "使用",
    "采用", "实现", "系统", "问题", "工作", "当前", "进行", "通过", "可以",
    "需要", "应该", "如果", "因为", "所以", "或者", "还是", "关于", "基于",
})

# Legacy patterns preserved verbatim for strict Antigravity adapter compatibility
_GOAL_LINE_RE = re.compile(r"^目标[：:]\s*(\S.+)$")
_HUMAN_GOAL_RE = re.compile(r"[^。\n]*围绕[^。\n]+打造[^。\n]*")
_USER_DECISION_RE = re.compile(r"^(?:选项[一二三四1234]|选\s*[A-D])(?:[，,。:\s]\s*\S.+|$)")
_EXPLICIT_DECISION_RE = re.compile(r"^(?:核心决策|决策)[：:]\s*(\S.+)$")
_ASSISTANT_TASK_RE = re.compile(r"^(?:已实现|已完成)\s+(?:Module\s+\d+|`?[A-Za-z_][A-Za-z0-9_.-]*`?)[^。\n]*。?")

# v1.6 causal dialogue extraction patterns (clause-anchored, non-interrogative)
_CLAUSE_PREFIX = r"(?:^|[，,；;：:\s])"
_NEXT_STEP_RE = re.compile(
    r"^(?:(?:下一步|接下来)(?:计划|重点|先做|动作|先|优先|将|要)[：:\s]*|下一步[：:]\s*|Immediate\s+next\s+step[：:\s]+)(\S[^\n]{4,180})",
    re.IGNORECASE,
)
_PREMISE_RE = re.compile(
    rf"{_CLAUSE_PREFIX}(?:前提(?:是|在于|条件(?:是|为))|前置条件(?:是|为)|隐含前提(?:是|为)|核心假设(?:是|为)|关键假设(?:是|为)|"
    r"(?:当前|基本)假设(?!\s*[和与及])|假定条件|硬(?:性)?约束(?:是|为)|红线(?:是|为)|底线(?:是|为)|"
    r"必须保证[^。！？\n]{3,60}(?:不变|为零|离线)|"
    r"\b(?:assuming\s+(?:that)?|our\s+premise\s+is|hard\s+constraint\s+is|relies\s+on\s+[^.!?\n]{4,40}\s+being)\b)"
    r"[^。！？!\n]{3,160}",
    re.IGNORECASE,
)
_REJECTED_RE = re.compile(
    rf"{_CLAUSE_PREFIX}(?:(?:我们|项目|本轮|系统|最终|坚决|明确|已经)?\s*"
    r"(?:不引入|不采用|不选用|不再使用|不依赖|放弃(?:引入|采用|使用|支持)?|否决|明确排除|舍弃|淘汰(?:方案|路线|路径))|"
    r"排除[^。！？!\n]{2,48}的做法|"
    r"\b(?:rejected|ruled\s+out|abandoned|do\s+not\s+use|won't\s+use)\b)"
    r"[^。！？!\n]{2,160}",
    re.IGNORECASE,
)
_REJECTION_SPLIT_RE = re.compile(r"(?:因为|以免|避免|由于|否则|代价是|太重|会破坏|because|since|to avoid|as it)", re.IGNORECASE)
_OPEN_FORK_RE = re.compile(
    r"(?:(?:有?(?:两|三|[23])种(?:方案|路线|路径|选型|做法)|备选方案(?:有|包括)|候选方案(?:有|包括)|"
    r"分歧在于|需要在[^。！？\n]{2,50}(?:与|还是|or)[^。！？\n]{2,50}之间权衡|"
    r"尚未决定选?用?[^。！？\n]{2,50}还是[^。！？\n]{2,50}|"
    r"方案\s*[A1一][^。！？\n]{1,60}(?:vs\.?|还是|对比|与)[^。！？\n]{1,60}方案\s*[B2二]|"
    r"\b(?:two\s+options|open\s+question|undecided\s+between|option\s*[a1]\s*(?:vs|or)\s*option\s*[b2])\b)"
    r"[^。！？!\n]{0,180})",
    re.IGNORECASE,
)
_SETTLED_RE = re.compile(
    r"^(?:(?:最终|正式|现已|确认|统一)?(?:采用|选用|使用|定为|拍板(?:选|使用|采用)?|沿用|坚持使用|决定使用|决定采用)"
    r"(?!(?:这个|该)?推荐(?:的)?(?:方案|选项)?\d*[，,。！!\s]*$)[^。！？!\n]{4,160}|"
    r"(?:以后都|一律|默认|统一)(?:使用|用|采用|走)[^。！？!\n]{4,120}|"
    r"(?:核心路线|技术路线|架构选型|存储方案|默认(?:模式|模型)|技术栈)(?:是|为|定为)[：:\s]*[^。！？!\n]{4,160}|"
    r"(?:别|不要)[^。！？!\n]{2,40}[，,]?(?:就|直接|只)(?:做|用|走|保持)[^。！？!\n]{2,80}|"
    r"\b(?:we\s+(?:decided|chose|agreed)\s+to|settled\s+on|stick\s+with)\s+[^.!?\n]{5,140})",
    re.IGNORECASE,
)
_OPTION_BULLET_RE = re.compile(
    r"(?:选项|方案|路线)\s*([A-D1-4一二三四])[：:、.\s]+([^\n]{4,120})|"
    r"\bOption\s*([A-D1-4])[:.\s]+([^\n]{4,120})",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}", re.IGNORECASE)


def _hash_content(text: str) -> str:
    return sha1(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:12]


def _extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for chunk in _TOKEN_RE.findall(str(text or "").casefold()):
        if chunk.isascii():
            tokens.add(chunk)
        elif len(chunk) == 2:
            if chunk not in _CHINESE_GENERIC_BIGRAMS and not any(ch in chunk for ch in "的了是在和与"):
                tokens.add(chunk)
        else:
            for idx in range(len(chunk) - 1):
                bg = chunk[idx : idx + 2]
                if bg not in _CHINESE_GENERIC_BIGRAMS and not any(ch in bg for ch in "的了是在和与"):
                    tokens.add(bg)
    return tokens


def _visible_dialogue_mask(content: str) -> str:
    """Replace XML summaries and code fences with spaces while preserving char offsets 1:1."""
    if not content:
        return ""
    chars = list(content)
    for pattern in (_CONTEXT_TAG_RE, _CODE_FENCE_RE):
        for match in pattern.finditer(content):
            for idx in range(match.start(), match.end()):
                if chars[idx] != "\n":
                    chars[idx] = " "
    return "".join(chars)


def _iter_line_spans(masked_text: str, raw_content: str) -> list[tuple[int, int, str]]:
    """Yield trimmed line spans (start, end, exact_raw_slice) from non-masked lines."""
    rows: list[tuple[int, int, str]] = []
    pos = 0
    for line in masked_text.splitlines(keepends=True):
        raw_slice = line.rstrip("\r\n")
        trimmed = raw_slice.strip()
        if trimmed:
            # Find cleaned body inside original line without markdown bullet decorations,
            # while still guaranteeing the returned substring exists verbatim in raw_content.
            lstrip_len = len(raw_slice) - len(raw_slice.lstrip())
            rstrip_len = len(raw_slice) - len(raw_slice.rstrip())
            abs_start = pos + lstrip_len
            abs_end = pos + len(raw_slice) - rstrip_len
            slice_text = raw_content[abs_start:abs_end]
            # Strip leading quote/blockquote/bullet prefix only if exact tail remains clean.
            prefix_match = re.match(r"^(?:@\[Quote\]\s*|>{1,3}\s+|[-*+]\s+|\d+[.)]\s+)", slice_text)
            if prefix_match and len(slice_text) - prefix_match.end() >= 4:
                abs_start += prefix_match.end()
                slice_text = raw_content[abs_start:abs_end]
            rows.append((abs_start, abs_end, slice_text))
        pos += len(line)
    return rows


def _extract_alternatives_from_text(text: str) -> list[str]:
    alts: list[str] = []
    # 1. Explicit Option A / B bullets
    for match in _OPTION_BULLET_RE.finditer(text):
        label = match.group(1) or match.group(3)
        body = (match.group(2) or match.group(4) or "").strip(" 。；;,，")
        if body:
            entry = f"方案 {label.upper()}: {clean_display_text(body, max_chars=48)}"
            if entry not in alts:
                alts.append(entry)
    if len(alts) >= 2:
        return alts[:4]

    # 2. Inline binary comparisons: A vs B / 选 A 还是 B / 在 A 与 B 之间
    inline_patterns = (
        re.compile(r"在\s*([^，,。；;\n]{2,40}?)\s*(?:与|和|vs\.?|还是)\s*([^，,。；;\n]{2,40}?)\s*之间", re.IGNORECASE),
        re.compile(r"(?:选|采用|待定(?:是|选)?)\s*([^，,。；;？?\n]{2,40}?)\s*(?:还是|vs\.?|or)\s*([^，,。；;？?\n]{2,40})", re.IGNORECASE),
        re.compile(r"([A-Za-z0-9_\u4e00-\u9fff+.-]{2,32})\s+vs\.?\s+([A-Za-z0-9_\u4e00-\u9fff+.-]{2,32})", re.IGNORECASE),
    )
    for pat in inline_patterns:
        hit = pat.search(text)
        if hit:
            left = clean_display_text(hit.group(1), max_chars=40)
            right = clean_display_text(hit.group(2), max_chars=40)
            if left and right and left != right:
                return [left, right]
    return alts[:4]


def _extract_rejection_reason(quote: str) -> str:
    hit = _REJECTION_SPLIT_RE.search(quote)
    if not hit:
        return ""
    return clean_display_text(quote[hit.start():].strip(" ，,：:;；。."), max_chars=96)


def _split_sentence_spans(line_start: int, line_text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for sep in re.finditer(r"[。！？!?]+|\.\s+", line_text):
        end = sep.end()
        seg = line_text[start:end].strip()
        if seg:
            inner_l = line_text.find(seg, start, end)
            if inner_l >= 0:
                spans.append((line_start + inner_l, line_start + inner_l + len(seg), seg))
        start = end
    tail = line_text[start:].strip()
    if tail:
        inner_l = line_text.find(tail, start)
        if inner_l >= 0:
            spans.append((line_start + inner_l, line_start + inner_l + len(tail), tail))
    return spans or [(line_start, line_start + len(line_text), line_text)]


def extract_dialogue_rich_facts(content: str, claim_type: str) -> list[dict[str, Any]]:
    """Deterministically extract legacy + causal decision/fork/premise/rejected facts.

    Every emitted item's ``quote`` is guaranteed to appear verbatim in ``content``
    so exact-span validation and raw source drawers always hold.
    """
    if not isinstance(content, str) or not content.strip():
        return []

    masked = _visible_dialogue_mask(content)
    line_spans = _iter_line_spans(masked, content)
    facts: list[dict[str, Any]] = []
    seen_quotes: set[str] = set()

    def _emit(
        *,
        kind: str,
        quote: str,
        start: int,
        end: int,
        subject_key: str,
        decision_stage: str | None = None,
        alternatives: list[str] | None = None,
        rejection_reason: str | None = None,
        premise_status: str | None = None,
        task_state: str | None = None,
    ) -> None:
        if not quote or len(quote) < 4 or quote in seen_quotes:
            return
        max_cap = _MAX_FORK_BLOCK_CHARS if decision_stage == "open_fork" else _MAX_ITEM_CHARS
        if len(quote) > max_cap:
            quote = quote[:max_cap].rstrip()
            end = start + len(quote)
        if content[start:end] != quote:
            idx = content.find(quote)
            if idx < 0:
                return
            start, end = idx, idx + len(quote)
        if _XML_TAG_RE.search(quote):
            return
        seen_quotes.add(quote)
        row: dict[str, Any] = {
            "kind": kind,
            "subject_key": subject_key,
            "value": quote,
            "quote": quote,
            "source_start": start,
            "source_end": end,
            "claim_type": claim_type,
        }
        if decision_stage:
            row["decision_stage"] = decision_stage
        if alternatives:
            row["alternatives"] = list(alternatives)[:4]
        if rejection_reason:
            row["rejection_reason"] = rejection_reason
        if premise_status:
            row["premise_status"] = premise_status
        if task_state:
            row["task_state"] = task_state
        facts.append(row)

    # First pass: group adjacent "方案 A / B" or "Option 1 / 2" bullet blocks on multi-line prompts
    option_lines: list[tuple[int, int, str, str]] = []
    block_header_starts: set[int] = set()
    consumed_option_starts: set[int] = set()

    def _flush_option_block(block: list[tuple[int, int, str, str]]) -> None:
        if len(block) < 2:
            return
        block_start = block[0][0]
        block_end = block[-1][1]
        block_quote = content[block_start:block_end]
        if len(block_quote) > _MAX_FORK_BLOCK_CHARS:
            block_quote = block_quote[:_MAX_FORK_BLOCK_CHARS].rstrip()
            block_end = block_start + len(block_quote)
        if block_quote and block_quote not in seen_quotes:
            _emit(
                kind="decision",
                quote=block_quote,
                start=block_start,
                end=block_end,
                subject_key=f"decision.fork.{_hash_content(block_quote)}",
                decision_stage="open_fork",
                alternatives=[alt for _, _, alt, _ in block[:4]],
            )
            for opt_start, _, _, _ in block:
                consumed_option_starts.add(opt_start)

    for idx_line, (l_start, l_end, raw_line) in enumerate(line_spans):
        plain = raw_line.replace("**", "").strip()
        m_opt = _OPTION_BULLET_RE.match(plain)
        if m_opt:
            label = (m_opt.group(1) or m_opt.group(3) or "").upper()
            body = (m_opt.group(2) or m_opt.group(4) or "").strip()
            if body:
                if not option_lines and idx_line > 0 and line_spans[idx_line - 1][2].rstrip().endswith((":", "：")):
                    block_header_starts.add(line_spans[idx_line - 1][0])
                option_lines.append((l_start, l_end, f"方案 {label}: {clean_display_text(body, max_chars=48)}", raw_line))
        elif option_lines:
            _flush_option_block(option_lines)
            option_lines = []
    _flush_option_block(option_lines)

    for l_start, l_end, raw_line in line_spans:
        if l_start in block_header_starts or l_start in consumed_option_starts:
            continue
        plain = raw_line.replace("**", "").strip()
        if not plain or _XML_TAG_RE.search(plain) or _HEADING_RE.match(plain):
            continue
        # Preserve exact Antigravity legacy goal extraction
        if _GOAL_LINE_RE.match(plain):
            _emit(
                kind="goal",
                quote=raw_line,
                start=l_start,
                end=l_end,
                subject_key=f"goal.agy.{_hash_content(raw_line)}",
            )
            continue

        if claim_type == "user_statement":
            human_goal = _HUMAN_GOAL_RE.search(plain)
            if human_goal:
                goal_txt = human_goal.group(0).strip()
                if goal_txt in raw_line:
                    g_off = raw_line.find(goal_txt)
                    _emit(
                        kind="goal",
                        quote=goal_txt,
                        start=l_start + g_off,
                        end=l_start + g_off + len(goal_txt),
                        subject_key=f"goal.agy.{_hash_content(goal_txt)}",
                    )
            if _USER_DECISION_RE.match(plain) or _EXPLICIT_DECISION_RE.match(plain):
                _emit(
                    kind="decision",
                    quote=raw_line,
                    start=l_start,
                    end=l_end,
                    subject_key=f"decision.agy.{_hash_content(raw_line)}",
                    decision_stage="settled",
                )
                continue
            ask_match = _ASK_CHOICE_LINE_RE.match(plain)
            if ask_match:
                choice_body = ask_match.group(1).strip()
                is_ephemeral_action = bool(
                    _EPHEMERAL_ASK_ACTION_RE.search(choice_body)
                    and not _DURABLE_CHOICE_SIGNAL_RE.search(choice_body)
                )
                is_structured_choice = (
                    len(choice_body) >= 12
                    and not _LOW_SIGNAL_CHOICE_PREFIX_RE.match(choice_body)
                    and not is_ephemeral_action
                    and not _INTERROGATIVE_RE.search(choice_body)
                )
                if is_structured_choice:
                    _emit(
                        kind="decision",
                        quote=raw_line,
                        start=l_start,
                        end=l_end,
                        subject_key=f"decision.choice.{_hash_content(raw_line)}",
                        decision_stage="settled",
                    )
                    continue
                # Non-structured choice lines continue to sentence/clause extraction below.

        if claim_type == "assistant_report":
            task_match = _ASSISTANT_TASK_RE.match(plain)
            if task_match:
                raw_task_txt = task_match.group(0).strip()
                if raw_task_txt in raw_line:
                    t_off = raw_line.find(raw_task_txt)
                    _emit(
                        kind="task",
                        quote=raw_task_txt,
                        start=l_start + t_off,
                        end=l_start + t_off + len(raw_task_txt),
                        subject_key=f"task.agy.{_hash_content(raw_task_txt)}",
                        task_state="reported_complete",
                    )
                    continue

        # Sentence-level causal semantics with question & UI-mention noise guards
        for s_start, s_end, sentence in _split_sentence_spans(l_start, raw_line):
            clean_sent = sentence.replace("**", "").strip()
            if not clean_sent or _HEADING_RE.match(clean_sent):
                continue
            is_question = bool(_INTERROGATIVE_RE.search(clean_sent))
            probe_sent = _QUOTED_UI_MENTION_RE.sub(" ", clean_sent).strip()
            if not probe_sent:
                continue

            if claim_type == "user_statement" and not is_question and _NEXT_STEP_RE.match(clean_sent):
                _emit(
                    kind="task",
                    quote=sentence,
                    start=s_start,
                    end=s_end,
                    subject_key="project.next_step",
                    task_state="pending",
                )
                continue

            # Rejected path takes priority over settled/assumption when negation markers exist
            if not is_question and _REJECTED_RE.search(probe_sent) and len(clean_sent) >= 8:
                reason = _extract_rejection_reason(sentence)
                _emit(
                    kind="decision",
                    quote=sentence,
                    start=s_start,
                    end=s_end,
                    subject_key=f"decision.rejected.{_hash_content(sentence)}",
                    decision_stage="rejected_path",
                    rejection_reason=reason,
                )
                continue

            # Premise / Assumption / Hard constraint
            if not is_question and _PREMISE_RE.search(probe_sent):
                _emit(
                    kind="assumption",
                    quote=sentence,
                    start=s_start,
                    end=s_end,
                    subject_key=f"premise.{_hash_content(sentence)}",
                    decision_stage="premise",
                    premise_status="unverified",
                )
                continue

            # Unresolved binary or multi-option fork (require >=2 concrete extracted alternatives)
            if _OPEN_FORK_RE.search(probe_sent):
                alts = _extract_alternatives_from_text(probe_sent)
                if len(alts) >= 2:
                    _emit(
                        kind="decision",
                        quote=sentence,
                        start=s_start,
                        end=s_end,
                        subject_key=f"decision.fork.{_hash_content(sentence)}",
                        decision_stage="open_fork",
                        alternatives=alts,
                    )
                    continue

            # Explicit settled choice or durable directive from human speaker
            if claim_type == "user_statement" and not is_question and (
                _SETTLED_RE.match(clean_sent) or _USER_CLAUSE_SETTLED_RE.search(clean_sent)
            ):
                _emit(
                    kind="decision",
                    quote=sentence,
                    start=s_start,
                    end=s_end,
                    subject_key=f"decision.settled.{_hash_content(sentence)}",
                    decision_stage="settled",
                )

    if len(facts) <= 12:
        return facts
    _stage_rank = {"goal": 0, "settled": 1, "open_fork": 2, "rejected_path": 3, "premise": 4}
    indexed = sorted(
        enumerate(facts),
        key=lambda pair: (
            _stage_rank.get(str(pair[1].get("decision_stage") or pair[1].get("kind") or ""), 5),
            pair[0],
        ),
    )
    kept_idxs = {idx for idx, _ in indexed[:12]}
    return [f for idx, f in enumerate(facts) if idx in kept_idxs]


class IncrementalSemanticObserver:
    """Optional LLM extractor that enriches turns with grounded causal proposals."""

    def __init__(self, llm_callable: Callable[[list[dict[str, str]]], str] | None = None, *, timeout: float = 8.0) -> None:
        self._llm_callable = llm_callable
        self._timeout = max(2.0, min(float(timeout), 20.0))

    def extract_batch(self, events: list[EvidenceEvent], *, max_messages: int = 6) -> list[EvidenceEvent]:
        """Extract exact-span semantic facts from up to ``max_messages`` dialogue events."""
        dialogue = [
            ev
            for ev in events
            if is_public_raw_event(ev)
            and ev.kind in {"user_message", "assistant_message"}
            and isinstance(ev.content, str)
            and len(ev.content.strip()) >= 12
        ][-max(1, int(max_messages)):]
        if not dialogue:
            return []

        call_fn = self._llm_callable
        if call_fn is None:
            cfg = resolve_llm_config()
            if not cfg.get("enabled"):
                return []

            def _default_call(msgs: list[dict[str, str]]) -> str:
                text, _ = chat_completion_text(msgs, temperature=0.1, max_tokens=1600, timeout=self._timeout)
                return text

            call_fn = _default_call

        def _bounded_text(ev_content: str) -> str:
            cleaned = _visible_dialogue_mask(ev_content)
            if len(cleaned) <= 1800:
                return cleaned.strip()
            # Keep both opening context and closing conclusions for long multi-paragraph messages.
            return f"{cleaned[:800].rstrip()}\n...\n{cleaned[-1000:].lstrip()}"

        source_payload = [
            {
                "source_id": ev.id,
                "role": "user" if ev.kind == "user_message" else "assistant",
                "text": _bounded_text(ev.content),
            }
            for ev in dialogue
        ]
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是高精度工程决策抽取器。只返回 JSON：{\"candidates\":[...] }。"
                    "每个条目必须包含 source_id、kind(goal|decision|assumption|task)、"
                    "decision_stage(settled|open_fork|rejected_path|premise)、"
                    "alternatives(字符串数组，可选)、rejection_reason(字符串，可选)、"
                    "subject_key、quote(必须是对应 source text 中逐字连续存在的原话子串！严禁改写)。"
                    "若无明确可提取条目则返回 {\"candidates\":[]}。"
                ),
            },
            {"role": "user", "content": json.dumps(source_payload, ensure_ascii=False)},
        ]
        try:
            raw_reply = call_fn(prompt)
        except Exception:
            return []
        parsed = extract_json_object(raw_reply)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
            return []

        by_id = {ev.id: ev for ev in dialogue}
        grouped: dict[str, list[dict[str, Any]]] = {}
        seen_keys: set[tuple[str, str, str]] = set()
        for ev in dialogue:
            for existing in (ev.metadata.get("facts") if isinstance(ev.metadata, dict) else []) or []:
                if isinstance(existing, dict) and existing.get("quote"):
                    seen_keys.add((ev.id, str(existing.get("kind") or ""), str(existing.get("quote") or "").strip()))
        for raw_item in parsed["candidates"]:
            if not isinstance(raw_item, dict):
                continue
            sid = str(raw_item.get("source_id") or "").strip()
            src = by_id.get(sid)
            if src is None:
                continue
            quote = str(raw_item.get("quote") or "").strip()
            kind = str(raw_item.get("kind") or "").strip().lower()
            if kind not in {"goal", "decision", "assumption", "task"} or not quote:
                continue
            idx = src.content.find(quote)
            if idx < 0:
                continue  # Strict zero-hallucination gate
            stage = str(raw_item.get("decision_stage") or "").strip()
            if stage not in {"settled", "open_fork", "rejected_path", "premise"}:
                stage = "premise" if kind == "assumption" else ("settled" if kind == "decision" else "")
            subj = str(raw_item.get("subject_key") or "").strip() or f"{kind}.llm.{_hash_content(quote)}"
            dedup = (sid, kind, quote)
            if dedup in seen_keys:
                continue
            # Also skip substring near-duplicates ONLY within the same fact kind
            if any(
                ex_sid == sid and ex_k == kind and (quote in ex_q or ex_q in quote)
                for ex_sid, ex_k, ex_q in seen_keys
            ):
                continue
            seen_keys.add(dedup)
            entry: dict[str, Any] = {
                "kind": kind,
                "subject_key": subj,
                "value": quote,
                "quote": quote,
                "source_id": sid,
                "source_start": idx,
                "source_end": idx + len(quote),
            }
            if stage:
                entry["decision_stage"] = stage
            if stage == "premise" or kind == "assumption":
                entry["premise_status"] = "unverified"
            alts = raw_item.get("alternatives")
            if isinstance(alts, list) and alts:
                entry["alternatives"] = [str(a).strip() for a in alts if str(a).strip()][:4]
            reason = str(raw_item.get("rejection_reason") or "").strip()
            if reason:
                entry["rejection_reason"] = reason[:120]
            if kind == "task":
                entry["task_state"] = "pending"
            grouped.setdefault(sid, []).append(entry)

        proposals: list[EvidenceEvent] = []
        for sid, items in grouped.items():
            src = by_id[sid]
            prop_id = f"proposal-llm-{_hash_content(sid + ':' + json.dumps(items, ensure_ascii=False, sort_keys=True))}"
            proposals.append(
                EvidenceEvent(
                    id=prop_id,
                    session_id=src.session_id,
                    author=src.author,
                    kind="fact_proposal",
                    content=items[0]["quote"],
                    observed_at=src.observed_at,
                    metadata={
                        "member_id": str(src.metadata.get("member_id") or src.author),
                        "derivation": "incremental-semantic-observer-v1",
                        "facts": items,
                    },
                )
            )
        return proposals


def normalize_same_author_supersession(
    views: dict[str, Any],
    review_history: list[dict] | tuple[dict, ...] = (),
) -> dict[str, Any]:
    """Eliminate spurious conflicts caused by sequential single-author updates or stale docs.

    Preserves all real >=2 member conflicts untouched while preventing a single user's
    anchor updates (e.g. v1.3 -> v1.4 on ``project.next_step``) or live-vs-archive-doc
    updates from showing false 'conflicted' alerts.
    """
    team = views.get("team") or {}
    team_facts = list(team.get("facts") or [])
    conflicts = list(team.get("conflicts") or [])
    if not conflicts:
        return {"superseded_count": 0}

    latest_review: dict[str, dict] = {}
    for item in review_history or ():
        fid = item.get("fact_id")
        if fid and item.get("action") != "confirm_relation":
            latest_review[str(fid)] = item
    rejected_ids = {fid for fid, rev in latest_review.items() if rev.get("action") == "reject_fact"}

    by_subject: dict[str, list[dict]] = {}
    for f in team_facts:
        if str(f.get("id") or "") not in rejected_ids:
            by_subject.setdefault(str(f.get("subject_key") or ""), []).append(f)

    resolved_pairs: list[tuple[dict, list[dict]]] = []
    kept_conflicts: list[dict] = []

    def _obs_ts(fact: dict) -> float:
        try:
            return as_utc_timestamp(fact.get("observed_at") or "").timestamp()
        except (TypeError, ValueError):
            return 0.0

    for conflict in conflicts:
        subj = str(conflict.get("subject_key") or "")
        items = by_subject.get(subj) or []
        if len(items) <= 1:
            continue
        live_items = [item for item in items if not is_historical_doc_fact(item)]
        doc_items = [item for item in items if is_historical_doc_fact(item)]

        live_authors = {
            str(item.get("author") or item.get("reported_by") or "").strip().casefold()
            for item in live_items
            if str(item.get("author") or item.get("reported_by") or "").strip()
        }
        human_live_authors = {a for a in live_authors if a != "antigravity"}
        live_values = {str(item.get("value") or "") for item in live_items}

        same_author_evolution = len(live_items) == len(items) and len(human_live_authors) <= 1 and len(live_authors) >= 1
        doc_vs_single_live = (
            bool(doc_items)
            and all(d.get("status") != "accepted" for d in doc_items)
            and len(live_items) >= 1
            and (len(human_live_authors) <= 1 or len(live_values) == 1)
        )

        if not (same_author_evolution or doc_vs_single_live):
            kept_conflicts.append(conflict)
            continue

        accepted_items = [it for it in items if it.get("status") == "accepted"]
        if not accepted_items:
            pool = live_items if doc_vs_single_live else items
            winner = max(pool, key=lambda it: (_obs_ts(it), str(it.get("id") or "")))
            losers = [it for it in items if str(it.get("id")) != str(winner.get("id"))]
            resolved_pairs.append((winner, losers))
            continue

        # Accepted anchor exists: NEVER let an older accepted item hide a strictly NEWER human proposal,
        # while folding stale unconfirmed assistant suggestions or interrogatives behind it.
        newest_acc = max(accepted_items, key=lambda it: (_obs_ts(it), str(it.get("id") or "")))
        acc_ts = _obs_ts(newest_acc)

        def _is_superseded_draft(it: dict) -> bool:
            if it.get("status") == "accepted":
                return False
            if _obs_ts(it) <= acc_ts:
                return True
            author_cf = str(it.get("author") or it.get("reported_by") or "").strip().casefold()
            val_txt = str(it.get("value") or "").rstrip()
            return author_cf == "antigravity" or val_txt.endswith(("?", "？"))

        older_drafts = [it for it in items if _is_superseded_draft(it)]
        newer_drafts = [it for it in items if it.get("status") != "accepted" and not _is_superseded_draft(it)]
        if older_drafts:
            resolved_pairs.append((newest_acc, older_drafts))
        if len(newer_drafts) >= 2:
            newest_new = max(newer_drafts, key=lambda it: (_obs_ts(it), str(it.get("id") or "")))
            older_new = [it for it in newer_drafts if str(it.get("id")) != str(newest_new.get("id"))]
            resolved_pairs.append((newest_new, older_new))
        # Clear spurious conflicted flag from the active newest_acc / latest newer_draft without hiding newer_draft.
        active_keep = {str(newest_acc.get("id") or "")}
        if newer_drafts:
            newest_new = max(newer_drafts, key=lambda it: (_obs_ts(it), str(it.get("id") or "")))
            active_keep.add(str(newest_new.get("id") or ""))
        for item in items:
            if str(item.get("id") or "") in active_keep and item.get("status") == "conflicted":
                item["status"] = "proposed"

    superseded_ids: dict[str, dict[str, str]] = {}
    winner_ids: set[str] = set()
    for winner, losers in resolved_pairs:
        win_id = str(winner.get("id") or "")
        winner_ids.add(win_id)
        win_title = str(winner.get("short_title") or summarize_node_title(winner.get("value") or "", max_chars=24))
        for loser in losers:
            lid = str(loser.get("id") or "")
            if lid and lid != win_id:
                superseded_ids[lid] = {"fact_id": win_id, "title": win_title}

    if superseded_ids or len(kept_conflicts) != len(conflicts):
        def _normalize_list(facts_list: list[dict]) -> None:
            for item in facts_list:
                fid = str(item.get("id") or "")
                if fid in winner_ids and item.get("status") == "conflicted":
                    item["status"] = "proposed"
                elif fid in superseded_ids:
                    if item.get("status") == "conflicted":
                        item["status"] = "proposed"
                    item["superseded_by_fact_id"] = superseded_ids[fid]["fact_id"]
                    item["superseded_by_title"] = superseded_ids[fid]["title"]
                elif item.get("status") == "conflicted" and str(item.get("subject_key") or "") not in {
                    str(c.get("subject_key") or "") for c in kept_conflicts
                }:
                    item["status"] = "proposed"

        _normalize_list(team_facts)
        for member_view in (views.get("personal") or {}).values():
            _normalize_list(list(member_view.get("facts") or []))
        team["conflicts"] = kept_conflicts
    return {"superseded_count": len(superseded_ids)}


def _build_raw_fact_metadata_index(events: list[EvidenceEvent]) -> dict[str, dict[str, Any]]:
    """Build an O(N) lookup of rich fact metadata by fact_id, source span, or latest (subject, quote)."""
    by_fid: dict[str, dict[str, Any]] = {}
    for ev in events:
        raw_facts = ev.metadata.get("facts") if isinstance(ev.metadata, dict) else None
        if not isinstance(raw_facts, list):
            continue
        for idx, item in enumerate(raw_facts):
            if not isinstance(item, dict):
                continue
            digest = sha1(f"{ev.id}:{idx}".encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
            by_fid[f"fact-{digest}"] = item
            src_id = str(item.get("source_id") or ev.id)
            subj = str(item.get("subject_key") or "")
            quote = str(item.get("quote") or "").strip()
            if src_id and quote:
                by_fid[f"eq:{src_id}\n{quote}"] = item
            if subj and quote:
                # Overwrite with newer event metadata rather than freezing stale open_fork state.
                by_fid[f"sq:{subj}\n{quote}"] = item
    return by_fid


def _lookup_raw_fact_metadata(fact: dict, meta_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fid = str(fact.get("id") or "")
    if fid in meta_index:
        return meta_index[fid]
    quote = str(fact.get("quote") or fact.get("value") or "").strip()
    for eid in fact.get("evidence_ids") or ():
        hit = meta_index.get(f"eq:{eid}\n{quote}")
        if hit is not None:
            return hit
    subj = str(fact.get("subject_key") or "")
    return meta_index.get(f"sq:{subj}\n{quote}", {})


def _infer_stage_for_fact(fact: dict, meta: dict[str, Any]) -> tuple[str, list[str], str]:
    stage = str(meta.get("decision_stage") or "").strip()
    alts = [str(a) for a in (meta.get("alternatives") or []) if str(a).strip()]
    reason = str(meta.get("rejection_reason") or "").strip()
    text = f"{fact.get('quote') or ''} {fact.get('value') or ''}".strip()
    probe = _QUOTED_UI_MENTION_RE.sub(" ", clean_display_text(text)).strip()
    is_question = bool(_INTERROGATIVE_RE.search(text))

    if not stage:
        if fact.get("kind") == "assumption":
            stage = "premise"
        elif not is_question and _REJECTED_RE.search(probe):
            stage = "rejected_path"
            if not reason:
                reason = _extract_rejection_reason(text)
        elif _OPEN_FORK_RE.search(probe) or _OPTION_BULLET_RE.search(probe):
            cand_alts = alts or _extract_alternatives_from_text(probe)
            if len(cand_alts) >= 2:
                stage = "open_fork"
                alts = cand_alts
            else:
                stage = "proposed"
        elif fact.get("kind") == "decision":
            stage = "settled" if fact.get("status") == "accepted" or _SETTLED_RE.match(clean_display_text(text)) else "proposed"
        else:
            stage = str(fact.get("kind") or "task")
    elif stage == "open_fork" and not alts:
        alts = _extract_alternatives_from_text(probe)
    elif stage == "rejected_path" and not reason:
        reason = _extract_rejection_reason(text)
    return stage, alts, reason


def attach_decision_context(
    team_facts: list[dict],
    personal_views: dict[str, dict],
    events: list[EvidenceEvent],
    *,
    derived_context_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach causal alternatives, premise verification states, and rejected paths onto facts."""
    meta_index = _build_raw_fact_metadata_index(events)
    event_step_by_id: dict[str, int] = {}
    for ev in events:
        if isinstance(ev.metadata, dict):
            step_val = ev.metadata.get("step_index")
            if type(step_val) is int:
                event_step_by_id[ev.id] = step_val
    exec_events = [
        ev
        for ev in events
        if ev.kind in {"test_result", "command_execution", "tool_result"}
    ][-200:]
    exec_records: list[tuple[float, int | None, set[str]]] = []
    for ev in exec_events:
        code = ev.metadata.get("exit_code") if isinstance(ev.metadata, dict) else None
        if type(code) is not int:
            continue
        preview = str(ev.metadata.get("command_preview") or ev.metadata.get("source_ref") or "")
        tokens = _extract_tokens(f"{ev.content[:1500]} {preview}")
        exec_records.append((ev.observed_at.timestamp(), code, tokens))

    meta_by_id: dict[str, dict[str, Any]] = {}
    stage_by_id: dict[str, tuple[str, list[str], str]] = {}
    premise_nodes: list[dict[str, Any]] = []
    fork_nodes: list[dict[str, Any]] = []
    rejected_nodes: list[dict[str, Any]] = []

    for fact in team_facts:
        fid = str(fact.get("id") or "")
        meta = _lookup_raw_fact_metadata(fact, meta_index)
        meta_by_id[fid] = meta
        stage, alts, reason = _infer_stage_for_fact(fact, meta)
        stage_by_id[fid] = (stage, alts, reason)

        title = str(fact.get("short_title") or summarize_node_title(fact.get("value") or "", max_chars=28))
        raw_ev_ids = [str(eid) for eid in (fact.get("evidence_ids") or ()) if eid]
        ev_ids = raw_ev_ids[:4]
        ev_id_set = set(raw_ev_ids)
        step_indices = {event_step_by_id[eid] for eid in raw_ev_ids if eid in event_step_by_id}
        try:
            fact_ts = as_utc_timestamp(fact.get("observed_at") or "").timestamp()
        except (TypeError, ValueError):
            fact_ts = 0.0

        if fact.get("kind") == "assumption":
            prem_tokens = _extract_tokens(f"{fact.get('value') or ''} {fact.get('quote') or ''}")
            p_status = "verified" if fact.get("status") == "accepted" else str(meta.get("premise_status") or "unverified")
            if fact.get("speculative_verified"):
                p_status = "verified"
            elif fact.get("status") != "accepted" and prem_tokens:
                latest_hit: tuple[float, int] | None = None
                for ts, code, e_toks in exec_records:
                    if ts >= fact_ts and len(prem_tokens & e_toks) >= 2:
                        if latest_hit is None or ts >= latest_hit[0]:
                            latest_hit = (ts, code)
                if latest_hit is not None:
                    p_status = "verified" if latest_hit[1] == 0 else "invalidated"
            node = {
                "fact_id": fid,
                "title": title,
                "value": clean_display_text(fact.get("value") or "", max_chars=140),
                "status": p_status,
                "author": fact.get("author"),
                "session_id": fact.get("session_id"),
                "is_historical_doc": bool(fact.get("is_historical_doc") or is_historical_doc_fact(fact)),
                "tokens": prem_tokens,
                "evidence_ids": ev_ids,
                "evidence_id_set": ev_id_set,
                "step_indices": step_indices,
            }
            premise_nodes.append(node)
        elif stage == "open_fork":
            fork_nodes.append({
                "fact_id": fid,
                "title": title,
                "alternatives": alts,
                "status": fact.get("status"),
                "session_id": fact.get("session_id"),
                "is_historical_doc": bool(fact.get("is_historical_doc") or is_historical_doc_fact(fact)),
                "tokens": _extract_tokens(f"{fact.get('value') or ''} {' '.join(alts)}"),
                "evidence_ids": ev_ids,
            })
        elif stage == "rejected_path":
            rejected_nodes.append({
                "fact_id": fid,
                "title": title,
                "value": clean_display_text(fact.get("value") or "", max_chars=140),
                "reason": reason or "已明确排除该路线",
                "session_id": fact.get("session_id"),
                "is_historical_doc": bool(fact.get("is_historical_doc") or is_historical_doc_fact(fact)),
                "tokens": _extract_tokens(f"{fact.get('value') or ''} {reason}"),
                "evidence_ids": ev_ids,
                "evidence_id_set": ev_id_set,
                "step_indices": step_indices,
            })

    live_premises = [p for p in premise_nodes if not p["is_historical_doc"]] or premise_nodes
    live_rejected = [r for r in rejected_nodes if not r["is_historical_doc"]] or rejected_nodes

    def _adjacent_or_shared(sess_a: str | None, steps_a: set[int], evs_a: set[str], target: dict[str, Any]) -> bool:
        if evs_a & target["evidence_id_set"]:
            return True
        if sess_a and target["session_id"] == sess_a and steps_a and target["step_indices"]:
            return min(abs(sa - sb) for sa in steps_a for sb in target["step_indices"]) <= 2
        return False

    context_by_id: dict[str, dict[str, Any]] = {}
    for fact in team_facts:
        fid = str(fact.get("id") or "")
        stage, alts, reason = stage_by_id.get(fid, ("proposed", [], ""))
        f_tokens = _extract_tokens(f"{fact.get('value') or ''} {fact.get('quote') or ''}")
        sess = fact.get("session_id")
        f_ev_ids = {str(eid) for eid in (fact.get("evidence_ids") or ()) if eid}
        f_steps = {event_step_by_id[eid] for eid in f_ev_ids if eid in event_step_by_id}

        linked_premises: list[dict[str, Any]] = []
        linked_rejected: list[dict[str, Any]] = []
        if fact.get("kind") == "assumption":
            own = next((p for p in premise_nodes if p["fact_id"] == fid), None)
            if own:
                linked_premises.append({
                    "fact_id": own["fact_id"],
                    "title": own["title"],
                    "status": own["status"],
                    "evidence_ids": own["evidence_ids"],
                })
        elif stage != "rejected_path":
            for p in live_premises:
                overlap = len(f_tokens & p["tokens"])
                same_source = bool(f_ev_ids & p["evidence_id_set"])
                adjacent = _adjacent_or_shared(sess, f_steps, f_ev_ids, p)
                if overlap >= 2 or same_source or (adjacent and overlap >= 1):
                    linked_premises.append({
                        "fact_id": p["fact_id"],
                        "title": p["title"],
                        "status": p["status"],
                        "evidence_ids": p["evidence_ids"],
                    })

            for r in live_rejected:
                if r["fact_id"] == fid:
                    continue
                overlap = len(f_tokens & r["tokens"])
                same_source = bool(f_ev_ids & r["evidence_id_set"])
                adjacent = _adjacent_or_shared(sess, f_steps, f_ev_ids, r)
                if overlap >= 2 or same_source or (adjacent and overlap >= 1):
                    linked_rejected.append({
                        "fact_id": r["fact_id"],
                        "title": r["title"],
                        "reason": r["reason"],
                        "evidence_ids": r["evidence_ids"],
                    })

        ctx_payload: dict[str, Any] = {
            "stage": stage,
            "alternatives": alts,
            "premises": linked_premises[:3],
            "rejected_paths": linked_rejected[:2],
        }
        if reason:
            ctx_payload["rejection_reason"] = reason
        if fact.get("kind") == "assumption" and linked_premises:
            ctx_payload["premise_status"] = linked_premises[0]["status"]
        context_by_id[fid] = ctx_payload
        fact["decision_context"] = ctx_payload

    for member_view in (personal_views or {}).values():
        for m_fact in member_view.get("facts") or []:
            fid = str(m_fact.get("id") or "")
            if fid in context_by_id:
                m_fact["decision_context"] = dict(context_by_id[fid])

    active_forks = [f for f in fork_nodes if not f["is_historical_doc"] and f.get("status") != "accepted"]
    return {
        "settled_count": sum(1 for _, (st, _, _) in stage_by_id.items() if st == "settled"),
        "open_forks_count": len(active_forks),
        "open_forks": [
            {k: v for k, v in row.items() if k != "tokens"}
            for row in active_forks[:5]
        ],
        "unverified_premises_count": sum(1 for p in live_premises if p["status"] == "unverified"),
        "invalidated_premises_count": sum(1 for p in live_premises if p["status"] == "invalidated"),
        "premises": [
            {k: v for k, v in row.items() if k not in {"tokens", "evidence_id_set", "step_indices"}}
            for row in live_premises[:6]
        ],
        "rejected_paths_count": len(live_rejected),
        "rejected_paths": [
            {k: v for k, v in row.items() if k not in {"tokens", "evidence_id_set", "step_indices"}}
            for row in live_rejected[:6]
        ],
    }


def is_legacy_noise_fact(fact: dict[str, Any] | Any) -> bool:
    """Identify unconfirmed legacy interrogative/ephemeral-choice noise at read time without mutating raw history."""
    if not isinstance(fact, dict):
        return False
    if fact.get("status") == "accepted" or fact.get("kind") == "goal":
        return False
    raw = str(fact.get("quote") or fact.get("value") or "").strip()
    if not raw:
        return False
    if _INTERROGATIVE_RE.search(raw):
        return True
    ask_match = _ASK_CHOICE_LINE_RE.match(raw)
    if ask_match:
        body = ask_match.group(1).strip()
        if (
            len(body) < 12
            or _LOW_SIGNAL_CHOICE_PREFIX_RE.match(body)
            or (_EPHEMERAL_ASK_ACTION_RE.search(body) and not _DURABLE_CHOICE_SIGNAL_RE.search(body))
            or _INTERROGATIVE_RE.search(body)
        ):
            return True
    return False


_NON_OWNER_AUTHORS = frozenset({"antigravity", "assistant", "project-documents", "scanner"})
_RELEASE_VERSION_RE = re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b", re.IGNORECASE)
_PAST_RELEASE_DONE_RE = re.compile(r"已实现|验证通过|联调通过|已接通|已就绪")
_TOPIC_UX_RE = re.compile(
    r"界面|视觉|主题|配色|亮色|米白|暗色|脑图|导图|文案|大白话|交互|看板|侧边栏|窄栏|按钮|折叠|弹窗|搜索框|输入框|用户体验|logo|徽标|模板|\b(?:ui|ux|layout|design)\b",
    re.IGNORECASE,
)
_TOPIC_ARCH_RE = re.compile(
    r"架构|零依赖|python|数据库|存储|协议|接口|api|mcp|锁|性能|索引|安全|权限|模型|llm|缓存|并发|框架|不引入|后端|前端|部署|插件|来源|规则|过滤|归类|自动|同步|测试|评测|stdlib|sqlite",
    re.IGNORECASE,
)


def is_owner_dialogue_decided_fact(
    fact: dict[str, Any] | Any,
    source_event: Any = None,
    *,
    owner_id: str = "",
    can_review: bool = True,
    team_enabled: bool = False,
) -> bool:
    """Return True when a proposed decision was explicitly chosen by the local owner in dialogue."""
    if not can_review or not isinstance(fact, dict):
        return False
    if fact.get("kind") != "decision" or fact.get("status") != "proposed":
        return False
    if is_legacy_noise_fact(fact) or fact.get("is_historical_doc") or is_historical_doc_fact(fact):
        return False
    if fact.get("claim_type") == "assistant_report":
        return False
    fact_author = str(fact.get("author") or "").strip()
    if not fact_author or fact_author.lower() in _NON_OWNER_AUTHORS:
        return False
    if source_event is None or getattr(source_event, "kind", "") != "user_message":
        return False
    ev_meta = getattr(source_event, "metadata", None)
    meta = ev_meta if isinstance(ev_meta, dict) else {}
    capture = str(meta.get("capture") or "").strip()
    if capture != "antigravity-ask-question" and fact.get("claim_type") != "conversation_exchange":
        return False
    if str(meta.get("role") or "user").strip().lower() != "user":
        return False
    if team_enabled:
        owner_norm = str(owner_id or "").strip().casefold()
        if not owner_norm or fact_author.casefold() != owner_norm:
            return False
    return True


def classify_mindmap_topic(
    fact: dict[str, Any],
    *,
    is_completed: bool = False,
    is_stale: bool = False,
) -> str:
    """Classify a mindmap node into generic collapsible topic groups without domain lock-in."""
    kind = str(fact.get("kind") or "decision")
    status = str(fact.get("status") or "proposed")
    text = str(fact.get("clean_value") or fact.get("short_title") or fact.get("value") or "").strip()

    if is_completed:
        return "archive"
    if kind != "task":
        is_past_release = bool(
            status == "accepted"
            and _RELEASE_VERSION_RE.search(text)
            and (is_stale or _PAST_RELEASE_DONE_RE.search(text))
        )
        if is_stale or is_past_release:
            return "archive"

    if status == "conflicted" or kind == "assumption":
        return "open_risks"
    if kind == "task":
        return "execution"
    if kind == "decision":
        if _TOPIC_UX_RE.search(text):
            return "product_ux"
        if _TOPIC_ARCH_RE.search(text):
            return "architecture"
    return "decisions"
