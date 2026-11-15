# M3 UI A/B 对照测试与双盲视觉评审报告（2026-11-14）

## 1. 实验目标与受控变量设计

为解决 Project Compass 原 Web 看板长期存在的“样式多套私自实现、青绿 `#0d6e52` 泛滥、卡片内套娃边框噪音、个人/团队/过程视图视觉混淆、零值绿色误导以及 `390px` 移动端溢出”等问题，M3 阶段在不引入任何第三方前端框架、严格保持零新增依赖及 `index.html` 全量 ID 与 `app.js` 数据契约兼容的前提下，围绕 **Swiss Bauhaus / Neo-Brutalism（国际主义栅格 + 新粗野克制建筑美学）** 构造了两组布局风格截然不同的对照实现，并组织了 3 名隔离盲审视觉 Critic 对真实 Chromium/Playwright 运行时截图（`1440×900` 与 `390×844`）开展独立评审与合成迭代。

- **公共不变量（对照组共同基线）**：
  - 同一份重构后的 [app.js](../src/project_compass/web/app.js)（单一 `apiFetch`、统一 `renderStatusBadge`、无内联 `style=`、诚实零值徽章、无 `"100% 绿灯"`、双栏冲突裁决逻辑、`Esc` + 焦点归还 + 边界钳制浮窗）。
  - 同一组 `--paper: #F4F3EE` / `--navy: #090D16` / `--orange: #FF5500` / `--orange-ink: #B83B00` / `--muted: #3F4756` 语义 Token 体系与 `2px` 锐利切角、零模糊阴影基线。
  - 同一套样例数据集（`--sample` 模式独立隔离运行）与同一套 Playwright 5 场景视口捕获流程。

---

## 2. 双分支方案架构对比（Design Alpha vs Design Beta）

| 维度 | 方案 A：**Design Alpha** (`Triage-First Swiss Command Ledger`) | 方案 B：**Design Beta** (`Asymmetric 5fr/7fr Swiss Editorial Grid`) |
| :--- | :--- | :--- |
| **空间骨架** | 单栏垂直指挥账簿，先强置分歧与指标、再向下顺序展开个人/团队分区 | 非对称 `5fr / 7fr` 双栏编辑栅格（左栏 `5fr` 为 North Star 海报、证据问答与图例轨道；右栏 `7fr` 为高频工作台/分歧矩阵） |
| **KPI 指标条** | 5 张卡片呈 3+2 网格排列（桌面首行 3 张、次行 2 张） | 后期合成优化目标：全宽 5 列单行均分；移动端 `2+2+1` 跨栏对齐 |
| **分诊首屏密度** | Personal 工作台落位相对靠后，视觉焦点偏重顶部指令区 | Personal 模式下 `WORKBENCH` 与 `DECISIONS` 位于右侧首屏核心位置；Team 模式下 `TEAM TRUTH MATRIX` 居右栏顶部 |
| **量化自动化门禁** | 静态脚本通过（`ALL_GATES_PASS`、`test_dashboard` 首轮 21 tests OK，M3 后增补至 22 tests）；但 `390x844` 实测发现 `.view-switch` 超出视口边界被 `overflow-x: hidden` 遮罩 | 静态脚本与 `test_dashboard` 首轮 21 tests 全部通过，`390x844` 元素级边界检测优于 Alpha（但首轮 3+2 KPI 仍存在孤儿格待消解） |

---

## 3. 第一阶段：3 位独立视觉 Critic 双盲评审结果（Alpha vs Beta）

3 名互不知晓作者映射与源码来源的 `research` Critic 通过并行盲审全部 10 张实时运行截图（`design_alpha_01..05.png` vs `design_beta_01..05.png`），按 `grid_hierarchy`、`triage_clarity`、`typography_contrast`、`responsive_mobile`、`anti_ai_slop` 5 个维度严格评分（0–10 分）：

