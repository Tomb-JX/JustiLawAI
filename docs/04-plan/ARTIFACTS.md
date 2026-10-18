# 产物登记（权威路径与版本）

> `$DATA` = `D:/02_Dev/Data/justilaw-research`。下表是各线消费时应引用的**唯一当前版本**；状态为“过期/基线/WIP”的产物不得当作现行契约。
> 文件哈希为 SHA-256；部分 JSON 内部还有自己的 `hash` 字段，二者不同，引用时写明是“文件 SHA”还是“内部 digest”。

**最后更新：2026-10-18 12:10**

| 产物 | 路径 | 版本 / 哈希 | Owner | 消费方 | 状态 |
|---|---|---|---|---|---|
| 冻结开发切片 | `$DATA/parsed2/dev-slice-20261018-codex-v2/` | manifest `5010f077…`；records `72ccfb60…`；excluded `743ef99d…`；212 条 / 121 事件 | 后处理 | 引擎、后处理 | **现行**（开发切片；`reference_elements=null`、`release_approved=false`） |
| E-05 规则包 | `docs/05-research/annotation-guideline.md` v0.4 | 引擎 commit `69c7b24` | 引擎 | 后处理、验收 | **现行**（七字段裁决、日期/金额、证据语义） |
| E-05 实现包 | 引擎 `research/eval/normalization_spec.py`、`evidence_contract.py` | 文件 SHA `e0573e0a…`、`29b448eb…`；commit `45a7d1a` | 引擎 | 后处理 | **现行**（只覆盖归一化 + 证据；**不含主体绑定**） |
| 引擎 schema / prompt | 引擎 `justilaw-api/app/discretion/schema.py`、`element_labels.py` | schema 1.1.0，文件 SHA `6546ad8e…`；prompt `element-v1`，文件 SHA `5b80d9c0…` | 引擎 | 全部 | **现行**（版本号未随描述变更提升，见 ISSUES） |
| E-05 contract bundle | `$DATA/s1_runs/contract-e05-bundle/contract.json` | 文件 SHA `7a0e70bf…`；内部 digest `dbe8643e…` | 后处理 | 引擎、验收 | **待重导**（11:17 生成，早于 11:24 实现包；`normalization_policy` 仍为 `proposed_pending_engine_adoption`） |
| post-E-05 离线回放 | `$DATA/parsed2/replay-e05-verify-20261018/summary.json` | 文件 SHA `eae5c95a…` | 后处理 | 协调、引擎 | **S3 基线**（26/299=8.7%；`element_states` 全 `not_available`，不测要素层） |
| 工程诊断（pre-E-05） | `$DATA/parsed2/engineering-diagnostics-20261018-codex-v1/summary.json` | 文件 SHA `3c092cb5…` | 后处理 | 协调、引擎 | **基线（pre-E-05，已完成）**（binding unresolved 1,647 / 1,704） |
| Gate A2 212 诊断 | `$DATA/parsed2/diagnostics-e05-e2e-20261018/summary.json` | 文件 SHA `372adbfa…`；212 条 | 后处理 | 协调 | **已完成**（normalizer 1704；binding 1,647；approx 失败 97→11；e05 parse failed 5） |
| Gate B 212 诊断（待跑） | 输出目录由后处理新建（建议 `$DATA/parsed2/diagnostics-e05-b-20261018/`） | 未生成 | 后处理 | 协调 | **待跑**（接入绑定后；binding 应变化） |
| 引擎绑定规则（Gate B） | 引擎 `research/eval/binding_rules.py` | 文件 SHA `720e3c11…`；commit `971fdc3` | 引擎 | 后处理 | **现行**（shared_fact / target_specific / needs_review；231 passed） |
| 共享事件登记 | `$DATA/coordination/events.jsonl`、`CURRENT.md`、`coord_event.py` | 13 条种子事件（12:03） | 协调 | 全部 | **现行**（实时状态源；BOARD 是里程碑快照） |
| 12 条 smoke 计划 | `$DATA/s1_runs/smoke12-elements-e05-plan/plan.json` | 文件 SHA `93a3a36d…`；`execute=false`、`release_approved=false` | 后处理 | 协调 | **计划未执行**（等免费诊断通过 + I-21 门） |
| 法定 caps | `$DATA/config/legal_caps.json` | 文件 SHA `aedf5a23…` | 协调导出 | 引擎 | **现行**（E-01 核对使用；是否转正见 ISSUES） |
| 后处理 E-05 接入（Gate A） | 后处理 `research/discretion/unify/element_contract.py`、`normalization.py` | commit `256d2ce`（11:36）；文件 SHA `5d36c89f…`、`2f28259b…` | 后处理 | 后处理、引擎 | **已提交并推送**（139 passed；模块级） |
| E-05 主路径接入（Gate A2） | 后处理 `research/discretion/unify/evidence_graph.py` | commit `4b7680d`；文件 SHA `00063ffc…` | 后处理 | 后处理 | **已完成并推送**（A2 诊断 11:58） |
| 集成回放（Gate A） | `$DATA/parsed2/replay-e05-integrated-20261018/summary.json` | 文件 SHA `133f1b85…` | 后处理 | 协调 | **基线**（S3 26/299；`element_states` 全 `not_available`；不测绑定） |
| 主体绑定（Gate B） | 引擎待补 `research/eval/` 契约模块 | 未提交（截至 11:47，last commit `45a7d1a`） | 引擎 | 后处理 | **未交付**（`shared_fact` / `target_specific` / `needs_review`） |
| 当前交付 | L3 指针 **r6**；r7 未放行 | 见 [stage-plan-v2](./stage-plan-v2-2026-10-17.md) | 网页/法宝 | 全部 | **r7 关闭**（S3 <5% 未达） |
| 协调规范 | `BOARD.md` / `DECISIONS.md` / `ARTIFACTS.md` / `ISSUES.md` / `OWNERSHIP.md` / `handoffs/` | commit 见本批 | 协调 | 全部 | **现行** |

## 引用规则

1. 跨线消息只引用本表“现行”行的路径 + 哈希；引用“基线/待重导/WIP”时必须注明其限制。
2. 产物更新后先改本表，再发 handoff；不得在消息里另写一份路径。
3. 旧版本不删除，但在本表标“已被取代”，避免两条线同时消费不同版本。
4. 模型调用产生的产物必须另标模型 ID、prompt 版本、调用批次日；未标者不得当作可复现结果。
