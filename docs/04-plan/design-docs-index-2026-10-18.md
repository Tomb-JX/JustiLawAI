# 设计讲解文档索引（2026-10-18 · 权威版本判定）

> 用途：告诉各线“该读哪份、哪份已过时”。判定依据：各文档在所属分支的最后提交（哈希/日期）+ 文档内版本号 + 是否被后续评审/决策取代。
> **重要：没有单一分支包含全部最新文档。** 每份文档以其归属分支的最新提交为准；合并 main 之前，不要用 main 或协调分支里的镜像副本。

## 0. 推荐阅读顺序

1. **先看全局**：`framework-panorama.md`（引擎分支）→ `stage-plan-v2`（协调）→ `seg-v2-project-level-design-review`（Codex）。
2. **再看数据链路**：`parse-format-chain-design`（读变更日志 v1.3）→ `parse-engineering-design-v2`（v2.1）→ `model-call-design-full-record`（v1.1）→ `seg-v2-pipeline-implementation-report`（最新实施）。
3. **要看当前决策**：`review-driven-coordination-revision` → `stage-plan-v2` → `I-20` / `I-21`。
4. **要动手实施**：Codex 的 `seg-v2-engineering-solutions`（EP-01–12）＋ `seg-v2-pipeline-implementation-report`（切片与免费回放）。

## 1. 总体与产品

| 文档 | 权威位置 | 版本/日期 | 状态 | 一句话 |
|---|---|---|---|---|
| 框架全景笔记（活文档） | 引擎分支 `discretion-engine/docs/02-design/framework-panorama.md`（`b2bda42`） | 2026-10-17 | **现行** | 项目全景：三层架构、M0–M6、数据六层、门禁；main/协调分支的副本较旧 |
| 引擎方案 | `docs/02-design/gambling-discretion-engine.md`（`b863408`） | 2026-10-15 | 原始详细设计（历史基线） | 引擎总体方案；后续决策以全景笔记/门禁为准 |
| 产品需求 | `docs/01-product/requirements.md`（main） | 2026-10-15 前后 | 现行（产品层） | 平台/产品需求，不涉及当前数据链路 |

## 2. 数据供给与解析（网页/后处理）

| 文档 | 权威位置 | 版本/日期 | 状态 | 一句话 |
|---|---|---|---|---|
| 解析层格式链路设计 | 网页/Codex 分支 `docs/04-plan/parse-format-chain-design-2026-10-17.md`（`3ea14ee`） | **变更日志最新 v1.3**（2026-10-17；文件标题仍写 v1.0，属滞后） | **现行契约** | 逐字段数据契约：L0→S0→模型→S2→S3→parsed-2→交付；读 §变更日志，不看标题版本 |
| 解析层 v2 工程设计（详细版） | 同上（`19e76c6`） | v2.1（2026-10-17） | **现行工程设计** | 五阶段管线、定位链、隐私排序取消后的设计、评测与灰度 |
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
| 行政案例数据交付规格 | 引擎分支 `docs/05-research/data-spec.md`（`4dd4897`） | **v0.5.1**（2026-10-17） | **现行契约** | 原文正本、字段总表由 `records.py` 生成；main 落后 |
| 要素标注指南 | 引擎分支 `docs/05-research/annotation-guideline.md`（`4355bc4`） | **v0.3**（2026-10-17） | **现行** | 字段唯一来源 `schema.py`；§4 自动生成 |
| 固定对照与阶段门禁 | 引擎分支 `docs/05-research/sota-baselines-and-gates.md`（`4355bc4`） | **v0.6**（预注册稿） | 现行执行口径（待周会冻结） | 8 红线、P0–P5、G1.1/G1.2；B4 定义 |
| I-20 要素教师 v1 接口 | 引擎分支 `docs/05-research/element-teacher-v1.md`（`113db42`） | 2026-10-18 | **现行接口** | 36 字段（非 37）；教师输入/输出与验收口径 |
| 要素本体 | 引擎分支 `justilaw-api/app/discretion/schema.py`、`element_labels.py` | 1.1.0 | **字段唯一来源** | 7 组 36 字段＋3 meta；改动需升版 |

## 4. 评审与实施（Codex 分支，最新）