| Critic 角色 | Design Alpha 得分 | Design Beta 得分 | 胜出裁决 | 核心扣分与合成意见摘要 |
| :--- | :---: | :---: | :---: | :--- |
| **Critic 1**：Swiss Grid & Typography Master | `5.0` | **`7.4`** (`grid: 7.4, triage: 7.8, typo: 7.6, mobile: 6.6, anti_slop: 7.5`) | **Design Beta** | 肯定 Beta 的 `5fr/7fr` 非对称栅格与编辑呼吸感；指出双方 3+2 指标格均有孤儿格、次级面板仍套了过多四边黑框、Alpha 移动端按钮越界且 Process 孤立感不足 |
| **Critic 2**：Engineering Workbench UX & Triage | `4.8` | **`7.3`** (`grid: 7.3, triage: 7.6, typo: 7.4, mobile: 6.4, anti_slop: 7.8`) | **Design Beta** | Beta 的左轨+右舞台分诊更贴合工程师日常工作流；要求把 Personal 待办与决策提至右栏 `<= 900px` 首屏，并在 Process 视图隐藏 `.rail-column` |
| **Critic 3**：WCAG AA, Mobile & Anti-AI-Slop | `4.8` | **`7.0`** (`grid: 7.2, triage: 7.5, typo: 6.5, mobile: 6.3, anti_slop: 7.5`) | **Design Beta** | 严格扣除了橙底白字对比度风险、移动端顶栏过厚、触控热区不足 `44px` 与零值绿色隐患，要求统一落到 `--muted: #3F4756`、`--orange-ink: #B83B00` 与 `--navy` 配 `--orange` |

**阶段结论**：**3:0 全票选择 Design Beta** 作为骨架基底，并吸收 Alpha 的快速分诊结构以及 3 位 Critic 提出的全部扣分修正进入终版合成。

---

## 4. 终版合成改造与双轮盲审门禁验证（`>= 9.0/10`）

依据 Critic 扣分清单，我们在工作区 [index.html](../src/project_compass/web/index.html)、[styles.css](../src/project_compass/web/styles.css) 与 [app.js](../src/project_compass/web/app.js) 中实施了以下结构性合成改造：

1. **消除 KPI 孤儿格**：桌面端改用 `repeat(5, minmax(0, 1fr))` 横向 5 列均分；`<= 1024px` / `<= 780px` 移动端通过 `.metric:last-child:nth-child(odd) { grid-column: 1 / -1; }` 收敛为无孤儿的 `2+2+1` 栅格。
2. **首屏与层级重建**：将 `#personal-activity` 移入左侧 `.rail-column`，使 Personal 视图右栏顶部立即呈现 `#personal-todos` 与 `#personal-decisions`；Team 视图右栏顶部直显 `#team-truth-history`（Split A-vs-B 冲突对抗矩阵）与 `OWNER REVIEW`。
3. **去盒化与演进单行化**：所有次级大区切换为 `.ledger-band`（透明底 + `2.5px` 顶部实线），全站仅保留 `.goal-surface` 焦点海报投影；`#chapter-timeline` 升级为单行 4 阶段等宽 `flex` 时间轴；Process / Source 视图隐藏 `.rail-column` 与 `.hero-copy`，使 `PROJECT TRACE` 独占全宽。
4. **WCAG AA、移动端紧缩与触控达标**：`390x844` 顶栏重建为 `103px` 双行网格（`clippedCount === 0`）；`Team Truth 0` 等零计数徽章采用中性灰 `.zero-count`。

### 4.1 终版盲审第 1 轮（均分 `9.033`，发现关键根字号缩放 Bug）

在首轮终版 5 张实时截图盲审中，三位 Critic 分别给出 **`9.1`、`8.9`、`9.1`**（均分 `9.033`），并独立定位出隐藏在 CSS 继承链中的真实工程缺陷：
- **根字号缩放 Bug**：`html, body { font-size: 15px; }` 导致 `1rem = 15px`，使全站 28+ 处 `0.75rem` 标签计算值为 `11.25px`（低于 `12px` 规范下限）。
- **Process 过程轨道细节**：`.trace-legend` 使用 `space-between` 造成中间图例孤悬居中；`.trace-sources` 缺少 `width: 100%` 导致右缘错位 `40–55px`；固定 `width: 300px` 在 3 主题下留白。
- **Personal 卡片状态显性度与次级触控**：`.todo-item`/`.decision-item` 缺少高对比 `renderStatusBadge` 徽章，且部分移动端次级操作按钮高度未达 `44px`。

### 4.2 定向精修与第 2 轮全票复核（`9.3 / 9.3 / 9.3 = 9.30` PASS）

