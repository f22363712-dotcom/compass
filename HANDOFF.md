# Project Compass 长期收敛与 Swiss UI 重构交接台账 (HANDOFF.md)

> **当前日期**：2026-11-17（v1.4.0 正式开源门面整备完成：版本号统一、并行环境变量支持、三张实机截图更新、双语 README 与 X 首发手册就绪）  
> **当前分支**：`main`（正式开源主仓库 `f22363712-dotcom/compass`）  
> **提交里程碑链**：`15f204a` (`feat: initial open-source release of Compass v1.0.0`) -> v1.1 完成 -> v1.2 验收交付 -> v1.3 交付 -> v1.4 封板就绪  
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
6. **O1–O3 · 开源合规定型、脱敏导出与去占位符收口**：
   - **O1**：根目录落盘 `LICENSE`（Apache-2.0）、更新 `THIRD_PARTY_NOTICES.md`、完善 `pyproject.toml` 构建与 `web/*` 静态打包、统一 `1.0.0` 版本号与 `server.json` 4 项工具清单；
   - **O2**：脱敏仓内本机路径、清理 `.env.example`、归档竞赛遗留脚本与 `devpost/` 至 `docs/archive/competition_legacy/`、新增 `scripts/export_public_release.py` 导出单提交纯净公共仓；
   - **O3**：修复 `DerivedContext.source_current` 目录指纹与源码节点排序、落地无 `--base-url` 零配置 `WorkspaceMCPAdapter`、清零 UI/导出 16 处占位符并刷新真实截图与双语 `README`。
7. **v1.1 · Solo 纵深闭环、正交思维脑图与自举体验迭代**：
   - **MCP 零配置与并发持久化**：支持 `--zero-config`、`--session-id` 写入客户端（含 Antigravity `mcp_config.json`），文件锁 + 跨进程审阅合并与实时 `state_stat_signature()` 状态热重载；
   - **Solo 首屏与认知双视图**：升级 `#personal-activity` 为可读的会话行动轨迹流（`activity_stream`）、首屏拆分「待拍板思路 & 未验证前提」与「已定案项目基准」、清理 Solo 团队/审核文案与署名弹窗摩擦、新增随手记（`POST /api/notes`）、网页端扫描同步提取文档候选与 AST 索引、提供「清单台账 | 思维脑图」左→右正交脑图视图与 Mermaid `mindmap` 导出；
   - **中文化与全量 CI**：状态徽标全面中文化、统一 `compass-*` 导出命名，并将全部 `tests/*_test.cjs` 纳入 `.github/workflows/ci.yml`。
8. **v1.2 · 交互瘦身、人话动作翻译、防跑偏 MCP 护栏与实时生长迭代（已验收交付）**：
   - **文本脱水与新老分流**（`text_summary.py`）：剥离日期与代码符号生成 15–22 字 `short_title`，个人视图兜底保留项目核心目标，未确认静态文档扫描候选收敛入 `historical_archive` 胶囊；
   - **人话动作翻译与探索折叠**（`activity_stream.py`）：补全 `file_change`/`test_result`/`explore`/`edit` 中文翻译并跨工具折叠连续只读探索步骤；
   - **硬隔离账本、1 步记录与完工门禁**：严格修复 `build_compact_project_context` 未定案提案外泄问题，新增 `record_note` 与 `verify_completion`（含 `completion_gate.py` 确定性阻塞检查 + 环境变量可选干净上下文异体模型挑刺，`--init-rules` 写入目标仓 `AGENTS.md`）；
   - **零配置实时生长与窄分屏**：开启免刷新 3s 局部轮询（保护输入框与抽屉不丢失），适配 `560px–959px` 窄侧栏横向脑图并精简页面文案与「依据 · N」角标。
9. **v1.3 · 四大体验治理、开放模型连接器与 Agent 提示双线迭代（已验收交付）**：
   - **开放模型连接器与思考过程剥离**（`llm_connector.py`）：在零外部依赖下打通云端 OpenAI 兼容 API（含 MiniMax Coding Plan）与本机免 Key Ollama，自动清洗 `<think>...</think>` 与提取 JSON；
   - **四大核心体验治理**（`text_summary.py`、`quick_notes.py`、`dashboard.py`、`investigator.py`、`literal_relevance.py`、`web/`）：落地「核心目标 + 下一步工作共识」双锚点行内改写拍板、静态旧计划复选框与当前活任务硬隔离、一框两用全文+单字检索联动（含 2,000 字证据摘录过滤）、复合问句去成员误判与全新简洁答案卡；
   - **双层 `Agent 提示` 与双端同频**（`agent_hints.py`、`web_server.py`、`plugin_protocol.py`）：本地瞬时规则提示 + 按状态版本异步缓存的模型建议，零阻塞融入看板与 MCP 唤醒简报。
