# 协调看板（提交快照）

> **实时状态以 [`$DATA/coordination/CURRENT.md`](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md) 为准**（共享事件登记自动生成）；本页是 **2026-10-18 13:40 的提交快照**，只在里程碑更新。
> 事件登记设计：[event-registry.md](./event-registry.md)；运行时 CLI：`D:/02_Dev/Data/justilaw-research/coordination/coord_event.py`；共享镜像：`D:/02_Dev/Data/justilaw-research/handoff/2026-10-18/CURRENT.md`。
> 历史见 [collab-log.md](./collab-log.md)；决策/产物/阻塞见 [DECISIONS.md](./DECISIONS.md)、[ARTIFACTS.md](./ARTIFACTS.md)、[ISSUES.md](./ISSUES.md)。

## 五分钟阅读路径

1. **实时**：[CURRENT.md](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md)（自动生成；各工作树都能读）。
2. **设计索引**：[design-docs-index-2026-10-18.md](./design-docs-index-2026-10-18.md)（按主题找现有文档；含文档勘误）。
3. 本页（提交快照；比 CURRENT 可能旧几分钟）。
4. [本轮 handoff](./handoffs/2026-10-18-element-contract-v1.md)（验收命令）。
5. [ARTIFACTS.md](./ARTIFACTS.md)（只读“现行”行）。
6. **不要从 `collab-log.md`、续跑单、`workstreams.md` 开始读**；它们是历史/归属参考。

## 各线当前状态（13:40）

| 线 | 最新动作 | 下一步 | 注意 |
|---|---|---|---|
| 引擎 | `1152141`（已推送）：L5 字段边界定版（36 要素 + CaseMeta 3 元数据 + binding 派生块）；architecture 37→36；语义表 `f0dd746` 未变（8 shared / 28 target，225 passed） | 只维护语义表/契约 | 引擎文档已按复跑结果勘误；不签后处理实现 |
| 后处理 | `60ebb52`（已推送）：scene-level money 判定；当前代码复跑 212 310/1517/518、P1 557/1519/513；142 passed | 修复 BIND-04：scene 规则只用于总额/明确 shared 字段；重跑两批并落盘 | **130/130 是提交说明中的自检，无 artifact**；P1 254/399、212 57/187 的 scene money 是他人个人金额，与 `personal_stake=TARGET` 冲突 |
| 协调 | 复跑当前代码并落盘两批诊断；登记 BIND-04；修正引擎/协调文档 | 等待后处理修复后复核 | BIND-03/BIND-04/CONTRACT-01 均未关闭 |

## 当前循环

| 项 | 内容 |
|---|---|
| 目标 | element 契约 v1 定版（schema + 归一化 + 证据 + **主体绑定**）；212 条 Gate B 诊断；契约只重导一次 |
| Loop owner | **后处理线** |
| 贡献方 | 引擎线（绑定规则已交付）；协调线（事件登记/快照/验收口径） |
| 截止 | 2026-10-18 13:15 |
| 状态 | **复跑发现回归，循环阻塞**：`60ebb52` scene-level money 把他人个人金额标 shared（P1 254/399、212 57/187）；130/130 无 artifact；BIND-04 需先修；修复后重跑 212/P1 并落盘，再谈 Gate B |

## Gate A / A2：已完成

- 后处理 `4b7680d`：`evidence_graph` 主路径的金额/日期归一化改用 E-05；已推送。
- A2 诊断：`$DATA/parsed2/diagnostics-e05-e2e-20261018/summary.json`（`372adbfa…`），212 条：
  - `normalizer:resolved` 1,704；`normalizer:unresolved` 5；
  - `requires_explicit_approximation_policy` **97 → 11**；
  - `reason:e05_parse_failed` 5；
  - `binding:unresolved` **仍 1,647**（绑定未接，预期）。
- **A2 是同一 212 条、不同代码路径的重跑**，不是重复 10:28；10:28 是 pre-E-05 基线。

