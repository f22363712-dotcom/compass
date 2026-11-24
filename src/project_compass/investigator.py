from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from .candidate_extraction import current_file_snapshots, source_claim_type
from .evidence_filters import SENSITIVE, is_platform_control, is_public_raw_event, resolve_member_id
from .fact_engine import derive_facts
from .intent_vocab import (
    BLOCKED_QUERY_TERMS,
    DIRECTION_QUERY_TERMS,
    GAP_QUERY_TERMS,
    GENERAL_QUESTION_TERMS,
    MEMBER_ASSUMPTION_TERMS,
    MEMBER_DECISION_TERMS,
    MEMBER_NEXT_TERMS,
    MEMBER_TASK_TERMS,
    MEMBER_UNFINISHED_TERMS,
    TRANSLATION_EXCLUSION_TERMS,
    WHY_STATE_QUERY_TERMS,
    is_recent_completed_query,
)
from .models import CandidateFact, EvidenceEvent, FactKind
from .source_currentness import source_states, needs_source_review
from .literal_relevance import rank_literal
from .raw_source_investigation import extend_raw_sources, raw_requests, raw_scope_question
from .directions import extend_direction_answer, direction_requested
from .derived_context import fact_chain_of_recall, analyze_contract_risk
from .text_summary import clean_display_text


def _is_static_doc_fact(fact: CandidateFact) -> bool:
    if fact.author == "project-documents":
        return True
    return any(str(eid).startswith("scan-file-") for eid in (fact.evidence_ids or ()))


_COMPLETED_SEMANTIC_TERMS = (
    "已完成",
    "已验收",
    "已接通",
    "已实现",
    "已交付",
    "已落地",
    "跑通",
    "封板",
    "封存",
    "闭环",
    "收口",
    "联调验证通过",
    "就绪",
    "completed",
    "shipped",
    "adopted",
)
_COMPLETED_NEGATIVE_TERMS = ("未完成", "待完成", "尚未", "unfinished", "pending")


def _is_completed_fact(fact: CandidateFact) -> bool:
    if fact.task_state in {"pending", "active", "blocked"}:
        return False
    if fact.kind is FactKind.TASK and fact.task_state == "reported_complete":
        return True
    if fact.kind is FactKind.DECISION:
        text = f"{fact.quote or ''} {fact.value or ''}"
        lower = text.casefold()
        if any(neg in lower for neg in _COMPLETED_NEGATIVE_TERMS):
            return False
        return any(tok in lower for tok in _COMPLETED_SEMANTIC_TERMS)
    return False


def _completed_sort_key(
    fact: CandidateFact,
    sources: dict[str, EvidenceEvent],
    is_accepted: bool,
) -> tuple:
    text = f"{fact.quote or ''} {fact.value or ''}"
    explicit_dates = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
    src = sources.get(fact.evidence_ids[0]) if fact.evidence_ids else None
    src_meta = src.metadata if (src is not None and isinstance(src.metadata, dict)) else {}
    src_mod = str(src_meta.get("source_modified_at") or "")
    if explicit_dates:
        date_key = max(explicit_dates)
    elif len(src_mod) >= 10:
        date_key = src_mod[:10]
    else:
        date_key = fact.observed_at.isoformat()[:10]
    versions = [
        (int(a), int(b), int(c or 0))
        for a, b, c in re.findall(r"\bv(\d+)\.(\d+)(?:\.(\d+))?\b", text, re.I)
    ]
    ver_key = max(versions) if versions else (0, 0, 0)
    m_stages = [int(m) for m in re.findall(r"\bM(\d+)\b", text)]
    m_key = max(m_stages) if m_stages else -1
    live_priority = 0 if _is_static_doc_fact(fact) else 1
    return (
        date_key,
        ver_key,
        m_key,
        1 if is_accepted else 0,
        fact.observed_at.isoformat(),
        live_priority,
    )


@dataclass(frozen=True)
class ConflictSide:
    value: str
    evidence_ids: tuple[str, ...]
    author: str
    status: str = "conflicted"
    source_status: str = 'recorded'
    observed_at: str | None = None
    source_kind: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class Conflict:
    subject_key: str
    sides: tuple[ConflictSide, ...]


