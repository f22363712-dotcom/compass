# M2 检索方案可控 A/B 实验与双盲 Critic 评审报告 (2026-11-14)

> **状态**：已完成受控 A/B 实测、双路匿名 Critic 评审与可靠性加固落地  
> **受测模块**：`src/project_compass/literal_relevance.py`（纯 Python 标准库零新增三方依赖约束）

---

## 一、 实验背景与对照组设计

根据 [REMEDIATION_EXECUTION_PLAN_2026-11-14.md](REMEDIATION_EXECUTION_PLAN_2026-11-14.md) M2 阶段要求，在保持 `rank_literal(question, pool, fallback, *, text)` 契约及 `tests/test_question_relevance.py` 同分时间顺序保持（recency tie-break）行为不变的前提下，设计两个零三方依赖候选方案进行受控对照实验：

1. **Candidate Alpha（对照组：Clean N-Gram IDF）**：原主干 `literal_relevance.py` 实现，基于 `unicodedata.normalize("NFKC")`、中文 4/3/2-gram 切分、ASCII 标识符边界正则，以及 `(len(term) - 1) / df` 布尔存在性打分。
2. **Candidate Beta（实验组：Hybrid SQLite FTS5 Trigram BM25 + 2-Gram Short-CJK Fallback）**：利用 Python 3.10+ 标准库自带 SQLite `:memory:` FTS5 `tokenize='trigram'` 计算 `len(term) >= 3` 词条的 `bm25(docs)`（兼具词频饱和与文档长度归一化），叠加平滑对数 IDF `math.log(1.0 + (N + 0.5) / (df + 0.5))`；对 ASCII 词在召回后二次校验边界正则（防止 `ann` 误召回仅含 `anna` 的文档）；对 `< 3` 字符短中文双字词与短 ASCII 词走纯 Python 2-gram/边界正则平滑 IDF 分支；按 `-round(score, 9)` 排序。

---

## 二、 实测基准定量对比

测试脚本位于会话 `scratch/m2_retrieval_ab_bench.py`，全程锁定 `easy-course-picker`（14 题）与 `tests/test_question_relevance.py`（18 条单测），严禁任何面向特定题目的硬编码停用词作弊：

| 评测维度 | Candidate Alpha (N-Gram IDF) | Candidate Beta (FTS5 Trigram BM25 + Fallback) | 差异 |
|---|---|---|---|
| `easy-course-picker` L3 `evidence_coverage` | `0.7143` (10/14) | `0.7143` (10/14) | `0.0000` |
| `easy-course-picker` L3 `retrieval_hit_rate` | `0.2857` (4/14) | **`0.3571` (5/14)** | **`+0.0714` (+25.0% 相对)** |
| `easy-course-picker` L3 `retrieval_mrr` | `0.2321` | **`0.2560`** | **`+0.0239` (+10.3% 相对)** |
| `easy-course-picker` L3 `answer_accuracy` | `0.2857` (4/14, team `0.25`, personal `0.3333`) | `0.2857` (4/14, team `0.25`, personal `0.3333`) | `0.0000` |
| `easy-course-picker` L3 `evidence_validity` | `1.0000` | `1.0000` | `0.0000` |
| 综合质量分 (Quality Grade, `--extractor reference`) | `34.4 / 100` | **`36.2 / 100`** | **`+1.8`** |
| `tests/test_question_relevance.py` | `18/18 PASS` | `18/18 PASS` | 零回归 |
| 12 题独立双语合成微基准 (`Hit@1` / `Hit@3` / `MRR`) | `1.0000 / 1.0000 / 1.0000` (4.29 ms) | `1.0000 / 1.0000 / 1.0000` (13.91 ms) | 同满分 |
| 120 次高频调用延迟 (`total` / `p50` / `p95`) | **`27.80 ms` / `0.1981 ms` / `0.4523 ms`** | `158.64 ms` / `1.2144 ms` / `2.2490 ms` | Beta 慢约 6x (绝对值 ~1.2ms) |