我们立即实施了定向修复：
- 分离 `html { font-size: 16px; }` 与 `body { font-size: 15px; }`，使全站 `0.75rem === 12px` 实测成立（Playwright DOM 校验 `sub12Count === 0`、`rootFontSize === '16px'`、`eyebrowFontSize === '12px'`），并同步升级门禁脚本识别 `html` 根字号换算。
- 过程层 `.trace-legend` 左对齐聚类、`margin-left: auto` 锚定说明文字；`.trace-group` 设为 `flex: 1 1 300px` 等分填充轨道；`.trace-sources` 与 `.trace-citation` 补齐 `width: 100%`（实测 `srcR === factR === 455px`，右缘零偏差）。
- `.todo-item` 与 `.decision-item` 胶囊行前置 `${renderStatusBadge(fact.status)}`；移动端 `<= 780px` 补充 `.icon-button`、`.question-row`、`.handoff-action-btn`、`.trace-nav-actions button`、`.workspace-utilities summary`、`.ev-pill` 的 `min-height: 44px` 规则并统一 `.field-tag` 宽度。

随后重新启动独立 `--sample --web --port 8793` 实例并重新捕获 5 张终版截图，提交同一批 3 名 `research` Critic 盲审复核：

| Critic 角色 | 第 1 轮得分 | 第 2 轮最终得分 | 5 维度分项（第 2 轮） | 门禁结果 (`>= 9.0`) |
| :--- | :---: | :---: | :--- | :---: |
| **Final Critic 1** (Swiss Grid Master) | `9.1` | **`9.3`** | `grid: 9.5, triage: 9.3, typo: 9.0, mobile: 9.2, anti_slop: 9.7` | **PASS** (`true`) |
| **Final Critic 2** (Workbench UX Architect) | `8.9` | **`9.3`** | `grid: 9.2, triage: 9.4, typo: 9.6, mobile: 9.0, anti_slop: 9.6` | **PASS** (`true`) |
| **Final Critic 3** (WCAG AA & Mobile) | `9.1` | **`9.3`** | `grid: 9.5, triage: 9.4, typo: 9.3, mobile: 9.1, anti_slop: 9.6` | **PASS** (`true`) |
| **全票综合均分** | `9.033` | **`9.300`** | 全项维度均 `>= 9.0` | **3:0 全票通过** |

所有变更同步通过 [UI 设计手册](UI_STYLE_GUIDE_MANUAL.md)、前端静态门禁（历史遗留青绿配色出现 `0` 次、裸 `#hex == 0`、模糊阴影 `0`、最小字号 `>= 12px`）、Node 契约测试与 `tests.test_dashboard` 全套后端 HTTP 验证。

---

## 5. 三视角 PBR 代码审查暴露缺陷与终版闭环（Post-Visual Polish）

完成第 2 轮视觉盲审（`9.30/10`）后，我们遵循 `AGENTS.md` 模块门禁触发了隔离三视角 PBR 代码审查（用户视角 / 架构数据流视角 / 对抗测试视角），暴露出若干**仅在只读切换、冲突视角、键盘操作与最小运行环境下浮现的深度 P0/P1 缺陷**并已全部清零关闭：

1. **事实晋升与诚实边界收敛**：
   - 修复 `project.read_only === true` 时未确认待办/决策落入 `else` 分支显示绿色确认徽章的问题；只读模式下未确认候选不再伪造团队共识标记。
   - 修复 `isGoalAccepted` 按 `subject_key` 跨 ID 匹配导致成员 B 冲突目标被标绿为已确认的问题，改为严格按 `fact.id` 核验。
   - 移除个人待办与交接简报中脆弱的子串正则完成态启发式匹配，统一严格遵循后端 `task_state === "completed"`。
   - 引入纯函数 `resolveFactStatus(fact)` 协同渲染个人卡片、分歧卡与详情抽屉的已采纳/已驳回/补证据状态，并移除个人面板中的冗余双层套框及未确认/模型块上的绿色 `.reviewed-note` 误用（改为中性 `.meta-note`）。
2. **浮层 z-index 序、Esc 栈与焦点/DOM 隔离**：
   - 调整层叠秩序为 `#scrim (80) < #handoff-modal (88) < #evidence-drawer (95) < #citation-popover (100)`，解决交接简报弹窗内点击 `[e*]` 时抽屉被遮挡的问题。
   - 实现弹窗自动聚焦、拆分 `lastModalTrigger` 与 `lastDrawerTrigger`、改造 `Escape` 为仅关闭最顶层可见浮层，并在 `closeDrawer()` 时清空 `#drawer-body` 与显式作用域化 `#review-note` 读取，杜绝跨提交污染。
   - 为 `[data-inline-review]` 与弹窗/抽屉内 `[data-evidence-id]` 补齐键盘隔离与 `Enter`/`Space` 支持。
