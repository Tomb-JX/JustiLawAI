# 解析层格式链路设计 v1.0（供多轮审核）

> 2026-10-17。定位：把《解析工程设计 v2.1》的管线落到**逐字段的数据契约**——每个环节记录：信息是什么、数据格式、字段表、产生层、实测填充率、设计理由。供用户分节审核，预计多轮提问完善；每轮修订在 §17 登记版本。
> 上游文档：[解析工程设计 v2.1](./parse-engineering-design-v2-2026-10-17.md)（架构理由）、[网页×法宝原料对比实测](./parse-input-comparison-2026-10-17.md)（两源落差实测）。
> 实测口径：三个实测脚本跑 parsed-1 两源全量（web-r3 5,001 / pkulaw merged-b2 738），L1/L2 原料口径 = web 1,722 + pkulaw 729 = 2,451 件；聚合统计、零原文输出；event_key 公式经两份生成代码核对。

## 1. 全链路总图（格式视角）

```
L0 原始+台账 ──── 两源各自稳定收割；台账（仓库外）持 id/URL/文号/引证码/harvest_date
  │
  ├─ 渠道特定解析【已存在，冻结降权】
  │     web:    HTML→压平文本 + 样板/字段粗抽 + regex 分段（降为对照参考）
  │     pkulaw: Word→文本 + 字段抽取 + 段文本（降为对照参考）
  │     产出：渠道原生 JSON（内部格式，仅要求"text + 源标记"可映射到统一原料）
  │
  ├─ S0 统一规范化【半新：补公示词表/管道表/逗号续行组件】
  │     产出：cleaned_text + offset_map（管线内）+ form 真值
  │
  ├─ 预筛【已有 regex，保留】：gambling 三态 + in_scope → 决定谁进模型（2,451 件）
  │
  ├─ 模型语义批注【新】：输入=统一原料+提示 → 输出=引文+要素 JSON
  │
  ├─ S2 定位【新】：quote→cleaned 坐标→offset_map→原文坐标
  ├─ S3 校验【半新：parse_qc 15 项迁移+罚幅对账】：硬失败→换模型重试→低置信队列
  │
  ├─ 语料组装【已有 build.py 改造】：去重 / 事件键统一重算 / linked_ids / region / tier 重分级 / law_version 定版
  │
  └─ 统一产物 parsed-2（=原料字段+模型字段+组装字段）→ 交付 rN（原文正本）→ 自动验收
        parsed-2 三用：标注集（蒸馏标签）＋裁量模型特征/标签源＋实证分析对象
```

格式存亡总表：

| 格式 | 处置 |
|---|---|
| 台账 | 保留不动（唯一溯源源） |
| 渠道原生 JSON | 保留，冻结为"文本+源标记"抽取器；语义产出降为对照参考 |
| 统一原料契约 | **新**（薄） |
| offset_map | 管线内部传递，**不落盘、不进契约** |
| parsed-1（现行） | 拆解：原料字段并入统一原料；分段字段由模型产出；现行文件保留为对照参考集 |
| parsed-2 | **新**（parsed-1 的后段+模型字段+组装字段） |
| 交付 L3 | 保留，改原文正本（待协调层规范修订） |
| L5 人标层 / deid_map / r6_report / 源端 event_key 公式 | 消亡（见 §14） |

## 2. L0 与台账

| 项 | web | pkulaw |
|---|---|---|
| 原始物 | HTML 页面快照（`raw/web/<批次>/`） | Word/HTML 导出（作业台下载，inbox 归位） |
| 台账 id | `W-`（公开网页）/ `B-`（复议专栏） | `P-`（法宝执法库/案例库） |
| 溯源字段（只存台账） | URL、站点、发布方、页面内条目序号 | 引证码、pkulaw_id |
| harvest_date | 台账记录 | 台账记录 |
| 原始文号 | 台账+记录内；`doc_no_hash` = 规范化文号（去空白、〔〕统一）SHA-256 前 16 位。实测样例形态：`行政处罚决定书定兴公（刑李）行罚决字〔N〕N号 → 3d6085ec19abb1bb` | 同规则，100% 有 |

