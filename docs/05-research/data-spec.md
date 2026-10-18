# 行政案例数据交付规格（数据链路 → 引擎）

> 版本 v0.6 · 2026-10-18 · 细化[分工文档](../04-plan/workstreams.md) §5"案例数据交付"；新增 §8 要素标签契约（L5）
> 配套：[项目现状总览](../04-plan/project-status.md)（数据分层 §4）· [数据收集计划](../04-plan/data-collection.md) · [文本处理规范](../04-plan/text-processing-spec.md)（数据链路的实现规则）· [标注指南](./annotation-guideline.md) · [固定对照与阶段门禁](./sota-baselines-and-gates.md)
> v0.5 按用户批准的[规范修订案](../04-plan/normative-revision-deid-cancel-2026-10-17.md)改为原文正本；解析层统一中间格式（§6）与自动验收（§4）保留，字段总表（§7）由 `justilaw-api/app/discretion/records.py` 生成，**以代码为准**。

## 0. 为什么要这份规格：CAIL 探针的教训

在 CAIL2018 赌博子集上，M1 抽取 + 统计模型只比"永远猜最多的类"高约 1 个百分点。原因不在模型，而在数据本身：

| 统计（1,613 件） | 比例 |
|---|---|
| 事实是"检察院指控……××罪"式的公诉书摘要 | 57% |
| 一个金额都没有（赌资、抽头、获利都没写） | 26% |
| 自首、坦白、认罚、退赃一项都没写 | 69% |
| 金额和情节都没有 | 19% |

这 19% "信息空白"的案件，实际刑期从 1 个月到 27 个月都有。**输入一样、答案却不同，任何模型都学不会。**

所以行政案例采集的第一原则是：**决定处罚结果的信息必须在文本里，而且要分清哪部分是"事实"、哪部分是"结论"**。

## 1. 每件案例必须提供的信息

### 1.1 来源与溯源（缺一项就不能入库）

| 字段 | 说明 |
|---|---|
| `id` | 台账 id（如公开网页 `W-000123`）。URL 等来源链接仍通过台账追溯；公开文书中的原始文号可随正文和 `doc_no` 保留 |
| `source_type` | 处罚决定书 / 不予处罚决定书 / 行政复议决定书 / 行政判决书 / 执法公示 / 合作案卷 |
| `doc_no_hash` | 规范化文号（去空白、统一括号）的 SHA-256 前 16 位；用于跨来源去重 |
| `harvest_date` | 采集日期 |

### 1.2 时间、地点与法律版本（决定适用哪部法律、哪个省的裁量基准）

| 字段 | 说明 | 为什么必须有 |
|---|---|---|
| `behavior_date` | 违法行为日期，持续行为取结束日；正文和元数据均保留原文可得的日期精度 | 2026-01-01 前后分别适用旧法第七十条、新法第八十二条 |
| `decision_date` | 处罚决定日期，元数据保留到日 | 从旧兼从轻需要同时知道两个日期；"一年内 / 六个月内"从重按日计算 |
| `authority` | 作出决定的机关，如"××县公安局" | 定位到省、市 |
| `region` | 行政区划代码，至少到省 | 选省级裁量基准 |
| `law_version` | 旧法（2012 修正）/ 新法（2025 修订）/ 未知。**指处罚决定实际适用的版本，以 `outcome.articles` 引用的法条为准，不按行为日期推算**；同时写在 `outcome.law_version`，两处必须一致 | 引擎按日期推算"应当适用"的版本，与实际适用的对比。两者不同的多是从旧兼从轻案件，正是 T-time 要的样本，构建时不能用日期推算值覆盖 |

### 1.3 原文与分段（最重要，防止"答案混进题目"）

`text_full` 是**依法公开文书的原文正本**：冻结后，标注证据的字符位置都相对它计算；冻结后任何改动（包括纠正 OCR 错字）都要重新标注受影响的字段。附 `text_sha256`。

文书按内容切成下面几段，每段必须是 `text_full` 的连续子串，起止位置记在 `segments`：

