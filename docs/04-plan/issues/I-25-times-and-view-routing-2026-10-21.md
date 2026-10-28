# I-25：`times` 过度推断 + 前科/复议视图矛盾（2026-10-21）

> 状态：**times 部分已修正；B/C 视图问题仍 open**。影响 expansion-1000 的 909 条标签；
> 修正后标签仍只能 training-only，不能作为正式 parsed-2 或评测标签。
> 关联：`annotation-guideline.md` v0.4.4 §3.5；`schema.py` `conduct.times` 描述；
> `LEAKAGE-REMEDIATION-REPORT.md`；`labels-909-audit.json`；`labels-909-timesfix/`。

## 1. 问题一：`times=1` 被过度推断

### 事实

按 `annotation-guideline` v0.4 §3.5（2026-10-18 E-05，最新修订 v0.4.3）：

| 原文写法 | 记法 | 状态 |
|---|---|---|
| "两次""3 次"等明确数字 | 该数字 | 明确 |
| "多次""数次""经常" | null | 推断 |
| "一场""本次" | 1 | 明确 |
| **未提及赌博次数** | **未提及** | **未提及** |

即：**只有原文出现“一场/本次/此次/该场/单次/一次/明确数字”才记 1；单个日期、单次事件描述不算次数提及。**

### 当前 909 条标签实测

- `times` 状态：未提及 677、推断 124、明确 108。
- `times=1`：**215 条**。
- 在 facts+meta 输入视图中**完全没有次数字样**的 `times=1`：**208 条**。
  - 其中状态“明确”99 条；
  - 状态“推断”109 条。
- 证据 quote 中出现明确次数字样的只有 2 条；视图中出现但证据未选中的 3 条；合计 7 条可解释。
- 典型错误：原文只有“现查明 2024年7月29日……进行赌博”，模型就记 `times=1`，
  甚至标“明确”。

### 结论

**208/215 不符合最新规范。** 最新口径不是“单次事件=1”，而是“没有次数字样=未提及，value=null，evidence=[]”。
规范在 v0.4 E-05 已统一；本次问题是 `schema.py` 的字段描述和教师提示只写了“次数（场次）”，
没有把 §3.5 的四行规则放进提示/校验器，模型便从“一个日期/一个场景”自行推 1。

### 最新决策口径（本次确认）

1. 原文明确数字（两次/3 次/多场+数字）→ 值=数字，状态=明确；
2. 原文“一场/本次/此次/这次/该场/单场/单次/一次/1 次” → 值=1，状态=明确；
3. 原文“多次/数次/经常”且无确切数字 → 值=null，状态=推断；
4. **原文没有次数字样（只有单个日期/单次事件描述）→ 未提及，value=null，evidence=[]**；
5. 不得从单个日期、单个场景、处罚结果或“一场赌博”的常识反推 1。

### 需要修的地方

- `schema.py` / `element_labels.py` 的 `times` 描述与系统提示：加入上述四行规则；
- 校验器或后处理：`times.value==1` 但证据/视图无明确次数字样 → 降级为未提及；
- 对 909 条重跑受影响记录，或在标签包做确定性降级并重审计；
- 203 银标与人工口径保持一致：未提及为主，只有明确“一场/本次”才 1。

## 2. 问题二：前科（B）与复议/程序（C）的视图矛盾

### B：前科 meta（8 条）

原文例：

> `违法前科：2023年05月17日，因4.25开设赌场案，被新乐市公安局罚款。`

- `last_prior_penalty_date` 需要这条前科事实；
- 但 `penalty_amount` 泄漏正则把“罚款”判为当前处罚泄漏；
- 输入视图只有 facts/meta，没有 `prior_record` 通道；
- 删掉丢要素，保留被泄漏闸拒绝，模型还可能把前科罚款当本次处罚。

**这是设计矛盾，不是原文没有事实。** 解决：增加 `prior_record` 类型化视图（只允许
`last_prior_penalty_date` 引用），最好只传前科日期+案由，不传罚款金额；或窄例外并明确标注来源。

### C：复议/程序陈述（3 条）

原文例：

> `申请人称：我因参加赌博被……行政拘留15日，罚款3000元……`

这是复议/诉讼材料，不是本案当前行政处罚事实。当前管线把它当普通处罚决定书，S1 划进 facts，
才触发泄漏。解决：按 `source_type` 路由，行政复议/法院材料走 review/outcome 通道，不进要素供给。

