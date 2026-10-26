# 金额关系线阶段收束（2026-10-25 至 10-26）

> 由于标注预算用尽，本线暂停投入，不再新增 LLM 标注。参照全部是模型多数票，不是人工金标。

## 1. 已验证、可以合入的

| 改动 | 证据 | 状态 |
|---|---|---|
| 参赌人数：显式“X人”与姓名名单同台竞争（候选＋NIL） | 开发 13/14、首个留出 10/10，均零错值；冻结链路为 10/14、7/10 | 冻结产物 `2026-10-25-relation-edges-artifact.json`，建议合入 |
| 个人赌资、现场总额：四分类角色模型 `softmax/semantic`（数量语义线索＋金额间加和关系） | 开发集和三套独立留出（扩产池 80、扩产池剩余 255、旧银标 203）都优于冻结链路；在 lake 池 H3 上**不及**冻结链路（20 对 23） | `2026-10-26-joint-amount-artifact.json`；建议合入，但要注意跨来源分布的稳健性 |
| 年龄：出生日期区间推导 | 各留出基本无错值 | 维持 |
| E05 金额归一化“一千五 / 两万五”省略单位 | 25 个新用例，引擎、eval、研究侧测试全过；只影响银标 1 个事件 | 已改，**未提交**，在 discretion-engine 未跟踪的 `normalization.py` 中 |

## 2. 试过、未达标的（不合入）

| 方向 | 结果 | 原因 |
|---|---|---|
| 软竞争解码（个人与现场抢同一笔钱） | 一次都没触发 | 四分类模型本身已经避免了双重认领 |
| 归属特征（左侧最近人、占有词等）接进字段模型 | 开发集 +20，三套留出一负一负一正 | 增益不稳定 |
| 解析器结构（HanLP/LTP 语义依存、SRL） | 单独判归属 0.58，低于预设门槛 0.6；给线性对模型只加 +0.02 | 中文省略主语（零形回指），句内解析拿不到跨句主语 |
| 自训 RoBERTa 人—金额关系模型 | 对级宏 F1 0.38 → 0.56–0.59（开发集与 H3 一致）；接进字段模型后 H3 从 20 提到 30，**但开发集 121 → 120，无增益**；推出的归属只有 0.53，低于老归属模型的 0.73 | 字段增益不稳定，归属门槛未达到 |
| 补话题主语、无主语标记（针对零形回指） | 开发集字段效用 141（最高），H3 26（低于原版 30）；归属仍在 0.50 左右 | 开发集增益没有在留出上复现 |

## 3. 关键认识

1. **瓶颈已经从模型转移到参照质量。** A/B 两家标注不一致的人—金额对上，kimi 与 Claude 两个裁判只有 48% 一致（H3 中 313 对）。难例的参照本身定不下来，模型间几分的差距很可能落在噪声里。
2. **零形回指是归属问题的根源。** 规则、解析器、编码器加窗口提示都没有解决它。
3. **跨来源分布会翻转结论**：在扩产池上领先的模型，在 lake 池（多金额为主）上不一定领先。今后验收至少需要两种来源的留出集。
4. **供应侧还有缺陷**：一个金额会被拆成“00元”“0元”之类的碎片（子代理标注时发现）。这属于数值候选识别的问题，应在供应侧修正。

## 4. 若日后恢复，最省钱的路线

1. **小规模人工金标**：从分歧最大的人—金额对和字段里抽 50–80 条，一人判定。只用来裁决“哪个模型更好”，不用来训练。在当前参照噪声下，这是唯一能拉开差距的办法。
2. **零成本实验**：把老归属模型的输出（0.73）与对模型特征合并后接入字段模型；修复金额碎片化后重跑。这些都不需要新标注。
3. 补齐剩余的第三票：kimi 在百炼上很贵；用 Claude 子代理成本低，与 kimi 的一致度见第 3 节。

## 5. 资源与产物

- **花费**：两日 LLM 标注合计约 ¥90（各批 `calls/attempts.jsonl` 的账面值）。百炼和 DeepSeek 都曾因余额耗尽中断；目前百炼仍处于拒绝访问状态。
- **数据**（私有目录 `relation_annotation/`）：四批事件共 906 个的字段草标、人—金额对级草标 467 个事件、HanLP/LTP 解析缓存、RoBERTa 模型与折外预测（`pair-models/`）。
- **代码**（`research/discretion/unify/`，未提交）：
  - 标注：`run_relation_model_labels.py`、`run_pair_relation_labels.py`、`claude_pair_labels.py`；
  - 数据：`prepare_relation_model_batch*.py`、`prepare_lake_holdout.py`；
  - 实验：`experiment_relation_edges.py`、`experiment_joint_amount_roles.py`、`ownership.py`、`experiment_ownership.py`、`experiment_parser_probe.py`、`experiment_pair_relations.py`、`experiment_pair_integration.py`、`export_pair_examples.py`、`train_pair_encoder.py`、`parse_with_toolkits.py`、`export_parse_jobs.py`、`score_pair_variants.py`、`compare_arbiters.py`、`evaluate_relation_model_labels.py`；
  - 基础设施：`durable_calls.py`（新增中断接续、熔断复活）、`s1.py`（新增 `extra_body`）。
- **测试**：`tests/test_relation_model_labels.py` 共 15 项通过。
- **分轮报告**：`2026-10-25-relation-model-draft-eval.md`、`2026-10-25-relation-edges-experiment.md`、`2026-10-26-joint-amount-roles.md`、`2026-10-26-ownership.md`、`2026-10-26-semantic-structure-experiments.md`，以及本文。
