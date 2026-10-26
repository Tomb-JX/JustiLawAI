# 数据链路现状（2026-10-26 核对版）

> 核对方式：逐项读取外置数据目录 `D:/02_Dev/Data/justilaw-research/`（lake catalog SQLite、REGISTRY.csv、delivery、unified_raw_refresh、s1_runs、coordination 看板）、main 与各 codex 分支的 git 记录、法宝作战手册 §11–§18。**所有数字为 2026-10-26 实测或引自当日协调看板**（`$DATA/coordination/CURRENT.md`，自动生成于 10-26 16:07，事件源 events.jsonl 163 条）。
> 本文取代 2026-10-16 版《数据链路阶段总结》（旧版全文见 git 历史，提交 aab696b 之前）；旧版数字全部失效，对照清单见 §9。
> 范围：数据处理链路（L0–L5 与 S0–S4）。引擎模块（M0–M6）状态见协调分支 `PROJECT-PANORAMA-STATUS-2026-10-22.md`，本文只在"消费侧"一节引用其结论。
> 配套：[数据链路全景 data-flow.md](../05-research/data-flow.md)（v0.2 状态刷新）· [法宝作战手册](./pkulaw-playbook.md) §11–§18 · [数据交付规格](../05-research/data-spec.md) · [协作记录](./collab-log.md)

## 0. 一页结论

1. **重心已全面转向法宝端文书（用户裁定，2026-10-26）**：北大法宝行政执法库是当前唯一在产的采集来源（P1–P7 批，10-18 至 10-22）；**公开网页链路（discover/harvest/parse）停止维护**——不再新增采集、不再修复解析缺口，存量网页数据继续在统一层与 L5 管线流转（见 §1）。
2. **数据湖已建成并成为唯一底账**：`lake/catalog/lake.db` 现有 **8,436 条记录 / 7,682 份文书 / 12 个批次**（法宝 11 批 4,159 条 + 网页 1 批 5,037 条，跨批去重后 8,436）。文档里旧的"881 件交付 / 890 条首批"等数字全部过时。
3. **交付版本已走到 r6，r7 被质量门挡下**：`delivery/LATEST` → `2026-10-17.r6`（主文件 1,695 件 / 785 事件，仅结果 576 件）。r7 因 S3 校验硬失败率 25/299=8.36%（门禁 <5%）未放行；且 **r6 的输入还停在 web-r2 + pkulaw merged-b2，P1–P7 新批尚未进入任何交付版本**。
4. **L5 要素标签链路（unify，S0–S4）是当前主战场，产出了四批 training-only 银标**：203 参照银标、909 模型银标、expansion-1000 的 454 条标签、706b 湖文本批（567/706 完成）；10-26 现行开发银标为质量闸 v3 的 **345 条**（lake-text-v3-345）。**金标仍为 0**。
5. **要素密度的决定性结论已坐实**（P3–P7 实验，playbook §15–§16）：年龄/前科/抽头**买不到**（词元碰撞）；唯一可富集的是现场赌资——定向批 onsite_stake 落事实段 **78.5%**（法宝 L1 基线 48.0%），P6+P7 后全库升至 **53.6%**。
6. **binding（本人归属绑定）v1.1 已冻结但只许影子推理**：H3 171 条影子审计全通过、工程缺陷已修，但复核仍有语义错（个人赌资 1/4、现场总额 1/7），且 H3 是开发复用集——**不得进入训练或在线裁量**（BIND-SVC-QA-01）。
7. **消费侧（M4 开发试验）的现状是"纯文本最强、要素无增益"**：合并 203+909 的 168 条验证上，文本 107 / 融合 106 / 要素 86 / 多数类 61。这是当前要素密度的直接后果，不是要素路线的终局判定（样本量 underpowered）。

## 1. 重心裁定：法宝主线，网页线停止维护（2026-10-26）

