# 数据与裁量引擎工作树分工

> 版本 v1.8 · 2026-10-16 22:06 · 适用于本项目跨应用并行工作会话
> 阶段目标与计数口径见 [500 件金标计划](./data-program-500-gold.md)；字段契约见 [数据交付规格](../05-research/data-spec.md)，门禁见 [固定对照与阶段门禁](../05-research/sota-baselines-and-gates.md)。

**现行交付和金标状态见 [2026-10-16 21:12 阶段审查](./phase-review-2026-10-16.md)**。下表的提交、数量与任务交接为 18:28 快照；目录归属规则继续适用。

**21:45 更正**：阶段审查也已落后；现势与隐私退回见[交接文档审计](./coordination-audit-2026-10-16.md)。

**工作树不是会话。**用户确认：法宝和网页前端设计在 Zcode，引擎和网页信息在 Claude；金标线因 Zcode 内容审查易触发，于 22:06 转交新建的 Codex 执行会话。其他应用的历史与模型额度保留在原应用，不迁入 Codex。本会话只协调；其他会话的活动状态和消息送达仍需在各原应用核对。

## 1. 工作树登记与当前任务

| 工作线 | 工作树与分支 | 执行会话 | 目标任务与当前交接 |
|---|---|---|---|
| 协调总控（本会话） | `data-coordination` · `codex/data-coordination` | 本 Codex 会话 | 调查进度、决策记录、排期、跨线验收与合并顺序；只写协调文档 |
| 网页发现与交付 | `project-data-collection-audit-4bac93` · `claude/project-data-collection-audit-4bac93` | **Claude：网页信息线**；额度已恢复，具体会话待核 | 立即核对专属树与主线 r1 的网页输入及构建改动，接手 L2/L3 单写；先做内容抽检与警告复核，再扩河北＋江苏 |
| 法宝来源 | `legal-ai-gambling-sentencing-cb2c21` · `claude/legal-ai-gambling-sentencing-cb2c21` | **Zcode：法宝线**；具体会话待核 | 主线 `7e36827` 已产出合并 parsed-1 311 条；统一交付中 258 条 P 来源进入主文件。下一步查跨源事件和可标注率，定向补新法与不予处罚 |
| 金标质检与标注 | `jolly-cerf-82e544` · `claude/jolly-cerf-82e544` | **Codex 新会话** `01a1450d-9dd3-7fd2-834b-32e14e0788b5`；原 Zcode 会话转交后停止写入 | 保留已有代理试标与未提交 QA 改动；修复抽检 ID／JSON／覆盖率，待安全新版交付后冻结 50 件输入、重试双标并经法律复核；正式金标仍 0 |
| 引擎与验收 | `discretion-engine` · `worktree-discretion-engine` | **Claude：引擎线**；具体会话待核 | `parsed-1`／L3 契约、独立自动验收、评测和封存治理 |
| 主检出历史会话 | `D:/02_Dev/Projects/大创` · `main` | **历史会话待核** | 实际完成 `parsed-1` 和统一构建，最新 L3 为 `delivery/2026-10-16.pk1`；给各归属线交代码、批次与验收哈希后停止跨线写入 |

Zcode 的网页前端设计会话继续负责平台前端；它不是网页案例发现与收割工作线，不参与 L0–L5 计数。若未来调整执行应用，只转交任务契约、代码提交与数据批次哈希，保留原应用中的历史，不以复制聊天记录来重建上下文。

**金标转交执行规则（22:06）**：Codex 金标会话已创建并开始运行，项目目录直接指向现有 `jolly-cerf-82e544` 工作树，不复制聊天历史或覆盖未提交文件。原 Zcode 会话的停止写入尚需在 Zcode 侧确认；在确认前，新会话须先检查并发修改，遇到同文件冲突立即停写该文件并报告。外置 `qa/**`、`labels/**` 由金标新会话单写；已作废 r1 和内容安全未通过的 r2 不升格正式标注输入。

主检出目录 `D:/02_Dev/Projects/大创` 的 `main` 拟只用于浏览与人工集成，不用于并行开发。一个工作树可能被多个应用会话同时打开；**每条线只保留一个执行写入会话**，其余会话的用途要在原应用核对后决定，不能擅自标为只读或继续并发编辑。旧工作树保留到任务交接完成，不因重组而改名或删除。

## 2. 路径与数据写入权

| 写入方 | 仓库内范围 | 外置数据范围 |
|---|---|---|
| 网页 | `research/discretion/discover/**`、`research/discretion/harvest/**`、网页发现／处理设计文档 | 网页源台账与 `parsed/web/**`；共用 `delivery/<版本>/**` 唯一发布者 |
| 法宝 | `research/discretion/collect/**`、法宝采集／解析设计文档 | `inbox/pkulaw/**`、`raw/pkulaw/**`、`ingest/<法宝批次>/**`、`parsed/pkulaw/**`；现有原件只追加和核对，不覆盖 |
| 金标 | 标注指南建议、质检报告、标注任务与版本台账；需要修改 `harvest/sample_pilot.py` 时提出变更要求，由网页负责人落地 | `qa/**`、`labels/**`；不得修改 L0–L3 正本 |
| 引擎 | `justilaw-api/app/discretion/**`、`research/eval/**`、`docs/05-research/**` | `engine/acceptance/**`、封存治理产物；读取 L0–L3，不改来源批次 |
| 协调 | `docs/04-plan/workstreams.md`、`data-program-500-gold.md`、文档索引和协调记录 | 只读台账和统计，不触碰原件、交付或标签 |

