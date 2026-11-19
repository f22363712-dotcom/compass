# Project Compass v1.2 交互瘦身、人话动作翻译、防跑偏 MCP 护栏与实时生长交付报告（2026-11-16）

> 本文档依据本仓库源码、自动化测试输出、五层基准测评及三视口真实浏览器走查编写；全仓导出泄密检查已确认 `leaks_found == 0`。

---

## 一、核心升级概览

### 1. 注意力协同模型与新老用户分流
- **日常对话内零切屏预警 + 网页实时窄侧栏生长**：依据 `/grill-me` 决策共识与同类项目调研，MCP 不在主链路阻塞调用冗余模型；90% 编码过程中通过工具返回值中的 2 行中文 `nudge_lines` 在编辑器主对话内提示基准偏离与遗漏坑位，10% 全局复盘或分屏协同通过网页 3 秒无感热生长画布与 `560px–959px` 窄分屏紧凑模式零摩擦呈现。
- **0→1 新项目与老仓库接管分流**：
  - 全新项目开局呈现干净的「核心目标待定锚」，通过一步式 `record_note` 与 `--init-rules` 写入目标仓的 `AGENTS.md` 协作守则，随对话自动生长出枝干；
  - 接管既有仓库时，旧文档扫描提取的未定案历史条目自动脱水剥离日期与代码符号，默认折叠收进脑图下方的 `<details class="historical-archive-capsule">`（「历史文档参考（N 条）」）中；一旦在页面点击「✓ 定案」，立即自动晋升进入主脑图绿色基准分支。

### 2. 脑图文案脱水与真正的人话动作翻译（Wake / RunGraph）
- 新增 [text_summary.py](../src/project_compass/text_summary.py)（纯标准库，零核心引擎依赖）：
  - `summarize_node_title` 自动剥离 ISO 日期前缀、Markdown 标记、反引号及路径前缀，提炼 15–22 字短标题（目标根锚点放宽至 28 字），同时 100% 保持账本原始 `value` 与精确引文 `quote` 不变供侧边抽屉溯源核对。
  - 更新 [dashboard.py](../src/project_compass/dashboard.py)（个人视图支持团队核心目标兜底继承，避免切换视角误报空态）与 [cognitive_export.py](../src/project_compass/cognitive_export.py)（Mermaid 脑图导出同步优先输出短标题与历史参考区）。
- 升级 [activity_stream.py](../src/project_compass/activity_stream.py)：
  - 补全 `file_change`、`test_result`、`explore`、`edit` 与 `mcp_record_note` 的中文人话动作翻译；
  - 支持跨越不同只读探索工具（如 `read_file` → `grep_search` → `project_context`）的连续健康探索自动折叠为一行「探索上下文 · 连续探索代码与上下文（共 N 步）」，失败或非零退出码动作绝不折叠；自动去重随手记伴生 `fact_proposal` 冗余动态。

### 3. 硬隔离账本 + 一步式 `record_note` + 防假完工 `verify_completion` + `--init-rules`
- 修复 [plugin_protocol.py](../src/project_compass/plugin_protocol.py) `build_compact_project_context` 历史越权隐患：**彻底移除无已定案事实时混入 `team_facts[:5]` 的退避逻辑**，确保 `accepted_facts` 只含明确已定案条目；同时压缩重复 `inline` 拷贝以节省上下文开销，补充 `core_goal_status`、`pending_proposals`、`open_pitfalls` 及 2 行防跑偏 `nudge_lines`。
- 扩展 [quick_notes.py](../src/project_compass/quick_notes.py) 支持可选 `title` 与 `source_channel="mcp_record_note"`，新增 [completion_gate.py](../src/project_compass/completion_gate.py) 实现 `evaluate_completion_gate`：
  - 确定性门禁拦截无改动文件与实测依据的“空口完工”及最近一次非零退出码测试失败，并提示遗留坑位与未拍板风险；
  - 预留可选环境变量旁路异体模型审查（`COMPASS_CRITIC_API_KEY`、`COMPASS_CRITIC_BASE_URL`、`COMPASS_CRITIC_MODEL`），未配置或 `SAMPLE_MODE=true` 时零网络零耗时跳过，请求超时（`<= 6.0s`）或异常自动 fail-warn 降级放行，绝不阻塞主工作流。
