# 要素标注指南

> 版本 v0.1（试标前草稿）· 2026-10-15 · 对应门禁 G0.3
> 字段定义的唯一来源是 `justilaw-api/app/discretion/schema.py`；本文 §4 的字段表由它自动生成。
> 配套：[固定对照与阶段门禁](./sota-baselines-and-gates.md) · [数据收集计划](../04-plan/data-collection.md) · [并行工作流与分工](../04-plan/workstreams.md) §5

## 1. 总原则

1. **只标事实，不标法律结论。** 例如标"上次受治安处罚的日期 2025-08"，不标"一年内受过处罚"；是否构成从重由规范层按适用的法律版本判断（2012 版是六个月，2025 版是一年）。
2. **每个有值的字段都必须附原文证据**：从案情中逐字复制一段连续文字，不改写、不拼接。一个值需要多处原文支持时，附多段证据。
3. **状态三选一**：
   - **明确**：原文直接写明；
   - **推断**：原文没有直接写明，但由上下文可以合理推出，仍须附据以推断的原文；
   - **未提及**：原文没有相关信息，值留空。**不确定时选"未提及"，不要猜。**
4. 一份案卷有多名违法行为人时，**每人一条标注**，只标该人自己的要素；涉及共同事实（如现场赌资、参赌人数）的字段，每人都标。

## 2. 数额

- 单位一律为**元**；"1.2 万"记 12000。
- 确切数额：最小值 = 最大值。
- "三千余元"记 3000–3999；"约 5 万元"记 45000–55000；"数百元"记 200–999。
- 原文给出"人均"而无个人数额时，个人赌资标"推断"，证据引用人均那句。
- 抽头渔利、台费、头钱、"水钱"都归入 `amounts.commission`。

## 3. 日期与人员

- 日期只写到月份时取该月 1 日，状态标"推断"。
- 年龄按**行为时**的周岁；只有出生年份时按 7 月 1 日估算并标"推断"。
- "情节轻微 / 情节特别轻微"只在原文（如处罚决定书、复议决定书）明确写出时才标，不要自行判断。

## 4. 字段表

<!-- schema:begin -->
> 由 `schema.py`（v1.0.0）自动生成，请勿手改。

| 字段 | 说明 | 关键字段 |
|---|---|---|
| `conduct.behavior_type` | 本人的行为类型。只按事实描述判断，拿不准时选最接近的一项并标'推断' | 是 |
| `conduct.role` | 本人在赌博活动中的角色 | 是 |
| `conduct.method` | 赌博方式 | 是 |
| `conduct.times` | 赌博或提供条件的次数（场次） |  |
| `conduct.duration_days` | 持续时间（天），如'持续三个月'记 90 |  |
| `conduct.cheating` | 是否以作弊手段赢取财物（可能转为诈骗） |  |
| `amounts.personal_stake` | 本人的赌资：本人用作赌注、换取筹码的款物及赢取的款物（元） | 是 |
| `amounts.per_bet` | 单注或每局输赢的金额（元） |  |
| `amounts.onsite_stake_total` | 现场查获的赌资合计（元） | 是 |
| `amounts.cumulative_stake` | 累计赌资（元），多次赌博累计 |  |
| `amounts.commission` | 抽头渔利、台费、头钱等从赌博中获取的收入（元） | 是 |
| `amounts.illegal_gain` | 其他违法所得（元） |  |
| `persons.participant_count` | 参赌人数（同一场次在场参赌的人数，不含本人以外的围观者） | 是 |
| `persons.cumulative_participants` | 累计参赌人数（多场次合计） |  |
| `persons.minors_involved` | 是否有未成年人参赌 |  |
| `persons.civil_servant` | 本人是否为国家工作人员 |  |
| `persons.relatives_only` | 参与者是否均为亲属 |  |
| `persons.abroad_organized_count` | 组织中国公民出境赌博的人数 |  |
| `venue.venue_type` | 赌博场所类型 |  |
| `intent.profit_purpose` | 是否以营利为目的。有抽头、收台费、经营性收费等事实时为'明确'；仅凭金额大小判断时标'推断' | 是 |
| `circumstances.last_prior_penalty_date` | 本人最近一次受治安管理处罚的决定日期；只写到月份时取该月 1 日并标'推断' | 是 |
| `circumstances.surrendered` | 是否主动投案 |  |
| `circumstances.truthful_statement` | 是否如实陈述违法事实 |  |
| `circumstances.admits_and_accepts` | 是否承认违法事实并愿意接受处罚（认错认罚） |  |
| `circumstances.remedied_consequence` | 是否主动消除或减轻违法后果 |  |
| `circumstances.victim_forgiveness` | 是否取得被侵害人谅解 |  |
| `circumstances.coerced_or_lured` | 是否出于他人胁迫或诱骗 |  |
| `circumstances.meritorious` | 是否有立功表现 |  |
| `circumstances.instigated_others` | 是否教唆、胁迫、诱骗他人参与 |  |
| `circumstances.retaliation` | 是否对报案人、举报人、证人打击报复 |  |
| `circumstances.obstructed_police` | 是否阻碍民警执行职务 |  |
| `circumstances.minor_circumstance` | 原文明确认定的'情节轻微'或'情节特别轻微'（只记原文认定，不自行判断；2012 版减轻条件是'特别轻微'，2025 版是'轻微'） |  |
| `circumstances.first_offense` | 是否初次违反治安管理 |  |
| `circumstances.violations_last_year` | 本次行为前一年内违反治安管理的次数 |  |
| `person.age` | 行为时的周岁年龄 | 是 |
| `person.pregnant_or_nursing` | 是否怀孕或哺乳自己不满一周岁的婴儿 |  |
<!-- schema:end -->

## 5. 质量控制（门禁 G0.3 / G1.2）

- 试标：50 件双人独立标注，分类字段 Cohen's κ ≥ 0.80，数值字段完全一致率 ≥ 95%；不达标就修订本指南后重试，最多 2 轮。
- 正式标注：至少 20% 双人标注；分歧由第三人仲裁，并把仲裁结论补进本指南。
- 指南每次修订都要在变更日志中记录；`schema.py` 改字段时同步提升版本号，并在[协作记录](../04-plan/collab-log.md)中通知数据链路。

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-15 | v0.1 | 初稿：总原则、数额与日期规则、字段表（schema v1.0.0） | 模型组 |
