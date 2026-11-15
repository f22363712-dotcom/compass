# ProjectCompass 1.0 演进进度追踪 (`PROGRESS.md`)

> 文档入口：[docs/INDEX.md](docs/INDEX.md) · 实时全量回归以 `$env:PYTHONPATH='src'; python -m unittest discover -s tests -q`（当前 `530+` 项）及 `python -m project_compass.eval run` 实跑输出为准；下列条目中的数字仅标注各历史阶段验收时的历史快照。

- [x] **测评体系（Goal: Evaluation Benchmark）**：建成五层测评系统（L1 结构 / L2 抽取 / L3 交接 / L4 契约 / L5 对抗）、去标识化真实语料与独立金标准（19 事实 + 14 题）、模型无关的 harness 接缝与报告/基线对比；新增 `project_compass.code_index`（纯 `ast` 结构图生产者，零新增依赖）。（当时历史阶段快照：`499 tests`）
  - 文档：[`docs/EVAL_FRAMEWORK.md`](docs/EVAL_FRAMEWORK.md) · [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) · [`docs/archive/reviews/COMPASS_ITERATION_PLAN.md`](docs/archive/reviews/COMPASS_ITERATION_PLAN.md) · [`docs/archive/reviews/CODEGRAPH_BORROWING.md`](docs/archive/reviews/CODEGRAPH_BORROWING.md)
  - 真实基线口径（已在 M0 清除 `f5b84ec` 过拟合后重算，详见 [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md)）：红线门禁 PASS，质量评级按最新 `eval run` 输出动态更新。
- [x] **UI 设计预览生成**：使用 `image-generator` 生成设计参考图并存入 `docs/design_previews/`。
- [x] **Module 1**：架构断舍离 —— 清退无不可替代性的历史外部组件（Zetaris / Meterless / JEV）并通过测试与只读审查。
- [x] **Module 2**：会话阶段时间轴、思维演进线（Thinking Line）与悬停原文取证气泡（Hover Citation Popover）。
- [x] **Module 3**：卡片内联秒批（In-Card Triage）、多会话在场胶囊与交接简报（Handoff Brief）。
- [x] **PBR 缺陷治理与视觉优化**：修复状态裂脑（P1-1）、监听幂等与报错暴露（P1-2）、DOM 合规防冒泡（P1-3）、真 HTTP 套接字测试（P1-4）以及引文清洗与聚焦优化。（历史快照：`393 tests`）
- [x] **Goal M1 (Live Ingestion & Watcher)**：实现行截断保护的 `TranscriptWatcher` 与 `/api/refresh` 感知。（历史快照：`395 tests`）
- [x] **Goal M2 (Bidirectional Export)**：实现 GitHub Issue / PR / PRD 多格式导出引擎。（历史快照：`401 tests`）
- [x] **Goal M3 (Packaging & MCP Setup)**：完善标准 `pyproject.toml` 打包规范与 `project_compass.mcp_setup` 工具。（历史快照：`407 tests`）
- [x] **健康度整改 M0（紧急止血）**：清除 Web 虚假 `"100% 绿灯"`、封堵 `--sample` 宿主机项目列表泄露、统一 `v1.0.0` 清单与诚实文案、清理 `f5b84ec` 过拟合并打通 `--extractor builtin` 与 Git/金标准哈希溯源、补齐 GitHub Actions CI。
- [x] **健康度整改 M1–M4**：完成 198 篇文档归档与 [INDEX.md](docs/INDEX.md) 建库、后端收敛（`limits.py` / `evidence_filters.py` / `intent_vocab.py`）与检索可控 A/B 盲审（[`docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md`](docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md)）、Swiss Neo-Brutalism Web 看板双分支 A/B 盲审重构（[`docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md`](docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md)，终版 9.30/10 全票通过），以及全链路 PBR 闭环与终局量化交付（[`docs/HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md`](docs/HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md)）。

---
### 历史里程碑要点总览
1. **架构收敛**：纯 Python 3.10+ 标准库与 Vanilla Web（`dependencies = []`），无外部数据库或框架依赖。
2. **认知交互链**：01–04 阶段时间轴、思维演进线、AST 跨模块拓扑联动与可溯源引文取证浮窗。
3. **多角色协作闭环**：个人工作台（Proposed）与团队共识（Team Truth）严格隔离，所有确认与裁决均由人类负责人显式操作，Append-only 不可篡改。
