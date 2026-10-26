# 要素供给链 S1→S2→L5 执行契约 v0.1

> 发布日期：2026-10-21；状态：**供给链执行设计已定，代码接入与消费方验收未完成**。本文件规定输入视图、事件关系中间表示、候选与推导、失败去向及评测口径；不修改引擎 36 字段 schema，不把设计发布等同于 silver 放行。
>
> 适用范围：S1 事实视图进入 S2 候选/绑定，再进入 L5 教师、证据编译及标签组装。`M4` 的 `observed_outcome` 始终为独立目标列。

## 1. 权威与决定边界

| 内容 | 唯一权威 | 本契约的决定 |
|---|---|---|
| 36 字段名称、类型、字段语义、三态与 `CaseMeta` | 引擎 [`schema.py`](../../../justilaw-api/app/discretion/schema.py)、[`annotation-guideline.md`](../annotation-guideline.md) | 原样消费 schema 1.1.0；不新增字段或更改含义 |
| 哪些字段为 `shared_fact` / `target_specific` | 引擎 [`binding_rules.py`](../../../research/eval/binding_rules.py) | 只规定如何给具体证据建立场景与主体边；不重分 8/28 字段 |
| 金额、日期、时长的最终字段值与证据合法性 | 引擎 [`normalization_spec.py`](../../../research/eval/normalization_spec.py)、[`evidence_contract.py`](../../../research/eval/evidence_contract.py) | 候选层保留原始语义；投影时调用/逐项对照引擎 E-05，不能以 JioNLP 输出覆盖 |
| 事实片段的可见性、事件/关系中间表示、候选 ID、弃权原因、推导溯源 | 后处理/供给链 | 按本文件固定 v0.1；实现可换，外部语义不变 |
| 字段语义、值类型、证据允许区域或状态需要改变 | 引擎 `SCHEMA_VERSION` 升版并登记 | 本文件只列冲突和变更请求；在升版前不得自行发布不同口径的标签 |

本文件是**实施契约**，不是第二份字段标注指南。遇到文字示例与引擎现行代码/指南冲突，暂停该字段投影，记录 `engine_contract_conflict`；不暗中择一。跨线消费以具体 schema 版本、策略版本和输入哈希为准。

## 2. 输入与可见事实契约

### 2.1 一条输入必须携带

- `record_id`、来源记录的 `event_id`（内部记为 `case_event_id`）、`target`、已解析的 `aliases`、原文 SHA-256、S1 输出版本/哈希、`view_hash`、原文坐标基准。`case_event_id` 是**跨记录分组/切分 ID**，不能直接充当文内某一次赌博的 `scene_id`。
- 可见源片段的 `span_id/start/end/quote/zone/role/source/sentence_id`。坐标均为同一冻结正文的 0 起、左闭右开；必须满足 `text_full[start:end] == quote`。片段有序、不重叠；从两段文字推导一个值时分别引用两段，不拼接成假引文。
- `view_hash`、原文哈希或坐标不一致，目标本人不能唯一定位，或者允许视图中有处罚结果/法条答案泄漏时，整条输入进入 quarantine，不调用教师，也不产生 accepted 标签。

### 2.2 事实可见性

1. L5 只消费经核验的事实/身份片段；处罚结果仅进入独立 outcome 通道。不得因整句被 S1 标为 facts 就允许其中的决定、说理、法条子片段进入教师。
2. 同一句混有行为事实和决定时，在原文坐标上分别划定片段。事实子片段可入视图；决定子片段不得入视图。若不能无歧义拆分，设 `input_visibility_ambiguous`，不得以整句放行。
3. 实质事实被 S1 放入 evidence/reasoning 时，可通过**显式、源文定位的事实片段复核**重新入事实视图，保留旧 zone、新 role、裁定来源及版本。自动词形命中只能提出候选，不能自行改变可见性。decision/review 中的内容不得通过这种路径绕过引擎证据来源规则。
4. `context_time` 仅给已绑定的行为/情节提供时间锚；单独的日期、文号或出生信息不能证明一次赌博行为。事实/身份覆盖不足以判定某字段时，记 `input_fact_gap`，不把缺失视图解释为原文没有该事实。

这使 S1 的漏取、混句和 S2 的绑定错误可以分别归因。后处理工作树 `research/discretion/unify/fact_spans.py` 的子句表可作定位起点；该文件尚未进入本工作树，其 cue 召回与是否接入生产仍须单独验收。

## 3. 事件与关系中间表示

### 3.1 三个不同的身份