设计理由：交付文件不写 URL/原文号（D3），溯源一律经台账 id join——这是"统一产物能追回到 L0"的唯一通道，任何环节丢 id 即断链。

## 3. 渠道特定解析（冻结范围与各自产出）

**冻结的含义**：不再往渠道解析里投入新的语义能力（分段/outcome 的权威产出归模型）；只修确定性噪声（§4 词表）。渠道解析的角色收窄为：**文本抽取 + 源标记产出**。

### 3.1 web 渠道

- 输入：HTML 页面 → 压平文本（现有 harvest.py + parse.py）。
- 保留产出（源标记）：`page_id`、`site`、`publisher`、`title`、`item_index`（页内条目序号，1,712 件有——汇总公示页拆条的依据）、`needs_ocr`（12 件）、`attachment_files`、`province_code`/`region_level`（区划映射的中间量）。
- 降为对照参考：regex 分段坐标（L1/L2 100% 有，4,294 段文本 100% 是 text_full 精确子串——已实测可用作分歧对照）、regex outcome（warn 标记 1,129 件未解析）。
- **公示三种子形态**（修正后口径，S0 词表的依据）：
  1. 字段表式：模板词可命中 ~539 件（词表见 §4.2），键值行结构；
  2. 标题汇总式：116 件——短行无冒号（行长度 p50 218 字 / 9 行），结构为"案例标题行（如"张某某等人赌博案"）+ 裸日期行（2023.5.8，含全角点"2023.2．2"、句号"2023.3。2"变体）+ 机关名行 + 短事实 + 短决定（decision p50 69 字）"；一页多条目，靠 `item_index` 拆条；
  3. 混合/弱模板：其余 ~135 件，模板词出现但不成字段表布局。
  （第一轮实测说"251 件档次式"是词表与匹配口径的双重误判：档次词一般/从重等来自其他形态；严格口径重测为零命中公示 116 件，标题汇总式。）

### 3.2 pkulaw 渠道

- 输入：作业台 Word/HTML 导出 → 文本（pkulaw_ingest.py）。
- 保留产出（源标记）：`legacy.pkulaw_id`、`legacy.event_hint`（两源事件线索，738/738）、`quality.form` **真值**（叙述式-独立成篇 666 / 叙述式-结果栏内 35 / 字段式公示 28——L1/L2 口径）、`extra.outcome.detention_items`。
- **重要修正（本轮实测）**：`extra.outcome` 不是顶层 outcome 的冗余双写——键集合完全不同（`detention_items` / `from_execution_clause`），是拘留执行方式明细（合并执行拆项），支撑 `detention_days` 合并计算。应保留，但建议改名 `extra.detention_items` 消除与顶层 outcome 的混淆。
- 降为对照参考：段文本（729 件段文本 2,071 段 100% 精确子串——可逐字定位还原坐标，但坐标本身 0%）。
- 待补的确定性修复（→ S0/组装）：两栏管道表 77 件、逗号尾续行 67 件、authority→region 编码 729 件全缺、tier 拼写归一 28 件。

## 4. S0 统一规范化

### 4.1 机制

- **规则注册表**（有序、可单测、按源分册）：每条规则 = `名称 + 触发模式 + 动作（删除/替换/续接/归一）+ 审计（记录删除 span 与原因进 extra）`。
- **offset_map**：单调数组 `cleaned_pos → orig_pos`，每个保留字符一个映射；纯函数，单测逐字符断言 `cleaned[c] == orig[map[c]]`。只在管线内传递给 S2 定位用，**不落盘**。
- 失败模式防线：删除类规则白名单化（只删命中导航/纯标签字的 span）；删错正文 = 硬校验失败可回溯。

### 4.2 web 册（规则清单）

