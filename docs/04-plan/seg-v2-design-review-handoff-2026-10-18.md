# seg-v2 设计评审交接（Codex 新会话 · 2026-10-18）

> 一句话：网页线的解析/标注链路（seg-v2 + elements）在 300 件试点后仍未达标，并已积累一批设计层问题。请你独立评审设计、给出下一步接口方案。
> **本单只做索引与问题蒸馏，不预设结论、不代替你判断；细节一律以源文档为准。**

## 1. 任务

- 设计评审，不是写代码、不是调提示词、不是跑批。
- 产出：一页评审结论 + 决策日志（每条裁定写依据与生效批次）。
- 你的独立性很重要：网页线在反思文档里列了它自认为的"结构性错误"，**请自行判断成立与否**，不要照单全收。

## 2. 必要背景（只给定位，不给结论）

- 项目：行政赌博裁量引擎；本链路在网页工作树 `.claude/worktrees/project-data-collection-audit-4bac93`。
- 现行交付 r6 只是格式关口（不可标注）；标签挂在 parsed-2；r7 候选池约 2,918 条 L1/L2。
- 试点：seg-v2 final300 的 S3 硬失败率 8.7%（未达 <5%）；elements 首批 88 件、平均 6.58 个字段分歧。
- 近期两次事故供你当约束背景：I-20（要素字段无标签来源）、I-21（大批量检索缺锚，8,400 分换 42 条 L1）。

## 3. 请回答（蒸馏清单，不限于此）

1. 现在的模型调用拆分对不对？分区、结果抽取、日期规范化、赌博判定、置信自评，是否该拆成不同调用？
2. 证据/引文是否应改为**结构引用（句编号）**，而不是让模型逐字抄？S2 定位层是否可整体退役？
3. 双盲分歧应该怎么用？哪些字段的分歧是"定义缺裁决规则"，该怎么改契约而不是加仲裁？
4. 36 个要素字段该如何分档验收？哪些字段源头就缺，不能与常规字段同一标准？
5. `decision` 区间的边界到底怎么定（当前 F1 只有约 0.49）？
6. 哪些改动能用现有真实输出**离线重放**验证，哪些必须付费烟测？下一笔付费批的最小设计（大小/预算/判据）是什么？
7. r7 放行需要哪些数字条件？

## 4. 先读这些（按顺序，自己判断取舍）

1. 网页线反思（它自述的 D1–D6、五条调用准入、分歧榜）：
   `docs/04-plan/model-call-design-reflection-2026-10-18.md`
2. 全链路逐接口 + O1–O12 开放决策点：
   `docs/04-plan/model-call-design-full-record-2026-10-18.md`
3. 试点与判据：
   `docs/04-plan/pilot300-quality-report-2026-10-17.md`
4. 句表分区设计：
   `docs/04-plan/parse-interface-v2-design-2026-10-17.md`
5. 全链路格式契约：
   `docs/04-plan/parse-format-chain-design-2026-10-17.md`
6. 协调侧现状与约束（数据分布、I-20、I-21、阶段规划、分工）：
   `D:\02_Dev\Projects\大创\.claude\worktrees\data-coordination\docs\04-plan\` 下的
   `data-distribution-2026-10-18.md`、`issues/I-20-*`、`issues/I-21-*`、`stage-plan-v2-2026-10-17.md`、`workstreams.md`
7. 代码入口：
   `research/discretion/unify/{s1.py, s3.py, run_s3.py, run_elements.py, arbitrate.py, zoning.py, cleanse.py, locate.py}`
8. 数据入口：
   `$JUSTILAW_DATA_DIR/s1_runs/s1-20261018-segv2-final300/`（含 `outputs.jsonl`、`s3-coord-check/summary.json`）、同目录 `elements/`、`diffs.jsonl`、`budget.jsonl`；
   `$JUSTILAW_DATA_DIR/unified_raw/web/20261017-web-r3/records.jsonl`
9. 引擎侧要素契约：
   `justilaw-api/app/discretion/{schema.py, element_labels.py}`、`research/eval/accept_element_labels.py`、`docs/05-research/element-teacher-v1.md`

## 5. 边界（不展开，源文档有定义）

- 只读代码与数据；只写自己的评审分支（建议 `codex/seg-v2-design-review`），不动主工作树与 `$DATA`。
- 不跑付费批、不下载、不改交付/标签、不重定义门禁。
- 模型隔离、原文口径、r6/r7 分离、大批量六道门：以 `workstreams.md`、`issues/I-21-*`、`stage-plan-v2-*` 为准，不要凭印象。

## 6. 交付

- `docs/04-plan/seg-v2-design-review-2026-10-18.md`（或你的分支内等价路径）：结论、目标调用架构、字段级验收、免费重放方案、下一付费批设计、O1–O12 裁定、r7 门禁。
- 不确定的地方标"待验证"，不要为了完整而补结论。
