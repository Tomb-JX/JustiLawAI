# seg-v2 问题到工程方案的映射与开源选型（2026-10-18）

> 接续 [独立设计评审](./seg-v2-design-review-2026-10-18.md)。本次只补工程拆解、官方资料调研及本机合成探测，写在同一评审分支；未安装新依赖、未改生产代码或数据、未付费调用。下列 EP 编号是可移交的工程任务，不是已经创建的外部工单。

**结论：把现链路拆成“定位原文事实 → 绑定主体与事件 → 类型化解析 → 业务规则投影 → 验证与组装”。** 中文日期、数字、金额不应由模型自由生成规范值；优先复用中文解析库，模型保留在分区、事件关系及语义归类等确实需要理解的地方。库的输出还须经过项目适配器，不能直接覆盖现有 schema。

“主流”在这里指已有通行工程模式与公开实现，不是经市场占有率统计得出的排名。库能力按官方仓库、官方文档或作者测试核查；项目适配、任务划分与采用顺序是本评审的判断。没有本地运行的候选明确标为待验证。

## 1. 先把问题改写成能开发、能验收的任务

| 评审问题 | 具体工程问题 | 主流解决模式 | 本项目任务 |
|---|---|---|---|
| F1：模型回了 JSON，却不符合字段契约 | JSON 语法有效与业务 schema 有效混淆；生产和验收没有共享可执行请求契约 | Schema-first、严格类型验证、受限输出/工具参数、验证失败定向重试 | EP-01 契约编译与 provider 适配 |
| F2：缺字段被补成未提及 | 内容状态与执行状态混用 | 显式状态机、带判别字段的联合类型、无效结果隔离 | EP-02 结果状态与合并边界 |
| F3：原文切片混用了两套偏移 | 多坐标空间缺少类型边界、半开区间约定被破坏 | 带坐标系的 span、单向映射、性质测试 | EP-03 坐标与证据编译 |
| 日期、年龄、前次处罚时间不稳定 | 时间实体识别、时间指代、日期规范化被塞进同一个字符串 | 中文时间解析器＋显式参考时间＋保留粒度的时间对象 | EP-04 时间归一化与锚点解析 |
| 大写金额漏检、范围被当确数 | 数字解析、单位换算、区间语义及金额角色未分层 | 中文数字/金额解析器＋Decimal＋比较关系 AST | EP-05 数额及计数归一化 |
| F6：全文有同一个数字就算有据 | 值未绑定到本人、行为、事件及金额种类 | 实体—事件—属性关系抽取、候选 ID 选择 | EP-06 本人与事件绑定 |
| 角色、场所、方式争议大 | 自由词归一与本体定义歧义混杂 | 版本化词表、精确别名、受控多标签、反例表 | EP-07 枚举与字段规则 |
| decision 边界与 regex 差异大 | 互斥章节分区和可重叠事实引用用同一结构承载 | Section 分类与 span 标注分离，先结构后字段 | EP-08 分区与引用双层表示 |
| C 仲裁吞掉错误、上下文截断 | 裁决器与教师不共用契约；上下文按字符截而非完整对象裁剪 | 同契约复核、候选验证、字段分组及证据窗 | EP-09 分歧分类与仲裁路由 |
| 空值多但不知道为什么 | 来源缺失、脱漏、遮蔽、不可推导均被写为 null | Missingness taxonomy、字段可观测性矩阵 | EP-10 字段可观测性报告 |
| 已付费响应丢失、同 ID 缓存错误复用 | 缺 durable task ledger、幂等键和统一 attempt 账本 | 任务账本、原始响应先持久化、事务提交、有限重试 | EP-11 调用执行与恢复 |
| 每次变更靠付费批调试 | 无固定回放语料及分层评估；机制正确与模型质量混测 | 固定夹具、性质测试、影子对照、冻结留出集 | EP-12 免费验证与实验分流 |

