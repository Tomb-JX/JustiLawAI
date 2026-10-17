# 引擎线后继会话交接简报（2026-10-17）

> 背景：原 Claude 引擎会话额度耗尽，引擎线执行会话迁移。本简报供新会话（ZCode/Codex 均可）开。
> 工作树：`D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine`，分支 `worktree-discretion-engine` @ `b2bda42`（干净）。**开工前先 `git status --short --branch` 核对。**

## 1. 基线（你已经有什么）

- 分支领先 main 3 笔未合（`1d20dbf` D-002 登记+门禁 v0.6+目标省建档、`50671fd` 两省 YAML 原文、`b2bda42` 省级基准结构化分档）；合 main 待用户/周会审阅。
- 已落地资产：schema 1.1.0（开口金额/营利目的裁定）、agreement.py（κ 唯一实现）、`outcome.fine_masked` 契约、text_party 契约、norm_layer Ω（30 黄金用例过）、规范库国层 22 项逐字核对+省级两省分档。
- 测试基线：`pytest tests/discretion`（此前 105 项全绿）——动手前先跑一遍确认起点。

## 2. 任务清单（按序）

### 任务 1（立即）：规范修订案套用（引擎四件 + 契约 + 验收器）

按 [normative-revision-deid-cancel-2026-10-17.md](./normative-revision-deid-cancel-2026-10-17.md) §B/§C 逐条执行：

1. 偏离日志登记 **D-003**（脱敏全量取消：旧要求/新要求/依据/影响面，格式对齐 D-002）；
2. 门禁 `sota-baselines-and-gates.md`：R6 条文改写（§C 表）、G1.3 联动；
3. `data-spec.md`：删 `deidentified`/`r6_scan` 字段、`text_full` 改原文正本、§1.6 代称约定改写（subject_alias 取消→`subject_mention`）、D3 文号明文、§4 验收项撤三项、新增外发条款；
4. `annotation-guideline.md`：标注输入改原文、产物不收录姓名字段、本人定位用 subject_mention；
5. `records.py`：契约同步删字段/改名；`accept_delivery.py`：撤 deidentified=是/R6 两遍/甲-presence 三项检查；
6. `justilaw-api/tests/discretion/` 全量回绿；完成后在修订案 §E 登记行。

### 任务 2（复核件）：legal_caps.json 转正

`$DATA/config/legal_caps.json`（caps-v1）已由协调层代生成（源自 `norms/national/psal-2012.yaml`/`psal-2025.yaml`，带源文件 sha256 前 16 位）。请核对数字与结构后把 `generated_by` 改为引擎线正式署名（转正）；发现差异直接改并经协作记录告知。

### 任务 3（等 parsed-2 + 标签初稿）：端到端首跑切片

- **输入（2026-10-17 深夜更正，原表述作废）**：**parsed-2 记录**＝S1 分段/字段经 S2 定位在原文正本上＋蒸馏标签（网页线产出，模型共识口径）。**不是 r6**——r6 的分段/字段全部是旧正则产物、未经模型标注，仅作原文文本冻结参考与交付格式关口（法宝线指认"r6 不可用于标注"，协调确认）；
- 做什么：M1 零样本抽取**首次跑行政数据**（字段准确率/证据命中/丢弃率首份真实数字）→ M2 Ω → M4 最简专家（GBDT/B4 风格）→ 五项输出卡片 3 件样例；
- 口径：开发性评测（D-002），带 `-model` 后缀，不触门禁；
- 产出：`engine/` 下报告 + collab-log 行（四个数字：已标件数/抽取字段准确率/基线区间准确率/卡片可用率）。

## 3. 边界与纪律

1. 只写引擎范围：`justilaw-api/app/discretion/**`、`research/eval/**`、`docs/05-research/**`、`docs/02-design/gambling-discretion-engine.md`；规范文档按修订案蓝本改，不自创口径。
2. 跨线需求（如给网页线的常量表变更）走协作记录；不写网页/协调/金标树。
3. collab-log 行提交回引擎分支；推分支不直推 main（合 main 待审阅）。
4. 凭据纪律照旧；测试不引入真实姓名样本。
5. 阅读顺序：本简报 → normative-revision 修订案 → coordination-audit 顶部 2026-10-17 各节（今日决策全史）。

## 4. 现势速查

- 现行交付 r5（LATEST）；r6 由网页线按[接入指令](./web-integration-directive-2026-10-17.md) §2 发布中；
- 你的常量表已被网页线列为 P0 依赖——任务 2 建议最先做（10 分钟）；
- 协调线：Zcode 协调会话（data-coordination 树），有事在 collab-log 留行或经用户转达。
