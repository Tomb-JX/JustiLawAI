# 解析层 v2 工程设计（详细版）：模型语义抽取 × 规则清理校验 × 定位通路

> 2026-10-17。承接《解析架构 v2》的方向判断，本文是可实施的工程设计：每个子问题先翻译成**标准工程问题**，给出**主流方案族**、**选型**、**置信度**与**匹配度分析**。所有设计以本项目的实测约束为输入，不引入未经论证的组件。
> **v2.1（2026-10-17）**：脱敏限制已取消（用户决策；规范文档的对应修订由协调层承接，本设计不代改规范）。主管线去掉预脱敏（六阶段→五阶段），定位链减少一级投影，标注证据直接绑定原文正本。修订明细见文末《修订记录》，对规范条款的影响清单见 §11。
> **v2.2（2026-10-18，协调层代笔）**：保留 v2.1 的 S0–S4 作为架构源头，但当前实现已分化为 **seg-v2 句表分区 + `element-ref-v2` 传输 + E-05 要素/绑定**，不再等同本节的 `seg-v1` JSON。新增 §1.1 实现映射、§3A 要素标签层（L5）、§9.1 实测状态、§10.1 执行状态；旧 S1 输出仅作设计历史参考。当前 `reference_elements=null`，字段准确率仍暂缺；绑定 v5 已做证据感知 3 步，但 212 切片无多人案例，655 review 为 unclassified role，joint 分支未验证。（此段为 v2.2 历史注记，当前见 v2.5。）
> **v2.4（2026-10-18，历史复跑）**：`60ebb52` 复跑 212 310/1517/518、P1 557/1519/513；scene-level money 把他人个人金额标 shared（P1 254/399、212 57/187）；该回归已在 `e06a0af` 修复，见 v2.5。
> **v2.5（2026-10-18，当前实现）**：S1 已是 **seg-v2 句表分区**——模型输入编号句表，输出 zones + 文书字段，**quote 由服务端从句表生成**，不再由模型写引文；S2 为 `locate.py` + `evidence_graph.py`（`evidence-graph-2`）；绑定 `e06a0af` 后 212 123/611/1611、P1 158/723/1708，money shared=0，`semantic_rules_approved=false`；L5 `reference_elements=null`；S3 26/299=8.7%；r7 未放行。BIND-03/BIND-04/BIND-05 未关闭。
> 硬约束（设计前提）：① 证据定位契约——五段必须是交付正本的连续子串，标注证据位置相对正本计算（data-spec §1）；② 可溯源——模型 id+提示版本+输入哈希全程可查；③ 确定性校验不得被模型输出绕过；④ 模型纪律——仅远程旗舰，禁本地小模型。（原 v2.0 的"远程模型调用不得接触未脱敏原文"隐私排序约束随脱敏取消移除。）

## 0. 现状问题的工程化翻译（总表）

| 我方问题（实测计数） | 标准工程问题 | 主流方案族 | 选型 | 置信度 | 匹配度 |
|---|---|---|---|---|---|
| 五段边界语义切分（定性句 132、边界 93、无锚点 357） | 文档结构分段（section segmentation） | LLM 结构化分段+引文锚定；LayoutML 族需要版面坐标（我们输入是压平文本）→ 排除 | 旗舰模型 + JSON Schema 约束输出 | 高（金标线 50 件评审已验证同形链路） | 高（p50=435 字、p99=3,397，页级即单调用） |
| outcome 未解析/变体（90+） | 信息抽取（IE）/结构化字段 | LLM 结构化输出（JSON Schema 强约束解码：OpenAI Structured Outputs；开源侧 outlines/xgrammar 族）+ Instructor 式 pydantic 校验重试 | Schema 约束 + 逐字段引文 | 高 | 高 |
| 人名脱敏 7 轮打地鼠 | ~~中文命名实体识别~~ **随脱敏取消退出主管线** | 外发衍生如需人名遮蔽：模型 NER（复用模型层基建）或现行规则，离线运行、独立定版 | 主管线关闭；衍生工具另行定版 | — | — |
| 导航/标签字/拼接尾（~200） | 样板噪声移除（boilerplate removal） | readability 族主内容提取的成熟化；我们输入已压平 → 规则模式表 + 位置映射 | 确定性清理注册表 | 高（可单测、可断言） | 高 |
| 表格续行/裸换行/空白 | 文本规范化 + 字符对齐（normalization with alignment） | 搜索索引的 char_filter 映射模式（Elasticsearch 一族）；单调映射复合 | 清理层产出 offset map（单调映射），全管线复合 | 高（既有投影实测 0 错位） | 高 |
| 日期倒挂/数额矛盾/法条-版本（~15） | 数据质量期望校验 | 期望套件（Great Expectations 族）+ schema 校验 | 校验注册表（从 parse_qc 15 项迁移为管线内阻断校验） | 高（已实测这些恰是规则可靠项） | 高 |
| 事件分组/家族碎裂 | 实体消解（entity resolution）：blocking + matching | blocking 键（文号）+ 规则匹配；ER 是成熟工程 | event_key 改文号优先 | 高 | 高 |
| 事实段边界无分母 | 金标准评测集 | 分层抽样 + 双人标注 + 一致性系数（CoNLL 式边界 F1） | 100–200 件人工标注 | 高（方法成熟；人力待定） | 高 |
| 引文幻觉风险 | 归因生成（attributed generation） | generate-then-verify：模型只给引文，代码逐字定位验证；e-discovery 的 fuzzy span alignment 兜底 | 引文定位（§4） | 高（确定性代码，结构性防幻觉） | 高 |
| 低置信/失败件 | 人机协同队列（HITL） | 不确定性采样 + 审阅队列（Label Studio 族）+ mask_review 显示辅助复用 | 失败分级 + 队列工具 | 高 | 高 |
| 版本漂移 | 数据/模型合同与溯源 | parser 字段记 `model@prompt`；prompt 注册；回归评测 | 版本治理（§7） | 中高（跨模型版本不可比，需评测回归护栏） | 高 |

