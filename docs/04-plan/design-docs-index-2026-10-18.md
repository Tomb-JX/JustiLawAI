# 设计讲解文档索引（2026-10-18 · 权威版本判定）

> **当前产物（切片/契约/诊断/报告）的权威路径、版本与哈希以 [ARTIFACTS.md](./ARTIFACTS.md) 为准；本文件只负责设计文档的版本判定。**

> 用途：告诉各线“该读哪份、哪份已过时”。判定依据：各文档在所属分支的最后提交（哈希/日期）+ 文档内版本号 + 是否被后续评审/决策取代。

## 先读：状态源与主题索引

- **实时状态**：`$DATA/coordination/CURRENT.md`（自动生成）。
- **提交快照**：[BOARD.md](./BOARD.md)；产物：[ARTIFACTS.md](./ARTIFACTS.md)；决策/问题：[DECISIONS.md](./DECISIONS.md)、[ISSUES.md](./ISSUES.md)。
- 设计文档按主题查下表；与 CURRENT/BOARD 冲突时，以状态源为准。

### 主题索引（按问题找文档）

| 你想知道 | 先读 | 注意 |
|---|---|---|
| 项目目标/阶段/依赖 | [stage-plan-v2](./stage-plan-v2-2026-10-17.md) §0/§2；[项目层评审](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-project-level-design-review-2026-10-18.md) | 目标/门禁现行；六数看板是历史快照，现状看 BOARD |
| 引擎 M0–M6 概念 | [framework-panorama](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/02-design/framework-panorama.md) §3 | 概念可用；“脱敏正本”/数据进度是旧口径 |
| 当前进度/指标 | [CURRENT.md](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md)、[BOARD.md](./BOARD.md)、[p0-closure](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/p0-closure-2026-10-18.md) | CURRENT 实时；BOARD 快照；p0 是 E-01–E-04 收口 |
| 数据 L0–L3 格式 | [data-spec](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/data-spec.md) §1/§6/§7/§8；`records.py` | parsed-1/交付 + **L5 标签契约（v0.6.1 §8）**；36 要素字段 + CaseMeta 3 元数据 + binding 派生块 |
| parsed-2 / seg-v2 | [parse-format-chain-design](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/parse-format-chain-design-2026-10-17.md) v1.4；[parse-engineering-design-v2](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/parse-engineering-design-v2-2026-10-17.md) v2.5；[unify/README](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/research/discretion/unify/README.md) | 架构 v2.5 + 格式 v1.4；seg-v2/element-ref-v2；S1 句表分区、S2 locate+evidence-graph-2 |
| 36 字段/教师/标签 | [annotation-guideline](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/annotation-guideline.md)；[element-teacher-v1](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/element-teacher-v1.md)；`schema.py`/`element_labels.py` | 7 组 36 要素字段；CaseMeta 3 元数据不是标签字段；binding 是派生标注；§3.11 是绑定语义；代码是字段唯一来源 |
| 绑定/证据图 | [annotation-guideline §3.11](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/annotation-guideline.md)；`research/eval/binding_rules.py`；`research/discretion/unify/evidence_graph.py`；[EP-06](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-engineering-solutions-2026-10-18.md) §6.2；[实施报告](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-pipeline-implementation-report-2026-10-18.md) §5.2；[架构 §12](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/parse-engineering-design-v2-2026-10-17.md) | 当前代码 `e06a0af`：212 123/611/1611；P1 158/723/1708；shared 全为 count、money shared=0；无独立准确率；规则版语义归属按 B-10 冻结；BIND-03/BIND-04/BIND-05 |
| 交付/门禁/付费 | [data-spec §4](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/data-spec.md)；[sota-baselines-and-gates](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/sota-baselines-and-gates.md)；[I-21](./issues/I-21-p2-workorder-incident-2026-10-18.md)；[ARTIFACTS](./ARTIFACTS.md) | r6/r7、S3、六道付费门 |
| 决策/分工 | [DECISIONS](./DECISIONS.md)；[OWNERSHIP](./OWNERSHIP.md) | B-08：引擎契约、数据实现、独立验收 |
| 历史/不要当依据 | [collab-log](./collab-log.md)；[workstreams](./workstreams.md)；续跑单；[text-processing-spec](./text-processing-spec.md) | 历史/归属参考；脱敏已取消（D-003） |

> **重要：没有单一分支包含全部最新文档。** 每份文档以其归属分支的最新提交为准；合并 main 之前，不要用 main 或协调分支里的镜像副本。

