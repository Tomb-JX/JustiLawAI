# JustiLawAI 文档中心

> 版本 v0.5 · 2026-10-28。快变数字以外置看板 `$DATA/coordination/CURRENT.md` 为准；维护规则见 [文档维护体系](./04-plan/doc-maintenance-system.md)。

> 项目：法律大模型智能体工作平台（AI 大模型辅助裁决赌博类行政案件）· 学生大创项目
>
> 本目录是项目的**唯一文档源**：设计、需求、开发规范、计划均在此维护，随代码走 Git 版本管理。

## 文档地图

```
docs/
├── README.md                  ← 本文件：导航 + 文档管理规范
├── 01-product/                产品层
│   ├── requirements.md          产品需求说明（PRD：角色 / 功能点 / 验收 / 优先级）
│   └── glossary.md              术语表（法律 + AI 领域，团队统一用语）
├── 02-design/                 设计层
│   ├── frontend-design.md       前端设计方案（架构 / 技术选型 / 模块 / 页面）
│   ├── api-contract.md          API 契约（前后端对接唯一依据，变更须评审）
│   ├── gambling-discretion-engine.md  赌博案件智能裁量引擎方案（业界调研 / 架构 / 数据 / 评测）
│   ├── discretion-services-design.md  裁量引擎两类服务设计草案（执法计算器 + 公众结果预期）
│   ├── discretion-capability-layer.md 裁量能力层：封装、模型槽位配置、可追溯设计（草案）
│   ├── framework-panorama.md     框架全景笔记（活文档：三层全景、模块总表、逐项确认清单）
│   └── data-lake-design-2026-10-17.md  数据湖设计 v0.2（分区 / 内容寻址 blob / manifest / 目录 / 迁移；T-L1 实施）
├── 03-dev/                    开发层
│   ├── setup.md                 环境搭建指南
│   └── conventions.md           代码 / Git / 文档规范
├── 04-plan/                   计划层
│   ├── milestones.md            里程碑计划与进度跟踪（M1-M6）
│   ├── data-collection.md       数据收集计划（渠道 / 标注 / 治理 / 时间表）
│   ├── crawler-ops.md           批量采集运维计划（站点台账 / 适配 SOP / 每周节奏）
│   ├── pkulaw-playbook.md       渠道 C 北大法宝作战手册（检索式 / 导出 SOP / 侦察清单）
│   ├── pkulaw-ingest-design.md  渠道 C 数据化链路设计（实样解剖 / 字段缺口 / 导出计划）
│   ├── pkulaw-agent-design.md   法宝作业台设计（agent 自检索/预探/下载/核对；M0–M4）
│   ├── manual-collection-guide.md  人工采集指南（县级公示 / 复议 / 裁判文书网 / 信用中国）
│   ├── search-discovery-design.md  发现层设计（千帆搜索 API / 饱和拆分 / 交付文件）
│   ├── web-harvest-design.md    公开网页收割设计（分诊 → 收割 → 解析 → 脱敏）
│   ├── text-processing-spec.md  文本处理规范与数据对接分析（分段 / 脱敏 / D1–D5 待拍板）
│   ├── project-status.md        10-16 历史快照与数据流水线规范化方案；现状见 data-pipeline-status.md
│   ├── zcode-web-discovery-handoff-2026-10-17.md 网页发现层正式移交单（现行 Zcode 执行归属）
│   ├── data-pipeline-status.md  数据链路阶段总结（核对版，各来源件数与缺口）
│   ├── data-program-500-gold.md 500 件金标计划（双来源供给、质检、交付与门禁）
│   ├── coordination-audit-2026-10-16.md 交接文档现势审计（当前交付／质检／差异与责任）
│   ├── doc-maintenance-system.md 三层文档模型与检查点同步规则
│   ├── workstreams.md           并行工作树与会话分工（单写入方、交接、Git 纪律）
│   ├── collab-log.md            协作记录（只追加，union 合并）
│   └── meetings/                周例会纪要（YYYY-MM-DD-主题.md）
├── 05-research/               研究层（裁量引擎）
│   ├── reference-library.md     文献与资料库（出处 / 分级 / 选择依据）
│   ├── sota-baselines-and-gates.md  固定对照与阶段门禁（预注册，冻结后只能经偏离日志修改）
│   ├── deviation-log.md         偏离日志
│   ├── annotation-guideline.md  要素标注指南（字段表由 schema.py 生成）
│   ├── data-spec.md             行政案例数据交付规格（数据链路 → 引擎）
│   ├── data-flow.md             数据链路全景（as-built：各来源 → 解析 → 规范数据）
│   ├── data-requirements.md     引擎侧需求 → 数据交付对齐清单（五层对齐与关键字段出现率）
│   ├── wenshu-retrieval-plan.md 裁判文书批量检索需求（检索条件、字段、样例验收、合规）
│   ├── gambling-documents-and-retrieval.md 赌博案件文书体系与检索方案研究（法律体系、所需文书、案由、检索方式差别）
│   ├── pkulaw-mcp-enforcement.md 北大法宝 MCP 与行政执法数据链路调研（行政执法检索实测、全文途径、积分分配）
│   ├── notes/                   学习笔记（算法原理、操作步骤与结果解读）
│   └── gate-reports/            各阶段门禁报告
├── 06-algorithm/              算法层（裁量引擎算法设计的权威：为什么这样、试过什么、结论的适用范围）
│   ├── README.md                入口：开工必读、提议检查单、维护规则 A1–A5
│   ├── problem.md               问题骨架（A–F 分层与法律在各层的角色）
│   ├── architecture.md          现行算法架构（取代引擎方案 §4–§5 的算法内容）
│   ├── claims.md / questions.md 结论台账（带适用范围）/ 问题台账（关闭项带重开条件）
│   ├── loops.md                 已发生的兜圈子回路与触发信号
│   ├── eval-protocol.md         评估协议版本（EP-x）
│   ├── experiments.md           实验索引（一行一个，链接原报告）
│   ├── ledger-process.md        规范规则化流程（逐条台账 S0–S8）；ledgers/ 为各规范复核表
│   ├── adr/                     算法决策记录（ADR-xxx，只追加）
│   └── templates/               ADR / 实验卡 / 预注册模板
└── templates/                 模板库
    ├── api-spec.md              接口文档模板（新增接口时使用）
    ├── feature-design.md        功能设计模板
    └── meeting-notes.md         会议纪要模板
```

