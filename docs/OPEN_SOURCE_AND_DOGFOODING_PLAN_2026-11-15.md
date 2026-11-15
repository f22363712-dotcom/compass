# Project Compass 开源准备计划、真实自举（Dogfooding）实跑报告与 UI 占位符整改台账（2026-11-15）

> 本文档面向 Project Compass 从竞赛/个人工程阶段迈向**公开发布开源（Open Source Release）**而编写，包含三部分核心内容：
> 1. **开源准备四阶段计划（O1–O4）**：许可证、隐私路径与历史清理、零配置体验与宣传一致性、社区治理与跨平台 CI；
> 2. **真实自举案例实跑报告（Dogfooding Case Study）**：使用本项目自身的开发文档、真实 Antigravity 会话轨迹与架构分歧演化，完整跑通 Project Compass 的取证、对峙裁决、问答与交接闭环，并记录实测暴露的真实产品缺陷；
> 3. **UI 与导出模板 4 类 16 处占位符整改台账**：作为下一阶段“去占位符 & 开源收口”的执行清单（本次暂不重构 UI 代码，待负责人拍板后统一推进）。

---

## 第一章：开源准备计划（O1–O4）

当前仓库已具备“纯 Python 标准库、零第三方运行时依赖（`pyproject.toml` 中 `dependencies = []`）”的良好内核，但在公开托管至 GitHub / PyPI / MCP Registry 前，存在**合规阻断、隐私路径泄露、文档与 CLI 行为不一致**三类硬缺口。建议按 `O1 → O4` 分四步推进：

### O1 · 开源合规与包构建基础（上线前硬阻断）

