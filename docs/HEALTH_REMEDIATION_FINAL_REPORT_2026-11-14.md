# Project Compass 健康度审计整改、双 A/B 盲审与 M0–M4 终局交付报告（2026-11-14）

> **分支**：`codex/evidence-links`（起始基线 `f5b84ec`，按用户指令仅限本地显式提交，不执行 push）  
> **受保护文件约束**：[pyproject.toml](../pyproject.toml) 保持 `dependencies = []`（纯 Python 3.10+ 标准库 + Vanilla Web）；`docs/ZETARIS_DEMO_CHALLENGE_55S.md` 与 `.agents/` 目录全程零触碰。

---

## 一、 执行摘要与阶段提交链（M0 → M4）

围绕 [PROJECT_HEALTH_AUDIT_2026-11-14.md](PROJECT_HEALTH_AUDIT_2026-11-14.md) 识别出的四大长期维护瓶颈与用户的**三项核心决策**（紧急止血与文档归档、Swiss 粗野视觉体系重构、以受控 A/B 测试与内部双盲评审取代主观臆断），本轮收敛按 M0–M4 五阶段稳步推进并在本地完成全部闭环提交：

| 阶段 | Commit SHA | 核心交付与收敛目标 |
|---|---|---|
| **M0 · 紧急止血** | `1e182cc` | 清除 UI 虚假 `"100% 绿灯"`；封堵 `--sample` / `SAMPLE_MODE=true` 泄露宿主机项目列表；对齐 `pyproject.toml` / `plugin.json` / `server.json` / `index.html` 至 `1.0.0`；回滚 `f5b84ec` 针对金标准措辞的过拟合逻辑，补通 `--extractor builtin\|reference`、真实 L3 排序与溯源哈希；新增 GitHub Actions CI 与 `[tool.ruff]` |
| **M1 · 文档治理** | `b130965` | 将 198 篇历史一次性审查/品牌/黑客松/计划文档归入 `docs/archive/`；清理根目录残留（含 `requirements-zetaris.txt` 等）；建立唯一入口 [INDEX.md](INDEX.md)；修复 5 处文档测试数矛盾与 `events.jsonl` 失实描述，实现全库零断链 |
| **M2 · 后端收敛与检索 A/B** | `89b395b` | 抽离共享常量 `limits.py`、事件筛选/成员归属/ISO-8601 `Z` 时间解析与线程安全原子写 `evidence_filters.py`、双语意图词表 `intent_vocab.py`；消除 `investigator.py` 重复推导与平方级冲突扫描；落地可控检索 A/B 盲审（FTS5 Trigram BM25 胜出并补齐精简版 SQLite / NUL 字节降级兜底） |
| **M3 · Swiss UI 重构与视觉 A/B** | `4ff9bc7` | 基于 `--paper #F4F3EE` / `--navy #090D16` / `--orange #FF5500` 重构 Swiss Bauhaus / Neo-Brutalism Web 看板；清除 `#0d6e52`、裸 `#hex` 与模糊阴影；经 Design Alpha vs Beta 双分支实跑截图盲审与定向修复，以 **9.30/10**（3:0 全票）定稿；修复 4 轮 PBR 跨边界缺陷（含二级只读项目作用域、PR/PRD 认知导出诚实性与 `resolveFactStatus` 防御） |
| **M4 · 终局门禁与收口** | *当前收口提交* | 执行真实 `cli --sample --web` HTTP 冒烟测试、刷新 [EVAL_REPORT.md](EVAL_REPORT.md)、完成全套量化脚本/单测/Node 契约/Eval 双轨道复测，同步更新 [INDEX.md](INDEX.md)、[PROGRESS.md](../PROGRESS.md) 与 [HANDOFF.md](../HANDOFF.md) |

---

## 二、 用户三大决策落地与两场可控 A/B 盲审闭环

### 决策 1：先做止血，过期与过程文档规范归档
- **诚信止血**：彻底清零前端与设计文档中的 `"100% 绿灯"` 与历史 `#0d6e52` 配色；`export_pull_request()` 不再将未完成/`[blocked]` 待办或未实跑验证项伪标 `- [x]`；`--sample` 模式严格隔离宿主机真实工作区列表（`/api/projects` 恒返回 `[]`）。
- **文档治理**：将 `198` 篇历史过程文档按主题迁移至 `docs/archive/{reviews,hackathon_and_brand,superpowers,root_legacy}/`（保留完整 Git 重命名历史）；`docs/` 主目录收敛为 `21` 篇受追踪核心活跃文档（加受保护未跟踪 `ZETARIS_DEMO_CHALLENGE_55S.md`），并以 [INDEX.md](INDEX.md) 作为唯一目录总入口。

### 决策 2 & 3：Swiss Bauhaus / Neo-Brutalism UI 重构与可控 A/B 双盲评审

