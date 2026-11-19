"""Bounded literal matching with SQLite FTS5 trigram BM25 and Python fallback."""

from __future__ import annotations

import math
import re
import sqlite3
import unicodedata


def literal_terms(question):
    """Extract normalized ASCII identifier and CJK n-gram terms from a question."""
    query = unicodedata.normalize("NFKC", question[:512]).casefold()
    query = re.sub(
        r"为什么|为何|如何|怎么|什么|项目|团队|当前|状态|下一步|接下来|"
        r"方向|决策|变化|改变|未完成|未验证|阻塞|前提|证据|对应|相关|"
        r"请问|问一下|关于|查看|查询|看看|成员|同事|选择|方案|"
        r"做了|做过|负责|处于|应该|目前|最近|今天|进展|任务|记录",
        " ",
        query,
    )
    stop = {
        "why",
        "what",
        "which",
        "how",
        "did",
        "do",
        "does",
        "is",
        "are",
        "was",
        "were",
        "the",
        "and",
        "to",
        "of",
        "for",
        "with",
        "we",
        "it",
        "its",
        "in",
        "this",
        "that",
        "should",
        "next",
        "current",
        "now",
        "state",
        "status",
        "project",
        "team",
        "choose",
        "chosen",
        "change",
        "changed",
        "direction",
        "decision",
        "decisions",
        "task",
        "tasks",
        "work",
        "records",
        "record",
        "evidence",
        "progress",
        "recent",
        "recently",
        "latest",
        "today",
        "about",
        "happen",
    }
    terms = [
        ("ascii", term.strip("._+-"))
        for term in re.findall(r"[a-z0-9][a-z0-9_.+-]*", query)
        if len(term.strip("._+-")) >= 2 and term.strip("._+-") not in stop
    ]
    for chunk in re.findall(r"[\u3400-\u9fff]+", query):
        terms.extend(
            ("han", chunk[index : index + size])
            for size in (4, 3, 2)
            for index in range(len(chunk) - size + 1)
        )
    _CJK_PARTICLES = frozenset(
        "的地得了着过是为有在和与及或把被让给对从向到于已曾正将要会能可吗呢吧啊呀么谁哪这个些条项处上下中里外"
    )
    if not terms:
        stripped_q = str(question or "")
        raw_norm = unicodedata.normalize("NFKC", stripped_q[:32]).casefold().strip()
        if stripped_q == stripped_q.strip() and 1 <= len(raw_norm) <= 4:
            if len(raw_norm) == 1 and "\u3400" <= raw_norm <= "\u9fff" and raw_norm not in _CJK_PARTICLES:
                terms.append(("han", raw_norm))
            elif re.fullmatch(r"[a-z0-9]{2,4}", raw_norm) and raw_norm not in {"why", "how", "who", "what", "the", "and", "for"}:
                terms.append(("ascii", raw_norm))
    return list(dict.fromkeys(terms))[:256]


def _open_trigram_index(texts: list[str]) -> sqlite3.Connection | None:
    """Create an ephemeral in-memory FTS5 trigram index, returning None if unsupported."""
    try:
        conn = sqlite3.connect(":memory:")
    except sqlite3.Error:
        return None
    try:
        conn.execute("CREATE VIRTUAL TABLE docs USING fts5(body, tokenize='trigram')")
        conn.executemany(
            "INSERT INTO docs(rowid, body) VALUES (?, ?)",
            [(idx + 1, body.replace("\x00", " ")) for idx, body in enumerate(texts)],
        )
        return conn
    except (sqlite3.Error, ValueError):
        conn.close()
        return None


def _score_fts5_term(
    conn: sqlite3.Connection,
    term: str,
    texts: list[str],
    pattern: re.Pattern[str] | None,
) -> list[tuple[int, float]] | None:
    """Query FTS5 trigram BM25 scores for a >=3-char term; return None to trigger Python fallback."""
    clean_term = term.replace("\x00", "")
    if len(clean_term) < 3:
        return None
    escaped = '"' + clean_term.replace('"', '""') + '"'
    try:
        raw_hits = conn.execute(
            "SELECT rowid, bm25(docs) FROM docs WHERE docs MATCH ?",
            (escaped,),
        ).fetchall()
    except (sqlite3.Error, ValueError):
        return None
    filtered: list[tuple[int, float]] = []
    for rowid, raw_bm25 in raw_hits:
        idx = int(rowid) - 1
        if 0 <= idx < len(texts):
            exact_tf = 0
            if pattern is not None:
                exact_tf = len(pattern.findall(texts[idx]))
                if exact_tf == 0:
                    continue
            score = -float(raw_bm25)
            score = score if score > 0.0 else 1e-18
            if pattern is not None:
                substring_tf = texts[idx].replace("\x00", "").count(clean_term)
                if substring_tf > exact_tf:
                    score *= exact_tf / substring_tf
            filtered.append((idx, score))
    return filtered


def rank_literal(question, pool, fallback, *, text):
    """Rank pool items by FTS5 trigram BM25 (len>=3) with smooth-IDF boundary fallback."""
    terms = literal_terms(question)
    if not terms or not pool:
        return fallback
    texts = [unicodedata.normalize("NFKC", text(record)).casefold() for record in pool]
    n_docs = len(texts)
    scores = [0.0] * n_docs
    conn = _open_trigram_index(texts) if any(len(term) >= 3 for _, term in terms) else None
    try:
        for kind, term in terms:
            pattern = (
                re.compile(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])")
                if kind == "ascii"
                else None
            )
            term_len_weight = max(1, len(term) - 1)
            fts_hits = (
                _score_fts5_term(conn, term, texts, pattern)
                if (conn is not None and len(term) >= 3)
                else None
            )
            if fts_hits is not None:
                freq = len(fts_hits)
                if freq:
                    idf = math.log(1.0 + (n_docs + 0.5) / (freq + 0.5))
                    max_bm25 = max(val for _, val in fts_hits) or 1.0
                    for idx, bm25_pos in fts_hits:
                        scores[idx] += term_len_weight * idf * (0.5 + 0.5 * (bm25_pos / max_bm25))
            else:
                matches = [
                    bool(pattern.search(body)) if pattern else (term in body)
                    for body in texts
                ]
                freq = sum(matches)
                if freq:
                    idf = math.log(1.0 + (n_docs + 0.5) / (freq + 0.5))
                    weight = term_len_weight * idf
                    for idx, matched in enumerate(matches):
                        if matched:
                            scores[idx] += weight
    finally:
        if conn is not None:
            conn.close()
    ranked = [
        pool[index]
        for index in sorted(range(n_docs), key=lambda index: -round(scores[index], 9))
        if scores[index] > 0
    ]
    return ranked or fallback
