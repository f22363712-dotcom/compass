# Compass 测评体系（Evaluation Framework）

> 建立于 2026-11-10 · 目的：**给迭代排优先级、给方向做抉择**，而不是发布卡口，也不是营销素材。

---

## 一、这套测评到底回答什么问题

Compass 是个"证据台账"，它的价值主张有三句话：

1. **不编**——每条事实都必须挂在真实原文上；
2. **不越权**——没有人类确认，任何机制都不能把提议变成团队真理；
3. **不失忆**——上次会话说过的话，这次还找得到。

因此评测不问"Compass 好不好看"，只问三件事：

| 问题 | 对应层 | 一句话 |
|---|---|---|
| 它有没有把材料**如实**收进来并分好归属？ | L1 结构层 | 摄入、归属、两层真相 |
| 它有没有把材料**抽成**人认可的事实，并拒掉不该收的？ | L2 抽取层 | 准召 + 抽取契约 |
| 人或 Agent 能不能**问得到**答案？ | L3 交接层 | 检索可达性 + 答案质量 |
| 改一个核心函数，**谁会碎**？ | L4 契约层 | 调用链追踪 + 索引新鲜度 |
| 它会不会被**骗**？ | L5 对抗层 | 准入门抗攻击 + 越权拦截 |

五层里，L1/L4/L5 完全不需要模型，L2/L3 可以是模型轨也可以是确定性轨。这就是"双轨并行"的含义：**同一套金标准、同一套打分器**，只是换掉被测对象。

---

## 二、方法学：为什么这些数字可信

测评系统最容易自欺的地方，是让**出题的人和打分的人共用同一个模型**。所以这里有几条硬规矩：

### 2.1 金标准独立于被测系统

`tests/fixtures/benchmark/easy-course-picker/gold.json` 里的 19 条事实和 14 道题，是在**没有跑过 Compass 抽取**的前提下，根据项目自己的 `project_context.md` 与 `tasks/todo.md` 写出来的，然后才锚定回 `conversation.md` 里真正记录该决策的条目。

锚定这一步由 `eval/builder.py` 完成，并且**失败得很响**：

- 锚点找不到原文 → 构建失败；
- 锚点对应的原文被去标识化改掉了 → 构建失败；
- `required_terms` 在锚定原文里不存在 → 构建失败。

也就是说：**金标准不可能悄悄漂移到"Compass 恰好能产出什么"上**。

### 2.2 打分完全确定，与模型无关

`eval/scorers.py` 里的规则只有四种：必需词是否覆盖、禁用词是否出现、引文是否与金标准共享锚点、答案是否引用了不存在的证据。没有任何一处用"像不像人话"来判分。

一条事实只允许认领**一条**金标准（`score_extraction` 的一对一贪心分配），所以一次侥幸命中撑不起多个指标。

### 2.3 模型可以被测，但模型不参与判分

模型只出现在两个位置：**被测的抽取器**和**被测的回答器**。裁判永远是规则。

> 如果要用 LLM 做裁判，裁判模型必须与被测模型不同——这一条留给后续的人工校准环节（见 §六）。

### 2.4 硬指标 / 软指标分明

每个指标带 `hard` 标记：

- **硬指标**（`hard=True`）= 产品红线，不通过就是回归，直接卡住 CI；
- **软指标**（`hard=False`）= 质量水位，只记录和排名，用来排迭代优先级。

所以"整体 PASS"的意思是"没有踩红线"，**不是**"效果很好"。质量水位看的是软指标的数字——那些数字现在很难看，这正是本轮迭代要解决的问题。

---

## 三、五层是怎么测的

### L1 结构层 —— 摄入、归属与两层真相

| 指标 | 含义 | 硬性 |
|---|---|---|
| `ingest_completeness` | 每条证据都写进了存储 | 是 |
| `member_attribution` | 每条证据都能定位到成员 | 是 |
| `session_consistency` | 会话 ID 与成员一致 | 是 |
| `evidence_owner` | 每条证据出现在其归属成员的视图里 | 是 |
| `fact_isolation` | 每条事实只出现在作者本人的个人视图里 | 是 |
| `no_unconfirmed_promotion` | 没有未经人工确认的事实晋升为团队事实 | 是 |
| `team_view_coverage` | 团队视图覆盖全部候选事实 | 是 |
| `conflict_visibility` | 冲突主张在团队视图中两侧都保留 | 是 |

注意 `evidence_owner` 的口径：证据可以被**别人引用**（B 引用 A 的材料是可以的），所以检查的不是"只出现一次"，而是"出现在对的那个视图里"。

### L2 抽取层 —— 事实准召与抽取契约

**契约指标（产品自己的）**：`contract_accept_rate`、`evidence_attachment`、`member_attribution`、`conflict_preservation`——全部由 `candidate_extraction.validate_candidates` 与 `fact_engine.derive_facts` 实测，不经过任何模型。

**质量指标（被测对象的）**：`extraction_precision`、`extraction_recall`、`extraction_f1`——把抽出来的事实与金标准对撞。