### A：字段表/公示结果行（16 条）

只有案名+日期+处罚+法条，没有行为事实；应走 outcome-only 或隔离，不强行产要素。

## 3. 影响

- 909 条标签中，`times` 字段至少 208 条需降级/重标；这是训练前必须处理的字段级缺陷。
- 27 条泄漏残余中，16 条应排除，8 条需 prior_record 视图，3 条需 review 路由。
- 在这些问题关闭前，909 条只能作 **training-only silver**，不能作为正式 parsed-2 或评测标签。

## 4. 证据路径

- `D:/02_Dev/Data/justilaw-research/s1_runs/expansion-1000-20261021/labels-909-audit.json`
- `.../teacher-inputs-v4d/`
- `.../LEAKAGE-REMEDIATION-REPORT.md`
- `.../leak-remediation-manual-queue-final.jsonl`
- `docs/05-research/annotation-guideline.md` §3.5

## 5. 执行结果（2026-10-21）

### 规范

- `annotation-guideline.md` 升到 **v0.4.4**：`times` 只有原文出现明确数字或
  “一场/本次/此次/这次/该场/单场/单次/一次/1 次”才记 1 明确；只有单个日期/单个场景/
  单次事件描述、没有次数字样的一律未提及；禁止“推断+value=1”。
- `schema.py` 的 `conduct.times` 描述同步该口径；教师提示（`element_labels.py`）和单模型
  `extract.py` 都从 schema 描述生成，自动生效。
- schema fixtures 已重生成；`test_element_labels.py` + `test_accept_element_labels.py`
  **13 passed**。

### 统一修正

对 909 条标签执行 `fix_times_909.py`，原标签包保留，修正包写入 `labels-909-timesfix/`：

| 动作 | 数量 |
|---|---:|
| 无次数字样 `times=1` → 未提及 | 212 |
| 仅视图有标记、证据不支持 → 未提及 | 4 |
| 无明确数字的 2/3/4/5 等 → 未提及/推断 null | 2 |
| 推断 null 但无“多次”依据 → 未提及 | 7 |
| “至少18次” → 推断 18（下界） | 1 |
| 明确数字/标记保留或改明确 | 4 |
| 多次无数字 → 推断 null | 1 |

最终 `times` 分布：

| 状态/值 | 数量 |
|---|---:|
| 未提及 / null | 903 |
| 推断 / null | 1 |
| 推断 / 18 | 1 |
| 明确 / 1 | 1 |
| 明确 / 2 | 3 |

`times` 非空从 **215/909 降到 6/909**（5 个有值 + 1 个推断 null）；其余全部未提及。
单模型 schema 不接受“推断+null”，因此单模型里的 1 条“多次”已降为未提及并记
`engine_contract_conflict`；三模型 wire 保留 1 条推断 null。  
修正包：`labels-909-timesfix/records.jsonl`、`changes.jsonl`、`manifest.json`、`summary.json`。

### 仍未关闭

- B（前科 `prior_record` 视图）和 C（复议/法院文档路由）仍 open；
- 16 条字段表结果行仍应 outcome-only/隔离；
- 909 条修正后仍为 training-only silver，不能当金标或正式 parsed-2。

## 6. 深入复查：B/C 不是 27 条边缘样本，而是三层设计缺陷（2026-10-21）

> 本节对 909 条标签、1000 条输入、482 条泄漏隔离和 S1 分区结果逐条复算。
> 数字为当前数据目录实测；“前科”计数使用肯定性表述探测，个别边界需人工复核。

### 6.1 909 条的来源构成

| 来源 | 数量 | 占比 | 说明 |
|---|---:|---:|---|
| 处罚决定书 | 653 | 71.8% | 627 叙述式独立成篇 + 26 结果栏内 |
| 执法公示 | 199 | 21.9% | 69 字段表 + 122 混合弱模板 + 8 字段式 |
| 行政复议决定书 | **57** | **6.3%** | 全部为 web 叙述式复议 |

C 的真实范围不是 3 条，而是 **57 条**复议决定书进入了要素供给。27 条残余中的 3 条只是
“补救脚本无法再切”的那 3 条；其余 54 条被“恢复”了，但仍是复议文书。

### 6.2 复议标签的实际污染

- 57 条中 **54 条**的 facts/meta 视图仍含“申请人称/被申请人称/复议请求/申请人：/被申请人：”
  等复议当事人语言；**38 条**的要素证据直接引用了这类句子；