| ID | 含义 | 禁止的替代 |
|---|---|---|
| `case_event_id` | 多份文书/多名当事人关联的同案切分组 | 不等于一次行为场次 |
| `scene_id` | 文内一场可区分的赌博/提供条件行为及其参与者 | 不用句号、文书 ID 或 `case_event_id` 直接代替 |
| `economic_item_id` | 一笔可区分的赌资、抽头收入、其他所得或其合计 | 不用相同数值或同一字符串位置直接代替 |

`scene_id` 只在证据支持时间、地点、参与者或行为连续性时合并跨句信息。同一文书、同一天或同一案号**不足以单独证明同一场**；证据不能区分时保留多个候选场景和 `event_link_ambiguous`。共享字段只向被证实参与该场的目标传播。

### 3.2 最小事实主张 `claim`

每个主张保存 `claim_id`、`source_span_ids`、`predicate`、`actor_ids`、`patient_ids`、`scene_id`（可 unresolved）、`time_ref_ids`、`quantity_ref_ids`、`polarity`（肯定/否定/不明）、`modality`（已发生/拟议/转述/不明）、`assertion_source`（事实、历史处罚、查获、决定、复议/诉讼）及模型/规则来源。谓词至少区分参赌、持有/投入赌资、抽头/收费、提供场地、组织、查获、历史处罚、处罚决定。

候选关系边至少区分 `actor_of`、`participant_of`、`owns_amount`、`amount_of_action`、`found_at_scene`、`part_of_total`、`same_entity` 和 `temporal_anchor`。边须指向源片段并附 `explicit/inferred/unresolved`，不能仅因人物与金额相邻就形成已确认边。

否定、条件、引用法条、处罚结果和他人陈述不能被当成肯定的本人行为。`各/分别`支持分配到名单成员；`共/合计`先建立集体或合计主张，不向每人复制金额；多人并列本身不强制弃权。

## 4. 候选、归一化和推导

### 4.1 候选格式

候选至少有 `candidate_id/type/source_span_id/start/end/raw/unit/parse_status/normalizer_version`；`start/end` 精确指向候选词面，满足 `text_full[start:end] == raw`，且包含在父片段内。数值候选另外保存 `kind`（exact/interval/lower_bound/upper_bound/approximate/unknown）、`lower/upper`、两端开闭、运算符及后端提示。`candidate_id` 由原文哈希、候选坐标和类型稳定生成；不依赖运行顺序。原表达与标准化结果并存，后端提示不得直接当引擎字段值。

金额、人数、场次、设备台数、日期、持续时间是不同类型；只有单位与谓词关系同时相容才可成为字段候选。例如“3 台赌博机”不能默认为 `persons.participant_count=3`。相同金额的两处提及先判断是否同一经济项目；同一处提及可以在政策允许时支持多字段，不设“一个 span 只能用一次”的全局约束。

### 4.2 字段投影

- 金额、日期、时长按引擎 E-05 投影；保存 `engine_schema_version`、`normalization_policy_version`、投影前值和 `losses`。`3000余元`、`约5万元`、`万元以上`等以引擎指南为准；开闭区间与近似的内部信息即使现行 36 字段无法完整表达，也必须留在 sidecar，不能被静默抹除。
- `conduct.times` 是目标本人参与赌博或提供条件的**场次**，不是同句人数、设备数量、赌博局数或文书数量。跨场累计、多人共同场次等须先有场景归属与引擎字段规则；无充分证据时不加总。
- `persons.participant_count` 是同一场在场参赌人数；围观者、望风者、机器数量不计入。`persons.cumulative_participants` 不得把相同参与者跨场简单相加，除非引擎政策明确采用人次口径。
- `amounts.personal_stake` 须有本人对该经济项目的持有/投入/赢取关系；`amounts.onsite_stake_total` 须有场景级现场查获合计关系；`amounts.commission` 须有抽头、头钱、水钱、台费等收入关系。只有词面“现场”或“赌资”不足以判定。`illegal_gain` 与 commission 的去重依据是**经济项目关系**，不是数值相等。
- `age`、持续时长、合计金额、由名单得出的人数等派生值引用 `derivation_id`，其中列出多个操作数候选、运算、目标、场景、每项证据和引擎政策。行为日期若来自 `CaseMeta`，只有能回到允许的事实/身份片段且引擎证据规则许可时才能作 L5 推导证据；否则年龄推导保持 unresolved。不得让模型直接写一个无推导链的最终数字。

如果引擎 E-05 无法机械解析、来源不支持投影、端点开闭无法无损表达，或必要运算缺乏政策，记录 `normalization_unresolved` / `projection_loss_unapproved` / `aggregation_policy_missing`，不借用同页另一金额补齐。

## 5. 绑定、弃权与输出