| 段落 | 内容 | 引擎怎么用 |
|---|---|---|
| `text_party` | 当事人段：本人的身份、年龄或出生年月、违法经历，即事实段之前、标题和文号之后的部分；有多名当事人时只取本人那一段（可选，I-02） | 模型输入：年龄、前科日期这类要素主要在这里（实测年龄线索在事实段 0%、当事人段 39%） |
| `text_facts` | 查明的违法事实（"经查""查明"部分） | 模型输入：M1 从这里抽取要素 |
| `text_evidence` | 证据列举 | 辅助核对，不作为模型输入 |
| `text_reasoning` | 认定理由、情节认定、裁量说明（"本局认为""经审查"部分） | **不作为模型输入**（里面常写着"情节严重""从轻处罚"，等于答案的一部分）；用于标注情节和训练 M6 说理 |
| `text_decision` | 处罚决定原文（"决定给予……"） | 提取处罚结果标签 |
| `text_review` | 复议、诉讼机关的审查意见与结论（如有） | 判断原处罚是否被认可 |

切不准时只保留 `text_full`，标 `segmented: false`，引擎会单独处理。`text_facts` 里混有结论词又移不走的，标 `quality.facts_contains_conclusion`。

### 1.4 处罚结果（标签，必须结构化）

| 字段 | 取值 |
|---|---|
| `outcome.type` | 不予处罚 / 不构成违法 / 警告 / 罚款 / 拘留 / 拘留并处罚款 / 移送刑事 |
| `outcome.detention_days` | 整数，没有填 0；合并执行的取合并后天数 |
| `outcome.fine` | 元，没有填 0 |
| `outcome.fine_masked` | 发布方把罚款数额打码（"罚款**元"）时为 `true`，`fine` 填 0。验收只记 warn；这类记录的处罚档次可用，**罚款额不得作训练或评测目标** |
| `outcome.detention_not_executed` | 是 / 否（依法不执行拘留） |
| `outcome.confiscation` | 收缴的赌资、赌具描述 |
| `outcome.articles` | 引用的法条，统一写法如"治安管理处罚法（2012修正）第七十条""治安管理处罚法（2025修订）第八十二条""第二十条第五项" |
| `outcome.stated_circumstances` | 决定书中**明写**的情节认定：情节严重 / 从轻 / 减轻 / 从重 / 不予处罚（原文怎么写就怎么记） |
| `review.result` | 见下表（D4） |
| `review.changed_outcome` | 被变更后的处罚（如有），结构同 `outcome` |

`review.result` 的取值与含义：

| 取值 | 含义 | 原文常见写法 | 原处罚能否当标签 |
|---|---|---|---|
| 维持 | 经实体审查，认可原处罚 | 复议"决定维持"；诉讼"判决驳回原告诉讼请求"、二审"驳回上诉，维持原判" | 能 |
| 变更 | 原处罚被改 | "决定变更为……"；诉讼"判决变更"（行政诉讼法第七十七条，处罚明显不当） | 不能直接用；变更后的处罚记入 `changed_outcome` |
| 撤销 | 原处罚被撤销 | "决定撤销""判决撤销" | 不能 |
| 确认违法 | 违法但不撤销 | "确认……违法" | 不能 |
| **程序驳回** | 未经实体审查就结束 | 复议"驳回行政复议申请"（如超期、不符合受理条件）；诉讼"裁定驳回起诉"、不予立案 | 能，但视同未经审查（与"无"同等对待），**不算被认可** |
| 无 | 未经复议或诉讼 | — | 能 |

注意：**诉讼中的"驳回诉讼请求"是实体认可，记"维持"，不是"程序驳回"**。2014 年行政诉讼法修改后，"维持判决"改成了"驳回诉讼请求判决"，所以行政判决里几乎见不到"维持"二字。

### 1.5 事实要素（按[标注指南](./annotation-guideline.md)标注；P1 阶段由教师模型预标、人工校正）

至少要能从 `text_facts` 中判断以下内容，文中没写的就记"未提及"，不要猜：