外置数据根目录由 `JUSTILAW_DATA_DIR` 指定，当前为 `D:/02_Dev/Data/justilaw-research`。原件、未脱敏正文、登录态、标签正文、封存测试集和模型权重不进 Git。共享文件（契约、构建入口、`docs/README.md`、依赖、平台入口）由协调先登记变更要求，再由归属方在自己的工作树单独提交；一次提交只解决一类跨线接口。

## 3. 交接协议

1. 来源方交 L0 原件清单与 SHA-256、来源凭据和批次日期；L1 `parsed/<来源>/<批次>/records.jsonl` 通过 `records check --layer parsed`，并附分级、事件数、缺失率与重复报告。法宝已有正式 `parsed-1`；`ingest/` 中的旧产物仍只是过渡层。
2. 网页线指定一名 L2/L3 构建负责人，按显式批次清单合并、去重、脱敏和分流；发布 `delivery/<版本>/` 及校验和、统计、排除清单、数据卡草稿。任何修订另起版本；不在旧 `admin/` 路径重建覆盖。
3. 引擎线按交付版本与哈希验收，退回项只由来源或构建负责人修复。金标线另做人工内容抽检；自动字段通过不等于事实可标注。
4. 金标线仅从通过验收、可指认本人、隐私扫描合格且事件不重复的记录抽样。两名法律标注者独立试标、仲裁；正文哈希变化的标签重标。金标总数只数已人工校正并有证据链的行政案件。
5. 跨线问题写入 [协作记录](./collab-log.md)：`版本/哈希｜现象与样本 ID｜归属方｜验收条件｜交接状态`。协调会话维护一张当前状态表；旧数字作为历史保留，不与新批次混算。

用户 2026-10-16 21:24 已明确开放法宝作业台的自动检索、正文读取与有限额下载；原暂停决定已解除，执行边界与文档冲突处理见[阶段审查补记](./phase-review-2026-10-16.md)。河北＋江苏作为采集目标，省级裁量基准的现行效力和 2026 年法律衔接由法律组核验后才能冻结标注依据。

## 4. Git 与并行纪律

1. 每会话只在登记的工作树写；运行前看 `git status --short --branch`、分支和目标数据目录。相同外置目录同一时间只有一名发布者；批次名、交付版本名不可复用。
2. 用明确路径 `git add <路径>`，检查 `git diff --cached --stat` 与 `git diff --cached --check`。禁止 `git add .` / `git add -A` 把他人的文件带入提交。
3. 在自己的**干净**工作树同步 `origin/main`。绝不在别人的工作树执行 rebase、reset、stash、clean、checkout、移动或删除；有未提交文件时先由该树负责人处理。协调不替来源方改产物。
4. 分支推送为 `git push -u origin HEAD`，共享契约、里程碑和本分工经审阅／PR 后顺序合入 `main`；取消旧规则的 `git push origin HEAD:main`。合并前复查新主线，避免两线同时修改同一接口。
5. `DISCRETION_ENABLED=false` 维持默认关闭；尚未验收的引擎功能不得因主线合并而对用户开放。

## 5. 管理命令模板（PowerShell）

```powershell
$repoRoot = 'D:\02_Dev\Projects\大创'
$dataRoot = 'D:\02_Dev\Data\justilaw-research'
git -C $repoRoot worktree list
git -C "$repoRoot\.claude\worktrees\project-data-collection-audit-4bac93" status --short --branch
git -C "$repoRoot\.claude\worktrees\legal-ai-gambling-sentencing-cb2c21" status --short --branch
git -C "$repoRoot\.claude\worktrees\jolly-cerf-82e544" status --short --branch
Get-ChildItem -LiteralPath "$dataRoot\ingest" -Recurse -File -Filter 'pkulaw_ingest.stats.json'
Get-ChildItem -LiteralPath "$dataRoot\engine\acceptance" -Directory
```

工作树内的提交流程：

```powershell
git status --short --branch
git diff --check
git add <自己拥有的明确路径>
git diff --cached --stat
git diff --cached --check
git commit -m 'docs(plan): 描述本次交付'
git fetch origin main
git rebase origin/main
git push -u origin HEAD
```

此模板中的 `<...>` 必须替换成实际路径；先确定上游新提交没有改同一外置批次或接口，才同步与发布。数据目录不是 Git 工作树，不能用 Git 操作代替文件与哈希核对。

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-15 | v0.1–v0.2 | 原三工作流及直接推主线规则 | 模型组 |
| 2026-10-16 | v1.0 | 拆双来源、独立金标与验收，定义唯一写入与审阅合并 | 协调 |
| 2026-10-16 | v1.1 | 更正工作树与会话的关系；跨应用会话绑定待核，撤回仅凭 Codex 列表派工 | 协调 |
| 2026-10-16 | v1.2 | 记录用户确认的 Zcode／Claude 归属；保留各应用历史与额度，不向 Codex 镜像派工 | 协调 |
| 2026-10-16 | v1.3 | 同步法宝新增南京批与跨批去重的最新基线 | 协调 |
| 2026-10-16 | v1.4 | 确认金标质检线沿用现有原会话 | 协调 |
| 2026-10-16 | v1.5 | 更新 Claude 网页线暂停期间的主线交付与质检状态 | 协调 |
| 2026-10-16 | v1.6 | 确认金标原会话在 Zcode；记录四子代理试标分工与临时调度 | 协调 |
| 2026-10-16 | v1.7 | 记录 Claude 网页额度恢复与法宝作业台开放的用户决定 | 协调 |
| 2026-10-16 | v1.8 | 按用户决定将金标执行转到独立 Codex 会话，保留原工作树与 Zcode 历史，登记并发写入风险 | 协调 |