1. 硬校验仅处理可确定事项：源文坐标、允许视图、字段类型、否定/决定排除、经济项目重复引用、已知人物/场景边以及引擎字段约束。语义关系的歧义由教师或模型化/混合组件判定；不能以规则邻近分数独自完成 `shared/target/review` 判定（现行决策 B-10）。ILP 只能作为候选解码器，所用约束和目标分数须先在样例上验证。
2. `shared_fact` 表示字段语义属于场景，并且**目标有该场参与关系**；`target_specific` 表示值有目标本人关系。目标与源中另一人不能仅因同句出现就视为同一主体。`needs_review` 是内部关系状态，不是第 37 个要素字段。
3. 绑定结果引用 `field/target_id/scene_id/claim_ids/candidate_ids` 或 `derivation_id`、证据片段、决定来源、`binding_status`（bound/unresolved/rejected）与原因码。不能只返回最终字段值及一句整句证据。
4. 区分 `source_absent`（核验后的完整允许视图确实没有相关事实）、`input_fact_gap`、`candidate_missing`、`subject_ambiguous`、`event_link_ambiguous`、`relation_ambiguous`、`normalization_unresolved`、`engine_contract_conflict`。后六者不得静默转为 `未提及`。
5. 内部 sidecar 保存逐字段 `accepted/quarantined`。对 quarantined 字段，消费者有字段掩码能力时可只排除该字段；没有掩码能力时整条记录不得作为 accepted 训练标签。36 字段结构占位不代表该字段可训练。`未提及`仅按引擎三态规则和通过输入完整性检查后的无事实情况发布。
6. 最终 `elements` 仍只含 7 组 36 字段。`CaseMeta` 与 `observed_outcome` 分列；M4 训练输入不含 observed outcome。发布记录必须附 `input_hash/view_hash/schema_version/policy_version/binding_contract_version/provenance/split/field_disposition`，测试划分不得用于调参或检索库构建。

### 5.1 中间产物的最小 wire 形状

以下键和类型为 v0.1 必需项；数组可为空，引用的 ID 必须存在于同一产物或明确的源登记中。实现可以增加带命名空间的诊断键，但不能用新增键绕过上述放行规则。

```json
{
  "binding_contract_version": "supply-binding-0.1",
  "source": {
    "record_id": "R-1", "case_event_id": "E-1", "target_id": "P-乙",
    "text_sha256": "<sha256>", "view_hash": "<sha256>",
    "s1_version": "<version>", "schema_version": "1.1.0"
  },
  "visible_spans": [
    {"span_id": "S-1", "sentence_id": "T-1", "start": 0, "end": 12, "quote": "乙赌博时持有赌资500元", "zone": "facts", "role": "behavior_core", "source": "s1"}
  ],
  "mentions": [
    {"mention_id": "M-1", "source_span_id": "S-1", "start": 0, "end": 1, "raw": "乙", "person_id": "P-乙"}
  ],
  "persons": [
    {"person_id": "P-乙", "target": true, "mention_ids": ["M-1"]}
  ],
  "scenes": [
    {"scene_id": "SC-1", "kind": "gambling_activity", "support_span_ids": ["S-1"], "membership": [{"person_id": "P-乙", "state": "explicit", "support_span_ids": ["S-1"]}]}
  ],
  "economic_items": [
    {"economic_item_id": "EI-1", "kind": "stake", "quantity_candidate_ids": ["Q-1"], "identity_status": "explicit"}
  ],
  "claims": [
    {"claim_id": "C-1", "predicate": "hold_stake", "actor_ids": ["P-乙"], "patient_ids": [], "scene_id": "SC-1", "economic_item_id": "EI-1", "time_ref_ids": [], "quantity_ref_ids": ["Q-1"], "polarity": "positive", "modality": "actual", "assertion_source": "fact", "source_span_ids": ["S-1"], "provenance": "example_relation_model"}
  ],
  "quantities": [
    {"candidate_id": "Q-1", "type": "amount", "source_span_id": "S-1", "start": 8, "end": 12, "raw": "500元", "unit": "CNY", "parse_status": "resolved", "kind": "exact", "lower": "500", "upper": "500", "lower_inclusive": true, "upper_inclusive": true, "operator": "=", "normalizer_version": "<version>"}
  ],
  "relations": [
    {"relation_id": "REL-1", "kind": "owns_amount", "from_id": "P-乙", "to_id": "EI-1", "status": "explicit", "support_span_ids": ["S-1"]}
  ],
  "derivations": [],
  "bindings": [
    {"field": "amounts.personal_stake", "target_id": "P-乙", "scene_id": "SC-1", "claim_ids": ["C-1"], "candidate_ids": ["Q-1"], "derivation_id": null, "evidence_span_ids": ["S-1"], "binding_status": "bound", "decision_source": "example_relation_model", "reason": null}
  ],
  "field_disposition": {"amounts.personal_stake": {"status": "accepted", "reason": null}},
  "unresolved": []
}
```

