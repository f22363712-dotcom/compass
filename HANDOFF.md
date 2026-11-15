# Project Compass 长期收敛与 Swiss UI 重构交接台账 (HANDOFF.md)

> **当前日期**：2026-11-15（M0–M4 健康度整改已全部收敛交付）  
> **当前分支**：`codex/evidence-links`（仅限本地 commit，禁止 push）  
> **提交里程碑链**：`f5b84ec` (基线) -> `1e182cc` (M0) -> `b130965` (M1) -> `89b395b` (M2) -> `4ff9bc7` (M3) -> 当前 M4 收口提交  
> **技术栈契约**：Python >= 3.10 纯标准库（`pyproject.toml` 保持 `dependencies = []`） / 原生 Web（Classic JS + CSS，无打包器） / 本地 JSON 原子存储 + 可选 SQLite FTS5 `:memory:` 检索（带精简环境自动退避）  
> **主控与验收文档**：
> - 活跃文档唯一总入口：[`docs/INDEX.md`](docs/INDEX.md)
> - M0–M4 终局交付报告：[`docs/HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md`](docs/HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md)
> - 体检与执行台账：[`docs/PROJECT_HEALTH_AUDIT_2026-11-14.md`](docs/PROJECT_HEALTH_AUDIT_2026-11-14.md) · [`docs/REMEDIATION_EXECUTION_PLAN_2026-11-14.md`](docs/REMEDIATION_EXECUTION_PLAN_2026-11-14.md)
> - 双 A/B 盲审报告：[`docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md`](docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md) · [`docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md`](docs/UI_AB_TEST_AND_REVIEW_2026-11-14.md)
> - UI 设计系统规范：[`docs/UI_STYLE_GUIDE_MANUAL.md`](docs/UI_STYLE_GUIDE_MANUAL.md)
> - 长跑检查点：`.goal/GOAL.md`（不纳入 Git 追踪）

---

## 一、 阶段完成状态总览（M0 → M4 全部闭环）

1. **M0 · 紧急止血 (`1e182cc`)**：
   - 清除 UI 硬编码 `"100% 绿灯"` 虚假测试宣称（改为关联证据跳转与明确缺口标注）；
   - 修复 `--sample` / `SAMPLE_MODE=true` 泄露宿主机真实已保存项目列表的问题；
   - 统一 `pyproject.toml` / `plugin.json` / `server.json` / `index.html` 版本号至 `1.0.0`，清除 `server.json` 占位符和无实测支撑的 `0.15s` 宣传语；
   - 回滚 `f5b84ec` 中针对金标准措辞的过拟合正则/marker/停用词；修复 `ReferenceExtractor.name`、`default_runner()`、L3 `ProductAnswerer` 全量倾倒与真实检索排序打分；CLI 补齐 `--extractor builtin|reference` 与溯源哈希；标注 0 冲突空洞通过；加最小 CI 与 `[tool.ruff]`。
2. **M1 · 文档治理 (`b130965`)**：
   - 将历史审查记录、品牌与黑客松材料、`superpowers` 历史计划及根目录残留移入 `docs/archive/`（198 篇）；
   - 全程未触碰未跟踪受保护文件 `docs/ZETARIS_DEMO_CHALLENGE_55S.md` 与 `.agents/`；
   - 新建 `docs/INDEX.md`，修复多处文档测试数矛盾与 `events.jsonl` 失实描述，验证零断链。
3. **M2 · 后端收敛与检索 A/B 盲审 (`89b395b`)**：
   - 抽离 `limits.py`、`evidence_filters.py`（统一公开事件筛选、成员归属修复 `dashboard.py:401` 分叉、`Z` 后缀时间解析、文本归一化与平台控制过滤）及 `intent_vocab.py`；
   - 修复多入口并发写固定 `.json.tmp` 踩踏问题；优化 `investigator.py` 去双算及 O(F) 冲突探测；为 `derive_facts` 提供可选坏 span 隔离模式；打通 CLI `--index-code`；
   - 严格保持 L4 `tests/fixtures/benchmark/contract_chains.json` 定义的三核心符号调用链契约；
   - 执行纯净 2-gram IDF vs SQLite FTS5 Trigram BM25 受控 A/B 测试与双盲评委裁决并落地兜底防护（L3 命中率 `0.2857 -> 0.3571`，MRR `0.2321 -> 0.2560`）。
4. **M3 · Swiss Bauhaus / Neo-Brutalism UI 重构与 A/B 盲审 (`4ff9bc7`)**：
   - 彻底清除旧版 `#0d6e52` 墨绿色与模糊软阴影，补齐符合 WCAG AA（对比度 `5.16:1–19.43:1`，`html { font-size: 16px }` 最小 `0.75rem = 12px`）的 `:root` Token；
   - 收敛 `renderStatusBadge` 单一认知状态视觉语法、`apiFetch` 统一超时/错误处理、`Esc` + 断连触发焦点恢复、`#scrim(80) < #handoff-modal(88) < #evidence-drawer(95) < #citation-popover(100)` 浮层序；
   - Team Truth 缺已确认目标时诚实暴露缺口；冲突视图改为 Split A-vs-B 左右双栏对照裁决；打通二级只读项目 `/api/evidence`、`/api/export`、`/api/investigate` 垂直作用域及 `cognitive_export.py` 真实看板 Schema；
   - 通过两个隔离分支并基于 Playwright 多视口实拍截图由 3 位独立盲审评委 3:0 选定 Design Beta 并复核至 **9.30/10**（`9.3 / 9.3 / 9.3`），随后关闭 4 轮 PBR 三视角全部 P0/P1 缺陷。
5. **M4 · 全链路终局门禁与收口**：
   - 完成 `cli --sample --web --port 8790` 真实 HTTP 冒烟实测、刷新 `docs/EVAL_REPORT.md`（`Red-Line Gate: PASS`, `36.20 / 100 · Tier 3 Baseline`）、完成量化红线与全套单测/Node 契约复测并输出 `docs/HEALTH_REMEDIATION_FINAL_REPORT_2026-11-14.md`。
6. **O1–O3 · 开源合规定型、脱敏导出与去占位符收口（当前推进）**：
   - **O1**：根目录落盘 `LICENSE`（Apache-2.0）、更新 `THIRD_PARTY_NOTICES.md`、完善 `pyproject.toml` 构建与 `web/*` 静态打包、统一 `1.0.0` 版本号与 `server.json` 4 项工具清单；
   - **O2**：脱敏仓内本机路径、清理 `.env.example`、归档竞赛遗留脚本与 `devpost/` 至 `docs/archive/competition_legacy/`、新增 `scripts/export_public_release.py` 导出单提交纯净公共仓；
   - **O3**：修复 `DerivedContext.source_current` 目录指纹与源码节点排序、落地无 `--base-url` 零配置 `WorkspaceMCPAdapter`、清零 UI/导出 16 处占位符并刷新真实截图与双语 `README`。

---

## 二、 必须遵守的测试与契约红线

```powershell
$env:PYTHONPATH='src'; python -m compileall -q src tests
$env:PYTHONPATH='src'; python -m unittest discover -s tests -q
node --check src/project_compass/web/app.js
node tests/web_tool_pair_test.cjs src/project_compass/web/app.js
$env:PYTHONPATH='src'; python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker --baseline tests/fixtures/benchmark/baseline_report.json
```

- 前一阶段历史交接内容已留存于 Git 历史 (`8d21003` / `f5b84ec`)，本台账随 M0–M4 执行持续更新。
