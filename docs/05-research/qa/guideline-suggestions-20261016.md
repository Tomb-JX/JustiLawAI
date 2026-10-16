# 标注指南修订建议（金标质检线 · 2026-10-16）

> 依据：pilot50 代理试标冒烟（4 个候选法律大模型 × 3 件代表性案卷）暴露的共识性歧义。
> 状态：以下规则已写入试标协议 v1.1（`$JUSTILAW_DATA_DIR/qa/trial-annotation-20261016/protocol.md` §6）先行统一双标口径；
> 正式修订需引擎线/法律组确认后落入 [标注指南](../annotation-guideline.md) 并升版本号。
> 每条附冒烟证据（哪些模型提出）。

## G-1 法条引用不构成前科事实证据（§3 / `circumstances.*`）

- 问题：决定段援引"第二十条第（四）项（六个月内曾受治安处罚从重）"时，四个模型都不确定 `last_prior_penalty_date`、`violations_last_year`、`first_offense` 能否据引用推断（4/4 提出）。
- 建议：指南 §3 增补——法条引用只反映机关的法律认定，不是事实叙述；上述三字段除非事实段有文字叙述前科，一律"未提及"。

## G-2 "等人"人数取点名下界（§2 / `persons.participant_count`）

- 问题：`participants.participant_count` 遇"甲和乙丙丁戊己等人"无规则可循（deepseek-v4-pro、deepseek-flash、glm53 提出）。
- 建议：取点名下界（含甲），状态"推断"；"等"不计入。指南可同时考虑引入区间值表达。

## G-3 流水型赌资口径（§2 / `amounts.personal_stake`）

- 问题：微信收付流水（收入 630 / 支出 990）如何折算个人赌资无口径；"合计涉及金额"后数字缺失（deepseek-v4-pro、glm53、glm53flash 提出）。
- 建议：personal_stake ＝ 支出合计（赌注）＋收入合计（赢取），状态"推断"；无现金查获表述时 `onsite_stake_total` 标"未提及"。

## G-4 单场次案件的累计与时长字段（§1 / `conduct.duration_days` 等）

- 问题：单日单场案件 `cumulative_stake`、`cumulative_participants`、`duration_days` 应记未提及还是同值/1（glm53、glm53flash、deepseek-v4-pro 提出）。
- 建议：累计类字段不复制单场值，标"未提及"；`duration_days` 仅原文写明持续时长才标。

## G-5 布尔字段禁猜 false（§1 状态三选一）

- 问题：deepseek-v4-pro 在怀孕/公务员/投案等无表述字段填 false，其余模型标"未提及"——两种口径会人为压低 κ。
- 建议：指南 §1 明示——布尔字段只有原文明写否定事实才填 false；"当场查获"不构成"非自首"证据。

## G-6 场所归类细则（§4 / `venue.venue_type`）

- 问题："包房""出租屋"归属无规则（deepseek-flash、glm53flash 提出）。
- 建议：出租屋/家中/宿舍→住宅；包房/茶楼/棋牌室/宾馆/KTV→经营场所；"某处/某地"→其他＋推断。

## G-7 行为定性→枚举映射的状态（§4 / `conduct.role` 等）

- 问题："为赌博提供条件的违法行为"→role=提供条件者，状态"明确"还是"推断"（4/4 提出）。
- 建议：原文表述与枚举语义直接对应时"明确"；需选择/转化时"推断"。

## G-8 两档注额记区间（§2 / `amounts.per_bet`）

- 问题："底注 100、自摸 300"能否记 {100,300}（glm53 提出）。
- 建议：可以，状态"明确"。

## G-9 minor_circumstance 只认轻微（§4）

- 问题：原文认定"情节严重"时枚举（轻微/特别轻微）无对应档（deepseek-flash、glm53、glm53flash 提出）。
- 建议：维持两档枚举，"情节严重"标"未提及"；严重档由 `outcome.stated_circumstances` 承载，指南可注明这一分工。

## G-10 营利目的默认口径（§4 / `intent.profit_purpose`）

- 问题：仅有"为赌博提供条件"定性、无抽头/收费事实时，profit_purpose 是否默认（deepseek-v4-pro、deepseekflash 提出）。
- 建议：不默认，标"未提及"；仅凭金额大小判断按现规则标"推断"。

## G-11 认定词的分段归属（§1 / 分段规则）

- 问题：复议说理段的"公共场所""以营利为目的"是机关认定词，引用时分寸不定（glm53、deepseekflash 提出）。
- 建议：事实段出现的照常标"明确"；仅出现在说理/决定段的降为"推断"。

## 附：代理试标方法论偏离（提请登记 deviation-log）

G0.3 原要求两名法律组成员双人试标；真人无法在窗口期内到位（用户 2026-10-16 决定），改为：
标注员 A=GLM-5.3、B=DeepSeek-Flash（异构家族、互不可见、同版协议 v1.1），分歧由 GLM-5.3-Flash 逐条仲裁，
法条问题以法宝 MCP 原文核验。影响：模型间 κ ≠ 人类 κ（通常高估；异构家族只缓解不消除相关错误）；
本批 50 件产物是**代理标签（proxy）**，不计金标；法律组到位后须真人复标或抽样复核后方可升格。
本报告由金标质检线（Zcode 会话）产出，请协调/引擎线镜像登记至 `docs/05-research/deviation-log.md`。
