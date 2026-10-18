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
| 引擎 | `3a37c56`（已推送）：binding_rules 增加 `review_reason` 子类（NO_SUBJECT/AMBIGUOUS/IMPLICIT/FIELD_DEFAULT/UNKNOWN_FIELD）；235 passed；上一笔 `971fdc3` 为规则主体 | 签发 `binding_policy` / 契约采纳 | 规则已交付；896 的“为什么 review”现在可分类 |
| 后处理 | `f00b494`（已推送）：Gate A2 + Gate B 分类（61 shared / 752 target / 896 review）；contract bundle 重导；142 passed | 用 `review_reason` 重跑 Gate B；决定 896 处置；改主 `binding` | `e05_binding` 是并行报告；旧 `binding` 仍 1,647 |
| 协调 | 共享事件登记上线；`CURRENT.md` 自动生成；已核实 Gate B 过度表述 | 里程碑提交快照 | 不再手抄各线状态 |

## 当前循环

| 项 | 内容 |
|---|---|
| 目标 | element 契约 v1 定版（schema + 归一化 + 证据 + **主体绑定**）；212 条 Gate B 诊断；契约只重导一次 |
| Loop owner | **后处理线** |
| 贡献方 | 引擎线（绑定规则已交付）；协调线（事件登记/快照/验收口径） |
| 截止 | 2026-10-18 13:15 |
| 状态 | **Gate A/A2 完成；Gate B 主字段已写，但 shared/review 不可消费、契约未批准、无质量验证** |

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

## 绑定四层（避免混淆）

| 层 | 做什么 | 当前状态 |
|---|---|---|
| 1. 规则定义 | 引擎 `binding_rules.py`：字段默认 shared/target；内容依赖字段按证据文本分类；review_reason 细分原因 | **已完成**（`3a37c56`，235 passed） |
| 2. 分类诊断 | 后处理 `classify_graph_bindings`：给每个候选加 `e05_binding` 标签并统计 | **已完成**（61 shared / 752 target / 896 review） |
| 3. 主链路执行 | 更新主 `binding` 字段；`resolve_binding` 接受 shared/target/review，真正把值归到本人/事件 | **部分完成**：`90c46a6` 写主 `binding`；`resolve_binding` 接受 lexical/target；shared 61 + review 896 仍不可消费（814/1709 可消费） |
| 4. 契约采纳 | 引擎签发 `binding_policy`；`semantic_rules_approved=true`；版本号提升 | **未完成**：`binding_policy` / `normalization_policy` 仍 `proposed_pending_engine_adoption`；`semantic_rules_approved=false` |

**质量保障现状**：暂无绑定标注准确率；字段默认表有疑误（如 `persons.civil_servant` 标成 shared，但它是“本人是否为国家工作人员”）；调用方把 target+aliases 当 `all_subjects`，别名可能被误判为“他人”；`conduct.times` 多人时标 shared，可能掩盖本人次数。以上都未验证。

**一句话**：现在的“绑定”推进到第 1–2 层（规则 + 分类诊断），第 3 层只做了主字段写入，第 4 层未采纳；**分类完成 ≠ 绑定质量已保证**。

## 诊断/回放口径（避免重复劳动）

| 名称 | 输入 | 内容 | 状态 |
|---|---|---|---|
| 工程诊断 10:28 | 212 条 | 图/归一化/证据/36 字段可观测性；binding 1,647 | pre-E-05 基线，已完成 |
| post-E-05 回放 11:16 / 集成回放 11:36 | final300 的 S3 299 条 | S3/装配；`element_states` 全 `not_available` | 已完成；不测要素层 |
| **Gate A2 诊断 11:58** | 212 条 | 主路径改用 E-05 后重跑；approx 失败 97→11；binding 仍 1,647 | **已完成** |
| **Gate B 诊断 12:03** | 212 条 | `e05_binding` 61/752/896；旧 `binding` 仍 1,647 | **已完成**；896 needs_review 待决策 |

**不要用 11:16/11:36 的 S3 回放替代 212 诊断**：它们只测 S3/装配。

## 下一步（按顺序）

1. **引擎**：审计字段默认表与别名接口（`civil_servant`、`cumulative_stake`、`abroad_organized_count`；target/aliases 不得当他人）；签发 `binding_policy` / 契约采纳。
2. **后处理**：定义 shared/review 的消费方式（shared 挂事件或每人共享；review 显式未知）；用 `review_reason` 重跑 Gate B；做 100–200 个候选的绑定准确率小样本；再决定是否接主链路。
3. **协调**：核对 Gate B 新结果；从 `BOARD.generated.md` 提交快照；不手抄状态。
4. **只有绑定质量验证 + 契约批准 + I-21 门**，才讨论 12 条 smoke；之前不调模型、不放行 r7。

## 指标（当前）

| 指标 | 当前值 | 说明 |
|---|---|---|
| S3 硬失败 | 26/299 = 8.7% | 11:16/11:36 S3 回放；r7 要求 <5% |
| binding unresolved | 1,647 / 1,704 候选 | 旧 `binding` 字段；E-05 分类未改它 |
| binding 分类 | 61 shared / 752 target / 896 review | `90c46a6` 已写主 `binding` |
| binding 可消费 | 814 / 1,709 = 47.6% | target 752 + lexical 62；shared/review 不可经 `resolve_binding` |
| binding needs_review | 896 / 1,709 = 52.4% | `e05_binding` 分类；需决策 |
| A2 approx 失败 | 97 → 11 | E-05 主路径生效 |
| A2 e05 parse failed | 5 | 需 Gate B 时复核 |
| M1 丢弃 | 59/406 = 14.5% | validation 64；pre-E-05 |

## WIP

- 跨线循环：**1**（Gate B）
- 新功能/新文档：冻结；只做 handoff/事件登记内事项

## 阻塞

- **BIND-03**：绑定质量未证：shared 61 + review 896 不可消费；字段默认表疑误（`civil_servant` 等）；target+aliases 被当 all_subjects；无标注准确率（owner 引擎+后处理）。
- **CONTRACT-01**：`binding_policy`/`normalization_policy` 仍 pending；`semantic_rules_approved=false`；`release_approved=false`（owner 引擎+后处理）。
- **PUSH-01**：引擎/后处理已推送；协调事件登记快照待提交。

## 本看板不做什么

- 不重复 `collab-log` 的历史叙述。
- 不手抄各线状态；实时看 `CURRENT.md`。
- 不写“请对接/请关注”；跨线交接用 [handoffs/](./handoffs/)。
- 不把测试通过等同于消费方跑通；三级完成定义见 DECISIONS B-03。