示例中的人物和原文完全虚构；`start/end/quote` 在真实产物中仍须逐字通过冻结正文校验。`visible_spans` 只保存可见片段；被排除的源片段另存审计登记，不能作为教师候选。若 `scene_id`、经济项目身份或目标归属不确定，相关引用留空并在 `unresolved` 中列出原因，不能伪造一个确定 ID。

## 6. 最小判例和不变量

| 源事实片段 | 正确关系/结果 | 应拒绝的捷径 |
|---|---|---|
| `甲持有赌资300元，乙持有赌资500元。`，目标乙 | 乙的 personal_stake 候选为 500；300 属甲 | 以整句证据把 300 绑给乙；把两人相加为乙的 800 |
| `甲、乙各出300元，共600元。`，目标乙 | “各”建立乙→300；“共”建立场景合计→600 | 多人列表一律 review；把 600 当乙个人赌资 |
| `现场查获赌资3000元。`，目标乙 | 仅在乙被证实参与该场时，3000 可投 onsite_stake_total | 把任意同案目标都接到该场 |
| `甲使用3台赌博机。` | 3 的类型是设备台数 | 投到 participant_count 或 times |
| `甲未抽头，乙抽头300元。`，目标甲 | 甲的抽头为否定/无正金额主张；乙的 300 不属于甲 | 因“抽头”与 300 同句就给甲 commission |
| `甲于1月、3月各赌博一次；2月受到治安处罚。` | 两次本次行为与一次历史处罚分开；日期均有事件角色 | 把处罚日期当第三次赌博或把日期全合并为一场 |
| `甲主动投案自首。现决定罚款500元。` | 前一 span 可作为事实；后一 span 只入 outcome | 因整句/整段混合而整体纳入或整体丢弃 |

这些是关系与输入契约的预期样例，金额/日期最终字段值仍经引擎 E-05 与 schema 校验。

## 7. 验证与发布门

- **契约测试**：上述判例及否定、同额不同项、总额/子项、多场同日、跨句指代、模糊日期/金额、S1 混句、坐标错位的变形样例；每例检查主体、场景、角色、值来源及弃权原因。测试数据必须给出明确预期关系，不以现有解析器输出作答案。
- **真实数据诊断**：按字段、渠道、输入来源报告 S1 可见性缺口、候选证据命中、归一化未解析、关系未解析、字段隔离、最终有值率。203 silver 只作相对参照；其证据不是穷尽 mention 标注，不能据此报告候选总体 precision/recall 或真实 binding accuracy。40 条 test 继续封存，不能建 RAG 索引或调约束。
- **复杂方法准入**：先报告简单候选 + 模型关系选择 + 确定性校验的基线，再分别消融 SRL、ILP 和 RAG；以主体/场景错绑率、可用覆盖率和字段隔离率判断增益。模型自报置信度不直接当风险校准。
- **发布资格**：设计文档发布不改变运行中的 `release_approved`。代码接入需按版本产回放及质量报告，由消费方在冻结输入上验收；silver 仍不是 gold。

## 8. 需引擎升版或明确答复的三个接口冲突

1. **`推断 + null`**：引擎指南及 [`element_labels.py`](../../../justilaw-api/app/discretion/element_labels.py) 允许 `times`、模糊年龄/人数等场景，但后处理工作树 `research/discretion/unify/element_contract.py` 的 `reference_schema` 要求非 `未提及` 的 `value` 非 null；`schema.py` 的 `Extracted` 模型也拒绝非未提及 null。该后处理文件尚未进入本工作树。供给链不自行改三态语义；在统一前，这类字段标 `engine_contract_conflict` 并隔离。
2. **`minor_circumstance` 的可见性**：字段要求原文明确认定，而事实视图排除说理/决定中的法律认定。若认定只出现在被禁区域，供给链不能从中取证，也不能把“未入视图”声称为“原文未提及”。引擎须决定字段在 facts-only 教师中的资格，或升版证据来源规则。
3. **数值投影的边界损失**：内部表示区分 `>`/`>=`、`<`/`<=`、近似与无上界；现有 `{min,max}` 及部分归一化适配无法逐项表达。引擎须明确哪些损失允许投影，哪些字段必须隔离；期间 sidecar 完整保留原表达和损失。

上述三项不妨碍输入视图、事件关系、候选和 sidecar 契约先实施；它们妨碍相应字段作为 accepted 标签发布。由引擎统一其本体/验证器后，本文件只更新版本映射，不另立第二权威。