@dataclass(frozen=True)
class InvestigationAnswer:
    question: str
    conclusion: str
    goal: str
    active_tasks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    conflicts: tuple[Conflict, ...]
    next_action: str
    acceptance_condition: str
    evidence_gaps: tuple[str, ...]
    findings: tuple[dict, ...] = ()
    next_action_status: str | None = None
    source_warnings: tuple[dict, ...] = ()
    scope: dict | None = None
    next_action_basis: dict | None = None
    chain_of_recall: tuple[dict, ...] = ()
    contract_risk: tuple[dict, ...] = ()
    completed_items: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        payload = {
            "question": self.question,
            "conclusion": self.conclusion,
            "goal": self.goal,
            "active_tasks": list(self.active_tasks),
            "evidence_ids": list(self.evidence_ids),
            "assumptions": list(self.assumptions),
            "conflicts": [{"subject_key": item.subject_key, "sides": [{"value": side.value, "evidence_ids": list(side.evidence_ids), "author": side.author, "status": side.status, 'source_status': side.source_status,
                'observed_at': side.observed_at, 'source_kind': side.source_kind, 'session_id': side.session_id} for side in item.sides]} for item in self.conflicts],
            "next_action": self.next_action,
            "acceptance_condition": self.acceptance_condition,
            "evidence_gaps": list(self.evidence_gaps),
            "findings": list(self.findings),
            "next_action_status": self.next_action_status,
            'source_warnings': list(self.source_warnings),
            'scope': self.scope,
            'next_action_basis': self.next_action_basis,
            'chain_of_recall': list(self.chain_of_recall),
            'contract_risk': list(self.contract_risk),
        }
        if self.completed_items:
            payload["completed_items"] = list(self.completed_items)
        return payload


def _is_clean_raw_event(event: EvidenceEvent) -> bool:
    """Return True when raw event content is non-sensitive public record (not internal reasoning/control)."""
    meta = event.metadata if hasattr(event, "metadata") and isinstance(event.metadata, dict) else {}
    return (
        not is_platform_control(event.content, kind=event.kind)
        and meta.get("phase") not in {"analysis", "reasoning"}
        and meta.get("role") not in {"analysis", "reasoning"}
        and not SENSITIVE.search(event.content)
    )


def _member_query(events, facts, question, session_members, *, raw_query=False, direction_query=False, current_member=None):
    public_kinds = {'agent_message', 'assistant_message', 'user_message', 'tool_call',
                    'tool_result', 'command_execution', 'test_result', 'file_change'}
    raw = [e for e in events if e.kind in public_kinds and _is_clean_raw_event(e)]
    members = sorted(({resolve_member_id(e, session_members=session_members) for e in raw}
                      | {f.author for f in facts}) - {'project-documents'})
    if current_member and current_member in members and re.search(r'(?<!我)我(?:的|有|有哪些|有什么|刚才|最近|今天|目前|现在|还有|做了|负责)', question) and '我们' not in question:
        return {'kind': 'member', 'member_id': current_member}, [e for e in raw
            if resolve_member_id(e, session_members=session_members) == current_member]
    if raw_query:question=raw_scope_question(question,known_members=members,sources=raw)
    # ASCII identity boundaries allow Chinese questions without spaces while
    # avoiding Ann/Anna and dev-a/dev-a-extra collisions.
    def complete_mention(match):
        before, after = question[:match.start()], question[match.end():]
        if before and before[-1].isalnum() and not before[-1].isascii():
            if not re.search(r'(?:请问|问一下|关于|查看|查询|看看|成员|同事|和|与|及|为什么|为何)$', before):
                return False
        if after and after[0].isalnum() and not after[0].isascii():
            suffix=r'(?:做了|做过|做什么|负责|的|下一步|接下来|当前|目前|最近|今天|分别|和|与|及|进展|状态|为什么|为何)'
            if raw_query:suffix=r'(?:命令|终端|测试|工具|提交|原始)|'+suffix
            if direction_query:suffix=r'(?:舍弃|放弃|暂缓|延期|恢复|为什么|为何)|'+suffix
            if not re.match(suffix, after):
                return False
        return True

    mentions = [(match.start(), match.end(), member) for member in members
                for match in re.finditer(r'(?<![A-Za-z0-9_-])' + re.escape(member)
                                        + r'(?![A-Za-z0-9_-])', question, re.I) if complete_mention(match)]
    # A full identity owns its span; a separate short-name mention still counts.
    matched = sorted({member for start, end, member in mentions if not any(
        low <= start and high >= end and (low, high) != (start, end)
        for low, high, _ in mentions)})
    if len(matched) == 1:
        member = matched[0]
        return {'kind': 'member', 'member_id': member}, [e for e in raw
            if resolve_member_id(e, session_members=session_members) == member]
    query = question.casefold()
    actions=r'下一步|接下来|当前状态|状态|进展|做了|做过|负责|\b(?:next|status|progress|tasks?|decisions?)\b'
    if raw_query:actions+=r'|命令|终端|测试|工具|(?<![a-z0-9_])(?:git|commits?|commands?|terminal|tests?|tools?)(?![a-z0-9_])'
    if direction_query:actions+=r'|舍弃|放弃|暂缓|延期|恢复|\b(?:abandon|abandoned|defer|deferred|discard|restore)\b'
    clauses = [seg.strip() for seg in re.split(r'[？?。！!；;\n]+', query) if seg.strip()]
    target_clause = next((seg for seg in clauses if re.search(actions, seg)), query)
    action_subject = re.split(actions, target_clause, maxsplit=1)[0].strip(' ，,？?。.!')
    direction_prefix=action_subject
    if raw_query or direction_query:
        action_subject=re.sub(r'请问|请|查看|查询|看看|最近|最新|目前|当前|原始|失败|成功|的|\b(?:show|list|find|recent|latest|raw|the|what|are|is)\b',' ',action_subject).strip()
    generic_subjects = {'', '我们', '我', '咱们', '大家', '现在', '目前', '当前', '然后', '接着', 'what', 'what should we do',
                        'what should i do', 'what should happen', 'what is', 'what are', 'how is', 'how are', 'do'}
    unknown_subject = action_subject != target_clause.strip(' ，,？?。.!') and action_subject not in generic_subjects and not any(
        term in action_subject for term in (
            '项目', '团队', '整体', '全局', '目标', '工作', '共识', '任务', '方案', '方向', '功能', '模块',
            '问题', '看板', '脑图', '搜索', '检索', '什么', '哪些', '哪个', '怎么', '如何', '是否', '有没有',
            'project', 'team', 'goal', 'why', 'what', 'which', 'how',
        )
    )
    if direction_query and not raw_query:
        explicit_member=bool(re.search(r'(?:的|[\u2019\x27]s)\s*$',direction_prefix) or re.fullmatch(r'[a-z0-9_-]+',direction_prefix))
        unknown_subject=unknown_subject and explicit_member and not any(term in direction_prefix for term in ('方案','方向','功能','模块','任务','哪些','什么'))
    why_subject=re.match(r'^\s*(?:请问\s*)?([a-z][a-z0-9_-]*)\s*(?:为什么|为何)',query)
    unknown_why_member=bool(why_subject and why_subject[1] not in {'project','team','we','i'})
    if matched or unknown_subject or unknown_why_member or any(term in query for term in
                      ('同事', '成员', '另一个人', '其他人', '做了什么', 'teammate', 'colleague', 'who did', 'what did')):
        return {'kind': 'member_choice', 'available_members': members}, []
    return None, []