把这两类指标分开是刻意的：**弱抽取器和坏契约是两个不同的问题，修法完全不同**。契约坏了要改产品，抽取器弱要换模型或改提示。

### L3 交接层 —— 检索可达性与答案质量

| 指标 | 含义 |
|---|---|
| `evidence_coverage` | 金标准证据**至少被一条事实引用过**的比例（抽取覆盖） |
| `retrieval_hit_rate` | 金标准证据排进前 5 的比例（排序命中） |
| `retrieval_mrr` | 命中证据的平均倒数排名 |
| `answer_accuracy` / `_team` / `_personal` | 答案是否覆盖全部必需词、不含禁用词 |
| `evidence_validity` | 答案没有引用不存在的证据 |

`evidence_coverage` 是后加的，因为没有它就分不清"检索没找到"和"抽取根本没抽"——这两个失败必须开不同的药方。

### L4 契约层 —— 调用链追踪与索引新鲜度

依赖 `project_compass/code_index.py`（本轮新增，见 §五）：用标准库 `ast` 产出一张 `understand-anything` 结构图，再交给产品已有的 `derived_context` 读。

| 指标 | 含义 |
|---|---|
| `symbol_locatable` | 受测符号都能在索引里定位 |
| `caller_trace_recall` | 预期调用方被追到的比例 |
| `risk_reported` | 有调用方的符号都给出了契约风险 |

### L5 对抗层 —— 准入门抗攻击与越权拦截

直接拿产品自己的 `validate_candidates` 当靶子，8 条攻击覆盖：伪造引文、引文张冠李戴、指向不存在的来源、空/超长主题键、非法事实类型、引文落在窗口外、单批候选数超限，以及**源材料内嵌越权指令**。

最后一条最关键：那段文字确实存在于原文，所以准入门**应该**放行；但它只能变成 `proposed`，绝不能自动变成 `accepted`。这一条直接对应产品红线。

---

## 四、怎么跑

```bash
# 确定性轨（不调模型，可进 CI）
PYTHONPATH=src python -m project_compass.eval run \
    --corpus tests/fixtures/benchmark/easy-course-picker

# 产出报告文件
PYTHONPATH=src python -m project_compass.eval run \
    --corpus tests/fixtures/benchmark/easy-course-picker \
    --out tests/fixtures/benchmark/baseline_report.json \
    --markdown docs/EVAL_REPORT.md

# 与基线对比
PYTHONPATH=src python -m project_compass.eval run \
    --corpus tests/fixtures/benchmark/easy-course-picker \
    --baseline tests/fixtures/benchmark/baseline_report.json

# 模型轨：接入外部 harness
PYTHONPATH=src python -m project_compass.eval run \
    --corpus tests/fixtures/benchmark/easy-course-picker --harness claude
```

### Harness 接口（模型无关）

模型轨不绑定任何一家。约定只有一条：**一个进程，从 stdin 读一段 JSON，往 stdout 写一段 JSON**。

```jsonc
// 请求
{"task": "extract", "sources": [{"id": "...", "kind": "...", "content": "..."}]}
{"task": "answer", "question": "...", "context": {"facts": [...], "evidence": [...]}}

// 响应
{"candidates": [{"source_id": "...", "kind": "decision", "subject_key": "...", "quote": "..."}]}
{"answer": "..."}
```

Claude、Codex、DeepSeek、openclaw、PI…… 各自只需要一个薄 wrapper，然后**完全等价地**参与同一套打分。这就是 `eval/harness.py` 和 `eval/runners.py` 存在的意义。

产品侧的 agent 接口是 **MCP 客户端**：被测 agent 拿的是一个由语料支撑的 MCP server，而不是直接读文件。

### 重建语料（需要真实项目材料，本地执行）

```bash
PYTHONPATH=src python -m project_compass.eval build \
    --spec tests/fixtures/benchmark/local-specs/easy_course_picker.json \
    --source-root <真实项目目录> \
    --out tests/fixtures/benchmark/easy-course-picker
```

`local-specs/` 已被 `.gitignore` 排除，因为它含真实人名；去标识化在构建时完成，**仓库里留下的语料不含任何个人数据**。

---

## 五、本轮补上的一块：结构图生产者

Compass 之前能**读** `understand-anything` 结构图（`derived_context`），但没有任何东西能**产出**它——契约层因此没有输入。

新增 `src/project_compass/code_index.py`：只用标准库 `ast`，无新增依赖、无索引服务、无文件监听，产出 `derived_context.from_understand_anything` 可以直接吃的结构图。

它刻意保守：**调用目标在项目内不唯一时就不建边**。对契约风险分析来说，错的边比缺的边更糟。

> 本轮修掉的两个真实 bug：嵌套函数（闭包）产生的调用边因为没有对应节点而被丢弃，导致 `caller_trace_recall` 漏掉 `codex_extractor.py`；以及超长限定名让边 id 超过读取方的 256 字符上限。