10. **v1.4 · 四方模型同题横评、追问倒金字塔重塑与 v1.x 封板收口（已验收交付）**：
   - **多格式凭据与在线秒切模型**（`llm_connector.py`、`web_server.py`）：兼容 `base_url:` / `api_key:` 多行配置与多文件 `COMPASS_LLM_KEY_FILES`，提供 `POST /api/llm-mode` 与顶栏 `#llm-profile-select` 实现四模式无重启切换；精准为 `MiniMax-M3.1-Flash` 适配极速 `reasoning_effort="low"` 并放宽 `max_tokens` 至 16,384；
   - **追问倒金字塔重塑与复合问题双焦点穿透**（`investigator.py`、`web/app.js`、`web/styles.css`）：复合目标/下一步问题强制同步召回核心目标与已定案 `project.next_step`，回答框固定「语义归纳 → 当前目标 + 高亮下一步 → 精简依据 → 默认折叠 `source_warnings` 与边界」，彻底消灭 16 条旧文件换版横幅顶栏刷屏；
   - **四方量化横评与封板**（`docs/COMPASS_V1_4_MODEL_BENCHMARK_AND_UX_SEAL_2026-11-16.md`）：完成纯本地检索（39.8）、`MiniMax-M2.7`（41.1）、`MiniMax-M3.1-Flash`（41.3，100% 证据合法率，L2 F1 `0.1525`）与 `DeepSeek-Chat`（41.8，101.5s，63.16% 召回率）对比归档并默认启用 `MiniMax-M3.1-Flash` 作为 8787 看板引擎。
11. **v1.4.0 · 正式开源门面与实时闭环升级（2026-11-17 已完成封存待推）**：
   - **版本号统一与文档归档**：将 `pyproject.toml`、`plugin.json`、`server.json`、`__init__.py`、`web/index.html`、`cognitive_export.py` 与对应单测统一至 `1.4.0` / `v1.4`；将 `v1.1`–`v1.3` 过渡计划归档至 `docs/archive/reviews/` 并刷新 `docs/INDEX.md`；
   - **并行多环境变量支持与三张实机截图**：更新 `llm_connector.py` 支持独立并行读取 `MINIMAX_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`；刷新 `board_overview.png`、`pyramid_answer_and_models.png`、`mindmap_split_companion.png` 三张 `v1.4` 实机截图并重写中英双语 `README`；
   - **不重启核心文档热同步与近期已完成检索**：新增白名单 `watched_docs_signature` 轮询触发 `ProjectRescan(extract_docs=True)` 自动增量入账，修复 `HANDOFF.md` 冒号阶段与 `DECISIONS.md` 标题决策提取并新增 `AGENTS.md` 兜底目标提取；为「最近完成的工作」新增时间倒序检索、模型隔离缓存与前端「近期已完成事项」板块；
   - **真实 AI 漫剧工程接入与演示剧本定稿**：在 `ai_drama_studio` 完成 MCP 守则与核心锚点实装验证，并重写 `docs/archive/hackathon_and_brand/X_LAUNCH_AND_DEMO_PLAYBOOK_2026-11-17.md`（AI 漫剧双分屏实战剧本与双语 X 连推）。

---

## 二、 必须遵守的测试与契约红线

```powershell
$env:PYTHONPATH='src'; python -m compileall -q src tests
$env:PYTHONPATH='src'; python -m unittest discover -s tests -q
node --check src/project_compass/web/app.js
Get-ChildItem tests\*_test.cjs | ForEach-Object { node $_.FullName src/project_compass/web/app.js; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
$env:PYTHONPATH='src'; python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker --baseline tests/fixtures/benchmark/baseline_report.json
```

- 前一阶段历史交接内容已留存于 Git 历史 (`8d21003` / `f5b84ec`)，本台账随 M0–M4 执行持续更新。
