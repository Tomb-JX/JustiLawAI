# 协调看板（唯一当前状态）

> 只放当前循环；历史见 [collab-log.md](./collab-log.md)，决策见 [DECISIONS.md](./DECISIONS.md)，产物见 [ARTIFACTS.md](./ARTIFACTS.md)，阻塞见 [ISSUES.md](./ISSUES.md)。
> 更新时机：循环开始/结束、阻塞变化、核心指标变化。**不再在其它文档维护“当前状态”。**

**最后更新：2026-10-18 11:50**

## 当前循环

| 项 | 内容 |
|---|---|
| 目标 | element 契约 v1 定版（schema + 归一化 + 证据 + **主体绑定**），并在 212 条冻结切片上完成一次**免费离线诊断** |
| Loop owner | **后处理线**（激活交接、跑验收、回报结果） |
| 贡献方 | 引擎线（绑定规则与版本化）；协调线（看板/路由/验收口径） |
| 截止 | 2026-10-18 13:15（90 分钟时间盒） |
| 状态 | **Gate A 已完成；Gate B（绑定）进行中** |

### Gate A：接入（已完成 11:36）

- 后处理提交 `256d2ce`：接入引擎 `normalization_spec` + `evidence_contract`；工作区干净。
- 后处理单测：**139 passed**（但新增接入代码没有单独测试，见 ISSUES CONTRACT-01）。
- 集成回放 `replay-e05-integrated-20261018`：S3 仍 26/299=8.7%；`element_states` 全 `not_available`，**没有测要素/绑定层**。

### Gate B：绑定（等引擎）

- 引擎截至 11:47 尚未提交绑定表；最后一个引擎提交仍是 `45a7d1a`（11:24）。
- 后处理不需要等整段：Gate A 的提交、测试、免费诊断基线现在就能做；只有**绑定验收**这一步等引擎。

## 下一步（按顺序）

1. **引擎**：补主体绑定规则（`shared_fact` / `target_specific` / `needs_review`），写进 `research/eval/` 契约模块并版本化；推送 7 笔本地提交。
2. **后处理**：推送 `256d2ce`（当前 7 笔领先 origin）；给新接入补 2–3 个单测；用集成后的代码跑一次免费工程诊断，建立“pre-binding 基线”。
3. **引擎绑定到位后**：后处理接 `shared_fact` / `target_specific`，重跑同一诊断，比较 binding 变化；再重导 contract。
4. **协调**：核对结果并更新本看板；通过后才讨论 12 条 smoke。

## 验收命令

```bash
# 后处理单测
python -B -m pytest research/discretion/unify/tests -q -p no:cacheprovider

# 离线诊断（输出目录必须不存在，且位于 $DATA/parsed2/ 下）
python -B research/discretion/unify/diagnose_pipeline.py \
  --input D:/02_Dev/Data/justilaw-research/parsed2/dev-slice-20261018-codex-v2/records.jsonl \
  --out D:/02_Dev/Data/justilaw-research/parsed2/diagnostics-e05-e2e-20261018
```

**判据**：测试全绿；binding unresolved 与 1,647 基线对比，或给出明确的 `shared_fact` / `target_specific` / `needs_review` 分类；**不产生模型调用**。

## 核心指标（基线，均为 E-05 前）

| 指标 | 当前值 | 说明 |
|---|---|---|
| S3 硬失败 | 26/299 = 8.7% | 11:16 离线回放；r7 要求 <5%，E-05 不改 S3 |
| binding unresolved | 1,647 / 1,704 候选 | 10:28 工程诊断；本轮要测变化 |
| M1 丢弃 | 59/406 = 14.5% | validation 64 条；本轮不改 M1 |
| 字段准确率 | 暂缺 | `reference_elements=null` |

## WIP

- 跨线循环：**1**（本循环）
- 诊断子任务：0
- 新功能、新文档：**冻结**（本循环结束前不新增）

## 阻塞

- **主体绑定规则未写**（引擎）；这是本轮唯一需要新增的语义规则。
- **11:17 contract bundle 已过期**：它早于 11:24 的 E-05 实现包，`normalization_policy` 仍为 `proposed_pending_engine_adoption`；需在绑定完成后重导一次，不要为 Gate A 重导两次。
- **可见性**：引擎 7 笔、后处理 7 笔提交均未推 origin；交接前必须 push。后处理新增接入代码没有专用单测，需补 2–3 个。

## 本看板不做什么

- 不重复 `collab-log` 的历史叙述。
- 不列已完成工单；已完成项只进 `ARTIFACTS` 或历史。
- 不写“请对接/请关注”这类开放式消息；跨线交接一律用 [handoffs/](./handoffs/) 模板。
- 不把测试通过等同于消费方跑通；三级完成定义见 [DECISIONS.md](./DECISIONS.md) 的 B-03。