## 快速打开（绝对路径）

**全局**
- [实时状态 CURRENT（自动生成）](D:/02_Dev/Data/justilaw-research/coordination/CURRENT.md)
- [提交快照 BOARD](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/BOARD.md)
- [产物登记 ARTIFACTS](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/ARTIFACTS.md)
- [框架全景笔记（引擎分支，概念部分现行）](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/02-design/framework-panorama.md)
- [阶段规划 v2（目标/门禁现行）](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/stage-plan-v2-2026-10-17.md)
- [评审驱动协调修订 A-01–A-06](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/review-driven-coordination-revision-2026-10-18.md)

**评审与实施（Codex 分支）**
- [seg-v2 项目层设计评审](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-project-level-design-review-2026-10-18.md)
- [seg-v2 设计独立评审](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-design-review-2026-10-18.md)
- [问题到工程方案映射 EP-01–12](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-engineering-solutions-2026-10-18.md)
- [后处理链路第一批实施与切片交接（最新）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/seg-v2-pipeline-implementation-report-2026-10-18.md)

**解析与模型调用（Codex/网页分支）**
- [解析层格式链路设计（v1.4）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/parse-format-chain-design-2026-10-17.md)
- [解析层 v2 工程设计（v2.5）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/parse-engineering-design-v2-2026-10-17.md)
- [全链路模型调用设计 full-record（v1.1）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/model-call-design-full-record-2026-10-18.md)
- [模型调用全链路反思（D1–D6）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/model-call-design-reflection-2026-10-18.md)
- [文本处理规范（2026-10-18）](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/docs/04-plan/text-processing-spec.md)

**契约、标注与门禁（引擎分支）**
- [数据交付规格 v0.5.1](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/data-spec.md)
- [要素标注指南 v0.3](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/annotation-guideline.md)
- [固定对照与阶段门禁 v0.6](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/sota-baselines-and-gates.md)
- [I-20 要素教师 v1 接口（36 字段）](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/element-teacher-v1.md)
- [数据湖设计 v0.2（main）](D:/02_Dev/Projects/大创/docs/02-design/data-lake-design-2026-10-17.md)

**现状与问题**
- [协调审计看板（活看板）](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/coordination-audit-2026-10-16.md)
- [数据分布与增量方向](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/data-distribution-2026-10-18.md)
- [I-20 要素字段标注缺口](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/issues/I-20-element-label-gap-2026-10-18.md)
- [I-21 P2 工单事故](D:/02_Dev/Projects/大创/.claude/worktrees/data-coordination/docs/04-plan/issues/I-21-p2-workorder-incident-2026-10-18.md)

## 0. 推荐阅读顺序（按任务）

1. **先确认现状**：`$DATA/coordination/CURRENT.md` → [BOARD.md](./BOARD.md)（快照）→ [ARTIFACTS.md](./ARTIFACTS.md)。
2. **要理解数据/标签**：`data-spec`（L0–L3 格式）→ `annotation-guideline`（36 字段/证据/§3.11）→ `element-teacher-v1`（教师契约）→ `schema.py`（字段唯一来源）。
3. **要看解析/seg-v2**：`parse-format-chain-design`（v1.4 格式契约）→ `parse-engineering-design-v2`（v2.5 架构 + §1.1/§3/§4/§12）→ `unify/README`（模块地图）。
4. **要看绑定/证据**：`annotation-guideline §3.11`（引擎语义）→ `binding_rules.py`（8 shared/28 target）→ `evidence_graph.py`（后处理实现）→ BOARD/ISSUES 的 BIND-03/BIND-04/CONTRACT-01。
5. **要看历史**：`collab-log` / `workstreams` / 续跑单；只作历史，不作当前状态。

## 1. 总体与产品

| 文档 | 权威位置 | 版本/日期 | 状态 | 一句话 |
|---|---|---|---|---|
| 框架全景笔记（活文档） | 引擎分支 `discretion-engine/docs/02-design/framework-panorama.md`（`cc35cd2`） | 2026-10-17 | **概念现行；历史注记** | M0–M6 概念可用；文内已加 D-003 注记并改“原文正本”入口；§6 的 10-16 数据快照仍过期，现状看 BOARD/CURRENT |
| 引擎方案 | `docs/02-design/gambling-discretion-engine.md`（`b863408`） | 2026-10-15 | 原始详细设计（历史基线） | 引擎总体方案；后续决策以全景笔记/门禁为准 |
| 产品需求 | `docs/01-product/requirements.md`（main） | 2026-10-15 前后 | 现行（产品层） | 平台/产品需求，不涉及当前数据链路 |

