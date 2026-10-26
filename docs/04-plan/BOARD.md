# 协调看板（提交快照）

> **实时状态以 [`$DATA/coordination/CURRENT.md`](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md) 为准**（共享事件登记自动生成）；本页是 **2026-10-18 17:15 的提交快照**，只在里程碑更新。
> 事件登记设计：[event-registry.md](./event-registry.md)；运行时 CLI：`D:/02_Dev/Data/justilaw-research/coordination/coord_event.py`；共享镜像：`D:/02_Dev/Data/justilaw-research/handoff/2026-10-18/CURRENT.md`。
> 历史见 [collab-log.md](./collab-log.md)；决策/产物/阻塞见 [DECISIONS.md](./DECISIONS.md)、[ARTIFACTS.md](./ARTIFACTS.md)、[ISSUES.md](./ISSUES.md)。

## 五分钟阅读路径

1. **实时**：[CURRENT.md](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md)（自动生成；各工作树都能读）。
2. **设计索引**：[design-docs-index-2026-10-18.md](./design-docs-index-2026-10-18.md)（按主题找现有文档；含文档勘误）。
3. 本页（提交快照；比 CURRENT 可能旧几分钟）。
4. [element 契约 handoff](./handoffs/2026-10-18-element-contract-v1.md)（验收命令）；[标注线角色交接](./handoffs/2026-10-18-labeling-role-handoff.md)（新会话接手标注）；[数据链续跑交接](./handoffs/2026-10-18-data-chain-continuation.md)（额度耗尽后续跑）。
5. [ARTIFACTS.md](./ARTIFACTS.md)（只读“现行”行）。
6. **不要从 `collab-log.md`、续跑单、`workstreams.md` 开始读**；它们是历史/归属参考。

## 2026-10-22 里程碑快照（覆盖 10-18 状态）

> 现行主文档：[CURRENT-STATUS-2026-10-22.md](./CURRENT-STATUS-2026-10-22.md)；全项目分层对齐：[PROJECT-PANORAMA-STATUS-2026-10-22.md](./PROJECT-PANORAMA-STATUS-2026-10-22.md)。10-18 以下各线状态保留为历史。

| 线 | 2026-10-22 状态 | 下一步 |
|---|---|---|
| 数据/要素 | 909 timesfix 完成但 training-only；字段/前科闭环 37+12 样本通过 | 909 路由/重标、M1 坐标 |
| 千问 S1 | 3.7-flash 12 条 11/12、¥0.075；30c 26/30 完成 | fallback/硬停/100 条 |
| 706 湖文本 | 新根 706b pilot12 12/12 | full 567/706 incomplete（139 missing；113 Arrearage） |
| 阻塞 | 57 复议/26 前科/199 公示；M1 587/219；key 已暴露需轮换 | 见 CURRENT-STATUS §6 |

## 各线当前状态（17:15）

| 线 | 最新动作 | 下一步 | 注意 |
|---|---|---|---|
| 引擎 | `1152141`（已推送）：L5 字段边界定版（36 要素 + CaseMeta 3 元数据 + binding 派生块）；语义表 `f0dd746` 未变（8 shared / 28 target，225 passed） | 维护语义表/契约；评估是否采纳 binding contract | 引擎未签后处理实现；binding 规则版已冻结 |
| 后处理/解析 | `d9999aa`（已推送）：全量 unified_raw 刷新 41 批/26,185 条；format_ok 24,439；canonical released+content 3,728；S3 25/299=8.36%；表格行修复；218 候选池 | 用新 unified 树跑 S1 主批；P2-r1 清理；web party；S1 句内 span 盲评；S3 <5% | **P2-r1 761 条重复权限页不合格；web/P2-L4word party=0；218 候选非金标** |
| 协调 | `377e495`：标注线角色交接；`CURRENT` 已登记最新 S3/218/溯源；BOARD 刷新 | 维护事件登记与跨线验收 | 不再手抄各线状态 |
| 标注 | 角色交接已落盘；**尚无新教师批** | 218 候选复核 + L5 spec36 | L5 `reference_elements=null`；binding 不挡教师；边界人工评测未做 |

## 当前循环