- 在 [mcp_server.py](../src/project_compass/mcp_server.py)、[local_plugin.py](../src/project_compass/local_plugin.py)、[agent_inbox.py](../src/project_compass/agent_inbox.py)、[agent_http.py](../src/project_compass/agent_http.py) 与 [server.json](../server.json) 中统一暴露 **6 项 MCP 工具**（`project_context`、`append_evidence`、`query_state`、`propose_fact`、`record_note`、`verify_completion`），并在 [mcp_setup.py](../src/project_compass/mcp_setup.py) 新增幂等规则安装选项 `--init-rules`。

### 4. UI 极简瘦身、卡片依据角标、3s 实时生长与窄分屏模式
- 更新 [index.html](../src/project_compass/web/index.html)、[app.js](../src/project_compass/web/app.js) 与 [styles.css](../src/project_compass/web/styles.css)：
  - 清理冗长 `//` 副标与自宣文案，`Ask Compass` 按钮替换为「查证据」，`#hero-copy` 改为实时反映项目当前已定案/待拍板/待办计数或 0→1 就绪引导；
  - 卡片表层隐藏杂乱 `[scan-file-xxxx]` 编号，改为干净的「依据 · N」角标（悬停与抽屉内保留完整原编号与原文快照）；
  - 零配置模式开启 3 秒静默 `GET /api/state` 局部刷新（绝不清空正在输入的 `#quick-note-input` 也不关闭已打开的 `#evidence-drawer`，新增节点带 `.is-fresh-node` 提示）；
  - 新增 `560px–959px` 窄分屏伴随横向脑图排版并严守 `test_web_assets.py` 全部 Swiss Bauhaus 静态样式门禁。

---

## 二、全量实测验收结果

| 验证项目 | 运行方式 / 范围 | 实测结论 |
| :--- | :--- | :--- |
| 前端语法与契约全集（本地 & UTC） | `node --check src/project_compass/web/app.js` + 全套 18 个 `tests/*_test.cjs`（含新增 [web_v12_live_growth_and_copy_test.cjs](../tests/web_v12_live_growth_and_copy_test.cjs)）在本地与 `TZ=UTC` 双轨执行 | **18/18 双时区全部通过**（exit code 0） |
| 全量 Python 编译与单元测试 | `$env:PYTHONPATH='src'; python -m compileall -q src tests; python -m unittest discover -s tests -q`（含新增 [test_v12_mcp_guardrails_and_ux.py](../tests/test_v12_mcp_guardrails_and_ux.py) 及真实仓导出泄密扫描） | **Ran 553 tests in 90.132s · OK**（0 failures, 0 errors） |
| 五层测评基准 | `python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker --baseline tests/fixtures/benchmark/baseline_report.json` | **`red_line_gate: PASS`，`overall: PASS`**（L1–L5 全通，`L4 caller_trace_recall = 1.0000` [15/15]，`L5 attack_rejection_rate = 1.0000` [8/8]） |
| 本机 `:8787` 看板 + 6 工具 stdio MCP 联调 | 重启守护进程加载最新 v1.2 代码后子进程运行 `project_compass.mcp_server` 探针调用 `project_context`、`record_note`、`verify_completion` | **写入后无需重启立即热同步至 `/api/state`**；脑图根节点与活跃分支呈简短中文，20 条旧文档历史收敛进折叠胶囊 |
| 真实浏览器三视口 UI 走查 | `browser` 子智能体访问 `http://127.0.0.1:8787/`（宿主证据确认 `visited_origins: http://127.0.0.1:8787`，`blocked_origins: none`） | **0 控制台报错**；桌面 `1366×768`（`scrollWidth 1264.7 <= 1366`）、窄分屏 `660×860`（`644.7 <= 660`，左→右横向脑图置顶）、手机 `390×844`（`374.7 <= 390`）均零横向溢出，`historical-archive-capsule` 默认折叠并支持展开溯源 |
