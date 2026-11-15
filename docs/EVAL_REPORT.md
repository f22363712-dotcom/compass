# Compass 测评报告 · easy-course-picker

- 运行时间：2026-11-14T17:09:34.002418+00:00
- 安全红线闸门 (Red-Line Gate)：PASS（通过，零越权/零崩溃）
- 智能质量评级 (Quality Grade)：36.20 / 100 · Tier 3 (Baseline)
- 轨道：answerer=product-investigator，extractor=reference-rules-v1，git_sha=4ff9bc7，gold_sha256=cebdd4ec9a79

## L1 结构层：摄入、归属与两层真相 — 通过

| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |
|---|---|---|---|---|---|---|
| `ingest_completeness` | 1.0000 | 1.0 | higher | 是 | 通过 | 438/438 条证据写入存储 |
| `member_attribution` | 1.0000 | 1.0 | higher | 是 | 通过 | 每条证据都能定位到成员 |
| `session_consistency` | 1.0000 | 1.0 | higher | 是 | 通过 | 会话 ID 与成员一致 |
| `evidence_owner` | 1.0000 | 1.0 | higher | 是 | 通过 | 每条证据都出现在其归属成员的视图里 |
| `fact_isolation` | 1.0000 | 1.0 | higher | 是 | 通过 | 每条事实只出现在作者本人的个人视图里 |
| `no_unconfirmed_promotion` | 1.0000 | 1.0 | higher | 是 | 通过 | 未经人工确认的事实没有晋升为团队事实 |
| `team_view_coverage` | 1.0000 | 1.0 | higher | 是 | 通过 | 团队视图覆盖全部候选事实 |
| `conflict_visibility` | 1.0000 | 1.0 | higher | 是 | 通过 | 当前语料含 0 处冲突，属空洞通过（vacuous pass） |

> 本层不依赖任何模型，可直接在 CI 中运行。
> 成员视图只做隔离，不做语义过滤；语义精度由 L2 与 L3 负责。
> vacuous_conflict_check: corpus has 0 conflicting subjects (requires multi-stance corpus for non-vacuous conflict check).

## L2 抽取层：事实准召与抽取契约 — 通过

| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |
|---|---|---|---|---|---|---|
| `extraction_precision` | 0.0493 | 0.0 | higher | 否 | 通过 | 11/223 条候选命中金标准 |
| `extraction_recall` | 0.5789 | 0.0 | higher | 否 | 通过 | 11/19 条金标准被找回 |
| `extraction_f1` | 0.0909 | 0.0 | higher | 否 | 通过 | 抽取层 F1 |
| `contract_accept_rate` | 1.0000 | 1.0 | higher | 是 | 通过 | 所有候选都带有原文精确引用 |
| `evidence_attachment` | 1.0000 | 1.0 | higher | 是 | 通过 | 每条事实都挂到证据 |
| `member_attribution` | 1.0000 | 1.0 | higher | 是 | 通过 | 每条事实都能追到成员 |
| `conflict_preservation` | 1.0000 | 1.0 | higher | 是 | 通过 | 当前语料含 0 处冲突，属空洞通过（vacuous pass） |

> vacuous_conflict_check: extracted facts contain 0 conflicting subjects.

## L3 交接层：检索可达性与答案质量 — 通过

| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |
|---|---|---|---|---|---|---|
| `evidence_coverage` | 0.7143 | 0.0 | higher | 否 | 通过 | 10/14 道题的金标准证据至少被一条事实引用过 |
| `retrieval_hit_rate` | 0.3571 | 0.0 | higher | 否 | 通过 | 5/14 道题在前 5 条证据内命中 |
| `retrieval_mrr` | 0.2560 | 0.0 | higher | 否 | 通过 | 命中证据的平均倒数排名 |
| `answer_accuracy` | 0.2857 | 0.0 | higher | 否 | 通过 | 4/14 道题答对 |
| `answer_accuracy_team` | 0.2500 | 0.0 | higher | 否 | 通过 | 团队视角 2/8 |
| `answer_accuracy_personal` | 0.3333 | 0.0 | higher | 否 | 通过 | 个人视角 2/6 |
| `answers_produced` | 1.0000 | 1.0 | higher | 是 | 通过 | 14/14 道题给出了非空回答 |
| `evidence_validity` | 1.0000 | 1.0 | higher | 是 | 通过 | 答案没有引用不存在的证据 |

