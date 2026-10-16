# 数据链路全景（as-built）：各来源 → 规范数据

> 版本 v0.1 · 2026-10-16 · 模型组
> 与[行政案例数据交付规格](./data-spec.md)（**契约**：要什么字段、什么质量）配对阅读。
> 本文回答另外三个问题：**现在有哪些来源、各自用什么代码解析、产出的规范数据长什么样、还差什么才算可交付**。
> 结论以代码与外置数据目录的实测为准（2026-10-16 逐项核对）；未验证的写"待办"，不写"预计"。

## 1. 全景

```
来源                          采集/解析代码                                产物（$JUSTILAW_DATA_DIR/）                    分级
① 公开网页（县级政府公示、    discover/*（计划·检索·分诊·栏目）→               admin/web_cases.pre_deid.jsonl                 in_scope / gambling
   复议专栏）                 harvest/*（收割·OCR）→ harvest/parse.py          （3,693 条，在范围内 1,036）                    + completeness
② 法宝行政执法库（公安        collect/pkulaw_ingest.py docs                      parsed/pkulaw/<批次>/records.jsonl（L1 正本，   **tier L1–L4**
   行政处罚决定书）           （parsed1 产统一中间格式；legacy 在 ingest/）      parsed-1 → 九组字段；ingest/<批次>/ 为工作副本
                                                                               ingest/<批次>/admin_needs_review.jsonl（L4）
                                                                               ingest/<批次>/pkulaw_out_of_scope.jsonl（L3）
③ 法宝司法案例库（法院判决）   collect/pkulaw_ingest.py cases（MCP 记录）        cases/<批次>/pkulaw_cases.pre_deid.jsonl（行政）  tier（判决书形态）
                             + docs（网页批量导出的 .doc，parse_judgment_doc） cases/<批次>/pkulaw_crim.pre_deid.jsonl（刑事）
④ 第三方采购裁判文书          collect/ingest_wenshu.py（清洗去重入库）          wenshu/imported/<批次>/wenshu.jsonl              **暂存，未分段**
⑤ 公开数据集                  collect/fetch_cail.py / fetch_lecard.py          cail/（赌博子集四 split）、lecard/
                             ↓
                     ⑥ L2 统一构建（harvest/build.py：脱敏+R6+区划+去重+事件分组）
                        —— 2026-10-16 起支持 `--parsed` 接入 parsed-1 来源；产物按版本发布 `delivery/<版本>/` + LATEST
                             ↓
                     ⑦ 交付引擎：admin_cases.schema-1.0.0.jsonl（data-spec v0.1）  ← **尚未产出过任何一批**
```

**一句话现状**：①②③ 三条来源的**解析链路已跑通并实测**（含真样本验证），④ 只到"清洗暂存"，⑥⑦ 一步都没到——**金标目前是 0**，卡在脱敏（+D1–D5）与标注流程，不卡在解析。

## 2. 各来源的解析链路（实测要点）

### ① 公开网页（发现层负责，纪律：只收有出处的材料）

- 链路：千帆搜索 API → `triage.py` 分诊 → `harvest.py` 收割（含扫描件 `ocr.py`）→ `parse.py` 解析。
- **五种页面形态**：叙述式处罚决定书（441 件，含"现查明"）/ 字段式公示（144）/ 汇总页拆分（377，红塔式，只有"因赌博"）/ 复议决定书（73）/ 结果表（1）。
- 产出字段贴近 data-spec：`text_facts/text_evidence/text_reasoning/text_decision/text_review` + `outcome` + `review` + `completeness{has_amount,has_outcome}` + `deidentified:false`。
- 已知坑：汇总页信息贫乏（377 件里 0 件信息完整）；扫描件落款被公章压住 → `decision_date` 缺失；管辖条款/前科/权责清单会误判赌博（`triage.py` 已加规则）。
- **在范围内 1,036 件，信息完整 263 件（25%）**；河北 81、新疆 38 集中。

### ② 法宝行政执法库（本次新建，数据链路目录）

- **三种落位**（分省不同，已实测）：叙述式独立成篇（江苏/浙江/河北/湖南/山东/湖北…）/ 正文塞在决定表"处罚结果"栏（浙江嵊泗、湖北咸丰式）/ 只有摘要字段（上海、南昌式）。
- 解析要点：`flatten()` 拍平后才能正则（表格换行会把词拆进不同单元格、填充空格会撑爆长度窗口）；`table_cells()` 合并跨格续行；罚款支持"圆"（壹仟圆整）；复合刑期"一年四个月"=16 个月；**结果优先取"决定"段**（结果栏是长文时会先命中前科里的旧拘留天数）；"不送拘留所执行"写入 `detention_not_executed`；裸条号"第十一条、第八十二条"按上下文补法律名并定新法。
- 分级（`tier`）：L1 金标候选（有事实+结果）/ L2 结果-only / L3 范围外（非赌博、民事）/ L4 待核；四路各自落盘。
- 实测批次：A 批（正文=`现场查获赌资`）**含金额 98%**、事件折算率 33%；B 批（常规检索）含金额 54%、事件折算率 64%。

