# 要素供给链交接备忘（2026-10-20）

> 这不是设计计划，也不是排期。它只回答四件事：现在真正的问题是什么、交接后要拿到什么、已有思路该读哪些文档、哪些判断必须靠检索/实测核对。
>
> 交接对象：接手要素供给链开发的会话/开发者。默认你已经有仓库和数据目录访问权限，能读 `D:/02_Dev/Data/justilaw-research`，能跑 `pytest`，但不默认你能调用付费模型。

> **2026-10-22 状态覆盖**：本文的进度/下一批部分已被 [CURRENT-STATUS-2026-10-22.md](../CURRENT-STATUS-2026-10-22.md) 取代；全项目分层见 [PROJECT-PANORAMA-STATUS-2026-10-22.md](../PROJECT-PANORAMA-STATUS-2026-10-22.md)。本文保留作交接背景与边界，不再作为当前状态依据。

## 0. 一句话

要素供给链现在缺的不是第 37 个字段，也不是又一层图模型，而是**一条从冻结输入到可消费标签的闭环**：同一份输入能重复产出 36 字段、每个值有证据、主体绑定可审计、质量按字段报告、结果能被 M4 直接消费，并且知道哪些字段根本不该 train。

## 1. 交接边界

### 在范围内

- 冻结输入 → 教师输入视图 → 要素标签 → 证据/绑定校验 → silver 包 → M4 消费表。
- 36 字段的字段级质量、覆盖率、弃权率、证据合法率、绑定质量。
- 小批端到端、免费回放、失败分类、成本/吞吐记录。
- 对现有 203 银标和 L5 CLI 的复用、对照、修缺。

### 不在范围内

- 不改 36 字段 schema，不新增第 37 个要素字段；字段变更只能引擎 `SCHEMA_VERSION` 升版。
- 不用本地小模型构建训练集/产标签；本地模型只允许在蒸馏后的推理侧出现。
- 不在没有新工单的情况下启动付费批；付费必须过 I-21 六道门。
- 不放行 r7，不合并 main，不把 silver 说成 gold。
- 不把“模型间一致”当成字段正确率；没有人工/独立裁决就明确写“不可测”。

## 1A. 项目全景与模块职能（新会话先读）

这一节只给“这个项目是什么、每个模块负责什么、哪些边界不能混”。细节仍在后文和引用文档里。

### 1A.1 项目在做什么

不是做一个“读判决书聊天”的通用法律助手，而是把**行政赌博处罚决定书**变成一条可计算、可追溯的裁量链：

```text
公开处罚决定原文
  → 解析/清洗/事件分组
  → 36 个要素字段（每个值带状态和原文证据）
  → M2 规范层：适用法律版本、合法处罚空间 Ω、修正情节、涉刑提示
  → M4 裁量模型：处罚类型/幅度/区间
  → M6 解释与校验
```

要素供给链负责其中“原文 → 36 要素标签”这一段。它不是整个项目，但它是 M1 训练、M4 特征、M5 类案和 M6 说理的共同上游。

### 1A.2 两条轴：数据层 L0–L5 与引擎 M0–M6

数据层：

| 层 | 职能 | 当前交接相关产物 |
|---|---|---|
| L0 原始 | 网页/法宝原文、导出文件、批次归档；只读 | 原始目录在仓库外，按批次管理 |
| L1 解析 | 统一中间格式 parsed-1；一份文书的一个当事人一条 | `parsed/<来源>/<批次>/records.jsonl` |
| L2 构建 | 清洗、原文正本、去重、事件分组、分级 | `unified_raw`、`parsed-2` 候选 |
| L3 交付 | `admin_cases.schema-1.0.0.jsonl` + 交付附件 | r5/r6/r7 交付线 |
| L4 验收 | 引擎自动验收、三档结论 | `acceptance.json` |
| L5 标注与划分 | 银标/金标、事件级 split、测试封存 | `ALL-203-silver-20261020`、`m4-pilot-203` |

注意：L5 是**独立标签支线**，不是 S0–S4 的第五个阶段。S1/S2/S3 是解析与校验，L5 是在合格输入上产要素标签；两者不能混成一个“解析模型”。

引擎层：

