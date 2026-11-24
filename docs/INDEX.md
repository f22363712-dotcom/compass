# Project Compass 文档总索引 (`docs/INDEX.md`)

> 维护口径：本文档为 Project Compass 仓库活跃文档与历史归档的唯一总入口。所有静态状态描述以源码、`pyproject.toml` 与实跑命令输出为准；测评与测试结果请以最新一次本地实跑为准，不再手动硬编码相互冲突的测试条数。

---

## 一、核心产品与工程规范（Active Specs）

| 文档 | 用途说明 |
| :--- | :--- |
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | 竞赛与产品核心定义（两层真相、证据不可篡改、冲突可见、显式确认） |
| [PRODUCT_GOAL.md](PRODUCT_GOAL.md) | 核心目标与成功边界 |
| [ROADMAP.md](ROADMAP.md) | 增量黄金路径路线图与阶段 Gate |
| [PRODUCT_FORM_AND_TECH_STACK.md](PRODUCT_FORM_AND_TECH_STACK.md) | 四大产品形态、纯 Python 3.10+ 标准库 + Vanilla Web 架构、本地 `state.json` 原子持久化机制 |
| [DERIVED_CONTEXT_PROJECTION_SPEC.md](DERIVED_CONTEXT_PROJECTION_SPEC.md) | 衍生上下文投影规范 |
| [AGENT_HTTP_PROTOCOL.md](AGENT_HTTP_PROTOCOL.md) | 本地 HTTP Agent 协议约定 |
| [MCP_REGISTRY_GUIDE_AND_AUTHENTIC_STORY.md](MCP_REGISTRY_GUIDE_AND_AUTHENTIC_STORY.md) | MCP Registry 注册指南与标准客户端接入说明 |
| [ENVIRONMENT.md](ENVIRONMENT.md) | 本地环境变量与安全配置约定 |
| [QUALITY_GATES.md](QUALITY_GATES.md) | 五层验收阶段质量门与回归检查说明 |
| [UI_STYLE_GUIDE_MANUAL.md](UI_STYLE_GUIDE_MANUAL.md) | Web 看板设计系统、Token 与认知状态语法手册（Swiss Bauhaus & Neo-Brutalism v3.0） |

---

## 二、测评体系与健康度治理（Evaluation & Health Remediation）