| 项 | 裁定内容 |
|---|---|
| 法宝线（主线） | 行政执法库定向采集（P 系列批）+ Word 补救下载 + L2 解析质量修复继续推进；P8 与 Word 复核队列（playbook §17）待机构下载权限解锁 |
| 网页线（停止维护） | `discover/`（千帆发现）、`harvest/`（收割/OCR/parse/build）不再新增采集、不再修复解析缺口；计划任务 `JustiLaw-Discover-Weekly` 应停用（待运维确认） |
| 存量网页数据 | 继续保留并流转：web-r4 批 5,037 条已入湖；unified 层 A 级 3,728 条中 web 占 2,225；expansion-1000 标签批中 web 595 条。既有的 web 缺口（`text_party=0`、`no_subject` 486 条，即 I-22/I-24）**不再修复**，按管线既有规则隔离/单列处理 |
| 影响 | S1 输入 3,196 条中 party 可用的 2,460（web 772 / pkulaw 1,688）维持现状；后续增量全部来自法宝端 |

## 2. 管线分层全景：现状与代码位置

```
L0 原始        inbox/pkulaw、raw/、harvest/（网页存量）          —— 法宝线继续，网页线封存
L1 parsed-1    parsed/pkulaw/<批次>/records.jsonl（41 批在册）    collect/pkulaw_ingest.py（main，PARSER@0.4）
数据湖          lake/{blobs,catalog,ops,parsed}                   research/discretion/lake/（main，T-L1）
               → lake.db：8,436 records / 7,682 docs / 12 batches
统一中间层      unified_raw + unified_raw_refresh/20261018         unify/*（codex 分支，未合 main）
               → 41 批 26,185 条（唯一 id 7,333）→ canonical A 级 3,728
S0–S4 / L5     s1_runs/、parsed2/、labels                          unify/{cleanse,s1,run_seg,run_elements,s3,
               → S1 输入 3,196/1,790 事件；四批银标（§6）            element_contract,field_table,binding_*}.py
L3 交付        delivery/{r2…r6}，LATEST=r6                         harvest/build.py（main，harvest-0.6）
L4 验收        engine/acceptance/、S3 门                           research/eval/accept_delivery.py（main）
协调看板        $DATA/coordination/{CURRENT.md,events.jsonl}       coord_event.py（data-coordination 分支）
```

**代码位置注意（2026-10-26 更新）**：L5 管线 `research/discretion/unify/`（含 S1 分区、要素契约、金额硬闸、field_table、binding）此前只在 codex 分支、main 缺失。**2026-10-26 已将 engine / coordination / binding-fix / l5-quality 四支并入 main**（两个 L5 血统的 5 个 unify 冲突文件手工合并，保留 binding v1.1 + VIEW-01/金额硬闸修复 + field_table；排除 gate-reports 机器产物 ~11 万行）。合并后集成缺口 `normalize_date_range`/`normalize_count`（binding-fix 调用但 E-05 从未实现）已补全，run_elements binding 审计兼容缺 supply_packet 的输入。**main 现可复现 L5 管线**：collect 67 / eval 83(+1 skip sklearn) / unify 286 测试全绿（需设 `JUSTILAW_ENGINE_API` 指向 justilaw-api）。

## 3. 数据湖与批次账（lake.db，2026-10-26 实测）

| 批次 | 来源 | 条数 | 入湖时间 | 说明 |
|---|---|---:|---|---|
| merged-20261017-full | 法宝 | 890 | 10-18 | 首批双写（T-L1） |
| 20261016-2026T作业台-b4-r2 | 法宝 | 2 | 10-18 | 跨批去重验证批 |
| 20261018-P1-r6 | 法宝 | 183 | 10-18 | 要素导向首批（12 次检索） |
| 20261018-P1b-r2 | 法宝 | 115 | 10-18 | 要素导向补充 |
| 20261018-P2-r1 | 法宝 | 1,746 | 10-18 | 常规批；**异常：761 条重复权限页（I-22）** |
| 20261018-P2-L4word | 法宝 | 317 | 10-18 | L4 Word 补救下载（转 L1 率 99.1%，314 条 L1） |
| 20261018-web-r4-table-repair | 网页 | 5,037 | 10-20 | **网页线最后一批**（表格续行修复重建） |
| 20261021-P3-r1 | 法宝 | 69 | 10-21 | 密度可购性实验批 |
| 20261021-P4-r1 | 法宝 | 78 | 10-21 | 同上 |
| 20261021-P5-r1 | 法宝 | 116 | 10-21 | 同上（大样本定论批） |
| 20261021-P6-r1 | 法宝 | 327 | 10-22 | 现场赌资定向（变体锚破 20 上限） |
| 20261021-P7-r1 | 法宝 | 316 | 10-22 | 现场赌资再补（净新增 284 条 L1） |
| **合计（去重后）** | | **8,436 records / 7,682 docs** | | artifacts 8,239；lineage 36 |