- 57 条中 4 条三模型、38 条单模型、15 条单模型恢复批，**53/57 是单模型**；
- S1 的 user prompt 其实**已经带了 `[source_type] 行政复议决定书`**；模型仍把 94 句
  当事人陈述放进 `meta`、16 句放进 `facts`。原因是 6 类 zone 里没有
  `party_allegation`：`review` 的定义是“复议/诉讼机关的审查意见与结论”，
  不是申请人/被申请人的陈述。**类型提醒无法替代输出类型**；
- 典型错误：`S1-cb022f26d4d5069839bc` 的 `first_offense=false` 证据是
  “申请人之前曾到此处参与过三四次赌博”——这是当事人陈述的先前行为，不等于
  “曾被公安机关查处”，不足以否定初次；
- 典型结构：一份复议决定书同时包含“被申请人称（原处罚事实）”“经审理查明（复议机关认定）”
  “复议决定（维持/撤销）”。当前 `facts` 区没有区分当事人陈述与复议机关认定，
  要素教师看到的“事实”可能是单方陈述。

**结论：C 不是“3 条进错通道”，而是“57 条复议文书被当成处罚决定书做要素标注”。**

### 6.3 前科（B）的真实范围

27 条残余中的 8 条前科 meta 只是最显眼的部分。逐条复算 909 条的原文与视图：

- 909 条中 `last_prior_penalty_date` 非未提及 **26 条**（23 明确 + 3 推断）；
  其中 20 条证据落在 `meta`，6 条落在 `facts`；
- 48 条记录在全文命中肯定性前科表述（含少量法条/否定句边界），其中 **34 条**进入视图，
  **14 条**没有进入；14 条按 S1 zone 分布：`reasoning` 8 条、facts 之后 `meta` 3 条、
  `review` 1 条（法条引用）、`decision` 1 条（法条引用）、`facts` 1 条（投影/切分差异）。
  逐条看，**7 条可确认为真实前科事实被视图丢掉**：4 条 reasoning（其中 3 条无日期、
  1 条日期为 2020-01-23）+ 2 条后置 meta（酒驾前科，含 3 个日期）+ 1 条 facts；
  另有 2 条法条引用、1 条否定陈述、1 条刑事前科，不应计入前科日期；
- 例：`S1-1316908ed339f4c89aff` 原文“另查明，张**曾因赌博于2020年1月23日被公安机关
  治安处罚”，S1 把它划进 `reasoning`，视图不收，标签为未提及；
- 例：`S1-a838f370052513a13f68` 的公示 meta 有两条酒驾前科（2017-08-21、2021-10-04），
  位于 facts 之后，视图不收，标签为未提及；
- 8 条残余前科中，7 条的 target 不在前科句内，靠“违法前科”字段语义绑定本人；
  当前视图没有字段/段落作用域，只有字符串 target，无法表达这种绑定。

**S1 其实已经抽出过一部分前科提要**：`outcome.stated_circumstances` 在 39 条记录里
出现前科字样；26 条前科标签中 10 条能在其中找到，8 条残余中 5 条（e317、17bd、afe1、
131690、cf47）的 stated 已含前科。但要素链路完全不读这个字段（`build_inputs` 只读
zones），所以“前科抽不出来”不是主因；主因是**抽出来没接线、视图又没收**。
仍有约 40 条全文有前科而 stated 没有严格匹配，抽取也不完整，但这是第二位的。

**为什么 leak gate 对这些前科时而放过、时而拦截**：`penalty_amount` 只匹配“罚款”或
“拘留+日/天”。前科写“行政拘留”不带天数就通过（26 条多数如此）；写“罚款”或
“拘留十日”就被判泄漏（8 条残余）。同一法律事实，只因表面写法不同，命运相反。
这不是数据问题，是 gate 的语义错误。

### 6.4 字段契约缺口：前科存在但日期不明

3 条 reasoning 前科没有日期：

- “另查明，覃**、蒙**曾因赌博被公安机关治安处罚。”
- “因钱xx在六个月内曾受过治安管理处罚，应当从重处罚。”（两条）

`last_prior_penalty_date` 是日期字段；`element_labels.NULLABLE_WHEN_INFERRED` 不包含它，
所以 `value=null, status=推断` 会被判 `bad_value`。标注只能二选一：
写一个不存在的日期，或标“未提及”把前科事实丢掉。当前 3 条都标了未提及。
**这是 B 的字段级契约缺口：字段同时承担“是否存在前科”和“前科日期”，但没有
“存在但日期不明”的合法状态。**

