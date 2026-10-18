# 数据链路故障定位与本分支修复（2026-10-18）

范围：只核对后处理 B 分支可读源、冻结切片和既有免费产物。`diagnose_pipeline.py` 的候选计数是规则输出数量，**不是绑定准确率**；本次没有新模型调用，也没有把旧标签晋升为参考答案。

| 位置 | 已验证的现象与工程原因 | 本分支处置 | 剩余判据 |
|---|---|---|---|
| 跨源事件键，L1→统一输入 | `harvest/to_parsed1.py::_event_key` 取可缺日的首日期和首金额，无二者时返回空；`collect/pkulaw_ingest.py::event_key_of` 取完整日期及金额集合，缺项用 `-`。同一事件无法依键稳定合并。 | 定位并保留只读；本分支无 A/采集代码写权。 | 单一构建层公式，重算两源事件组并检查跨组泄漏后重新冻结切片。旧 212/121 仍按其原冻结口径使用。 |
| S1/S3→parsed2 | final300 离线重放：S1 成功 299/300；S3 pass/warn/error = 121/152/26，硬失败 **26/299=8.70%**，超过原 `<5%` 放量门槛。26 件内有 34 条 error finding：`facts_quality` 15、`outcome_consistency` 10、`decision_present` 5、`subject` 2、`value_grounded` 2；一个记录可有多项。另有 72 个输入或契约拒收，可与 S3 错误重叠。 | 保持原失败分母和隔离状态。 | 按错误类别修复并在同一 300 件重算；不以开发切片组装成功替代正式 S3。 |
| 旧 elements→L5 | 历史 88 条落盘标签仅 6 条通过当时结构检查；64 条实际教师输入与正确投影不同。新回放审计 88、晋升 0。 | 旧批保持隔离；新候选必须带原文哈希、视图哈希、契约版本和逐字坐标。 | 新契约下独立复核参考要素，才可报告字段准确率。当前 `reference_elements=null`。 |
| 开发切片→parsed2 | `replay_pipeline.py --slice` 曾调用未定义的 `assemble_slice`，入口启动即失败；只复制切片字段也缺后续消费者使用的 `subject_mention`、事实视图等名称。 | 补齐冻结文件及 manifest 哈希验证、原文/视图校验、标准 parsed2 字段和候选元素回执复核。免费实跑 **212/212、剔除 0**，下游诊断再消费同为 212 条；输出明确 `s3_certificate=false`、`field_accuracy=null`。 | 候选元素尚未产生，不能视为训练标签或 S3 放行。 |
| 金额候选→主体绑定 | 上版 P1 399 个 `scene-level money` 中 380 个金额角色未知；场景关键词先行把这些候选和他人的个人金额写成 `shared_fact`。这违反个人赌资字段的主体语义。 | 删除场景词直接授权共享的捷径；未知角色和目标未在本小句出现的专属金额进入 `needs_review`；`resolve_binding` 不再接受原始 `lexical_candidate`。212 与 P1 两批中，`personal_stake`/未知角色金额进入 `shared_fact` 均为 **0**。 | 仍未形成可靠的 mention→amount→event→person→role 链；尤其跨句代词和多人共载需独立标注核准，不以待审数量当准确率。 |
| 契约与报告 | 导出的 `accept_in_resolve` 只有 `lexical_candidate/target_specific`，代码却接受 `shared_fact`；报告曾将未获引擎批准的旁路规则标为 `semantic_rules_approved=true`。 | 契约值与当前解析器一致；归一与绑定策略均标 `proposed_pending_engine_adoption`，诊断标 `semantic_rules_approved=false`。 | E/C 对完整字段、归一、证据语义作契约采纳后，再冻结版本及付费工单。 |

修复前协调复跑：开发 212 条 `shared/target/review=310/1517/518`；P1 多人 178 条 `557/1519/513`。本分支修复后的**规则分布**：开发 `123/611/1611`；P1 `158/723/1708`。待审增加是移除了无证据的默认绑定，不能推论准确率变化。两批 `field_accuracy=null`、`release_approved=false`。

免费回执均在外置 `$DATA`：

- `parsed2/diagnostics-bind-fix-dev212-20261018-codex/summary.json`，SHA256 `99de4f478a0ffed71663326dee17b7d7ff276f5774810ed12bf819b5782f0b74`。
- `parsed2/diagnostics-bind-fix-p1-20261018-codex/summary.json`，SHA256 `3269c2606889b5d3f4b836e058c910b6606327b59e825ba055ea9f42deceb588`。
- `parsed2/replay-devslice-bind-fix-20261018-codex-v2/summary.json`，SHA256 `fd1621bf1bfbdec3f35d944452b7bad68f6213d0183cc988e333291ddede8cd7`；其 `records.jsonl` 经下游 `diagnose_pipeline.py` 重读为 212 条。
- `s1_runs/elements-devslice-bind-fix-plan-20261018-codex/`：212 eligible，0 rejected，`execute=false`。

项目主线的下一步是：先取得可审计的 L5 参考要素及主体绑定反例集，用事件隔离的 12 件烟测检验真实字段准确率；S3 的 26 条硬错另行修复复跑。当前模块负责提供稳定输入、候选、证据和失败回执，不能用图节点召回数替代标签质量或引擎增益。
