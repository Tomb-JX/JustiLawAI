# 标注线角色交接（L5 教师标注，2026-10-18）

> 给接手标注工作的新会话：先读这一份，建立角色和现场感；再按文末阅读路径去看原始文档。不要从旧 `collab-log`、续跑单或历史会话摘要开始，它们只作历史参考。

## 1. 你的角色

你是 **L5 要素标注线**的推进者。不是解析线、引擎线或绑定线的修复者。

- 你负责：把“可标注的输入”变成“可审计的教师标签批次”，并给出字段质量、A/B 一致性和证据定位的证据。
- 你不负责：改 `schema.py`/教师契约、改 S1/S2/S3 代码、改 binding 规则、放行 r7、宣布人工金标。
- 你可以自主决定：合格子集的口径、批次顺序、抽样方式、A/B/C 的组织、冒烟规模、报告结构。遇到字段定义、契约版本、教师提示词的问题，找引擎线确认；遇到 S1/S2 输入错误，记录并交给解析/后处理线，不要自己改代码。

一句话：**你是标注线的 owner，不是全栈修理工。你的产出是“可审计的标签批次和质量证据”，不是“把解析 bug 全修完”。**

## 2. 先读什么

按这个顺序读，边读边对照 `$DATA` 里的实际产物：

1. **实时状态**：`$DATA/coordination/CURRENT.md`、协调分支 `BOARD.md`、`ISSUES.md`、`DECISIONS.md`。先知道现在哪些门没开。
2. **L5 契约**：引擎 `docs/05-research/data-spec.md` §8（v0.6.1，36 要素 + `CaseMeta` 3 元数据 + `binding` 派生块）。
3. **字段规则**：`docs/05-research/annotation-guideline.md` §3.11（v0.4.3，字段裁决、证据、绑定边界）。
4. **教师接口**：`docs/05-research/element-teacher-v1.md`（教师只输出 7 组 36 字段，不输出 binding/CaseMeta/outcome）。
5. **字段唯一来源**：引擎 `justilaw-api/app/discretion/schema.py`、`element_labels.py`（`teacher_messages`、`teacher_system_prompt`、`validate_teacher_output`）。
6. **解析/标签分层**：`docs/04-plan/parse-engineering-design-v2-2026-10-17.md` v2.8，重点 §3（S1）、§3A（L5）、§4（S2）、§6.1（S4）、§9.1（实测）、§12（卡点）。
7. **S1 质量分母**：`docs/04-plan/pilot300-quality-report-2026-10-17.md`（seg-v2、S3、边界 F1、错误类别）。注意：现有边界 F1 是“模型 vs 正则”，不是人工金标。
8. **I-20 方案**：`docs/04-plan/i20-interface-for-engine-2026-10-18.md`（12 → 36 → 200–300 的路径）。
9. **本轮契约交接**：`docs/04-plan/handoffs/2026-10-18-element-contract-v1.md`（验收命令、A/B/C、产物格式）。
10. **实际产物**：见 §3 的路径。先看 `summary.json`/`plan.json`，再看 `outputs.jsonl`/`diagnostics.jsonl`。

## 3. 当前现场（2026-10-18）

### 解析/S1

- final300：299/300 成功；zones 铺满/不重叠违例 0；
- S3 硬失败 **26/299 = 8.7%**，未达 r7 的 <5%；
- 错误构成：facts_quality 15、outcome_consistency 10、decision_present 5、subject 2、value_grounded 2；
- 边界 F1（**模型 vs parse.py 正则，不是人工金标**）：final300 facts 0.768 / decision 0.487 / evidence 0.975；spec50 facts 0.769 / decision 0.393；
- 人工 100–200 件五段边界评测集仍未做；decision 是最低、最不确定的段。

### L5 标签

- `reference_elements=null`，L5 标签为 0；
- 12 件烟测：21 条证据、20 条定位成功（95.2%）；**字段准确率仍未测**；
- 教师契约：`element-teacher-v1`、schema 1.1.0、`element-ref-v2`；
- 教师输入只有 `target + aliases + facts_text + meta_text`，不含 decision/reasoning/review/outcome；
- 一人一条记录；多人案件拆成多条调用；
- 产物标 `model-adjudicated`、`human_review=false`，不是人工金标。