def _member_source_answer(question, scope, raw):
    choice = scope['kind'] == 'member_choice'
    member = scope.get('member_id')
    selected = sorted([e for e in raw if e.content.strip()], key=lambda e: (e.observed_at, e.id), reverse=True)[:3]
    findings = tuple({'quote': e.content[:1600], 'status': 'raw', 'claim_type': source_claim_type(e),
        'member_id': member, 'observed_at': e.observed_at.isoformat(), 'evidence_ids': [e.id],
        'source_kind': e.kind, 'session_id': e.session_id,
        'source_ref': e.metadata.get('source_ref'), 'excerpt_truncated': len(e.content) > 1600} for e in selected)
    names = '、'.join(scope.get('available_members', []))
    conclusion = ('请在问题中写明一个成员名。已知成员有' + names + '。' if names else '尚未找到可识别的成员，请先接入公开记录。') if choice else f'找到 {member} 的公开来源记录，尚未生成该成员的候选声明。'
    return InvestigationAnswer(question, conclusion, '成员记录待明确' if choice else f'{member} 的公开来源记录',
        (), tuple(e.id for e in selected), (), (),
        '在问题中写明一个成员名，再查询其公开记录。' if choice else '打开该成员的来源，核对对应版本和实际检查条件。',
        '回答的成员归属与原文来源一致；报告中的完成状态仍需核对。',
        ('成员指向尚不明确，未选择其他成员的记录。',) if choice else
        ('下方仅为有界原文摘录，尚未提取或确认其任务状态。',), findings, scope=scope)


def _extract_evidence_target_id(question: str) -> str | None:
    text = question.strip().strip('"').strip("'")
    m = re.search(r'(?:call\s+)?query_state\([\'"]?([a-zA-Z0-9_\-\.:]+)[\'"]?\)', text)
    if m:
        return m.group(1)
    if text.startswith("evidence:"):
        return text[len("evidence:"):].strip()
    m2 = re.search(r'\[([a-zA-Z0-9_\-\.:]+):\s*[^\]]+\]\s*->', text)
    if m2:
        return m2.group(1)
    m3 = re.match(r'^(?:展开|查看)?(?:原始)?证据\s*[:：]?\s*([a-zA-Z0-9_\-\.:]+)$', text)
    if m3:
        return m3.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_\-\.:]+', text) and not any(term in text.casefold() for term in {"help", "why", "how", "what", "status", "next", "state", "谁", "什么", "怎么", "状态", "进展"}):
        return text
    return None


