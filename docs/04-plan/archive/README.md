# 归档索引

> 本目录不移动原文件，只登记“不再作为当前状态/任务来源”的文档。保留它们是为了历史、审计和回答“当时为什么这么做”。
> 当前状态：[BOARD.md](../BOARD.md)；决策：[DECISIONS.md](../DECISIONS.md)；产物：[ARTIFACTS.md](../ARTIFACTS.md)。

## 已归档（不再维护）

| 文档 | 原用途 | 归档原因 | 替代 |
|---|---|---|---|
| [codex-engine-continuation-2026-10-18.md](../codex-engine-continuation-2026-10-18.md) | 引擎会话恢复/模块地图 | 当前引擎会话已恢复并交付 E-01–E-06；续跑单消费后即旧 | BOARD、ARTIFACTS |
| [codex-postprocessing-continuation-2026-10-18.md](../codex-postprocessing-continuation-2026-10-18.md) | 后处理会话恢复/模块地图 | 当前后处理会话已恢复并在接入；续跑单消费后即旧 | BOARD、ARTIFACTS |
| [engine-task-assignment-2026-10-18.md](../engine-task-assignment-2026-10-18.md) | E-01–E-06 派工 | 六项已完成；保留为历史 | DECISIONS、ISSUES |
| [coordination-audit-2026-10-16.md](../coordination-audit-2026-10-16.md) | 10-16 现势审计 | 历史快照，数字已过期 | BOARD |
| [seg-v2-design-review-handoff-2026-10-18.md](../seg-v2-design-review-handoff-2026-10-18.md) | seg-v2 设计评审交接 | 交接已消费 | 设计文档索引 |
| [codex-pipeline-implementation-order-2026-10-18.md](../codex-pipeline-implementation-order-2026-10-18.md) | 管线实施顺序 | 已进入实现，顺序表过期 | BOARD |
| [p2-acquisition-order-2026-10-18.md](../p2-acquisition-order-2026-10-18.md) | P2 采集工单 | 事故已登记 I-21；工单本身不再执行 | I-21 |
| [zcode-web-r3-takeover-2026-10-16.md](../zcode-web-r3-takeover-2026-10-16.md) | 网页线接管 | 历史 | workstreams 归属 |
| [zcode-web-r4-handoff-2026-10-16.md](../zcode-web-r4-handoff-2026-10-16.md) | r4 交接 | 历史 | workstreams 归属 |
| [phase-review-2026-10-16.md](../phase-review-2026-10-16.md) | 阶段审查 | 历史 | DECISIONS |
| [web-integration-directive-2026-10-17.md](../web-integration-directive-2026-10-17.md) | 网页接入指令 | 已执行/过时 | 当前管线文档 |
| [zcode-web-discovery-handoff-2026-10-17.md](../zcode-web-discovery-handoff-2026-10-17.md) | 网页发现移交 | 历史 | workstreams 归属 |
| [data-program-500-gold.md](../data-program-500-gold.md) | 500 件金标供给/验收计划 | 已被 stage-plan-v2 取代；500 金标推迟到 Stage 3，旧人工门禁未关闭（D-002） | stage-plan-v2、dataset-registry |
| [milestones.md](../milestones.md) | 12 周 M1–M6 里程碑计划 | 已被目标制阶段计划取代 | stage-plan-v2 |
| [project-status.md](../project-status.md) | 2026-10-16 项目现状快照 | 状态已由 BOARD/CURRENT 取代 | BOARD、dataset-registry |
| [data-collection.md](../data-collection.md) | v0.5 数据收集计划 | 供给数字/口径已由 r7 候选池与 registry 取代 | data-distribution、dataset-registry |
| [crawler-ops.md](../crawler-ops.md) | 批量采集运维计划 | 2026-10-16 已停止执行；仅保留适配 SOP 参考 | search-discovery-design、web-harvest-design |
| [data-pipeline-status.md](../data-pipeline-status.md) | 2026-10-16 数据链路快照 | 数字已过期 | dataset-registry、data-distribution |

> 2026-10-18 归档登记：旧 500 计划、里程碑、收集、状态、运维计划。按本目录规则**不移动文件**，避免断链；只在文首加归档横幅。

## 仍然现行（不要归档）

- [stage-plan-v2-2026-10-17.md](../stage-plan-v2-2026-10-17.md)：目标、依赖与门禁仍有效；状态看 BOARD。
- [review-driven-coordination-revision-2026-10-18.md](../review-driven-coordination-revision-2026-10-18.md)：A-01–A-06 决策来源。
- [design-docs-index-2026-10-18.md](../design-docs-index-2026-10-18.md)：设计文档版本判定。
- [model-adjudicated-labeling-decision-2026-10-16.md](../model-adjudicated-labeling-decision-2026-10-16.md)：D-001/D-002 来源。
- [normative-revision-deid-cancel-2026-10-17.md](../normative-revision-deid-cancel-2026-10-17.md)：D-003 来源。
- [dataset-registry-2026-10-18.md](../dataset-registry-2026-10-18.md)：现行数据版本口径。
- [data-distribution-2026-10-18.md](../data-distribution-2026-10-18.md)：现行供给事实与 r7 候选池。
- [issues/](../issues/)：I-20/I-21 原始问题单。

## 使用规则

1. 归档文档不再接受状态更新；需要补历史时只追加“归档备注”。
2. 任何新会话先读 BOARD/DECISIONS/ARTIFACTS/ISSUES/OWNERSHIP，再按需读归档。
3. 归档不删除文件，避免断链；如确需移入本目录，先全仓搜引用再动。