### 6.5 泄漏闸的真实负担：它在替 S1/选择层做工

482 条泄漏隔离按来源和形态：

| 来源/形态 | S1 成功数 | 泄漏数 | 泄漏率 |
|---|---:|---:|---:|
| 处罚决定书 | 681 | 342 | 50% |
| 执法公示 | 247 | 120 | 49% |
| 行政复议决定书 | 66 | 20 | 30% |
| 叙述式-独立成篇 | 651 | 316 | 49% |
| 叙述式-结果栏内 | 26 | 26 | **100%** |
| 字段表公示 | 98 | 36 | 37% |
| 混合-弱模板 | 137 | 76 | 55% |
| 字段式公示 | 16 | 8 | 50% |

按“泄漏落在 facts 还是 meta”逐条复算，482 条不是同一种：

| 泄漏位置 | 数量 | 占比 | 主要内容 |
|---|---:|---:|---|
| **仅 meta** | **375** | **77.8%** | 301 条“叙述式-独立成篇”处罚决定书的 pkulaw 头（“处罚种类：罚款…”“执法依据：…第82条”）、36 条字段表、24 条结果栏、8 条字段式公示、6 条复议 |
| 仅 facts | 103 | 21.4% | 71 条本次处罚句、5 条前科、5 条定性尾句、4 条表头、82 条其他（含“处以打六合彩的方式”这类“处以”误判的假阳性、身份+前科+本次事实粘连句） |
| facts+meta | 4 | 0.8% | 两边都有 |

表中的 375/103/4 是**记录数**；下面的 flags 和 facts 分类是**泄漏句/flag 次数**，
一条记录可有多句，故分类合计会大于 103。

meta 侧 flags：`legal_basis` 930 次、`penalty_amount` 616 次；facts 侧：
`penalty_amount` 151 次、`legal_basis` 89 次、`decision_language` 87 次、
`legal_conclusion` 5 次。

所以“叙述式-独立成篇漏 49%”的主因不是 facts 里混了判决，而是 **meta 里的 pkulaw
结果字段被视图当成事实送进去了**。但这里要纠正一个说法：S1 把“处罚种类/执法依据”
放进 meta **不符合设计**。设计规定 `meta` 只放案件名称/文号/日期栏/当事人栏，
`decision` 才放处罚决定、依据、执行；S1 的 facts/decision 边界通常是对的，错在
meta 的语义范围。`build_inputs` 又把 facts 前 meta 全量收进教师视图，于是页头的
结果字段进入教师输入。其次才是 71 条 facts 本次处罚句；另有 154 条泄漏记录根本
没有候选子句（跨句或无可切分标点），需要段级重划，而不是子句级修补。

#### 6.5.1 以 S1-9497 为例：facts/decision 没切错，meta 切错了

`S1-9497afc064c42eee0d1d`（pkulaw，处罚决定书）的 S1 zones：

`meta 1–9` / `facts 10–25` / `evidence 26–29` / `reasoning 30` / `decision 31–37` /
`meta 38–41`。

- facts 10–25 是“现查明……组织赌客……抽水渔利……”的纯行为事实，没有本次处罚；
- decision 31–37 是“法律依据/处罚类别/处罚结果/行政拘留五日”，切分正确；
- 但 meta 第 3 句是：
  `处罚种类： 行政拘留行政相对人： 蒋永明执法级别： 区/县级执法机关：东安县公安局…`
- meta 第 4 句是：
  `执法依据： 中华人民共和国治安管理处罚法(2025修订)第82条`

也就是说，**同一份结果在页头和 decision 区各出现一次**：decision 区是对的，
页头的“处罚种类/执法依据”被 S1 放进了 meta。设计说 meta 只放案件名称/文号/日期/
当事人；S1 把整个 pkulaw 页头当成了 meta，违反设计。

为什么模型会这样：S1 提示词的 meta 定义是“表单元数据（案件名称、文号、日期栏、
当事人栏等）”，“等”没有封口；硬性规则只写“定性/结论句不进 facts”，没有写
“处罚种类/执法依据不进 meta”；S3 只查 facts_quality，不查 meta。模型把页头
整段归 meta，在提示词下是合理选择，但不符合设计。

