# 绑定服务 v1（binding-v1）：说明与引擎接入（2026-10-27）

## 是什么

一个**只做推理**的确定性服务，对每条赌博处罚文书给出 4 个字段的绑定结果：个人赌资、现场总额、参赌人数、年龄。运行时不训练、不调用大模型。输入相同，输出逐位相同：ONNX 用 1 线程和 8 线程跑出的结果逐位一致，重跑也一致。

- 代码：`research/discretion/unify/binding_service.py`
- 冻结产物：`D:/02_Dev/Data/justilaw-research/serving/binding-v1/`。由 `freeze_serving.py` 生成，启动时逐个文件校验 `MANIFEST.json` 里的 SHA256，不符就拒绝启动。
- 运行环境：主环境 Python 3.14，依赖 `onnxruntime`、`tokenizers`、`numpy`、`jionlp`。只用 CPU，不需要 PyTorch 或 GPU。

## 上线策略（保守）

| 字段 | 自动填（bound）的条件 | 否则 |
|---|---|---|
| 个人赌资、现场总额 | 冻结链路、softmax/semantic、softmax/semantic_pair **三者给出同一个值** | 三者不一致 → `relation_ambiguous`，附上各方法的建议值和原文；都没给答案但文中有金额候选 → `no_route_output`，附上全部候选；文中没有金额候选 → `no_candidate` |
| 参赌人数 | 显式“X人”与姓名名单**两种来源给出同一个数** | 模型值作为建议 → `single_source_count`，附分数和出处 |
| 年龄 | 由出生日期和行为日期推出**唯一**的周岁 | `no_operands`／`ambiguous_age_or_event` |

只有 `bound` 的字段可以直接进入裁量计算。`unresolved` 的字段必须交人工确认，其中 `no_candidate` 可以按“原文未提及”处理。

## 输入与输出

**输入**（JSONL，每行一条）：`id, target, aliases, source_sha256, text_full, sentence_view, view_hash, facts_text, meta_text`。格式与 S1 教师输入相同。

**输出**（JSONL）：

```
{"id", "target", "service_version": "binding-v1", "artifact_manifest_sha256",
 "bindings": [{"field": "amounts.personal_stake", "target_id", "binding_status": "bound|unresolved",
               "value": "amount:365" | 4 | 33 | null, "candidate_ids": [...],
               "evidence": [{"candidate_id", "start", "end", "quote", "raw"}],
               "decision_source", "reason", "proposals": {...}, "derivation"?}]}
```

`start`／`end` 是原文 `text_full` 中的字符位置。年龄附带两个日期操作数。字段名、`binding_status` 和原因码沿用供应契约 v0.1。

**运行**：

```
python binding_service.py --artifacts <serving/binding-v1> --engine-root <discretion-engine/justilaw-api> --inputs in.jsonl --out out.jsonl --threads 8
```

## 实测（H3：lake 池 171 条，多金额为主）

参照是模型投票（A/B＋第三票）。80 条双盲复核显示，这类参照在字段级的正确率为 95%–100%。

| 字段 | 参照有值 | 自动填 | 自动填正确 | 转人工中参照有值的 |
|---|---:|---:|---:|---:|
| 个人赌资 | 56 | 16 | 16（100%） | 40（不一致 18，均未给答案 22） |
| 现场总额 | 37 | 18 | 17（94%） | 20 |
| 参赌人数 | 50 | 6 | 6（100%） | 40 条建议值；在未参与训练的批次上，建议值约 82%–87% 正确 |
| 年龄 | 17 | 10 | 9（90%） | 7；错的 1 条属于“陈述年龄与行为时周岁”的口径差异 |

- **覆盖率低**：171 条中有 141 条（82%）至少一个字段需要人工确认。这是选择“宁可转人工、不自动出错”的代价；在多金额文书多的 lake 池上尤其明显。
- **一致性核对**：在复核过的 80 条上，服务三条路线的输出与评估实验逐条一致（480/480）。ONNX 与 PyTorch 的概率差 ≤ 2×10⁻⁶。
- **速度**：8 线程处理 171 条（约 1.2 万个人—金额对）约 200 秒。
- **注意**：H3 已多次用于开发评估，上表**不是独立盲测**。正式上线前应在一批全新数据上复测。

## 引擎接入步骤（引擎线执行）

1. **先处理依赖**：服务通过 `research/eval/normalization_spec.py` 调用引擎工作树里**未提交的** `app/discretion/normalization.py`，其中包含“一千五”的修复。必须先随引擎线提交，否则服务结果会跟着工作树变化。冻结链路的现场总额还依赖引擎 `app/discretion/binding.py`（原 S2），其哈希已在冻结产物中记录。
2. 引擎侧用一个适配层调用 `BindingService(artifacts, engine_root).bind(records)`，只采用 `bound` 的值；`unresolved` 进入人工确认队列，展示 `proposals` 和 `evidence`。
3. 把 `service_version` 和 `artifact_manifest_sha256` 写入审计日志，确保每个结果都能追溯到具体模型版本。
4. 升级流程：重新训练 → 运行 `freeze_serving.py` 生成新目录（如 binding-v2）→ 运行 `check_service.py` 核对一致性和指标 → 切换目录。不要在原目录里替换文件。

## 已知缺口（详见研究设计差距分析）

- 契约中的 `claims`／`relations` 层还没输出（人—金额关系概率只作为中间特征）。
- 名单人数没有列出成员推导链（`derivation_id`）。
- 人物识别仍用规则；“申请人＝目标人”和脱敏同名无法区分的问题没有建模。
- 金额被拆成“00元”之类碎片的上游缺陷没有修。
- 只覆盖 4 个字段。