| 项 | 内容 |
|---|---|
| 目标 | S3 降到 <5% + 人工边界评测有分母；L5 教师批在合格子集上先跑 spec36；binding 降为 guard，不再当 Gate |
| Loop owner | **协调（跨线）**；解析修复=后处理，教师批=标注 |
| 贡献方 | 引擎（契约/字段语义）、后处理（S1/S3/句内 span + harvest 前处理三文件，B-11）、标注（L5 批次）、协调（事件/验收） |
| 截止 | 下一里程碑待定（不以时间为门，以指标为门） |
| 状态 | **blocked**：S3 25/299=8.36% >5%；218 候选非金标；L5 教师批未跑；边界人工评测未做；r7 未放行 |

## 最新进展（17:15）

- **S3 26 → 25**：法条“七十条/第七十条”等价写法修复后，fixed-299 复跑 25/299=**8.36%**；唯一变化 W-000350-28 error→warn；其余错误未修。r7 仍关闭。
- **26 件硬错溯源**：`failure-provenance-audit.jsonl` 将 26/26 关联到原 HTML、parsed-1、S0；字段是否真的在原网页出现仍需人工/结构化核对。典型：W-000421/429/459 原网页缺拘留天数；W-000798-d4 是 HTML 表格越行，需上游 `<tr>/<td>` 修复。
- **218 条候选池**：排除 final300 同源页 2,735 条后审计 2,266 条，218 条通过保守筛选（叙述式、已放行、有 facts/decision、主体在事实与决定均出现、有量化处罚、事实含赌博证据）。**这是待复核候选，不是金标**；第一版 399 条作废。
- **句内事实 span 离线契约**：`fact_spans.py` 用子句 ID + `cleaned_text` 坐标，模型/审阅者只选 ID；6 个混合句硬错用人工 ID 重放通过 `check_facts_quality`，但这是 **oracle 上界**（仅 5 个独立页），未接 S1 生产契约，无付费调用。
- **标注线**：角色交接 `377e495`；尚无新教师批；12 件 smoke 仍是 21 条证据/20 条定位（95.2%），字段准确率未测。
- **binding**：`e06a0af` 修复 scene 捷径后 212 123/611/1611、P1 158/723/1708；money shared=0，但 money/time 大量 review；规则版语义归属按 B-10 冻结，不再是 Gate。
- **范围解锁（B-11）**：S1/S3 修复期，后处理可写 `harvest/{parse.py,parse_qc.py,to_parsed1.py}`（网页原文→parsed-1：表格行/字段/事件键/QC）；`discover/**`、`collect/**`、`delivery/**`、引擎代码、`harvest` 其余文件、既有正本仍不动。
- **全量 unified 刷新（`d9999aa`）**：41 批/26,185 条 → `$DATA/unified_raw_refresh/20261018/`；format_ok 24,439；canonical 8,288；`released+content` 3,728。主批：web-r4、P1-r6、P1b-r2、P2-L4word、merged-full。P2-r1 有 761 条重复 `P-2963` 权限页，`format_ok=false`；web/P2-L4word `text_party=0`，meta 依赖字段受限。
- **26,185 不是去重数**：唯一 id 7,333、唯一文本 7,468、唯一 text+subject 7,476；A 级 3,728（唯一 id 3,613、唯一事件键粗算 1,622）。`to_unified` 只做格式转换。
- **S1 输入已产出（`a787352`）**：`20261018-s1/` 3,196 条 / 1,790 事件；唯一 id 与 event+subject；split 2,202/495/499；A 2,883 + A-salvage 313；party 1,320；`no_subject` 558 单列；S1 离线 plan `ee9cb165…` 通过。**不是标签**，P2-r1 salvage/party 缺口仍要标。
- **party 批量回收（`7b0d9ff`）**：2,691 条 source-grounded（句 2,041/表 650）；`20261018-s1-party/` 3,196 条 / 1,790 事件，party_available **2,460**（原 1,320；web 772、pkulaw 1,688）；仍无 party 736；no_subject 558 不变；plan `17da2993…`。回收是规则结果，非人工审核。

## Gate A / A2：已完成