> 注：上表“引文锚定”是 v2.1/seg-v1 的选择；现行 seg-v2 已改为**句表分区**，模型输出 `from/to` 句号区间，不写 quote。当前实现见 §1.1、§3。

## 1. 管线总览（五阶段 S0–S4）

```
parsed-1（原文态, 5,739件）
  S0 清理层   确定性：样板噪声移除、续行/裸换行归一、标签字剥离、空白归一
              产物：cleaned_text + offset_map（cleaned 位置 → 原文位置，单调映射）
  S1 模型层   seg-v2：cleaned_text → 编号句表 → 远程旗舰（T=0, JSON）
              输出 zones（run-length 句号区间）+ 文书字段（outcome/dates/review/articles…）
              ★ 模型不写 quote；区间对应句子的原文由服务端生成
  S2 证据层   locate.py：quote → cleaned/原文坐标（exact/ws/fuzzy）
              evidence_graph.py：小句 → money/count/time/behavior 候选节点 + E-05 归一化 + 绑定
              → 原文坐标＝交付坐标（交付正本即原文）
  S3 校验层   parse_qc 15 项迁移为管线内阻断校验 + schema/枚举/一致性/值-文对账
              通过 → parsed-2（模型态 parsed-1）；失败 → 重试一次（换模型）→ 低置信队列
  S4 人工     低置信队列审核（mask_review 显示辅助）+ 分段评测集标注（100–200件金标准）
```

**脱敏取消（v2.1 关键决策，2026-10-17）**：原 v2.0 将模型调用排在预脱敏之后（模型只见遮蔽文本）。该隐私排序随脱敏限制取消一并解除：主管线不再有预脱敏，模型直接处理清理后的原文。量化收益（数据源：《完全去掉脱敏的链路影响模拟》§2）：

1. **定位链三级投影减为两级**——五段坐标直接绑定交付正本，少一级投影＝少一类错位源；
2. **`text_sha256` 随上游 parse 冻结真正稳定**——"每次重建 42 件正文哈希漂移"消失，已冻结样本（试标、抽检）不再被脱敏规则迭代作废；
3. **脱敏伪影类缺陷整类消失**——伪影人名（姓+代号截断）、别名撞号（乙5 类）、ambiguous_persons 265 / subject_variants 585；
4. **7 轮脱敏打地鼠（22 规则 / 16 处事故注释）与 R6 白名单维护停止**。

要求脱敏的规范条款（text-processing-spec §4.2/§4.3 与冻结点、data-spec §1.1/§1.3/§1.6/§4、sota-gates R6、data-collection 三原则与 §4 SOP）由**协调层承接修订**，本设计不代改规范；设计侧依赖变化见 §11。`deid.py` / `r6_scan.py` 降级保留：转为**外发衍生可选工具**（离线、独立定版），不再是交付门禁；`build.py` 的 deid_case 调用与 `_` 前缀内部字段剥离自 r6 构建起移除。

### 1.1 2026-10-18 实际实现映射

> 本节把 v2.1 的设计阶段对应到当前代码/产物；旧 `seg-v1` JSON 不是当前实现。

| 设计阶段 | 当前实现 | 产物/状态 |
|---|---|---|
| L1 parsed-1 | 原文、事实/当事人段、坐标 | `parsed/<来源>/<批次>/records.jsonl`；r6 主文件 1,695/785 事件 |
| S0 清理 | `cleanse.py` + `replay_edits`；cleaned_text + offset | `unified_raw` 的 edits；回放可重建 |
| S1 模型分区 | **seg-v2**：句表 + run-length zones；模型只给 `from/to` 句号，服务端从句表生成 quote/坐标；`run_seg.py`；公示族 `zones_det` 确定性分区 | `s1_runs/seg-v2-*`；final300 299/300 成功、zones 铺满违例 0；`element-ref-v2` 是传输版本，不是 `element-v2` 本体批准 |
| S2 定位/证据图 | `locate.py` + `evidence_graph.py`；quote → 原文坐标；小句 → money/count/time/behavior 候选节点；`evidence-graph-2` | 候选图/证据；当前绑定 `e06a0af`：212 123/611/1611、P1 158/723/1708；money shared=0；无独立准确率；BIND-03/BIND-04/BIND-05 |
| S3 校验 | `s3.py`/`run_checks`；S3 硬失败 26/299=8.7% | parsed-2 候选；r7 要求 <5% |
| L5 要素标签 | 7 组 36 要素字段；`CaseMeta` 3 元数据（非标签）；教师 `element-teacher-v1` 只输出 elements；A/B/C 仲裁；binding 是派生块 | **`reference_elements=null`**；无字段准确率 |
| 交付 | r6 可用；r7 未放行 | r6 是格式/原文参考，不是标注底料 |

**边界**：S1 的文书字段（outcome/subject/dates/review/gambling）仍供 S3/装配；segments 由 zones 从句表生成，不再是模型引文。要素标签与绑定见 §3A，不在 S1 一次调用里完成。

## 2. S0 清理层（确定性）详细设计