更麻烦的是**粒度**：第 3 句里“处罚种类：行政拘留”和“行政相对人：蒋永明”粘在
一句里，中间没有句号；`clause_table` 按冒号切出来的第 5 段是
` 行政拘留行政相对人：`——处罚结果和下一个字段标签粘在一起。句子级 zone 和
子句级切分都无法既保留 person 字段、又排除 outcome 字段。这是**字段级语义 vs
句子级表示**的错位，不是 facts/decision 边界问题，也不是再加一个关键词正则能解决的。

另外，1000 条 S1 确实带了 `--clause-refine`，但 **917/994 的 `fact_clause_ids` 为空**；
482 条泄漏中 313 条有候选子句却选了 0；15 条选了子句的记录里 8 条选后无泄漏。
更关键的是 `build_inputs` 只用 `zones`，不读 `fact_clause_ids`；即使模型选了正确子句，
教师视图也不使用。语义子句选择不是不存在，而是没接线、没验收。

### 6.6 选择层缺口：16 条 A 类本不该进入

- 26 条“叙述式-结果栏内”全部泄漏；其中 10 条在删掉处罚句后 target 消失（target_lost），
  6 条字段表行没有可切出的行为事实，合计 16 条 A 类；
- 这 16 条不是“切句规则不够”，是**选择时没有检查“去掉本次结果后，是否仍有
  含 target 的行为事实”**；
- 同类缺口也造成 6 条 S1 硬失败（5 条执法公示 + 1 条复议）——这些记录本就不该进入
  S1 要素批次。

### 6.7 三层设计缺陷（按影响排序）

1. **选择层没有文书类型/行为事实门槛。** `source_type` 在 L1 存在，`selection.jsonl`
   和 teacher input 没有携带；S1 的 user prompt 虽然带了 `[source_type]`，但它只能提醒，
   不能给当事人陈述一个输出槽位。复议、结果栏、字段表与单案处罚决定仍走同一条链。
2. **视图契约只有 facts/meta，且是位置规则。** “所有 facts + facts 前 meta”既会漏掉
   reasoning/后置 meta 中的前科，也会把 facts 内的本次处罚句带进来。更关键的是
   **meta 本身是大杂烩**：pkulaw 的 document header（处罚种类/执法依据）、person info、
   违法前科都在里面；视图把 facts 前 meta 全量收进，375 条 meta-only 泄漏的主体
   就是这些 header 字段。没有 `document_header`、`person_info`、`prior_record`、
   `party_allegation`、`review_finding`、`table_row` 等类型。
3. **泄漏闸是文本正则，不是“本案结果”策略。** 它无法区分本次处罚/前科处罚/他人处罚/
   被复议的原处罚，也无法区分事实、法条引用和当事人陈述；482 条隔离和 27 条残余都是
   这个语义缺口的产物。已有具体假阳性：“犯罪嫌疑人李**处以打‘六合彩’的方式参与赌”
   里的“处以”被 `decision_language` 当成处罚决定，实际是“以…方式”的病句。
4. **句内语义选择建了但没接线。** `fact_clause_ids` 在 917/994 条为空；有候选的
   313 条泄漏记录也选了 0；15 条选了子句的记录里 8 条选后无泄漏。但 `build_inputs`
   只用 `zones`，不读 `fact_clause_ids`；S3 只把它当检查参照，不改变视图。
5. **前科提取存在但不被消费。** S1 的 `stated_circumstances` 已含 39 条前科提要，
   26 条前科标签中 10 条可对应；要素链路不读这个字段，视图又只收 facts+前 meta。

附带但同样影响下游的第六点：**证据坐标系不统一**。引擎线已复算，4,731 段证据中
587 段无法回投为原文连续精确引文，涉及 219 条（主要是恢复批）。视图坐标（facts+meta
拼接）不等于原文坐标；任何视图重构都必须同时定清“标签证据用哪套坐标”。

### 6.8 方案与影响

