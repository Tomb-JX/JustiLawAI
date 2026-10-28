# L5 金额开口语句 `X元起` 被硬闸误拒（2026-10-26）

下一批 L5 离线分担记录 `S1-eca1cc49bea9e945b58d` 的允许事实视图 `S17.1.1` 写明“每局100元起”。按标度指南，这是每局金额下界 100 元、上界未知，应表示 `amounts.per_bet={min:100,max:null}`。目标人的参与事实在前两条连续事实片段中，当前先只报告金额**数值证据**问题，本人归属仍单独验收。

用当前稳定 `l5-stable@c3343ec` 的 `compile_references` 离线编译该字段，返回 `numeric_evidence_unsupported:amounts.per_bet`。触发点在 `research/discretion/unify/element_contract.py::check_money_support`：`open_top` 列出“上不封顶／以上／超过／至少／逾／不低于／余／多”，没有识别紧随金额的“起”；`tokens` 只提取到 `100元` 确数，因此 `{100,null}` 被拒。证据片段“以20元起押、上不封顶”在同批另一记录跨两句引文，现有逻辑可接受，说明不能把任何位置出现“起”都当成金额开口。

建议后处理线在**同一金额短语**内支持 `X元起`／`X元起押`／`X元起注`，只将该数解释为下界、上界空；`X元` 仍是确数。验收至少包含上述正例、跨句 `20元起押、上不封顶`、他人金额同额反例及数字与证据不一致反例。继续用原文坐标和本人归属闸单独验证，不能因数值闸通过而发布个人金额。

本轮对该字段记录 `field_quarantine`，未修改 `unify/**`，未补造上界，也未放入训练。复现入口：`research/eval/curate_l5_next30_manual.py` 与 `$DATA/engine/l5-expansion-next30-inputs-c3343ec-20261026-v2/manual/records.jsonl`。`$DATA` 指 `D:/02_Dev/Data/justilaw-research`。