| 规则 | 触发 | 动作 | 实测面 |
|---|---|---|---|
| 导航样板移除 | "首页>专题专栏"、面包屑残句、"走进X"、发布时间/来源行、【字体】打印关闭 | 删 span | L1/L2 16 件 |
| 字段表归一 | 17 词模板（违法事实/处罚依据/处罚内容/处罚类别/案件名称/决定书文号/罚款金额/执法主体名称/决定书名称/处罚结果/证件类型/证件号/身份证/处罚决定日期/违法嫌疑人/当事人/赌博） | 键值行结构化提示（不删值） | ~539 件 |
| 标题汇总归一 | 短行无冒号 + 标题模式（"××等人赌博案"）+ 裸日期行 | 条目边界标记（进 form 提示） | 116 件 |
| 日期变体归一 | 全角点"2．2"、句号"3。2"混写 | 统一为半角点（改 cleaned 层，原文不动） | 标题汇总式常见 |
| 管道/续行归一 | 单管道行、夹在汉字/数字间的裸换行 | 续接 | L1/L2 罕见（0.1%） |
| 空白/全角归一 | 连续空白、全角空白 | 归一 | 全部 |

### 4.3 pkulaw 册

| 规则 | 触发 | 动作 | 实测面 |
|---|---|---|---|
| 两栏管道表归一 | 行内 ≥2 管道（结构表行，非续行） | 键值行结构化提示 | 77 件（10.6%） |
| 逗号尾续行 | 行尾"，/,"接下一行 | 续接 | 67 件（9.1%） |
| 空白归一 | 同上 | 同上 | 全部 |

### 4.4 与渠道层的归属约定

噪声修复**单点**挂在 S0（注册表按源分册），渠道解析层不再加清理规则——避免两处漂移。pkulaw 册三步的执行线归属待协调指定（单写入方原则）。

## 5. 统一原料契约（unified-raw v1）

**定义**：交给模型的最小完备单元 = 规范化文本 + 形态提示 + 元数据信封。**不是**"一份干净文本"——信封字段是模型提示的形态感知、S3 交叉校验、溯源 join 的必需品。

### 5.1 字段表

| 字段 | 类型 | 必填 | 产生层 | 解释 | 实测填充（L1/L2） |
|---|---|---|---|---|---|
| `id` | str | 是 | 台账 | 溯源 join 键（W-/B-/P-/C-） | 100% |
| `source` | enum | 是 | 渠道 | 公开网页/复议专栏/法宝执法库/法宝案例库/裁判文书采购/合作案卷 | 100% |
| `source_type` | enum | 是 | 渠道 | 处罚决定书/不予处罚决定书/行政复议决定书/行政判决书/执法公示/合作案卷 | 100% |
| `form` | enum | 是 | 渠道+S0 | **形态提示，进模型提示**。枚举见 §5.2 | pkulaw 真值已有；**web 现为 source_type 复制，必须补真值**（§4.2 词表判别） |
| `cleaned_text` | str | 是 | S0 | 规范化后文本；模型唯一正文输入 | — |
| `doc_no_hash` | str(16) | 否 | 渠道 | 跨源去重键 | web 88.4%（缺 199，其中公示 179）；pkulaw 100% |
| `authority` | str | 否 | 渠道 | 机关名。**进信封不进提示**——用于 S3 交叉校验与组装 | web L1/L2 ~97%+；pkulaw 100% |
| `behavior_date` / `decision_date` | date | 否 | 渠道粗抽 | 元数据到日；**粗值进信封**供 S3 与模型产出交叉，定版以模型为准 | web 64.9% / 87.5%；pkulaw 94.9% / 100% |
| `prefilter.gambling` | enum | 是 | 预筛 | 是/否/待定 | 全库：1,934 / 2,814 / 253 |
| `prefilter.in_scope` | bool | 是 | 预筛 | 进模型阀门（§6） | — |
| `harvest_date` | date | 是 | 台账 | 采集日期 | 100% |
| `extra` | dict | 否 | 渠道 | 源标记：web（page_id/site/publisher/title/item_index/needs_ocr/province_code/region_level）；pkulaw（pkulaw_id/event_hint/detention_items） | 见 §3 |