| 类别 | 要素 |
|---|---|
| 行为 | 参与赌博 / 为赌博提供条件；赌博方式；次数、持续时间 |
| 数额 | 个人赌资、每局输赢、现场查获赌资、抽头或台费、违法所得 |
| 人员 | 参赌人数、是否有未成年人参与、亲属之间与否 |
| 主观 | 是否以营利为目的（有无抽头、收费） |
| 本人 | 年龄、近期是否受过治安处罚（**要有日期**）、是否初次违法（按公通字〔2007〕1号第五项认定）、孕期或哺乳 |
| 情节 | 主动投案、如实陈述、认错认罚、主动消除后果、立功、受胁迫诱骗、阻碍执法 |

### 1.6 当事人定位与事件关联

正文保留来源文书的原写法。`subject_mention` 记录本人在原文中的称谓，M1 用 `extract(text_facts, target=subject_mention)` 定位本人并只标本人的要素；不再生成 `subject_alias`。出生日期、年龄和文号保留原文，`doc_no_hash` 仍用于去重。元数据日期尽可能保留到日，原文只有月时不得补日。

同一现场、同一时间的多人各自成案，用 `event_id` 关联；复议决定书与原处罚决定书用 `linked_ids` 关联。划分训练、验证、测试集时，同一 `event_id` 或 `linked_ids` 连通的案例整组放在同一侧（门禁 G1.3、R7）。

## 2. 数据集整体要求

| 要求 | 数量 / 比例 | 依据 |
|---|---|---|
| 行政案例金标总量 | ≥ 500 件，目标省份 ≥ 300 件 | 门禁 G1.1 |
| 2026 年新法施行后的行为 | ≥ 50 件 | 门禁 G1.1（T-time） |
| 不予处罚、不构成违法的案例 | **必须收**，不能只收被处罚的 | 门禁 G3.2 要求这一类单独达标 |
| 一般档、情节严重档 | 两档都要有，每档至少 100 件 | 档次要能学 |
| 复议、诉讼来源占比 | 测试集中 ≤ 50% | 门禁 §7；这类案件偏争议、偏重罚 |
| 新旧法两个时期 | 都要有 | 时间效力与迁移 |
| **信息完整度** | 至少一项金额 + 处罚结果齐全的案例 ≥ 80% | CAIL 教训：信息空白的案例占比高时，模型学不到东西 |

**只有结果、没有事实的条目**（D6，如汇总公示每条只写"因赌博"）：不进金标，单独交付 `admin_outcomes_only.jsonl`，字段同上但不要求 `text_facts`。引擎只用它看处罚结果的分布、核对 T-time 的结果，不用作 M1 或 M4 的训练标签；计算信息完整度时不计入。

## 3. 交付格式

- 交付主文件（历史 L1 分流，r6 不作标注底料）：`$JUSTILAW_DATA_DIR/delivery/<版本>/admin_cases.schema-1.0.0.jsonl`；结果条目：同目录 `admin_outcomes_only.jsonl`。每件一行（注意每行末尾要换行），字段如 §1。
- 同目录附 `SHA256SUMS`。
- 内部质量信息放进 `quality` 对象：`ocr`、`completeness`、`parse_warnings`、`ambiguous_persons`、`age_uncertain`、`facts_contains_conclusion`。
- 每行示例：

```json
{"id": "W-000123", "source_type": "处罚决定书", "doc_no_hash": "…", "harvest_date": "2026-10-16",
 "behavior_date": "2025-11-03", "decision_date": "2025-11-04", "authority": "××县公安局",
 "region": "130626", "law_version": "旧法",
 "subject_mention": "张某", "doc_no": "某公〔2025〕1号", "event_id": "E-…", "linked_ids": [],
 "schema_version": "1.1.0", "pipeline_version": "harvest-0.x",
 "text_full": "…", "text_sha256": "…", "segmented": true,
 "segments": {"text_facts": [120, 188], "text_decision": [230, 301]},
 "outcome": {"type": "拘留并处罚款", "detention_days": 5, "fine": 500, "…": "…"},
 "review": {"result": "无", "changed_outcome": null},
 "quality": {"ocr": false, "completeness": {"has_amount": true, "has_outcome": true},
             "parse_warnings": [], "ambiguous_persons": false, "age_uncertain": false}}
```

- 每批交付在[协作记录](../04-plan/collab-log.md)留一行：件数、来源构成、信息完整度和原文正本哈希。