### 切片与绑定

- 212 开发切片：单人案卷，121 事件；有 `reference_elements=null`；
- P1-r6：178 条、186 个多人 behavior 节点；是多人绑定样本；
- binding 当前 `e06a0af`：212 123/611/1611；P1 158/723/1708；money shared=0，money/time 大量 review；
- binding **没有接入教师主链路**；`binding_contract.ground_fields` 目前只有测试调用，没有生产调用；
- 规则版语义归属已按 B-10/BIND-05 冻结；不要为了标注去修 binding 规则。

### 门禁

- r7 未放行：S3 8.7% >5%；
- 没有新付费批；付费要过 I-21 六道门；
- 契约 `binding_policy=proposed_pending_engine_adoption`、`semantic_rules_approved=false`；这不阻塞教师标注，但报告里要写清。

## 4. 三条线的边界

| 线 | 你找它做什么 | 你不做什么 |
|---|---|---|
| 引擎线 | 字段定义、教师提示词、契约版本、`schema.py` 变更 | 不自己改 schema/教师输出契约 |
| 解析/后处理线 | S1 zones、facts/meta 视图、S3 findings、输入错误 | 不自己改 S1/S2/S3/binding 代码 |
| 协调线 | 事件登记、看板、跨线验收、I-21 工单 | 不手改 `CURRENT.md`，不绕过事件登记 |

你可以在合格子集上自主推进；跨线问题用事件登记 + 一份 handoff，不要用长聊天记录交接。

## 5. 标注工作的核心问题

### 输入合格集

教师输入不是整篇文书，而是 `facts + facts 之前的 meta`。所以“输入合格”至少包括：

- S3 无 error（`run_elements.load_work` 已过滤）；
- target 在 facts/meta 视图里（`build_inputs` 已检查；不满足会 `missing_target_or_input`）；
- 不含 decision/reasoning/review/outcome；
- 证据引文必须能在原文逐字找到（S2 定位 + `validate_teacher_output`）。

S3 的 8.7% 里，**不是所有错误都影响教师**：

- 影响教师：`facts_quality`、`decision_present`、`subject`；
- 基本不影响教师：`outcome_consistency`、`value_grounded`（教师不看 S1 的 outcome/日期字段）。

第一批是否要求“facts_quality/subject/decision 也无 warn”，由你定。严格会缩小批次，但标签更干净；宽松会扩大批次，但要在报告里标出风险。不要拿过滤后的子集去报 r7 的 S3<5%。

### 批次路径

现有设计是 12 → 36 → 200–300。12 件烟测只证明调用/证据定位能跑，不证明字段准确率。下一段的重点是：

- spec36：字段准确率、关键字段 P/R/F1、A/B 一致率、仲裁分歧率；
- 200–300：事件隔离、分层抽样、稳定扩量；
- 产物必须带原文哈希、视图哈希、契约版本、A/B 原始结果、仲裁记录。

### 质量指标

不要只报“证据定位率”。至少分开：

- 证据定位率：引文能否逐字回到原文；
- A/B 一致率：分类字段 Cohen's κ、数值字段一致率（只在至少一方非“未提及”上算）；
- 仲裁分歧率：>20% 要回修提示；
- 字段准确率：没有人工金标时，只能报“模型仲裁一致率/抽样复核”，不要叫准确率；
- 泄漏检查：教师输入不含 decision/reasoning/review/outcome；
- 覆盖/空值：关键字段未提及率、字段覆盖率。

### 事件隔离

212 是单人切片，P1 是多人样本。教师批次要按事件分组，不能让同一事件跨 train/test。多人案件还要注意 target/aliases 的可见性和“只标本人”的边界。

## 6. 现在可以做什么