- **输入**：parsed-1 的 `text_full`（原文态）。
- **规则注册表**（有序、可单测）：导航样板模式（"首页>专题专栏"、面包屑残句、走进X）、管道/裸换行续行归一（现 CELL_WRAP 的泛化：管道型 + 短片段裸换行）、字段表标签字剥离（"事由/处罚类别/案件名称"等 LABELS 词与单字残片）、空白/全角归一。
- **核心数据结构**：`offset_map`——单调数组 `cleaned_pos → orig_pos`（每个保留字符一个映射；删除段不映射）。所有下游位置先记 cleaned 坐标，投影回原文由 map 完成；映射本身是纯函数，**单测可穷举**（对每条断言 cleaned[c] == orig[map[c]]）。
- **置信度：高**。纯确定性、逐条可断言；同型映射（三段投影）已在现网 2,267 件实测 0 错位。
- **失败模式**：规则误删正文片段——对策：删除类规则白名单化（只删命中导航模式/纯标签字的 span），并保留删除审计（删除 span 与原因入 extra）。

## 3. S1 模型层详细设计（当前：seg-v2 句表分区）

> v2.1 的“模型输出五段引文 + S2 定位引文”已被 seg-v2 取代；旧 seg-v1 只作历史设计参考。当前实现以 [s1.py](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/research/discretion/unify/s1.py)、[run_seg.py](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/research/discretion/unify/run_seg.py) 和 [cleanse.sentence_table](D:/02_Dev/Projects/大创/.claude/worktrees/seg-v2-design-review/research/discretion/unify/cleanse.py:149) 为准。

### 3.1 输入：cleaned_text → 编号句表

- S0 产出 `cleaned_text` + offset；S1 先调用 `sentence_table(cleaned)`，按句末标点/换行切成 cleaned 坐标的 `[[start,end], ...]`。
- 模型实际看到的是：

```text
[form] 叙述式-独立成篇 | [source_type] 处罚决定书 | 共 18 句
[本人] 本案当事人：沈xx；outcome 各值只填本人的处罚……
句表：
[S1] 经查，沈xx……
[S2] 2022年5月16日中午……
...
```

- 模型不拿原文坐标；句子 ID 是唯一锚点。`run_seg.request_for()` 会校验记录里的句表与当前 `sentence_table()` 完全一致，防止切句版本漂移。
- `[本人]` 是目标参数：多人并载页用它定位本人；它不泄漏答案，和 M1 `extract(target=…)` 同构。
- **形态分治**：字段表公示/标题汇总等形态由 S0 模板规则生成 `zones_det`；提示会删掉分区指令与 zones 示例，模型只抽字段，输出后再用 `zones_det` 覆写分区。约 2,000+ 件走这条路，不靠模型猜分段。

### 3.2 输出：zones + 文书字段

模型不再输出 quote，只输出 **run-length 句号区间** + 文书级字段：

```json
{"zones": [
  {"type": "facts", "from": 1, "to": 14},
  {"type": "reasoning", "from": 15, "to": 16},
  {"type": "decision", "from": 17, "to": 18}
],
 "subject": {"mention": "沈xx", "aliases": []},
 "outcome": {"type": "罚款", "detention_days": 0, "fine": 500, "...": "..."},
 "dates": {"behavior": "2022-05-16", "decision": "2022-05-17"},
 "review": {"result": "无", "changed_outcome": null},
 "gambling": {"verdict": "是", "reason": "…"},
 "confidence": "high"}
```

**zones**（6 类）：`facts`（违法事实，只写行为事实）、`evidence`（证据列举）、`reasoning`（认定理由/裁量/定性结论）、`decision`（处罚决定、依据、执行）、`review`（复议/诉讼审查）、`meta`（案件名称/文号/日期栏/当事人栏等）。设计上说的“五段”是前五类；实现多了 `meta`。zones 必须首尾衔接、完整铺满 `[S1..SN]`，无缝隙、不重叠。

**quote 设计**：模型只给 `from/to`；服务端从句表取对应句子的原文，段落的 quote 由代码生成，段证据取区间首尾句。模型不可能编引文，只能把句子 ID 编错，而 ID 错误会被 `validate()` 抓住并触发反馈重试。L5 要素教师的 evidence quote 是另一层：教师给短引文，S2 做逐字定位校验，不要与 S1 的“取消 quote”混为一谈。

**文书字段**：

| 字段 | 类型/枚举 | 说明 |
|---|---|---|
| `subject.mention` / `aliases` | string / string[] | 本人原写法与其他写法 |
| `outcome.type` | **7 值**：不予处罚 / 不构成违法 / 警告 / 罚款 / 拘留 / 拘留并处罚款 / 移送刑事 | 处罚结论，来自 decision 段 |
| `outcome.detention_days` / `fine` | int / number | 拘留天数、罚款金额 |
| `outcome.not_executed` | 是/否 | 是否未执行 |
| `outcome.multi_violation` / `executed_penalty` | bool / object | 多违法行为与合并执行总额 |
| `outcome.confiscation` / `detention_items` / `stated_circumstances` | array | 没收、拘留事项、明示情节 |
| `outcome.articles` | `[{text, edition}]` | 法条原文 + `2012修正/2025修订/未知` |
| `dates.behavior` / `dates.decision` | `YYYY-MM-DD`/null | 行为日期、决定日期 |
| `review.result` | 维持/变更/撤销/确认违法/程序驳回/无 | 复核结论 |
| `review.changed_outcome` | object/null | 变更后的处罚 |
| `gambling.verdict` / `reason` | 是/否/待定 + string | 是否赌博案件 |
| `confidence` | high/low | 模型自评 |

