# 未关闭问题

> 只放**当前未关闭**的阻塞与风险；解决后移入历史或从本表删除。每项必须有 owner、下一步、验收条件。
> 当前循环见 [BOARD.md](./BOARD.md)；产物见 [ARTIFACTS.md](./ARTIFACTS.md)。

**最后更新：2026-10-18 11:45**

| 编号 | 问题 | Owner | 下一步 | 验收 / 关闭条件 | 状态 |
|---|---|---|---|---|---|
| BIND-02 | Gate B 分类完成但链路未接：`classify_graph_bindings` 只写 `e05_binding`，主 `binding` 仍 1,647；`resolve_binding` 仍只接受 `lexical_candidate`；896/1709 为 `needs_review` | 后处理 + 引擎 | 决定 dev 切片是否接受显式 `needs_review`；或改主 `binding`/规则；再跑 Gate B | 分类进入主链路或有明确“仅诊断”声明；needs_review 有处置口径 | **open** |
| CONTRACT-01 | 契约未采纳：`binding_policy=null`、`semantic_rules_approved=false`、`normalization_policy=pending`；旧 bundle 已过期；版本号未随语义变更提升 | 引擎 + 后处理 | 引擎签发 policy/批准；后处理提升版本并重导 contract | `semantic_rules_approved=true`；binding_policy 非空；单一 module+版本 | **open** |
| PUSH-01 | 可见性：引擎/后处理已推送；协调事件登记工具/快照待提交 | 协调 | 提交并推送本批协调文档 | handoff 引用的 commit 在 origin 上；CURRENT 可读 | **open** |
| I-20 | 36 要素参考标签未产出；`reference_elements=null`；字段准确率暂缺 | 引擎 + 后处理 | 契约定版后，按 ≤12 → 200–300 件跑教师参考；过 I-21 门 | 参考批次有版本/哈希；A/B 分歧报告；字段 P/R/F1 可算 | **执行中** |
| I-21 | 付费批六道门：试点、赌博锚、会签、分批、按 L1 转化率验收、留评审记录 | 协调 | 任何新付费批先登记；未过门不得调用 | 六项记录齐全；L1 转化率达到约定 | **现行（无新付费批）** |
| R7-01 | r7 未放行：S3 硬失败 26/299=8.7%，门禁 <5% | 后处理 + 协调 | 先做 S3 错误分类；不把 E-05 规则与 S3 混为一谈 | S3 <5%；正式门禁全过 | **blocked** |
| DOC-01 | 陈旧“37 字段”表述仍在少数设计文档；实际 36 字段 | 各文档归属线 | 下次触碰该文档时改为 36；不为此单开循环 | grep 无现行文档写 37 | **open（低）** |
| SCOPE-01 | 循环等待期间新增功能/文档导致 WIP 扩散（效率审计、模块地图、额外批准包） | 全部线 | 本循环结束前冻结新增；只做 handoff 内事项 | BOARD 的 WIP=1 保持；无新增产物 | **现行约束** |

## 处理规则

- 新问题先登记编号，再决定是否进入当前循环；**不允许绕过 BOARD 直接开做**。
- 同一问题只允许一个 owner；跨线由 owner 发 handoff，不由协调代做。
- 关闭时必须写“证据路径/哈希/命令结果”，不能只写“已解决”。
