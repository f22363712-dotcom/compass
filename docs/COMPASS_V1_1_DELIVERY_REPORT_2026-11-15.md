# Project Compass v1.1 交付与验收总结报告（2026-11-15）

> 本文档依据本仓库源码、配置文件与实跑命令输出编写，所有测试通过率、评测指标与真实浏览器核验结果均为本轮最终代码改动后的实测结果。

---

## 一、核心交付概览

### 1. 本机服务重启、零配置 `compass` MCP 自举与实时联动
- **旧实例清理与现仓看板上线**：停掉旧仓端口 `8792` 残余进程（PID `39632`），以当前开源主仓（`main` 分支，远程 `origin` 为 `f22363712-dotcom/compass`）通过 `--scan . --extract-docs --with-code-index --web --port 8787` 启动本地看板服务。
  - 首轮启动即加载本仓项目证据、提取文档候选与 **200 个 AST 代码结构节点**（`derived_context.enabled = true`，存储隔离于 `.project-memory/` 工作区内，零污染目标仓根目录）。
- **editable 安装与 Antigravity zero-config MCP 配置**：
  - 执行 editable 安装，并写入宿主机 `<USER_HOME>/.gemini/antigravity/mcp_config.json`，配置 zero-config `compass` stdio MCP 服务（`--project-path <REPO_ROOT> --member-id fang --session-id antigravity-local`）。
- **真实 stdio MCP 握手与热同步实测**：
  - 通过子进程 stdio JSON-RPC 实跑 `initialize` -> `notifications/initialized` -> `tools/list`（`project_context`、`append_evidence`、`query_state`、`propose_fact`）-> `project_context` -> `query_state` -> `append_evidence` -> `propose_fact`。
  - 写入完成后未重启 `8787` 看板进程，直接访问 `GET http://127.0.0.1:8787/api/state` 即可在 `personal.fang.facts` 与 `team.facts` 中立即读取到新提案。

---

### 2. Solo 个人工作台纵深增强
1. **可读会话行动轨迹流（`#personal-activity`）**：
   - 新增 [activity_stream.py](../src/project_compass/activity_stream.py)，过滤文档类快照（`DOCUMENT_RECORD_KINDS`）、配对 `tool_call` / `tool_result`、按中文行动类型分类，并折叠相邻健康的重复工具调用。
2. **首屏双区域拆分与 Solo 去团队摩擦**：
   - 个人主工作区首屏拆分为 **「待拍板思路 & 未验证前提」** 与 **`#solo-baseline-surface`（已定案项目基准）**，彻底清理 Solo 模式文案中残留的 `"团队共识"` 与 `"负责人核对"`。
   - 移除 Solo 模式阻塞确认弹窗，改为抽屉内嵌 **一次性个人署名表单**（`data-inline-review`）；首轮填妥署名（如 `fang`）后即记忆，后续定案操作零弹窗直通，同时保留团队路线对空署名时 `"请先填写负责人姓名"` 的护栏。
3. **随手记轻量入口（`POST /api/notes`）**：
   - 新增 [quick_notes.py](../src/project_compass/quick_notes.py) 与页面顶部单行表单 `#quick-note-form`，支持快速记录 `决策 / 前提 / 待办 / 目标`（2000 字符上限、敏感凭据拦截、`client_nonce` 幂等重放防护及同源 JSON POST 校验）。
4. **网页端接入项目支持文档候选提取与 AST 索引**：
   - 新增 [onboarding.py](../src/project_compass/onboarding.py) 并扩展 [project_scan_job.py](../src/project_compass/project_scan_job.py)，前端接入面板提供 `#scan-extract-docs` 与 `#scan-code-index` 勾选项，扫描阶段分步回报进度；语法残缺的 Python 文件（如 `broken.py`）走 `strict_syntax=False` 降级容错不中断整库扫描，产物隔离存放在 Compass 工作区 `code-index.json` 中。

---