- REGISTRY.csv 共 188 行数据，最后一批登记为 P7（10-22）；10-25 的离线修复（canonical 12 条 + 源批 13 条，`ops/subject-mention-repair-20261025.jsonl`）未新增台账行。
- 湖外派生（不属六层）：`engine/`（M1 探针、binding 审计、L5 金丝雀）、`serving/`（binding-v1 / v1.1 冻结产物）、`labels/`、`s1_runs/`、`parsed2/`。

## 4. 统一中间层与 S1 输入（unified_raw_refresh/20261018，看板 10-18 实测）

| 层 | 数字 | 备注 |
|---|---:|---|
| 全量转换 | 41 批 / 26,185 条 | format_ok 24,439；content_ready 22,659 |
| 唯一 id | 7,333 | **不能把 26k 当独立事件**（同文书多批转换） |
| canonical released+content（A 级） | 3,728 | web 2,225 / pkulaw 1,503；released+facts 3,557 |
| S1 输入（label-ready，去重） | 3,196 条 / 1,790 事件 | split 2,202/495/499（train/valid/test 记录级）；事件级划分 |
| party 可用 | 2,460 / 3,196 | web 772 / pkulaw 1,688；规则恢复 2,691（句 2,041/表 650），非人工审核 |
| no_subject 单列 | 558 | web 486 / P2-r1 62 / P1b 7 / P1 3；**不进教师、不进 label-ready**（I-24） |

r7 取样框 2,918 条（A 级扣除隔离项）。

## 5. 交付版本序列（L3/L4）

| 版本 | 主文件 | 仅结果 | 管线 | 状态 |
|---|---:|---:|---|---|
| 2026-10-16.r1 | 1,387 | 799 | harvest-0.5 | **已作废删除**（21 件脱敏漏网） |
| 2026-10-16.r2 | — | — | harvest-0.5 | 已取代（曾为 LATEST） |
| 2026-10-16.r3 | 1,403 | 814 | harvest-0.4 | 已取代 |
| 2026-10-16.r4 | 1,404 | 813 | harvest-0.5 | 已取代 |
| 2026-10-16.r5 | 1,447 | 820 | harvest-0.5 | 已取代 |
| **2026-10-17.r6** | **1,695（785 事件）** | **576** | harvest-0.6 | **现行 LATEST** |
| 2026-10-?.r7 | 取样框 2,918 | — | — | **未放行**：S3 硬失败 25/299=8.36% > 门禁 5% |

r6 口径要点：输入为 web-r2（4,939→范围内 1,778）+ pkulaw merged-b2（738→735），in_scope 2,513；按 D-003（2026-10-17 规范修订案）**主管线零遮蔽**、`doc_no_plaintext=true`，r6_scan/deid_map 转外发衍生工具；省份前三：江苏 595 / 河北 375 / 广西 357。**P1–P7 的法宝新批（约 3,267 条入湖）尚未进入任何交付版本**——r7 放行依赖 S3 修复与 I-22 清理。

## 6. L5 标签产出与质量（全部 training-only 银标；金标 = 0）