## 阅读路径

**阶段交接先读**：[数据链路现状](./04-plan/data-pipeline-status.md)（L1 快照）、[引擎线现状](./05-research/engine-line-status-2026-10-26.md)（L1 快照）、[现行算法架构](./06-algorithm/architecture.md)（L2 设计）、[文档维护体系](./04-plan/doc-maintenance-system.md)。运行时数字读 `$DATA/coordination/CURRENT.md`；2026-10-16 的 `project-status.md` 与 `data-flow.md` 中旧数字只作历史资料。

| 你是谁 | 建议阅读顺序 |
|---|---|
| 新加入的成员 | 根 README → 术语表 → 前端设计方案 → 环境搭建 |
| 后端同学 | API 契约（重点 §3.3 SSE）→ 产品需求 → 里程碑 |
| 指导老师 / 结题材料 | 产品需求 → 前端设计方案 → 里程碑进度 |
| 模型组（裁量引擎） | `06-algorithm/README.md`（开工必读五项）→ 引擎方案 → 固定对照与阶段门禁 → 文献与资料库 |
| 法律组（裁量引擎） | 引擎方案 §3 领域分析 → 数据收集计划（重点标注与 B-H）→ 门禁文档 |

## 文档管理规范

1. **存放位置**：所有项目文档只放 `docs/` 对应子目录，不散落在代码目录或聊天记录里
2. **命名规范**：文件名用英文小写 kebab-case（如 `frontend-design.md`），内容用中文；会议纪要加日期前缀（`2026-10-20-第2次周会.md`）
3. **新增文档**：先选用 `templates/` 中模板；无对应模板时参照现有文档结构；新增后必须更新本文档的「文档地图」
4. **变更流程**：修改文档 → 文末「变更日志」加一行（日期/版本/变更/作者）→ Git 提交（commit 前缀 `docs:`）
5. **接口契约纪律**：`02-design/api-contract.md` 是前后端对接唯一依据——**先改文档、评审通过、再写代码**；口头约定的接口一律无效
6. **评审约定**：涉及架构、契约、里程碑的变更，需在周会或群内评审通过后方可合入 `main`
7. **模块文档同步纪律（2026-10-26 起，硬性）**：任何模块的每次实质性更新（代码、数据批次、交付版本、实验结论、口径裁定），**必须在同一次提交或同一工作日内同步更新其描述文档**，不得积压到之后统一补写。具体要求：
   - 每个模块有唯一的"现状文档"作为数字与状态的出处（如数据链路 → `04-plan/data-pipeline-status.md`；引擎模块 → 协调分支全景状态文档 + 看板）。更新模块时同步刷新对应现状文档的章节与"变更日志"。
   - 现状文档只记**当前实况**；被取代的旧数字必须显式标注失效或移入历史，不允许新旧数字并存造成歧义。
   - 跨模块影响（接口、契约、口径变化）除更新本文档外，还须在 `04-plan/collab-log.md` 追加一行知会相关方。
   - 现状文档中的每个关键数字应可溯源：注明实测来源（数据目录路径、看板生成时间、git 提交号或产物哈希），不写"预计""大约"。
   - **理由**：本项目并行工作流多、迭代快，文档滞后会导致后续会话基于过时数字误判进度（见 2026-10 数据链路文档全面重写的教训）。"改了不写"视为未完成该次更新。
8. **版本规则**：文档头部标注版本号；小修（措辞/补充）+0.1，结构性调整（章节增删/方案变更）进位大版本

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-16 | v0.1 | 将 500 件金标计划加入文档地图 | 协调 |
| 2026-10-26 | v0.2 | 新增第 7 条「模块文档同步纪律」（硬性）；合并协调分支变更日志 | 宏观指引会话（用户指示） |
| 2026-10-28 | v0.4 | 文档地图加 `06-algorithm/ledger-process.md` | 引擎（规则链路） |
| 2026-10-28 | v0.3 | 文档地图新增 `06-algorithm/` 算法层；模型组阅读路径以其 README 为起点 | 引擎（规则链路，负责人批准） |
| 2026-10-28 | v0.5 | 纠正历史快照入口；增加阶段交接阅读路径和看板时效说明 | 阶段收束会话 |