**外发条款**：对外发布、论文附录或第三方共享前，须另行运行[文本处理规范](../04-plan/text-processing-spec.md) §4.2–§4.3 的衍生遮蔽与扫描，并经专项评审。内部验收器不承担外发检查。

**r6 用途边界**：r6 仅是交付格式关口和原文冻结参考。其分段来自旧 `parse.py` 正则，字段来自旧规则抽取，没有模型语义字段，**不可用于标注**。新链路以 `unified_raw` 为原料，经 S1/S2/S3 形成 `parsed-2`；标注可用性挂在 `parsed-2` 的 G2.2 质量证据包。

## 4. 引擎侧的验收（自动执行）

**工具**：`research/.venv/Scripts/python research/eval/accept_delivery.py [交付目录]`。报告写到 `$JUSTILAW_DATA_DIR/engine/acceptance/<管线版本>-<主文件哈希前 8 位>/`，包括 `acceptance.json`、一页摘要 `acceptance.md`、退回清单 `rejected.csv`。引擎对交付目录只读，所以报告**不**写进 `delivery/<版本>/`。要查某个交付版本对应哪份报告，看 `engine/acceptance/INDEX.csv`：每验收一次追加一行，记录交付版本、主文件哈希、报告目录、结论和时间。

**自动验收通过只说明交付格式与原文正本自洽。** 对 r6 尤其不代表标注可用；它不证明分段和字段准确，也不构成对外发布批准。`LATEST` 指针只表示"最新"，不表示"已验收"。

**逐条检查**（`records.check_delivery`，每条记录的全部问题一次列出）：
- 字段、类型、取值符合 §7 总表；渠道内部标记（页面编号、站点、来源网址等）不进入交付；
- 日期能解析（只到月记 info）；行为在 2026-01-01 之后的不能适用旧法；顶层与 `outcome` 的法律版本一致；
- `text_sha256` 与正文相符，`segments` 切出的文字与各段一致；
- `subject_mention` 记录本人原写法（来源未给出时可空）；不要求特定代称出现在事实段；
- 处罚类型与拘留天数、罚款金额相符；不超过该版本法定上限（上限取自规范库）。超过单项上限、但不超过合并执行上限 20 日的，记 warn；
- 事实段不含"决定给予""现决定""情节严重""从轻处罚""减轻处罚""从重处罚"（已标 `facts_contains_conclusion` 的除外）。

**批次检查**：
- 文件哈希与 `SHA256SUMS` 一致（发布后被改写即不通过）；
- 两份文件间 `id` 不重复；
- 一批只含一个本体版本和管线版本；
- `linked_ids` 指向的记录存在；
- 同一事件内行为日期相差不超过 31 天。

**结论**：
- **通过**：没有 error；
- **部分通过**：只有记录级 error，这些记录退回，其余仅在格式层通过；
- **不通过**：有批次级 error，整批退回。

门禁差距单独列出，不影响结论，包括信息完整度、新法件数、各档件数、不予处罚件数等。

**历史首次验收**（2026-10-16，harvest-0.4，主文件哈希 e87ec995；旧脱敏契约）：**部分通过**。主文件 881 条退回 12 条，869 条可进入标注；只有结果的文件 678 条退回 49 条。主要问题：
- 法律版本被按日期覆盖：13 条，均为从旧兼从轻、实际引用新法的案件；
- 只有结果的条目没有本人代称：46 条；
- 日期错误：1 条；
- 事实段含结论：1 条。

门禁差距：
- 信息完整度 40%；
- 2026 年后的行为只有 7 件；
- 不予处罚只有 2 件。

以上旧验收中的“可进入标注”为当时的历史表述，**不适用于 r6**。r6 的验收结论只针对格式；`accept-0.2.1` 起在报告中显式标 `annotation_ready=false`。

## 5. 决策记录（文本处理规范 §5）