| 模块 | 职能 | 当前真实状态 |
|---|---|---|
| M0 知识层 | 法律原文、效力区间、36 字段本体、案例库 | 国家层规范已核对，部分省级分档已录；案例库/M5 未建；本体以 `schema.py` 为准 |
| M1 要素抽取 | 原文 → 36 字段 `{status,value,evidence}`；在线/本地抽取器 | 有刑事原型和零样本实现；行政数据没有正式训练；203 银标现在可作训练参照 |
| M2 规范层 | 适用法律版本、Ω、修正情节、涉刑提示；纯符号/代码 | 有实现，30 条黄金用例通过；省级门槛和签字仍未完成 |
| M3 定性辨析 | 只对“带彩娱乐 vs 赌博”等少数无结果标签的判断给概率 | 未开始 |
| M4 裁量模型 | 要素 + Ω + M3 + 类案 → 处罚类型/幅度/区间；核心模型 | 只有 B4 文本基线 pilot；要素增益未证；test 40 未动 |
| M5 类案检索 | 相似案件、相同/不同点、处罚分布 | 未开始 |
| M6 解释与校验 | 反事实、追问、偏离预警、三段论说理 + 校验器 | 未开始 |

最容易误解的是：**M1 不是 L5 教师**。L5 教师是离线产标模型；M1 是未来要被训练/部署的抽取器。203 银标可以给 M1 做训练参照，但“教师产出了 203 条”不等于“M1 已达到 203 条的质量”。

### 1A.3 解析链 S0–S4 与 L5 的位置

```text
S0 清洗
  → S1 seg-v2：句表 + zones（facts/evidence/reasoning/decision/review/meta）+ 文书字段
  → S2 locate/evidence graph：把证据引文定位回原文，产候选/绑定
  → S3 确定性校验：结构、证据、outcome 一致性、日期、金额、来源
  → S4 人工层（需要时）
L5（独立支线）：合格输入 → 教师 A/B/C → 36 要素标签 → silver/gold
```

- **S1 必须看 decision**，因为要抽 outcome、法条、执行方式。
- **L5 不能看 decision/review/outcome**，否则会从处罚结果反推要素；L5 输入只有 facts/meta（加 target/aliases）。
- **S2 的绑定不是 36 字段**；它回答“这个值算谁的”，是派生标注。
- **S3 不是训练标签**；它是质量门，失败件不能因为“模型能标”就放行。

### 1A.4 核心对象与术语

一条记录通常是**一个案件里的一个当事人**；多人案件拆成多条，每条有 `target` 和 `aliases`。

- `text_full`：原文正本；所有证据坐标相对它。
- `facts_text` / `meta_text`：L5 教师实际看到的视图；由 S1 句表投影，不能重新分段。
- `allowed_sentences`：现行教师 wire 的句表；模型只回 `sentence_ids`。
- `elements`：7 组 36 字段，每个字段 `{status,value,evidence}`；`status` 为明确/推断/未提及。
- `CaseMeta`：`region`/`behavior_date`/`decision_date` 三个记录级元数据，不是第 37–39 个要素字段，也不由教师输出。
- `binding`：`shared_fact`/`target_specific`/`needs_review`，派生标注，不是教师输出。
- `observed_outcome`：处罚类型/拘留天数/罚款等，是 M4 的目标列；绝不能作为教师输入。
- `parsed-1`：统一中间格式；`parsed-2`：S1 产物/带标签装配件的统称。**这两个名字在不同文档里有漂移，交接时以 manifest 和实际 schema 为准，不要凭名字判断。**
- silver / gold：silver 是训练可用、非人工金标；gold 需要人工或独立裁决。203 是 silver，`gold=false`，test 40 禁用。
- B4：M4 的文本基线（TF-IDF/线性模型），不是 36 要素模型；B4 好不代表要素供给有价值。
- Ω：M2 由法律版本/地区/情节算出的合法处罚空间；M4 的输出必须落在 Ω 内。

### 1A.5 最容易混淆的六个边界

1. **36 要素 vs CaseMeta vs binding**：只有 36 字段是 `elements`；CaseMeta 是记录元数据；binding 是归属元数据。
2. **outcome vs elements**：outcome 是答案列，不能进教师输入；从 outcome 反推要素就是泄漏。
3. **S1 vs L5**：S1 看全文（含 decision）做分区/结果；L5 只看 facts/meta 做要素；两者输入可见性不同。
4. **M1 vs 教师**：教师是离线产标者；M1 是抽取器；教师标签是 M1 的参照，不是 M1 已达标。
5. **silver vs gold**：203 是 silver，不是人工真值；不能用它宣称“字段准确率”。
6. **r5/parsed-1 vs S1**：r5 与 parsed-1 在 945/945 个值上相同，r5 不是独立第二解析器；S1 对照只能说明相对差异。

