# 未关闭问题

> 只放**当前未关闭**的阻塞与风险；解决后移入历史或从本表删除。每项必须有 owner、下一步、验收条件。
> 当前循环见 [BOARD.md](./BOARD.md)；产物见 [ARTIFACTS.md](./ARTIFACTS.md)。

**最后更新：2026-10-18 11:45**

| 编号 | 问题 | Owner | 下一步 | 验收 / 关闭条件 | 状态 |
|---|---|---|---|---|---|
| BIND-01 | 主体/事件绑定规则缺失：Codex `evidence_graph` 对共同/间接主体一律 `binding=unresolved`；`resolve_binding` 只接受 `lexical_candidate`；1,647 个候选未解析。引擎截至 11:47 未提交绑定表 | 引擎 | 写 `shared_fact` / `target_specific` / `needs_review` 绑定表与代码；后处理只等这一步，Gate A 不阻塞 | 212 条离线诊断：binding unresolved 下降或全部有明确分类；有正反例；版本化 | **open** |
| CONTRACT-01 | element 契约未定版：归一化/证据模块已由后处理 `256d2ce` 提交，但 `evidence_graph` 主路径仍用旧 `normalize_time/quantity`；绑定仍缺；11:17 bundle 过期；schema/prompt 版本号未随语义变更提升 | **A2 后处理；B 引擎** | 改 `evidence_graph` 主路径；补 2–3 个接入单测；绑定并入同一契约模块；提升版本号；绑定后重导 contract | 单一 module + 版本 + tests；consumer 能只引一个版本；旧 bundle 标 superseded | **open** |
| PUSH-01 | 可见性不足：引擎 7 笔、后处理 7 笔提交未推 origin；协调分支已推 `88855e6` | 各线 owner | 交接前 push / commit | handoff 引用的 commit 在 origin 上 | **open** |
| I-20 | 36 要素参考标签未产出；`reference_elements=null`；字段准确率暂缺 | 引擎 + 后处理 | 契约定版后，按 ≤12 → 200–300 件跑教师参考；过 I-21 门 | 参考批次有版本/哈希；A/B 分歧报告；字段 P/R/F1 可算 | **执行中** |
| I-21 | 付费批六道门：试点、赌博锚、会签、分批、按 L1 转化率验收、留评审记录 | 协调 | 任何新付费批先登记；未过门不得调用 | 六项记录齐全；L1 转化率达到约定 | **现行（无新付费批）** |
| R7-01 | r7 未放行：S3 硬失败 26/299=8.7%，门禁 <5% | 后处理 + 协调 | 先做 S3 错误分类；不把 E-05 规则与 S3 混为一谈 | S3 <5%；正式门禁全过 | **blocked** |
| DOC-01 | 陈旧“37 字段”表述仍在少数设计文档；实际 36 字段 | 各文档归属线 | 下次触碰该文档时改为 36；不为此单开循环 | grep 无现行文档写 37 | **open（低）** |
| SCOPE-01 | 循环等待期间新增功能/文档导致 WIP 扩散（效率审计、模块地图、额外批准包） | 全部线 | 本循环结束前冻结新增；只做 handoff 内事项 | BOARD 的 WIP=1 保持；无新增产物 | **现行约束** |

## 处理规则

- 新问题先登记编号，再决定是否进入当前循环；**不允许绕过 BOARD 直接开做**。
- 同一问题只允许一个 owner；跨线由 owner 发 handoff，不由协调代做。
- 关闭时必须写“证据路径/哈希/命令结果”，不能只写“已解决”。
