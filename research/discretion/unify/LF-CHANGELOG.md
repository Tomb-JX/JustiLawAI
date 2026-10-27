# LF-CHANGELOG：标注函数库变更记录

规则见计划 §1.2：只能新增或修改标注函数，每次改动需在 dev 上修正 ≥3 条同一现象的错误、写一句通用写法，并在此记录改前改后的覆盖率与准确率。判据文件：数据目录 `lf-20261028/CRITERIA-stage2.md`（sha256 `4f1daacd…`）。

## v0（2026-10-28）首版，34 个 LF

- personal 19 个：rule 7、definition 1、context 2、structure 4、model 3、llm 2。
- onsite 15 个：rule 5、context 1、structure 4、model 3、llm 2。

### 基线前的实现更正（看任何准确率之前）

- **现象**：`onsite_caliber.caliber_of` 在找不到任何依据时，返回兜底类 OTHER。`o_not_stake` 和 `p_not_stake` 把这个兜底类也当成“非赌资”去投否，和这两个 LF 自己的定义（人均、输赢、抽头、兑换、硬币等明确依据）不符。
- **发现方式**：首跑只看了汇总覆盖面，onsite 的“规则全弃权”只有 0.1%。这时还没有看任何准确率或错例。
- **更正**：新增 `_explicit_other`，只在 `caliber_of` 写明的那几条依据上投票，兜底一律弃权。规则文件本身没有改动。
- **更正后**：onsite 规则全弃权 21.2%，personal 44.2%。以更正后的版本为 v0 基线。

### v0 基线结论（dev，按判据）

- 判据 2：没有 LF 被剔除。5 个 LF 标“支持不足”：p_unnamed_stake、p_stated_result、p_face_value、p_definition_larger、o_only_unattributed。
- 判据 3：两个任务都满足（structure 与 model 组覆盖率 ≥ 10%）。
- `p_fine_clause` 和 `o_fine_clause` 在 dev 上投票数为 0。罚款句不在事实视图里，没有候选。暂保留，不改。