- 后处理 `4b7680d`：`evidence_graph` 主路径的金额/日期归一化改用 E-05；已推送。
- A2 诊断：`$DATA/parsed2/diagnostics-e05-e2e-20261018/summary.json`（`372adbfa…`），212 条：
  - `normalizer:resolved` 1,704；`normalizer:unresolved` 5；
  - `requires_explicit_approximation_policy` **97 → 11**；
  - `reason:e05_parse_failed` 5；
  - `binding:unresolved` **仍 1,647**（绑定未接，预期）。
- **A2 是同一 212 条、不同代码路径的重跑**，不是重复 10:28；10:28 是 pre-E-05 基线。

## Gate B：回归已修，质量未证；binding 降为 guard

- 引擎 `f0dd746`：语义表（8 shared / 28 target），225 passed。
- 后处理 `e06a0af`：删除 scene 捷径；目标专属字段无明示 target → review；`resolve_binding` 只收 target/shared；212 **123/611/1611**，P1 **158/723/1708**；144 passed；BIND-04 已解决。
- 但 money shared=0、money/time 大量 review；`field_accuracy=null`、`semantic_rules_approved=false`；规则版语义归属按 **B-10/BIND-05** 冻结。
- `build_graph`/`classify` 当前只在诊断与测试；`resolve_binding` 只经 `binding_contract`（无生产调用）。**binding 不是 L5/M1/M4 主链路的前置**。
- 结论：Gate B 不再作为主阻塞；BIND-03（无准确率）/BIND-05（方法门禁）/CONTRACT-01（引擎未采纳）保持 open。下一步是按教师/模型化归属，不再加规则。

## 绑定四层（避免混淆）

| 层 | 做什么 | 当前状态 |
|---|---|---|
| 1. 规则定义 | 引擎 `binding_rules.py`：**只定语义**（8 shared / 28 target），不写具体分类 | **已完成**（`f0dd746`，225 passed；职责倒置已修） |
| 2. 分类诊断 | 后处理 `classify_graph_bindings`：把语义表映射到候选 | **当前代码 `e06a0af`**：212 123/611/1611；P1 158/723/1708；shared 全为 count，money shared=0；规则版已冻结（B-10） |
| 3. 主链路执行 | `resolve_binding` 接受 target/shared；真正把值归到本人/事件 | **未接主链路**：`resolve_binding` 只经 `binding_contract`，无生产调用；money target 仅 23%/11%，time 2%/6% |
| 4. 契约采纳 | 引擎签发 `binding_policy`；`semantic_rules_approved=true`；版本号提升 | **未采纳**：contract `accept_in_resolve` 已与 resolver 一致（target/shared），但 `binding_policy=proposed_pending_engine_adoption`、`semantic_rules_approved=false` |

**质量保障现状**：当前 binding 能挡住 scene 误标，但 money/time 大量 review；`field_accuracy=null`；130/130 无 artifact；规则版语义归属按 B-10 冻结。**它是保守隔离器，不是已验收的语义归属；也不是教师标注的前置条件。**

**一句话**：BIND-04 已修；binding 质量仍未证、未接主链路；**下一步是教师/模型化归属 + 100–200 标注 + A/B，不再加规则**。

## 绑定职责（谁做什么）

| 层 | 应该谁做 | 现在谁做 | 问题 |
|---|---|---|---|
| 契约 | **引擎**：字段语义、类别、证据要求、验收指标 | 引擎 `binding_rules.py` 的语义表 | 语义表存在，但正式 contract 未被引擎采纳（`proposed_pending_engine_adoption`） |
| 具体判定 | **数据/后处理**：NLP/混合模型做指代、主体归属、事件归属 | 后处理规则版 `classify_graph_bindings` | 规则只到字段查表 + 关键词/多人列表；已按 B-10 冻结，不再加规则 |
| 质量验证 | **独立评测**：100–200 候选标注，precision/coverage | 暂无 | `field_accuracy=null`；130/130 无 artifact；只有分布计数 |

**结论**：规则版 binding 是保守 guard，不是语义归属；下一步只能是教师/模型化归属 + 标注 + A/B，或承认它不接主链路。继续加正则不再计入进展。

## 诊断/回放口径（避免重复劳动）

