# Project Compass UI 设计与交互规范手册 (Swiss Bauhaus & Neo-Brutalism v3.0)

本文档为 [Project Compass Web 看板](../src/project_compass/web/index.html) 的唯一权威视觉与交互设计系统规范（M3 完成后已与 [styles.css](../src/project_compass/web/styles.css) 和 [app.js](../src/project_compass/web/app.js) 完全对齐）。所有前端 CSS、DOM 结构、徽章状态语法与无障碍边界均必须遵守本手册并接受自动化门禁验证。

---

## 一、 核心设计原则与诚实约束

1. **Swiss Bauhaus / Neo-Brutalism 克制架构**：
   - 使用明确的信息等级、`1px`–`3px` 锐利结构分割线与 `2px` 微倒角（`--radius: 2px`），全局仅保留 `3px 3px 0 0` 与 `2px 2px 0 0` 硬边偏移投影（`--shadow-focus` / `--shadow-orange` / 控件硬边偏移），严禁任意半径的柔和模糊投影（`blur > 0`）与玻璃拟态（`backdrop-filter: blur(...)` 禁止，模态遮罩强制 `backdrop-filter: none`）。
   - 核心焦点海报（`.goal-surface`）、原子交互卡片与辅助功能外框（`.investigation-answer`、`.thinking-line-canvas`、`.workspace-utilities`）保留四边硬框；分段容器采用 `.ledger-band` 顶线去盒化设计（`background: transparent`，`border-top: 2.5px solid var(--navy)`），消除“套娃卡片”噪音。
2. **证据诚实与认知零误导**：
   - 团队视图 **禁止伪造积极完成度提示**；`0` 值计数统一采用中性灰 `.zero-count`（`--surface-alt` + `--muted`），绝不对 `Team Truth 0`、`0 accepted facts` 或 `0 unlinked evidence` 使用绿色成功色调。
   - **单一事实晋升边界**：候选声明默认标记为 `proposed`；冲突必须通过 Split A-vs-B 对抗矩阵（`.conflict-vs-grid`）同时保留双方立场与原始证据 ID，由填写姓名后的负责人显式裁决；系统启发式建议仅作参考徽标。
3. **单一 Token 真源**：
   - [styles.css](../src/project_compass/web/styles.css) 中禁止在 `:root` 块外部出现裸 `#hex` 色值；[index.html](../src/project_compass/web/index.html) 与 [app.js](../src/project_compass/web/app.js) 中禁止出现裸 `#hex` 与内联 `style=` 属性。严禁使用历史遗留青绿配色体系。

---

## 二、 `:root` 设计令牌系统 (Design Tokens)

全部色彩、表面、边框、投影与排版令牌定义于 [styles.css](../src/project_compass/web/styles.css) 顶部 `:root`：

### 2.1 表面与墨色（Surfaces & Ink）

| Token | 色值 | 用途与对比度基线 |
| :--- | :--- | :--- |
| `--paper` | `#F4F3EE` | 全局暖石纸基画布，消除纯白眩光 |
| `--surface` | `#FFFFFF` | 原子卡片、输入控件、模态弹窗与状态容器底色 |
| `--surface-alt` | `#EBE9E2` | 中性零值徽章、次级表带与交替行底色 |
| `--surface-subtle` | `#E5E2D8` | 弱化表面底色与禁用态背景 |
| `--navy` | `#090D16` | 核心结构粗线、主行动按钮背景、高对比橙底文本墨色 |
| `--navy-soft` | `#141B2D` | 次级深海军蓝表面与悬停深色状态 |
| `--ink` | `#090D16` | 主正文与主标题文本 |
| `--ink-inverse` | `#F8FAFC` | `--navy` 深色背景上的反白文字 |
| `--muted` | `#3F4756` | 次级元数据、时间戳与作者说明（在 `#F4F3EE` 上 > 8.4:1、在 `#FFFFFF` 上 > 9.3:1 WCAG AA/AAA） |
| `--line` | `#CBD5E1` | 卡片内部分割细线 |
| `--line-strong` | `#090D16` | 关键骨架线、KPI 分栏线与实体卡片硬边框 |