- [x] **O1.1 选定并落盘根目录 `LICENSE`**
  - **已执行（负责人拍板 Apache-2.0）**：根目录已写入标准 [`LICENSE`](../LICENSE)（Apache License 2.0），与 [`server.json`](../server.json#L7) 保持一致，并同步更新 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
- [x] **O1.2 补全 `pyproject.toml` 打包元数据**
  - **已执行**：[`pyproject.toml`](../pyproject.toml) 已补全 `[build-system]`（`setuptools>=68`）、`license`、`readme`、`authors`、`[project.urls]` 与 `project_compass = ["web/*"]` 数据文件声明，零新增第三方运行时依赖（`dependencies = []`）。
- [x] **O1.3 统一包版本号口径**
  - **已执行**：统一 `pyproject.toml`、[`src/project_compass/__init__.py`](../src/project_compass/__init__.py)、[`src/project_compass/mcp_server.py`](../src/project_compass/mcp_server.py#L39-L42) 及 [`tests/test_environment.py`](../tests/test_environment.py#L10) 为 `"1.0.0"`。

### O2 · 隐私脱敏、竞赛遗留物清理与 Git 发布策略（上线前硬阻断）

- [x] **O2.1 清理已追踪文件中的本机用户路径泄露**
  - **已执行**：已完成工作区非归档文档及保留脚本路径脱敏（`git grep` 排除 `docs/archive` / `.goal` / `.agents` 命中归零）。
- [x] **O2.2 清理 `.env.example` 与竞赛赞助商遗留脚手架**
  - **已执行**：[`../.env.example`](../.env.example) 已移除赞助商 key 残留，竞赛构建脚本与 `devpost/` 已通过 `git mv` 归档至 `docs/archive/competition_legacy/`。
- [ ] **O2.3 手工移出受保护的未追踪竞赛文档**
  - 工作区仍保留未追踪文件 `docs/ZETARIS_DEMO_CHALLENGE_55S.md`（受仓库协议保护、Agent 禁止修改或删除）；导出脚本 `scripts/export_public_release.py` 已强制排除该文件。公开推送前请由负责人**手动移出或归档**。
- [x] **O2.4 决定公共 Git 历史策略（单一 Clean Initial Release 提交）**
  - **已执行**：已实现 [`scripts/export_public_release.py`](../scripts/export_public_release.py)，支持从工作区导出脱敏后的**单一初始提交**至 `.release-export/project-compass-public`，并在导出阶段执行防泄露正则门禁与目录剪枝。

### O3 · 开箱即用体验、README 诚实度与可视化资产对齐

- [x] **O3.1 修复“新用户开箱运行看板结构上下文陈旧/排序失焦与无可用事实”的问题**
  - **已执行**：保留 `--extract-docs` 与 `--with-code-index`，同时修复 [`src/project_compass/derived_context.py`](../src/project_compass/derived_context.py) 目录指纹新鲜度（`current == True`）、优先保留已链接及 `src/` AST 节点并生成 `handoff_brief.code_nodes`；并将 [`src/project_compass/code_index.py`](../src/project_compass/code_index.py) `iter_python_files` 改为 `os.walk` 就地剪枝 `.git`/`.venv`/生成目录，使实时 `/api/state` 响应从超时降至 `< 0.7s`。
- [x] **O3.2 对齐 `mcp_server.py` 与 `README` / `server.json` / `smithery.yaml` 的零配置承诺**
  - **已执行**：新增 [`WorkspaceMCPAdapter`](../src/project_compass/local_plugin.py) 支撑零配置 `--project-path .` 本地工作区读写，`server.json` 与双语 README 对齐列明 4 项 MCP 工具（`project_context` / `append_evidence` / `query_state` / `propose_fact`），保留 `--base-url` 模式下的 `PROJECT_COMPASS_AGENT_TOKEN` 强校验边界。
- [x] **O3.3 全面更新 `README.md`、`README_EN.md` 与 `docs/images/*` 视觉资产**
  - **已执行**：在 `1440×900` 桌面视口重采 Clean Public Dogfood 真实截图并更新 [`docs/images/board_overview.png`](images/board_overview.png)、[`hover_citation.png`](images/hover_citation.png)、[`handoff_modal.png`](images/handoff_modal.png)，同步修正双语 README 中的测试数（542 Python + 16 CJS）、Apache-2.0 协议徽标、Swiss `5fr/7fr` + DOM 演进树描述、10px 预取表述与 4 项 MCP 工具列表。
- [x] **O3.4 清零 UI 与导出模板中的 16 处占位符（详见第三章台账）**。

### O4 · 开源社区治理与跨平台 CI 门禁

- [ ] 新增 `CONTRIBUTING.md`（本地测试门禁、前端 `node --check`、提交规范、不伪造证据原则）。
- [ ] 新增 `SECURITY.md`（本地 Token 安全边界、私密日志/环境消息过滤机制说明与漏洞反馈路径）。
- [ ] 新增 `.github/ISSUE_TEMPLATE/` 与 `.github/PULL_REQUEST_TEMPLATE.md`。
- [ ] 新增 `.github/workflows/ci.yml`：在 `ubuntu-latest` / `windows-latest` / `macos-latest` × `Python 3.10–3.13` 上运行 `unittest`、`node --check src/project_compass/web/app.js` 与包构建冒烟检查。

---

## 第二章：Project Compass 真实自举（Dogfooding）实跑案例

为了验证 Project Compass 对“开发 Project Compass 自己”是否真有用（而不只是 `--sample` 下 `e1/e2` 两条玩具数据），我们在本次真实跑通了**从仓内文档、真实 Agent 对话轨迹到建筑栅格看板的完整闭环**。

### 2.1 本次落地的数据接入闭环与公开示例资产

- [`src/project_compass/doc_fact_intake.py`](../src/project_compass/doc_fact_intake.py)（新增）：规则 `doc-structure-v1`，零外部模型依赖地扫描项目文档（`README.md`、`PRODUCT_GOAL.md`、`PRODUCT_SPEC.md`、`DECISIONS.md`、`HANDOFF.md`、根目录 `.md` 等），抽取**精确原文子串**作为 `goal`、`decision` 与 `task` 候选（由 `validate_candidates` 严格校验原文 span，并由 `ExtractionProgress` 游标保证断点续扫与幂等性）。
- [`src/project_compass/cli.py`](../src/project_compass/cli.py) & [`src/project_compass/code_index.py`](../src/project_compass/code_index.py)：新增可选 CLI 参数 `--extract-docs`（调用文档结构提取）与 `--with-code-index`（为 `--web` 与 `--export-format` 构建绑定当前工作区 SHA-1 `project_id` 的代码拓扑 `DerivedContext`）。同时严格禁止 `--sample` 模式混用上述开关。
- [`examples/dogfood_project_compass.json`](../examples/dogfood_project_compass.json)（新增，零本机隐私路径）：开源可用的公开自举数据集，重现本项目真实演进过程中的多会话分歧，包括：
  - 核心目标确立与竞赛期外部重依赖（`zetaris_provider`、`meterless_memory`、`jev_provider`）退役决策；
  - 冲突 A（`arch.retriever_backend`）：`session-alpha`（纯 Python 2-gram IDF，L3 Hit Rate `0.2857`）vs `session-beta`（标准库 SQLite `:memory:` FTS5 Trigram BM25，L3 Hit Rate `0.3571`、MRR `0.2560`）；
  - 冲突 B（`ui.design_system`）：`session-alpha`（紧凑命令台账，`4.87/10`）vs `session-beta`（Swiss Neo-Brutalism `5fr/7fr` 非对称编辑栅格，`9.30/10`）。
- [`tests/test_dogfood_cli.py`](../tests/test_dogfood_cli.py)（新增）：4 个回归用例验证文档精确原文跨度与幂等性、`--scan --extract-docs --with-code-index --export-format json` 完整链路、`--sample` 安全隔离拒绝边界及公开案例集加载/冲突/问答闭环。

### 2.2 实跑数据与实时看板观察证据

实际针对当前仓库构建隔离自举工作区 `.project-memory-dogfood/`（已被 `.gitignore` 的 `.project-memory-*/` 忽略，不污染仓库），融合了本地源码与文档扫描（`--scan . --extract-docs`）、本次会话真实 Antigravity `transcript.jsonl`（`--member-id project-author`）与公开分歧场景（`examples/dogfood_project_compass.json`），并启动在 `http://127.0.0.1:8792/`：

- **工作区写入统计（CLI 实测输出）**：
  - `project_id`: `299f228d389f023b`
  - `total_events`: `211`（含源码/提交扫描、Antigravity 公开轨迹、10 条 `doc_fact_scan` 文档候选及 9 条公开案例事件）
  - `total_facts`: `30`（`decision: 15`、`task: 10`、`goal: 4`、`assumption: 1`）
  - `doc_fact_scan`: 扫描 `25/25` 个文档源，无遗漏，抽出 10 条带精确 `quote` 的文档候选（覆盖 `README.md`、`PRODUCT_GOAL.md` 与 `DECISIONS.md` 直至 `2026-11-14 M3 UI overhaul`）
  - `code_index`: 索引 `155` 个 Python 文件（`0` 跳过）、`1,488` 个节点（`class: 192, file: 155, function: 254, method: 887`）、`2,730` 条关系边（`calls: 1170, contains: 1333, imports: 227`）
- **真实浏览器全链路走查（`1440×900` 视口，HTTP 200 无报错，控制台 `0` 错误）**：
  1. **初始态与在场矩阵**：页面加载显示 `ProjectCompass`、`INDEX // 201 EVIDENCE ITEMS`（前端索引计数），顶栏状态条展示 `Team Truth: 0 / 30 pending`、`project-author: 10`、`owner-dev: 6`、`session-alpha: 2`、`session-beta: 2`、`项目文档: 10`。
  2. **负责人裁决与状态晋升**：在 `#reviewer-input` 填入 `project-author`，切换至 `Team Truth` 视图后，先后确认核心团队目标，并针对 `arch.retriever_backend` 与 `ui.design_system` 采纳各自验证通过的 `方案 Beta`；随后 `Team Truth` 确认数由 `0 → 3`，待核对候选由 `30 → 25 pending`，`session-alpha`/`session-beta` 药丸转为绿色对勾 `✓`，`#team-truth-history` 完整落盘 3 条带操作人、时间戳与证据数量的历史裁决记录。
  3. **证据链问答与原文悬停取证（`Ask Compass`）**：提问 *“检索器为什么要采用 SQLite FTS5 Trigram BM25 方案？”* 后，`#investigation-answer` 同时给出**EVIDENCE GAPS** 提醒、`WHY / EVIDENCE`（并列展示 `session-beta` confirmed 实测数据、`project-author` M2 提交记录与被否决的 `session-alpha` conflicted 对照基线）以及 `CONFLICT HISTORY`；鼠标悬停 `[data-evidence-id="dogfood-retrieval-beta-test"]` 时，`#citation-popover` 正确弹出说话人、时间、文档来源 `docs/RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md` 与完整引文。
  4. **过程层与交接简报**：切换至 `过程` 层，横向时间轴显示 `28 主题 · 30 条记录`，`STRUCTURE CONTEXT` 展示 200 个结构节点与 400 条关系截取；开启 `交接简报`（`#handoff-modal`），完整呈现 1 条核心目标、3 条已确认团队共识、8 条待审候选与 8 项行动清单。

### 2.3 诚实复盘：这次自举实跑反而帮我们挖出的 4 个真实问题

“自己用起来”最有价值的地方，恰恰在于暴露了单测全绿时看不见的体验裂缝：

1. **自举问答 Q3 暴露中英混合分词盲区**：CLI 测试问答 *"UI 改版选了什么风格，有哪些证据支撑？"* 时，检索器优先召回了含开源待办和 `DECISIONS.md` 早期记录的证据，而把含 `ui.design_system` / `Swiss Neo-Brutalism` 的 A/B 卡片排在后面——原因是中英混排词面与标点切分权重不足，需在下一轮检索器优化中针对中英混排短语建立专项测试用例。
2. **结构上下文提示“来源已变化或不可用”与截断排序失焦**：刚由 `--with-code-index` 新鲜生成的 1,488 节点代码图，在 `过程` 层的 `#derived-context-note` 中仍提示 *“来源已变化或不可用 · . · 400 条结构关系 · 页面已截断”*，且按字母序优先展示了 `logs/` 与 `scripts/` 而把核心源码 `src/project_compass/` 截到后面；同时 `#handoff-modal` 第 4 节显示 `0 个节点（无直接关联代码模块）`，说明“代码符号与证据事实的自动桥接匹配”尚未在展示链路充分生效。
3. **16 处占位符与静态文本在真实数据下直接刺眼暴露**：浏览器实测清晰抓到了页面右上角写死的 `Local workspace`、`TEAM CONTEXT` 静态徽标以及待办中的占位符整改提示（见第三章）。
4. **原生本地扫描未加 `--extract-docs` 时门槛仍偏高**：纯源码库初次运行如果用户不知道附加 `--extract-docs`，依然只见材料不见候选，需在下一步开源交互中顺滑打通。

### 2.4 一分钟本地复现自举看板命令

仓库任何人（或评审）只需在根目录执行两条命令之一即可查看本自举项目状态：

```powershell
# 方式一：本地源码 + 文档结构提取 + AST 代码拓扑看板
$env:PYTHONPATH='src'
python -m project_compass.cli --scan . --extract-docs --with-code-index --web --port 8793

# 方式二：直接导出或查看无隐私脱敏公开自举演进数据集
python -m project_compass.cli --input examples/dogfood_project_compass.json --export-format json
```

---

## 第三章：UI 看板与导出模板 4 类 16 处占位符整改台账（✅ O3.4 已全部清零）

以下 **4 类共 16 处占位符/假默认值/硬编码残留** 均已完成整改并通过单测与 Node VM 前端契约验证（额外修复 `.citation-popover` 长文件名右缘裁切与 `TranscriptWatcher.sync()` 空回包丢失 `"channel": "antigravity"` 问题）：

| 类别 | 编号 | 文件与整改点 | 整改前问题 | 已落地修复状态 |
|---|---|---|---|---|
| **A. 跨项目硬编码导出模板** | P1 | `src/project_compass/cognitive_export.py` | `export_github_issue` 兜底写入硬编码“黄金路径” | ✅ 仅渲染真实 `active_tasks`，空时显式提示无行动项 |
| **A** | P2 | `src/project_compass/cognitive_export.py` | `export_pull_request` 硬编码本项目专属检测命令与文案 | ✅ 改为动态读取实测证据与通用验证缺失提示 |
| **A** | P3 | `src/project_compass/cognitive_export.py` | `export_prd` 写死固定多 Agent 协作背景描述 | ✅ 由目标项目真实 `goal` / `assumptions` / `conflicts` 推导 |
| **A** | P4 | `src/project_compass/cognitive_export.py` | `export_prd` 写死“视线聚焦与注意力聚焦”宣传语 | ✅ 绑定项目真实核心目标或提示 `[待补充核心目标]` |
| **A** | P5 | `src/project_compass/cognitive_export.py` | `export_prd` 写死功能范围与验收清单元文本 | ✅ 动态读取真实 `decision` 与 `task` 列表 |
| **B. 空状态与静态骨架兜底** | P6 | `src/project_compass/dashboard.py` | 固定 4 章节骨架与合成路径分支 | ✅ 区分真实状态与缺失提示并保留契约字段 |
| **B** | P7 | `src/project_compass/web/index.html` | 静态 `等待扫描结果` 占位提示 | ✅ 由实时 `intake` 状态与动态操作反馈驱动 |
| **B** | P8 | `src/project_compass/web/index.html` | 原文抽屉初始静态占位 | ✅ 收口为统一空选态提示与键盘导航指引 |
| **B** | P9 | `src/project_compass/sample_data.py` | `--sample` 仅有 2 条极简事件 | ✅ 保留 `e1`/`e2` 契约兼容并扩展真实多角色演进样例 |
| **C. 错位标签与假默认值** | P10 | `src/project_compass/web/app.js` & `transcript_watcher.py` | 连接态无论何通道均显示 `Codex 已连接` | ✅ 按 `antigravity` / `codex` / `doc_fact_scan` 等真实通道渲染 |
| **C** | P11 | `src/project_compass/web/index.html` & `app.js` | 顶栏与状态回退写死 `Local workspace` | ✅ 改为 `formatConnectionLabel(data)`（`本地工作区 · 项目名`） |
| **C** | P12 | `src/project_compass/web/index.html` | 负责人/提问输入框预填默认 `value=` | ✅ 统一改为 `placeholder=` 提示，避免假默认值误导 |
| **C** | P13 | `src/project_compass/web/index.html` | 输入框示例硬编码 Windows 反斜杠路径 | ✅ 改为跨平台中性示例 `./your-project 或本地仓库路径` |
| **D. 残留英文与双语混杂** | P14 | `src/project_compass/web/index.html` | 英文标语、`SWISS EVIDENCE GRID`、`TEAM CONTEXT` 静态徽标 | ✅ 中文化统一工作台文案并转为动态 `#investigation-scope-tag` |
| **D** | P15 | `src/project_compass/web/app.js` | `No member data`、`PERSONAL CANDIDATES`、`PROJECT MATERIALS` 等 | ✅ 全量收口为规范中文术语与统一空态表达 |
| **D** | P16 | `src/project_compass/web/app.js` | `relation(s)`、`REVIEW HISTORY`、`Confirm as team fact` 等混杂文本 | ✅ 统一为中文格式化函数，同时保留前端/契约测试断言兼容 |

---

## 第四章：三项架构/开源拍板决策记录

1. **开源许可证**：✅ 负责人拍板选择 **`Apache-2.0`**，根目录 [`LICENSE`](../LICENSE) 与 [`server.json`](../server.json) 已对齐。
2. **公开 Git 历史策略**：✅ 采纳**方案 A（干净单提交导出）**，已通过 [`scripts/export_public_release.py`](../scripts/export_public_release.py) 生成并校验脱敏公共仓库 `.release-export/project-compass-public`。
3. **实施顺序**：✅ 已按 **O1 → O2 → O3** 全量执行、通过 UI 真机校验与单元测试回归；**O4 社区模板与 GitHub Actions CI** 留待下一迭代或按需补充。

---

## 第五章：PBR 三视角穿透审查结论表

| 审查视角 | 核查范围 | 发现与处理结论 | 证据锚点 |
|---|---|---|---|
| **1. 用户视角** | `index.html`、`app.js`、`styles.css`、`1440×900` 实时看板、双语 `README` | 实机发现 2 处真实缺陷并即刻修复：（a）长文件名触发 `#citation-popover` 右缘 `● 当前有效` 裁切（已通过 `min-width: 0` + `overflow-wrap: anywhere` + `flex-shrink: 0` 修复并在 `1440×900` 下验证完整不裁切）；（b）初次打开或空步 sync 时 `TranscriptWatcher` 丢失 `"channel": "antigravity"` 导致界面通道文案回退错误（已收口 `_build_status()` 并补单测） | [`styles.css`](../src/project_compass/web/styles.css)、[`hover_citation.png`](images/hover_citation.png)、[`tests/test_open_source_readiness.py`](../tests/test_open_source_readiness.py) |
| **2. 架构与数据流接缝** | `cli.py` -> `code_index.py` -> `derived_context.py` -> `web_server.py`、`mcp_server.py` -> `WorkspaceMCPAdapter` -> `local_plugin.py`、`export_public_release.py` | 穿透排查并修复 3 处接缝隐患：（a）`iter_python_files` 与导出脚本原用 `rglob` 先遍历 `.git`/`.venv`/`.release-export` 导致每次 `/api/state` 耗时 `8.3s+` 触发锁超时，改为 `os.walk` 就地剪枝后单次 `/api/state` 降至 `0.67s`；（b）`WorkspaceMCPAdapter` `state.query` 原直接向 `_structure_answer` 传 `InvestigationAnswer` 对象而非 `dict`（已转换为 `answer.to_dict()`）；（c）`test_environment.py` 仍断言 `"0.1.0"`（已同步统一为 `"1.0.0"`） | [`code_index.py`](../src/project_compass/code_index.py)、[`local_plugin.py`](../src/project_compass/local_plugin.py)、[`export_public_release.py`](../scripts/export_public_release.py) |
| **3. 对抗测试视角** | 隐私泄露门禁、受保护文件隔离、`--base-url` 鉴权边界、`os.walk` 目录剪枝、导出构建冒烟 | 验证（a）未设置 `PROJECT_COMPASS_AGENT_TOKEN` 启动 `--base-url` 必拒绝退出；（b）注入真实盘符路径会被 `export_public_release` 拦截抛出 `ValueError`，同时测试夹具占位字符串不误伤导出；（c）`.release-export/project-compass-public` 单提交可独立通过全套单元测试且离线 wheel 包含 `web/*` 资源；（d）受保护 `docs/ZETARIS_DEMO_CHALLENGE_55S.md` SHA-256 与工作区零修改 | [`export_public_release.py`](../scripts/export_public_release.py)、[`tests/test_open_source_readiness.py`](../tests/test_open_source_readiness.py)、[`pyproject.toml`](../pyproject.toml) |