| 编号 | 问题 | 决定 | 状态 |
|---|---|---|---|
| D1 | 年龄写整数周岁还是年龄段 | 原文保留来源写法；此项脱敏约定失效 | D-003 覆盖 |
| D2 | 日期粒度 | 原文保留来源写法，元数据尽可能到日 | D-003 覆盖 |
| D3 | 文号与来源 | 文号可明文保留；URL 等来源链接仍走台账，`doc_no_hash` 用于去重 | D-003 覆盖 |
| D4 | 复议"驳回" | 新增"程序驳回"；诉讼"驳回诉讼请求"记"维持" | 引擎已定（§1.4） |
| D5 | 本人定位与事件关联 | `subject_mention` 定位本人，`event_id`、`linked_ids` 保留 | D-003 部分覆盖（§1.6） |
| D6 | 只有结果的汇总条目 | 不进金标，单独交付 `admin_outcomes_only.jsonl` | 引擎已定（§2） |
| D7 | OCR 文本 | 冻结前人工通读 | 数据链路自定 |
| D8 | `law_version` 指什么 | 决定实际适用的版本（以引用法条为准），不是按行为日推算的版本 | 引擎已定（2026-10-16，首次验收发现 13 条被覆盖） |
| D9 | 各来源解析产物的格式 | 统一为解析层中间格式 `parsed-1`（§6），由构建脚本合并 | 引擎已定格式；各来源接入时间待定 |

## 6. 解析层统一中间格式（parsed-1）

**为什么要有**：网页、法宝、裁判文书三套解析器原来各出一种形状。统一之后，去重和事件分组只需实现一次，由构建脚本统一处理；各来源只负责"把原文解析成这一格式"。

**放在哪**：`$JUSTILAW_DATA_DIR/parsed/<来源>/<批次>/records.jsonl`，一个批次一个文件，同目录附 `stats.json`。写过的批次不改，重解析就出新批次（数据分层见[项目现状总览](../04-plan/project-status.md) §4）。

**和交付层的区别**：

| | 解析层 L1 | 交付层 L3 |
|---|---|---|
| 正文 | 渠道提取的原文 | 原文正本，附 `text_sha256` |
| 溯源 | `source_ref` 可以是网址；`batch` 指向原始层批次；`parser` 记解析器版本 | 台账 `id`、`doc_no_hash`，原始文号可保留 |
| 本人 | `subject_mention`：本人在正文中的原写法 | 原写法保留，供本人定位 |
| 分段 | 各段须是正文的连续子串，不要求起止位置 | 必须有 `segments` 起止位置和 `text_sha256` |
| 事件 | `event_key` 指纹（可选） | `event_id`、`linked_ids`（构建生成） |
| 分级 | `quality.tier`：parsed-1 历史 L1 有事实与结果 / L2 只有结果 / L3 范围外 / L4 待核 | r6 只收 L1（主文件）与 L2（只有结果的文件），不代表标注可用 |
| 来源专有字段 | 一律放进 `extra`（页面编号、站点、法宝引证码等） | 不得出现 |
| 缺失值 | `null` 或空字符串都可以；枚举字段的"未知"要写"未知" | 同左 |

**自检**：`cd justilaw-api && python -m app.discretion.records check <records.jsonl> --layer parsed`，按"问题:字段"汇总，列出例子，有 error 时退出码为 1。

**现有产物离 parsed-1 还差什么**（2026-10-16 自检）：

| 来源 | 只需搬字段（格式差距） | 要修的数据问题 |
|---|---|---|
| 公开网页（`harvest/parse.py`，4,906 条） | 补 `record_version`、`source`、`batch`、`parser`；把顶层的 `completeness`、`gambling`、`in_scope`、`ocr`、`parse_warnings` 移进 `quality`，加 `quality.tier`；`page_id`、`site`、`title`、`publisher`、`item_index` 移进 `extra` | 决定段不是正文子串 149 条；复议结论为空 127 条、仍写"驳回" 17 条（按 D4 改）；2026 年后行为标旧法 13 条；结果字段整组缺失 12 条；日期错 1 条；罚款超新法上限 1 条（多人合计？）；区划、省、机关全空 778 条 |
| 法宝执法库、案例库（`collect/pkulaw_ingest.py`） | 分配台账 `id`（目前为空）；补 `record_version`、`source`、`batch`、`parser`；`has_amount`、`has_outcome` 移进 `quality.completeness`；`pkulaw_id`、`event_hint` 移进 `extra`；`source_ref` 填法宝引证码 | 产物目前不在数据目录，接入后再自检 |
| 裁判文书采购（`collect/ingest_wenshu.py`） | 整体映射到本格式：`primary_key` → `extra`，补 `source_type`、`outcome`、`review`、`quality` | 还没有分段和结果抽取（只到清洗暂存） |

