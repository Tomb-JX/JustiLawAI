# 数值抽取与归一化设计核查（2026-10-21）

> 2026-10-21 复审：下文“目标抽取算法”主要是工程分层，并未证明能降低语义判断的模型依赖。算法判断已由[结构化推断复审](2026-10-21-numeric-structured-inference-review.md)替代；本页保留现状盘点和调用链核查。

## 当前事实

数值“抽取”和“解析”是两项不同任务。`supply_packet.py` 先用五组正则在允许视图里找子串，命中后才调用 E05 解析。`element_contract.py` 的教师契约仍让模型直接填最终字段值，只回句 ID，不回数值子区间、操作数或语义边；`check_money_support` 另用金额正则作硬门槛。E05 不能发现未提交给它的表达。

163 条 train/valid 银标的证据内直接候选覆盖：金额 147/147、参赌人数 37/61、年龄 8/59、次数 1/1，总计 193/268。51 个年龄需要出生日期与事件日期推导；24 个人数缺口中 23 个需要人员列举去重，1 个是“6名参赌人员”结构。另有 10 处遮蔽金额没有成为候选。该结果只衡量相对银标证据的候选覆盖，不是人工金标准确率。参见[复跑报告](2026-10-21-numeric-supply-recall-audit.md)。

## 归一化实现盘点

| 使用处 | 实际入口 | 现状 |
| --- | --- | --- |
| 当前 L5 新候选包 | `supply_packet._normalized` → 旁支 E05 `normalization_spec` → `app.discretion.normalization` | 数值解析复用 E05；候选抽取、原文比较符另写在本地。 |
| 当前 L5 教师字段 | 模型直接输出引擎最终值；`check_money_support` → 引擎 `extract.parse_amount`，必要时 S3 `_text_numbers`；再调用 E05 对账 | 同一个值经历多种、能力不同的判断；句级证据不能指明数值子串。E05 对账对无法机械解析的文本会返回 `True`，不能证明一致。 |
| 旧诊断图 | 金额/日期调用 E05；计数调用本地 JioNLP `normalize_quantity` | 同一图内解析后端混用；且此图不在 L5 主产物的关系求解路径。 |
| 本地 `normalization.py` | JioNLP 的 `normalize_time/quantity`，附 E05 代理函数 | 前者有更丰富的精度、开闭端点与锚点表示；契约包标为 `proposed_pending_engine_adoption`，不能当作已经批准的字段值政策。 |
| M1 | 本工作树 `justilaw-api/app/discretion/extract.py` 有自己的 `cn_to_number/parse_amount/parse_int/parse_date`；引擎旁支 M1 已改为统一调用 `app.discretion.normalization` | 两个工作树代码不同。E05 的旁支收敛不等于本分支和整条数据链已收敛。 |
| S3/采集 | `s3._text_numbers` 和 `harvest/parse.py`、`collect/pkulaw_ingest.py` 各自解析 | 前者用于处罚结果对账；后两者服务采集/元数据，输入可见性、字段语义不同，不应直接拿来判 L5 赌博事实字段。 |

因此应统一**L5/M1 字段值的规范化入口与中间语义**，同时保留采集清洗的专用解析器，但不得让它们悄悄决定 L5 字段值。`normalize_amount` 的 `{min,max}`、`normalize_count` 的 `{min,max,exact}`、日期的 `(date,status)` 和 JioNLP 的开闭端点对象目前不是同一个无损表示；“都能调用 E05”不等于语义已经一致。特别是金额用 `float` 且上下界开闭、近似政策只能另行补注；粗日期投影到月首/年中，若无精度标记容易被当成精确日期。

## 目标抽取算法：先找来源表达，再解关系，最后投影字段

### 1. 可见性与来源坐标

只给 S2/L5 当前允许的 facts/meta 原文片段、target、aliases 和句 ID。每个模型提出的对象必须回 `{sentence_id,start_in_sentence,end_in_sentence,quote}`；服务端换算到 `text_full` 的半开区间，逐字校验原文、哈希和允许视图。引用不唯一时要求模型给坐标；不做模糊匹配自动修正。decision/review/outcome 不进入教师抽取。

### 2. 开放式 mention 抽取，不以正则候选为前置条件