## Gate B：复跑发现回归，未通过

- 引擎 `f0dd746`：语义表（8 shared / 28 target），225 passed；职责已拆清。
- 后处理 `60ebb52`：当前代码复跑 212 310 shared/1517 target/518 review；P1-r6 178 条 557/1519/513；142 passed。
- **回归**：scene-level money 规则把“现场扣押杭xx赌资12000元…”这类他人个人金额整段标 shared；P1 399 个 scene-level money 节点中 254 个可定位为“他人姓名+赌资+金额”，212 为 57/187；与 `amounts.personal_stake=TARGET` 冲突，并覆盖了多人 evidence 的 `needs_review` 分支。
- **证据缺口**：提交说明 130/130=100% 是自检，无样本、判定口径和落盘 artifact；不能作为准确率。
- 结论：Gate B 未通过；先修 BIND-04，重跑两批并落盘，再做独立小样本。BIND-03/CONTRACT-01 保持 open。

## 绑定四层（避免混淆）

| 层 | 做什么 | 当前状态 |
|---|---|---|
| 1. 规则定义 | 引擎 `binding_rules.py`：**只定语义**（8 shared / 28 target），不写具体分类 | **已完成**（`f0dd746`，225 passed；职责倒置已修） |
| 2. 分类诊断 | 后处理 `classify_graph_bindings`：把语义表映射到候选 | **当前代码复跑（`60ebb52`）**：212 310/1517/518；P1 557/1519/513；但 scene-level money 规则有回归，见 BIND-04 |
| 3. 主链路执行 | 更新主 `binding` 字段；`resolve_binding` 接受 shared/target/review，真正把值归到本人/事件 | **部分完成**：`resolve_binding` 接受 shared/target/lexical；但 shared 含 254/399 误标（P1），可消费比例暂不作为进展指标；contract 仍只写 lexical/target |
| 4. 契约采纳 | 引擎签发 `binding_policy`；`semantic_rules_approved=true`；版本号提升 | **状态不一致**：`binding_policy.status=adopted`、`semantic_rules_approved=true`，但 contract `accept_in_resolve` 仍只写 lexical/target，与代码接受 shared 不一致 |

**质量保障现状**：当前代码的证据感知 3 步只到 node 级，不是完整 EP-06；scene-level money 规则把他人个人金额标 shared（P1 254/399、212 57/187），与 `personal_stake=TARGET` 冲突；review 主要是 `unclassified role: None` 与多人列表；130/130 无 artifact；无独立绑定准确率。**“分类完成/契约 adopted”不等于质量保证。**

**一句话**：职责拆分已修（引擎语义、后处理实现）；当前代码出现 scene-level money 回归（BIND-04），**修复、重跑落盘、独立小样本之前，绑定不能进入 Gate B 通过**。

## 绑定职责（谁做什么）

| 层 | 应该谁做 | 现在谁做 | 问题 |
|---|---|---|---|
| 契约 | **引擎**：字段语义（哪些 shared/target）、类别、证据要求、验收指标 | 引擎 `binding_rules.py` 的字段表 | 字段表是契约雏形，但没有正式 contract/验收指标 |
| 具体判定 | **数据/后处理**：NLP/混合模型做指代、主体归属、事件归属 | 引擎 regex + 后处理接线 | **职责倒置**：引擎写了具体判定；896 review、别名脆弱就是证据 |
| 质量验证 | **独立评测**：100–200 候选标注，precision/coverage | 暂无 | 只有分布计数，没有准确率 |

**结论**：引擎应定“什么算本人/共同/待查”的契约，数据侧做“这条事实到底归谁”的 NLP 判定；规则只能做高精度基线，不能替代 NLP，也不能由引擎自己签收。

## 诊断/回放口径（避免重复劳动）

