# M2 规范层输出语义（2026-10-27）

`assess(Facts)` 分别返回国家法定处罚选项 `tiers` 和省级数额分档建议 `stake_threshold`。两者不能互换。`tiers` 对每个预设档次，按**已提供事实**展开法定选项，不表示哪个档次已被事实证明；`contains(tier, days, fine)` 仅检查该档次已列选项，不证明档次认定正确，也不证明未知减轻事实不存在。`exhaustive_for_case=False` 是明确的接口声明。

省级 `stake_threshold` 只描述**已知要素能推到的档位**：

- `applicability=applicable`：日期和省级基准已核验且可对接；`provisional`：缺决定日期，以行为日期暂代；`unavailable`：省基准缺失、未生效、旧法数额与新法衔接未核验，或缺少可判断事实。`unavailable` 一律返回空 `bands`、`band_penalty`，调用方不得读取旧档位。
- `observed_band_indices` 与 `bands` 是已知数额及已确定升档情节的**精确可能集合**；不同法律类别分支产生第一、第三档时，不填入第二档。索引 `0` 为“未达起罚标准”，没有相应处罚文本，因此 `band_penalty` 只包含正档的文本，与 `bands` 不保证等长。
- `unknown_conditions` 列出未提供的并行计量、升档条件或法律类别。未知不等于否定。即使 `bands` 只有一档，开放性情节和输入事实缺失仍可能改变最终判断，所以 `final_band_determinable=False`、`hard_filter_allowed=False` 恒成立。
- `status` 为人读摘要；“达到赌资较大”指**已知数额**跨过对应数额门槛。单靠明确升档情节而数额未达门槛时，摘要写“情节升档、已知赌资未达数额门槛”，不会把升档误说成数额已达。程序应依据结构化字段处理，不解析 `status` 字符串作为法律硬约束。

2026 年新法决定而省级旧法数额衔接未核验时，国家法 `tiers` 仍单独返回，省级 `stake_threshold` 为 `法律衔接待核验`、`unavailable` 和空档位。这是弃判省级建议，不是断言省基准已失效。决定日期早于行为日期会直接拒绝输入。

当前 M4 正式文本模型尚未调用 M2；仅 `research/eval/m4_binding_law_ablation.py` 在训练集内把可用省级结果当作软特征，不做硬筛选。该接口修订修正了规则输出含义，并未证明预测准确率提升。验证：`python -m pytest justilaw-api/tests/discretion -q`，冻结训练集回放报告见 `D:/02_Dev/Data/justilaw-research/engine/development/m4-v5-binding-law-ablation-20261027/report-v8.json`；封存 test40 未读取。