### 1A.6 当前状态一句话

203 条银标（135 事件）已经能组装 M4 pilot，但要素供给链还不是生产线：输入有 S1 facts 缺陷，教师只有 smoke/小批证据，binding v0 覆盖率不足，M4 只有 B4 文本基线，G2.2 仍是条件性 silver。新会话不要把“有 203 条标签”误读为“要素链已完成”。

## 2. 问题画像

### 2.1 链没有真正连起来

现在有四段各自可用的东西，但它们不是一条链：

1. **输入段**：`export_l5_inputs.py` 从 S1/S3 产出教师输入，v3b 池 328 条中 accepted 203、quarantine 125（123 答案泄漏 + 2 upstream S3 error）。输入是 facts/meta 句表，不是全文。
2. **教师段**：`run_elements.py` 走 `element-ref-v2` wire，模型只回 `sentence_ids`，`compile_references` 再生成 quote/start/end；A/B 盲标、C 仲裁。smoke12 有 12/12 valid 的记录，但没有“203 条全量自动 A/B/C 完成并验收”的证据。
3. **绑定段**：`binding.py` v0 是独立的类型化候选/约束模块，203 回放只有 115 个绑定、768 个 unresolved，`conduct.times` 0 个绑定；它没有接进 `run_elements.py` 主路径。
4. **消费段**：`build_m4_pilot.py` 已能用 203 银标 + CaseMeta + observed_outcome 生成 M4 表；B4 文本基线 acc 56.52%、macro-F1 .517，多数类 47.83%/.216；但这是文本基线，不是要素增益证明。

所以“要素供给链开发”首先要回答：**这四段怎么在同一份冻结输入、同一版契约、同一套证据规则下连起来**，而不是继续各写各的。

### 2.2 203 银标是参照，不是生产线

- 203 条 / 135 事件；split 140/23/40；0 泄漏、0 证据校验错误；1,226 个非空字段 accepted，79 个降级；`release_approved=true` 只代表 silver 训练可用，`gold=false`、test 禁用。
- 标签来源是 `manual-subagent` 180 条 + `manual-coordinator` 23 条，不是 L5 CLI 产出，也不是人工专家金标。
- 203 条的字段密度极不均匀：`conduct.times` 人工只有 9 个非空，silver accepted 只有 1 个；`commission` 15、`per_bet` 11、`cumulative_stake` 3。大量字段是“未提及”，不是“模型学会了”。
- 203 条本身有渠道偏样：pkulaw 66 / web 137；web 的 facts 更短、要素更稀。不能把 203 的字段率直接外推到 534/全量。

**交接含义**：203 可以用来做参照集、错误分析和回归，但不能当作“自动供给链已验收”的证据；更不能用 test 40 调参。

### 2.3 输入端仍有真实缺陷

- G2.2 50 条审计：S1 facts 侧 7/50 有实质问题（5 A + 2 C），主要是把自首/前科/孕妇/查获经过放进 reasoning/evidence，或把证据目录/处罚结果并进 facts；P-1174、P-1009、P-1084 会直接影响 L5 要素。
- `outcome.not_executed` 有 6 条 parsed-1 抽错；parser 的 `NOT_EXECUTED` 模式已补 `不(?:予)?执行(?:行政)?拘留`，102 个 harvest 测试通过，但 parsed-1 没有重跑，当前数据仍是旧值。
- 输入侧还有 target 缺失/不在投影视图、P2-L4word 视图 0 通过、web 当事人段缺失等历史问题。`CURRENT.md` 是 2026-10-18 的快照，不能当今日状态；以最新 handoff/quality evidence 为准。
- 输入不是“全文越长越好”：fact 中位约 103 字，很多关键字段没有正例；先做密度/正例率审计，再谈扩量。

### 2.4 教师契约不等于字段质量

- 教师只输出 7 组 36 字段，`status` 为明确/推断/未提及，证据只给 `sentence_ids`；`CaseMeta` 和 `binding` 都不是教师输出。
- 现行契约能保证“结构合法、句子可编译、证据逐字”，但不能保证“字段语义正确”。17 条教师契约记录 vs 203 人工的交叉校准里，金额只有 2 处分歧，主要分歧在 `times`、`pregnant_or_nursing`、`venue`、`method`、`profit_purpose`、`first_offense`、`violations_last_year`、`participant_count`。
- 模型会自由写数值，候选表/`value_ref` 还没有进入教师输入；金额归一化口径（如 `3000余元` 应为 3000–3999，而不是开口）仍是独立问题。
- A/B/C 的 C 仲裁在历史工单里出现过 B=C 同模型，存在“同模型复核”退化；改配置又会改契约哈希。不要把“三模型”当默认事实，先看工单和 provider 身份。