**关键现象解释**：在真实基准问题 `ecp-q-team-001` 中，Candidate Alpha 因冗长上下文稀释未能在前 5 条内命中黄金证据 `conv-b3d68da84583`（`rr=0.00`）；Candidate Beta 借助文档长度归一化与平滑 IDF 将该证据推升至第 3 位（`hit_at=5`, `rr=0.33`），且其余 13 题零回归。

---

## 三、 双路匿名 Blind Critic 评审结论

将两套代码与定量表完全匿名化（`Candidate X = Beta`，`Candidate Y = Alpha`）后，通过 `run_workflow` 启动两个独立 `research` Critic 并行盲审：

| Critic 角色 | Candidate X (Beta) 评分 | Candidate Y (Alpha) 评分 | 匿名裁决 | 核心理由与风险提示 |
|---|---|---|---|---|
| **Retrieval & Epistemic Accuracy Critic** | **7.8 / 10** | 6.0 / 10 | **X (Beta)** | L3 `retrieval_hit_rate` (`0.2857 -> 0.3571`) 与 `MRR` (`0.2321 -> 0.2560`) 实打实净提升且零回归；有效抑制冗长噪声与 `1/df` 极端加权；提醒 `answer_accuracy` 尚未传导提升。 |
| **Systems Reliability & Latency Critic** | 6.3 / 10 | **7.5 / 10** | **Y (Alpha)** | 指出初版 X 代码的 3 处可靠性短板：(1) `CREATE VIRTUAL TABLE ... fts5(tokenize='trigram')` 未捕获 `OperationalError`（精简版 `libsqlite3` 会直接崩溃）；(2) `MATCH` 异常捕获后直接返回 `[]` 造成静默丢词；(3) `\x00` NUL 字节会触发 `sqlite3` `ValueError`；且每次查询重建索引带来 ~6x 延迟开销。 |
| **综合均值** | **7.05 / 10** | 6.75 / 10 | **采纳 Beta（并立即修复可靠性缺口）** | 以准确率胜出组为基底，立即吸收 Critic 2 的全部工程兜底建议。 |

> 附注：我们在落盘前亦补充对照了纯 Python `Okapi BM25`（字符长度归一化，`k1=1.2, b=0.75`），其在 L3 `easy-course-picker` 上虽达到 `retrieval_hit_rate = 0.3571`，但 `retrieval_mrr` 降至 `0.2202`（低于 Beta 的 `0.2560` 与 Alpha 的 `0.2321`），故坚持采用 FTS5 trigram BM25 方案。

---

## 四、 落地加固与认知诚实声明

最终合入 [literal_relevance.py](../src/project_compass/literal_relevance.py) 的实现完整关闭了 Blind Critic 2 指出的 3 个隐患：

1. `_open_trigram_index()` 将 `sqlite3.connect` 与 `CREATE VIRTUAL TABLE ... fts5(tokenize='trigram')` 包裹在 `try / except (sqlite3.Error, ValueError)` 内；若宿主环境不支持 FTS5 或 trigram，返回 `None` 并无缝退回纯 Python 扫描分支。
2. `_score_fts5_term()` 在 `MATCH` 异常时返回 `None`（而非空列表 `[]`），外层 `rank_literal()` 检测到 `None` 后自动走纯 Python 平滑 IDF 边界分支，**零静默丢词**。
3. 写入和查询 SQLite 前统一清理 `\x00` 字节，彻底消除 `sqlite3` NUL `ValueError` 崩溃路径；同时在 `tests/test_backend_convergence.py` 中覆盖 FTS5 降级与 `\x00` 边界用例。

**认知诚实声明**：本次改进将 `easy-course-picker` L3 检索命中率从 `0.2857` 提升至 `0.3571`、MRR 从 `0.2321` 提升至 `0.2560`，但终端问答准确率 `answer_accuracy` 仍保持 `0.2857`（仍受限于字面检索缺乏跨表述语义泛化），不将检索排名改善夸大为问答全量解决。