1. **M2 检索方案可控 A/B 与双盲 Critic 评审（见 [RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md](RETRIEVAL_AB_TEST_AND_REVIEW_2026-11-14.md)）**：
   - 在 `easy-course-picker`（14 题）与 `tests/test_question_relevance.py`（18 条单测）上对比对照组 Alpha（Clean N-Gram IDF）与实验组 Beta（纯标准库 SQLite `:memory:` FTS5 Trigram BM25 + 2-Gram Short-CJK Fallback）。
   - 结果：Beta 将 L3 `retrieval_hit_rate` 由 `0.2857` 提升至 **`0.3571`**（+25.0% 相对），`retrieval_mrr` 由 `0.2321` 提升至 **`0.2560`**（+10.3% 相对），综合分从 `34.4` 升至 **`36.2`**，`answer_accuracy` 保持 `0.2857`（如实披露字面瓶颈，不夸大效果）；根据 Critic 2 指出的 3 项可靠性隐患，落地阶段补全 `OperationalError` 自动降级、无静默丢词及 `\x00` 字节清洗。
2. **M3 Web UI 双分支 A/B 实跑截图与双盲 Critic 评审（见 [UI_AB_TEST_AND_REVIEW_2026-11-14.md](UI_AB_TEST_AND_REVIEW_2026-11-14.md)）**：
   - 第一轮（5 场景桌面 `1440×900` + 移动 `390×844` 实拍图盲审）：3 位独立 Critic 以 **`7.4 / 7.3 / 7.0`** vs `5.0 / 4.8 / 4.8`（3:0）一致选定 **Design Beta（非对称 `5fr / 7fr` 编辑栅格）** 作为基底。
   - 终版合成第 1 轮均分 `9.033`（`9.1 / 8.9 / 9.1`），抓出并修复 `html { font-size: 16px }` 根字号缩放导致 `0.75rem = 11.25px` 的继承缺陷、Process 轨道右缘对齐与移动端 `44px` 触控目标。
   - 终版合成第 2 轮盲审：**3 位 Critic 一致打出 `9.3 / 9.3 / 9.3`（均分 `9.30 / 10`）**，全维度 ≥ `9.0`，零第三方依赖落地并同步更新 [UI_STYLE_GUIDE_MANUAL.md](UI_STYLE_GUIDE_MANUAL.md)。

---

## 三、 健康度审计问题逐条收敛前后对比

| 审查维度 | 整改前状态（`f5b84ec` 基线） | 整改后状态（`4ff9bc7` + M4 终局实测） |
|---|---|---|
| **1(a) UI 样式与交互标准** | 3 套视觉语言并存、192 处 `:root` 外裸 hex、11 处 `#0d6e52`、4 处软阴影、21 种字号、15 处裸 `fetch(`、含空 `catch (_e) {}` | 唯一 `:root` Token 系统、`raw_hex_outside_root = 0`、`teal_0d6e52 = 0`、`blur_shadows = 0`、`backdrop-filter = 0`、`min_css_font_px = 12.0`、`html/js` 零裸 hex 与零 `style=`、唯一 `apiFetch`（1 处 `fetch(`）、0 个空 catch |
| **1(b) 硬编码与重复逻辑** | "公开原始事件"判定分散 9+ 处；`dashboard.py:401` 成员归属分叉；`1600`/`512` 魔数散落；6 处时间解析漏处理 `Z` 后缀；中文意图分散 4 处 | 统一收敛于 [limits.py](../src/project_compass/limits.py)、[evidence_filters.py](../src/project_compass/evidence_filters.py) 与 [intent_vocab.py](../src/project_compass/intent_vocab.py)；`resolve_member_id` 全链路单一真相；原子写使用 `NamedTemporaryFile(..., delete=False)` 杜绝并发踩踏 |
| **1(c) 冗余残留与清单一致** | 根目录残留 `HACKATHON_BRIEF.md`/`PLAN.md`/`requirements-zetaris.txt`；`plugin.json` (`0.1.0`) / `server.json` (`0.1.0`) / `index.html` 与 `pyproject.toml` (`1.0.0`) 版本分裂 | 历史冗余文件全部清理或归档；三份清单与 `index.html` 统一 `1.0.0`；`pyproject.toml` 维持 `dependencies = []` 并补齐 `[tool.ruff]` 与 `.github/workflows/ci.yml` |
| **1(d) 文档治理** | 162 篇文档平铺混杂；测试总数存在 5 种互相矛盾描述；`INDEX.md` 缺失 | 归档 198 篇历史快照至 `docs/archive/`；建立唯一入口 [INDEX.md](INDEX.md)；自动化脚本校验全库活跃 Markdown 链接 **0 断链** |
| **2(a) 技术路线与后端性能** | `investigator.py` 重复调用 `derive_facts`、冲突扫描平方复杂度；只读二级项目 `/api/evidence`、`/api/export`、`/api/investigate` 未隔离开主项目状态 | `investigator.py` 消除重复推导并优化冲突扫描；CLI 打通 `--index-code`；`web_server.py` 为 `/api/evidence`、`/api/export`、`/api/investigate` 打通 `project_id` 只读作用域并新增无锁 `active_project_id()` 比对 |
| **2(b) 测评体系诚实性与反作弊** | 存在基于金标准措辞的硬编码过拟合、`default_runner` 未透传抽取器、0 冲突标注不清 | 清除过拟合分支；明确 `Red-Line Gate (PASS)` 与 `Quality Grade (36.20/100 · Tier 3 Baseline)` 解耦双轨；支持 `--extractor reference\|builtin` 对照实跑、L4 调用链回归全绿与 `gold_sha256` 溯源校验 |
| **3 UI 可视化与认知诚实** | 存在 `"100% 绿灯"` 误导、零值绿徽章、个人 `North Star` 在团队/只读切换下错乱、浮窗叠放遮挡与导出状态伪报 | `Team Truth` 缺确认目标暴露 `EMPTY GAP`、零值使用中性 `.zero-count`、Split A-vs-B 双栏冲突对抗、`#scrim(80) < #handoff-modal(88) < #evidence-drawer(95) < #citation-popover(100)` 与 `Esc` 堆栈恢复、导出仅在真实下载或剪贴板成功时报告成功 |