### 2.5 绑定仍是 proposal，不是已验收能力

- `binding_rules.py` 的 8 shared / 28 target 语义表是对的，但只是表；`binding.py` v0 是 clause + 最近谓词 + 多主体检查，不是 ILP/全局推断。
- 203 回放 115 个绑定、768 个 unresolved；`times` 0 绑定。未解析主因包括日期多属 CaseMeta、多人需要 review、无金额谓词、出生日期需要行为日期、无计数谓词。
- 当前 binding 不能直接写进教师标签；`needs_review` 必须显式保留，不能静默当正确。
- 研究上对应的是 document-level event argument extraction + entity/relation joint inference + ILP/约束，不是再写一套“金额附近找角色词”的正则。

### 2.6 质量声明容易说过头

- G2.2 现在只能算“证据包完成、silver 训练可用”，不是 formal release：33 条 S1/parse 分歧裁决后 S1 18/33 vs parse 22/33，但 1,388 条 same 未复核；r5 只覆盖 135/203 且 r5=parsed-1 945/945，不独立；spec50 原始 50/50 有 decision 范围歧义，政策裁决后 canonical U=0、decision core 50/50，但 S1 facts 7/50 仍差。
- 没有第二人工复核；政策裁决是协调层做的，不是指南被独立批准。
- M4 pilot 的 `release_approved=false`；test 40 未评估。B4 56.52% 不能证明 36 要素有增益。

## 3. 预期目标

目标写成“拿到什么”，不写成“先做 P0 再做 P1”。

### G1：一条可复跑的端到端供给链

在冻结输入上，能从 manifest 一条命令/一个入口产出：

- 36 字段 + `status` + 证据（quote/start/end 或 sentence_ids 编译结果）；
- binding（shared/target/needs_review）与来源；
- `label_provenance`、契约版本、prompt 版本、输入哈希、backend；
- 失败分类与可恢复状态（不是中途死掉只留 traceback）。

验收不是“跑完了”，而是：同一 manifest 重跑得到可解释的相同/差异结果；失败项有明确原因；不依赖手工改目录。

### G2：字段级质量证据，而不是一个总准确率

至少按字段报告：

- 有值字段的 precision/recall（相对 203 silver 或独立裁决集；如果只有 silver，要明确“相对参照，不是人工真值”）；
- 证据合法率（逐字、来源在 facts/meta、坐标正确）；
- `未提及` 的正确率/漏标率；
- 弃权率（needs_review/abstain）与 silent wrong；
- 按渠道（web/pkulaw）、按 facts 长度、按多人/单人分层。

特别关注 `times`、`pregnant_or_nursing`、`venue`、`method`、`profit_purpose`、`first_offense`、`violations_last_year`、`participant_count`；不要用金额字段的高分掩盖它们。

### G3：绑定可审计，且不阻塞主链

- 每个 target 字段有主体边；每个 shared 字段没有单主体硬绑；
- 多人/共同事实/指代不清时输出 `needs_review`，不硬猜；
- 报告 binding coverage/precision（哪怕只在 50–100 条人工抽查上），而不是只报分类计数；
- binding 可以作为可选增强接入教师，但不能让教师看不到候选就自由写数值，也不能把 binding 当已验收的语义真值。

### G4：M4 消费证明要素有增量

- 用同一事件级 split，比较：多数类、B4 文本基线、B4 + 要素特征、仅要素特征；
- test 40 保持不动，只在最后评估；
- 如果要素特征没有超过 B4，要能说出是字段太稀、标签噪声、绑定错，还是任务本身文本已足够；不要用“模型还没调好”掩盖。

### G5：明确哪些字段不该供

- 对每个字段给出“可训练/仅诊断/暂不供”的判断，依据是正例数、证据质量、标注一致性、下游增益；
- 如果 `times` 只有 9 个非空、silver 只剩 1 个，就不要假装能训练 36 字段全量；
- 允许结论是“缩窄 M4 目标”或“先补数据密度”，而不是硬扩量。

### G6：运行约束可交付

- 支持断点续跑、缓存命中、失败核账、字节闸、锁接管；
- 付费前有工单、预算、review 字段、I-21 六道门；
- 记录每条记录的成本/延迟/失败类型；不把本地小模型塞进产标签路径。