## 7. 字段总表（由代码生成）

<!-- records:begin -->
> 由 `records.py`（parsed-1）自动生成，请勿手改。

| 字段 | 类型 | 解析层 L1 | 交付层 L3 | 可为空 | 取值 | 说明 |
|---|---|---|---|---|---|---|
| `record_version` | str | 必填 | — | 否 |  | 解析层格式版本，固定为 parsed-1 |
| `id` | str | 必填 | 必填 | 否 |  | 台账 id，前缀标来源（W- 公开网页，B- 复议专栏，P- 法宝，C- 采购） |
| `source` | enum | 必填 | 可选 | 否 | 公开网页、复议专栏、法宝执法库、法宝案例库、裁判文书采购、合作案卷 | 来源渠道 |
| `batch` | str | 必填 | 可选 | 否 |  | 原始层批次名（raw/<来源>/<批次>/），用于追溯 |
| `parser` | str | 必填 | — | 否 |  | 解析器与版本，如 harvest/parse.py@0.4 |
| `source_type` | enum | 必填 | 必填 | 否 | 处罚决定书、不予处罚决定书、行政复议决定书、行政判决书、执法公示、合作案卷 | 文书类型 |
| `source_ref` | str | 必填 | — | 否 |  | 原文出处（URL、台账引用或法宝引证码）；交付层不得出现 |
| `doc_no` | str | 可选 | 可选 | 可 |  | 原始文号；交付层可随公开原文保留 |
| `doc_no_hash` | str | 可选 | 必填 | 可 |  | 规范化文号的 SHA-256 前 16 位，无文号时为空 |
| `harvest_date` | date | 必填 | 必填 | 否 |  | 采集日期 |
| `behavior_date` | date | 可选 | 必填 | 可 |  | 违法行为日期，持续行为取结束日；可只到月 |
| `decision_date` | date | 可选 | 必填 | 可 |  | 处罚决定日期 |
| `authority` | str | 可选 | 必填 | 可 |  | 作出决定的机关 |
| `region` | str | 可选 | 必填 | 可 |  | 行政区划代码；交付层必须有 |
| `province` | str | 可选 | 可选 | 可 |  |  |
| `province_code` | str | — | 可选 | 可 |  |  |
| `region_level` | str | — | 可选 | 可 |  |  |
| `law_version` | enum | 可选 | 必填 | 否 | 旧法、新法、未知 | 旧法（2012 修正）/ 新法（2025 修订）/ 未知 |
| `subject_mention` | str | 可选 | 可选 | 可 |  | 本人在公开原文中的写法，供本人定位 |
| `event_key` | str | 可选 | 可选 | 可 |  | 事件指纹：处罚机关 + 事实段首个日期 + 金额 |
| `event_id` | str | — | 必填 | 否 |  | 事件编号，同一事件多人共用 |
| `linked_ids` | list | — | 必填 | 否 |  | 关联记录（如复议决定书与原处罚决定书） |
| `text_full` | str | 必填 | 必填 | 否 |  | 公开文书原文正本 |
| `text_sha256` | str | — | 必填 | 否 |  | text_full 的 SHA-256 |
| `segmented` | bool | 必填 | 必填 | 否 |  |  |
| `segments` | dict | 可选 | 必填 | 否 |  | 各段在 text_full 中的 [起, 止) |
| `text_party` | str | 可选 | 可选 | 可 |  | 当事人段：本人身份、年龄或出生年月、违法经历，取正文中事实段之前的部分；不含其他当事人。要素 person.age、circumstances.last_prior_penalty_date 等主要靠它 |
| `text_facts` | str | 可选 | 必填 | 可 |  |  |
| `text_evidence` | str | 可选 | 必填 | 可 |  |  |
| `text_reasoning` | str | 可选 | 必填 | 可 |  |  |
| `text_decision` | str | 可选 | 必填 | 可 |  |  |
| `text_review` | str | 可选 | 必填 | 可 |  |  |
| `outcome` | dict | 必填 | 必填 | 否 |  | 处罚结果（见 OUTCOME_FIELDS） |
| `review` | dict | 必填 | 必填 | 否 |  | 复议、诉讼结论（见 REVIEW_FIELDS） |
| `quality` | dict | 必填 | 必填 | 否 |  | 质量与分级（见 QUALITY_FIELDS） |
| `schema_version` | str | — | 必填 | 否 |  | 要素本体版本 |
| `pipeline_version` | str | — | 必填 | 否 |  | 构建管线版本 |
| `extra` | dict | 可选 | — | 可 |  | 来源专有的内部字段（page_id、site、pkulaw_id 等）一律放这里 |
| `outcome.type` | enum | 必填 | 必填 | 可 | 不予处罚、不构成违法、警告、罚款、拘留、拘留并处罚款、移送刑事 | 处罚类型；L3/L4 分级的记录可为空 |
| `outcome.detention_days` | int | 必填 | 必填 | 否 |  | 拘留天数，没有填 0；合并执行取合并后 |
| `outcome.fine` | num | 必填 | 必填 | 否 |  | 罚款（元），没有填 0；源文把数额打码时填 0 并标 fine_masked |
| `outcome.fine_masked` | bool | 可选 | 可选 | 可 |  | 罚款数额被发布方打码（'罚款**元'）：类型可用，罚款额不能作训练目标 |
| `outcome.detention_not_executed` | enum | 必填 | 必填 | 否 | 是、否 |  |
| `outcome.confiscation` | str | 可选 | 可选 | 可 |  |  |
| `outcome.articles` | list | 必填 | 必填 | 否 |  |  |
| `outcome.stated_circumstances` | list | 可选 | 可选 | 可 |  |  |
| `outcome.law_version` | enum | 可选 | 可选 | 可 | 旧法、新法、未知 | 若给出须与顶层 law_version 一致 |
| `review.result` | enum | 必填 | 必填 | 否 | 维持、变更、撤销、确认违法、程序驳回、无 | 诉讼'判决驳回诉讼请求'记'维持'；复议驳回申请、裁定驳回起诉记'程序驳回' |
| `review.changed_outcome` | dict | 可选 | 可选 | 可 |  |  |
| `quality.tier` | str | 必填 | 可选 | 否 |  | parsed-1 历史分级：L1 有事实与结果 / L2 只有结果 / L3 范围外 / L4 待核；不表示标注可用 |
| `quality.in_scope` | bool | 必填 | 可选 | 否 |  |  |
| `quality.completeness` | dict | 必填 | 必填 | 否 |  | {has_amount, has_outcome} |
| `quality.parse_warnings` | list | 必填 | 必填 | 否 |  |  |
| `quality.form` | str | 可选 | 可选 | 可 |  | 页面或文书形态（叙述式、字段式、汇总、复议、判决书……） |
| `quality.gambling` | enum | 可选 | — | 可 | 是、否、待定 |  |
| `quality.ocr` | bool | 可选 | 可选 | 可 |  |  |
| `quality.facts_contains_conclusion` | bool | 可选 | 可选 | 可 |  |  |
| `quality.ambiguous_persons` | bool | 可选 | 可选 | 可 |  |  |
| `quality.age_uncertain` | bool | 可选 | 可选 | 可 |  |  |
<!-- records:end -->

