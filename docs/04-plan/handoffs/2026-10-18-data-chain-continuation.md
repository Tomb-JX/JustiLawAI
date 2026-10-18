# 数据链续跑角色交接（解析/后处理，2026-10-18）

> 给接手数据链的新会话。先读这一份建立角色和现场感，再按文末路径看原始文档和代码。不要从旧 `collab-log`、续跑单或历史摘要开始。

## 1. 你的角色

你是**数据链（解析/后处理）续跑 owner**，不是标注线、引擎线或协调线的替代者。

- 你负责：`parsed → unified_raw → S0/S1/S2/S3 → 可送标的 S1 输入`；批次质量、失败归因、离线审计、契约回执。
- 你不负责：L5 教师标签（标注线）、schema/教师契约（引擎线）、看板/事件登记（协调线）、binding 语义归属（已按 B-10 冻结）。
- 你可以自主决定：先修哪类失败、怎么抽样、先跑哪个免费审计、如何组织批次；跨线问题用 handoff/事件登记，不靠聊天记录。

一句话：**你的产出是“可复现的解析/校验/输入批次 + 失败证据”，不是“把模型标签也做了”。**

## 2. 先读什么

1. **实时状态**：`$DATA/coordination/CURRENT.md`、[BOARD.md](../BOARD.md)、[ISSUES.md](../ISSUES.md)、[DECISIONS.md](../DECISIONS.md)。
2. **本轮现场**：[unified-refresh-2026-10-18.md](../unified-refresh-2026-10-18.md)（全量刷新、去重、S1 输入、party 回收）。
3. **S1/S3 修补**：[seg-v2-remediation-execution-2026-10-18.md](../seg-v2-remediation-execution-2026-10-18.md)。
4. **句内事实/表格**：[seg-v2-clause-and-table-closeout-2026-10-18.md](../seg-v2-clause-and-table-closeout-2026-10-18.md)。
5. **设计口径**：[parse-engineering-design-v2 v2.8](../parse-engineering-design-v2-2026-10-17.md) §3/§4/§5/§9.1/§12。
6. **S1 质量分母**：[pilot300-quality-report-2026-10-17.md](../pilot300-quality-report-2026-10-17.md)。
7. **代码**：`research/discretion/unify/**`；重点 `fact_spans.py`、`run_seg.py`、`run_elements.py`、`s3.py`、`fact_boundary_audit.py`、`refresh_unified_batches.py`、`build_s1_input.py`、`recover_party_segments.py`。

## 3. 当前现场（2026-10-18）

### 已完成

- 41 个 parsed 批次 → 新 `unified_raw_refresh/20261018/`：26,185 条；旧数据未动。
- canonical 8,288 条；A 3,728（去重前）；S1 输入 **3,196 人 / 1,790 事件**，唯一 id/event+subject，事件级 split 2,202/495/499。
- party 回收 2,691 条；`20261018-s1-party/` 的 `party_available=2,460`，仍无 party 736；`no_subject=558` 单列。
- S3 fixed-299：**25/299 = 8.36%**（26/299=8.7% 是修复前基线）；只修了法条等价写法 W-000350-28。
- 26 件硬错溯源台账：26/26 关联 HTML/parsed/S0；字段是否在原网页出现仍需人工/结构化核对。
- 表格行修复已进入 `harvest/parse.py`、`to_parsed1.py`（commit `fb361ce`），web-r4 已产出。
- 句内事实视图 WIP 已 checkpoint（见 §4）。

### 未完成/仍卡

- S3 仍高于 <5%；facts_quality/decision/表格行/混合句未清。
- 25 件硬错中一部分是源文缺值/缺当事人/权限页，不能靠解析补；需要弃权或来源清理。
- 人工 100–200 件五段边界评测仍未做；现有边界 F1 是“模型 vs 正则”，不是人工金标。
- P2-r1：1,746 条里 761 条重复 `P-2963` 权限页，`format_ok=false`；只 salvage 313 条。
- web 未回收 party 2,737 条；P2-r1 763 条；主要来自执法公示/复议/处罚摘要/字段表。
- r7 未放行；无新付费批；S1 只跑过离线 plan，没有执行模型调用。
- binding 已降为 guard：212 123/611/1611、P1 158/723/1708；规则版按 B-10 冻结，不要为了标注去改它。

## 4. WIP checkpoint（`8410da7`）

额度耗尽前的未提交改动已由协调层 checkpoint 并推送：