`validate()` 当前校验：zones 铺满与衔接、`outcome.type` 枚举、`gambling.verdict`、`review.result`、`confidence`；`run_seg` 另校验 outcome 数值非负/有限。值-文对账（罚款、拘留、日期、法条条号）在 S3 的 `check_value_grounded` 中做。

### 3.3 调用形态

- 每记录一次调用；temperature=0；`response_format=json_object`；提示版本 `seg-v2`。
- 重试：同提供商 1 次 → 换提供商 1 次；结构错误会把违例回灌到下一次提示；熔断与预算按提供商独立配置（deepseek max_tokens 12000/timeout 240s；bailian 6000/120s 等）。
- 当前主/备：deepseek-flash 主、qwen3.8-flash 备；模型纪律仍是远程旗舰，本地小模型不参与生产。

### 3.4 当前分段质量（开发性，不是正式验收）

- **调用层**：final300 299/300 成功（289 一次过、10 二次、1 超时）；zones 铺满/不重叠违例 **0**；1,383 个区间，平均 4.63 段/件。
- **结构收益**：seg-v1 的 coverage 51 件、facts 尾定性 35 件在 seg-v2 中降为 0（结构保证 + 边界 snap/兜底）；这是接口变更的直接收益。
- **硬失败**：S3 26/299 = **8.7%**，仍高于 <5% 门。残余：facts 区间缺失 15、类型矛盾 10、decision 缺 5、subject 疑幻觉 2、值无据 2；形态上叙述式-独立成篇 18、字段表公示 6、混合 2。公示族已由确定性分区接管，剩余主战场是叙述式。
- **边界 F1（注意分母）**：这是“模型 vs parse.py 正则”，不是“模型 vs 人工金标”：
  - final300：facts 0.768 / decision 0.487 / evidence 0.975；
  - spec50（xiaomi-pro）：facts 0.769 / decision 0.393；
  - seg-v2 pilot（混合模型）：facts 0.620 / decision 0.533。
  facts 边界跨模型稳定（0.768 vs 0.769，±0.001）；decision 是最低、最不确定的段，正则只取“结果部分”、模型给“依据+结果+执行”的完整块，口径不同，F1 低有构造性成分。**人工标注的 100–200 件五段边界评测集仍未做**，所以不能把这些 F1 当分段准确率。
- S1 质量直接决定 L5 输入：facts 缺失/decision 误分会变成要素教师的输入错误；当前 L5 `reference_elements=null`，字段准确率仍未测。

### 3.5 为什么 S1 与 L5 要素教师分开

| | S1 seg-v2 | L5 要素教师 |
|---|---|---|
| 输入 | 全文编号句表，**含 decision/review** | 只给 target + facts/meta 视图，**不含 decision/reasoning/review** |
| 输出 | zones + 文书级字段（outcome/dates/review/articles） | 36 个要素字段 + 每字段证据 |
| 粒度 | 文书/段落 | 人/字段 |
| 目的 | 解析结构、抽处罚结论和元数据，构造 facts/meta 视图 | 产出 M1/M4 的参考标签 |
| 质量指标 | 边界 F1、S3 硬失败率、结构覆盖 | 字段准确率、A/B 一致性、证据命中率 |
| 泄漏风险 | 必须看 decision 才能抽 outcome | 不能看 decision，否则可能从处罚反推要素 |

核心是**输入可见性**：S1 必须看 decision 才能抽 `outcome.type`、法条和执行方式；L5 教师如果看 decision，就可能从“拘留十日”反推 `profit_purpose` 或 `role`，把处罚结论泄漏进要素标签。要素标签必须只来自事实。其次，两者粒度/输出/质量分母不同，分开才能定位是分段错了还是要素抽错了。再次，S1 每份文书一次解析调用，L5 是标注阶段 A/B/C 盲标调用，输入、输出、阶段都不同，不是重复调用。

## 3A. 要素标签层（L5，2026-10-18 补）

> 解析/分区只把文书变成可用输入；**标签**是另一层。当前项目最大的缺口在这里，不在解析。

- **字段**：7 组 **36 个要素字段**；`CaseMeta` 的 `region`/`behavior_date`/`decision_date` 是 3 个记录级元数据（登记/来源，教师不输出，不是第 37–39 个要素）；`binding` 是派生标注，不是字段。唯一来源 `schema.py`/`element_labels.py`。一人一条记录；`input` 只放 facts/meta 视图与 target/aliases，不能放 decision/reasoning/review/outcome。
- **标签形状**：每字段 `{status, value, evidence}`；`status`=明确/推断/未提及；金额 `{min,max}`；日期 ISO；证据 `{quote,start,end}` 必须逐字命中且只来自 facts/meta。
- **教师**：`element-teacher-v1` 只回 `elements`，不输出 binding；A/B 双盲 + 非 DeepSeek C 仲裁，产物 `model-adjudicated`、`human_review=false`，不计人工真值。
- **绑定**：`binding` 是后处理派生标注（`shared_fact`/`target_specific`/`needs_review`），不是要素字段；引擎 `binding_rules.py` 只定语义（8 shared/28 target），具体判定由后处理实现。当前代码 `e06a0af`：212 单人 123 shared/611 target/1611 review；P1-r6 178 条 158/723/1708；shared 全部是 count（`participant_count`/`unclassified_count`），money 的 shared 为 0；money 大量进入 review（212 1032、P1 1085），time 也多为 review。`field_accuracy=null`、`semantic_rules_approved=false`，契约 `binding_policy=proposed_pending_engine_adoption`。规则版语义归属已按 **B-10** 冻结（语义归属不得用规则实现，规则只做格式/证据/归一化校验）；**BIND-03/BIND-04/BIND-05 未关闭**。130/130 无落盘 artifact，不能作为准确率。
- **验收**：schema/枚举/版本、证据逐字/坐标/来源、target 可定位、无 decision/reasoning/outcome 泄漏、金额/日期合法、`reference_elements` 非空、字段覆盖率、绑定小样本准确率、A/B 或人工复核。完整格式见 [data-spec §8](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/data-spec.md) 与 [annotation-guideline §3.11](D:/02_Dev/Projects/大创/.claude/worktrees/discretion-engine/docs/05-research/annotation-guideline.md)。
- **当前状态**：`reference_elements=null`；L5 标签为 0；M1 字段准确率暂缺；M4 只能用历史处罚做基线；r7 未放行。当前 12 件烟测的 21 条证据有 20 条定位成功（95.2%），但字段准确率仍未测。