## 4. 判断“链是否成立”的硬问题

交接后不要先写架构，先回答这些问题：

1. 从 manifest 到 labels，能不能在不手改文件的情况下重跑？重跑差异是否有解释？
2. 每个有值字段能不能回到 facts/meta 的连续原文？`compile_references` 的逐字校验有没有被绕过？
3. 36 字段里有多少字段的正例足以支撑报告？`times`/`commission`/`per_bet` 这类稀疏字段准备怎么处理？
4. 多人/多金额/共同事实时，binding 输出的是主体、shared 还是 `needs_review`？有没有人工抽查的 precision？
5. 教师输出和 203 silver 的差异，哪些是字段规则歧义、哪些是模型读错、哪些是证据缺失？有没有按字段归类，而不是只看总一致率？
6. M4 加要素特征后，事件级 test 是否超过 B4？如果没有，是否还敢说“要素供给有价值”？
7. 当前标签包的 provenance、split、test 禁用、release 状态是否在 manifest 里写清楚？
8. 失败/中断后能否恢复，是否会重复计费或产生未知账？

## 5. 参考文档（按“为什么读”排序）

### 5.1 先建立契约与字段语义

| 文档 | 位置 | 读它解决什么 |
|---|---|---|
| 要素教师 v1 接口 | `D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/element-teacher-v1.md` | 36 字段、输入边界、教师输出、A/B/C、首批验收、binding/CaseMeta 不是教师输出 |
| 标注指南 v0.4 | `.../discretion-engine/docs/05-research/annotation-guideline.md` | 字段裁决规则（E-05）、`times`/`age`/`venue`/`method` 等易错字段、§3.11 绑定语义 |
| 数据交付规格 v0.6.2 | `.../discretion-engine/docs/05-research/data-spec.md` | §8 标签契约、evidence 坐标、`label_provenance`、release 语义；§1.3 facts/decision 新裁决 |
| schema / element_labels | `.../discretion-engine/justilaw-api/app/discretion/schema.py`、`element_labels.py` | 字段唯一来源、`SCHEMA_VERSION`、`PROMPT_VERSION`、`validate_teacher_output` |

### 5.2 再理解输入与 S1/L5 分工

| 文档 | 位置 | 读它解决什么 |
|---|---|---|
| 解析层 v2 工程设计 v2.10 | `.../seg-v2-design-review/docs/04-plan/parse-engineering-design-v2-2026-10-17.md` | §3A S1/L5 分工、§3.2 zones、§4.3 binding、§3A.2 教师输入视图 |
| L5 语义绑定实现计划 | `.../discretion-engine/docs/04-plan/l5-semantic-binding-implementation-plan-2026-10-20.md` | 绑定 v0 的真实状态、115/768、未接教师、目标架构与限制 |
| 绑定/标签供给研究笔记 | `.../discretion-engine/docs/05-research/notes/2026-10-20-binding-and-label-supply-research.md` | DocEAE/ILP/RAG/Snorkel 等研究地图，哪些能借、哪些不能直接搬 |
| L5 CLI 严格审计 | `.../data-coordination/docs/04-plan/2026-10-20-l5-cli-audit-and-test-plan.md` | 付费 CLI 的缓存、锁、字节闸、重试、C 仲裁、坐标系问题；这是开发前必读 |
| v3b 池完成交接 | `.../data-coordination/docs/04-plan/handoffs/2026-10-18-l5-v3b-pool-complete-handoff.md` | 328 池、203 accepted、125 隔离、S1/S3/教师输入的来源与坑 |
| element 契约 v1 交接 | `.../data-coordination/docs/04-plan/handoffs/2026-10-18-element-contract-v1.md` | 契约、binding 验收、历史不一致；注意其中的旧状态不能当今日结论 |

### 5.3 质量证据与消费