**信封 vs 提示的分界（设计理由）**：模型提示只收 `cleaned_text + form + source_type`——保持两源输入同构、提示最短；`authority`/粗日期/预筛结果留在信封，供 S3 与模型产出交叉校验（如：模型抽的机关 vs 信封机关不一致→告警）。若把它们塞进提示，模型会被引导抄信封而不是读正文，交叉校验就失效了。

### 5.2 form 枚举（提案，待审核定稿）

| 值 | 判别依据（确定性） | 实测面（L1/L2） |
|---|---|---|
| 叙述式-独立成篇 | 有"经查/查明"叙述结构 + 单文书 | web ~933 + pkulaw 666 |
| 叙述式-结果栏内 | 正文嵌在结果栏的叙述 | pkulaw 35 |
| 字段表公示 | 17 词模板 ≥3 命中 | web ~539 + pkulaw 28 |
| 标题汇总公示 | 短行无冒号 + 标题模式 | web 116 |
| 叙述式-复议 | source_type=行政复议决定书 | web 74 |
| 判决书 | source_type=行政判决书 | 存量少 |
| 混合/弱模板 | 其余 | web ~135 |
| 合作案卷 | 预留 | — |

（pkulaw 现有三值是本枚举的子集，映射兼容。）

## 6. 预筛（保留现有 regex 的理由）

- 现状：web parse.py 的 gambling 三态 + in_scope；pkulaw tier_of。
- 保留理由：它是**阀门不是语义判断**——把 5,739 件滤到 2,451 件再调模型（成本差 2.3 倍）；"待定"253 件默认放行（宁可多调不可漏）。 gambling 判定错误的后果只是"多一次模型调用/少一次"，由 S3 的 gambling_scope 校验兜底；这正符合"规则做便宜可靠的事，模型做语义"的分工。
- 接口：预筛结果写进原料信封（`prefilter` 字段），模型可自证推翻（输出 gambling=否+理由 → S3 交叉告警 → 人工队列）。

## 7. 模型交互链路

### 7.1 输入构造（一次调用，95%+ 免切块）

```
system: 五段/字段规范定义（引 data-spec）+ 硬规则（定性句不入事实段、引文必须逐字、仅输出 JSON）
few-shot: 3–5 个（从对照参考集抽，按 form 匹配；提示版本 seg-v1 注册）
user: [form 标签] + cleaned_text（>3,000 字的 36 件按句号粗分 2–3 块）
```

实测长度支撑：cleaned 前原文 p50=478 / p90=1,383 / p99=5,702 / max=38,859（web 全库）；pkulaw max=2,905。输入 token ≈1–2k、输出 ≈0.5k。

### 7.2 输出 JSON Schema（逐字段）

```json
{
  "segments": [{"type": "facts|evidence|reasoning|decision|review", "quote": "逐字引文"}],
  "subject": {"mention": "本人原写法", "aliases": ["同案写法"]},
  "outcome": {"type": "不予处罚|不构成违法|警告|罚款|拘留|拘留并处罚款|移送刑事",
              "detention_days": 0, "fine": 0, "not_executed": false,
              "confiscation": [], "detention_items": [],
              "articles": [{"text": "治安管理处罚法第七十条", "edition": "2012修正|2025修订|未知"}],
              "stated_circumstances": ["情节严重|从轻|减轻|从重|不予处罚（原文怎么写怎么记）"]},
  "dates": {"behavior": {"quote": "…"}, "decision": {"quote": "…"}},
  "review": {"result": "维持|变更|撤销|确认违法|程序驳回|无", "changed_outcome": null},
  "gambling": {"verdict": "是|否|待定", "reason": "…"},
  "law_version_hint": "旧法|新法|未知",
  "confidence": "high|low"
}
```

逐字段解释与实测缺口：