### ③ 法宝司法案例库（法院判决，学院账号长期权限）

- **两条入口**：MCP `case-keyword`（返回 29 字段、**已按语义分段**：`Ascertain` 经审理查明 / `Identified` 本院认为 / `RefereeResult` 判决结果 / `RefereeBasis` 裁判依据，但正文是节选）；网页批量导出 `.doc`（结构化头 + 独占一行的小节标题：当事人/审理经过/检察院指控｜本院查明/被告辩称/本院认为/裁判结果/落款，**信息量更大**）。
- 解析要点：小节按**独占一行**识别（拍平后正文里的"提及"会冒充标题，实测事实段只抽到 4 字）；`RefereeBasis` 混着法院程序条文 → 处罚依据优先取事实段"根据《…》第X条…作出处罚决定"；判决书**含真名**（律师、法官也有）。
- 分流：刑事判决出 `criminal{主刑,月数,缓刑,罚金}`；民事判决标 `in_scope:false` 单独存放（实测 3/7 = 43% 噪声，与目录表一致）。
- 覆盖实测：行政一审 4,986 / 二审 6,604；**2026 年审结仅 12 份** → T-time 不能靠它。

### ④ 第三方采购裁判文书（数据链路负责）

- 现状：`ingest_wenshu.py` 只做**清洗与入库暂存**——替代主键（案号+文书类型+裁判日期+正文 SHA-1）、省份自案号推导、**当事人列入库即丢弃**，产物是 `{primary_key, case_no, court, cause, procedure, case_type, publish_date, judgment_date, province, doc_type, text_full, segmented:false, ...}`。
- **缺口**：到货后没有"分段 + 结果抽取"这一步（`text_full` 是一整段），也没接 data-spec 的 `outcome/review`。要做时需要把③的判决书解析思路移植过来（版面不同，需一份到货样本）。
- 合规：下单前需指导老师确认来源合规；本链路当前**未下单**。

### ⑤ 公开数据集（已完成）

- CAIL2018 赌博子集四 split（2,468/293/558/841，已修 JSONL 换行并附 SHA256SUMS）；LeCaRDv2 查询与标注就位。引擎侧 A2 锚点已用 CAIL 跑完基线。

## 3. 规范字段映射矩阵（哪个来源能填哪些字段）

| data-spec 字段 | ① 公开网页 | ② 法宝执法库 | ③ 法院判决 | ④ 采购 |
|---|---|---|---|---|
| `id`（台账） | ✅ W-xxxx | ⚠️ 等 `import_manual.py` 分配 | ⚠️ 同左 | ✅ 走 manifest channel=C |
| `source_type` | ✅ 处罚决定书/执法公示/复议决定书 | ✅ 处罚决定书/执法公示 | ✅ 行政/刑事判决书 | ✅ 判决书 |
| `behavior_date` | ⚠️ 888/1036 有（扫描件缺） | ✅ 事实段首个日期（实测可提） | ✅ 行为日期在事实段 | ⚠️ 需从正文抽 |
| `decision_date` | ⚠️ 536/1036（扫描件落款被压） | ✅（"同日作出"回溯 + 落款兜底） | ✅ 审结日期；原处罚日另有 | ⚠️ 裁判日期有，处罚日需抽 |
| `authority` / `region` | ⚠️ 机关多数有；**region 待做**（regions.py WIP） | ✅ 处罚机关 + 执法地域 | ✅ 审理法院 + 案号推省 | ✅ 法院 + 案号推省 |
| `text_facts` | ✅ 切分 823/1036 | ✅ 叙述式两种落位 | ✅ 本院查明/指控 | ❌ 未分段 |
| `text_evidence` / `text_reasoning` | ⚠️ 叙述式才有 | ✅ 证据段；裁量说明通常无 | ⚠️ 证据散在事实段 | ❌ |
| `text_decision` | ✅ | ✅ 决定段 | ✅ 裁判结果 | ❌ |
| `text_review` | ✅ 复议 61 件 | ❌（执法公示无审查意见） | ✅ 本院认为 | ❌ |
| `outcome.*` | ✅ 948/1036 结果解析 | ✅ 类型/拘留日/罚款/不执行/法条/版本 | ✅ 原处罚复述 + `review.result` | ❌ |
| `review.result` | ✅ 复议结论 | ⚠️ 记"无" | ✅ 驳回=维持/撤销/变更/确认违法 | ⚠️ 判决书结论可抽 |
| 信息完整度（有金额+结果） | 263/1,036（25%） | **98%**（A 口径批次） | 刑事带罚金；行政待测 | 待测 |
| 事件分组 | ⚠️ 有 page_id/site，未做事件键 | ✅ `event_key`（机关+事实首日期+赌资金额） | ✅ `event_key`（同左） | ⚠️ 要按"处罚机关+违法行为日期"分组（wenshu v0.2 已写明） |