- 用 `run_elements` 的 **plan 模式**（不 `--execute`）先跑合格集，得到 eligible/rejected 数量和拒绝原因；这是免费的，先做。
- 从 12 件 smoke 的产物开始看：`$DATA/s1_runs/smoke12-elements-e05/`（已执行）和 `smoke12-elements-e05-plan/`（从 final300 选 ID 的 plan，很多 `missing_target_or_input`）。后者能告诉你 target 可见性有多严格。
- 在合格子集上设计 spec36；不要等所有 S1 错误修完，也不要把 8.7% 的记录硬塞进教师批。
- 把 S1 输入问题（facts 缺失、decision 误分、subject 不可见）记录成 case，交解析/协调线；不要自己改 parser。
- 如果要做 200–300，先写清 eligible 分母、事件隔离、预算、A/B/C 分工，再过 I-21；不要先调用后补工单。

## 7. 不能做什么

- 不改 `schema.py`、教师提示词、`element-teacher-v1` 契约；字段问题找引擎线。
- 不改 S1/S2/S3/binding 代码；输入问题记录并交接。
- 不用本地小模型产标签/训练数据（用户明确决策）；教师只用远程旗舰 A/B/C。
- 不在没有冻结工单/预算的情况下调用付费模型；凭据不入库、不入对话。
- 不把 `model-adjudicated` 叫人工金标；不写 `human_review=true`；不写 `release_approved=true`。
- 不用过滤后的子集报 r7 的 S3<5%；r7 的分母仍是 299。
- 不放行 r7、不改门禁、不合并 main。
- 不手改 `$DATA/coordination/CURRENT.md`；用 `coord_event.py` append 事件。

## 8. 交接与记录

- 实时状态：`$DATA/coordination/events.jsonl` + `CURRENT.md`；提交/产物/阻塞/指标都 append。
- 跨线交接：`docs/04-plan/handoffs/` 一文件一次，写清输入、产物、验收命令、失败处置。
- 你的批次产物：`$DATA/s1_runs/<new-run>/`，不要写旧 run；manifest 里保留 contract/view/source 哈希。
- 你的报告：字段质量、A/B、仲裁、拒绝原因、分母、未解决项；不要只写“已跑通”。

## 9. 开放问题（你可以自己定，或拉引擎/协调线定）

1. 第一批合格集：严格（无 facts/subject/decision warn）还是宽松（仅 S3 无 error）？
2. 先 212 单人切片，还是直接 P1 多人样本？建议先用 212 验契约，再用 P1 验多人归属。
3. 没有人工金标时，字段质量怎么报：A/B 一致率 + 仲裁 + 小样本人工抽检，三者怎么组合？
4. `missing_target_or_input` 的处置：剔除、回修 S1 视图、还是转人工？需要给出比例和原因。
5. 引擎契约 `proposed_pending_engine_adoption` 未采纳时，是否先跑开发批？可以，但报告要标“开发/未采纳”，不能当正式交付。

## 10. 关键路径

- `$DATA = D:/02_Dev/Data/justilaw-research`
- 实时：`$DATA/coordination/CURRENT.md`
- final300：`$DATA/s1_runs/s1-20261018-segv2-final300/`（`outputs.jsonl`、`s3/summary.json`、`s3/findings.jsonl`）
- 12 件 smoke：`$DATA/s1_runs/smoke12-elements-e05/`（已执行）、`smoke12-elements-e05-plan/`（plan）
- 212 切片：`$DATA/parsed2/dev-slice-20261018-codex-v2/records.jsonl`
- P1-r6：`$DATA/parsed/pkulaw/20261018-P1-r6/records.jsonl`
- 212 诊断：`$DATA/parsed2/diagnostics-bind-fix-dev212-20261018-codex/`
- P1 诊断：`$DATA/parsed2/diagnostics-bind-fix-p1-20261018-codex/`
- 引擎代码：`.claude/worktrees/discretion-engine/justilaw-api/app/discretion/`
- 后处理代码：`.claude/worktrees/seg-v2-design-review/research/discretion/unify/`

读文档时以 `CURRENT.md`/`BOARD.md` 的实时状态为准；设计文档里的数字如果和 `CURRENT.md` 冲突，先看事件登记和最新提交，再决定是否要回写文档。
