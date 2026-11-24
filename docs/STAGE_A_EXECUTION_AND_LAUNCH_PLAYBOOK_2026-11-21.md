# Compass Stage A 整改台账与小红书 / B 站发布实操手册（2026-11-21）

> 本文档为 Stage A（中文种子公测版）的唯一执行总账，覆盖：**GitHub 组织命名建议与迁移步骤**、**三块核心体验整改清单**、**小红书 + B 站真机发布分镜与懒人安装卡片**，以及 **首批 10–20 名种子用户闭环 checklist**。

---

## 一、GitHub 组织命名核查结果与 1 分钟迁移步骤

> 实查结果：纯词 `github.com/compass`（8 个仓库）和 `github.com/project-compass`（4 个仓库）均已被占用；Atlassian Compass（软件目录）、MongoDB Compass（数据库客户端）也属同名高知名度产品。**使用差异化命名空间 + 独立组织可 100% 避开重名冲突与个人 Gmail 前缀暴露。**

| 候选名称 | GitHub 组织主页 | PyPI 包名 | 推荐度 | 说明 |
| :--- | :--- | :--- | :---: | :--- |
| **`get-compass`** | `github.com/get-compass/compass`（未占用） | `get-compass`（未占用） | **强烈推荐** | 参照 `getzep/graphiti` 顶级开源命名范式，短、好记、海内外均直观，且包名可直接复用 |
| `compass-board` | `github.com/compass-board`（未占用） | `compass-board`（未占用） | 推荐 | 强心智突出“看板”，搜索 `compass board` 几乎零碰撞 |
| `agent-compass` | `github.com/agent-compass`（未占用） | `agent-compass`（未占用） | 备选 | 紧贴 AI Agent 赛道，但在 Cursor/Claude 搜索时略泛 |
| `vibe-compass` | `github.com/vibe-compass`（未占用） | `vibe-compass`（未占用） | 备选 | 非常贴合 Vibe Coding 群体，稍限制后续团队场景延展 |
| `compass-kit` | `github.com/compass-kit`（未占用） | `compass-kit`（未占用） | 备选 | 偏开发者工具箱风格 |

### 1 分钟免费新建组织 & 无损迁移步骤
1. 打开 GitHub 右上角 **`+`** → **`New organization`** → 选择底部 **`Create a free organization`**。
2. Organization name 填 **`get-compass`**（若更喜欢也可填上面任一 `FREE` 名称），邮箱填你的常用邮箱，用途选个人开源项目，直接提交。
3. 回到原仓库 `https://github.com/f22363712-dotcom/compass/settings` 最底部 Danger Zone → 点击 **`Transfer ownership`** → 目标输入刚建好的 **`get-compass`**。
4. 迁移后 GitHub 会永久把旧地址自动 301 跳转至新地址；本地终端只需跑一句：`git remote set-url origin https://github.com/get-compass/compass.git`（后续正式发 PyPI 与上 MCP Registry 时同步把项目配置中的 `io.github.f22363712-dotcom/...` 替换为新组织名即可）。

---

## 二、Stage A 三块整改执行清单（已获批准并同步落地）

### 块 ①：治好“Agent 提示看不懂 + 临时问答堆满 21 条 + 黑话满屏”
- **`decision_graph.py`**：过滤 `ask_question` 中一次性的执行/调试操作选项（如重试、切片注入、关弹窗、批准动工、切换只测等），除非带有明确长期决策信号，只记行动轨迹不再污染“待确认决策”。
- **`cli.py` + `text_summary.py` + `dashboard.py` + `web/app.js`**：为「当前下一步」新增 **`✓ 标记已完成`**，完成后不再死咬过期旧计划；超过 72 小时的陈年待定自动折叠并支持一键清理。
- **`agent_hints.py`**：
  - 剔除已否决和已完成记录；取消危险的 `✓ 定案最新项` 一键操作，改为安全的 `查看待确认`；
  - 快照改取**最新**已定案/待确认（而非最老 4 条）并补充日期与距今天数；
  - 提示词明确要求日常大白话，且旧“下一步”明显早于近期进展时严禁误报为偏航。
- **全界面与 `index.html` / `app.js` / `completion_gate.py`**：彻底替换「证据脊柱」「实时正交脑图」「收敛分支」「定锚/锚点」「证伪」「未填坑位」「优先施工队列」「投机校验标记」「来源换版」「语义提示」等技术黑话，去除写死的旧版本号。

### 块 ②：治好“图二光说去看板却没链接也没打开”与跨项目暗坑
- **`completion_gate.py` + `mcp_server.py`**：当 `verify_completion` / `record_note` / `project_context` 生成需要用户查看看板的提醒时，按宿主自动附带可点击入口（Antigravity 带 `[打开 Compass 实时掌控台](sidecar://compass/compass_board/)`，已启用本地守护进程带 `http://127.0.0.1:...`）；不带入口时绝不空喊“请点看板”。
- **`mcp_setup.py`**：更新 `AGENTS.md` 守则模板；`install_agent_rules` 自动安全幂等追加 `.project-memory/` 到 `.gitignore` 防误传隐私；修复 `--doctor` 时间戳并增补 `node` / `compass-mcp` / Sidecar 安装状态检测；`mcp.json` 改为安全零配置模式。
- **`mcp_server.py` + `sidecar_backend.py` + `web_server.py` + `web/app.js`**：兼容 `file:///` URI、修掉切区首屏 `read_only` 死锁、失效目录优雅退避、跨区加载报错与窗口串台显式提示而非静默吞错。