| 批次 | 规模 | 划分 | 质量状态 |
|---|---|---|---|
| ALL-203 参照银标 | 203 条 / 135 事件；1,226 非空字段（79 字段降级"未提及"） | train 140 / valid 23 / **test 40 封存** | `release_approved=true` 只限银标训练；gold=false；G2.2 正式发布未过 |
| 909 模型银标（timesfix） | 909 条 / 726 事件；784 单模型 + 125 三模型降级 | train 763 / valid 146 | 909/909 过 schema；**未修**：587 段/219 条证据坐标无法回投（M1 located 训练不就绪）、57 复议污染、26 前科待审、199 公示应转 outcome-only |
| expansion-1000（10-21） | 1,000 候选/797 事件 → S1 994 → 教师输入 454 accepted / 540 隔离 → **454 条标签**（三模型 125 + 单模型 329） | train 377 / valid 77 / test 0；与 203 事件零重叠 | 结构 454/454、证据引文 99.93% 逐字一致、泄漏词 0；**字段分布与 203 显著偏离，内容质量未证**；单模型 329 条须重投影 text_full 才可入 reference_elements。S1 实付约 ¥29.5，混 provider（deepseek-flash 607 / xiaomi-pro 291 / xiaomi-flash 96），下游对拍注意漂移 |
| 706b 湖文本批 | 706 条（train 561 / valid 145），qwen3.8 | — | full **567/706 incomplete**（139 missing：113 Arrearage + 9 outcome 数值 + 4 timeout + 4 clause ID + 3 budget + 6 无诊断），¥10.618 |
| personbind-349 → **lake-text-v3-345（现行开发银标）** | 345 条 | train 275 / 141 事件；valid 70 / 28 事件 | 质量闸 v3 替代 personbind-349；剔除缺半原文及无答案锚点 4 条；非金标 |

**10-26 当日 L5 线进展**（看板 + c3343ec）：
- L5 单模型法宝 train 金丝雀 30 条：26 条证据/数值有效、4 条金额拒收、9 条本人字段归属待判；**剩余 115 条暂缓付费扩产**。
- 目标可见性审计纠偏：127 条不是源数据坏——103 条允许视图已有掩码等价姓名、19 条可补前置 span、5 条仅 decision 区需隔离路由。
- DeepSeek 混合小批 20 条：13 条硬闸通过（其中标题泄漏 7、本人归属待判 8），6 条数值失败；离线 5 条草稿——**均未入训练**。
- 质量规则修复（c3343ec，230 测试全绿）：VIEW-01 person_block 起点收窄（标题+文号强制剥离，冻结记录 4/4）；金额硬闸短语级（"X至Y元"区间、"最低下注"近邻开口、多句 direct 对账 all→any；6 例冻结重放 3 抢救/3 拒收，引擎已验收）。

**binding（本人归属绑定）**：v1.1 冻结于 `$DATA/serving/binding-v1.1-47bffae`（同额不同人→relation_ambiguous、结构化 {min,max} 金额、实现/视图哈希绑定、人数双引文）；H3 171 条影子审计 0 结构/坐标错，自动绑定个人赌资 17 / 现场总额 19 / 人数 6 / 年龄 10；**但 H3 复核 bound 仍有语义错（个人赌资 1/4、现场总额 1/7），H3 为开发复用集**——BIND-SVC-QA-01：只许影子推理，需全新来源批次独立字段级复核后逐字段放行。

## 7. 要素密度实测（供给决定训练上限）

| 要素 | 密度结论 | 数字 |
|---|---|---:|
| 现场赌资 onsite_stake | **唯一确认可富集**（P6/P7 定向，变体锚族破 MCP 单格 20 条上限） | 法宝 L1 基线 48.0% → 定向批 78.5%（P6）/58.5%（P7）→ **全库 53.6%**（lake 8,436，10-22） |
| 个人赌资 personal_stake | 定向批顺带抬升 | P6 批 61.6%（基线约 44%） |
| 年龄 / 前科 / 抽头 | **买不到**（P3–P5 证伪：词元碰撞，带锚含赌 0%→100% 但目标要素不随） | playbook §15；密度缺口转抽取侧（I-20） |
| 参赌人数 / 行为类型 / 赌博方式 | 常规可得（历史基线：方式 96%、人数 30%、行为类型 28%，99 件 L1 实测，data-requirements v0.2） | — |
| 源端天花板 | smoke12 复查：77.8%"未提及"以原料稀疏为主（facts 中位 72.5 字；年龄多因出生日期打码不可得） | 看板 10-18 |

## 8. 未闭环阻塞与挂账（看板 10-26，只列数据线相关）