---

## 六、与交接文档四大指标组的对应关系

`docs/HANDOFF_TO_MINIMAX_EVAL.md` 提出过四组指标。诚实对照：

| 交接文档的指标组 | 本体系的位置 | 状态 |
|---|---|---|
| 1. 事实确证与越权拦截 | **L1 + L5** | 已覆盖（L5 是本轮新增） |
| 2. 引文精准度与流式对齐 | L2 `contract_accept_rate` 覆盖"精准"；"流式"由 `tests/test_streaming_quote_validation.py` 覆盖 | **部分**：流式对齐尚未做成测评层 |
| 3. 冲突裁决与沙箱投机 | L1 `conflict_visibility` 覆盖冲突可见性；沙箱由 `tests/test_superagent_speculative_execution.py` 覆盖 | **部分**：沙箱准确率尚未做成测评层 |
| 4. AST 契约破坏检出 | **L4** | 已覆盖 |

**仍然开放的缺口**（诚实记录，不掩饰）：

- **流式对齐**没有进入测评层，只在单元测试里；
- **沙箱投机准确率**同理；
- **L2 的质量水位依赖参考抽取器**。当前用的是通用规则抽取器（`reference-rules-v1`），它是一个**刻意保守的替身**，不是产品默认路径——产品默认走 `codex_extractor`。所以 L2 的 precision/recall 是"这套金标准对通用规则的难度"，不是"Compass 在最优抽取器下的真实水平"。接上模型轨后这两个数会变，**那是预期的，不是不公平**；
- **人工校准尚未做**（见 §七）；
- **语料只有一个项目**。跨项目泛化性未验证。

---

## 七、一次性人工校准协议（待执行）

规则打分能测"有没有覆盖必需词"，测不了"这个答案对不对、有没有用"。一次性人工校准的方案：

**样本**：14 道题 × 3 个回答器（产品自答、模型轨、朴素检索基线）= 42 份回答，打乱顺序、去掉来源标识。

**评审**：对每份回答打三个分——`正确` / `部分正确` / `错误`，外加一个 `是否答非所问`。评审者不看金标准的必需词（避免锚定），只看问题和回答。

**用途**：

1. 校准规则打分器：算出规则判定的准确率/召回率，得到"规则判定 ↔ 人工判定"的混淆矩阵；
2. 若偏差大，按人工判定**修规则**（比如补必需词表），而不是把模型塞进判分环节；
3. 之后规则判分器就长期作为代理，人工只在规则变化时抽查。

**产出**：一张评分表 + 混淆矩阵 + 规则修订记录，存 `docs/EVAL_CALIBRATION_*.md`。

**注意**：人工校准**一次就够**，而且必须由人做——它是给规则打分器定标，不是常态化流程。

---

## 八、扩展方式

| 想做什么 | 怎么做 |
|---|---|
| 加一个项目语料 | 写 spec（`name` / `sources` / `facts` / `questions` / `member_aliases`），跑 `build` |
| 加一条抽取攻击 | 往 `tests/fixtures/benchmark/adversarial_cases.json` 加一条 case |
| 加一个契约期望 | 往 `tests/fixtures/benchmark/contract_chains.json` 加一条 case |
| 接一个新的 harness | 写一个 stdin/stdout 的 JSON wrapper，然后 `--harness-command` |
| 加一个新维度 | 在 `eval/layers/` 加一个层，导出到 `layers/__init__.py`，在 `__main__.py` 注册 |

新增层必须同时补 `tests/test_eval_benchmark.py` 里的测试——**测评系统自己的测试，比被测系统的测试更容易被放松**。

---

## 九、相关文件

```
src/project_compass/eval/
├── __main__.py            # CLI：build / run
├── build_cli.py           # 语料构建入口
├── builder.py             # spec → 去标识化语料 + 金标准
├── corpus.py              # 语料格式 + 去标识化
├── gold.py                # 金标准格式
├── adapters.py            # 真实协作日志 → 证据事件
├── scorers.py             # 确定性打分
├── runners.py             # 抽取器 / 回答器适配
├── harness.py             # 外部 harness 的 JSON wrapper
├── report.py              # 报告与基线对比
└── layers/                # L1~L5

src/project_compass/code_index.py   # 结构图生产者（ast，无新增依赖）

tests/fixtures/benchmark/
├── easy-course-picker/     # 去标识化语料 + 金标准（已提交）
├── adversarial/            # 对抗语料（已提交）
├── adversarial_cases.json  # 攻击用例（已提交）
├── contract_chains.json    # 契约期望（已提交）
└── baseline_report.json    # 基线快照（已提交）

tests/test_eval_benchmark.py         # 测评系统自身的测试
tests/test_code_index.py             # 结构图生产者的测试
docs/EVAL_REPORT.md                  # 基线报告
docs/COMPASS_ITERATION_PLAN.md       # 迭代优先级（由本轮结果推出）
docs/CODEGRAPH_BORROWING.md          # Code Graph 借鉴分析
```