| 文档/产物 | 位置 | 读它解决什么 |
|---|---|---|
| G2.2 裁决包 | `D:/02_Dev/Data/justilaw-research/parsed2/g22-adjudication-20261020/G22_ADJUDICATION.md` | 33 条 S1/parse 裁决、r5 135/203、spec50、S1 facts 缺陷、parsed not_executed |
| 银标质量证据 | `D:/02_Dev/Data/justilaw-research/s1_runs/manual-batches/ALL-203-silver-20261020/QUALITY_EVIDENCE.md` | 203/135、1,226 accepted、79 downgraded、0 泄漏/0 证据错误 |
| 银标 manifest | `.../ALL-203-silver-20261020/manifest.json` | split、source quality、g22 状态、可用边界 |
| M4 pilot | `D:/02_Dev/Data/justilaw-research/parsed2/m4-pilot-203-silver-20261020/manifest.json` | 203/135、B4 56.52、release_approved=false、test 未评估 |
| M4 builder | `.../discretion-engine/research/eval/build_m4_pilot.py` | elements + CaseMeta + observed_outcome 的实际 join/拆分逻辑 |
| silver builder | `.../discretion-engine/research/eval/build_silver_203.py` | 证据修复、binding audit、降级规则；理解 79 个字段为什么被降级 |
| I-20 要素缺口 | `.../data-coordination/docs/04-plan/issues/I-20-element-label-gap-2026-10-18.md` | 为什么 36 字段标签此前断供；历史背景，不是当前 blocker 全文 |

### 5.4 代码入口（读代码，不要只读文档）

| 代码 | 位置 | 看什么 |
|---|---|---|
| `run_elements.py` | `.../seg-v2-design-review/research/discretion/unify/run_elements.py` | 输入构造、A/B/C、`compile_references`、验收、批处理 |
| `element_contract.py` | 同目录 | `element-ref-v2`、契约哈希、`reference_schema`、`messages`、`compile_references` |
| `element_labels.py` | `.../discretion-engine/justilaw-api/app/discretion/element_labels.py` | 36 字段提示、三态校验、`teacher_messages` |
| `binding.py` | `.../discretion-engine/justilaw-api/app/discretion/binding.py` | v0 候选/图/约束；看它为什么只有 115 个绑定 |
| `binding_rules.py` | `.../discretion-engine/research/eval/binding_rules.py` | 8 shared / 28 target 的唯一语义表 |
| `export_l5_inputs.py` | `.../seg-v2-design-review/research/discretion/unify/export_l5_inputs.py` | S1/S3 → 教师输入的资格、泄漏隔离、视图构造 |
| `build_m4_pilot.py` | `.../discretion-engine/research/eval/build_m4_pilot.py` | 消费端实际字段形状、split、outcome join |
| `build_silver_203.py` | `.../discretion-engine/research/eval/build_silver_203.py` | 从人工草稿到 silver 的证据/绑定/降级规则 |

## 6. 调查研究检索方向（核对清单）

下面不是“采用清单”，而是交接后要自己核对的技术判断。每项都给出检索词、要验证的点、以及“如果验证失败会怎样”。

### 6.1 文档级事件/论元抽取

- 检索词：`DocEE argument scattering`、`GIT document-level event extraction`、`SCPRG role relevance`、`TSAR AMR document argument extraction`、`PAIE prompt argument interaction`、`HMEAE hierarchical argument extraction`。
- 核对：这些工作是否真的处理跨句论元、多事件、多角色；它们的监督数据有多大；我们只有 203/135 事件，是否足以训练；能否只用它们的**结构**（事件-角色-论元图）而不训练深度模型。
- 如果核对失败：不要上 GNN/大模型；退回 typed graph + 约束 + 小样本规则。

### 6.2 实体/关系联合抽取

- 检索词：`multi-head joint entity relation extraction`、`PFN partition filter network`、`RIFRE heterogeneous graph relation extraction`、`RECON knowledge graph relation extraction`。
- 核对：候选-字段分配是否能表达成“关系分类”；图结构是否比“候选 + 硬约束”带来可测增益；在低资源法律文本上是否仍成立。
- 如果核对失败：不要为了“图”而图；先做 ILP/约束。

### 6.3 全局约束/ILP

- 检索词：`Yih Roth ILP global inference`、`ILP inference cookbook`、`OR-Tools integer linear programming`。
- 核对：shared/target、唯一归属、事件一致性、同一金额不能双字段，能否写成线性约束；变量规模（36 字段 × 候选数）是否可解；无解/多解如何 abstain。
- 如果核对失败：保留 v0 约束传播，不要硬上求解器。

### 6.4 RAG / schema-guided extraction

- 检索词：`RAG4RE retrieval relation extraction`、`GenSIE schema-guided information extraction`、`GoLLIE guideline zero-shot IE`、`GLiNER open schema NER`。
- 核对：检索相似标注是否会泄漏 test；schema/guideline 是否能稳定约束 36 字段；RAG 对“角色/归属”是否有增益，还是只对“找证据句”有增益。
- 如果核对失败：RAG 只做证据句推荐，不做字段权威。