def investigate(events: list[EvidenceEvent], question: str, fact_reviews=(), confirmed_relations=(), *, memory_facts=None, memory_support=None, session_members=None, current_member=None, derived_context=None) -> InvestigationAnswer:
    target_id = _extract_evidence_target_id(question)
    sources = {event.id: event for event in events}
    if target_id and target_id in sources:
        event = sources[target_id]
        chains = ()
        if derived_context is not None:
            source_ref = event.metadata.get("source_ref") if hasattr(event, "metadata") and isinstance(event.metadata, dict) else None
            refs = {source_ref} if source_ref else set()
            chains = tuple(derived_context.chain_of_recall(source_refs=refs))
        return InvestigationAnswer(
            question=question,
            conclusion=f"展开证据 {event.id} ({event.kind}, 来源: {event.metadata.get('source_ref') if hasattr(event, 'metadata') and isinstance(event.metadata, dict) else 'direct'})",
            goal="按需展开原始溢出引用",
            active_tasks=(),
            evidence_ids=(event.id,),
            assumptions=(),
            conflicts=(),
            next_action="核对该原始证据的具体内容，若确认为正式结论可记入待确认想法。",
            acceptance_condition="通过证据 ID 精确反查溯源完整原始内容。",
            evidence_gaps=(),
            findings=({
                "quote": event.content,
                "status": "raw",
                "claim_type": "original_material",
                "member_id": resolve_member_id(event, session_members=session_members, route_documents=True),
                "observed_at": event.observed_at.isoformat(),
                "source_kind": event.kind,
                "evidence_ids": [event.id],
                "source_ref": event.metadata.get("source_ref") if hasattr(event, "metadata") and isinstance(event.metadata, dict) else None,
                "metadata": event.metadata if hasattr(event, "metadata") else {},
                "exit_code": event.metadata.get("exit_code") if hasattr(event, "metadata") and isinstance(event.metadata, dict) else None,
            },),
            chain_of_recall=chains,
        )

    derived = derive_facts(events) if memory_facts is None else memory_facts
    answer = _investigate_claims(events, question, fact_reviews, confirmed_relations, memory_facts=derived,
        memory_support=memory_support, session_members=session_members, raw_query=bool(raw_requests(question)[0]), current_member=current_member, derived_context=derived_context)
    if raw_requests(question)[0]:
        return extend_raw_sources(answer, events, question, session_members=session_members, derived_context=derived_context)
    return extend_direction_answer(answer, derived, fact_reviews, events)


def _select_question_findings(
    extracted: list[CandidateFact],
    question: str,
    scope: dict | None,
    status_fn,
    gaps: list[str],
    gap_query: bool,
    current_accepted: dict[str, str],
) -> tuple[list[CandidateFact], list[CandidateFact] | None, list[CandidateFact]]:
    """Select candidate findings matching the question intent and member scope."""
    query = question.casefold()
    pending = [
        fact
        for fact in extracted
        if fact.kind is FactKind.TASK
        and fact.task_state in {"pending", "active", "blocked"}
        and current_accepted.get(fact.subject_key) in (None, fact.id)
    ]
    pending.sort(
        key=lambda fact: (
            status_fn(fact) != "accepted",
            _is_static_doc_fact(fact) and status_fn(fact) != "accepted",
            fact.subject_key != "project.next_step",
        )
    )
    member_pending = [
        fact
        for fact in extracted
        if fact.kind is FactKind.TASK and fact.task_state in {"pending", "active", "blocked"}
    ]
    finding_pool: list[CandidateFact] | None = None
    if scope:
        if any(term in query for term in MEMBER_UNFINISHED_TERMS):
            selected = member_pending + [fact for fact in extracted if fact.kind is FactKind.ASSUMPTION]
        elif any(term in query for term in MEMBER_NEXT_TERMS):
            selected = member_pending
        elif any(term in query for term in MEMBER_TASK_TERMS):
            selected = [fact for fact in extracted if fact.kind is FactKind.TASK]
        elif any(term in query for term in MEMBER_DECISION_TERMS):
            selected = [fact for fact in extracted if fact.kind is FactKind.DECISION]
        elif any(term in query for term in MEMBER_ASSUMPTION_TERMS):
            selected = [fact for fact in extracted if fact.kind is FactKind.ASSUMPTION]
        else:
            selected = extracted
    elif direction_requested(question) or any(term in query for term in DIRECTION_QUERY_TERMS):
        selected = [fact for fact in extracted if fact.kind is FactKind.DECISION]
    elif any(term in query for term in BLOCKED_QUERY_TERMS):
        selected = pending + [fact for fact in extracted if fact.kind is FactKind.ASSUMPTION]
    elif any(term in query for term in MEMBER_NEXT_TERMS) and not any(
        term in query for term in ("为什么", "why", "状态", "state")
    ):
        if any(term in query for term in ("目标", "goal")):
            goal_facts = [fact for fact in extracted if fact.kind is FactKind.GOAL]
            goal_facts.sort(key=lambda fact: (status_fn(fact) != "accepted", _is_static_doc_fact(fact)))
            selected = goal_facts[:1] + pending
        else:
            selected = pending
    elif gap_query:
        selected = [fact for fact in extracted if status_fn(fact) != "accepted"]
        finding_pool = extracted
    elif any(term in query for term in WHY_STATE_QUERY_TERMS):
        selected = (
            [fact for fact in extracted if status_fn(fact) == "accepted"]
            + [fact for fact in extracted if fact.kind is FactKind.ASSUMPTION]
            + pending
        )
        finding_pool = extracted
    elif any(term in query for term in TRANSLATION_EXCLUSION_TERMS):
        selected = []
        gaps.append("当前调查仅支持方向变化、未完成或未验证事项、当前状态及下一步问题；此问题尚未得到回答。")
    else:
        selected = rank_literal(
            question,
            extracted,
            [],
            text=lambda fact: f"{fact.quote or fact.value} {fact.subject_key}",
        )
        finding_pool = selected
    return list({fact.id: fact for fact in selected}.values()), finding_pool, pending