## 2. 数据供给与解析（网页/后处理）

| 文档 | 权威位置 | 版本/日期 | 状态 | 一句话 |
|---|---|---|---|---|
| 解析层格式链路设计 | 网页/Codex 分支 `docs/04-plan/parse-format-chain-design-2026-10-17.md`（`730ad96`） | **v1.4**（2026-10-18；标题已改 v1.3，v1.4 加现状注记） | **现行格式契约** | 逐字段契约：L0→S0→模型→S2→S3→parsed-2→交付；当前实现映射看 architecture v2.5 §1.1/§3/§4/§12 |
| 解析层 v2 工程设计（详细版） | 同上 `parse-engineering-design-v2-2026-10-17.md`（`15a5863`） | **v2.5**（2026-10-18） | **现行架构 + 实现映射 + 阻塞映射** | S1 改为 seg-v2 句表分区（服务端 quote、6 类 zones、文书字段、zones_det）；S2 改为 locate+evidence-graph-2；§9.1 实测、§10.1 执行、**§12 卡点→设计位置** |
| parse-v2 模型接口重设计（句表分区） | 同上（`c89ea69`） | 2026-10-17 | **seg-v2 设计依据（草案）** | 把“引文摘录”改为“句表 run-length 分区”；后续评审有修订建议 |
| 解析架构 v2 | 同上（`19e76c6`） | 2026-10-17 | 背景/方向 | 正则退位、模型承接、规则转校验的量化论证；接口细节以 parse-interface 为准 |
| 模型调用全链路反思 | 同上（`4b9d0cd`） | 2026-10-18 | **现行问题清单** | D1–D6 六个结构性设计错误、五条调用准入、分歧榜实测 |
| 全链路模型调用设计 full-record | 同上（`d254487`） | v1.1（2026-10-18，含勘误） | **现行现状呈现** | 5 个调用站逐接口原文/行号/实测＋O1–O12；v1.1 修正 F3 坐标混用 |
| 文本处理规范 | 网页/Codex 分支 `docs/04-plan/text-processing-spec.md`（`eca52b8`） | 2026-10-18 | **现行** | 脱敏取消后的文本处理口径；§4.2/§4.3 转外发衍生工具 |
| 网页×法宝原料对比 | 同上 `parse-input-comparison-2026-10-17.md` | 2026-10-17 | 实测依据 | 两源 parsed-1 落差、event_key 公式不一致、统一原料契约建议 |
| 数据湖设计 | **main** `docs/02-design/data-lake-design-2026-10-17.md`（`99e08d6`） | **v0.2**（2026-10-18 协调评审通过） | **现行** | 内容寻址 blob＋manifest＋SQLite catalog；T-L1 法宝线实现 |
| 网页收割设计 / 发现层设计 | 网页分支 `web-harvest-design.md`、`search-discovery-design.md` | 2026-10-15/16 | 采集层设计（非当前重点） | 收割与千帆发现；新增采集当前冻结 |

## 3. 要素、标注、交付与门禁（引擎）

| 文档 | 权威位置 | 版本/日期 | 状态 | 一句话 |
|---|---|---|---|---|
| 行政案例数据交付规格 | 引擎分支 `docs/05-research/data-spec.md`（`1152141`） | **v0.6.1**（2026-10-18） | **现行（L0–L3/交付 + L5 标签）** | 原文正本、字段总表由 `records.py` 生成；§8 L5 契约：36 要素字段 + CaseMeta 3 元数据（非标签）+ binding 派生块 |
| 要素标注指南 | 引擎分支 `docs/05-research/annotation-guideline.md`（`1152141`） | **v0.4.3**（2026-10-18） | **现行** | 36 字段；§3.11 绑定语义（引擎定语义、后处理实现）+ `60ebb52` 复跑与 scene 回归；§4 自动生成 |
| 固定对照与阶段门禁 | 引擎分支 `docs/05-research/sota-baselines-and-gates.md`（`cc35cd2`） | **v0.6 + 13:04 补记** | 现行执行口径（待周会冻结） | 8 红线、P0–P5、G1.1/G1.2；补记：绑定质量门未预注册，BIND-03 |
| I-20 要素教师 v1 接口 | 引擎分支 `docs/05-research/element-teacher-v1.md`（`113db42`） | 2026-10-18 | **现行接口** | 36 字段（非 37）；教师输入/输出与验收口径 |
| 要素本体 | 引擎分支 `justilaw-api/app/discretion/schema.py`、`element_labels.py` | 1.1.0 | **字段唯一来源** | 7 组 36 字段＋3 meta；改动需升版 |