| 方案 | 改什么 | 对当前 909 的影响 | 对后续批次/架构的影响 | 成本/风险 |
|---|---|---|---|---|
| **O0 继续打补丁** | 给 8 条前科加窄例外；手工排除 16+3 条 | 27 条清掉；375 条 meta 泄漏 + 71 条 facts 本次处罚仍在；57 条复议仍在 | 下一批同样问题重演；视图策略不变 | 最低；不解决根因 |
| **O1 视图策略 + 子句接线 + 类型化** | ①meta 拆 `document_header/person_info/prior_record`，视图排除 header；②`fact_clause_ids` 接进 `build_inputs`，有候选时要求选择，S3 对 facts 内本次处罚句报 error；③新增 `party_allegation/review_finding`，复议走 review/outcome；④`prior_record` 覆盖 reasoning/后置 meta/facts，并消费 S1 `stated_circumstances`；⑤`last_prior_penalty_date` 允许 null+推断或拆 `has_prior_penalty`；⑥按 `form` 排除结果栏 A 类 | 909 → 约 852（去 57 复议）+ 8 条前科 = 约 860；375 条 meta 泄漏源被视图策略消掉；71 条 facts 杂糅用子句选择处理；7 条被丢前科可修正；16 条 A 排除 | 视图层不再靠 leak gate 兜底；后续批次可复用同一策略；不需重跑 S1 | 中等；1–2 天；视图契约是加法，但 203 冻结片/`load_slice_work` 仍只认 facts/meta，需版本兼容 |
| **O2 全量类型化段模型** | S1 增加 `document_type`、`case_unit_id`、`prior_record/party_allegation/review_finding/table_row`；视图策略按要素组声明；leak gate 改为按段类型禁入；S3 按文书类型校验 | 需重跑 S1（约 ¥30）和 L5（约 ¥15），909 标签不能直接复用 | 从根上解决 A/B/C 和多人物行；review/outcome 成为一等公民 | 高；1–2 周；契约破坏性变更，203/冻结片需双版本或重建 |
| **O3 分阶段（建议）** | 现在做 O1；下一批再增量做 O2 的 `document_type` + `prior_record`，保留 facts/meta 兼容 | 当前 909 先得到可用子集（约 860，training-only） | 不阻塞当前训练准备，同时把架构演进留在下一批 | O1 成本 + 后续增量；需明确双契约期限 |

### 6.9 建议

**做 O1，不做 O0；O2 留到下一批，不在当前 909 上做全量重跑。**

具体顺序（按泄漏量排序，不按概念排序）：

1. **先做 meta 视图策略，不加正则**：把 S1 的 `meta` 拆成
   `document_header`（pkulaw 的处罚种类/执法依据/文号/日期栏）、`person_info`（姓名/住址/
   身份证）、`prior_record`（违法前科/曾因…处罚）。教师视图只保留 `person_info` 和
   `prior_record`，**`document_header` 一律不进**。375 条 meta-only 泄漏的主体就是
   document header；这一步不需要任何语义模型，也不需要“处罚种类/罚款”新正则。
2. **把句内语义选择接上**：`build_inputs` 改为：有候选子句时，用 `fact_clause_ids`
   选定的事实子句替代整句 facts；模型没选时不能静默接受 `[]`，要么重试，要么降级为
   “整句进 evidence/meta 并标记 needs_review”。S3 对叙述式 facts 内的本次处罚句
   （决定给予/罚款/拘留+日/天/法条）报 error。71 条 facts 本次处罚句 + 5 条定性尾句
   靠这一步处理；154 条无候选子句的记录需要段级重划，不能靠子句。
3. **复议文书类型化**：新增 `party_allegation`（申请人称/被申请人称/复议请求）和
   `review_finding`（经审理查明/本机关查明），`review_outcome`（维持/撤销/变更）。
   57 条复议移出要素供给，转 review/outcome；只有 `review_finding` 可作为事实来源，
   当事人陈述不能作为要素证据。**不要只给 L5 传 source_type**：S1 已经收到了，
   仍然把 94 句当事人陈述放进 meta，因为没有输出槽位。
4. **前科链路**：`prior_record` 来源覆盖 facts、facts 前 meta、facts 后 meta、
   reasoning 中的前科句，并优先消费 S1 已抽出的 `stated_circumstances`；只允许
   `last_prior_penalty_date`、`violations_last_year`、`first_offense` 引用；
   `prior_record` 内允许“罚款/拘留”等前科处罚词，`decision/review` 仍禁入。
   7 条 target 不在前科句内的记录，用字段/段落作用域绑定，不靠字符串包含。
5. **字段契约与选择路由**：`last_prior_penalty_date` 允许 `null + 推断`（前科存在、
   日期不明），或拆出 `has_prior_penalty`；`first_offense` 在前科存在时必须为 false；
   `form=叙述式-结果栏内` 和“去结果后无 target 行为事实”的行排除（16 条 A）。
6. **审计口径**：把“视图干净”与“任务有效”分开统计；当前 `leak_flags_in_evidence=0`
   只说明证据引文没有泄漏词，不说明 57 条复议文书适合做要素标签。