---

## 四、 全链路 PBR 三视角代码审查发现与闭环汇总

M0–M3 期间，累计执行多轮隔离/穿透 **Perspective-Based Reading (PBR)** 代码审查，重点捕获并就地修复以下跨文件接缝漏洞（详见各模块测试与 [UI_AB_TEST_AND_REVIEW_2026-11-14.md](UI_AB_TEST_AND_REVIEW_2026-11-14.md) §5 & §5.1）：

1. **事实晋升与诚实边界**：封堵 `project.read_only` 模式伪造确认徽章、消除按 `subject_key` 跨 ID 误认冲突目标、`export_pull_request()` 取消伪造 `- [x]` 已实现待办与 `"单元测试 100% 绿色通过"`、缺失下载与剪贴板时 `exportCognitiveAsset` 诚实提示 `"请手动复制"`。
2. **前后端跨边界契约接缝**：打通 `export_prd()` 对 `state["team"]["timeline_chapters"]` / `thinking_line` 与 `export_pull_request()` 对 `member_id` 的真实适配；修复 `POST /api/investigate` 对 JSON `null` 强转为 `"None"` 误报 `404`；新增 `DashboardHTTPServer.active_project_id()` 避免高频悬停预取反复重建 `dashboard_state()`。
3. **XSS / 竞态 / Node VM 兼容防御**：`resolveFactStatus(fact)` 提前拦截无 ID 对象防 `undefined === undefined` 错配；浮窗异步回写前检查 `targetEl.isConnected`、项目切换清理 `evidenceCache` 并拦截延迟 `404` 竞态覆盖；全面保持 16 套 Node VM `.cjs` 测试宿主兼容。

---

## 五、 终局实测验证与量化门禁证据

以下均基于工作区最终状态实际运行验证并观测退出码：

1. **自动化量化健康门禁（`scratch/m4_final_audit.py`）**：`ALL_M4_QUANTITATIVE_GATES_PASS`（`teal_0d6e52 = 0`、`fake_green_light = 0`、`css_raw_hex_outside_root = 0`、`css_blur_shadows = 0`、`css_non_none_backdrop_filter = 0`、`root_rem_px = 16.0`、`min_css_font_px = 12.0`、`html/js` 裸 hex 与内联 `style=` 均为 `0`、`js_fetch_count = 1`、`js_empty_catch_count = 0`、`js_reviewer_alert_count = 2`、`pyproject_dependencies = []`、`versions = 1.0.0`、`broken_active_doc_links = []`、`zetaris_sha256_ok = true`）。
2. **真实 CLI `--sample --web` HTTP 冒烟实测（端口 `8790`）**：`smoke_ok = true`，`/`、`styles.css`、`app.js`、`/api/state`（`sample_mode = true`、`projects = []`）、`/api/projects`（`[]`）与 `/api/export?format=prd`（含真实 `阶段 01：目标确立`）均返回 `200 OK`。
3. **五层测评基准实测（`easy-course-picker` + `baseline_report.json`）**：
   - `--extractor reference`（已刷新至 [EVAL_REPORT.md](EVAL_REPORT.md)）：`Red-Line Gate: PASS`，`Quality Grade: 36.20 / 100 · Tier 3 (Baseline)`（L1/L4/L5 全 1.0000；L2 `recall=0.5789, precision=0.0493, F1=0.0909`；L3 `evidence_coverage=0.7143, hit_rate=0.3571, mrr=0.2560, answer_accuracy=0.2857`）。
   - `--extractor builtin`：`Red-Line Gate: PASS`，`Quality Grade: 0.0 / 100 · Tier 3 (Baseline)`（L1/L4/L5 硬红线通过，零模型前提下无抽取候选用以校验端到端安全闸门与空洞标注诚实性）。
4. **全量静态编译、前端契约与单元测试**：
   - `$env:PYTHONPATH='src'; python -m compileall -q src tests` -> `exit 0`
   - `node --check src/project_compass/web/app.js` -> `exit 0`
   - 全部 `16` 个 `tests/*.cjs` Node VM 交互/安全/诚实性脚本 -> 16/16 `exit 0`
   - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -q` -> 在最终文档提交前复跑验证 `exit 0`（无跳过、无失败）。