| ID | 内容 | 状态 |
|---|---|---|
| I-22 | P2-r1 761 条重复权限页（duplicate_ids=760，format_ok=false）；web-r4/P2-L4word `text_party=0` | open；**网页部分随停维不再修**，P2-r1 清理仍待做 |
| I-24 | S1 输入 no_subject 558（web 486 为主） | open；已单列不进教师；网页部分随停维按弃权处理 |
| BIND-03 / BIND-05 | 绑定质量未证（money shared=0、大量 review）；方法违规（全程 regex，B-08 要求 NLP/混合） | open；规则版语义归属已冻结，归属改教师抽取+模型化（B-10） |
| CONTRACT-01 | binding_policy 仍 proposed_pending_engine_adoption | open；等引擎采纳契约 |
| L5-VIEW-01 | person_block 带入处罚决定书标题 | **已修复**（c3343ec，引擎 ack 10-26 15:28），待看板关闭 |
| BIND-SVC-QA-01 | binding v1.1 语义错残余，H3 非独立集 | open；影子模式，全新批次独立复核 |
| r7 放行 | S3 8.36% > 5% | blocked；下一步：L5 教师批、边界人工评测、S1 句内 span 与表格行修复 |
| 代码归并 | ~~unify/ 全链路只在 codex 分支，main 无法复现 L5 管线~~ **已完成（2026-10-26）**：engine/coordination/binding-fix/l5-quality 四支并入 main，5 个 unify 冲突手工合并保留双方逻辑，gate-reports 机器产物排除入库（.gitignore），E-05 缺口 normalize_date_range/normalize_count 补全，三套测试全绿 | ✅ 关闭 |
| Word 复核队列 | 法条名残缺 6 条（源侧缺陷，重建=治安管理处罚法第 70 条）待 Word 原件签字；与 P8 合并跑 | 挂账（playbook §17）；机构下载权限未生效 |

## 9. 旧版（10-16）过时点对照——引用旧文档时先看这张表

| 旧说法（10-16 版本文档） | 2026-10-26 实况 |
|---|---|
| "首批交付 881 件 / 678 件仅结果" | 已作废重建多次；现行 r6 = 1,695 / 576 |
| "数据湖是设计方案（data-lake-design v0.1）" | T-L1 已落地运行，8,436 条 / 12 批 |
| "网页链路是主力，脱敏/去重/区划只在网页线实现" | 网页线停止维护；法宝线是主力；统一构建走 harvest-0.6 + unified 层 |
| "法宝 0 入库 / MCP 刚接通" | 法宝 11 批 4,159 条入湖，P1–P7 定向采集方法论已定论 |
| "金标候选 881 件，试标未开始" | 银标链路已产四批（203/909/454/345），金标仍为 0，试标口径已被 union-κ 裁定取代 |
| "信息完整度 40%/25%，要求 ≥80%" | 口径已细化：A 级 canonical 3,728、S1 label-ready 3,196/1,790 事件；完整度问题转化为要素密度问题（§7） |
| "三套解析器格式不一致（quality/completeness 等四处）" | parsed-1 统一中间格式 + unified 层已解决；data-flow.md §4 的四处不一致为历史记录 |
| "onsite/密度数字以 99 件 L1 实测为准" | 以 lake 全库 8,436 与 P6/P7 大样本为准（onsite 53.6%） |

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-26 | v2.1 | 四支（engine/coordination/binding-fix/l5-quality）并入 main：§2 代码位置注记更新为"main 可复现 L5 管线"、§8 代码归并项关闭；记录 5 个 unify 冲突手工合并、gate-reports ~11 万行排除入库、E-05 缺口 normalize_date_range/normalize_count 补全、collect 67/eval 83/unify 286 测试全绿 | 宏观指引会话（用户指示） |
| 2026-10-26 | v2 | 全文重写为 2026-10-26 核对版：数据湖/统一层/交付序列/L5 银标四批/密度定论/binding v1.1/阻塞清单/旧版过时点对照；登记重心裁定（法宝主线、网页线停维）。取代 10-16 v1.1 | 宏观指引会话（用户指示） |
| 2026-10-16 | v1.1 | （历史）阶段总结 + 晚间交付更新 | 模型组 |
| 2026-10-16 | v1 | （历史）初版核对 | 模型组 |