预期当前批结果：约 **860 条 training-only silver**；57 条复议和 16 条 A 排除；375 条
meta 泄漏源被视图策略消掉；71 条 facts 杂糅用子句选择处理；8 条残余前科 + 7 条被位置
规则丢掉的前科可修正；`first_offense`/`last_prior_penalty_date` 的一致性可复核。
仍不能称 parsed-2 或金标，不打开 203 封存 test。

## 7. meta_fields 小轮测试（12 条，2026-10-21）

### 7.1 已实现的改动

工作树 `C:/Users/17728/.codex/worktrees/l5-quality-s1-run/大创`：

- `research/discretion/unify/s1.py`：
  - 删除 meta 的“表单元数据（…等）”模糊定义，明确 meta 只放案件名称/文书名称/文号/
    日期栏/当事人栏/违法前科；处罚种类/结果/金额/没收/依据/执行不得进 meta；
  - 新增 `meta_fields` 契约（`person/case/prior/outcome/other` + 逐字 `quote`）；
  - `validate_meta_fields` 校验 quote 必须在 meta 句内唯一、逐字，并解析出 cleaned 坐标。
- `research/discretion/unify/run_seg.py`：
  - 新增 `--meta-refine`；`request_for` 追加“本次必须输出 meta_fields”；
  - `validated_output` 在 `--meta-refine` 下强制校验；
  - `VERSION` 升到 `seg-v2-durable-5-meta`；manifest 记 `meta_refine`。
- `research/discretion/unify/run_elements.py`：
  - `build_inputs` 支持 `meta_fields`：只把 `person/case/prior` 的 **子片段** 投影回原文，
    `outcome/other` 和 facts 之后的 meta 一律不进教师视图；旧输出无 `meta_fields` 时走 legacy；
  - 修正 `first_f`：无 refined facts 时回退到第一个 facts zone，避免 `refined=[]` 时把后置
    meta 全收进来。
- 离线测试：`test_element_pipeline.py` **71 passed**。

### 7.2 测试结果

样本：374 条 meta-only 泄漏中分层抽 12 条（4 pkulaw 处罚、3 web 处罚、3 公示、2 复议）；
为控耗时**未开 clause-refine**，只开 meta-refine。

| 指标 | 结果 |
|---|---:|
| 旧视图 meta 泄漏 | 12/12 |
| 新视图当前结果泄漏（person/case） | **0/10** |
| 新视图 meta 泄漏（prior） | 4/10 |
| 新视图 facts 泄漏 | 0/10 |
| target 可见 | 10/10 有效输出 |
| 输出有效 | 10/12 |
| 角色分布 | case 74、person 36、other 20、prior 6、outcome 1 |
| meta 文本长度（10 条） | 2,496 → 1,520 字符（-39%） |

- **meta 细化对当前结果有效**：旧视图 12/12 泄漏，新视图 person/case 泄漏 0/10；
  当前处罚/法条已被排除。
- **剩下 4 条是前科**：全部为 `role=prior` 的“违法前科…罚款/行政拘留”，不是本次结果；
  需要 role-aware 的 prior 策略，不能再用文本 gate 一刀切。
- **2 条无效都来自字段表公示**：`S1_invalid_meta_fields:not_meta_zone:7/8`。公示族的
  `zones_det` 是确定性分区，模型的 meta_fields 与它不一致；字段表公示应走表格字段解析，
  或暂时跳过 meta-refine。
- 报告全文：`D:/02_Dev/Data/justilaw-research/s1_runs/meta-refine-test-20261021/META-REFINE-TEST-REPORT.md`。

### 7.3 耗时诊断（回答“一条 S1 为什么这么久”）

同一批 30 条最初开了 `--clause-refine`，单条 4–5 分钟。token 实测：

| 调用 | prompt | completion | reasoning |
|---|---:|---:|---:|
| 慢批第 1 条 | 2,081 | **16,000（触顶）** | 16,000 |
| 慢批第 1 条 repair | 2,090 | 7,186 | 6,500 |
| 慢批第 2 条 | 1,986 | 10,498 | 9,819 |
| 快批（无 clause-refine） | 1,719–1,866 | 2,773–11,266 | 1,996–10,588 |

- **输入不大**（1.7–2.1k prompt tokens），慢在输出/推理；快批 70k reasoning / 79k completion，
  推理占 88%。
- `deepseek-flash` 是推理型模型；S1 一次调用同时做 zones、outcome/dates/review/gambling、
  clause 选择 + role、meta_fields，模型会长时间“想”。