| 名称 | 输入 | 内容 | 状态 |
|---|---|---|---|
| 工程诊断 10:28 | 212 条 | 图/归一化/证据/36 字段可观测性；binding 1,647 | pre-E-05 基线，已完成 |
| post-E-05 回放 11:16 / 集成回放 11:36 | final300 的 S3 299 条 | S3/装配；`element_states` 全 `not_available` | 已完成；不测要素层 |
| **Gate A2 诊断 11:58** | 212 条 | 主路径改用 E-05 后重跑；approx 失败 97→11；binding 仍 1,647 | **已完成** |
| **Gate B 诊断 13:19（3d05914）** | 212 123/1567/655；P1-r6 178 条/186 多人 158/1570/861 | 证据感知 3 步；`semantic_rules_approved=true`；`resolve_binding` 接受 shared | **已完成**；861/655 review 为 unclassified role；无准确率；contract/code 不一致 |

**不要用 11:16/11:36 的 S3 回放替代 212 诊断**：它们只测 S3/装配。

## 下一步（按顺序）

1. **后处理**：v5 已做证据感知 3 步；下一步处置 528 个 unclassified role（`fine`/`unclassified_count`）、补多人案例测试、做 100–200 候选准确率；统一 `accept_in_resolve` 与代码。
2. **引擎**：只维护语义表/契约；确认 `semantic_rules_approved` 与 artifact 一致；不写具体判定。
3. **协调**：核对 Gate B 新结果；从 `BOARD.generated.md` 提交快照；不手抄状态。
4. **只有绑定质量验证 + 契约状态一致 + I-21 门**，才讨论 12 条 smoke；之前不调模型、不放行 r7。

## 指标（当前）

| 指标 | 当前值 | 说明 |
|---|---|---|
| S3 硬失败 | 26/299 = 8.7% | 11:16/11:36 S3 回放；r7 要求 <5% |
| binding unresolved | 1,647 / 1,704 候选 | 旧 `binding` 字段；E-05 分类未改它 |
| binding 分类（v5） | 212：123 shared / 1567 target / 655 review；P1-r6：158/1570/861 | 证据感知 3 步；212 单人、P1 多人（186 节点） |
| binding 可消费（代码，212） | 1690 / 2,345 = 72.1% | shared 123 + target 1567；`resolve_binding` 代码接受 shared |
| binding 可消费（contract，212） | 1567 / 2,345 = 66.8% | contract v4 `accept_in_resolve` 仍只写 lexical/target |
| binding 可消费（P1-r6） | 代码 1728/2589=66.7%；contract 1570/2589=60.6% | 861 review；multi-person 186 |
| binding needs_review | 212 655/2345=27.9%；P1 861/2589=33.3% | v5 review；unclassified role（fine/unclassified_count） |
| A2 approx 失败 | 97 → 11 | E-05 主路径生效 |
| A2 e05 parse failed | 5 | 需 Gate B 时复核 |
| M1 丢弃 | 59/406 = 14.5% | validation 64；pre-E-05 |

## WIP

- 跨线循环：**1**（Gate B）
- 新功能/新文档：冻结；只做 handoff/事件登记内事项

## 阻塞

- **BIND-03**：v5 证据感知 3 步；212 单人、P1-r6 178 条/186 多人（158/1570/861）；861/655 review 为 unclassified role；无标注准确率；`cumulative_stake` 仍 shared（owner 后处理+引擎）。
- **CONTRACT-01**：`binding_policy=adopted`、`semantic_rules_approved=true`，但 `accept_in_resolve` 仍 lexical/target，与代码接受 shared 不一致（owner 引擎+后处理）。
- **PUSH-01**：引擎/后处理已推送；协调事件登记快照待提交。

## 本看板不做什么

- 不重复 `collab-log` 的历史叙述。
- 不手抄各线状态；实时看 `CURRENT.md`。
- 不写“请对接/请关注”；跨线交接用 [handoffs/](./handoffs/)。
- 不把测试通过等同于消费方跑通；三级完成定义见 DECISIONS B-03。