## 4. S2 定位与候选证据图（当前：`locate.py` + `evidence_graph.py`）

> 当前 S2 不是单一的“引文定位”，而是两段：`locate.py` 负责 quote → 原文坐标；`evidence_graph.py` 负责小句 → 候选证据节点 + 归一化 + 绑定。最新代码 `e06a0af`，图版本 `evidence-graph-2`。

### 4.1 `locate.py`：quote → cleaned 坐标 → 原文坐标

- `OffsetIndex` 从 S0 的 `edits` 建 clean↔orig 双向映射；坐标是 Python 字符、0 起、左闭右开。`span()` 投影 clean 区间；`project()` 返回连续原文片段，**不会重新引入 S0 删除的字**；`crosses_boundary()` 标记删除边界。
- `locate()` 三级：
  1. **exact**：`cleaned.find(quote)`，唯一 → `exact_unique`；多处 → `exact_multi`（记录全部命中，交上下文消歧）。
  2. **ws**：双方去空白后匹配，唯一/多处 → `ws_unique` / `ws_multi`。
  3. **fuzzy**：引文前 10 字锚点 + `difflib` 最长连续公共块；块长 ≥60% 才采纳，返回 `fuzzy_unique` 并标 `note` 进审计；不足 60% 直接 `fail`。
- `SourceSpan` 强类型：`text_sha256 + start + end + quote`，构造与 `verify()` 都要求 `text[start:end] == quote`；坐标系统一 `original-python-char`。
- 当前主路径的保守点：`run_elements.locate_evidence` 只在允许区间内做**唯一精确匹配**，找不到就拒收；三级 `locate()` 已实现并有单测，但还不是教师证据的默认兜底。`build_graph` 直接用 S1 视图区间，不经过 `locate()`。

### 4.2 `build_graph()`：候选证据图

- 输入：原文、允许视图（facts/meta 等）、target、aliases、event_id。先校验 target/aliases 在原文、每个 view 的 `start/end/text` 与原文一致，否则报错，不凑坐标。
- 每个 view 按 `。；;\n` 和不在数字之间的逗号切小句；每句抽 `money` / `count` / `time`；小句含 target 时额外生成 `behavior` 节点。
- 每个节点带：`id`、`kind`、`source_ref`（原文坐标+哈希+quote）、`clause_ref`、`sentence_ref`、`target`、`subject_refs`、`event_id`、`event_kind`、`value_role`、`binding`、`reason`、`normalized`、`semantic_approved=false`。
- `value_role` 由金额前最近的角色关键词决定（本人/携带/持有/赌资、现场赌资合计、抽头/台费、违法所得等）；count/time 另有规则。`event_id` 优先用记录值，否则按小句 span+kind 生成；joint（分别/各自/与/和/伙同/、/等N人）会标 `joint_or_indirect_subject`。
- 金额/日期走 E-05 归一化：开口金额不补上界，近似值不静默变精确；count 保留区间/未知。
- **结构限制**：`subject_refs` 只记录 target/aliases，没有其他人物实体；没有跨句代词消解；event_id 可能按小句碎片化；没有形成完整的 mention→amount→event→person→role 链。

### 4.3 绑定与消费

- 引擎 `binding_rules.py` 只定语义（8 shared / 28 target）；`classify_graph_bindings` 做字段语义 → 证据主体 → 决策。当前 `e06a0af` 已删除“现场查获/现场扣押整段标 shared”的捷径；目标专属字段若小句未出现 target，一律 `needs_review`；金额多人列表 → `needs_review`；shared 字段（count 等）才标 `shared_fact`。
- 当前分布：212 123/611/1611；P1-r6 158/723/1708；shared 全为 count，money shared=0，money 大量 review；`field_accuracy=null`、`semantic_rules_approved=false`。
- `resolve_binding` 只接受 `target_specific` / `shared_fact`，并核对 target、event_id、value_role 与证据区间；`lexical_candidate` 不再接受；penalty/review 事件不能当 behavior 证据。
- 规则版语义归属已按 **B-10** 冻结：规则只做格式、证据逐字、来源视图、归一化校验；`shared/target/review` 的语义判断由教师模型在抽取时完成，或由模型化/混合组件完成。当前绑定是保守隔离器，不是已验收的语义归属。
- 测试：`research/discretion/unify/tests` 当前 **144 passed**；`test_locate.py` 覆盖 exact/ws/multi/删除边界/fuzzy/短引文；`test_engineering_completion.py` 覆盖同数不同人、joint 未决、scene 词不得把他人赌资标 shared、未分类金额 review、契约/resolver 一致、E-05 归一。