| 文档 | 用途说明 |
| :--- | :--- |
| [EVAL_FRAMEWORK.md](EVAL_FRAMEWORK.md) | 五层测评架构（L1 结构 / L2 抽取 / L3 交接 / L4 契约 / L5 对抗） |
| [EVAL_DUAL_GATE_EXPLAINED.md](EVAL_DUAL_GATE_EXPLAINED.md) | 安全红线闸门（Red-Line Gate）与智能质量分级双轨机制说明 |
| [EVAL_FRAMEWORK_CRITIQUE.md](EVAL_FRAMEWORK_CRITIQUE.md) | 测评框架自省与反作弊/去过拟合评估 |
| [HOW_EVAL_DRIVES_ITERATION.md](HOW_EVAL_DRIVES_ITERATION.md) | 测评驱动架构迭代闭环方法论 |
| [EVAL_REPORT.md](EVAL_REPORT.md) | 最新一次真实实跑生成的基准测评报告（由 `python -m project_compass.eval run` 生成） |
| [PROJECT_HEALTH_AUDIT_2026-11-14.md](PROJECT_HEALTH_AUDIT_2026-11-14.md) | 长期维护健康度全面审查报告（AI Coding 规范 / 技术路线 / 测评 / 真实浏览器 UI） |
| [REMEDIATION_EXECUTION_PLAN_2026-11-14.md](REMEDIATION_EXECUTION_PLAN_2026-11-14.md) | M0–M4 逐条整改执行方案与两场 A/B 盲审实验协议 |
| [RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md](RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md) | M2 检索方案可控 A/B 实测与双盲 Critic 评审报告（Alpha vs Beta） |
| [UI_AB_TEST_AND_REVIEW_2026-11-14.md](UI_AB_TEST_AND_REVIEW_2026-11-14.md) | M3 Swiss Neo-Brutalism UI 双分支 A/B 实测与双盲 Critic 复核报告（Design Beta 落地，终版 9.3/10） |
| [HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md](HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md) | M0–M4 长期健康度审计整改、双 A/B 盲审与终局门禁验收总结报告 |
| [OPEN_SOURCE_AND_DOGFOODING_PLAN_2026-11-15.md](OPEN_SOURCE_AND_DOGFOODING_PLAN_2026-11-15.md) | 开源发布准备计划（O1–O4）、Project Compass 真实自举案例实跑与 UI 16 处占位符整改台账 |
| [COMPASS_V1_1_DELIVERY_REPORT_2026-11-15.md](COMPASS_V1_1_DELIVERY_REPORT_2026-11-15.md) | Compass v1.1 交付与实测验收总结报告（含 `8787` 自举、MCP 热同步、`548` 单测、五层评测与真实浏览器走查） |
| [COMPASS_V1_2_DELIVERY_REPORT_2026-11-16.md](COMPASS_V1_2_DELIVERY_REPORT_2026-11-16.md) | Compass v1.2 交付与实测验收报告（`553` 单测、18 个 `.cjs` 双时区、`eval` L1–L5、stdio 6 工具与三视口浏览器验证） |
| [COMPASS_V1_3_DELIVERY_AND_BENCHMARK_2026-11-16.md](COMPASS_V1_3_DELIVERY_AND_BENCHMARK_2026-11-16.md) | Compass v1.3 交付与同题三方对比测评报告（v1.2 基线 vs v1.3 纯本地检索 vs MiniMax-M2.7 语义增强） |
| [COMPASS_V1_4_MODEL_BENCHMARK_AND_UX_SEAL_2026-11-16.md](COMPASS_V1_4_MODEL_BENCHMARK_AND_UX_SEAL_2026-11-16.md) | Compass v1.4 四方模型横评、追问倒金字塔重塑、在线切模型与 v1.x 底座封板报告 |
| [COMPASS_V1_5_MULTI_AGENT_AND_SIDECAR_BENCHMARK_2026-11-19.md](COMPASS_V1_5_MULTI_AGENT_AND_SIDECAR_BENCHMARK_2026-11-19.md) | Compass v1.5.0 Antigravity 原生 Sidecar 副栏、Codex/Hermes 五档跨宿主自适应架构、轻量化与实测对照报告 |
| [COMPASS_REVIEW_2026-11-20.md](COMPASS_REVIEW_2026-11-20.md) | Compass v1.5 能力只审不改全面体检报告（识别率、内容丰富度、顾问能力与 10 项指标） |
| [COMPASS_V1_6_ARCHITECTURE_AND_DIFFERENTIATION_2026-11-20.md](COMPASS_V1_6_ARCHITECTURE_AND_DIFFERENTIATION_2026-11-20.md) | Compass v1.6 竞品深拆（6 大成熟项目）、零依赖精准吸收清单与差异化技术架构方案 |
| [COMPASS_V1_6_CAPABILITY_BENCHMARK_2026-11-20.md](COMPASS_V1_6_CAPABILITY_BENCHMARK_2026-11-20.md) | Compass v1.6 三项核心能力定量对照、独立 L1–L5 对照、真实会话留出集与轮询性能实测报告 |
| [COMPASS_V1_6_CLAUDE_REVIEW_2026-11-20.md](COMPASS_V1_6_CLAUDE_REVIEW_2026-11-20.md) | Compass v1.6 独立 PBR 八维只读审查报告及 P0–P2 闭环整改验证结论 |
| [STAGE_A_EXECUTION_AND_LAUNCH_PLAYBOOK_2026-11-21.md](STAGE_A_EXECUTION_AND_LAUNCH_PLAYBOOK_2026-11-21.md) | Stage A 体验去黑话整改、GitHub 组织迁移与小红书 / B 站首发推广实操手册 |

---

## 三、历史归档目录（Archived Legacy & Point-in-Time Snapshots）

历史开发过程产物已按职责收敛归档，保留完整 Git 重命名历史以备溯源，不再混杂于 `docs/` 主目录：

- `docs/archive/reviews/`：历史时点 PBR 代码审查、冒烟核对、设计说明与 v1.1–v1.3 过渡迭代方案（含 [COMPASS_ITERATION_PLAN.md](archive/reviews/COMPASS_ITERATION_PLAN.md)、[CODEGRAPH_BORROWING.md](archive/reviews/CODEGRAPH_BORROWING.md)、v1.1/v1.2/v1.3 内部执行计划等）
- `docs/archive/hackathon_and_brand/`：历史品牌命名、红蓝对抗、视频脚本与宣传文稿（33 篇）
- `docs/archive/superpowers/`：2026-10 开发期的设计草案与分段实现计划（49 篇）
- `docs/archive/root_legacy/`：曾位于仓库根目录的历史简报与清单（[HACKATHON_BRIEF.md](archive/root_legacy/HACKATHON_BRIEF.md)、[SUBMISSION_CHECKLIST.md](archive/root_legacy/SUBMISSION_CHECKLIST.md)、[PLAN.md](archive/root_legacy/PLAN.md)）

---

## 四、常用本地验证命令

```powershell
# 全量单元测试（当前基准 530+ tests，以实跑输出为准）
$env:PYTHONPATH = 'src'; python -m unittest discover -s tests -q

# 五层测评基准运行与基线对比
$env:PYTHONPATH = 'src'; python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker --extractor reference --baseline tests/fixtures/benchmark/baseline_report.json

# 前端语法与 Node VM 契约测试
node --check src/project_compass/web/app.js
node tests/web_tool_pair_test.cjs src/project_compass/web/app.js
```