## 8. 要素标签契约（L5，2026-10-18 补）

> 本节补 §1.5 的落地格式；字段唯一来源仍是 `schema.py` / `element_labels.py`，标注规则见 [annotation-guideline](./annotation-guideline.md)。本节不是新本体，是“数据线交什么给引擎”的契约。

### 8.1 记录单位

- **一人一条记录**；同一事件多人 → 多条记录，共用 `event_id`；不得把多人事实合进一人记录。
- `input` 只放事实/元数据视图：`target`、`subject_aliases`、`views[meta/facts]`、`facts_text`、`meta_text`。
- 不得把 decision/reasoning/review/outcome 放进 `input`；`observed_outcome` 单独存，作为历史处罚目标。

### 8.2 reference_elements

- 7 组 36 字段；每字段 `{status, value, evidence}`。
- `status` = 明确 / 推断 / 未提及；未提及必须 `value=null, evidence=[]`。
- 金额 `{min,max}`，`max=null` 表示开口；日期 ISO `YYYY-MM-DD`。
- `evidence` = `{quote,start,end}`，必须满足 `text_full[start:end] == quote`，只来自 facts/meta。
- `label_provenance` = teacher / model-adjudicated / human；`human_review` boolean；`release_approved` boolean。

### 8.3 binding

- 每个字段/证据标 `shared_fact` / `target_specific` / `needs_review`。
- 共同事实（现场赌资总额、参赌人数等）在每个相关人记录中重复并标 `shared_fact`；个人事实只归本人；无法判定标 `needs_review`。
- 引擎语义表 `research/eval/binding_rules.py`（8 shared / 28 target）是权威定义；**具体判定由数据/后处理实现**。`needs_review` 是显式未知，不静默当正确。
- 当前实现（2026-10-18 12:46，v4）：61 shared / 1120 target / 528 review；仍是字段默认映射，不是逐案证据判定；shared 已在 `resolve_binding` 代码接受，但 contract v4 的 `accept_in_resolve` 仍只写 lexical/target，artifact 与代码待统一；BIND-03/CONTRACT-01 未关闭。