3. **XSS 逃逸封堵、剪贴板诚实性、浮窗边界与 M3 运行时测试**：
   - 为时间轴 `ch.status` 增加白名单 `safeToken()`，对 `rec.score`、`ch.count` 与 `direction_suggestion` 强制执行 `esc()`/白名单校验；`STATUS_BADGE_MAP` 改用 `Object.create(null)`。
   - 修复 `copyHandoffMarkdown` 在无剪贴板或 `execCommand("copy")` 失败时虚假提示已复制的缺陷，并为 `exportCognitiveAsset` 补齐无全局 `URL`/`navigator` 环境的防御守卫。
   - 修正 `showCitationPopover` 垂直边界钳制顺序（小视口恒保证 `top >= 12px`）、异步返回后按 `currentEvidenceId` 防覆盖并二次测高重钳制，以及 `apiFetch(..., { background: true })` 隔离悬停预取超时避免误污 `#connection-label`。
   - 新增全套 M3 前端交互自动化回归脚本 [web_m3_interactions_test.cjs](../tests/web_m3_interactions_test.cjs) 与单元测试包装 [test_web_m3_interactions.py](../tests/test_web_m3_interactions.py)，纳入 `unittest discover` 持续回归。

### 5.1 M3 收尾轮次（Round 4）PBR 三视角终审闭合表

在完成认知资产导出与只读二级项目 `project_id` 垂直作用域打通后，再次按 `pbr-code-review` 执行三视角正交核查，全部 5 项 P1 缺陷就地修复并复测归零：

| 审查视角 | 审查过程与检查接缝 | 发现的真实缺陷（已清零） | 修复措施与复验结果 |
| :--- | :--- | :--- | :--- |
| **1. 用户视角**<br>*(User Perspective)* | 实跑 `export_state_by_format(build_dashboard_state(sample_events()), ...)`、检查 `exportCognitiveAsset` 与只读抽屉 | PR 导出将未完成/`[blocked]` 待办与 `"单元测试 100% 绿色通过"` 硬编码为 `- [x]`；`exportCognitiveAsset` 无下载且无剪贴板时仍提示 `"已导出"`；只读抽屉残留 `Confirm support` 按钮 | `cognitive_export.py` 严格按 `_is_task_completed` 勾选并以 `- [ ]` 保留待核对清单元；`app.js` 共用 `copyTextToClipboard`，无真实下载/复制时诚实提示 `"请手动复制"`；只读下屏蔽 `Confirm support`（`test_cognitive_export` 与 18 项 M3 契约通过） |
| **2. 架构与数据流视角**<br>*(Dataflow & Seams)* | 核对 `web_server.py` 路由、PRD 导出 Schema、PR 成员字段与二级项目读写隔离 | `export_prd` 读取顶层 `thinking_line` / `chapter_timeline` 致实导 PRD 丢失阶段树；`export_pull_request` 读取 `id` 而非 `member_id`；`web_server.py` 每次悬停预取调用全量 `dashboard_state()` 仅查主项目 ID | `export_prd` 兼容回退至 `team.thinking_line` 与 `team.timeline_chapters`；`export_pull_request` 读取 `member_id \|\| id`；`DashboardHTTPServer.active_project_id()` 无锁比对（`ID_MATCH: True`） |
| **3. 测试对抗视角**<br>*(Adversarial Tester)* | 对抗 `POST /api/investigate` 空值输入、无 ID 对象 `resolveFactStatus`、断连浮窗及 Node VM 全套 | `{"project_id": null}` 被强转为 `"None"` 误报 404，`{"question": null}` 误查询；`resolveFactStatus` 对无 ID 对象产生 `undefined === undefined` 误匹配 | `web_server.py` 严格校验 `None` / 非字符串类型（400/200 回归见 `test_dashboard.py`）；`resolveFactStatus` 缺 ID 提前返回；全部 16 套 `.cjs` 与 41 项焦点 Python/HTTP 测试全部通过 |