模型先按片段列举**所有与行为事实可能有关的数量表达**，输出类型（金额、人数、年龄、次数、时长、日期）、原文子区间及邻近的单位/限定词；同时提出人名或代称、行为、钱款项目和否定/历史/假设标记。此步不填 36 字段，不做数值计算。无单位金额、表格标签值、中文大写、遮蔽值都应保留原文提及；遮蔽值可标 `unparseable`，不能凭上下文补数。正则/JioNLP 检出的额外片段并入候选池，标明 `source=rule`，仅用于补漏和主动复核，不能成为模型可选范围的上限。

对冗长文书按允许视图分块并做重叠窗口；跨块的人物/场景合并依据可验证的来源边，不按金额相同合并。每一块有显式 `none_found` 或 `incomplete` 状态，防止空列表被误当“未提及”。

### 3. 建证据边与推导链

模型对 mention 提议类型化边：`person participates_in scene`、`claim asserted_in scene`、`claim refers_to quantity`、`economic_item owned_by person / shared_by scene`、`claim has_role personal_stake/onsite_stake/...`、`time anchors scene`。每条边带原文来源区间、提出者和 `proposed/confirmed/review` 状态。模型提议不自动确认；服务端检查端点存在、证据可见、单位与字段兼容、否定/既往隔离、同值不同主体不可合并；无法机械证明语义的边保留待核或进入独立复核。

直接数值 `quantity` 必须引用 mention。非直接数值另建 `derivation`，列明操作、输入 ID、时间/去重政策及输出：年龄=`birth_date + target behavior_date + 周岁规则`；人数=`参加同一场景的去重 person IDs`；合计/分摊仅在原文关系明确时计算。无精确行为日期或参与人范围不完整时输出区间/待核，不伪造确数。

### 4. 单一规范化入口与字段投影

规范化器只接受已逐字定位的短原文表达和类型提示，返回**无损中间值**：原文、来源区间、单位、精度、精确/范围/上界/下界/约数、端点开闭、解析版本与失败原因。日期保留年/月/日精度及锚点来源；时长区分固定天数与日历月；遮蔽和不支持的表达返回未解析。可先以引擎 E05 为数词/日期底层实现，但其 `float` 和 `{min,max}` 输出不能独自充当无损中间契约。JioNLP 仅作可替换解析后端或差异诊断，不并行产生第二种权威字段值。

最终由一个版本化投影器把已确认的 mention/边/推导转换为引擎 36 字段的 `{status,value,evidence}`。确数、区间、约数、开区间、粗日期等如何投影要记录政策及信息损失；不满足政策的值弃权，不把“无法解析”记作“未提及”。当前教师 A/B/C 可以保留作为独立字段意见，但需把意见和图投影的冲突显式送审，不能仅凭句 ID 通过数值校验。

## 实施顺序与验收

1. 先发布 `mention/edge/derivation` 的独立中间契约和离线解析适配器；保留现有 36 字段接口。定义字段级缺失、待核、遮蔽、冲突状态。不要先扩大正则词表。
2. 在 train/valid 163 条上做 shadow run：固定输入和版本，让开放式模型抽取与现有正则候选并行；记录每个银标证据内的 span 命中、类型、解析、主体/场景/金额角色、推导、最终投影。规则独有、模型独有、双方都漏分开统计。只对差异样本做必要的人工/独立裁决；银标仍只称参考。
3. 对金额同值异人、个人与现场总额、出生日期推龄、列举人数、遮蔽额、无单位表格值、开区间和粗日期建立冻结反例。分别报告 mention 召回、给定正确 span 的解析率、边正确率、推导正确率、字段值一致率、弃权率及 silent-wrong；按单/多人、来源、文长分层。test40 保持封存，设计冻结后再按门禁评估。
4. 当新路径通过字段级门槛，再把教师 wire 从“句 ID + 自由数值”迁到“来源 mention ID/推导 ID + 边引用”；最后替换 `check_money_support` 的正则硬门槛。不能在缺少来源 span 的情况下直接删门槛。

此文是设计结论，不表示开放式 mention 抽取、关系确认和推导链已经实现，也不表示旁支 E05 代码已合并到当前工作树。