### 8.4 验收

- schema/枚举/版本合法；证据逐字、坐标正确、来源仅 facts/meta；target 能在原文定位；input 无 decision/reasoning/outcome 泄漏。
- 金额/日期合法；`reference_elements` 非空；字段覆盖率；绑定小样本 precision/coverage；A/B 或人工复核记录。
- 首批 200–300 件；>20% 分歧回修提示；验收通过只代表“产标管线可继续扩量”，不等于人工字段准确率。

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-18 | v0.6 | 新增 §8 要素标签契约（L5）：一人一条、reference_elements、evidence、binding、验收；与 annotation-guideline/element-teacher-v1 对齐 | 协调层代笔（引擎线复核） |
| 2026-10-17 | v0.5.1 | 更正 r6 用途：格式关口和原文冻结参考，不可用于标注；标注可用性由 parsed-2 G2.2 质量证据包决定 | 模型组（引擎） |
| 2026-10-17 | v0.5 | 按 D-003 改原文正本；删除主管线脱敏与 R6 字段及验收项，`subject_mention` 定位本人，原文文号可保留；新增外发条款；字段总表同步 `records.py` | 模型组（引擎） |
| 2026-10-15 | v0.1 | 初版：基于 CAIL 探针教训，规定来源、时间地点、原文分段、处罚结果标签、事实要素、整体构成与交付格式 | 模型组 |
| 2026-10-17 | v0.4 | §1.3 新增当事人段 `text_party`（I-02，两层都可选，旧交付不受影响）；§1.4 新增 `outcome.fine_masked`，复核法宝线提出的源文打码豁免，并改为正式字段，因为交付层没有 `extra`；§4 增加验收索引 `INDEX.csv`，并写明"自动验收通过"不等于"内容安全放行" | 模型组（引擎） |
| 2026-10-16 | v0.3 | 新增 §6 解析层统一中间格式 parsed-1（与交付层的区别、自检命令、三个来源的差距）与 §7 字段总表（由 `records.py` 生成）；§4 改为自动验收工具与三档结论，记录首次验收结果；`law_version` 定义为实际适用版本（D8）；决策 D9 | 模型组 |
| 2026-10-16 | v0.2 | 按文本处理规范 §5 决策 D1–D6 修订：溯源走台账（`doc_no_hash`），日期元数据到日、正文到月，`law_version`，正本冻结与 `segments`，`review.result` 新增"程序驳回"并明确诉讼"驳回诉讼请求"记"维持"，`subject_alias`、`event_id`、`linked_ids`，年龄写法，汇总条目单独交付，`quality` 对象，验收检查补充；新增决策记录 | 模型组 |