### 2.2 强调色与 WCAG AA 墨色配对

| Token | 色值 | 强制配对规则 |
| :--- | :--- | :--- |
| `--orange` | `#FF5500` | 国际安全橙（Bauhaus 焦点锚点、激活信息层、North Star 左边线）。背景使用 `--orange` 时**必须搭配 `--navy`（`#090D16`）文字**（实测对比度 > 6.0:1，严禁白字配 `--orange`） |
| `--orange-ink` | `#B83B00` | 浅纸底（`#F4F3EE`）或白底（`#FFFFFF`）上展示橙色文本/Kicker 时的加深专用墨色（5.16:1–5.73:1 WCAG AA） |

### 2.3 单一认知语义令牌 (Semantic State Palette)

全站状态徽章、冲突面板与历程线遵循同一组语义色彩契约：

| 语义状态 | Ink Token | Bg Token | Border Token | 对应 UI 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **已确认 / 一致** | `--ok-ink: #14532D` | `--ok-bg: #DCFCE7` | `--ok-border: #166534` | `accepted` / `confirmed` / `completed` / `● CURRENT`（含已确认 `.reviewed-note`） |
| **冲突 / 阻塞 / 不可用** | `--danger-ink: #991B1B` | `--danger-bg: #FEE2E2` | `--danger-border: #B91C1C` | `conflicted` / `blocked` / `● UNAVAILABLE` |
| **已驳回 / 已放弃** | `--muted: #3F4756` | `--surface-alt: #EBE9E2` | `--muted: #3F4756` | `rejected` / `abandoned`（`.is-rejected` 中性灰） |
| **待确认 / 假设 / 暂缓** | `--warn-ink: #92400E` | `--warn-bg: #FEF9C3` | `--warn-border: #A16207` | `proposed` / `candidate` / `deferred` / `needs_evidence` / `superseded` |
| **系统线索 / 中性元注** | `--info-ink: #1E3A8A` | `--info-bg: #DBEAFE` | `--info-border: #1D4ED8` | 系统启发式推荐 / `relation_confirmed` / `.decision-item` 左条（待确认与模型元数据使用中性 `.meta-note`） |
| **模态遮罩** | — | `--scrim-bg: rgba(9, 13, 22, 0.56)` | — | 无高斯模糊纯暗遮罩（`backdrop-filter: none`） |

### 2.4 几何、投影与字体基准

| Token | 值 | 说明 |
| :--- | :--- | :--- |
| `--shadow-focus` | `3px 3px 0 0 var(--navy)` | 焦点海报、模态框与悬停卡片硬阴影 |
| `--shadow-orange` | `3px 3px 0 0 var(--orange)` | 高亮焦点的橙色硬阴影 |
| `--radius` | `2px` | 全站统一建筑切角 |
| `--gutter` | `24px` | 主栅格列间距 |
| `--font-sans` | `"Inter", "Helvetica Neue", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif` | 主界面无衬线字体 |
| `--font-mono` | `"JetBrains Mono", "Cascadia Code", "Consolas", ui-monospace, monospace` | 等宽数字、`tabular-nums` 编号与来源标识 |
| 根字号基准 | `html { font-size: 16px; }`, `body { font-size: 15px; }` | 保证 `1rem === 16px`，全站最小字号 `0.75rem === 12px`（零亚 12px 文本） |

---

## 三、 架构栅格与信息层级

### 3.1 桌面端栅格（`1440px` 标准视口）

