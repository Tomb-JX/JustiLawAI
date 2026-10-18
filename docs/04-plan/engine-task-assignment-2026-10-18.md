# 引擎任务分配（2026-10-18 · 基于实时盘点）

> 现状快照（2026-10-18 约 10:30 实测）：
> - 引擎工作树 `discretion-engine` @ `aeb29b6`，干净；最近产物为 10:18 的 `first-run-v4` / `m1-validation`。**首跑已完成：M1 诊断 64/64、证据过滤后 363/363；M4 B4 未超多数类（35.94% vs 42.19%）；M2 规范核对未做。**
> - Codex 工作树 `seg-v2-design-review` 有**未提交改动**正在编辑 `unify/{arbitrate,durable_calls,element_contract,locate,run_elements,run_seg}`——引擎**不得编辑 `unify/**`**，避免撞车。
> - 交付仍 r6；r7 未放行；切片 `dev-slice-20261018-codex-v2` 212 条/121 事件已冻结。

## 0. 总原则

- 引擎只写自身范围：`justilaw-api/app/discretion/**`、`research/eval/**`、`docs/05-research/**`、引擎设计文档；**不写** `research/discretion/unify/**`（Codex 在改）、交付/标签/采集。
- 不跑付费模型；本地 qwen3.5:9b 只作学生端诊断，不产标签。
- 所有数字标注样本与口径；无 `reference_elements` 时字段准确率一律“暂缺”。
- 任务按 P0→P1→P2 顺序；P0 全部免费、可立即做。

## 1. P0 立即做（免费，不依赖 Codex）

### E-01 M2 规范层核对（首跑漏做）

- 输入：`$DATA/parsed2/dev-slice-20261018-codex-v2/records.jsonl` 的 `observed_outcome` + `metadata`；`legal_caps.json`；`norm_layer`。
- 做什么：逐条检查历史观察处罚是否落在所引法条/版本的合法空间内——罚款/拘留上限、并处/单处规则、合并执行 ≤20 日、条号-版本一致性（2012 第 70 条 / 2025 第 82 条）、行为日期与法律版本一致性。
- **不做什么**：不修改 `observed_outcome`；规范冲突单独报告（A-05）。
- 产出：`$DATA/engine/development/dev-slice-...-m2-legal-audit.json`＋报告：合法空间内比例、冲突按类型分组、ID 清单、不可核对项。
- 验收：纯确定性；冲突不混入训练目标；报告写清“观察值 vs 规范结论”。

### E-02 切片数据质量复核

- `P-1216` 本人归属（事实段“段xx” vs 决定段全名）；对“不可机械核对”的 42 条拘留/89 条罚款抽样做语义复核；确认 `observed_outcome` 与处罚证据一致。
- 产出：复核清单（ID/问题/建议），交 Codex/协调登记；**不改切片**。
- 验收：每条有结论；无法判定的标“待独立复核”，不猜。

### E-03 M4 负结果诊断

- 基于首跑已有指标，补：逐类混淆矩阵、每类 precision/recall/F1、类别不平衡、文本长度/稀疏度与错误关系、典型错误例（只引 ID 与聚合，不贴正文）。
- 回答：B4 为什么在类型准确率和罚款上输给多数类；是样本小、类别偏、文本特征弱，还是标签噪声。
- 提出**一个**预注册的下一步基线（如 class-weight/元数据特征/更简单目标），**不得在 validation/test 上调参**。
- 产出：`engine/development/...-m4-diagnosis.md`＋数据文件。

### E-04 M1 丢弃分析

- 从 `m1-validation.json`/重跑本地诊断，按字段统计：47 项“取值无法解析”与 11 项“证据找不到”分别落在哪些字段；证据命中/丢弃按字段分布。
- 产出：字段级丢弃榜＋提示/枚举修订建议（供 element-v2 契约）；不产标签、不报准确率。

## 2. P1 契约与验收准备（免费，需与 Codex 协作但不改其文件）

### E-05 element-v2 字段裁决规则（引擎侧）

- 针对分歧最高的字段写裁决规则：`conduct.role` 91%、`venue.venue_type` 91%、`behavior_type` 85%、`method` 70%、`times` 68%、`participant_count` 51%、`person.age` 30%。
- 输出：标注指南 v0.4 / `schema.py` 字段说明更新（枚举边界、多角色并存、计数是否含本人/被组织者、“多次”判定、年龄遮蔽下的推断规则）。
- 日期/金额归一化与证据语义：给出引擎侧唯一规则（JioNLP 仅作实现选项，不成为第二套权威）；与 Codex 的 `element_contract` 对齐，**通过协作记录交接，不编辑 `unify/**`**。
- 验收：每条规则有正反例；版本号提升；Codex 能直接照此实现。

### E-06 I-20 首批验收就绪

- 适配 `accept_element_labels.py` 到 `element-ref-v2` 与 Codex 新增的分歧类型（status/value/evidence-only）；定义 ≤12 条烟测与 ≤36 条规约批的字段级判据（证据命中、枚举合法、A/B 分歧、单位成本）；准备“预测 vs 参考”对比脚本。
- 不跑付费；等 Codex 的 element 参考批次产出后即可验收。
- 验收：跑通合成夹具；对真实参考可一键出字段级报告。

## 3. P2 等参考标签后（不提前）

### E-07 字段准确率与特征上界

- I-20 首批参考到位后：算 M1 字段准确率（逐字段/逐档）；跑“金标特征基线”作上界；与 B4 文本基线同切片比较；回答“要素路线是否有增益、抽取损失多大”。

### E-08 卡片 v2

- M2 完成后，把规范核对结果、未知项、未实现模块写入 3 张卡片；不编造类案/区间/覆盖率。

## 4. 依赖与协作

| 依赖 | 状态 |
|---|---|
| 切片 212/121 | 已冻结 |
| Codex element 参考批次 | 未产出；Codex 正在改契约，等其提交后再对齐 |
| `legal_caps.json` | 已就绪 |
| 引擎分支 4 笔未合 main | 保持；不合并、不放行 r7 |
| `unify/**` | **Codex 独占编辑**；引擎只读 + 协作记录 |

## 5. 交付与汇报

- 每项产出写 `$DATA/engine/development/` 与 `docs/05-research/`，在引擎分支提交；
- 每项完成在 collab-log 报一行：任务号 / 产出 / 关键数字 / 下一步；
- P0 三项（E-01/02/03/04）建议今天完成，作为 Stage 2 阶段版质量报告的引擎部分。