def _investigate_claims(events, question, fact_reviews, confirmed_relations, *, memory_facts, memory_support, session_members, raw_query, current_member=None, derived_context=None):
    facts = derive_facts(events) if memory_facts is None else memory_facts
    all_facts = list(facts)
    scope_question=question
    scope, member_sources = _member_query(events, facts, scope_question, session_members,raw_query=raw_query,direction_query=direction_requested(question), current_member=current_member)
    if scope:
        member_facts = [f for f in facts if f.author == scope.get('member_id')]
        if not member_facts:
            return _member_source_answer(question, scope, member_sources)
        subjects = {f.subject_key for f in member_facts}
        facts = [f for f in facts if f.subject_key in subjects]
    if not facts:
        gap = "已采集材料尚未整理出带来源的待确认想法，无法判断项目当前状态和下一步。" if events else "尚未采集项目证据，无法判断项目状态。"
        return InvestigationAnswer(
            question=question,
            conclusion="证据不足，当前无法形成项目状态结论。",
            goal="未找到已记录的项目目标",
            active_tasks=(),
            evidence_ids=(),
            assumptions=(),
            conflicts=(),
            next_action="先从项目材料提取候选目标和任务，核对来源后再提交团队确认。",
            acceptance_condition="候选目标和任务均能打开对应原文，且未确认条目保持候选状态。",
            evidence_gaps=(gap,),
        )
    accepted_by_subject = {
        str(item.get("subject_key", item.get("fact_id"))): item["fact_id"]
        for item in fact_reviews
        if item.get("action") == "accept_fact" and item.get("fact_id")
    }

    def status(fact: CandidateFact) -> str:
        return "accepted" if accepted_by_subject.get(fact.subject_key) == fact.id else fact.status.value

    sources = {event.id: event for event in events}
    reviews_by_fact = {item.get('fact_id'): item for item in fact_reviews if item.get('action') == 'accept_fact'}

    def finding(fact):
        review = reviews_by_fact.get(fact.id, {}) if status(fact) == 'accepted' else {}
        source = sources.get(fact.evidence_ids[0]) if fact.evidence_ids else None
        return {'fact_id': fact.id, 'quote': fact.quote or fact.value, 'kind': fact.kind.value,
                'claim_type': fact.claim_type, 'status': status(fact), 'evidence_ids': list(fact.evidence_ids),
                'source_ref': fact.source_ref, 'reviewed_by': review.get('reviewer'),
                'reviewed_at': review.get('observed_at'), 'member_id': fact.author,
                'observed_at': fact.observed_at.isoformat(), 'session_id': fact.session_id,
                'source_kind': source.kind if source is not None else None,
                **({'direction_state':review['direction_state'],'current':not needs_source_review(states[fact.id])}
                   if review.get('direction_state') in {'abandoned','deferred','active'} else {})}

    states = source_states(events, facts)
    current_facts = [fact for fact in facts if not needs_source_review(states[fact.id])]
    member_current = [f for f in current_facts if not scope or f.author == scope['member_id']]
    current_accepted = {fact.subject_key: fact.id for fact in current_facts if status(fact) == 'accepted'}
    warnings = tuple({'fact_id': fact.id, 'status': status(fact), 'evidence_ids': list(fact.evidence_ids),
                      'source_state': states[fact.id]} for fact in facts if needs_source_review(states[fact.id]))
    goals = [fact for fact in member_current if fact.kind is FactKind.GOAL]
    tasks = [fact for fact in member_current if fact.kind is FactKind.TASK]
    assumptions = [fact.value for fact in member_current if fact.kind is FactKind.ASSUMPTION]
    relevant_fact_ids = {fact.id for fact in facts}
    relevant_source_ids = {evidence_id for fact in facts if fact.id in relevant_fact_ids for evidence_id in fact.evidence_ids}
    relevant_event_ids = relevant_source_ids | {
        relation.evidence_id for relation in confirmed_relations if relation.fact_id in relevant_fact_ids
    }
    if memory_support is not None:
        relevant_event_ids = {eid for fid, ids in memory_support.items() if fid in relevant_fact_ids for eid in ids}
    relevant_event_ids |= {eid for warning in warnings for key in ('replacement_ids', 'observation_ids') for eid in warning['source_state'][key]}
    evidence_ids = tuple(event.id for event in events if event.id in relevant_event_ids
                         and not is_platform_control(event.content, kind=event.kind))
    by_subject: dict[str, list[CandidateFact]] = defaultdict(list)
    for fact in facts:
        by_subject[fact.subject_key].append(fact)
    conflicts: list[Conflict] = []
    for subject_key in sorted(by_subject):
        candidates = by_subject[subject_key]
        if len({item.value for item in candidates}) > 1:
            conflicts.append(Conflict(subject_key, tuple(ConflictSide(fact.value, fact.evidence_ids,
                fact.author, status(fact), states[fact.id]['status'], fact.observed_at.isoformat(),
                sources[fact.evidence_ids[0]].kind if fact.evidence_ids and fact.evidence_ids[0] in sources else None,
                fact.session_id) for fact in candidates)))
    accepted_goals = [fact for fact in goals if status(fact) == "accepted"]
    live_goals = [fact for fact in goals if not _is_static_doc_fact(fact)]
    chosen_goal_fact = accepted_goals[-1] if accepted_goals else (live_goals[-1] if live_goals else (goals[-1] if goals else None))
    goal = chosen_goal_fact.value if chosen_goal_fact else "未找到已记录的项目目标"
    active_tasks = tuple(
        fact.value
        for fact in tasks
        if current_accepted.get(fact.subject_key) in (None, fact.id) and fact.task_state != "reported_complete"
    )
    unresolved = [conflict for conflict in conflicts if not any(side.status == "accepted" and side.source_status not in {'superseded', 'unavailable'} for side in conflict.sides)]
    gaps = []
    gap_query = any(term in question.casefold() for term in GAP_QUERY_TERMS)
    if not goals:
        gaps.append("尚未提取到该成员的目标候选。" if scope else "尚未提取到带来源的项目目标。")
    if not tasks:
        gaps.append("尚未提取到该成员的任务候选。" if scope else "尚未提取到带来源的任务状态。")
    if warnings:
        gaps.append(f'{len(warnings)} 条声明的文件来源已换版或当前不可用，原确认保留，当前状态需要复核。')
    if unresolved:
        next_action = "核对冲突任务的真实状态，并由项目负责人确认当前状态。"
        acceptance = "项目看板保留双方证据，负责人确认后生成一条带证据链接的当前团队事实。"
    elif warnings and not current_facts:
        next_action = '先检查变更后的来源并重新提取候选，再由负责人核对当前状态。'
        acceptance = '旧来源和确认历史保留，新版本的候选有独立证据且不会自动继承确认。'
    elif not current_accepted:
        next_action = "先核对这些待确认想法的来源，再由项目负责人确认。"
        acceptance = "确认记录包含负责人和来源，待确认想法不会自动变成已确认事项。"
    else:
        next_action = "按已确认的团队事实推进，并核对剩余证据缺口。"
        acceptance = "当前团队事实保持 accepted，来源证据和历史冲突均可在看板中打开。"
    if gap_query:
        pending_gap_facts = [fact for fact in facts if status(fact) != "accepted"]
        if pending_gap_facts:
            gaps.insert(0, f"{len(pending_gap_facts)} 条待确认想法仍未负责人确认，需要核对对应来源和当前性。")
        if warnings:
            gaps.insert(0, f"{len(warnings)} 条声明的来源已换版或不可用，需要补充当前版本证据。")
        if not pending_gap_facts and not warnings:
            gaps.insert(0, "当前已采集材料没有识别出待补证据；仍需结合回填进度检查未覆盖历史。")
    conclusion = f"项目当前围绕“{goal}”推进，共记录 {len(active_tasks)} 条当前任务状态；保留 {len(conflicts)} 个可追溯冲突。"
    if warnings and not current_facts:
        conclusion = '现有声明的文件来源已变化或不可用，尚无可用于当前状态结论的候选；请先复核来源。'
    findings = []
    completed_items: tuple[dict, ...] = ()
    next_action_status = None
    next_action_basis = None
    recent_completed_mode = is_recent_completed_query(question)
    extracted = sorted([fact for fact in member_current if fact.quote or scope], key=lambda fact: fact.observed_at, reverse=True)
    if extracted:
        completed_facts: list[CandidateFact] = []
        if recent_completed_mode:
            completed_facts = [fact for fact in extracted if _is_completed_fact(fact)]
            if not completed_facts and (not scope or scope.get("member_id") == current_member):
                completed_facts = [
                    fact
                    for fact in all_facts
                    if not needs_source_review(states.get(fact.id, {})) and _is_completed_fact(fact)
                ]
            completed_facts.sort(
                key=lambda fact: _completed_sort_key(fact, sources, status(fact) == "accepted"),
                reverse=True,
            )

        selected, finding_pool, pending = _select_question_findings(
            extracted, question, scope, status, gaps, gap_query, current_accepted
        )
        ranking_question = question
        if scope:
            ranking_question = re.sub(r'(?<![A-Za-z0-9_-])' + re.escape(scope['member_id']) +
                                      r'(?![A-Za-z0-9_-])', ' ', question, flags=re.I)
        if recent_completed_mode and completed_facts:
            top_completed = completed_facts[:3]
            selected = top_completed
            ranked_facts = top_completed
            completed_items = tuple(finding(fact) for fact in top_completed)
            for item in completed_items:
                for eid in item.get("evidence_ids") or ():
                    if eid not in evidence_ids:
                        evidence_ids = (*evidence_ids, eid)
        else:
            pool = selected if finding_pool is None else finding_pool
            ranked_facts = rank_literal(ranking_question, pool, [], text=lambda fact: f"{fact.quote or fact.value} {fact.subject_key}")
            if finding_pool is not None and len(finding_pool) == 0:
                selected = []
            else:
                selected = ranked_facts or selected
        # When querying next-step on real repo data, avoid promoting legacy static plan checkboxes as findings
        if selected and not recent_completed_mode and not scope and any(term in question.casefold() for term in MEMBER_NEXT_TERMS):
            live_sel = [f for f in selected if not _is_static_doc_fact(f) or status(f) == "accepted"]
            if live_sel:
                selected = live_sel
        if (
            not recent_completed_mode
            and not scope
            and any(term in question.casefold() for term in MEMBER_NEXT_TERMS)
            and any(term in question.casefold() for term in ("目标", "goal"))
        ):
            anchor_pair = []
            if chosen_goal_fact is not None and chosen_goal_fact in extracted:
                anchor_pair.append(chosen_goal_fact)
            if pending:
                anchor_pair.append(pending[0])
            selected = list({f.id: f for f in [*anchor_pair, *selected]}.values())
        for fact in selected[:3]:
            findings.append(finding(fact))
        raw_hits: list[EvidenceEvent] = []
        promote_raw_findings = len(findings) == 0
        if not ranked_facts and not any("尚未得到回答" in gap for gap in gaps):
            current_snapshot_ids = {snap.id for snap in current_file_snapshots(events)}
            raw_pool = [
                event
                for event in events
                if is_public_raw_event(event)
                and event.kind != "file_unavailable"
                and (event.kind != "file_snapshot" or event.id in current_snapshot_ids)
                and _is_clean_raw_event(event)
                and (not scope or resolve_member_id(event, session_members=session_members, route_documents=True) == scope["member_id"])
            ]
            raw_hits = rank_literal(ranking_question, raw_pool, [], text=lambda event: event.content)
            for raw_event in raw_hits[:3]:
                lines = [ln.strip() for ln in raw_event.content.splitlines() if ln.strip()]
                best_lines = rank_literal(ranking_question, lines, lines[:2], text=lambda ln: ln)
                excerpt = " ".join(best_lines[:2])[:320]
                if promote_raw_findings:
                    src_ref = raw_event.metadata.get("source_ref") if isinstance(raw_event.metadata, dict) else None
                    findings.append({
                        "quote": excerpt or raw_event.content[:320],
                        "status": "raw",
                        "claim_type": source_claim_type(raw_event),
                        "member_id": resolve_member_id(raw_event, session_members=session_members, route_documents=True),
                        "observed_at": raw_event.observed_at.isoformat(),
                        "evidence_ids": [raw_event.id],
                        "source_kind": raw_event.kind,
                        "session_id": raw_event.session_id,
                        "source_ref": src_ref,
                        "excerpt_truncated": len(raw_event.content) > 320,
                    })
                else:
                    gaps.append(f"事实层未覆盖该问题，原始来源线索 [{raw_event.id}]：{excerpt}")
                if raw_event.id not in evidence_ids:
                    evidence_ids = (*evidence_ids, raw_event.id)
        has_settled_next_step = bool(
            not scope
            and pending
            and pending[0].subject_key == "project.next_step"
            and status(pending[0]) == "accepted"
        )
        if has_settled_next_step:
            chosen_next = pending[0]
            next_action = clean_display_text(chosen_next.value)
            next_action_status = status(chosen_next)
            next_action_basis = finding(chosen_next)
            acceptance = "按已确认的当前下一步推进，并在完成后更新工作台记录。"
            if unresolved:
                gaps.append(f"另有 {len(unresolved)} 处分歧待确认，详情见工作台分歧对照。")
        elif not unresolved and pending:
            chosen_pending = pending[0]
            only_static_pending = _is_static_doc_fact(chosen_pending) and status(chosen_pending) != "accepted"
            live_cands = [f for f in extracted if not _is_static_doc_fact(f) and status(f) != "accepted"]
            if only_static_pending and not scope and live_cands:
                live_lead = next((f for f in live_cands if f.kind in {FactKind.DECISION, FactKind.ASSUMPTION}), live_cands[0])
                next_action = f"核对并确认活跃待确认项「{clean_display_text(live_lead.value, max_chars=48)}」，并在工作台设定当前下一步。"
                next_action_status = status(live_lead)
                next_action_basis = finding(live_lead)
                acceptance = "确认或改写上述活跃事项，历史计划文档勾选不自动作为当前下一步。"
            else:
                next_action = chosen_pending.value if scope else clean_display_text(chosen_pending.value)
                next_action_status = status(chosen_pending)
                next_action_basis = finding(chosen_pending)
                acceptance = "按来源原文核对该待办的结果与验收条件；尚未确认的完成报告须由项目负责人审核。"
        if any(status(fact) != "accepted" for fact in extracted):
            gaps.append("部分来源声明仍待确认；已确认条目单独标记为已确认。")
        gaps.append("本次检索覆盖当前有效记录，未确认条目的适用性仍需结合来源时间核对。")
        clean_goal = clean_display_text(goal, max_chars=52)
        if completed_items:
            latest_completed_text = clean_display_text(completed_items[0].get("quote") or "", max_chars=64)
            if next_action_status == "accepted" or pending:
                conclusion = f"近期已完成：{latest_completed_text}；当前下一步：{clean_display_text(next_action, max_chars=52)}。"
            else:
                conclusion = f"近期已完成：{latest_completed_text}（共检索到 {len(completed_items)} 条最新完成记录）。"
        elif findings:
            conclusion = f"围绕核心目标“{clean_goal}”，检索到 {len(findings)} 条直接相关记录；当前下一步：{clean_display_text(next_action, max_chars=56)}。"
        elif any("尚未得到回答" in gap for gap in gaps):
            conclusion = f"当前问题不属于项目事实检索范围；项目目标为“{clean_goal}”。"
        else:
            conclusion = f"暂未检索到与“{question[:32]}”直接匹配的条目；当前项目目标为“{clean_goal}”。"
            gaps.append("未找到与该关键词或问题直接匹配的记录。")
    if scope:
        member = scope['member_id']
        goal = f'{member} 的记录'
        conclusion = f'找到 {member} 的 {len(member_facts)} 条声明和 {len(member_sources)} 条公开来源，下方显示至多三条带时间的来源声明。'
        if not member_current:
            conclusion = f'{member} 的声明来源已变化或不可用，需要复核后再判断当前工作。'
        if next_action_status is None:
            next_action = '打开该成员的来源，核对对应版本和实际检查条件。'
            acceptance = '成员归属、来源时间和版本相符；历史完成报告不自动成为当前验收结论。'
        gaps.append('这里查询成员记录；历史报告和原文任务状态不等于当前版本已验收。')
        if any(f.author != member for f in facts):
            gaps.append('同一主题涉及其他成员的声明，相关确认与冲突证据同时保留。')
    chains = []
    contract_risks = []
    if derived_context is not None:
        source_refs = set()
        facts_by_id = {f.id: f for f in facts}
        for f in facts:
            if f.source_ref:
                source_refs.add(f.source_ref)
            for eid in f.evidence_ids:
                if eid in sources:
                    ref = sources[eid].metadata.get("source_ref") if hasattr(sources[eid], "metadata") and isinstance(sources[eid].metadata, dict) else None
                    if ref:
                        source_refs.add(ref)
        raw_chains = derived_context.chain_of_recall(source_refs=source_refs)
        chains.extend(raw_chains)
        # Establish Fact -> Evidence -> AST Node penetration for each finding
        for f_dict in findings:
            fid = f_dict.get("fact_id")
            if fid and fid in facts_by_id:
                fc = fact_chain_of_recall(derived_context, facts_by_id[fid], events)
                if fc.get("ast_chains"):
                    f_dict["chain_of_recall"] = fc["ast_chains"]
                    for c in fc["ast_chains"]:
                        if c not in chains:
                            chains.append(c)
        for ref in source_refs:
            for r in analyze_contract_risk(derived_context, source_ref=ref):
                if r not in contract_risks:
                    contract_risks.append(r)
    return InvestigationAnswer(question, conclusion, goal, active_tasks, evidence_ids, tuple(assumptions), tuple(conflicts), next_action, acceptance, tuple(gaps), tuple(findings), next_action_status, warnings, scope, next_action_basis, chain_of_recall=tuple(chains), contract_risk=tuple(contract_risks), completed_items=completed_items)

