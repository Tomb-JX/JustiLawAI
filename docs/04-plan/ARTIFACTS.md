# 产物登记（权威路径与版本）

> `$DATA` = `D:/02_Dev/Data/justilaw-research`。下表是各线消费时应引用的**唯一当前版本**；状态为“过期/基线/WIP”的产物不得当作现行契约。
> 文件哈希为 SHA-256；部分 JSON 内部还有自己的 `hash` 字段，二者不同，引用时写明是“文件 SHA”还是“内部 digest”。

**最后更新：2026-10-18 13:04**

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
| Gate B 212 诊断（v5，历史） | `$DATA/parsed2/diagnostics-e05-binding-v5-20261018/summary.json` | 文件 SHA `1f690209…`；212 条 | 后处理 | 协调 | **历史口径**（123/1567/655；已被 `e06a0af` 取代） |
| P1-r6 绑定诊断（历史） | `$DATA/parsed2/diagnostics-e05-binding-p1-20261018/summary.json` | 文件 SHA `b26aaace…`；178 条 | 后处理 | 协调 | **历史口径**（111/1570/908；已被 `e06a0af` 取代） |
| Gate B 212 复跑（当前代码 `e06a0af`） | `$DATA/parsed2/diagnostics-bind-fix-dev212-20261018-codex/summary.json` | 文件 SHA `99de4f47…`；212 条 | 后处理 | 协调、引擎 | **当前口径**（123 shared/611 target/1611 review；money shared=0；BIND-04 已修；无准确率） |
| P1-r6 复跑（当前代码 `e06a0af`） | `$DATA/parsed2/diagnostics-bind-fix-p1-20261018-codex/summary.json` | 文件 SHA `3269c260…`；178 条 | 后处理 | 协调、引擎 | **当前口径**（158/723/1708；money shared=0；BIND-04 已修；无准确率） |
| S3 fixed-299 复跑（法条修复） | `$DATA/s1_runs/s1-20261018-segv2-final300/s3-b-review-article-fix/summary.json` | 文件 SHA `1a64f0c5…`；299 条 | 后处理 | 协调 | **当前 S3 口径**（25/299=8.36%；r7 仍 <5% 未达；仅 W-000350-28 error→warn） |
| 26 件 S3 硬错溯源 | `$DATA/s1_runs/s1-20261018-segv2-final300/failure-provenance-audit.jsonl` | 文件 SHA `b2ed923d…`；26 条 | 后处理 | 协调 | **台账**（26/26 关联 HTML/parsed/S0；字段是否在原网页出现仍需人工核对） |
| 218 条候选池 | `$DATA/s1_runs/s1-20261018-segv2-final300/gold-candidate-218-ids.json` | 文件 SHA `9cd815f3…`；218 条 | 后处理 | 标注、协调 | **候选不是金标**（2266 审计/218 通过；final300 同源页 2735 排除；第一版 399 作废） |
| 句内事实 span 离线契约 | `research/discretion/unify/fact_spans.py`（`cd19d59`） | 子句 ID + cleaned 坐标；oracle 6 件混合句通过 | 后处理 | 协调、引擎 | **离线契约**（仅 5 页 oracle 上界；未接 S1 生产；无付费调用） |
| 引擎绑定语义表（Gate B） | 引擎 `research/eval/binding_rules.py` | commit `f0dd746`（8 shared / 28 target，语义-only） | 引擎 | 后处理 | **现行**（225 passed；已删除具体分类实现） |
| Gate B contract bundle（v4，历史） | `$DATA/s1_runs/contract-e05-binding-v4-bundle/contract.json` | 文件 SHA `a56cbdd8…`；内部 digest `37f4f351…` | 后处理 | 引擎、验收 | **历史**（`adopted/semantic=true` 旧状态）；当前 `e06a0af` 为 `proposed_pending_engine_adoption`、`semantic_rules_approved=false` |
| 共享事件登记 | `$DATA/coordination/events.jsonl`、`CURRENT.md`、`coord_event.py` | 111 条事件（17:11） | 协调 | 全部 | **现行**（实时状态源；BOARD 是里程碑快照） |
| 12 条 smoke（已执行） | `$DATA/s1_runs/smoke12-elements-e05/` | `plan.json` 12 eligible、0 rejected；证据 21 条/20 定位 | 后处理 | 协调、引擎 | **只过冒烟**（字段准确率未测；`model-adjudicated`） |
| 12 条 smoke 计划（final300 选 ID，历史） | `$DATA/s1_runs/smoke12-elements-e05-plan/plan.json` | 多件 `missing_target_or_input` + 1 `upstream_s3_error` | 后处理 | 协调 | **历史**；说明 target 可见性是主要过滤 |
| 法定 caps | `$DATA/config/legal_caps.json` | 文件 SHA `aedf5a23…` | 协调导出 | 引擎 | **现行**（E-01 核对使用；是否转正见 ISSUES） |
| 后处理 E-05 接入（Gate A） | 后处理 `research/discretion/unify/element_contract.py`、`normalization.py` | commit `256d2ce`（11:36）；文件 SHA `5d36c89f…`、`2f28259b…` | 后处理 | 后处理、引擎 | **已提交并推送**（139 passed；模块级） |
| E-05 主路径接入（Gate A2） | 后处理 `research/discretion/unify/evidence_graph.py` | commit `4b7680d`；文件 SHA `00063ffc…` | 后处理 | 后处理 | **已完成并推送**（A2 诊断 11:58） |
| 集成回放（Gate A） | `$DATA/parsed2/replay-e05-integrated-20261018/summary.json` | 文件 SHA `133f1b85…` | 后处理 | 协调 | **基线**（S3 26/299；`element_states` 全 `not_available`；不测绑定） |
| 主体绑定（Gate B） | 引擎 `binding_rules.py` + 后处理 `classify_graph_bindings` | `f0dd746` + `e06a0af`；212 123/611/1611；P1 158/723/1708 | 引擎 + 后处理 | 引擎、验收 | **未通过/降为 guard**（money shared=0，但 money/time 大量 review；`field_accuracy=null`；规则版按 B-10 冻结；未接主链路；BIND-03/BIND-05/CONTRACT-01 open） |
| unified_raw 全量刷新（2026-10-18） | `$DATA/unified_raw_refresh/20261018/` | `CATALOG.json`/`REPORT.md`/`QUALIFIED.md`；41 批/26,185 条 | 后处理 | 全部 | **现行**（format_ok 24,439；canonical 8,288；released+content 3,728；**非去重**：唯一 id 7,333/文本 7,468；**事件去重未做**；P2-r1 重复权限页不合格；web party=0） |
| 当前交付 | L3 指针 **r6**；r7 未放行 | 见 [stage-plan-v2](./stage-plan-v2-2026-10-17.md) | 网页/法宝 | 全部 | **r7 关闭**（S3 <5% 未达） |
| 协调规范 | `BOARD.md` / `DECISIONS.md` / `ARTIFACTS.md` / `ISSUES.md` / `OWNERSHIP.md` / `handoffs/` | commit 见本批 | 协调 | 全部 | **现行** |

## 引用规则

1. 跨线消息只引用本表“现行”行的路径 + 哈希；引用“基线/待重导/WIP”时必须注明其限制。
2. 产物更新后先改本表，再发 handoff；不得在消息里另写一份路径。
3. 旧版本不删除，但在本表标“已被取代”，避免两条线同时消费不同版本。
4. 模型调用产生的产物必须另标模型 ID、prompt 版本、调用批次日；未标者不得当作可复现结果。