对应 O1/O12→EP-11，O2/O4/O5→EP-01/11，O3→EP-06，O6→EP-02/09，O7→EP-08，O8→EP-09，O9/O10/O11→EP-01/11。原 D1–D6 和 O1–O12 不再只落成“加强提示”或“加预算”的任务。

## 2. 最小选型：哪些直接复用，哪些只借鉴

| 能力 | 首选/参照 | 采用建议与边界 |
|---|---|---|
| 中文日期/时段 | [JioNLP 时间解析](https://github.com/dongrixinyu/JioNLP/wiki/%E6%97%B6%E9%97%B4%E8%AF%AD%E4%B9%89%E8%A7%A3%E6%9E%90-%E8%AF%B4%E6%98%8E%E6%96%87%E6%A1%A3) | 首选适配验证；输入完整时间表达式，输出类型、模糊性、时间范围；显式 time_base。本机已有 1.5.29 |
| 中文时间其他候选 | [Time-NLP Java](https://github.com/shinyke/Time-NLP)、[Python 移植](https://github.com/zhanzecheng/Time_NLP) | 经典规则方案，适合研究规则及作对照；移植版本须单独核对行为与许可，不按同名推定相同能力；本次未运行 |
| 多语种实体解析 | [Microsoft Recognizers-Text](https://github.com/microsoft/Recognizers-Text) | 覆盖中文数字、单位、日期等；官方列 Python 为 alpha，跨平台能力不可视为相同。可作离线对照，不因品牌直接替换当前 Python 解析器 |
| 中文数字字面量 | [cn2an](https://github.com/Ailln/cn2an) | 面向中文小写/大写/混合数字，strict/normal/smart 按表达类型选择；只处理已经定位的字面量，不全文改写。MIT；本次未安装/未运行 |
| 中文金额表达式 | [JioNLP money_parser](https://github.com/dongrixinyu/JioNLP/blob/master/jionlp/gadget/money_parser.py) | 可复用精确金额、单位和模糊修饰解析；其区间及模糊性输出必须经项目规则适配，不直接塞进 AmountRange |
| 结构与验证 | [Pydantic strict](https://docs.pydantic.dev/latest/concepts/strict_mode/)、[判别联合](https://docs.pydantic.dev/latest/concepts/unions/)、[JSON Schema 条件约束](https://json-schema.org/understanding-json-schema/reference/conditionals) | 复用已有 Pydantic，不重复手写两套类型表；缺字段必须报错，未提及作为明确内容分支 |
| 模型调用结构化封装 | [Instructor](https://github.com/567-labs/instructor)、[LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output) | 采纳 schema→请求→验证→反馈修复模式；Instructor 可小范围候选接入。无需为一次抽取重写成 Agent 或引入整套 LangChain |
| 证据与字符范围 | [W3C TextPositionSelector](https://www.w3.org/TR/annotation-model/#text-position-selector)、[spaCy Span](https://spacy.io/api/span)、[LangExtract](https://github.com/google/langextract) | 采用稳定源版本、半开字符范围、明确失败；LangExtract 的 source grounding 与诊断值得借鉴，整框架暂不迁移 |
| 费用与恢复 | [Tenacity](https://tenacity.readthedocs.io/en/latest/)、[Python sqlite3](https://docs.python.org/3.14/library/sqlite3.html) | 借鉴有界重试及事务账本；不是增加一个“自动无限重试”包装层，也不要求立即替换全部 JSONL |
| 坐标与恢复验证 | [Hypothesis](https://hypothesis.readthedocs.io/en/latest/quickstart.html)、[状态测试](https://hypothesis.readthedocs.io/en/latest/stateful.html) | 适合生成删改边界、Unicode、崩溃/恢复序列；本次未安装。实现线可用现有测试工具先覆盖固定反例 |

JioNLP 仓库标 Apache-2.0；cn2an 标 MIT。引入时冻结的是实际 wheel/依赖与规则版本，不是“永远用 master”。本机导入 JioNLP 会检查字典文件、缺失时尝试解压，因此部署还要固定字典资源及导入时写盘行为；本次确认已有字典齐全，并以审计钩子阻止评审树之外的写入和网络行为。参见 [JioNLP 仓库](https://github.com/dongrixinyu/JioNLP)、[字典解压实现](https://github.com/dongrixinyu/JioNLP/blob/master/jionlp/util/zip_file.py)。

## 3. EP-04：中文日期应怎么接，不只是换一个 parse_date

### 3.1 分成三项责任

1. **找时间表达式及其角色**：确定原文位置、目标本人和事件；角色至少分 `behavior / decision / prior_penalty / birth / remedy_deadline`。候选可以用规则或 NER 产生，模型只负责不易判定的角色/关系，输出候选引用。
2. **解析表达式**：完整绝对日期走日历校验快路；中文及复杂表达交 JioNLP；相对时间必须先提供有证据的锚点；解析不全或失败保留错误码。
3. **业务投影**：决定如何消费月份、区间、前次处罚日期及行为年龄；新中间表示保留精度。兼容 1.1.0 的“月初 1 日＋推断”只能在明确版本的兼容出口执行，不能污染底层事实。

JioNLP 官方明确把时间实体的抽取与 `parse_time` 分开，后者面向完整时间字符串；库支持 `time_base`，也有默认时间基及未来偏向参数。本项目建议适配器显式传基点、关闭未来偏向，纯表达式路径采用 strict 并在失败时拒收，不做宽松静默降级。这是项目策略，不是库默认配置。见 [时间解析说明](https://github.com/dongrixinyu/JioNLP/wiki/%E6%97%B6%E9%97%B4%E8%AF%AD%E4%B9%89%E8%A7%A3%E6%9E%90-%E8%AF%B4%E6%98%8E%E6%96%87%E6%A1%A3)、[解析器接口及限制](https://github.com/dongrixinyu/JioNLP/blob/master/jionlp/gadget/time_parser.py)。

### 3.2 需要的时间中间表示（设计，不修改现 schema）

```json
{
  "mention_id": "T4",
  "source_ref": {"sentence_id": 12, "span_id": "t1"},
  "event_id": "prior-penalty-1",
  "role": "prior_penalty",
  "kind": "calendar_range",
  "start_date": "2023-06-01",
  "end_date": "2023-06-30",
  "precision": "month",
  "calendar": "gregorian",
  "anchor_ref": null,
  "resolution": "resolved",
  "normalizer": "time-adapter-v1+jionlp@<pinned>"
}
```

这是一条合成示意，日期端点为包含当日的日期范围。若是具体时刻，另用带时区的 instant；不能把库的“23:59:59”当作项目统一的排他上界。`definition=accurate` 不等于 `precision=day`：完整年份、月份也可能被库称作 accurate，精度须结合源表达式和输出范围判定。

| 表达式 | 锚点责任 | 本项目应保留的结果 |
|---|---|---|
| 二〇二六年十月十八日 | 不需要补日期 | 2026-10-18，day |
| 2026年10月 | 不补某一天 | 2026-10-01 至 2026-10-31，month |
| 2023年5月至7月 | 区间内单位省略需解析 | 完整月份范围，不能只取 5 月 1 日 |
| 同年六月 | 找到“同年”指向的已述年份 | 锚点明确后解析该年 6 月；无锚点＝unresolved |
| 次日 | 绑定前述事件日期，不默认文书落款 | 锚点＋1 日；前述日期只是月份则不可精确成某日 |
| 去年六月 | 明确叙述参照时间 | 参照年的上一年六月；不能使用运行机器今天 |
| 三个月 | 是 duration，不是日历日期 | 保留 month=3；无起止日不能宣称自然时间恰等于 90 日 |
| 30日 | 根据语境判“某月30日”还是期限表达 | 若为日期缺年月须有锚；若为期限走 duration；禁止一律套本月 |
| 身份年龄 40 岁 | 判断该年龄对应何时 | 不等于行为时年龄；出生日期和行为日期精度不足时保留不可推导 |

年份、月份缺失的表达式也可能被库拿 time_base 补齐。因此即使解析返回成功，适配器仍须先检查必需的上下文是否有来源。基点不是一文固定一个 decision_date：同篇复议可能有多个历史事件，各表达式需要各自锚点；用于 E 的锚点还须符合其输入权限。

并发也需要适配：本机源码把 `parse_time` 暴露为一个解析器实例，调用时会修改实例上的 time_base 等状态。下一实现采用每 worker 独立实例或串行受锁调用，并做不同锚点交错测试；本次没有验证线程安全，不能直接把全局 `jio.parse_time` 塞进六线程管线。相关机制可核对 [解析器源码](https://github.com/dongrixinyu/JioNLP/blob/master/jionlp/gadget/time_parser.py)。

### 3.3 本机探测得到的证据

使用现有引擎树 `extract.py`，与本机已安装 **JioNLP 1.5.29**比较；`time_base=[2026,10,18,12,0,0]` 是合成上下文，`strict=True, ret_future=False`。完整输出见 [解析器合成探测](./seg-v2-engineering-parser-probes-2026-10-18.json)。这不是法律语料准确率测评，也未实现上述业务适配器。

| 输入 | 现 parse_date | JioNLP 本机结果 | 工程含义 |
|---|---|---|---|
| 二〇二六年十月十八日 | null | 2026-10-18 的全天范围 | 中文年份确有可复用能力 |
| 2026年10月 | 2026-10-01，推断 | 10 月全月范围 | 应保留月粒度，不能强行精确化 |
| 2023年5月至7月 | 2023-05-01，推断 | 5 月 1 日至 7 月 31 日 | 现函数把区间压成起点 |
| 同年六月 | null | 按给定基点变成 2026 年 6 月 | 库会补上下文；不能误认它解决了指代 |
| 三个月 | null | time_delta，month=3 | 时间跨度与日期的输出类型不同 |
| 2026年2月30日 | null | 抛 ValueError | 要保留错误处理，不让批处理崩溃 |
| 日期后附“作出处罚决定” | null | strict 模式拒绝整串 | 先定位纯时间表达式，不把整句交给 parser |

**选型建议：先实现 TimeNormalizer 适配边界，再把 JioNLP 作为首个后端；现 regex 仅保留经过验证的绝对日期快路。** Time-NLP 与 Recognizers-Text 不同时上线做“多数票”；先跑同一冻结表达式集，确认它们在项目困难例上有净收益再引入。

## 4. EP-05：中文数字、金额、人数要分层处理

### 4.1 可复用与必须自有的边界

`cn2an` 的职责是数字字面量转换，支持中文大写和中阿混写及不同宽严模式；它不是“本人赌资识别器”。JioNLP `parse_money` 可输出数值、币种和模糊性，适合表达式层；**“以上/超过/余/约”映射到什么业务区间由项目规则掌握**。参见 [cn2an API](https://github.com/Ailln/cn2an/wiki/API)、[JioNLP 金额解析](https://github.com/dongrixinyu/JioNLP/blob/master/jionlp/gadget/money_parser.py)。

建议数值中间表示包含 `exact / interval / lower_bound / upper_bound / approximate`，另带单位、端点包含性、raw 引用、解析器版本和业务规则版本。金额运算优先使用字符串构造 `Decimal` 或整数分，避免二进制 float 影响货币比较；这是 Python Decimal 的典型用途，见 [官方说明](https://docs.python.org/3.14/library/decimal.html)。若底层解析器已经经过 float，不能声称事后 `Decimal(str(x))` 已恢复无限精度；需设支持范围并核对超长/小额边界。

### 4.2 已观测的差异

| 合成输入 | 现引擎函数 | JioNLP 1.5.29 | 适配结论 |
|---|---|---|---|
| 贰佰肆拾元 | null | 240.00 元、accurate | 复用中文大写转换 |
| 三佰元 | null | 300.00 元、accurate | 混合大小写也应纳入表达式集 |
| 3到5万元 | **3–50000** | **30000–50000** | 现函数缺共享单位传播；不能用“两个端点可解析”判正确 |
| 万元以上 | 10000–null | 10000.00、blur+ | 需根据原始操作符映射开口上界，而不是丢掉 blur+ |
| 三千余元 | 3000–3999 | 3000.00–4000.00、blur | 两套区间口径不同，不能直替换 |
| 约5万元 | 45000–55000 | 50000.00、blur | ±10% 是现项目投影，不是通用库替你裁定 |
| 不足1000元 | 0–1000 | 1000.00、blur- | 上界“<”与“≤”须保存；旧闭区间契约会损精度 |
| 三十五块八 | null | 本机版本拒绝 | 不依据文档示例声称已支持；保留版本差异 |
| 20余人 / 至少3次 / 3至5人 | 20 / 3 / 3 | 本次未用金额库解析人数 | 现 parse_int 丢比较/区间，不能作为确数 |

项目当前 `AmountRange` 是闭区间，不能无损表达 `>5000` 与 `≥5000` 的差别。中间表示先保留比较关系；输出 1.1.0 时明确标记兼容投影及原始修饰，不擅自改字段形状。是否升级共享契约，交 E 定义并登记下一批生效。

对于人数、次数，数字转换只得到候选数量；“本人等四人”“本人与四人”“4名参赌人及2名围观者”还需要语法/语义归属规则。`多次` 不变成 2，`至少3次` 不变成恰好 3；现 int 字段无法承载下界时标为不可无损投影，不能假装是源头没写。

**采用顺序**：由于本机已有 JioNLP，先对其日期与精确金额作适配验证；金额关系、单位传播及人数边界使用独立的项目规则层。cn2an 作为轻量数字后端的候选/对照，只有它能补足覆盖或显著简化依赖时再加，不同时维护三套权威数字解析逻辑。

## 5. EP-01/02：schema、内容状态与执行状态

行业里已经有成熟的 schema 驱动请求和验证重试模式。Instructor 将 Pydantic 模型作为响应契约并提供验证/重试；LangChain 区分 provider-native 与 tool-calling 两种结构化策略。**这是客户端流程能力，不证明当前实际模型具有服务端 JSON Schema 受限解码。** DeepSeek 当前 JSON Output 文档明确的是合法 JSON，并要求提示给格式例、合理 max_tokens，还说明空返回可能发生。参见 [Instructor](https://github.com/567-labs/instructor)、[LangChain](https://docs.langchain.com/oss/python/langchain/structured-output)、[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。

具体交付：

- `ContractBundle`：schema、字段说明、枚举、必填集合、三态约束、证据规则、版本/哈希由 E 一次生成；A/B/C 共同使用。收到 schema 不支持错误时不得静默退化而不留痕。
- `ProviderCapabilities`：针对精确 endpoint/model 登记支持 `json_object / tool_schema / native_schema` 的哪一项。DeepSeek 现管线仅证实 json_object；MiMo 所用端点的 schema 能力待专门核实，不能从“兼容某协议”推断。
- `TaskResult`：执行状态 `valid / invalid / transport_failed / unresolved` 与内容状态 `明确 / 推断 / 未提及` 分开。一个非法枚举不能转成未提及；一个合法未提及不能被算为调用失败。
- 验证边界：缺任何必填字段即 invalid；嵌套 extra forbid；禁用无意识类型强转；内容三态的条件写进机器约束。Pydantic 严格模式对 Python 对象和 JSON 有区别，测试必须覆盖实际进入路径，不能认为加 strict 就万事大吉。参见 [Strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)、[判别联合](https://docs.pydantic.dev/latest/concepts/unions/)、[JSON Schema 条件约束](https://json-schema.org/understanding-json-schema/reference/conditionals)。

验收：原 88 条 A/B/labels 回放，坏类型、缺分组、额外字段、空值不一致全部给结构化问题报告，不崩溃、不自动填 null；C 新值亦需同样过关。无歧义平铺到嵌套仅作为显式适配器处理，不把“未知包裹格式”猜成正本。

## 6. EP-03/06/08：坐标、主体和章节不能互相代替

### 6.1 坐标与证据编译

通行做法是保存位置型选择器和源版本，必要时加文本校验：W3C TextPositionSelector 使用包含 start、不包含 end 的字符范围，并提醒资源变化会使位置失效；spaCy 也提供字符范围到 span 的接口及无法对齐时的失败结果。项目可采用这些约定，无须为此引入 spaCy 全套模型。见 [W3C](https://www.w3.org/TR/annotation-model/#text-position-selector)、[spaCy Span](https://spacy.io/api/span)。

EP-03 输出 `OriginalSpan / CleanSpan / SentenceRef` 三种不可混用的内部类型；所有跨层转换只在一个模块，显式 `project_clean_span` 与 `resolve_sentence_ref`。保留 Python 字符坐标、原文哈希、句表哈希；S0 删除形成的非连续投影返回 span 列表。模型只选引用 ID，由服务端生成 quote，不让模型直接算 Unicode 字符偏移。

验证对象是原评审中的 64 条错误输入及邻近边界，另加空句、一个字符、跨删除、同长替换、emoji、CRLF、重复句。句子结束位置不得再次减 1；外层不得把原文 end 再作 clean 下标。性质测试适合系统生成这些情况，见 [Hypothesis](https://hypothesis.readthedocs.io/en/latest/quickstart.html)。

### 6.2 本人—事件—数值绑定

EP-06 的输入不再是无来源的 `fine=500`，而是候选链：`mention M17 → amount A3 → event penalty-2 → person target-1 → role fine`。原文可有多个 500 元，只有绑定到正确主体/事件/金额角色的候选才能成为结果；`gambling_stake` 与 `fine` 即使相等也不能共证。

这里只需在单文书内建立轻量对象及关系，不需要上图数据库。规则识别明确标签，模型解决同指、复议引用或省略主语等难例，回候选 ID；编译器检查候选属于本次允许视图。法律规范层读取已抽事实并给独立冲突标记，不把合法候选自动当成原文真值。此结构为本项目建议，不是某库已提供行政赌博本体。

### 6.3 decision 与长文

EP-08 保留互斥章节 zones，同时提供 `operative_outcome / legal_basis / execution / remedy_notice` 引用层；先区分原处罚与复议结论，再选目标主文。公示表格标签可规则直通，混合句子要拆到子句或标不可分；不得为全覆盖把结论强塞入事实。

LangExtract 提供源位置回溯，并采用分块、并行及多轮提取处理长文；它仍要求原文对齐，定位不到的 extraction 可出现空 char_interval。**借鉴其证据诊断和长文对照方法，不能宣称安装它就消除对齐或主体错误。** 见 [官方仓库](https://github.com/google/langextract)。

这也修正了“切块一定不可行”的绝对说法：无上下文的机械切块不适合全局分区；章节定位后按任务取完整证据窗、保留全局目标与上下文的办法值得对照。先修现有 4000 字符/9000 字符截断，保留完整 JSON；是否采用分块，作为长文专项实验，不在本批直接迁框架。

## 7. EP-07/09/10：分歧和源头稀疏的工程化处理

**枚举归一**：建立引擎所有的 `AliasRuleSet`，含精确别名、前提、目标枚举、反例、版本。`参赌人员→参赌者` 可以成为经确认的别名；“组织者→聚众赌博”则涉及语义，不是字符串替换。多角色或多维场所不能靠模糊字符串相似度挑第一项。已有 parse_enum 的“枚举词包含于字符串”只作候选，不直接定案。

**分歧路由**：先按 contract error、reference error、presence conflict、value conflict、status conflict、evidence-window-only 分桶；只有合法候选才进入语义裁决。值同而证据不同，先查是否同一人/事件并各有支持，再决定免 C。C 输入包含 target、字段完整规则、候选证据、允许句与视图哈希；按语义依赖分组，不截断字段 JSON。

**可观测性**：EP-10 用显式旁路原因区分 source_absent、source_masked、input_omitted、ambiguous、unresolved、parser_failed。原始三态未改，执行失败不会写成源文未提及。先比较全文与允许输入中的可观测数，再决定补采还是修输入；每个 K 字段保留现门禁身份。关键词命中只是候选召回，不能给 `source_absent` 自动造真值。

这些是契约和评估流程问题；中文 NER、时间库或通用仲裁框架无法决定“含本人计数”“台费是否证明营利”“哪些前科日期有效”。规则必须由 E 明确，并通过真实反例核验。不能用增加第三模型替代规则缺口，也不能把高共识当作独立准确率。

## 8. EP-11/12：可靠执行与免费验证

主流重试库能表达异常筛选、退避和次数上限；事务存储可避免半条任务被当完成。建议沿用现 JSONL 原始产物，新增一个小型 task 索引或等价可靠提交协议即可，不把此次修复升级成工作流平台建设。参见 [Tenacity](https://tenacity.readthedocs.io/en/latest/)、[sqlite3 事务接口](https://docs.python.org/3.14/library/sqlite3.html)。

任务键至少由原文、target、句表、输入视图、契约/提示、模型身份、参数及任务种类共同决定。状态为 `pending → submitted → raw_persisted → validated → committed`；C 与降级调用没有特殊豁免。最终 schema 不过，不写 valid commit；恢复优先重解析已存 raw，不重打已完成任务。

费用由统一 HTTP attempt 账本计量。Instructor 文档特别区分 SDK transport 重试与验证重试；两层都打开会使真实请求多于表面“尝试次数”，取消本地等待也不保证远端停止计算。因此传输、格式修复和语义重审分别计数，并共享 cap/在飞预留。超时且无法知道远端是否完成，记 unknown outcome；没有 provider 幂等承诺，不能声称本地账本实现了付费请求恰好一次。见 [Instructor 重试说明](https://python.useinstructor.com/concepts/retrying/)。

EP-12 的验证分成四条线：

| 线 | 只需要免费测试的内容 | 不能据此证明 |
|---|---|---|
| 解析器 | 合成表达式＋冻结真实表达式，按日期精度/锚点、金额边界/单位分层 | 字段属于本人或正确事件 |
| 编译与执行 | 坐标性质、权限、坏 schema、C 新值、持久化故障及恢复序列 | 新提示下模型的实际正确率 |
| 旧输出重放 | 原 300/88 的输入重建、合法候选、分歧分桶与原门禁报告 | 被换掉输入后的模型答案 |
| 新模型小批 | 仍按评审中 12→36 的规约方案；先冻结前面已通过的解析器/规则/契约 | 正式 300 试点、200–300 件要素验收及 r7 全量门禁 |

状态机恢复可用固定故障注入或 Hypothesis 的 stateful testing；测试要模拟“响应到了但未记账”“raw 已存而未 validated”“labels 已写一半”的路径，而非只验证理想顺序。参见 [状态测试官方示例](https://hypothesis.readthedocs.io/en/latest/stateful.html)。

## 9. 可直接移交的工程任务与退出条件

下表路径是**归属线拟实现位置**，本评审没有在那里写入文件。E＝引擎线，W＝网页线，C＝协调。

| 任务 | 拟实现/改造位置与负责人 | 必要交付与退出条件 |
|---|---|---|
| EP-01 | E `element_labels.py`；W `run_elements.py / s1.py` | 一个 ContractBundle 真正进入 A/B/C 请求；本机夹具确认 36 字段、枚举/类型/必填齐全，坏候选报告而不合并；provider 能力显式登记 |
| EP-02 | W `merge_labels`；E 验收接口 | 内容三态与执行状态分离；原平铺输出可显式拒绝/适配，缺字段不能再产生全空“共识”；配对验收不崩溃 |
| EP-03 | W `locate.py / run_elements.build_inputs` | 单点 typed span 投影；旧 64 条输入偏差有逐件对照，所有视图切片满足引用权限；无模型调用 |
| EP-04 | E 拟 `normalization/time.py`，W 消费同契约 | 显式锚点与 precision 的 TemporalValue；接入 JioNLP 后端；中文日期、月/年/区间、非法日及无锚相对时间夹具正确 |
| EP-05 | E 拟 `normalization/quantity.py`；W grounding 复用 | Money/Count 中间表示、Decimal/单位/比较关系、兼容投影；覆盖共享单位和大写金额；只保留一个权威归一化出口 |
| EP-06 | W 候选构建；E 定义主体/事件语义 | 每个结果可追到 target/event/value-role；同值异人、赌资/罚款同值、原决定/复议变更夹具不会串用 |
| EP-07 | E `schema.py` 及规则资产 | 别名表、角色/方式/场所/人数边界与反例；是否多值明确决定并升版；不以字符串包含自动定案 |
| EP-08 | W `zoning.py / s1.py`；E 确认消费层 | 主分区与细引用层分开；decision 边界规范有例子；保持旧 F1、原 S3 并报，不改门禁凑数 |
| EP-09 | W C 输入装配、路由与合并 | 先分错误种类；C 同 target/schema/引用白名单；无裸截断、无新值借 A 引文，所有出口统一验证 |
| EP-10 | E 验收报告；W 产旁路诊断 | 36 字段×来源/形态的可观测性和失败原因；K 不删项；parse_failed 不进入未提及比例洗统计 |
| EP-11 | W 公共调用封装及 run manifest | 所有 HTTP attempt 有独立 receipt/raw/usage；重试总次数和费用预留有上界；模拟恢复不重发已知成功任务 |
| EP-12 | E/W 测试与报告；C 登记实验 | 固定表达式集、旧输出回放、独立留出及任务级质量/成本报告；免费测试完成再发下一付费工单 |

**实施次序**：先 EP-01/02/03 修已证实的错误；同时由 E 做 EP-04/05 的纯函数适配。再落 EP-06/07/08/09 的语义契约及 EP-10 的分层报告，EP-11/12 贯穿。日期和金额库的引入不必等待整条模型调用架构重写，也不能替代最先三项。

发布边界沿用原评审：原 final300/element-v1 只读；新规则、词表、normalizer、句表与契约各有版本，写新批次。旧“月份取 1 日”“余元区间”“三个月=90天”等兼容规则保持可追踪，改变语义由 E/C 登记后下一整批生效。解析器夹具通过不代表 r7 放行，也不新增或降低任何正式门禁。

## 10. 本次已做与尚未做

已查阅上述一手资料；在 Python 3.14.3、已装 JioNLP 1.5.29 上运行 **16 日期＋12 金额＋4 计数**合成探测，保存原始结果和引擎文件哈希。没有挑选几个成功例计算“准确率”，因为本次目的是识别接缝、默认值与口径差异。探测进程阻止网络、子进程及评审树外文件写入。

尚未安装或执行 cn2an、Time-NLP、Recognizers-Text、Instructor、LangExtract、Hypothesis；未比较真实法律语料的召回率、延迟和内存；未验证 MiMo 当前端点的原生 schema 能力；未实现 TemporalValue/QuantityValue 业务适配器。故结论是**可执行的优先选型与任务拆解**，不是已完成集成或已达到质量目标。
