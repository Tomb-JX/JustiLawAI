# 未关闭问题

> 只放**当前未关闭**的阻塞与风险；解决后移入历史或从本表删除。每项必须有 owner、下一步、验收条件。
> 当前循环见 [BOARD.md](./BOARD.md)；产物见 [ARTIFACTS.md](./ARTIFACTS.md)。

**最后更新：2026-10-22 00:30**

| 编号 | 问题 | Owner | 下一步 | 验收 / 关闭条件 | 状态 |
|---|---|---|---|---|---|
| BIND-03 | 绑定质量未证：`e06a0af` 复跑 212（123/611/1611）、P1-r6（158/723/1708）；money shared=0，但 money/time 大量 review；无独立标注准确率；规则版语义归属已按 B-10 冻结 | 后处理 + 引擎 | 按 B-10 改教师/模型化归属；100–200 标注 + A/B；不再加规则 | 有注明来源的标注集和 precision/coverage；字段/映射有测试；不再以 review 计数当质量 | **open** |
| CONTRACT-01 | 契约未采纳：`accept_in_resolve` 已与 resolver 一致（target/shared），但 `binding_policy=proposed_pending_engine_adoption`、`semantic_rules_approved=false`；引擎尚未采纳/拒绝 | 引擎 + 后处理 | 引擎明确采纳/拒绝；规则版冻结后再定版 | 单一 module+版本；engine ack；artifact 与代码一致 | **open** |
| I-20 | 36 要素参考标签未产出；`reference_elements=null`；218 条候选池（非金标）已产出；字段准确率暂缺 | 引擎 + 后处理 + 标注 | 复核 218 候选；合格子集跑 12 → 36 → 200–300；过 I-21 门 | 参考批次有版本/哈希；A/B 分歧报告；字段 P/R/F1 可算 | **执行中** |
| I-22 | 批次质量：P2-r1 有 761 条重复 `P-2963` 权限页（duplicate_ids=760，format_ok=false，仅 591 条 facts/40 条 decision）；web-r4、P2-L4word `text_party=0`；全量刷新 canonical released+content 仅 3,728 | 后处理 + 来源 | 清理 P2-r1 重复/非文书；补 web party；按 `QUALIFIED.md` 跑 S1 主批 | P2-r1 format_ok 或明确弃用；party 策略明确；S1 主批可复现 | **open** |
| I-24 | S1 输入仍有 **558 条无 target**（web 486 / P2-r1 62 / P1b 7 / P1 3），已单列 `no_subject.jsonl`；party 回收后仍有 **736 条无 party**（web 735、pkulaw 1）；web 未回收 2,737、P2-r1 763 | 后处理 + 来源 | 补 target；web 表格/复议/处罚摘要的 party 再回收或弃权；P2-r1 清理 | no_subject 计数稳定；party 策略记录；S1/教师输入无空 target | **open** |
| I-21 | 付费批六道门：试点、赌博锚、会签、分批、按 L1 转化率验收、留评审记录 | 协调 | 任何新付费批先登记；未过门不得调用 | 六项记录齐全；L1 转化率达到约定 | **现行（无新付费批）** |
| R7-01 | r7 未放行：S3 硬失败 25/299=8.36%，门禁 <5% | 后处理 + 协调 | 按 26 件溯源修 facts/decision/表格行；固定 299 分母复跑 | S3 <5%；正式门禁全过；边界人工评测有分母 | **blocked** |
| DOC-01 | 陈旧“37 字段”表述：引擎 architecture 已改 36；其他文档触碰时同步 | 各文档归属线 | 下次触碰该文档时改为 36；不为此单开循环 | grep 无现行文档写 37 | **open（低）** |
| SCOPE-01 | 循环等待期间新增功能/文档导致 WIP 扩散（效率审计、模块地图、额外批准包） | 全部线 | 本循环结束前冻结新增；只做 handoff 内事项 | BOARD 的 WIP=1 保持；无新增产物 | **现行约束** |

## 2026-10-22 追加

| 编号 | 问题 | Owner | 下一步 | 验收/关闭 |
|---|---|---|---|---|
| VIEW-02 | 909 未用字段/前科新视图重标；57 复议/26 前科/199 公示仍混在 909 | 数据+引擎 | 路由复议/公示；应用字段/前科视图；审计 26 前科 | 0 current outcome；57/89 分流；26 前科审计完 |
| EVID-01 | 4,731 段证据 587 段/219 条不能回投原文连续 | 引擎+数据 | 逐字段降级/拆 span；复跑 located | M1 located 通过 |
| PRIOR-02 | 26 前科：2a14 假阳性、4 条 first_offense 未提及、3 条无日期；`null+推断` 契约 | 数据+引擎 | 审计；允许 null+推断或拆 has_prior | 26 条有结论；无假阳性 |
| QWEN-01 | qwen S1 zone 覆盖失败、Arrearage/鉴权、key 暴露；30c 完成 26/30；706b full 567/706 incomplete, 139 missing | 数据 | fallback/硬停；key 轮换；30/100 阶梯 | 30/100 有效率与费用达标；key 作废 |
| LAKE-706 | 706 湖文本 pilot12 12/12；full 567/706 incomplete（139 missing；113 Arrearage + 9 outcome + 4 timeout + 4 clause ID + 3 budget + 6 无诊断） | 数据 | top-up 后 resume missing-ids.json；逐类重试/质量门 | 706 输出+转换审计 |
| SEC-01 | key 已贴对话 | 用户/协调 | 轮换/作废；不写入仓库 | 新 key 生效、旧 key 失效 |

## 处理规则

- 新问题先登记编号，再决定是否进入当前循环；**不允许绕过 BOARD 直接开做**。
- 同一问题只允许一个 owner；跨线由 owner 发 handoff，不由协调代做。
- 关闭时必须写“证据路径/哈希/命令结果”，不能只写“已解决”。