## 5. S3 校验层（规则的新角色）

- **迁移**：parse_qc 的 15 项检查从“交付后 QC”迁为管线内阻断校验——同一套注册表两个挂点（管线内阻断 + 交付后抽检），口径统一。
- **seg-v2 后的校验重点**：zones 铺满/不重叠已由结构保证，S3 不再做 quote 覆盖度；保留 schema/枚举、outcome 内部一致性（类型↔数额↔法条↔版本注解）、日期顺序、event_key（文号优先）、facts 质量、decision 存在性、subject 一致性与值-文对账（`check_value_grounded`：罚款/拘留/日期/法条条号）。
- **当前实测（final300）**：S3 pass/warn/error = 121/152/26，硬失败 **26/299=8.7%**，仍高于 r7 的 <5% 门。26 件含 34 条 error：facts_quality 15、outcome_consistency 10、decision_present 5、subject 2、value_grounded 2；另有 72 个输入/契约拒收，可与 S3 错误重叠。
- **失败处置**：硬校验失败 → 换旗舰重试一次 → 低置信队列（人工）；软校验（疑级）→ 标记入库不阻断。错误件重试带结构反馈；错误类别按 `facts/outcome/decision/subject/value` 落账，不用“整体通过率”掩盖。
- **置信度**：确定性校验本身可靠；但 S3 通过不等于要素标签准确，也不等于绑定正确。当前 r7 未放行。

## 6. S4 人工角色

1. **分段评测集**（100–200 件，分层：叙述式/字段式/表格/OCR 按实占比）：人工标五段起止；交付边界 F1 作模型 vs parse.py 的切换判据。**标注直接在原文正本上进行**——不再有"先脱敏、再冻结、再标注"的顺序约束，证据位置一步绑定，标注规范本线先出草案，标注平台走 Label Studio 族（或最小化：结构化表格 + mask_review 显示辅助）。
2. **低置信队列**：mask_review 复用为可选显示辅助（原为脱敏取证基建，随取消降级为阅读遮蔽工具）；队列量预估 = 校验失败率 × 全量（pilot 先测）。
3. **主动采样**：按模型 self-confidence=low 与校验告警密度优先抽样（不确定性采样，标准做法）。
4. **金标回退重基线**：33 件金标回退中 A/F 两类（脱敏伪影、隐私泄漏）随取消整类关闭，仅需处理解析类回退（B/C/D/E）；正式金标计数仍为 0，切换文本基座无已签署标注需要迁移。

## 7. 版本治理与溯源

- `parser` 字段升级为 `parse-v2|model:deepseek-flash|prompt:seg-v2|clean:v1`（四元组入库）；S2 另记 `evidence-graph-2`；每个 prompt/模型/图版本变更 = parser 版本变更 = 必须过评测集回归。
- 评测集本身版本化（标注人、日期、一致性系数）；变更清单（候选 D）继续：**解析与清理改动分开定版**；"privacy 定版维度"随脱敏取消不再是交付版本化维度（外发衍生工具如启用，另行独立定版）。
- 模型输出缓存：以"输入哈希 + 模型 + 提示版本"为键（与发现层缓存同模式），重跑不重复付费。v2.1 附带收益：输入哈希基于原文，不随脱敏规则漂移，缓存命中率提升。

## 8. 成本与吞吐（量级，准确价格以各控制台为准）

- 全量回填：5,739 件 × 1 调用（输入≈原文正文+提示 ≈1–2k token、输出 ≈0.5k）；周增量数百件。金标线 50 件三模型评审已实跑通该量级与形态。
- 吞吐：顺序+并发（限速按服务商配额），全量回填按小时计。
- 双轨期成本：parse.py 兜底路径保留，模型层只对增量+回填各跑一轮。

## 9. 风险与待测项（诚实清单）

| 待测项 | 现状 | 首测方式 |
|---|---|---|
| 一次通过率 / zones 结构 | final300 299/300 成功；铺满/重叠违例 0 | 已测；结构覆盖不再是主要风险 |
| 分段边界 vs 人工金标 | **未测**；现有 F1 是“模型 vs parse.py 正则” | 100–200 件人工标五段起止；边界 F1 |
| facts 区间缺失 | final300 15 件；叙述式为主 | 错误件反馈重试 + 形态分治；逐件定性 |
| decision 归属歧义 | final300 F1 0.487；spec50 0.393 | 5–10 件人工定性；明确“依据+结果+执行”边界 |
| 旗舰对 OCR 噪声的容错 | 未测 | OCR 件单独分层统计 |
| 长文单调用时延 | final300 1 件超时 | 按 provider 参数与输入长度分层统计 |
| 原文人名形态多样（真名/王某某/张某并存）对 subject 归一的影响 | 未测（v2.0 用脱敏别名回避） | pilot 统计 subject 一致率与 aliases 召回 |
| 跨模型版本可比性 | 行业已知问题 | parser 版本冻结 + 评测集回归门 |

### 9.1 2026-10-18 实测状态（开发性，不是正式验收）