| 字段 | 解释 | 现状缺口（实测） |
|---|---|---|
| segments.quote | 五段逐字引文，**不产出坐标**（S2 定位） | 源端分段降为对照 |
| subject.mention/aliases | 本人+同案写法；复议文书须解析"申请人" | web 复议 subject 仅 16.4% |
| outcome.type 等 | 结构化处罚结果 | warn outcome_not_parsed 1,129（全库）；detention_days>0 69.5%（web）/39.8%（pk）；**合并执行明细 detention_items 对齐 extra 现有辅助字段** |
| articles.edition | 版本注解——law_version 定版依据（D8：实际适用版本） | 现 articles 无版本注解（top1 "治安管理处罚法第七十条" 2,018 处裸写）；（2025修订）第七十条≠新法口径要显式校验 |
| stated_circumstances | 明写情节认定——裁量模型的关键要素 | **现几乎为空（web 0.6% / pk 0.1%）**，是最大的要素抽取缺口 |
| dates | 行为/决定日期引文 | 公示行为日期多为真缺失（22% 有），模型不得编造——schema 允许 null+confidence=low |
| review | 复议/诉讼结论 | pkulaw 全"无"（无复议文书）；复议标签靠组装层 linked_ids 关联原处罚 |
| law_version_hint | 模型按引文版本自报，S3 与 articles.edition 交叉 | web 未知 66.9% 全库，其中 1,840 件文中引治安法可恢复 |

### 7.3 调用纪律

- temperature=0；重试 = 同模型 1 次 → 换旗舰 1 次 → 低置信队列；生产单旗舰，三模型并行仅抽检复核。
- 缓存键 = `text_orig_sha256 + model + prompt版本`（原文哈希不随清理规则漂移，缓存命中稳定）。
- 模型纪律：仅远程旗舰（与金标线同档），禁本地小模型。
- 量级：预筛后 2,451 件 × 1 调用；金标线 50 件三模型评审已实跑通该形态。

## 8. S2 定位（quote → 原文坐标）

```
① cleaned_text.find(quote)（空白归一后）；多处命中→要求模型前后文消歧→仍歧义→低置信
② 失败→模糊对齐（去空白/标点，difflib 锚定搜索）
③ cleaned 坐标 ──offset_map──► 原文坐标（单调映射复合，逐字符单测）
④ 原文坐标 = 交付坐标（原文正本，无第三级投影）
⑤ 段间互不重叠；并集覆盖决策类文书主体 ≥95%
```

对照参考集用法：源端分段（web 坐标、pkulaw 段文本）与模型分段逐件比对，**一致率高→免复核；分歧→第二模型裁决或低置信队列**——这是零人力条件下的免人力质检器（pkulaw 段文本 100% 精确子串已实测，可直接 find 定位比对）。

## 9. S3 校验注册表（迁移 + 新增）

| 校验 | 规则 | 级别 |
|---|---|---|
| quote 命中/唯一 | §8 ①② | 硬 |
| 覆盖度/重叠 | 五段不重叠、决策主体覆盖 ≥95% | 硬 |
| outcome 一致性 | type↔detention_days↔fine↔detention_items（合并执行 = max） | 硬 |
| **罚幅对账（新增，零人力下唯一外部锚）** | outcome 不超所引法条法定上限（治安法第七十条/第八十二条各档；2026 前后版本不同） | 硬（超限→error；合并执行 ≤20 日 warn） |
| 法条版本口径 | （2025修订）第七十条 ≠ 旧法第七十条；articles.edition 与 law_version 一致 | 硬 |
| 日期顺序 | decision ≥ behavior；粗值 vs 模型值交叉 | 硬/warn |
| subject | mention 出现在 facts 引文内 | 硬 |
| gambling 交叉 | 模型 verdict vs 预筛不一致 | warn（进队列） |
| 枚举/Schema | 全字段枚举合法 | 硬 |
| review 枚举 | 六值；"驳回诉讼请求"=维持口径 | 硬 |
| 覆盖切片 | parse_qc 15 项按原口径迁移（N3 双口径顺带修复） | 硬/软 |