## L4 契约层：调用链追踪 — 通过

| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |
|---|---|---|---|---|---|---|
| `symbol_locatable` | 1.0000 | 1.0 | higher | 是 | 通过 | 每个受测符号都能在索引里定位 |
| `caller_trace_recall` | 1.0000 | 1.0 | higher | 是 | 通过 | 15/15 个预期调用方被追到 |
| `risk_reported` | 1.0000 | 1.0 | higher | 是 | 通过 | 每个有调用方的符号都给出契约风险 |

> 本层度量结构图本身，不度量事实层。

## L5 对抗层：准入门抗攻击与越权拦截 — 通过

| 指标 | 数值 | 门槛 | 方向 | 硬性 | 结果 | 说明 |
|---|---|---|---|---|---|---|
| `attack_rejection_rate` | 1.0000 | 1.0 | higher | 是 | 通过 | 8/8 条攻击被准入门按合同条款拒绝 |
| `gate_refused_without_crashing` | 1.0000 | 1.0 | higher | 是 | 通过 | 攻击只会触发合同拒绝，不会让准入门崩溃 |
| `no_promotion_under_attack` | 1.0000 | 1.0 | higher | 是 | 通过 | 攻击下的候选没有任何一条被自动晋升为团队事实 |
| `injection_held_at_proposed` | 1.0000 | 1.0 | higher | 是 | 通过 | 1/1 条注入的真实引文停留在 proposed |

> 本层直接调用产品自己的准入门，不经过任何模型。
> 源材料里嵌入的越权指令如果被引用为事实，必须停留在 proposed。

## 与基线对比

| 层 | 指标 | 基线 | 当前 | 变化 | 走向 |
|---|---|---|---|---|---|
| L1 | `conflict_visibility` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `evidence_owner` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `fact_isolation` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `ingest_completeness` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `member_attribution` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `no_unconfirmed_promotion` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `session_consistency` | 1.0000 | 1.0000 | +0.0000 | flat |
| L1 | `team_view_coverage` | 1.0000 | 1.0000 | +0.0000 | flat |
| L2 | `conflict_preservation` | 1.0000 | 1.0000 | +0.0000 | flat |
| L2 | `contract_accept_rate` | 1.0000 | 1.0000 | +0.0000 | flat |
| L2 | `evidence_attachment` | 1.0000 | 1.0000 | +0.0000 | flat |
| L2 | `extraction_f1` | 0.0909 | 0.0909 | +0.0000 | up |
| L2 | `extraction_precision` | 0.0493 | 0.0493 | +0.0000 | up |
| L2 | `extraction_recall` | 0.5789 | 0.5789 | +0.0000 | up |
| L2 | `member_attribution` | 1.0000 | 1.0000 | +0.0000 | flat |
| L3 | `answer_accuracy` | 0.2857 | 0.2857 | +0.0000 | up |
| L3 | `answer_accuracy_personal` | 0.3333 | 0.3333 | +0.0000 | up |
| L3 | `answer_accuracy_team` | 0.2500 | 0.2500 | +0.0000 | flat |
| L3 | `answers_produced` | 1.0000 | 1.0000 | +0.0000 | flat |
| L3 | `evidence_coverage` | 0.7143 | 0.7143 | -0.0000 | down |
| L3 | `evidence_validity` | 1.0000 | 1.0000 | +0.0000 | flat |
| L3 | `retrieval_hit_rate` | 0.3571 | 0.3571 | +0.0000 | up |
| L3 | `retrieval_mrr` | 0.2560 | 0.2560 | -0.0000 | down |
| L4 | `caller_trace_recall` | 1.0000 | 1.0000 | +0.0000 | flat |
| L4 | `risk_reported` | 1.0000 | 1.0000 | +0.0000 | flat |
| L4 | `symbol_locatable` | 1.0000 | 1.0000 | +0.0000 | flat |
| L5 | `attack_rejection_rate` | 1.0000 | 1.0000 | +0.0000 | flat |
| L5 | `gate_refused_without_crashing` | 1.0000 | 1.0000 | +0.0000 | flat |
| L5 | `injection_held_at_proposed` | 1.0000 | 1.0000 | +0.0000 | flat |
| L5 | `no_promotion_under_attack` | 1.0000 | 1.0000 | +0.0000 | flat |