1. **Topbar（`.topbar`）**：左品牌标识（`PROJECT COMPASS · SWISS EVIDENCE GRID · v1.0`）+ 中央动态多会话在场栏 `#session-presence-bar`（`Team Truth` 与个人成员胶囊）+ 右侧操作组（`↗ 交接简报` 与本地工作区连接指示）。
2. **Hero & Toolbar**：标题与双视角切换器（`Personal view · 个人看板` / `Team truth · 团队共识`）；工具栏聚合成员选择器（`MEMBER`）、负责人输入（`负责人`）以及三态信息层切换（`概览` / `过程` / `原文`）。
3. **5 列全宽建筑指标条（`#metrics`）**：`grid-template-columns: repeat(5, minmax(0, 1fr))` 均分 5 项 KPI，以 `1px solid var(--line-strong)` 竖向切分，彻底消除 3+2 孤儿格。
4. **`5fr / 7fr` 非对称编辑双栏（`.editorial-grid`）**：
   - **左栏（`5fr` 轨道 `.rail-column`）**：North Star 核心焦点海报（`.goal-surface`，`proposed` 状态呈现暖黄底 + `6px #FF5500` 左边线 + 硬阴影；`accepted` 状态切换冷静高可信呈现；`rejected` 状态采用中性 `.is-rejected`）→ Evidence Q&A 调查问答（`.ledger-band`）→ 最近推进活动 `#personal-activity` → 图例说明与折叠诊断抽屉 `.workspace-utilities`。
   - **右栏（`7fr` 主舞台 `.stage-column`）**：
     - **Personal 视图首屏**：`WORKBENCH // 我的待办任务` 与 `DECISIONS // 我的决策与前提` 紧贴顶部第一折叠区（`<= 900px` 可直接触达状态徽章、`[e1]` 证据胶囊与采纳/驳回操作）。
     - **Team 视图**：`TEAM TRUTH MATRIX // 分歧对抗矩阵与共识历史` 置顶呈现（`.conflict-vs-grid` 等高 `立场 A` / `VS` / `立场 B` 对抗双栏，保留 `[e1]`/`[e2]` 证据与独立裁决按钮），紧接 `OWNER REVIEW // 待负责人核对`。
5. **全宽演进带（`#thinking-surface`）**：底部单行 4 阶段时间轴 `#chapter-timeline`（`flex: 1 1 0` 等宽排列 `01 → 02 → 03 → 04` + 思维分支树）。

### 3.2 信息层严格隔离

- **Process 过程层（`body[data-layer="process"]`）与 Source 原文层（`body[data-layer="source"]`）**：强制隐藏 `.rail-column` 与 `.hero-copy`，将主舞台全宽让渡给 `PROJECT TRACE // 项目历程` 三主题横向轨道或可过滤原始证据脊柱；仅冲突历史 `#team-truth-history` 通过 `order: 6` 在需要时保留于底部查阅。
- **过程轨道视觉对齐**：`.trace-legend` 图例徽章左集群对齐、提示说明右锚定；`.trace-track` 配合 `.trace-group { flex: 1 1 300px; }` 自动填满宽度而不拉伸短列高度；`.trace-sources`、`trace-citation`、`trace-source` 与 `trace-fact` 保持 `width: 100%` 且纵向分层堆叠标题/作者/时间，禁止行内文字粘连。

### 3.3 移动端响应式契约（`<= 780px` / `390x844` 基线）

- `.topbar` 采用两行紧凑 Grid 架构：第 1 行容纳品牌图标/标题与 `交接简报` 按钮；第 2 行 `#session-presence-bar` 横跨全宽（`flex-wrap: wrap`），在隐藏副标题后顶栏总高保持在 `~103px`（`<= 105px`），三枚会话胶囊完整无横向裁剪。
- `#metrics` 自适应折叠为 **2+2+1 对称栅格**：前 4 项为两行双列，第 5 项（`.metric:last-child:nth-child(odd)`）使用 `grid-column: 1 / -1` 横跨全宽横向左右对齐，零孤儿空格。
- `.conflict-vs-grid` 与 `.chapter-timeline` 在窄屏安全降级为单栏垂直排布；`.lens`、`layer-choice`、`handoff-cta-btn`、`presence-pill`、审核按钮、`icon-button`、`ev-pill` 与选择控件强制 `min-height: 44px`。