| 项 | 当前 | 说明 |
|---|---|---|
| 开发切片 | 212 条/121 事件 | manifest `5010f077…`；298 来源/86 剔除 |
| S1 final300 | 299/300 成功；1,383 区间/4.63 段；铺满违例 0 | 289 一次过、10 二次、1 超时；结构覆盖已保证 |
| S1 边界 F1 vs 正则 | facts 0.768 / decision 0.487 / evidence 0.975 | **不是人工金标**；spec50 facts 0.769 / decision 0.393；decision 口径歧义待定性 |
| S3 硬失败 | 26/299=8.7% | r7 要求 <5%；facts_quality 15、outcome 10、decision 5、subject 2、value 2 |
| M1 诊断 | 64 条；丢弃 59/406=14.5% | 本地学生零样本；字段准确率暂缺 |
| M2 默认档位内 | 166/176=94.3% | 10 条例外有解释；不修改历史处罚 |
| M4 B4 | 35.94% vs 多数类 42.19% | 罚款 F1=0；负结果 |
| binding 当前代码 `e06a0af` | 212：123/611/1611；P1-r6：158/723/1708 | shared 全为 count，money shared=0；money 大量 review；`field_accuracy=null`、`semantic_rules_approved=false`；BIND-03/BIND-04/BIND-05 open |
| L5 标签 | `reference_elements=null` | 未产标签；12 件烟测 21 证据/20 定位；字段准确率/蒸馏被阻塞 |
| r7 | 未放行 | S3>5%；正式门禁未过 |

## 10. 实施排期

| 阶段 | 内容 | 依赖 |
|---|---|---|
| W1 | S0 清理层实现+单测（映射穷举断言）；评测集标注规范草案 | 无 |
| W1–W2 | 评测集标注（100–200 件，直接在原文正本上）；pilot 100 件模型层实跑（zones 结构/一次通过率/边界 F1 首测） | S0、API 额度 |
| W2–W3 | S1/S2/S3 管线化（schema 约束、定位、校验迁移）；双轨对比报告 | W1 pilot |
| W3–W4 | 达标则切主：parsed-2 全量回填 + build --diff-against 变更清单 + **r6 发布＝首个原文正本交付**（r1–r5 不可变保留、正文哈希不迁移；正式金标计数为 0，此刻切换文本基座成本最低） | 双轨达标 |
| 并行 | 金标回退闭环：A/F 类随取消关闭，B/C/D/E（解析类）按断点文档继续，不受影响 | 无 |

> 与旧"修正计划"的关系：批次 1 的正则重对齐项**降级为 S0 清理层的实现细节**；批次 0/2/3 原样保留；批次 4 的评测集升级为"双轨切换判据"；批次 5 架构批并入本设计 S0/校验器模块。

### 10.1 执行状态（2026-10-18 13:56）

- r6 已交付（1,695/785）；r7 未放行；开发切片 212/121 已冻结。
- S0–S3 已跑通；S1 已是 seg-v2：final300 299/300 成功，zones 铺满违例 0；S3 硬失败 26/299=8.7%，残余 facts 缺失 15、类型矛盾 10、decision 缺 5、subject 2、值无据 2。
- S1 边界 F1（vs 正则，不是人工金标）：facts 0.768 / decision 0.487 / evidence 0.975；人工五段评测集仍未做。
- 绑定已到 `e06a0af`：212 123/611/1611；P1-r6 178 条 158/723/1708；money shared=0；`semantic_rules_approved=false`，契约 `proposed_pending_engine_adoption`；规则版语义归属按 B-10 冻结，BIND-03/BIND-04/BIND-05 未关。
- L5 标签仍为 0（`reference_elements=null`）；12 件烟测 21 证据/20 定位（95.2%），字段准确率未测。M1/M4/蒸馏都等 L5。
- 无新付费调用；付费烟测需 I-21 六道门。

## 11. 规范联动影响清单（交协调层修订，本设计不代改规范）

> 本线只维护设计侧依赖；下表供协调层修订规范四件时对齐，避免设计与契约口径漂移。

| 规范条款 | 现行内容（要求脱敏） | 取消后的方向 |
|---|---|---|
| text-processing-spec §4.2 替换规则表 | 12 类替换（本人→甲、证件/电话/门牌删除、日期到月等） | 降级为"外发衍生可选层"，主管线不执行 |
| text-processing-spec §4.3 与 §11 | R6 两次扫描、零命中才通过；r1 漏网事故记录 | R6 降级为外发前扫描记录项，非交付门禁 |
| text-processing-spec 冻结点条款 | "先脱敏、再冻结、再标注"；冻结正本=脱敏后文本 | 冻结正本=原文；标注证据直接绑定原文 |
| data-spec §1.1 | `deidentified` 必须为"是"、`r6_scan` 未通过不交付 | 字段改为原文态声明 / 外发记录项 |
| data-spec §1.3 / §1.6 | 正本=脱敏后文本；`subject_alias` 固定"甲"；正文文号→哈希、日期到月（D2/D3） | 正本=原文；本人保留原写法（`subject_mention`）；文号/日期粒度随 D2/D3 重议 |
| data-spec §4 验收 | `deidentified`=是、r6 通过、隐私硬命中 0 为批次检查项 | 相应检查项移除或转为外发检查 |
| sota-baselines-and-gates §8 R6 | "个人信息泄漏扫描命中=0"为任何阶段红线 | 改为对外发布/交付红线（数据集出项目时），项目内不阻断 |
| data-collection 三原则与 §4 | "先合规再采集（脱敏 SOP 与协议先行）"；原料"须先脱敏（D1–D5 拍板后）" | 合规原则保留"协议先行+台账溯源"；脱敏 SOP 转为外发 SOP |

## 12. 当前阻塞在设计中的位置（2026-10-18 13:56）