## 4. 评审与实施（Codex 分支，最新）

| 文档 | 位置 | 日期 | 状态 | 一句话 |
|---|---|---|---|---|
| seg-v2 设计独立评审 | `seg-v2-design-review` 分支 `docs/04-plan/seg-v2-design-review-2026-10-18.md`（`abe4a94`） | 2026-10-18 | **现行评审结论** | 独立复核 D1–D6/O1–O12、契约/坐标/决策边界 |
| 问题到工程方案映射（EP-01–12） | 同上 `seg-v2-engineering-solutions-2026-10-18.md`（`b177ef1`） | 2026-10-18 | **现行实施目录** | 工程拆解、JioNLP/cn2an 选型、任务边界；不是外部工单 |
| 项目层设计评审 | 同上 `seg-v2-project-level-design-review-2026-10-18.md`（`abe4a94`） | 2026-10-18 | **现行阶段依赖依据** | A-01 切片首跑、职责边界、指标层级、两类结果分离 |
| 后处理链路第一批实施与切片交接 | 同上 `seg-v2-pipeline-implementation-report-2026-10-18.md`（`d796a3e`） | 2026-10-18 | **10:44 快照 + 13:04 更新注记** | 92 测试、免费回放、切片 212/121；§5.2 “binding 未交付”对证据级/NLP 仍成立；v5 已做证据感知 3 步，但切片无多人案例，现状看 BOARD/ISSUES |
| 评审复核回应（F3 勘误等） | 网页分支 `docs/04-plan/seg-v2-review-verification-response-2026-10-18.md`（`d254487`） | 2026-10-18 | 现行勘误 | 坐标混用 64/88、伪全未提及 5 件、88 件改判“已配对落盘” |

## 5. 协调、规划与问题单

| 文档 | 位置 | 状态 | 一句话 |
|---|---|---|---|
| 阶段规划 v2（目标树/会话编制/看板） | 协调分支 `docs/04-plan/stage-plan-v2-2026-10-17.md` | **目标/门禁现行；看板 13:04 刷新** | 阶段二目标 G2.1–G2.6；六数更新 M1 59/406；补充 v5 binding；历史编制注记 |
| 评审驱动协调修订（A-01–A-06） | 协调分支 `review-driven-coordination-revision-2026-10-18.md`（`7dd1372`） | **现行** | 依赖拆分、职责边界、指标层级、两类结果分离 |
| 数据分布与增量方向 | 协调分支 `data-distribution-2026-10-18.md`（`7dd1372`） | 现行实测 | r7 池 2,918/净新增 404/目标省 1,272；关键词仅为代理 |
| I-20 要素字段标注缺口 | 协调分支 `issues/I-20-element-label-gap-2026-10-18.md` | 现行问题单 | 36 字段无标签来源；教师契约已交付；切片可先跑诊断 |
| I-21 P2 工单事故 | 协调分支 `issues/I-21-p2-workorder-incident-2026-10-18.md` | 现行事故单 | 8,400 分换 42 L1；六道门防再犯 |
| 规范修订案（脱敏取消） | 协调分支 `normative-revision-deid-cancel-2026-10-17.md` | 现行 | 四文档逐条修订蓝本＋五补丁/版本门控 |
| 协调审计看板 | 协调分支 `coordination-audit-2026-10-16.md` | **历史快照** | 10-16/10-17 现势；当前状态用 BOARD/CURRENT |

## 6. 明确过时/不要作为依据的版本

