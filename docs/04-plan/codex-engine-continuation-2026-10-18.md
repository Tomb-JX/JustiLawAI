# 引擎线续跑交接单（2026-10-18 · 额度耗尽后）

> 会话状态：引擎会话额度耗尽。工作树 `.claude/worktrees/discretion-engine`，分支 `worktree-discretion-engine`，最后提交 `aeb29b6`。
> **有未提交工作**：`m1_dev_slice_probe.py` 已修改；新增 `m2_dev_slice_audit.py`、`m4_negative_diagnosis.py`、`slice_quality_review.py`。只读备份在 `D:/02_Dev/Data/justilaw-research/handoff/2026-10-18/engine/`。

## 1. 已完成（已提交）

- `113db42` I-20 要素教师契约（36 字段、element-v1、验收脚本）。
- `d7b7e74` 首跑：M1 诊断 + M4 B4 基线；报告 `docs/05-research/dev-slice-first-run-2026-10-18.md`。
- `aeb29b6` 大写中文金额证据测试。
- 首跑数字：M1 64/64 成功、过滤后证据 363/363、字段准确率暂缺；M4 B4 **类型准确率 35.94% vs 多数类 42.19%**（负结果）；test 21 条未动。

## 2. 未提交的进展（额度耗尽前已跑出结果）

**代码**
- 修改 `research/eval/m1_dev_slice_probe.py`；
- 新增 `research/eval/m2_dev_slice_audit.py`（E-01）、`m4_negative_diagnosis.py`（E-03）、`slice_quality_review.py`（E-02）。

**结果（数据目录，10-18 10:29/10:33）**
- **E-01 M2 合法空间核对**：`engine/development/dev-slice-20261018-codex-v2-m2-legal-audit.json`
  - 212 条；可核对（有明确版本＋条款）176 条；落在默认法定选项内 **166/176 = 94.3%**；
  - flags：未引赌博罚则 36、法律版本未知 36、超出默认法定选项 10、行为日期只到月 36、非标准结果需修正审查 1、拘留超单项需合并审查 2、罚款超单项需合并审查 1、决定早于行为 1。
- **E-03 M4 负结果诊断**：`engine/development/dev-slice-20261018-codex-v2-m4-diagnosis.json`
  - 混淆矩阵/每类：拘留 P0.324/R0.444/F1 0.375；拘留并罚 P0.423/R0.407/F1 0.415；**罚款 P0/R0/F1 0（10 条真值只预测 1 条）**；
  - 输入长度四分位准确率 0.25→0.25→0.4375→0.50；已知 n-gram 四分位非单调（0.1875/0.0625/0.875/0.3125）；
  - 罚款零值/正值分组的 MAE 差异已记录。
- 这些是 E-01/E-03 的初步结果，**尚未写入报告/未提交**；数字需在新会话复核后入库。

## 3. 续跑第一件事（防丢工作）

1. `cd D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine`
2. `git status --short --branch`、`git log --oneline -3`，与备份 `status.txt`/`log.txt` 对照；`git diff` 与 `uncommitted.patch` 对照。
3. 跑测试：`python -B -m pytest justilaw-api/tests/discretion research/eval/tests -q`（按现有配置）。
4. **小提交**：先提 M2/M4/切片复核脚本与结果报告，再提 m1 probe 改动；每步测试。
5. 复核 M2/M4 JSON 与生成脚本一致（哈希、切片 manifest、caps 哈希），再写报告。

## 4. 续跑任务（按优先级）

**P0（先完成，免费）**
1. **E-01 收口**：复核 M2 结果；把 10 条“超出默认法定选项”、2 条拘留合并审查、1 条罚款合并审查、1 条非标准结果逐条列出并说明（不修改观察值）；写入 `docs/05-research/` 报告。
2. **E-03 收口**：复核混淆矩阵；解释罚款类 F1=0（类别不平衡＋预测分布坍缩）与长度效应；给出一个**预注册**的下一步基线（不在 val/test 调参）。
3. **E-02**：完成 `P-1216` 归属复核与 42/89 条“不可机械核对”项抽样；`slice_quality_review.py` 结果入库。
4. **E-04**：M1 丢弃按字段分析（47 取值无法解析 + 11 证据找不到落在哪些字段），出字段级丢弃榜。

**P1（契约）**
5. **E-05**：写七字段裁决规则（role/venue/behavior/method/times/participant/age）＋日期/金额归一＋证据语义；更新 `schema.py`/标注指南（版本升 element-v2 草案），经协作记录交后处理线，**不编辑 `unify/**`**。
6. **E-06**：`accept_element_labels.py` 适配 `element-ref-v2` 与 status/value/evidence-only 分歧类型；定义 ≤12/≤36 判据。

**P2（等参考）**
7. 字段准确率、金标特征上界、与 B4 同切片比较；卡片 v2。

## 5. 关键路径与边界

- 工作树：`.claude/worktrees/discretion-engine`
- 备份：`$DATA/handoff/2026-10-18/engine/`
- 切片：`$DATA/parsed2/dev-slice-20261018-codex-v2/`
- M2/M4 结果：`$DATA/engine/development/dev-slice-20261018-codex-v2-m{2,4}-*.json`
- 写范围：`justilaw-api/app/discretion/**`、`research/eval/**`、`docs/05-research/**`；**不编辑** `research/discretion/unify/**`（后处理线在改）、交付/标签/采集。
- 不跑付费模型；本地 qwen3.5:9b 只作诊断；无参考不算字段准确率；不合并 main、不放行 r7。

## 6. 完成标准

- 未提交脚本与结果全部提交、测试绿、M2/M4/E-02/E-04 报告完成；
- E-05 七字段规则与 E-06 验收适配交付后处理线；
- 无付费调用、无 r7、无门禁变更。
