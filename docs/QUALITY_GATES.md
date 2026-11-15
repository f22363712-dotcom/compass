# ProjectCompass 阶段质量门

状态：当前开发规范，2026-10-31

每个阶段和每个独立板块都要经过代码审查和功能审查。功能完成不能只由单元测试证明；需要一条从真实入口到用户可见结果的端到端路径。

## 每个板块的固定门

### 1. 契约审查

检查输入、输出、身份、持久化字段和失败状态是否写入当前路线。发现字段重复、边界含糊或状态无法追溯时，先停在 `HOLD`。

### 2. 代码审查

使用 Ponytail review 规则检查：

- 正确性和异常路径；
- 信任边界、身份绑定和密钥处理；
- 并发、重复提交和重启行为；
- 是否有关键逻辑没有测试；
- 是否可以复用现有代码或删除多余抽象。

每个发现必须包含具体输入、错误结果、最小修复和不修复的代价。没有具体失败案例的风格意见不进入审查结论。

### 3. 功能审查

从用户动作检查可见结果：

- 记录是否进入个人视图；
- 团队事实是否仍由负责人确认；
- 证据 ID 是否能打开原文；
- 冲突和历史是否保留；
- 失败时是否显示缺口，而不是生成确定结论。

### 4. 端到端审查

端到端测试必须跨越真实边界，至少包含：

1. 启动真实入口：网页 HTTP、MCP stdio、Codex watcher 或真实扫描命令；
2. 输入公开事件或真实项目材料；
3. 经过协议校验、身份绑定、持久化和事实投影；
4. 通过另一个真实读取入口读取状态；
5. 验证用户可见结果、磁盘状态和重复执行结果；
6. 记录敏感内容、隐藏推理、失败请求和未覆盖范围。

夹具测试可以验证结构和边界，不能代替真实入口验收。真实验收可以使用隔离工作区，不能把测试材料写入正式用户账本。

### 5. 交付审查

只有以下条件同时满足，板块才标记 `PASS`：

- 代码审查没有 Must fix；
- 功能审查的用户路径通过；
- 端到端路径有可复现命令和结果；
- 全套回归通过；
- 隐私、来源和许可证边界已记录。

否则标记 `HOLD`，列出阻断项、证据和最短复验动作。

## 测试层级和报告格式

| 层级 | 目的 | 典型命令 | 证明内容 |
|---|---|---|---|
| 单元 | 纯函数、模型和边界 | `python -m unittest tests.test_plugin_protocol` | 输入校验和序列化正确 |
| 组件 | HTTP、MCP、持久化边界 | `python -m unittest tests.test_local_plugin tests.test_mcp_server` | 认证、路由和状态写入正确 |
| 工作流 | 多模块真实组合 | `python -m unittest tests.test_codex_plugin_bridge tests.test_codex_watch` | rollout 到适配器的链路正确 |
| 真实端到端 | 真实 Codex/本地服务 | `project-compass-codex-watch --once` | 真实消息进入真实状态并可重读 |
| 回归 | 防止比赛版能力退化 | `python -m unittest discover -s tests` | 所有已确认能力保持通过 |

每次报告使用以下字段：

```text
入口：
输入：
状态存储：
用户可见结果：
重复执行：
测试命令与版本：
结果：PASS / HOLD
未覆盖边界：
```

## 当前阶段记录

### 阶段 A：插件协议、MCP 和 Codex 持续入口

#### A1：协议与本地适配器

- 代码审查：Ponytail 检查通过，无 Must fix；watcher 的整文件重读已标注 shortcut。
- 功能审查：协议、认证、项目绑定、公开事件、候选事实和错误脱敏通过。
- 当前状态：`PASS`。

#### A2：宿主级插件集成

- 当前状态：`PASS`。
- 已通过：真实 MCP client 全工具链、watcher 增量 tick、重启后 `/api/state` 可见、plugin manifest/config、`codex mcp add/list` 发现。
- 已补验：交互式 `on-request` 下批准 `project_context`，返回项目 ID 和状态版本。
- 已通过：缺失 token、未知工具、跨项目和跨来源拒绝路径。
- 证据：[A2_HOST_SMOKE_2026-10-31.md](archive/reviews/A2_HOST_SMOKE_2026-10-31.md)、[RECONFIRM_AFTER_EVIDENCE_REVIEW_2026-11-02.md](archive/reviews/RECONFIRM_AFTER_EVIDENCE_REVIEW_2026-11-02.md)、`tests.test_mcp_server`、`tests.test_local_plugin`、`tests.test_agent_http`。

审查证据：`577005a` 的入口、适配器、协议、测试和 README 已阅读；阶段 A 当时关键测试为 `5/5 OK`（历史回归基线快照为 `392 tests`；当前全量回归请实时运行 `$env:PYTHONPATH='src'; python -m unittest discover -s tests -q`，基准已超过 `515+` 项）。独立审查和外部资料核对见 [EXTERNAL_REVIEW_2026-10-31.md](archive/reviews/EXTERNAL_REVIEW_2026-10-31.md)。

## 阶段路线

- 阶段 A：插件协议和持续入口，已通过；
- 阶段 B：网页项目入口，每个子板分别审查注册列表、切换、扫描向导和重启恢复；
- 阶段 C：个人视图持续更新，每个子板分别审查增量事件、事实候选、来源和重复写入；
- 阶段 D：团队事实治理，每个子板分别审查冲突、负责人确认和历史恢复；
- 阶段 E：调查和长期记忆，每个子板分别审查分层阅读、回填、当前性和导出。

阶段之间不能用上一阶段的测试结果代替下一阶段的功能审查。每次阶段结束都要更新本文件的阶段记录。