---

## 四、 状态语法、交互与无障碍契约

1. **统一状态徽章函数**：所有状态徽章渲染（含目标状态、Workbench 个人待办与决策、审核队列、分歧推荐与引文鲜活度）均通过 [app.js](../src/project_compass/web/app.js) 中的安全映射表 `STATUS_BADGE_MAP`（`Object.create(null)`）与 `renderStatusBadge(status, customLabel)` 生成，禁止私自拼写第二套状态类或内联颜色；`read_only` 预览项目下未确认候选绝不展示确认徽章，且个人卡片统一经 `resolveFactStatus(fact)` 只读合成 `team.facts` 与最新 `review_history` 状态。
2. **统一请求与剪贴板边界**：全文件仅允许保留 **`1` 处** 原生 `fetch()` 调用（封装于 `apiFetch(url, options)`），内置 `AbortController` 超时保护与空 `catch` 禁止规则；悬停预取请求携带 `background: true`，避免后台超时污染全局 `#connection-label`。剪贴板复制与资产导出仅在真实 API 或 `execCommand("copy")` 返回 `true` 时报告成功。
3. **证据溯源、层叠次序与弹窗无障碍**：
   - `[e1]` 悬停/聚焦浮窗 `#citation-popover`（`z-index: 100`）配置 `max-height: min(360px, calc(100vh - 24px))`，在渲染前及异步返回后均按锚点与 `currentEvidenceId` 双向钳制视口 `top >= 12px` 与 `left >= 12px`。
   - 四层弹层高度秩序严格为 `#scrim (80) < #handoff-modal (88) < #evidence-drawer (95) < #citation-popover (100)`，确保在交接简报模态框内点击 `[e*]` 时证据抽屉可清晰浮于上方。
   - 交接简报弹窗 `#handoff-modal` 打开时自动聚焦 `#handoff-close-btn`；与 `#evidence-drawer` 分别维护 `state.lastModalTrigger` / `state.lastDrawerTrigger`，`Esc` 每次仅关闭最顶层可见浮层并将焦点归还给对应触发控件；关闭 `#evidence-drawer` 时清空 `#drawer-body`（隔离 `#review-note`）。
   - 未填写负责人姓名前调用采纳/驳回触发明确引导提示，绝不自动伪造或默认填充 Reviewer 身份；内嵌审核按钮对 `Enter`/`Space` 拦截冒泡以免被外层事实卡片劫持。

---

## 五、 自动化门禁基线

每次修改 `src/project_compass/web/` 后，必须全部通过以下校验：

1. CSS 静态门禁：`:root` 外裸 `#hex == 0`、历史遗留青绿配色出现次数 `0`、模糊 `box-shadow == 0`、非 `none` 的 `backdrop-filter == 0`、最小计算字号 `>= 12px`（以 `html { font-size: 16px }` 为准）、禁止 `--orange` 底搭配浅色/白色字体。
2. HTML / JS 静态门禁：裸 `#hex == 0`、内联 `style= == 0`、虚假乐观完成率标语出现次数 `0`、`fetch( == 1`、空 `catch == 0`、JS 查表 DOM ID 与 HTML 全集匹配（`#guidance-extract` 与 `#review-note` 为运行期动态注入控件，由 `?.` 与局部查询安全兜底）。
3. 语法与逻辑契约：`node --check src/project_compass/web/app.js`、全量 `tests/*.cjs`（含 `tests/web_tool_pair_test.cjs` 与 `tests/web_m3_interactions_test.cjs`）及 `python -m unittest discover -s tests -q` 全部退出码 `0`。
