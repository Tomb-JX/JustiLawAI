# JustiLawAI 文档中心

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
│   └── framework-panorama.md     框架全景笔记（活文档：三层全景、模块总表、逐项确认清单）
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
│   ├── project-status.md        ★ 项目现状总览与数据流水线规范化方案（唯一入口：会话归属、产物分层、问题、待人工决定事项）
│   ├── data-pipeline-status.md  数据链路阶段总结（核对版，各来源件数与缺口）
│   ├── workstreams.md           并行工作流与分工（工作树、目录归属、Git 纪律、接口）
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
└── templates/                 模板库
    ├── api-spec.md              接口文档模板（新增接口时使用）
    ├── feature-design.md        功能设计模板
    └── meeting-notes.md         会议纪要模板
```

## 阅读路径

| 你是谁 | 建议阅读顺序 |
|---|---|
| 新加入的成员 | 根 README → 术语表 → 前端设计方案 → 环境搭建 |
| 后端同学 | API 契约（重点 §3.3 SSE）→ 产品需求 → 里程碑 |
| 指导老师 / 结题材料 | 产品需求 → 前端设计方案 → 里程碑进度 |
| 模型组（裁量引擎） | 引擎方案 → 固定对照与阶段门禁 → 文献与资料库 |
| 法律组（裁量引擎） | 引擎方案 §3 领域分析 → 数据收集计划（重点标注与 B-H）→ 门禁文档 |

## 文档管理规范

1. **存放位置**：所有项目文档只放 `docs/` 对应子目录，不散落在代码目录或聊天记录里
2. **命名规范**：文件名用英文小写 kebab-case（如 `frontend-design.md`），内容用中文；会议纪要加日期前缀（`2026-10-20-第2次周会.md`）
3. **新增文档**：先选用 `templates/` 中模板；无对应模板时参照现有文档结构；新增后必须更新本文档的「文档地图」
4. **变更流程**：修改文档 → 文末「变更日志」加一行（日期/版本/变更/作者）→ Git 提交（commit 前缀 `docs:`）
5. **接口契约纪律**：`02-design/api-contract.md` 是前后端对接唯一依据——**先改文档、评审通过、再写代码**；口头约定的接口一律无效
6. **评审约定**：涉及架构、契约、里程碑的变更，需在周会或群内评审通过后方可合入 `main`
7. **版本规则**：文档头部标注版本号；小修（措辞/补充）+0.1，结构性调整（章节增删/方案变更）进位大版本