| 旧文档/副本 | 原因 |
|---|---|
| 协调分支里的 `framework-panorama.md`、`data-spec.md`、`annotation-guideline.md`、`sota-baselines-and-gates.md` | 2026-10-16 镜像副本，落后于引擎分支；协调分支仅用于协调文档 |
| main 上的 `framework-panorama.md` / `data-spec.md` / `annotation-guideline.md` / `sota-baselines-and-gates.md` | 落后于引擎分支（`b2bda42`/`4dd4897`/`4355bc4`/`113db42`）；合并前以引擎分支为准 |
| `parse-format-chain-design` 旧标题 “v1.0” | 已于 2026-10-18 修正为 v1.3/v1.4；不再作为过时项 |
| `parse-architecture-v2`（2026-10-17） | 方向论证；接口细节已被 `parse-interface-v2-design` 取代 |
| `project-status.md`（2026-10-16 快照） | 历史快照；现行看板用协调 `coordination-audit` |
| `data-pipeline-status.md`、`data-collection.md`、`crawler-ops.md` | 旧阶段快照/计划；不作为当前执行依据 |
| `zcode-web-r3-takeover`、`zcode-web-r4-handoff`、`web-integration-directive` | 过程交接单，历史留档；不是设计依据 |
| I-20 中任何“37 要素”表述 | 已勘误为 **36 字段**（另 3 项 meta）；以 `schema.py`/element-teacher-v1 为准 |
| 旧 `admin/`、`pk1–pk4`、`w1`、`r1–r3` 交付 | 已作废/内容不安全；不要用于标注或训练 |

## 6.1 文档勘误（当前必须知道的偏差）

| 文档 | 偏差 | 正确口径/替代 |
|---|---|---|
| `framework-panorama.md`（引擎） | 已加 2026-10-18 现状注记，并把 L2/交付/哈希/合规等入口改为“原文正本”；§4.4 历史脱敏段落保留并标注；§6 数据快照仍旧 | 现状看 BOARD/CURRENT；M0–M6 概念可用；历史段落只解释旧实现 |
| `data-spec.md`（引擎） | 已补 **§8 要素标签契约（L5）**，升 v0.6.1；36 要素字段 + CaseMeta 3 元数据 + binding 派生块 | 记录单位/reference_elements/evidence/binding/验收见 §8；字段唯一来源仍是 `schema.py` |
| `annotation-guideline.md`（引擎） | 已升 **v0.4.3**；§3.11 补字段边界与 `60ebb52` 复跑 | 36 要素字段；引擎定语义、后处理实现；绑定不是教师输出 |
| `stage-plan-v2` | 六数看板已按 13:04 刷新（M1 59/406）；补充 v5 binding；历史编制注记 | 目标/门禁保留；实时状态仍看 BOARD/CURRENT |
| `workstreams.md` | 已加 13:04 现状注记；§1 会话表仍是历史 | 职责看 `OWNERSHIP.md`；历史留档 |
| `coordination-audit-2026-10-16.md` | 10-16/10-17 快照 | 当前状态用 BOARD/CURRENT |
| `seg-v2-pipeline-implementation-report` | 已加 13:40 复跑注记；§5.2 说 binding 未交付 | 对证据级/NLP 仍成立；`e06a0af` 已修 BIND-04 scene 回归，当前 212 123/611/1611；现状看 BOARD/ISSUES |
| `contract-binding-audit-2026-10-18.md`（引擎） | 版本审计；部分版本已被 `f0dd746`/`05485da` 覆盖 | 作审计清单；当前版本看 ARTIFACTS |
| `parse-format-chain-design` | 标题已改 v1.3，v1.4 加现状注记；仍是逐字段格式契约 | 不是 L5 标签契约；实现映射看 architecture v2.5 §1.1/§3/§4 |
| `text-processing-spec` | 包含已取消的脱敏/R6 主管线口径 | D-003 已取消；只作历史/外发衍生参考 |
| `collab-log.md` | 114KB 历史事件，混有旧状态 | 只追加事件；当前状态看 CURRENT/BOARD |
| “37 要素”表述 | 主要入口已修（framework/G0/M1）；历史报告仍可能残留 | 以 `schema.py`/`element-teacher-v1` 的 **36 要素字段 + CaseMeta 3 元数据（非第 37–39 要素）+ binding 派生块** 为准 |

## 7. 合并状态提醒

- 引擎代码最新 `f0dd746`（语义-only 8 shared/28 target），文档同步 `cc35cd2`；后处理代码最新 `3d05914`（v5 证据感知 3 步 + behavior/多人检测；212 123/1567/655；P1 158/1570/861），文档同步 `371ee1e`；协调最新见 `git log`。
- 三条线的最新提交**均未合并 main**；main 不能作为当前设计依据。
- 合并前，跨分支阅读按本索引“权威位置”走；合并后再统一路径。
- 当前状态始终以 `$DATA/coordination/CURRENT.md` 为准，BOARD 是提交快照。
