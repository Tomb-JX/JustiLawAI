# M4 银标开发训练首跑（2026-10-20）

## 准入判断

`ALL-203-silver-20261020` 已把 203 条要素与历史观察处罚对齐，修复证据坐标并隔离 125 条不合格教师输入。203 条中 79 个不能可靠绑定或数值缺支持的字段降为「未提及」。这允许 **银标限定的开发训练**。

证据包的 `g22.overall` 仍为 `conditional_silver_training_only; G2.2 formal release NOT passed`：同批 S1/parse.py 比较未达标、30–50 条规范歧义审查待做，且没有人工复核。此批不得称金标、不得用于正式测试或模型发布。

## 固定实验

- 输入：`$DATA/parsed2/m4-pilot-203-silver-20261020/records.jsonl`，SHA-256 `b9461e6bfeb6f16b195c4b0bd318eb9201f4d8603d6e95615f3c30b69d58796d`。
- 事件级划分：train 140、validation 23、test 40；事件跨划分 0。test 仅做完整性检查，不进入特征提取、拟合或评估。
- 特征：36 要素的状态/值与来源渠道；金额开口上界保留标志。排除证据引文、目标姓名、决定时间、法条、处罚引文和 `observed_outcome`。数值取 `log1p`。
- 分类：固定 `LogisticRegression(C=1, class_weight=balanced)`；数值：固定 `Ridge(alpha=10)`。只在 train 拟合，在 validation 评估，没有搜索参数。
- 代码：`research/eval/train_m4_silver_pilot.py`；模型与报告：`$DATA/engine/development/m4-silver-pilot-20261020/`，报告含输入及模型哈希，`release_approved=false`。

## 验证结果（n=23，开发性）

| 模型 | 处罚类型准确率 | Macro-F1 | 拘留 MAE | 罚款 MAE |
|---|---:|---:|---:|---:|
| 多数类/中位数 | 47.83% | 0.216 | 3.83 天 | 413.04 元 |
| B4 事实文本 | **56.52%** | **0.517** | 4.20 天 | 501.13 元 |
| 本轮银标要素 | 47.83% | 0.481 | 3.94 天 | 556.63 元 |

要素模型已可复现训练，但在这 23 条验证集上没有超过 B4；类别和数额都不能据此宣称有效。203 条只覆盖 20/36 个非空字段，营利目的 21 条、`conduct.times` 1 条，关键裁量信号仍稀疏。下一步先完成规范歧义审查、绑定小样本人评与银标随机抽检；扩量后按事件分组复跑预注册基线，正式测试必须使用人工金标。