### 块 ③：修好陌生人 60 秒上手、小白演示剧本与门面
- **`cli.py` + `sample_data.py`**：修复非源码环境下 `--sample --web` 找不到 `examples/` 崩溃的问题；新增「个人播客笔记与剪藏小工具」生活化中文演示剧本与 `--demo` 一键启动命令（支持自动打开默认浏览器）。
- **打包与市场契约**：统一升级版本至 `1.6.1`，补充 `pyproject.toml` 项目链接与分类，升级 `server.json` 至 2026 Schema、修正 `smithery.yaml` JS 函数写法，并新增 `.github/ISSUE_TEMPLATE/` 零门槛反馈模板。
- **`README.md`**：精简首屏为“1 句痛点定位 + 分屏实拍入口 + 2 行命令 + 懒人 AI 代装提示词”；默认隐藏复杂基准表和团队多端口配置。

---

## 三、小红书 + B 站首发实操手册

### 1. 「复制一句话让你的 AI 帮你装好」懒人提示词（可直接放正文/置顶/README）
```text
请帮我安装并配置开源项目 Compass（本地 AI 编程记忆护栏与实时思维脑图）：
1. 用 pip 或 uvx 安装最新版本并验证 `compass-setup --doctor`；
2. 根据当前编辑器运行 `compass-setup --client <antigravity|cursor|claude|codex|hermes> --zero-config --write --init-rules`；
3. 检查目标项目的 `.gitignore` 是否已排除 `.project-memory/`；
4. 安装完成后提示我是否需要重启编辑器，并帮我打开一次试用。
```

### 2. 小红书发布手册（主打：非科班 Vibe Coder / AI 副业开发者）
- **核心禁忌**：**正文与评论区严禁直接放外部链接或二维码**（防平台限流/折叠），引导“搜项目名或看个人主页简介/GitHub 用户名”。
- **推荐封面标题（三选一）**：
  - 《用 AI 写代码最崩溃的 3 个瞬间，我做了个免费工具治好了》
  - 《AI 总是擅自改烂代码、换窗口就失忆？给它装个外接大脑》
  - 《别再和 AI 鸡同鸭讲了！左边聊天、右边实时长出思维导图》
- **6 张图文分镜**：
  1. **P1 封面痛点图**：黑红对比字 + 真实分屏界面局部特写。
  2. **P2 翻车共鸣 1（随口一问被当圣旨）**：刚问“要不要加个功能”，AI 直接连改 6 个文件 → 右边对照 Compass 把「待确认想法」和「已拍板要求」隔开。
  3. **P3 翻车共鸣 2（换个对话彻底失忆 & 重复踩废案）**：之前否决过的方案过两天又被 AI 端出来 → 展示脑图里醒目的红叉淘汰原因 + 待核实假设提醒。
  4. **P4 怎么解决（零依赖纯本地）**：强调不用买新会员、不传云端代码、1 句话让手头 AI 帮装好。
  5. **P5 真实播客小工具演示截图**：全屏看清大白话界面（目标 / 当前下一步 / 方案对比 / 思维脑图）。
  6. **P6 结尾互动页**：配图 + 引导“想试的姐妹/兄弟在评论区扣你用的工具（Cursor / Antigravity / Claude Code），我发对应的一句话安装口令；有报错直接甩截图我当天改”。

### 3. B 站首发视频分镜（2 分 30 秒，真机实操录屏胜过一切特效）
- **标题建议**：`【开源】写给被 AI 写失控的人：左聊代码、右长脑图的本地记忆护栏（纯Python零依赖）`
- **分段脚本**：
  - **0:00–0:20 痛点开场（实机录屏，不放空洞 PPT）**：直接演示对话写项目时 AI 忘了旧决策、重提踩坑方案的真实尴尬。
  - **0:20–0:55 核心体验 A：左聊右长脑图**：开着编辑器与右侧面板，口头定一个目标和方案对比，现场看到右侧立刻长出分支和依据原文。
  - **0:55–1:35 核心体验 B：红灯防跑偏与一键结案**：演示故意重提被否决路线时面板亮出踩坑提醒、干完一件事点「✓ 标记已完成」交接下一步。
  - **1:35–2:10 小白怎么用（真机敲一遍）**：现场执行 `compass --demo` 10 秒看懂样例，再贴出“让 AI 帮你自动装”口令。
  - **2:10–2:30 坦诚边界与征集试用**：直说“目前主要支持 Python 结构分析，还是开源早期，欢迎前 20 位朋友进评论区/提 Issue 挑刺”。
- **简介置顶**：放 GitHub 仓库地址、`compass --demo` 一行试玩命令、支持客户端清单（Cursor / Claude Code / Codex / Antigravity / Hermes）。

---

## 四、首批 10–20 名种子用户反馈闭环 Checklist
- [ ] **准备环境**：先跑通 `compass --demo` 和干净环境 `uvx`/`pip` 安装再对外发帖。
- [ ] **盯 3 个真实指标（不焦虑 Star）**：① 多少陌生人实际装上了；② 哪句界面词还看不懂 / 哪步安装卡住了；③ 第 7 天谁还在打开看脑图。
- [ ] **24 小时快修 + 复盘**：收到真实报错或术语吐槽当天修掉，在原评论区回复确认，积攒 3–5 项真实改进后即可启动 **Stage B（中英双语界面 + GitHub Pages 在线沙盒 + 海外 MCP 市场与 Reddit / X / Show HN）**。
