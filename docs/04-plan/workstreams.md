# 并行工作流与分工

> 版本 v0.3 · 2026-10-26（§1–§6 为 10-15 原文；现行实况见 §7） · 适用于裁量引擎相关的并行开发（人或 AI 会话都适用）
> 配套：[引擎方案](../02-design/gambling-discretion-engine.md) · [数据收集计划](./data-collection.md) · [固定对照与阶段门禁](../05-research/sota-baselines-and-gates.md)
>
> 起因：2026-10-15 两条工作流共用一个工作树，一方做 rebase 时把另一方的原始数据临时移走（已全部恢复、核对无误）。本文件的规则就是为了不再出现这种互相打断。

## 1. 工作流登记

| 工作流 | 工作树（`.claude/worktrees/`） | 分支 | 负责内容 | 当前任务 |
|---|---|---|---|---|
| **数据链路** | `legal-ai-gambling-sentencing-cb2c21` | `claude/legal-ai-gambling-sentencing-cb2c21` | 采集、筛选、台账、脱敏、标注流水线 | 复议决定书多省适配、赌博案筛选 |
| **引擎** | `discretion-engine` | `worktree-discretion-engine` | 规范层、要素本体、评测框架、模型、接口 | P0：规范层 + 要素本体 + 指标框架 |
| **发现层** | `project-data-collection-audit-4bac93` | `claude/project-data-collection-audit-4bac93` | 用百度千帆官方搜索 API 发现赌博文书 URL 与可收割栏目，交付数据链路收割（[设计](./search-discovery-design.md)） | M0：API 探针；M1：查询规划 + 执行器 |

**2026-10-16 晚实况（发现层登记；正式归属待[项目现状总览](./project-status.md) §7 第 2、3 条由用户定）**：

| 实际在做的会话 | 实际负责 | 与上表的出入 |
|---|---|---|
| 数据链路（`legal-ai-gambling-sentencing-cb2c21`） | 复议专栏、CAIL / LeCaRD、裁判文书入库脚本（`collect/`） | 上表的"脱敏、标注流水线"实际不在这里 |
| 发现层（本工作树） | 千帆发现、公开网页收割与解析、OCR；**网页来源的 L1（`parsed/web/`）**；**共用 L2 构建**（`harvest/build.py`、`deid.py`、`r6_scan.py`、`regions.py`：脱敏、隐私扫描、区划、去重、事件分组、按版本发布交付）；试标抽样 | 交付构建与 L1 超出上表登记 |
| 引擎（`discretion-engine`） | 记录契约 `records.py`、交付验收 `accept_delivery.py`、交付规格、门禁、全景笔记、规范库、法宝 MCP 调用层 | 一致 |
| 主检出会话（主检出目录，**未登记**，自称"引擎（主检出会话）"） | **法宝来源全线**：手工导出入账（`collect/import_manual.py`）、解析与 parsed-1（`collect/pkulaw_ingest.py`、`parsed/pkulaw/`）、作业台（已暂停）；也跑过统一构建 pk1–pk3 并改过 `harvest/build.py`、`deid.py` | 写进了数据链路（`collect/`）和发现层（`harvest/`）两边的目录 |

建议（未定）：L2 共用构建归发现层一家维护，各来源只交 L1（parsed-1），要改构建在协作记录提；法宝来源并入数据链路工作流（主检出会话迁到 `cb2c21` 工作树或单独登记）。交付版本由构建写到 `delivery/<版本>/`，引擎验收后再在协作记录宣布可用。

- **一条工作流只在自己的工作树里写**。新开工作流先在此表登记，再开工。
- 主检出目录（`D:/02_Dev/Projects/大创`，`main`）只用于浏览和人工操作，不作为任何工作流的开发目录。

## 2. 目录归属

| 归属 | 路径 | 规则 |
|---|---|---|
| 数据链路 | `research/discretion/collect/**`、`docs/04-plan/data-collection.md` | 只有数据链路写 |
| 引擎 | `justilaw-api/app/discretion/**`、`research/eval/**`、`research/papers/**`、`docs/05-research/**`、`docs/02-design/gambling-discretion-engine.md` | 只有引擎写 |
| 发现层 | `research/discretion/discover/**`、`research/discretion/harvest/**`、`docs/04-plan/search-discovery-design.md`、`docs/04-plan/web-harvest-design.md`、`docs/04-plan/text-processing-spec.md`、`docs/04-plan/data-pipeline-status.md`、`docs/04-plan/manual-collection-guide.md` | 只有发现层写；不写 `collect/`。公开网页的收割与解析（`harvest/`）在数据链路主攻北大法宝期间由发现层承担（2026-10-15），台账用独立的 `harvest/manifest_web.csv`（id 前缀 W-），与 `collect/manifest.csv` 并列 |
| 共享 | `.gitignore`、`README.md`、`docs/README.md`、`research/README.md`、`justilaw-api/requirements.txt`、`docs/04-plan/milestones.md`、本文件 | 小改动、单独提交；提交前在[协作记录](./collab-log.md)留一行 |
| 平台其他代码 | `justilaw-api/app/**`（discretion 以外）、`justilaw-web/**`、`launcher/**`、`ops/**` | 引擎接入平台时只做最小改动（注册路由、开关、卡片），单独提交 |

需要改对方目录时：在[协作记录](./collab-log.md)留言说明需求，由对方改；紧急时改完立即留言。

## 3. 数据目录：放在所有工作树之外

