# Codex 后处理线续跑交接单（2026-10-18 · 额度耗尽后）

> 会话状态：Codex 后处理会话额度耗尽。工作树 `.claude/worktrees/seg-v2-design-review`，分支 `codex/seg-v2-design-review`，最后提交 `ba12e6f`（已推 origin）。
> **有大量未提交工作，必须先保住再继续。** 只读备份在 `D:/02_Dev/Data/justilaw-research/handoff/2026-10-18/postprocessing/`（status/log/patch/untracked/文件副本，25 个文件）。

## 1. 未提交工作盘点（`git status` 实测）

**修改（8）**
- `arbitrate.py`：退役旧“法律上限选候选”与无预算/截断裁判路径；新 CLI 默认 plan；保留历史裁决。
- `element_contract.py`：契约快照增加依赖哈希（`harvest/parse.py`、`parse_qc.py`、`key_field_presence.py`、`legal_caps.json`）；分歧分类改为 status/value/evidence-only。
- `durable_calls.py`、`locate.py`、`replay_pipeline.py`、`requirements.txt`、`run_elements.py`、`run_seg.py`：配套的可恢复调用、坐标、回放、依赖与运行入口调整。

**新增（17，均为 `research/discretion/unify/`）**
- `audit_run.py`：只读崩溃恢复/费用审计；不丢弃截断尾、不重试 HTTP。
- `field_rules.py`：读引擎定义、保留全部 K 字段、仅解析批准别名。
- `normalization.py`：证据绑定的中文时间/数量适配；JioNLP 只做表达式解析；精度/开口/兼容损失显式记录；不覆盖引擎本体。
- `outcome_arbitration.py`：**保留历史观察值**的结果裁决，与规范诊断分离；处罚上限不得用来选候选；每个决定须有自己的允许来源引用。
- `evidence_graph.py`：来源锚定的候选图；词法绑定只是候选不是真值；显式主体/事件/角色边。
- `contract_bundle.py`：导出可执行的引擎/传输契约＋拟议共享归一化 IR。
- `experiment_plan.py`：冻结事件不交叉的小批计划；只用独立参考评估。
- 其余：`binding_contract.py`、`budget_scope.py`、`diagnose_pipeline.py`、`evidence_types.py`、`observability.py`、`provider_contract.py`、`run_outcomes.py`、`section_refs.py`、`task_result.py`、`tests/test_engineering_completion.py`。

**已产出的诊断（未提交，数据目录）**
`$DATA/parsed2/engineering-diagnostics-20261018-codex-v1/`：`summary.json`、`field-catalog.json`、`observability.json`、`field-diagnostics.jsonl`、`candidate-graphs.jsonl`（10-18 10:28）。

## 2. 已完成（已提交）

- `ba12e6f` 首批实施：`element_contract`/`durable_calls`/`replay_pipeline`/`run_seg`/`freeze_slice`，92 测试通过，0 付费调用。
- `dev-slice-20261018-codex-v2` 已冻结：212 条/121 事件（manifest `5010f077…`）。
- 免费回放 `replay-final300-20261018-codex-v3`：S3 26/299=8.7%，parsed-2 候选 216，旧 88 标签隔离、晋升 0。

## 3. 续跑第一件事（防丢工作）

在新会话里，先不要改代码，按顺序：

1. `cd D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review`
2. `git status --short --branch`、`git log --oneline -3`，与备份 `status.txt`/`log.txt` 对照。
3. `git diff` 与 `uncommitted.patch` 对照，确认未提交内容完整。
4. 跑测试：`python -B -m pytest research/discretion/unify/tests -q -p no:cacheprovider`。
5. **按逻辑分组小提交**（不要一个大提交）：① 契约/依赖哈希＋分歧分类；② 归一化/字段规则/证据图；③ 裁决/保留观察值；④ 运行入口/预算/审计；⑤ 测试与文档。每步跑测试，确认无回归再下一步。
6. 若测试失败：先修到绿，不要删测试或回退未提交内容；必要时用备份副本恢复。

## 4. 续跑任务（按优先级）

1. **收口本批 WIP**：把上述模块提交、跑通测试，更新 README/契约快照；给出新的契约 bundle hash。
2. **读诊断**：`engineering-diagnostics-.../summary.json` + `observability.json` + `field-diagnostics.jsonl`，确认哪些字段/环节已可观测、哪些仍不可观测；与引擎 E-04 的丢弃分析对照。
3. **完成 element-v2 语义接入**：等引擎 E-05 交出七字段裁决规则＋日期/金额归一＋证据语义后，把 `field_rules/normalization/evidence_graph/contract_bundle` 对齐；**不得在网页侧自行定义本体**。
4. **免费回放**：用现有 1,600+ 条输出对拍新契约；确认 status/value/evidence-only 分歧分类与验收口径一致。
5. **I-20 参考批次**：只有引擎 E-05/E-06 完成、契约冻结、免费回放通过后，才做 ≤12 条烟测 → ≤36 条规约批；走 I-21 六道门；不得全量 2,451。
6. **不碰**：采集/下载、交付 `delivery/**`、标签 `labels/**`、引擎 `justilaw-api/**`、门禁、main。

## 5. 关键路径

- 工作树：`.claude/worktrees/seg-v2-design-review`
- 备份：`$DATA/handoff/2026-10-18/postprocessing/`
- 切片：`$DATA/parsed2/dev-slice-20261018-codex-v2/`
- 回放：`$DATA/parsed2/replay-final300-20261018-codex-v3/`
- 诊断：`$DATA/parsed2/engineering-diagnostics-20261018-codex-v1/`
- 引擎契约：`discretion-engine/justilaw-api/app/discretion/{element_labels.py,schema.py}`
- 写范围：`research/discretion/unify/**`；数据 `$DATA/s1_runs`、`$DATA/parsed2`

## 6. 完成标准

- 本批 WIP 全部提交、测试全绿、契约快照/README 更新；
- 诊断摘要能说明字段可观测性与剩余缺口；
- 引擎 E-05 规则接入后，免费回放通过；
- 未放行 r7、未付费、未改交付/标签。
