# Handoff：element 契约 v1（含主体绑定）

- **From**：协调线
- **To**：引擎线（BIND-01）、后处理线（接入 / 重导 / 诊断）
- **Loop owner**：后处理线
- **创建**：2026-10-18 11:45
- **截止**：2026-10-18 13:15
- **状态**：Gate A 已完成（11:36）；Gate B（绑定）open

## 1. 本轮要拿到什么

1. 引擎补齐**主体/事件绑定**规则：`shared_fact` / `target_specific` / `needs_review`，写进 `research/eval/` 的同一契约模块并版本化。
2. 后处理完成 `element_contract.py` / `normalization.py` 接入并提交；重新导出 contract，对齐 11:24 的 E-05 实现包。
3. 在同一 212 条冻结切片上跑一次**免费离线诊断**，给出 binding/normalizer 与基线对比。
4. 协调据结果更新 BOARD；**本轮不跑 smoke、不调模型、不放行 r7**。

## 2. 输入（已存在，引用时带哈希）

| 输入 | 路径 / 哈希 |
|---|---|
| 冻结切片 | `$DATA/parsed2/dev-slice-20261018-codex-v2/`；manifest `5010f077…`、records `72ccfb60…`；212 条 / 121 事件 |
| E-05 规则包 | 引擎 `docs/05-research/annotation-guideline.md` v0.4，commit `69c7b24` |
| E-05 实现包 | 引擎 `research/eval/normalization_spec.py` `e0573e0a…`、`evidence_contract.py` `29b448eb…`，commit `45a7d1a` |
| binding 基线 | `$DATA/parsed2/engineering-diagnostics-20261018-codex-v1/summary.json` `3c092cb5…`（1,647 / 1,704） |
| S3 基线 | `$DATA/parsed2/replay-e05-verify-20261018/summary.json` `eae5c95a…`（26/299；element 未测） |
| 过期 bundle | `$DATA/s1_runs/contract-e05-bundle/contract.json` `7a0e70bf…`（11:17，早于实现包；不要直接复用） |

## 3. 交付物

- 引擎：绑定规则 + 代码 + 正反例；版本号；推送引擎分支。
- 后处理：接入提交；新 contract bundle（新目录，不覆盖旧目录）；新诊断目录（不覆盖 10:28 / 11:16）。
- 协调：更新 BOARD/ARTIFACTS/ISSUES。

## 4. 验收命令

```bash
# 1) 后处理单测
python -B -m pytest research/discretion/unify/tests -q -p no:cacheprovider

# 2) 离线诊断（输出目录必须不存在，且位于 $DATA/parsed2/ 下）
python -B research/discretion/unify/diagnose_pipeline.py \
  --input D:/02_Dev/Data/justilaw-research/parsed2/dev-slice-20261018-codex-v2/records.jsonl \
  --out D:/02_Dev/Data/justilaw-research/parsed2/diagnostics-e05-e2e-20261018
```

**通过判据**：

- 单测全绿；
- 诊断输出 `binding` 分类可解释：`shared_fact` / `target_specific` / `needs_review`，unresolved 相对 1,647 有变化或全部有明确分类；
- 全程无模型调用；
- 新 contract 的 `normalization_policy.status` 不再是 `proposed_pending_engine_adoption`。

## 5. 本轮明确不做

- 不跑 2,451 全量；不跑 12 条 smoke；不调任何模型；不改切片；不放行 r7。
- 不再新开“批准包”文档；绑定必须并入同一契约模块。
- 不覆盖旧诊断/旧 contract 目录；只写新目录。

## 6. Ack / Result

| 项 | 记录 |
|---|---|
| 引擎 ack（时间/commit） | 未 ack（截至 11:47；last commit `45a7d1a`，无绑定表） |
| 后处理 ack（时间/负责人） | 11:36，commit `256d2ce`；工作区干净 |
| 单测结果 | 139 passed；新增接入代码无专用单测 |
| 诊断结果（binding 变化、normalizer、证据问题数） | Gate A 集成回放 `replay-e05-integrated-20261018`：S3 26/299；`element_states` 全 `not_available`；binding 未测 |
| 新 contract 路径/哈希 | 未重导（等 Gate B 绑定，避免导出两次） |
| 关闭时间 | 未关闭 |
