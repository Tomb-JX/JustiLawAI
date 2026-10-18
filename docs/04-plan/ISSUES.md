# 未关闭问题

> 只放**当前未关闭**的阻塞与风险；解决后移入历史或从本表删除。每项必须有 owner、下一步、验收条件。
> 当前循环见 [BOARD.md](./BOARD.md)；产物见 [ARTIFACTS.md](./ARTIFACTS.md)。

**最后更新：2026-10-18 13:40**

| 编号 | 问题 | Owner | 下一步 | 验收 / 关闭条件 | 状态 |
|---|---|---|---|---|---|
| BIND-03 | 绑定质量未证：当前代码 `60ebb52` 复跑 212 单人（310/1517/518）；P1-r6 178 条（557/1519/513）；review 为 `unclassified role: None` + 多人列表；提交说明 130/130 无落盘 artifact；`cumulative_stake` 仍 shared；无独立标注准确率 | 后处理 + 引擎 | 处置 review；独立小样本准确率；字段审计；再 Gate B | shared/review 有明确消费或显式未知；小样本准确率达标；字段/映射有测试 | **open** |
| BIND-04 | **scene-level money 回归**：`60ebb52` 把含“现场扣押/现场查获”等词的整段 money 标 shared；P1 254/399、212 57/187 是“他人姓名+赌资+金额”的个人金额，与引擎语义表 `amounts.personal_stake=TARGET` 冲突；scene 分支还覆盖了多人 evidence 的 `needs_review` 安全分支 | 后处理 | 只对 `onsite_stake_total`/`cumulative_stake` 或明确总额句应用 scene 规则；个人金额回 target/review；重跑 212 与 P1 并落盘 summary | 抽样误标=0 且有规则测试；两批计数落盘；contract/code 一致 | **open** |
| CONTRACT-01 | 契约状态不一致：`binding_policy=adopted`、`semantic_rules_approved=true`，但 `accept_in_resolve` 仍 lexical/target；代码接受 shared；artifact 与代码不一致 | 引擎 + 后处理 | 统一 `accept_in_resolve` 与 artifact；保留 shared；版本一致 | artifact 状态一致；shared 可消费；单一 module+版本 | **open** |
| PUSH-01 | 可见性：引擎/后处理已推送；协调事件登记工具/快照待提交 | 协调 | 提交并推送本批协调文档 | handoff 引用的 commit 在 origin 上；CURRENT 可读 | **open** |
| I-20 | 36 要素参考标签未产出；`reference_elements=null`；字段准确率暂缺 | 引擎 + 后处理 | 契约定版后，按 ≤12 → 200–300 件跑教师参考；过 I-21 门 | 参考批次有版本/哈希；A/B 分歧报告；字段 P/R/F1 可算 | **执行中** |
| I-21 | 付费批六道门：试点、赌博锚、会签、分批、按 L1 转化率验收、留评审记录 | 协调 | 任何新付费批先登记；未过门不得调用 | 六项记录齐全；L1 转化率达到约定 | **现行（无新付费批）** |
| R7-01 | r7 未放行：S3 硬失败 26/299=8.7%，门禁 <5% | 后处理 + 协调 | 先做 S3 错误分类；不把 E-05 规则与 S3 混为一谈 | S3 <5%；正式门禁全过 | **blocked** |
| DOC-01 | 陈旧“37 字段”表述：引擎 architecture 已改 36；其他文档触碰时同步 | 各文档归属线 | 下次触碰该文档时改为 36；不为此单开循环 | grep 无现行文档写 37 | **open（低）** |
| SCOPE-01 | 循环等待期间新增功能/文档导致 WIP 扩散（效率审计、模块地图、额外批准包） | 全部线 | 本循环结束前冻结新增；只做 handoff 内事项 | BOARD 的 WIP=1 保持；无新增产物 | **现行约束** |

## 处理规则

- 新问题先登记编号，再决定是否进入当前循环；**不允许绕过 BOARD 直接开做**。
- 同一问题只允许一个 owner；跨线由 owner 发 handoff，不由协调代做。
- 关闭时必须写“证据路径/哈希/命令结果”，不能只写“已解决”。