失败处置：硬失败 → 换旗舰重试 1 次 → 低置信队列（mask_review 显示辅助）；软 warn → 标记入库。

## 10. 语料组装（build 层改造）

| 步骤 | 现状 → 改造 |
|---|---|
| 去重 | doc_no_hash（现状保留）+ MinHash 近重复（R7）；**199 件无文号盲区**靠事件键+正文近似兜底；跨源文号规范化一致性待抽 1–2 例验证 |
| **事件键统一（硬伤修复）** | 废弃两源各自公式（web：机关\|月\|首金额，可空串；pkulaw：机关\|全日期\|金额集合，'-'占位），build 层单一实现：`机关｜日期(到日)｜金额集合`；缺失成分'-'占位、永不空串 |
| linked_ids | 复议↔原处罚：文号引用 + 同机关同当事人对齐（复议自身 outcome 仅 31.7%，标签必须关联取） |
| region | web 沿用区划映射；pkulaw authority→region 编码补齐（729 件） |
| tier 重分级 | tier_of(has_facts, has_outcome, gambling, in_scope) 全部改由**模型产出**推导；拼写统一为 web 口径（L2-只有结果） |
| law_version 定版 | 以 articles.edition 为准（D8），不按行为日推算覆盖 |

## 11. 统一产物 parsed-2 字段表

> 三段来源：**[原]** = 继承原料/组装，**[模]** = 模型产出经校验，**[组]** = 组装层生成。schema 版本随协调层规范修订联动。

| 字段 | 来源 | 说明 |
|---|---|---|
| record_version / id / source / batch | [原] | 溯源四件套；batch 指渠道解析批次 |
| parser | [原] | 升级四元组 `parse-v2\|model:<id>\|prompt:seg-v1\|clean:v1` |
| source_type / source_ref | [原] | source_ref（URL/引证码）**只在 parsed 层**，交付层剥离 |
| doc_no / doc_no_hash | [原] | doc_no 仅 parsed 层 |
| harvest_date | [原] | |
| behavior_date / decision_date | [模]（信封粗值交叉） | 定版以模型引文为准 |
| authority / region / province / province_code / region_level | [原+组] | pkulaw region 由组装补 |
| law_version | [模+组] | articles.edition 定版（D8） |
| subject_mention / subject_aliases | [模] | aliases 新增 |
| event_key | [组] | 统一公式重算 |
| event_id / linked_ids | [组] | 交付层必填 |
| text_full / text_orig_sha256 | [原] | **原文正本**（脱敏取消后）；SHA = 原文哈希，随 parse 冻结稳定 |
| segmented / segments(坐标) / 五段文本 | [模] | 全部记录将有模型分段；源端先验仅对照 |
| outcome（全子字段 + articles 带版本 + detention_items） | [模] | detention_items 与现 extra 辅助对齐 |
| review（result / changed_outcome） | [模+组] | 复议经 linked_ids 补原处罚 |
| quality（tier / in_scope / completeness / parse_warnings / form / gambling / ocr / facts_contains_conclusion） | [模+组] | 现枚举值全保留；parse_warnings 取值域实测：outcome_not_parsed 1,129 / facts_contains_conclusion 222 / articles_not_parsed 41 / facts_missing 30 / attachment_only 12 |
| schema_version / pipeline_version | [组] | |
| extra | [原] | 源标记；建议 `extra.outcome`→`extra.detention_items` 改名 |

**相对现行 parsed-1 的字段级变化**：`deidentified`/`r6_scan` 消亡（随脱敏取消，规范修订联动）；`subject_aliases` 新增；`articles[].edition` 新增；`segments` 坐标改由模型产出；`event_key` 公式统一；tier 拼写统一。

## 12. 交付与验收（变化点）