| 名称 | 输入 | 内容 | 状态 |
|---|---|---|---|
| 工程诊断 10:28 | 212 条 | 图/归一化/证据/36 字段可观测性；binding 1,647 | pre-E-05 基线，已完成 |
| post-E-05 回放 11:16 / 集成回放 11:36 | final300 的 S3 299 条 | S3/装配；`element_states` 全 `not_available` | 已完成；不测要素层 |
| **Gate A2 诊断 11:58** | 212 条 | 主路径改用 E-05 后重跑；approx 失败 97→11；binding 仍 1,647 | **已完成** |
| **Gate B 诊断（历史 3d05914）** | 212 123/1567/655；P1-r6 178 条/186 多人 158/1570/861 | 证据感知 3 步；`semantic_rules_approved=true`；`resolve_binding` 接受 shared | **历史**；当前 `e06a0af` 212 123/611/1611、P1 158/723/1708；无准确率 |

**不要用 11:16/11:36 的 S3 回放替代 212 诊断**：它们只测 S3/装配。

## 下一步（按顺序）

1. **后处理/解析**：把句内事实 span 从 oracle 推到模型选 ID 的小批盲评；修上游 HTML `<tr>/<td>` 表格行；S3 复跑仍按 299 固定分母，目标 <5%。
2. **标注**：复核 218 条候选（不是金标），在合格子集上跑 L5 spec36；测字段准确率/A-B，不只报证据定位。
3. **协调**：维护事件登记/看板；组织人工五段边界评测（100–200 件），给 decision/facts 一个真分母。
4. **引擎**：维护语义表/契约；决定 binding contract 采纳或拒绝；不写具体判定。
5. **r7**：只有 S3 <5% + 正式门禁全过才放行；过滤 8.36% 做教师批不算过门。

## 指标（当前）

| 指标 | 当前值 | 说明 |
|---|---|---|
| S3 硬失败 | **25/299 = 8.36%** | fixed-299 法条修复后；r7 要求 <5%；26/299=8.7% 是修复前基线 |
| binding 分类（`e06a0af`） | 212：123 shared / 611 target / 1611 review；P1：158/723/1708 | 规则版；money shared=0；已按 B-10 冻结 |
| binding 可消费（212） | 734/2345 = 31.3% | target 611 + shared 123；contract 与 resolver 均为 target/shared |
| binding 可消费（P1） | 881/2589 = 34.0% | target 723 + shared 158 |
| binding review | 212 1611/2345=68.7%；P1 1708/2589=66.0% | money/time 为主；无独立准确率 |
| money 可消费 | 212 128/1160=11.0%；P1 329/1414=23.3% | 其余 review |
| time 可消费 | 212 26/423=6.1%；P1 10/446=2.2% | 其余 review；存在 behavior_date 映射缺口 |
| 218 候选池 | 2,266 审计 / 218 通过 | **候选不是金标**；final300 同源页 2,735 条已排除 |
| A2 approx 失败 | 97 → 11 | E-05 主路径生效 |
| M1 丢弃 | 59/406 = 14.5% | validation 64；pre-E-05 |

## WIP

- 跨线循环：**1**（S3/边界/L5 标注）
- 新功能/新文档：冻结；只做 handoff/事件登记内事项

## 阻塞

- **BIND-03**：`e06a0af` 后 212 123/611/1611、P1 158/723/1708；money shared=0 但 money/time 大量 review；无独立准确率；规则版已冻结（owner 后处理+引擎）。
- **BIND-05**：规则版语义归属违反 B-08/B-10；不再加正则；需要教师/模型化归属 + 100–200 标注 + A/B（owner 协调+后处理）。
- **CONTRACT-01**：`accept_in_resolve` 已与 resolver 一致（target/shared），但 `binding_policy=proposed_pending_engine_adoption`、`semantic_rules_approved=false`；引擎未采纳（owner 引擎+后处理）。
- **R7-01**：S3 25/299=8.36% >5%；r7 未放行（owner 后处理+协调）。
- **I-20**：L5 `reference_elements=null`；218 候选非金标；教师字段准确率未测（owner 引擎+后处理+标注）。

## 本看板不做什么

- 不重复 `collab-log` 的历史叙述。
- 不手抄各线状态；实时看 `CURRENT.md`。
- 不写“请对接/请关注”；跨线交接用 [handoffs/](./handoffs/)。
- 不把测试通过等同于消费方跑通；三级完成定义见 DECISIONS B-03。
