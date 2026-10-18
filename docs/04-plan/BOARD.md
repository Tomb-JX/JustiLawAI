# 协调看板（提交快照）

> **实时状态以 [`$DATA/coordination/CURRENT.md`](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md) 为准**（共享事件登记自动生成）；本页是 **2026-10-18 12:07 的提交快照**，只在里程碑更新。
> 事件登记设计：[event-registry.md](./event-registry.md)；运行时 CLI：`D:/02_Dev/Data/justilaw-research/coordination/coord_event.py`；共享镜像：`D:/02_Dev/Data/justilaw-research/handoff/2026-10-18/CURRENT.md`。
> 历史见 [collab-log.md](./collab-log.md)；决策/产物/阻塞见 [DECISIONS.md](./DECISIONS.md)、[ARTIFACTS.md](./ARTIFACTS.md)、[ISSUES.md](./ISSUES.md)。

## 五分钟阅读路径

1. **实时**：[CURRENT.md](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md)（自动生成；各工作树都能读）。
2. 本页（提交快照；比 CURRENT 可能旧几分钟）。
3. [本轮 handoff](./handoffs/2026-10-18-element-contract-v1.md)（验收命令）。
4. [ARTIFACTS.md](./ARTIFACTS.md)（只读“现行”行）。
5. **不要从 `collab-log.md`、续跑单、`workstreams.md` 开始读**；它们是历史/归属参考。

## 各线当前状态（12:07）

| 线 | 最新动作 | 下一步 | 注意 |
|---|---|---|---|
| 引擎 | `971fdc3`（已推送）：Gate B 绑定规则 `shared_fact` / `target_specific` / `needs_review`；231 passed；`affcea2` 绑定审计 | 签发 `binding_policy` / 契约采纳 | 规则已交付，但契约包仍是 `binding_policy=null` |
| 后处理 | `f00b494`（已推送）：Gate A2 + Gate B 分类（61 shared / 752 target / 896 review）；contract bundle 重导；142 passed | 决定 896 needs_review 处置；改主 `binding` 字段 | `e05_binding` 是并行报告；旧 `binding` 仍 1,647 |
| 协调 | 共享事件登记上线；`CURRENT.md` 自动生成；已核实 Gate B 过度表述 | 里程碑提交快照 | 不再手抄各线状态 |

## 当前循环

| 项 | 内容 |
|---|---|
| 目标 | element 契约 v1 定版（schema + 归一化 + 证据 + **主体绑定**）；212 条 Gate B 诊断；契约只重导一次 |
| Loop owner | **后处理线** |
| 贡献方 | 引擎线（绑定规则已交付）；协调线（事件登记/快照/验收口径） |
| 截止 | 2026-10-18 13:15 |
| 状态 | **Gate A/A2 完成；Gate B 分类完成，但契约未采纳、主 binding 未改；896 needs_review** |

## Gate A / A2：已完成

- 后处理 `4b7680d`：`evidence_graph` 主路径的金额/日期归一化改用 E-05；已推送。
- A2 诊断：`$DATA/parsed2/diagnostics-e05-e2e-20261018/summary.json`（`372adbfa…`），212 条：
  - `normalizer:resolved` 1,704；`normalizer:unresolved` 5；
  - `requires_explicit_approximation_policy` **97 → 11**；
  - `reason:e05_parse_failed` 5；
  - `binding:unresolved` **仍 1,647**（绑定未接，预期）。
- **A2 是同一 212 条、不同代码路径的重跑**，不是重复 10:28；10:28 是 pre-E-05 基线。

## Gate B：分类完成，链路未完成

- 引擎 `971fdc3`：`binding_rules.py` 交付 `shared_fact` / `target_specific` / `needs_review`，10 tests，231 passed，已推送。
- 后处理 `f00b494`：`classify_graph_bindings` + diagnose `e05_binding`；212 条分类 **61 shared / 752 target / 896 needs_review**；142 passed。
- **未完成**：`classify_graph_bindings` 只写并行的 `e05_binding`，**没有更新主 `binding`**；`resolve_binding` 仍只接受 `lexical_candidate`。contract bundle 仍是 `binding_policy=null`、`semantic_rules_approved=false`、`normalization_policy=proposed_pending_engine_adoption`。
- 因此“Gate B 全部完成”是过度表述：**分类报告完成，绑定链路和契约采纳未完成**。

## 诊断/回放口径（避免重复劳动）

| 名称 | 输入 | 内容 | 状态 |
|---|---|---|---|
| 工程诊断 10:28 | 212 条 | 图/归一化/证据/36 字段可观测性；binding 1,647 | pre-E-05 基线，已完成 |
| post-E-05 回放 11:16 / 集成回放 11:36 | final300 的 S3 299 条 | S3/装配；`element_states` 全 `not_available` | 已完成；不测要素层 |
| **Gate A2 诊断 11:58** | 212 条 | 主路径改用 E-05 后重跑；approx 失败 97→11；binding 仍 1,647 | **已完成** |
| **Gate B 诊断 12:03** | 212 条 | `e05_binding` 61/752/896；旧 `binding` 仍 1,647 | **已完成**；896 needs_review 待决策 |

**不要用 11:16/11:36 的 S3 回放替代 212 诊断**：它们只测 S3/装配。

## 下一步（按顺序）

1. **引擎**：签发 `binding_policy` / 契约采纳，明确 `normalization_policy` 与 `semantic_rules_approved`；否则 `CONTRACT-01` 不能关闭。
2. **后处理**：决定 896 `needs_review` 的处置（dev 切片是否接受显式未知）；把 `e05_binding` 接进主 `binding` 或明确保持“仅诊断”；再跑 Gate B；最后重导 contract 一次。
3. **协调**：核对 Gate B 新结果；从 `BOARD.generated.md` 提交快照；不手抄状态。
4. **只有 Gate B 真正通过 + I-21 门**，才讨论 12 条 smoke；之前不调模型、不放行 r7。

## 指标（当前）

| 指标 | 当前值 | 说明 |
|---|---|---|
| S3 硬失败 | 26/299 = 8.7% | 11:16/11:36 S3 回放；r7 要求 <5% |
| binding unresolved | 1,647 / 1,704 候选 | 旧 `binding` 字段；E-05 分类未改它 |
| binding needs_review | 896 / 1,709 = 52.4% | `e05_binding` 分类；需决策 |
| A2 approx 失败 | 97 → 11 | E-05 主路径生效 |
| A2 e05 parse failed | 5 | 需 Gate B 时复核 |
| M1 丢弃 | 59/406 = 14.5% | validation 64；pre-E-05 |

## WIP

- 跨线循环：**1**（Gate B）
- 新功能/新文档：冻结；只做 handoff/事件登记内事项

## 阻塞

- **BIND-02**：`e05_binding` 分类 896/1709 为 `needs_review`；`classify_graph_bindings` 只写并行字段，主 `binding` 未改；`resolve_binding` 仍拒绝（owner 后处理+引擎）。
- **CONTRACT-01**：`binding_policy=null`、`semantic_rules_approved=false`、`normalization_policy=pending`；旧 `binding` 仍 1,647；契约未采纳（owner 引擎+后处理）。
- **PUSH-01**：引擎/后处理已推送；协调事件登记快照待提交。

## 本看板不做什么

- 不重复 `collab-log` 的历史叙述。
- 不手抄各线状态；实时看 `CURRENT.md`。
- 不写“请对接/请关注”；跨线交接用 [handoffs/](./handoffs/)。
- 不把测试通过等同于消费方跑通；三级完成定义见 DECISIONS B-03。