### 6.5 法律要素/判决数据集

- 检索词：`LEEC legal element extraction`、`MSLR-Bench Chinese legal reasoning`。
- 核对：LEEC 的 159 标签/多被告/多事件结构能否借；行政赌博 36 字段与刑事要素的差异；它们的评估是否包含证据/绑定。
- 如果核对失败：只借任务结构和错误分类，不借标签体系。

### 6.6 弱监督、弃权与标注质量

- 检索词：`Snorkel data programming`、`selective prediction coverage risk`、`Dawid-Skene label aggregation`、`OLAF LLM annotation quality`。
- 核对：parser/规则/模型能否作为 labeling function；如何估计 LF 准确率；needs_review/abstain 的 coverage-risk 怎么报告；模型间一致率为什么不能当正确率。
- 如果核对失败：不要用弱监督替代人工/裁决；只做候选/粗标。

### 6.7 中文句法/语义角色与归一化

- 检索词：`LTP semantic role labeling Chinese`、`HanLP dependency parsing`、`JioNLP TimeParser MoneyParser`、`Microsoft Recognizers Text`、`Duckling Chinese date amount`。
- 核对：谓词-论元（抽头/提供场地/查获）能否补主体边；中文金额（三千余元、五百元整、打码）和日期（月底、期间、农历）边界；库输出是否可回原文偏移。
- 如果核对失败：继续用引擎 normalization 作权威，JioNLP 只做后端/差分。

### 6.8 法律 LLM 标注/裁判

- 检索词：`LLM legal information extraction`、`LLM annotation agreement law`、`LLM-as-judge bias`、`selective prediction legal NLP`。
- 核对：模型 A/B/C 的提供方独立性、同模型复核、位置/长度偏差；是否需要人工抽检；如何记录 `model-adjudicated` 而不是 gold。
- 如果核对失败：不要把模型裁决写成人工真值；保留 `human_review=false`。

## 7. 当前可复用资产与路径

- 203 银标：`D:/02_Dev/Data/justilaw-research/s1_runs/manual-batches/ALL-203-silver-20261020/`
- 原始 203 人工草稿：`.../ALL-203/labels.jsonl`
- 教师输入：`.../l5-quality-pool-v3b-run/l5-teacher-inputs-v4/teacher-inputs.jsonl`（203 accepted）
- S1 输出/S3：`.../l5-quality-pool-v3b-run/combined/outputs.jsonl`、`combined/s3/`
- 328 池 manifest：`.../l5-quality-pool-v3b-20261018/MANIFEST.json`
- M4 pilot：`.../parsed2/m4-pilot-203-silver-20261020/`
- G2.2 裁决：`.../parsed2/g22-adjudication-20261020/G22_ADJUDICATION.md`
- 绑定 v0 回放：`D:/02_Dev/Data/justilaw-research/parsed2/m4-pilot-203-20261020/binding-v0-replay.json`、`binding-v0-proposals.jsonl`；用 `.../discretion-engine/research/eval/binding_replay.py` 可复算。
- L5 CLI 工单/账本：`.../s1_runs/l5-v3b-*`、`shared-budget/`；先读审计文档再碰付费目录。

## 8. 交接后第一份产出

不要先交“架构图”。先交一页**要素供给链诊断报告**，至少包含：

1. 当前切片/输入/契约/模型/预算的身份（manifest、哈希、provider）。
2. 36 字段的 field-level 覆盖/正例数/未提及率/证据合法率。
3. 绑定 coverage、needs_review 率、按字段的主体错误样例。
4. 与 203 silver 的字段差异分类：规则歧义 / 模型读错 / 证据缺失 / 输入缺失。
5. M4 是否值得加要素特征的初步判断（可以用现有 B4 对照，不要求立刻训新模型）。
6. 三个必须由项目层裁决的问题（例如 `times` 口径、shared 场景字段、哪些字段暂不供）。

这份报告的价值在于把“要素供给”从“模型输出 36 个键”变成“可验收的数据产品”。如果报告只能给出一个总准确率，说明还没有真正进入供给链开发。

## 9. 纪律

- 不把 203 silver 叫 gold；不把模型间一致叫准确率；不把 r5 叫独立第二解析器。
- 不用本地小模型产标签/建训练集。2026-10-21 项目裁决：付费批次不再走 smoke/spec36 工单与 36 条小批上限；仍保留“不重复计费、证据可编译、答案不泄漏、test 封存”四条必要保护。
- 不在 test 40 上调参；不把 test 结果写进开发迭代。
- 不改 schema、不放行 r7、不合并 main；需要变更时走引擎契约升版和协调记录。
- 任何“提升”必须给出对照、样本、分层和失败样例；没有对照就不写“提升”。