> 结论：主要卡点在 **L5 标签 + S3**。S1 已从“结构覆盖”问题转为 **叙述式 facts 缺失/decision 归属**；绑定不再是 Gate B 主阻塞，按 B-10 降为数据质量 guard。M1/M4 是 L5 的下游；r7 是独立的 S3 发布门。

| 设计位置 | 卡点 | 证据 | 阻塞的下一环 | 解除条件 |
|---|---|---|---|---|
| L0–L3 原文/解析/交付 | 基本通 | r6 1,695/785；开发切片 212/121；P1-r6 178 | r7 仍需 S3 | S3 <5% + 正式门禁 |
| S0 清理 | 无 | `cleanse.py`/replay edits | — | — |
| S1 分区 | **叙述式边界/事实缺失** | final300 299/300；铺满违例 0；S3 8.7%（facts 缺 15、类型矛盾 10、decision 缺 5）；边界 F1 vs 正则 facts 0.768/decision 0.487 | L5 输入、r7 | 人工五段评测集；facts 缺失/decision 定性；S3 <5% |
| S2 定位/证据图 | **绑定质量未证；规则版已冻结** | 当前代码 `e06a0af`：212 123/611/1611；P1 158/723/1708；money shared=0；无独立准确率；BIND-03/BIND-04/BIND-05 | L5 标签 | 按 B-10 改教师/模型化归属；100–200 标注 + A/B；不再加规则 |
| S3 校验 | **r7 门** | 26/299=8.7% >5% | r7 | S3 错误分类 + <5% |
| L5 标签 | **主阻塞** | `reference_elements=null`；无教师批次；字段准确率暂缺 | M1 字段准确率、M4 要素特征、蒸馏 | 标签契约 + 12/36/200–300 批 + 独立验收；I-20 |
| M1 | 等 L5 | 64 诊断；59/406 丢弃；准确率暂缺 | — | L5 标签 |
| M2 | 可用 | 166/176=94.3%；10 例外 | — | 法律组确认例外（不阻塞开发） |
| M4 | 等 L5 | B4 未超多数类；罚款 F1=0 | — | L5 要素特征 |
| M5/M6 | 未实现 | — | 后续 | 不在首跑前置 |
| 契约层 | **未采纳 + 规则版冻结** | `accept_in_resolve` 已与 resolver 一致（`target_specific`/`shared_fact`）；`binding_policy=proposed_pending_engine_adoption`、`semantic_rules_approved=false`；规则版语义归属违反 B-10 | L5 生产 | 引擎采纳/拒绝契约；模型化归属；CONTRACT-01/BIND-05 |
| 付费/发布 | 门禁 | 无新付费批；r7 关门 | 全量/r7 | I-21 六道门 + S3 |
| 协调/可见性 | 流程 | PUSH/DOC/SCOPE | — | 推送/归档/事件登记 |

**关键区分**：212 开发切片是单人案卷；P1-r6 才是多人绑定样本（178 条/186 个多人 behavior）。两边都还没有标注准确率；当前 review 主要是 `unclassified role: None` 与多人列表；scene-level money 回归见 BIND-04。

> 当前计数来自 `e06a0af` 的落盘诊断（`diagnostics-bind-fix-dev212-20261018-codex` / `diagnostics-bind-fix-p1-20261018-codex`，`field_accuracy=null`、`release_approved=false`）。`60ebb52` 的 310/1517/518 与 557/1519/513 是历史复跑（scene 回归），`3d05914` 的 123/1567/655 与 158/1570/861 更早；引用时注意版本。

## 修订记录

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v2.0 | 2026-10-17 | 初版：六阶段 S0–S5（含 S1 预脱敏），隐私排序=模型只见预脱敏文本 | 模型组（引擎） |
| v2.1 | 2026-10-17 | 脱敏限制取消（用户决策）：删 S1 预脱敏（六阶段→五阶段）；定位链去 deid 投影（③ 直达交付坐标）；标注直接绑定原文正本；deid.py/r6_scan.py/mask_review 降级为衍生/辅助工具；金标回退 A/F 类整类关闭；新增 §11 规范联动清单（规范修订由协调层承接）；新增 §9"原文人名形态"待测项 | 模型组（引擎） |
| v2.2 | 2026-10-18 | 补当前实现映射：seg-v2 句表分区、`element-ref-v2`、E-05 要素/绑定 v4；新增 §1.1、§3A L5 标签层、§9.1 实测状态、§10.1 执行状态；旧 `seg-v1` JSON 仅作历史设计 | 协调层代笔（引擎线复核） |
| v2.3 | 2026-10-18 | 补 v5 证据感知 3 步与 P1-r6 多人绑定（178 条/186 节点，158/1570/861）；新增 §12 当前阻塞在设计中的位置（L5/绑定为主阻塞，r7 独立门） | 协调层代笔（引擎线复核） |
| v2.4 | 2026-10-18 | 独立复跑 `60ebb52`：212 310/1517/518、P1 557/1519/513；登记 scene-level money 回归（P1 254/399、212 57/187）与 BIND-04；字段表述改为 36 要素 + CaseMeta 3 元数据 + binding 派生块 | 协调层代笔（后处理线复核） |
| v2.5 | 2026-10-18 | 按当前实现重写 S1/S2：S1 改为 seg-v2 句表分区（模型不写 quote，服务端生成；6 类 zones + 文书字段；7 值 outcome；zones_det 公式；final300/S3/边界 F1 实测）；S2 改为 `locate.py` + `evidence-graph-2`（三级定位、候选图、绑定约束、B-10）；更新 §9.1/§10.1/§12 与修订记录 | 协调层代笔（后处理线复核） |