- 原始数据和派生数据统一放在**仓库之外**的固定目录，默认 `D:/02_Dev/Data/justilaw-research/`，用环境变量 `JUSTILAW_DATA_DIR` 指定。
- 结构沿用现有约定：`raw/`、`cail/`、`lecard/`、`reconsider/`……
- **数据链路负责**：把 `research/discretion/collect/common.py` 的 `DATA_DIR` 改为优先读 `JUSTILAW_DATA_DIR`，并把现有 `research/data/` 迁移过去（迁移前后核对文件数与 SHA-256）。
- **引擎只读**这个目录；引擎生成的中间产物写到 `$JUSTILAW_DATA_DIR/engine/`。
- 封存测试集不放在这里，按[门禁文档 §7](../05-research/sota-baselines-and-gates.md) 由保管人另行存放。
- 迁移完成前，引擎通过环境变量直接指向数据链路工作树里的 `research/data/`，只读。

## 4. Git 纪律（当前不走 PR，直接推 main）

1. **只按明确路径 `git add`**，禁止 `git add -A` / `git add .`，避免把对方进行中的文件一起提交。
2. 推送前 `git pull --rebase origin main`，推送用 `git push origin HEAD:main`。
3. **禁止在别人的工作树里**执行 rebase、reset、stash、checkout、clean 或移动文件。
4. 提交小而频繁；推送后在 §6 记录一行（日期、工作流、提交、内容）。
5. 推到 main 的引擎代码默认关闭（`DISCRETION_ENABLED=false`），保证随时打 `v*` 标签发布不会带出半成品。
6. 原始数据、封存测试集、模型权重永不入库。

## 5. 两条工作流之间的接口

| 接口 | 提供方 | 使用方 | 约定 |
|---|---|---|---|
| 要素本体 `schema.py`（字段、取值、证据格式） | 引擎 | 数据链路（标注） | 引擎在 P0 发布 v1；变更时提升版本号并在协作记录中通知 |
| 案例数据交付 | 数据链路 | 引擎 | 按[行政案例数据交付规格](../05-research/data-spec.md)：来源、时间地点、**原文分段**（事实 / 理由 / 决定 / 复议审查分开存放）、结构化处罚结果、事实要素；JSONL + `SHA256SUMS` |
| 数据划分 | 数据链路生成，引擎复核 | 双方 | 按事件分组；划分文件只记 id 列表并入库；测试集封存按门禁 §7 |
| 金标标注 | 数据链路组织，法律组校正 | 引擎 | 按 `schema.py` 当前版本导出，文件名带本体版本号 |

接口有变化时，先改本节再改代码。

## 6. 协作记录（只追加）

已移到 [collab-log.md](./collab-log.md)（设为 union 合并，多方同时追加不会冲突）。新增记录请写在那里。

## 7. 2026-10-26 实况（用户裁定与分支现状；§1 登记表待周会正式改版）

**重心裁定（用户，2026-10-26）**：数据采集与处理重心**全面转向法宝端文书**；**公开网页链路（discover/harvest/parse）停止维护**——不再新增采集、不再修复解析缺口（含 I-22/I-24 的 web 部分），存量网页数据继续在统一层与 L5 管线流转。发现层工作流随之转入停止状态，其维护的共用 L2 构建（harvest/build.py）仍被交付版本使用。

**实际活跃的工作线（以协调看板 `$DATA/coordination/CURRENT.md` 为准）**：

| 线 | 分支 / 工作树 | 在做 |
|---|---|---|
| 法宝线（主检出） | main（collect/） | P 系列定向采集、L2 解析质量修复（PARSER@0.4）、Word 复核队列 |
| L5 质量线（后处理） | `codex/l5-quality-s1-run-aggregate`（l5-stable 工作树） | S1–S3 管线、要素契约、金额硬闸、VIEW 规则、field_table（230 测试） |
| 引擎 | `worktree-discretion-engine` | M4 开发银标试验、binding 影子审计、L5 金丝雀、门禁 |
| binding 服务 | `codex/seg-v2-design-review` → `codex/binding-service-v1-fix` | binding v1→v1.1 冻结与代修 |
| 协调 | `codex/data-coordination` | 看板/事件账本、审计、现行主状态文档（CURRENT-STATUS / PROJECT-PANORAMA-STATUS） |
| 前端平台 | main + 部署 | 平台功能与公网部署（与数据线独立） |
| 发现层 / 数据链路（旧登记） | `project-data-collection-audit-4bac93` / `legal-ai-gambling-sentencing-cb2c21` | **停止/半停止**：网页线停维；复议、CAIL/LeCaRD 已就位无新任务 |

**待治理事项**：① `research/discretion/unify/`（L5 全链路）只在 codex 分支，main 无法复现，需择期合并并更新本表与 §2 目录归属；② §1 的三工作流登记表与实况已严重脱节，待周会正式改版；③ 数据链路现状数字唯一出处为 [data-pipeline-status.md（2026-10-26 核对版）](./data-pipeline-status.md)。

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-26 | v0.3 | 新增 §7 实况：重心转法宝/网页线停维裁定、活跃工作线与分支对照、unify 未合 main 等治理待办 | 宏观指引会话（用户指示） |
| 2026-10-15 | v0.1 | 初版：工作流登记、目录归属、数据目录外置、Git 纪律、接口约定 | 模型组 |
| 2026-10-15 | v0.2 | §6 协作记录移到 collab-log.md 并设为 union 合并 | 模型组 |