- 交付 = parsed-2 的 L1 主文件 + L2 outcomes_only + 排除清单 + SHA256SUMS；目录不可变，`LATEST` 只是指针。
- 正文 = 原文正本：`text_sha256` = 原文哈希，重建不再漂移（原"每次重建 42 件漂移"消失）。
- 验收变化（随规范修订）：`deidentified`=是、r6 通过、隐私硬命中 0 三项检查移除或转外发；其余（字段/枚举/法条上限/日期/子串定位/subject/哈希）保留。
- r6 时点：文本基座切换（机械，从 parsed-1 可重建）与解析器切换（模型层）**分开**——建议 r6 只切文本基座，parse-v2 达标后出 r7，diff 干净。是否出 r6 挂在协调层规范修订落地时点。

## 13. 对照参考集（免人力质检器）

| 集 | 内容 | 用途 |
|---|---|---|
| web 分段 | 源端坐标（L1/L2 4,294 段 100% 精确子串） | 与模型分段比对：一致→免复核；分歧→裁决/队列 |
| pkulaw 段文本 | 源端段文本（2,071 段 100% 精确子串，无坐标可 find） | 同上 |
| 渠道 outcome | regex 抽取（含 1,129 件未解析标记） | outcome 字段对照 |
| 既有 parse_qc / 验收历史 | r4/r5 QC 记录 | 回归对照 |

## 14. 消亡清单

| 消亡项 | 原因 |
|---|---|
| L5 人标层（双人 κ、金标/银标双层） | 零人力已定；模型仲裁标注（10-16 决策）+ parsed-2 要素字段即标注集；仲裁回执替代人标记录 |
| deid_map / r6_report（主管线内） | 脱敏取消；deid.py/r6_scan.py 转外发衍生工具 |
| 源端 event_key 两套公式 | build 层统一重算（§10） |
| 源端分段权威地位 | 模型分段取代；源端降为对照参考集 |
| offset_map 落盘 | 管线内传递，不进契约 |

## 15. 实测附录（口径与数字索引）

- 脚本口径：parsed-1 全量（web-r3 5,001 / pkulaw merged-b2 738）；L1/L2 原料口径 web 1,722 / pkulaw 729；全部聚合统计零原文输出。
- 关键数字：跨源 doc_no_hash 交集 0（web 1,418 / pkulaw 729）；web L1/L2 无文号 199（公示 179）；段文本精确子串 web 4,294/4,294、pkulaw 2,071/2,071；pkulaw 分段坐标 0/729、region 0/729、管道表 77、逗号尾 67；web 导航 16、字段表 ~539、标题汇总 116、混合 ~135；预筛分布 1,934/2,814/253；length p50 web 478 / pk 859。
- event_key 公式核对：`to_parsed1.py:65` vs `pkulaw_ingest.py:1338`（差异：日期粒度 月 vs 日、金额 首个 vs 集合、空值 '' vs '-'）。
- 修正记录：`extra.outcome` 非双写（= detention_items 明细）；"251 件档次式公示"为词表口径误判，实为标题汇总式 116 件 + 混合 135 件。

## 16. 待审核问题清单（多轮迭代的抓手）

1. §5.2 form 枚举八值是否定稿（影响提示模板与词表）。
2. authority/粗日期进信封不进提示的分界（§5.1 设计理由）是否认可。
3. event_key 统一：build 重算（推荐）还是源端修齐？
4. pkulaw 三步归一（管道表/逗号续行/区划）执行线归属。
5. §7.2 Schema 字段增删（如 law_version_hint 是否必要、detention_items 进 outcome 还是 extra）。
6. §9 罚幅对账作为零人力唯一外部锚的优先级确认。
7. r6（文本基座切换）出不出、何时出（§12）。
8. 统一原料契约命名与落盘位置（建议 `$JUSTILAW_DATA_DIR/unified_raw/<来源>/<批次>/`，parsed-1 现行文件不动）。

## 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-17 | 初版：全链路格式视角总图、渠道冻结范围、S0 词表与注册表、统一原料契约字段表、模型交互 Schema、校验注册表、组装改造、parsed-2 字段表、消亡清单、实测附录；含两处实测修正（extra.outcome、公示子形态） |
