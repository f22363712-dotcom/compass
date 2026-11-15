# 只读结构上下文投影规格

状态：Stage E 已实现；已完成项目绑定、Understand-Anything 外部图显式只读适配、证据关联局部投影、只读网页过程层展示与 current/stale/restart smoke。

## 目的

为 ProjectCompass 增加一个可选的代码结构上下文入口，帮助用户从事实和证据跳到文件、模块、函数或依赖关系。该上下文只用于阅读和导航，不改变 ProjectCompass 的事实账本。

## 输入边界

- 输入可以是 Understand-Anything 的 `.ua/knowledge-graph.json`，也可以是未来其他结构分析器的等价 JSON。
- 适配器只读取文件，不调用外部模型，不要求安装 Understand-Anything。
- 每次导入保存项目路径、来源文件指纹、生成时间、schema 版本和节点/边计数。
- malformed JSON、未知 schema、重复节点 ID、跨项目来源和超出大小限制的输入直接拒绝。

## 读模型

```text
DerivedContext
  project_id
  source_ref
  source_fingerprint
  observed_at
  nodes[]
    id
    kind: file | module | function | class | domain | unknown
    label
    source_ref
    summary
  edges[]
    id
    from_id
    to_id
    kind: imports | calls | contains | belongs_to | unknown
```

所有节点和边都显式标记为 `derived_context`。它们没有 `proposed` 或 `accepted` 事实状态，也不能直接作为 `EvidenceRelation` 的 confirmed 来源。

## 页面投影

- 当前网页在过程层提供项目级结构上下文列表、来源状态、与当前证据关联的节点标记（直接来源 / 关联结构）以及每个节点的结构关系摘要。
- 事实卡仍以证据 ID、作者、时间、当前性和审核状态为主。
- 外部图来源换版或不可用时显示警告，不静默沿用旧摘要。
- 结构上下文仍是导航读模型，不进入个人事实、团队事实或审核队列。

## 不变量

1. 导入结构图不能生成 accepted Team truth。
2. 结构节点不能替代公开 Agent 事件或原始项目材料。
3. 结构边不能自动解释因果、决策理由或任务完成。
4. 删除或换版结构源不会删除证据账本和审核历史。
5. 外部图读取失败只影响结构导航，不影响调查回答和证据查询。

## 已完成切片

1. 离线 JSON fixture 和 schema 校验。
2. 项目绑定与 source fingerprint。
3. 过程层只读节点/边列表和来源状态。
4. stale/unavailable 状态提示。
5. 集成测试验证结构上下文永远不会进入 Team truth。
6. 实际 CLI → HTTP → 网页状态 smoke，覆盖 current、stale 和重启后可见。
7. Understand-Anything（`.ua/knowledge-graph.json`）显式只读适配器、真实项目结构图 `--open --derived-context --web` 离线验收，以及过程层证据关联局部投影与关系可读性展示。

## 下一切片

- 用真实项目已有的结构图 JSON 做一次离线验收。
- 如果外部图字段与本 schema 不一致，只增加显式适配器和映射测试，不把外部图直接写入事实账本。

## 明确不做

- 不复制 Understand-Anything 的多 Agent pipeline。
- 不把图节点数量或语义摘要当成质量指标。
- 不新增自动模型循环，不改变候选事实和负责人审核契约。