- `--clause-refine` 把候选子句清单和逐句 role 选择塞进同一次调用，是慢批的主因。
- `deepseek` 配置 `max_tokens=16000`，慢批第 1 条 completion 正好 16,000——推理耗尽输出预算，
  首答无效，触发 repair（又 7k），所以一条 4–5 分钟。
- 快批无 clause-refine：12 条 14 次调用、¥0.6815、约 8 分钟，约 40 秒/条；仍有单条
  10.6k reasoning 的波动。

把原批拆开看，慢不是单一原因：

| 批次 | provider/model | shards | calls | median completion | median reasoning |
|---|---|---:|---:|---:|---:|
| 原 v3 | xiaomi-pro / mimo-v2.6-pro | 4 | 309 | 837 | 609 |
| 原 v4 | xiaomi / mimo-v2.6-flash | 3 | 107 | 783 | 513 |
| 原 v2 | deepseek / deepseek-flash | 16 | 620 | 2,785 | 2,496 |
| 新 fast | deepseek / deepseek-flash | 1 | 14 | 5,439 | 4,771 |
| 新 slow | deepseek / deepseek-flash | 1 | 4 | 8,842 | 8,160 |

- **Xiaomi → DeepSeek 本身就是 3.3x**（837 → 2,785），这是模型差异，不是 meta；
- **DeepSeek 上加 meta_fields 再 2x**（2,785 → 5,439）；
- **meta + clause-refine 再 1.6x**（5,439 → 8,842），并出现 16k 触顶 + repair 的尾延迟；
- **原批 16 shard / 8–16 并发，新测试单进程串行**：吞吐差被体感放大成“一条 4–5 分钟”。
- 原批 v2 的 execution manifest 也是 deepseek-flash、max_tokens 16000，所以 16k cap 不是
  新加的；新加的是 meta 任务本身和它与 clause-refine 的同调。

### 7.4 下一步（按优先级）

1. **拆 S1 调用**：segmentation/outcome（快）、meta_fields（只对 meta 句）、clause 选择
   （只对候选句）分开；至少 meta 测试不再带 clause-refine。
2. **换低推理模型或低 reasoning effort** 做结构化抽取；S1 是抽取，不是长链推理。
3. **加截断检查**：`completion_tokens == max_tokens` 视为截断，直接换更高 cap/低推理重试，
   不要让 repair 静默翻倍。
4. **公示族**：`zones_det` 记录暂时跳过 meta_fields，转表格字段解析。
5. **前科**：`prior_record` 单独的泄漏策略，允许前科处罚词只进入前科字段，不进入当前结果。
6. **复跑 12 条**：低推理 + meta-only，确认 0 current leak 和 10/12 有效率是否保持。

## 8. 2026-10-22 收束：字段/前科闭环、千问 S1、706 湖文本

> 本节是 10-22 追加；现行主文档：`CURRENT-STATUS-2026-10-22.md`。

- 字段/前科：`field_table.py` + S1 `prior_sentence_ids` + `--prior-refine` 已实现。37 条离线：37/37 建视图、target 37、outcome 0；8 条前科残余 8/8；22/26 旧前科可定位。12 条 qwen3.7：11/12；qwen 11 + DeepSeek 1 回退后 12/12、prior 11/12；2a14 旧假阳性被避开、86f1 找回；63ae zone 覆盖失败需 fallback。
- 千问：公网 DashScope 200，工作区 MaaS 403；qwen3.7-flash 官方 0.2/0.8（≤32K）；12 条 ¥0.075 vs DeepSeek ¥0.62。30 条 qwen 仅 11 条 pkulaw 成功，18 Arrearage + 1 timeout；30c 新 key 已完成 26/30；4 诊断（2 zone 覆盖 + 2 review outcome.type 非法），4 条 DeepSeek 回退。
- 706 湖文本：旧 pilot12 5/12 Arrearage，不能原地续（execution_settings_changed）；新根 `lake-text-706b-20261022` pilot12 12/12，pilot≥10 自动 4 shard 跑剩余 694，qwen3.8-flash。
- 909：仍 training-only；57 复议/26 前科/199 公示/M1 587 段/219 条坐标未修；新字段/前科视图尚未落到 909。
- 下一步：收 706b full（30c 已完成）；909 路由/重标；M1 坐标；S1 fallback/Arrearage 硬停/去 meta_fields；key 轮换。