## 4. 对接约定（当前**不一致**的四处，交付前必须统一）

| # | 问题 | 现状 | 建议统一到 |
|---|---|---|---|
| 1 | 质量字段形状 | 法宝用 `quality{tier,form,has_amount,has_outcome,outcome_only,parse_warnings,law_version_raw}`；发现层仍用**顶层** `completeness` + `parse_warnings` + `ocr` | `quality` 一个对象（[文本处理规范](../04-plan/text-processing-spec.md) §2 已建议），发现层迁移 |
| 2 | 内部字段混进交付 | 发现层产物带 `page_id/site/publisher/title/gambling/in_scope`；法宝带 `event_hint/pkulaw_id` | 交付前把内部字段移入 `quality` 或删除（规格 §2 已列） |
| 3 | `region` 缺失 | 法宝有；发现层没有（行政区划映射 WIP） | 先按省级字符串填，符合规格"至少到省" |
| 4 | `event_key` 缺失 | 法宝有；发现层无 | 发现层用"发布单位 + 事实段首个日期 + 金额"生成同构键，供门禁 §7 分组划分 |

**统一后的交付接口（引擎读取的唯一形状）**：
`id, source_type, source_ref, harvest_date, deidentified, behavior_date, decision_date, authority, region, text_full, segmented, text_facts, text_evidence, text_reasoning, text_decision, text_review, outcome{type,detention_days,fine,detention_not_executed,confiscation,articles,law_version,stated_circumstances}, review{result,changed_outcome}, quality{tier,in_scope,has_amount,has_outcome,outcome_only,parse_warnings}, event_key`

## 5. 缺口清单（按阻断程度排序）

| # | 缺口 | 状态 | 责任 |
|---|---|---|---|
| 1 | **脱敏 SOP + R6 扫描** | `deid.py`/`regions.py` 仍在发现层工作树（未入库）；D1–D5 未拍板 | 发现层实现、数据链路复核、引擎+法律组拍板 D1–D5 |
| 2 | **金标流程未启动**（教师银标 → 主动学习 → 人工校正） | 未开始；教师模型 B1 未选定；试标 50 件未做 | 引擎（B1）+ 法律组 + 数据链路 |
| 3 | 交付文件名与格式 | 未产出过 `admin_cases.schema-*.jsonl` | 数据链路（按 §4 统一形状） |
| 4 | 采购到货的分段与结果抽取 | 只到清洗暂存 | 数据链路（可复用③的判决书解析） |
| 5 | T-admin 划分与封存（门禁 §7） | 未开始（需 ≥150 件、复议/诉讼 ≤50%） | 引擎 + 保管人 |
| 6 | 引擎侧数据读取与自动验收（规格 §4） | 未实现（`metrics.py` 只是指标） | 引擎 |

## 6. 状态表（每条链路验证到什么程度）

| 链路 | 解析已实测 | 产物已落盘 | 已脱敏 | 可交引擎 |
|---|---|---|---|---|
| ① 公开网页 | ✅（80 项测试 + 三次抽查） | ✅ 3,693 条 | ❌ | ❌ |
| ② 法宝执法库 | ✅（三种落位 + 50+50 篇实测） | ✅（四路分流） | ❌（**未遮挡省份含真名**） | ❌ |
| ③ 法宝判决书 | ✅（7 份刑事判决 + 行政 125 件） | ✅ | ❌（含真名） | ❌ |
| ④ 采购 | ⚠️ 清洗逻辑有合成样例自测 | ⚠️ 无到货 | ❌ | ❌ |
| ⑤ 数据集 | ✅ | ✅ | — | ✅（CAIL 已用于 A2 基线） |

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-16 | v0.1 | 初版：四条来源链路 as-built、规范字段映射矩阵、对接不一致的四处与统一接口、缺口清单与状态表 | 模型组 |