## 10. 扩产阶梯（2026-10-21 数据侧）

### 10.1 先把“扩产”定义清楚

**扩产不是把 203 条再跑一遍。** 203 已是人工 silver 参照集；重跑它只增加模型标签，不增加新案件。扩产指的是：

```text
从尚未标注的 S1-ready 记录中
  → 选新案件
  → S1/S3 合格
  → 导出教师输入
  → L5 A/B/C 产标
  → 证据/绑定/字段支持审计
  → 形成新的 silver 供给包
```

当前可用盘子：

- S1 输入约 3,196 条 / 1,790 事件；其中 558 条 no_subject，实际可产要素上限约 2,640 条。
- 现有 328 池只覆盖其中一小部分：203 accepted、125 quarantine；203 只占约 2,640 的 7.7%。
- 所以真正的扩产瓶颈在 **S1/S3/export 的覆盖**，不是 L5 CLI 的跑批按钮；L5 只是后半段。

### 10.2 三级扩产，不按日期按门

**A. 参照级（已有，不再跑）**

- 203 条人工 silver / 135 事件。
- 用途：字段规则校准、错误分析、教师/绑定对照。
- 不重跑 L5；不把它当“新增 203 条”。

**B. 试点扩产：200–300 条新案件**

- 从 3,196 条 S1 输入中排除已有 328/203，优先选：
  - pkulaw 叙述式、facts ≥100 字；
  - 有金额/参赌人数/前科/抽头等正例线索；
  - 事件去重后不跨 split；
  - web 只取有当事人段、facts 较完整的层。
- 目标：S1/S3/export 后得到 120–200 条教师输入，L5 产出 120–200 条模型标签。
- 这是“能否扩产”的判定批，不是全量。

**C. 规模扩产：600–1,000 条新案件**

- 只有 B 的证据合法率、字段支持率、A/B/C 分歧率、单条成本过关才做。
- 目标新增 300–600 条可用 silver。
- 仍保持事件级 split；test 不参与调参。

**D. 全量（约 2,640 条有 subject 的记录）**

- 只有 C 证明“扩产标签对下游有增益”才做。
- 如果字段正例率不升、M4/特征对照没有增益，停在 C；不要为了“跑完”而跑完。

### 10.3 每级的硬门

进入下一级前必须拿到：

1. **输入门**：S1/S3 通过、target 可见、无 answer leakage、facts/meta 来源合法。
2. **证据门**：逐字合法率 ≥95%，坐标/句 ID 可回原文；失败件有诊断，不静默丢。
3. **字段门**：逐字段正例数、未提及率、与 203 silver 的差异分类；`times` 等稀疏字段不因总量增加就假装可训。
4. **仲裁门**：A/B/C 完整；C 不与 B 同模型；分歧/无效有分类，不是只看“跑完”。
5. **绑定门**：至少抽样报告 shared/target/needs_review 的主体错误；不要求一次全对，但不能没有审计。
6. **成本门**：每条 accepted label 的成本、失败重试成本、unknown 比例。
7. **下游门**：把新 silver 交给引擎侧做要素特征对照；若没有超过 B4/多数类，停止扩产，先修字段/输入。

### 10.4 第一批具体动作

1. 建 `expansion-300` 候选清单：从 3,196 条中排除 328 池/203 已标，按渠道×facts 长度×正例线索分层抽 300。
2. 只对这批跑 S1/S3；不要先动全量。
3. 导出教师输入，统计 eligible/quarantine；若 eligible <120，先查 S1/S3/party，不要直接加 L5 调用。
4. 用 L5 full 模式跑 120–200 条，新目录、新 manifest；不重跑 203。
5. 产出 `element-supply-pilot-v1` 包：labels + evidence + binding + manifest + 字段支持报告。
6. 把包交给引擎侧做消费对照；数据侧不训练模型。

### 10.5 当前不应做的事

- 不把 203 重跑当扩产；不把 328 池当全量；不把 534 候选当已可用。
- 不在 S1 facts 7/50 缺陷未修、parsed `not_executed` 未重跑时直接放大到 2,640。
- 不因为 L5 full 模式解除了小批上限，就跳过输入门和字段门。
- 不在 test 40 上做扩产调参；不把模型一致率当字段准确率。