### 3. 「清单台账 | 思维脑图」双视图认知设计与权衡
- **为什么保留“清单 + 脑图”双视图**：
  - **视觉空间锚定与降低工作记忆负荷**：线性清单在逐条审校或检索证据时最精确，但条目增多后难以一眼看清“核心目标—关键路线—分支决策—未解决前提—待办任务—对应代码模块”的全局层次。桌面端（`>= 960px`）采用**从左到右的正交分层脑图**（左侧竖直居中锁定「核心目标锚点」，右侧展开决策与前提卡片，用绿/橙/灰边框语义直观区分「已定案 / 待拍板 / 已舍弃・已暂缓」，下挂任务叶节点与关联代码模块），利用空间组块帮助人脑快速定位“当前走在哪一条思路、哪几步还没拍板”；移动端（`<= 780px`）自动收敛为单列堆叠结构以防横向溢出。
  - **可导出传播的脑图载体**：后端 [cognitive_export.py](../src/project_compass/cognitive_export.py) 同步提供 `export_mindmap` 与前端 `#handoff-export-mindmap-btn`，可直接导出带证据编号对照表的标准 Mermaid `mindmap` Markdown 文档。
  - **适用边界**：需要批量审计、多维筛选或长文本精读时切换回 **`[清单台账]`**，需要全局复盘、向他人讲清决策脉络或快速找待拍板分叉时切换到 **`[思维脑图]`**，两者共享同一份状态与定案/溯源交互。

---

### 4. 中文化、命名规范与跨进程持久化加固
- 将前端状态徽标（`待核对` / `已确认` / `冲突` 等）及扫描阶段文案全面中文化，清理旧版 `project-compass-*` 导出文件名前缀为 `compass-*`。
- 在 [evidence_filters.py](../src/project_compass/evidence_filters.py) 中规范化 Windows `\\?\` 与大小写路径锁键并实现线程重入安全的 `interprocess_file_lock`；在 [project_workspace.py](../src/project_compass/project_workspace.py) 中补充只增合并 `merge_and_save_review_state` 与默认保持向后兼容的 `save_review_state(..., merge_existing=False)`。
- 修正 [HANDOFF.md](../HANDOFF.md) 顶部旧分支标注，更新 [DECISIONS.md](../DECISIONS.md)，并将 `node --check src/project_compass/web/app.js` 与 `tests/*_test.cjs` 全量循环纳入 [.github/workflows/ci.yml](../.github/workflows/ci.yml)。

---

## 二、验收与实跑评测结果

| 验证项目 | 运行命令 / 手段 | 实测结果 |
| :--- | :--- | :--- |
| 前端语法与契约测试（本地时区） | `node --check src/project_compass/web/app.js` + 遍历执行 `tests/*_test.cjs` | **17/17 全部通过**（exit code 0） |
| 前端跨时区测试（`TZ=UTC`） | `$env:TZ='UTC'` 下遍历执行全部 `tests/*_test.cjs` | **17/17 全部通过**（exit code 0） |
| 全量 Python 编译与单元测试 | `$env:PYTHONPATH='src'; python -m compileall -q src tests; python -m unittest discover -s tests` | **548 项测试 75.841s 全部 OK**（0 failures, 0 errors） |
| 五层评测基准 | `python -m project_compass.eval run --corpus tests/fixtures/benchmark/easy-course-picker --baseline tests/fixtures/benchmark/baseline_report.json` | **`red_line_gate: PASS`，`overall: PASS`**（L1–L5 全部 PASS，L4 `caller_trace_recall = 1.0000` [15/15]，L5 `attack_rejection_rate = 1.0000` [8/8]） |
| 本机 `8787` 看板 + 真实 MCP 热同步 | 启动实时进程后运行 stdio `mcp_server` 探针调用 `propose_fact` | **写入后无需重启立即在 `/api/state` 个人与团队视图可见** |
| 真实浏览器 UI 与响应式走查 | `browser` 子智能体访问 `http://127.0.0.1:8787/`（`1366x768` 与 `390x844`） | **0 控制台报错**；验证 Solo 文案隔离、随手记提交、左→右正交脑图渲染、抽屉一次性内嵌署名 + 二次免弹框定案、Team 空署名拦截、桌面/移动端 `scrollWidth <= innerWidth` 均成立 |