- `fact_spans.py`：新增 `fact_view()`、`fact_clause_roles`、`context_time`、标题/粘连日期处理、`ambiguous_fact_context()`、`fact_zone_conflicts()`。
- `run_elements.build_inputs()`：facts 视图改为使用 `fact_view()`，支持句内事实片段/角色。
- `run_seg.py`：clause-refine 提示与 `fact_clause_ids` 校验；VERSION `seg-v2-durable-4`。
- `s3.py`：接入 ambiguous/zone conflict 检查。
- `fact_boundary_audit.py`：对 frozen baseline 与 clause pilot 做离线 S3/输入视图对照。
- `tests/test_clause_refine.py`：新增 fact_view 与 S3/输入共享测试；fixture `fact-boundary-reference-20261018.json`。
- 测试：**157 passed**。

**WIP 的性质**：fixture 是“single-review provisional; not dual-adjudicated gold”；clause refine 还没有在完整 299 上跑过；WIP 只证明接口/单测，不代表 S3 已改善。不要把它当已验收。

## 5. 工作边界

按 [OWNERSHIP.md](../OWNERSHIP.md) 和 B-11：

- 可写：`research/discretion/unify/**`；`research/discretion/harvest/{parse.py,parse_qc.py,to_parsed1.py}`（仅网页前处理/parsed-1）。
- 不动：`discover/**`、`collect/**`、`delivery/**`、引擎 `justilaw-api/**`、`research/eval/**`、`harvest` 其余文件、既有 `unified_raw`/`parsed` 正本。
- 新批次只写 `$DATA` 新目录；不改旧批次；不覆盖已冻结切片。
- 不放行 r7、不改门禁、不合并 main；付费模型必须过 I-21/工单；先用免费离线审计。
- 不产 L5 标签、不改 schema/教师契约、不改 binding 规则（B-10）。
- 事件 append 到 `$DATA/coordination/events.jsonl`，不手改 `CURRENT.md`。

## 6. 现在可以从哪里续

建议先做免费、可回放的：

1. `pytest research/discretion/unify/tests -q`（确认 157 passed）。
2. 读 `fact_boundary_audit.py`，用已有 baseline/pilot 输出跑一次对照；不要新调模型。
3. 检查 fact_view 的角色/日期/标题规则是否符合设计：`behavior_core`、`other_case_fact`、`context_time`、`ambiguous`；fixture 只是 provisional，需人工复核。
4. 决定 clause refine 是否进入下一批 S1：先做小批免费重放/S3 对照，再决定是否重跑 299；不要直接全量。
5. 表格行：W-000798-d4 需要上游 `<tr>/<td>` 行级重建；B-11 已放行 `harvest` 前处理三文件。
6. P2-r1：清重复权限页/唯一 ID；web 剩余 party：先分类“能抽/源文没有/应弃权”，不要继续对权限页加规则。
7. 每完成一项，登记 artifact/metric/blocker；跨线问题写 handoff。

## 7. 开放问题（由你判断或拉协调/引擎定）

- clause refine 的 `fact_clause_ids` 是否进入正式 S1 契约？当前只是 WIP。
- `fact_clause_roles` 的角色枚举是否冻结？`behavior_core/other_case_fact/context_time/ambiguous` 是否够用？
- 句内事实片段是否要改变 `zones` 主契约，还是只做并行 facts view？
- P2-r1 是清理后保留，还是整批弃用？
- web 未回收 party 2,737 条，哪些值得继续抽，哪些应弃权？
- S3 25 件错误里，哪些是源文缺值，哪些是解析问题？必须逐件归因，不能拿“原料差”一概而论。

## 8. 产出与验收

- 代码/测试：小步提交，WIP 也提交并标 WIP；不要留未提交改动过夜。
- 批次产物：`$DATA/s1_runs/`、`$DATA/parsed2/` 新目录；manifest 带 contract/source/view hash。
- 报告：写清分母、过滤、未解决项；不要把“格式转换数”当“可标数”，不要把“无 error”当“语义正确”。
- 交接：一文件一次，写清输入、产物、验收命令、失败处置；消费方跑通才算交接完成。

## 9. 关键路径

- `$DATA = D:/02_Dev/Data/justilaw-research`
- 全量刷新：`$DATA/unified_raw_refresh/20261018/`
- S1 输入：`$DATA/unified_raw_refresh/20261018-s1/`（对照）、`...-s1-party/`（优先）
- S1 plan：`$DATA/s1_runs/s1-20261018-dedup-party-plan/`（plan hash `17da2993…`）
- 修复后 S3：`$DATA/s1_runs/s1-20261018-segv2-final300/s3-b-review-article-fix/summary.json`
- 硬错溯源：`.../s1-20261018-segv2-final300/failure-provenance-audit.jsonl`
- 表格/句内事实：`.../docs/04-plan/seg-v2-clause-and-table-closeout-2026-10-18.md`
- WIP：分支 `codex/seg-v2-design-review`，commit `8410da7`
- 协调实时：`$DATA/coordination/CURRENT.md`