| 文档 | 位置 | 日期 | 状态 | 一句话 |
|---|---|---|---|---|
| seg-v2 设计独立评审 | `seg-v2-design-review` 分支 `docs/04-plan/seg-v2-design-review-2026-10-18.md`（`abe4a94`） | 2026-10-18 | **现行评审结论** | 独立复核 D1–D6/O1–O12、契约/坐标/决策边界 |
| 问题到工程方案映射（EP-01–12） | 同上 `seg-v2-engineering-solutions-2026-10-18.md`（`b177ef1`） | 2026-10-18 | **现行实施目录** | 工程拆解、JioNLP/cn2an 选型、任务边界；不是外部工单 |
| 项目层设计评审 | 同上 `seg-v2-project-level-design-review-2026-10-18.md`（`abe4a94`） | 2026-10-18 | **现行阶段依赖依据** | A-01 切片首跑、职责边界、指标层级、两类结果分离 |
| 后处理链路第一批实施与切片交接 | 同上 `seg-v2-pipeline-implementation-report-2026-10-18.md`（`ba12e6f`） | 2026-10-18 | **最新实施报告** | 92 测试、免费回放、切片 212 条/121 事件、未付费/未放行 r7 |
| 评审复核回应（F3 勘误等） | 网页分支 `docs/04-plan/seg-v2-review-verification-response-2026-10-18.md`（`d254487`） | 2026-10-18 | 现行勘误 | 坐标混用 64/88、伪全未提及 5 件、88 件改判“已配对落盘” |

## 5. 协调、规划与问题单

| 文档 | 位置 | 状态 | 一句话 |
|---|---|---|---|
| 阶段规划 v2（目标树/会话编制/看板） | 协调分支 `docs/04-plan/stage-plan-v2-2026-10-17.md`（`7950f01`） | **现行** | 阶段二目标 G2.1–G2.6；评审后依赖拆分 |
| 评审驱动协调修订（A-01–A-06） | 协调分支 `review-driven-coordination-revision-2026-10-18.md`（`7dd1372`） | **现行** | 依赖拆分、职责边界、指标层级、两类结果分离 |
| 数据分布与增量方向 | 协调分支 `data-distribution-2026-10-18.md`（`7dd1372`） | 现行实测 | r7 池 2,918/净新增 404/目标省 1,272；关键词仅为代理 |
| I-20 要素字段标注缺口 | 协调分支 `issues/I-20-element-label-gap-2026-10-18.md` | 现行问题单 | 36 字段无标签来源；教师契约已交付；切片可先跑诊断 |
| I-21 P2 工单事故 | 协调分支 `issues/I-21-p2-workorder-incident-2026-10-18.md` | 现行事故单 | 8,400 分换 42 L1；六道门防再犯 |
| 规范修订案（脱敏取消） | 协调分支 `normative-revision-deid-cancel-2026-10-17.md` | 现行 | 四文档逐条修订蓝本＋五补丁/版本门控 |
| 协调审计看板 | 协调分支 `coordination-audit-2026-10-16.md` | **现行活看板** | 各线现势、决策、断点；替代旧 project-status |

## 6. 明确过时/不要作为依据的版本

| 旧文档/副本 | 原因 |
|---|---|
| 协调分支里的 `framework-panorama.md`、`data-spec.md`、`annotation-guideline.md`、`sota-baselines-and-gates.md` | 2026-10-16 镜像副本，落后于引擎分支；协调分支仅用于协调文档 |
| main 上的 `framework-panorama.md` / `data-spec.md` / `annotation-guideline.md` / `sota-baselines-and-gates.md` | 落后于引擎分支（`b2bda42`/`4dd4897`/`4355bc4`/`113db42`）；合并前以引擎分支为准 |
| `parse-format-chain-design` 文件标题的 “v1.0” | 标题未更新；**以文末变更日志 v1.3 为准** |
| `parse-architecture-v2`（2026-10-17） | 方向论证；接口细节已被 `parse-interface-v2-design` 取代 |
| `project-status.md`（2026-10-16 快照） | 历史快照；现行看板用协调 `coordination-audit` |
| `data-pipeline-status.md`、`data-collection.md`、`crawler-ops.md` | 旧阶段快照/计划；不作为当前执行依据 |
| `zcode-web-r3-takeover`、`zcode-web-r4-handoff`、`web-integration-directive` | 过程交接单，历史留档；不是设计依据 |
| I-20 中任何“37 要素”表述 | 已勘误为 **36 字段**（另 3 项 meta）；以 `schema.py`/element-teacher-v1 为准 |
| 旧 `admin/`、`pk1–pk4`、`w1`、`r1–r3` 交付 | 已作废/内容不安全；不要用于标注或训练 |

## 7. 合并状态提醒

- 引擎分支（`113db42`）与 Codex 分支（`ba12e6f`）**均未合并 main**；main 目前含 L4 Word 补救（`6be834f`）但缺上述两线最新提交。
- 在合并前，跨分支阅读请按本索引的“权威位置”列走；合并后再统一路径。
