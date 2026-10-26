# 全链路模型调用设计 · 现状全量呈现（full-record v1.1）

> **v1.1 勘误（2026-10-18，评审后）**：独立评审（`codex/seg-v2-design-review`）复算证实本文呈现的
> `build_inputs` 坐标装配存在 clean/orig 混用缺陷（U/run_elements.py:78-81 传 `span(cs,ce-1)` 且存混合坐标），
> 64/88 教师输入不等于应有原文切片——本文 §3.1 如实呈现了这条调用链，但 v1.0 未识别其为缺陷，
> 且 §3.6 "88 件有效标签"的定性**作废**，应为"88 件已配对落盘（64 件输入污染隔离留档，结构合格仅 6 件）"。
> 复核与处置全文见 `seg-v2-review-verification-response-2026-10-18.md`。

> **定位**：本文不是反思、不是问题清单。反思（`model-call-design-reflection-2026-10-18.md`，D1–D6）回答"哪里设计错了"；
> 本文回答"**现在到底是怎么设计的**"——把当前实现的全部模型调用链路逐调用点客观还原：提示词原文、输入装配、输出契约、
> 校验规则、失败处置、后处理、账本、实测参数与实测数字。每一处标注 `文件:行号`，可逐条对照代码核验。
> 审核方法：对照仓库源码与数据目录运行产物逐行核对；文档与代码不一致处以代码为准并修订本文。
> 代码根：`research/discretion/unify/`（下称 U/）；引擎契约根：`justilaw-api/app/discretion/`（下称 E/）；
> 运行数据根：`D:\02_Dev\Data\justilaw-research\`（下称 $D/）。
>
> **本文快照时点**：2026-10-18 下午。要素 120 件阶梯批刚跑完（88 件有效标签）。写作过程中另核出 12 个
> **开放决策点（§9，O1–O12）**——它们是实现中的客观事实（有行号、有数据），但定性为"待拍板的设计选择"而非"已确认错误"，
> 与反思文档的 D1–D6 不重复。

---

## 0. 全景拓扑

链路上**共 5 个模型调用站**，其中 4 个已实跑、1 个备用未实跑。其余全部环节是确定性代码，不碰模型：

```
harvest/parsed-1 ──► S0 清洗+句表+分区参照(U/cleanse.py,to_unified.py) [确定性]
                        │
                        ▼
              unified_raw records.jsonl ──► 预筛(U/prefilter.py) [确定性]
                        │ (release 记录)
                        ▼
        【站1】S1 seg-v2 ── 每记录 1 次调用：分区 zones + 六组字段
                        │       (U/s1.py)                提供商：deepseek-flash 主
                        ▼                                （失败→同模型重试1→换提供商1）
              outputs.jsonl ──► S3 十一项确定性检查(U/s3.py,run_s3.py)
                        │
                        ├─► 【站4】anchor 分歧裁判 ── 每条分歧 1 次调用
                        │        (U/arbitrate.py + anchor_compare.py)  提供商：xiaomi-pro
                        │        前置：legal_anchor 常量表判死（不调模型）
                        ▼
              【站2/3】elements 双标 A/B ── 每记录 2 次调用
                       (U/run_elements.py + E/element_labels.py 契约)
                       A=deepseek-flash  B=mimo-v2.6-flash
                        │
                        ▼
              【站5】C 合并仲裁 ── 每条有分歧记录 1 次调用（失败→逐字段≤4 降级）
                       提供商：mimo-v2.6-pro
                       │
                       ▼
              labels.jsonl（{status,value,evidence[quote,start,end]}）──► 引擎验收
```

| 站 | 目的 | 调用粒度 | 提供商/模型 | 状态（快照时点） |
|---|---|---|---|---|
| 1 S1 seg-v2 | 句表分区+字段抽取 | 记录×1 | deepseek-flash（备 qwen3.8-flash） | final300 已完成 299/300 |
| 2 elements-A | 教师标注甲 | 记录×1 | deepseek-flash | 88 件已配对落盘（v1.1：64 件输入污染待隔离） |
| 3 elements-B | 教师标注乙 | 记录×1 | mimo-v2.6-flash | 同上配对 |
| 4 C 合并仲裁 | 字段级分歧裁决 | 记录×1（降级×≤4） | mimo-v2.6-pro | 本批 52 次调用 51 成 |
| 5 anchor 裁判 | S1 vs 正则锚分歧 | 分歧×1 | mimo-v2.6-pro | final300 已跑 95 条；备用站 |

**确定性组件（易被误当模型环节，全部无模型参与）**：S0 清洗规则与句表切分（U/cleanse.py）、
form 检测（U/form.py）、预筛 19+1 词（U/prefilter.py）、公示族确定性分区 zones_det（U/zoning.py）、
facts 兜底回填 merge_fact_fallback（U/zoning.py）、S3 全部 11 项检查（U/s3.py:448-460）、
法条上限常量（legal_caps.json）、原文坐标映射 OffsetIndex（U/locate.py）、
要素证据定位 locate_evidence 与合并比较 merge_labels（U/run_elements.py:116-195）、
法律锚 legal_anchor（U/arbitrate.py:67-91）。

---

## 1. 公共基础设施层

### 1.1 HTTP 客户端（U/s1.py:109-150）

单一 `Provider` 类，五个调用站共用。请求体固定字段（U/s1.py:122-130）：

```json
{"model": <config>, "messages": [system, user], "temperature": 0,
 "max_tokens": <per-provider>, "response_format": {"type": "json_object"}, "stream": false}
```

- 鉴权 `Authorization: Bearer <api_key>`（U/s1.py:133）；超时 per-provider。
- 错误包装：HTTPError → `RuntimeError("HTTP <code>: <body前300字>")`（U/s1.py:139-141）；
  其余异常 → `RuntimeError("<类型名>: <msg>")`（U/s1.py:142-143）。这一格式是错误分类的解析锚。
- **空返回也算失败**：`content` 为空 → `RuntimeError("空返回（finish=…）")`（U/s1.py:148-149）。
  起因：deepseek-flash 是推理模型，reasoning tokens 挤占 max_tokens 时 content 为空但 HTTP 200。
- 每次成功返回 `(content, {latency_ms, usage})`；usage 直接透传上游 token 计数。

### 1.2 提供商配置（$D/config/s1_models.json，明文，不入仓库；日志一律掩码 U/s1.py:50-53）

| 键 | 模型 | base_url | max_tokens | timeout | 角色 |
|---|---|---|---|---|---|
| deepseek | deepseek-flash（推理模型） | api.deepseek.com | 12000 | 240s | S1 主 / elements-A |
| bailian | qwen3.8-flash | dashscope…/compatible-mode/v1 | 6000 | 120s | S1 备用（账户 400 停用中） |
| bailian-max | qwen3.8-max | 同上 | 8000 | 180s | 白名单裁判候选（未用） |
| xiaomi | mimo-v2.6-flash | token-plan-cn.xiaomimimo.com/v1 | 8000 | 180s | elements-B |
| xiaomi-pro | mimo-v2.6-pro | 同上 | 8000 | 180s | C 仲裁 / anchor 裁判 |

全局 params `temperature=0`；**per-provider 覆盖**（U/s1.py:367）：`{**gparams, **(pcfg.params)}`。
此设计起因是一次熔断事故——共享 max_tokens/timeout 时百炼超时拖死 deepseek 的连败计数（见 §8.4）。

### 1.3 价目表（$D/config/s1_prices.json，6 模型，元/百万 token）

deepseek-flash 2/8，qwen3.8-flash 1/4，qwen3.8-max 8/24，kimi-k3 6/18，mimo-flash 1/4，mimo-pro 4/16。
文件头声明口径：**占位估算，结算以 receipts 原始 token × 各控制台当期价为准**（CostMeter 只按此表折价，
U/progress.py:52-64）。推理模型的 reasoning_tokens 已含在 completion_tokens 里计费，不另列。

### 1.4 心跳/费用/熔断（U/progress.py 全 189 行）

- `classify_error`（U/progress.py:25-41）：balance(402/Insufficient Balance)、auth(401)、rate_limit(429)、
  timeout、server(5xx)、json、empty(空返回)、other。
- `ProgressTracker`：每件完成原子写 `progress.json`（tmp+os.replace，PermissionError 重试×5 →
  降级直接覆盖 → 再失败静默吞掉；**心跳任何失败不得传播到主管线**，U/progress.py:159-178）。
  快照字段：phase/total/done/ok/fail/in_flight/started/elapsed_min/rate_rpm/eta_min/latency p50/p90/
  attempts_dist/error_categories/errors_recent(10 条)/tokens_by_model/cost_total（U/progress.py:135-157）。
- `CostMeter`：按模型累计 calls/prompt/completion/cost（U/progress.py:44-77）。
- **熔断只在站 1 实现**（U/s1.py:237-256）：balance/auth 一次判死；其余类 **90 秒窗内**连 3 次判死；
  任何成功复位计数；提供商判死后同记录内跳过、跨记录不再尝试；全死→记录级快速失败
  `all_providers_dead`（U/s1.py:284-290）。站 2-5 无熔断，调用失败即返回 None（见 §3.4）。
- 观测 CLI：`status.py --run <id|latest> [--watch]`（2 秒刷新）。

### 1.5 日志族与断点续跑

| 文件 | 产生者 | 内容 |
|---|---|---|
| receipts.jsonl | 全部站 | 每次 HTTP 尝试一行（status/latency/usage/错误+分类；站 1 带 attempt，站 2-4 带 tag A/B/C/C-batch 和 n_fields） |
| outputs.jsonl | 站 1 | 每记录一行：raw、解析 output、validation_errors、zone_check、chain、content_sha；append，**断点缓存按其 ok 行**（U/s1.py:448-459） |
| raws.jsonl | 站 2/3 仅 | 每次 A/B 成功调用的原始 content 即时落盘（U/run_elements.py:262-266）；**C/C-batch 不写 raws**（O1） |
| labels/A/B/diffs.jsonl | 站 2-4 | 每件成功即时 append+flush（U/run_elements.py:438-461），断点按 labels 已有 id（U/run_elements.py:418-425） |
| budget.jsonl | $D/s1_runs/ | 每 run 一行 {ts,run,stage,records,cost,cap}，总账 |
| index.json / manifest.json / summary.json / progress.json | 站 1 全套，其余部分 | manifest 含输入 SHA、配置指纹（掩码后哈希）、ids、prompt_version |
| queue_manual.csv / queue_retry.csv | 站 2 | 输入不可标 / 单盲与崩溃件的重试点名单 |

---

## 2. 调用站 1：S1 seg-v2 —— 句表分区 + 字段抽取（每记录 1 次）

**目的**：把清洗后文书切成 facts/evidence/reasoning/decision/review/meta 六类连续区间并抽六组字段，
是 parsed-2 的分区与字段来源。**当前提示词版本 seg-v2**（U/s1.py:35；seg-v1 摘引式已冻结，
因 coverage 失败 51 件，见 pilot300 报告）。

### 2.1 输入装配（U/s1.py:262-275 + build_user_prompt U/s1.py:95-104）

1. `sentences = sentence_table(cleaned_text)` —— 清洗文本的编号句表（消费式切分，坐标无缝）；
   `texts = cleaned[a:b]` 逐句切片。
2. user prompt 模板（原文）：

```
[form] {form} | [source_type] {source_type} | 共 {N} 句
[本人] 本案当事人：{subject_mention}；outcome 各值只填本人的处罚，非本人的金额/天数不合并计入；subject.mention 用本人在正文的写法
句表：
[S1] …
[S2] …
```

   `[本人]` 行仅当记录有 subject_mention 时注入（多人并载页定位依据；与 M1 `extract(target=…)` 同构，
   设计论证在 U/s1.py:100-103 注释）。
3. **公示族附加行**（U/s1.py:274-275）：`rec.zones_det` 存在时追加
   `[分区] 本件分区已由模板规则确定（facts/decision 等区间以句号给定），输出中无需臆测分区。`
   ——注意：仍然要求模型在输出里给 zones，仅在解析后用确定性值**覆写**（U/s1.py:309-311），
   模型臆测值不采信。此处白花 output tokens（O7）。

### 2.2 系统提示词全文（U/s1.py:58-92，原文照录）

```
你是行政处罚文书的结构化抽取器。输入是清洗后的文书，以编号句表（[S1]…[SN]）给出。只输出一个 JSON 对象。

【分区 zones】把全部 N 个句子依原顺序切成连续区间，每区间一个类型，必须完整铺满 [S1..SN]：
- facts：违法事实（"经查/查明/现查明"部分）——只写行为事实；
- evidence：证据列举（"以上事实有…证据"）；
- reasoning：认定理由与裁量说明，以及一切定性/结论句（"行为已构成赌博""情节严重""从轻处罚"等）；
- decision：处罚决定及其依据、执行方式（"决定给予…"）；
- review：复议/诉讼机关的审查意见与结论（无则不设）；
- meta：表单元数据（案件名称、文号、日期栏、当事人栏等）。

【硬性结构规则】
1. zones 依序衔接：首区间 from=1；相邻区间前一个 to+1=后一个 from；最后区间 to=N。无缝隙、不重叠、不跳句。
2. 定性/结论句（"已构成""情节严重""决定给予""从轻处罚"等）一律归 reasoning 或 decision，绝不进 facts；
   facts 的最后一句必须是行为事实陈述。
3. meta 用于表单元数据行（字段表/公示的名称、文号、日期、当事人栏）。

【字段（基于 facts/decision 区间内容）】
- 文书没有的信息给 null 或 []，不得编造；dates 缺失给 null。
- 文书明示数项违法行为或"合并执行"时 multi_violation=true 并给 executed_penalty（合并后总额）；否则 false、executed_penalty 两项填 0。
- articles 每项 {"text": 原文写法, "edition": "2012修正|2025修订|未知"}。
- gambling：本文书是否属赌博案件，verdict 是/否/待定 + 一句 reason。
- confidence：high/low。

【输出 JSON 结构】
{"zones":[{"type":"facts","from":1,"to":10},…],
 "subject":{"mention":"本人原写法或null","aliases":[]},
 "outcome":{"type":"不予处罚|不构成违法|警告|罚款|拘留|拘留并处罚款|移送刑事",
   "detention_days":0,"fine":0,"not_executed":"是|否",
   "multi_violation":false,"executed_penalty":{"detention_days":0,"fine":0},
   "confiscation":[],"detention_items":[],
   "articles":[{"text":"…","edition":"…"}],"stated_circumstances":[]},
 "dates":{"behavior":"YYYY-MM-DD或null","decision":"YYYY-MM-DD或null"},
 "review":{"result":"维持|变更|撤销|确认违法|程序驳回|无","changed_outcome":null},
 "gambling":{"verdict":"是|否|待定","reason":"…"},
 "confidence":"high|low"}
```

### 2.3 输出校验（U/s1.py:173-203）——结构 6 条 + 枚举 4 条

| # | 规则 | 违规文例 |
|---|---|---|
| v1 | zones 非空列表 | `zones 缺失或为空` |
| v2 | 每区间 type ∈ 六类枚举 | `zone.type 非法: …` |
| v3 | from/to 为 int 且 from≤to | `zone 区间非法: …` |
| v4 | 依序衔接（from=prev_to+1） | `zones 不连续（有缝隙或重叠）` |
| v5 | 铺满句表（末 to=N） | `zones 未铺满句表: to=… ≠ …` |
| v6 | outcome.type / gambling.verdict / review.result / confidence ∈ 枚举 | 各 `… 非法: …` |

### 2.4 失败处置链（U/s1.py:281-352，顺序即代码顺序）

```
预算 cap 检查(267) → seq=[主,主,备首个](282)（判死者剔除→全死快速失败）
→ chat → extract_json 容错(155-170：直解→剥```json围栏→首{到末})→ 失败记 extract 回执后按调用失败处理
→ validate
→ zones_det 覆写(309-311)：公示族分区以确定性值为准，zone 类违例清除
→ facts 缺失时 merge_fact_fallback(312-318)：按正则 facts 区间把 meta 句回色
→ 仍有违例且还有尝试位：违例回灌重试(319-329)——
     "[上次输出存在结构错误，请修正后重发全部字段：<前3条>]" 拼在 user 尾部续打
→ 成功：熔断计数复位(331)、心跳、输出行
```

### 2.5 实测（final300 正式批，$D/s1_runs/s1-20261018-segv2-final300/）

n=300；ok 299（99.67%）；validation_clean 299；zones 1383（均值 4.63/件）；**tiling 违例 0**；
attempts {1:289, 2:10}；全部 deepseek（备用未上场）；成本 ¥6.66 / 309 次调用 / 1.12M token
（≈¥0.022/件）。质量结论（判据口径）见 pilot300 报告 §7-8：结构类错误清零，残余为语义类
（事实缺段/结果矩阵/渠道表损页），归因均有归属，非接口层。

---

## 3. 调用站 2/3：elements 双教师标注 A/B（每记录各 1 次）

**目的**：按引擎 I-20 契约产出要素金标。契约唯一真源是**引擎文件**（E/element_labels.py），
网页线以 sys.path 直读 import（U/run_elements.py:39-45，契约不可达即整体拒跑），
提示词/校验/schema 都不得在网页侧重定义——这一耦合是刻意的：验收方与生产方共用同一份定义，杜绝口径漂移。

### 3.1 输入装配（U/run_elements.py:53-108，build_inputs）

- 句子级选取：S1 输出 zones → facts 区间全部句 + **位于首个 facts 句之前的 meta 句**
  （当事人/身份句；zones 缺则退回确定性 zones_det；两者全空或无 subject_mention → 返回 None →
  `queue_manual.csv` 人工分流，final300 分流 32 件）。
- **原文切片**：句坐标经 edits.rle 映射回 `text_full`（join_orig，U/run_elements.py:84-92），
  因此模型看到的 facts_text/meta_text 是**未经清洗的原文**，引文坐标天然落在原文空间——这是"模型不再抄
  清洗文本"的设计落点。
- 同时给教师一份 `regions`（各输入句的原文区间），只用于后续定位消歧，不进提示词。
- aliases 取 S1 `subject.aliases`。引擎 teacher_messages 侧硬校验（E/element_labels.py:95-98）：
  target 空、或 facts/meta 全空 → 抛 ValueError 拒标（不匿名猜本人）。

user 消息模板（E/element_labels.py:100-102，原文）：

```
目标当事人：{target}
同一人的其他写法：{alias_line 或 无}
当事人/身份句：
{meta_text 或 （原文未提供）}
事实句：
{facts_text 或 （原文未提供）}
```

### 3.2 教师系统提示词九条规则（E/element_labels.py:76-89 生成，原文）

```
你是行政赌博案件要素标注教师。只输出符合 element-v1 / schema {SCHEMA_VERSION} 的 JSON。
一条记录只标一名目标当事人；aliases 仅是同一人的不同写法，不是其他参赌人。
只读给定的当事人/事实句；不得借处罚决定、说理、所引法条、机关信封或常识补事实。
每个字段都输出 {status,value,evidence}；状态只用 明确/推断/未提及。
未提及时 value=null、evidence=[]；有值时 evidence 为逐字连续引文数组，每项仅含 quote，不输出坐标。
未提及是正常且常见的结果；原文没有本人专属信息时不要猜，也不要从处罚结果反推。
金额用元的 {min,max}：确数两者相同；'以上/逾/超过/至少/不低于'只写下界，max=null，不补上界。
只收台费/场地费可记 commission，但不证明 profit_purpose；营利目的严格按字段说明。
年龄与前科优先看当事人句；当事人句缺失时不得从其他人的身份或处罚推断。
全部字段必须出现，且只出现下列字段：
conduct.behavior_type：… （此后为 36 个字段的 path：说明 逐行，见附录 A）
```

**输出契约**（E/teacher_output_schema:50-73）：七组 36 字段全量；每字段
`{status:明确|推断|未提及, value:<类型|null>, evidence:[{quote}]}`；值类型含枚举、
AmountRange（{min,max}，max 可 null）、date(ISO)、int/float/bool；additionalProperties=false。

**引擎校验** validate_teacher_output（E/element_labels.py:137-188）11 类 issue code：
bad_root / unknown_group / missing_group / unknown_field / missing_field / bad_field_shape /
bad_status / absent_inconsistent / bad_value / evidence_missing / bad_evidence_shape /
evidence_not_found / evidence_offset_mismatch。网页侧调用后 issue 只写进 `_diag.a_issues/b_issues`
（U/run_elements.py:344-345,400），**不触发反馈重试**（O5，对比站 1 的 2.4 违例回灌）。

### 3.3 调用与容错（U/run_elements.py:238-271 + 329-343）

- A、B 各**单次尝试**（ElementsRunner.call，无重试、无熔断）：失败→回执(status=fail,category=错误分类)
  →返回 None。
- **单盲保护**：pa/pb 任一为 None → 整件作废、不产空标签，进 queue_retry
  （U/run_elements.py:339-343）。原因：引擎验收要求 A/B 配对；早期版本曾因此产出整批 null 标签。
- 每次成功调用的原始 content **即时落盘 raws.jsonl**（U/run_elements.py:262-266）——
  首批 494 次调用载荷因批尾写盘丢失（事故账 ¥8.77，budget.jsonl 03:37 行）后的强制纪律。
- 每件结果 labels/A/B/diffs **即时 append+flush**（U/run_elements.py:442-461）；断点续跑按
  labels.jsonl 已有 id 跳过（U/run_elements.py:418-425）。
- **起跑前预估门槛**（U/run_elements.py:427-436）：per_rec 取 budget.jsonl 同 stage 最近均耗（缺省 0.12），
  `len(work)×per_rec > cap` → 拒绝起跑要求人工确认。实测本批均耗 ¥0.085/件，0.12 兜底偏保守（O10）。
- cap 到顶行为：停发新件（已在飞完成即止），返回 None 计入 retry（U/run_elements.py:330-332）。

### 3.4 S2 定位与字段级合并（定位是确定性代码，不花钱）

- `_candidates`（U/run_elements.py:198-223）：把每条 evidence 的 quote 在 `text_full` 里定位成
  `{quote,start,end}`；`locate_evidence` 三级（U/run_elements.py:116-154）：
  ① 逐字唯一命中；② 多处命中→用 regions（教师输入句的原文区间）消歧，唯一落入者取；
  ③ 空白归一后唯一命中→映射回原文并含尾空白重切。歧义不可消→`review:true` 标记进复核，不猜。
- `merge_labels`（U/run_elements.py:157-195）：A==B 判据 = **status 相等 ∧ value 深相等 ∧
  evidence 坐标集合相等**（review 证据除外）；满足直采 A。任一不满足记 diff；diff 字段交 C 裁决（§4）。
  注意此判据把"值同、status 或引文窗口不同"也算分歧（O6，实测见 §3.6）。

### 3.5 D-002 隔离（U/run_elements.py:292-293）

起跑即断言：`c_provider == deepseek` 或 A、B 同为 deepseek → 拒跑。当前组合 A=deepseek、
B=小米 flash、C=小米 pro，非百炼（2026-10-18 用户改令弃用百炼做双标；白名单登记
U/arbitrate.py:39-41）。**厂商相关性残余**：B 与 C 同厂小米——双盲独立性以 A 为锚。

### 3.6 实测（$D/…/final300/elements/，两批合并口径）

- ~~有效标签 88 件~~（v1.1 勘误：应为"88 件已配对落盘"；64/88 输入受 F3 坐标混用污染，
  merged 枚举非法值域 220+ 条，全未提及伪成功 5 件——见评审 F1/F2/F3 与复核回应 §1），
  04:40 批 33 件 ¥3.73 + 08:10 批 55 件 ¥4.69；manual 分流 32 件；single-blind/crash 0。
- 本批 fields_diff **328**（5.96/件，含上批合计 diffs.jsonl 541 行）；仲裁后 **unresolved 仅 1**；
  evidence 402 条，loc_fail(review) 10。
- receipts 代际混合（同目录混跑三代代码）：tag=C（逐字段旧版）232 次全成、C-batch（现行合并版）
  52 成 1 败；A fail 53 条 = deepseek 充值前 402×51 + empty 2（历史段，不影响现行断点缓存）。
- 分歧结构样本（diffs.jsonl 首行，W-000630 `conduct.behavior_type`）：A=`{明确,"参与赌博",1 条引文}`、
  B=`{推断,"参与赌博",2 条引文}`——**值完全相同，status 与引文窗口不同**即触发一次仲裁字段位；
  C-batch 裁决后 merged=明确+A 的短引文。该例是 O6 的直接证据。

---

## 4. 调用站 5：C 合并仲裁（记录级一次 + 逐字段降级）

### 4.1 提示词全文（U/run_elements.py:226-233）

```
同一案件多个字段两位标注教师给出不同结果，逐字段依原文裁决。
原文（当事人句+事实句）：
{text}
分歧字段（JSON 数组，每项 path/a/b）：
{fields}
规则：以原文逐字证据为准；两候选都无据给新值（附证据）或判"未提及"；逐字段回答。
只输出 JSON：{"decisions":[{"path":"组.字段","adopt":"A|B|未提及|新值","value":<裁决值或null>,
"status":"明确|推断","evidence":[{"quote":"逐字引文"}],"reason":"一句话"}]}
```

装配：`text = (meta_text+"\n"+facts_text)[:4000]`；`fields = json([{"path","a","b"} for 全部 unresolved])[:9000]`
（U/run_elements.py:357-361）。system 侧仅一句"只输出一个 JSON 对象。"

### 4.2 处置链（U/run_elements.py:354-389）

```
合并仲裁 1 次调用 → extract_json 容错 → decisions 按 path 建 adjud 表
→ 失败（含崩溃防护：整段 try）→ 逐字段降级各 1 次（仅前 4 字段）→ 仍败字段保持 unresolved 进复核，不炸批
→ merge_labels(ca, cb, adjud) 重合并
adopt 语义（U/run_elements.py:186-194）：A/B→原样采纳（含其 evidence 坐标）；未提及→置空；
新值→取 C 的 value/evidence/status，缺 evidence 时借用 A 的第一条。C 给的新值 evidence 是 C 的
quote——注意：该 quote 未经 _candidates 定位（merge 后再无定位步骤），落 review 与否取决于
loc_fail 统计（U/run_elements.py:391-392）。
```

### 4.3 实测与已知限制

本批 52 件记录级调用（51 成 1 败）、旧代逐字段 232 次全成；mimo-v2.6-pro 单次约 ¥0.01。
**C 的原始响应不落 raws.jsonl**（调用不走 ElementsRunner.call，U/run_elements.py:359-365）——
崩溃后 C 裁决不可恢复只能重打（O1）；且 C-batch 失败回执不带降级逐字段的独立 receipts（O12）。

---

## 5. 调用站 4：anchor 分歧裁判（S1 vs 历史正则锚，备用站）

**触发链**：U/anchor_compare.py 对 final300 逐字段比对 S1 值 vs parsed-1 正则锚值 →
divergences.csv（95 条）→ U/arbitrate.py `--referee xiaomi-pro`。

### 5.1 两级裁决（U/arbitrate.py:131-153）

1. **法律锚优先（不调模型）**（U/arbitrate.py:67-91）：fine/detention_days 对照 legal_caps——
   `dead(v) = v > 版本上限`；一方判死→自动采纳存活方（reason_code=legal_anchor）；双死→unresolved。
   参数口径：上限取**两版本较小值**（ref_det=min(15,15)=15、ref_fine=min(3000,5000)=3000，
   另加合并执行硬顶 20 日）。后果：2025 版下合法罚款 3000–5000 元、合并拘留 16–20 日会被保守判死
   （O3，属设计选择，需与 edition 判定联动修正）。
2. **裁判模型**（U/arbitrate.py:107-128）：

```
同一份行政处罚文书的一个字段出现两个不同的抽取值，请依正文裁决。
字段：{field}  候选 A：{a}  候选 B：{b}
正文：{text[:4000]}
规则：以正文逐字证据为准；正文没有的记"未提及"；两候选都错时给出正文支持的新值。
只输出 JSON：{"adopt":"A|B|未提及|新值","value":…,"status":"明确|推断","evidence":[…],"reason":"…"}
```

   system=“只输出一个 JSON 对象。”；解析用**裸 json.loads**（U/arbitrate.py:114）——
   未走 extract_json 容错，围栏/前后缀即炸（实测 referee_error：final300 1 条、ds300 2 条，O2）。
   text 取整篇 text_full 前 4000 字符——分歧证据在 4000 字之后的长文被截断（O8）。

3. **隔离硬断言**（U/arbitrate.py:60-64）：构造 Arbitrator 即校验 provider≠deepseek 且
   model ∈ {qwen3.8-max, kimi-k3, mimo-v2.6-pro, mimo-v2.6-flash}，违规直接崩（IsolationError）。

### 5.2 实测

final300：95 分歧 → A 56 / B 16 / C(新值+未提及) 22 / unresolved 1；legal_anchor 拦下 2 条未花模型钱；
by_field：outcome.type 39、fine 14、not_executed 11、decision_date 11、detention 13、behavior_date 7。
ds300 同构（82 条）。裁判结论以 decisions.jsonl 台账留档，装配 parsed-2 时作为分歧消解依据。

---

## 6. S3 校验层（模型产物的确定性验收，11 项）

注册表 U/s3.py:448-460：zones_tiling、schema、decision_present、outcome_consistency、penalty_caps、
article_edition、value_grounded、facts_quality、dates_order、subject、gambling_cross。
与模型的关系：S3 **不调模型**，但对站 1 输出做语义级反查——value_grounded 把模型给的金额/天数
与清洗文本数字集合（含中文大写反解 cn2int）比对、penalty_caps/article_edition 绑版本法条上限、
facts_quality 查结论句混入 facts。它定义了"接口之外还有一层确定性兜底"：站 1 的 validate 只保证
结构合法，值真实性靠 S3。final300 口径下 S3 error 率 22–41%（vs parse.py 83–98%）的拆解见 pilot300 报告。

---

## 7. 端到端实例（W-000630，真实链路）

1. S1：309 句中该件 zones 连续铺满，outcome 各值一次成功（attempts=1）。
2. build_inputs：facts 句+前置 meta 句拼原文切片，target=申请人写法。
3. A(deepseek)：`conduct.behavior_type={明确,"参与赌博",quote"对申请人及其他参与赌博人员进行了调查询问"(2337-2357)}`；
   B(xiaomi-flash)：同值但 `推断`+两条引文 → merge 记分歧。
4. C-batch(mimo-pro)：一次调用裁决全部分歧字段 → adopt A → merged `{明确, 值, 1 条带坐标引文}`。
5. labels.jsonl 落一行；_diag 记 n_diffs/n_unresolved/loc_fail。
全链路该件花费 ≈ ¥0.085（A+B+C 摊）。

---

## 8. 演化史：现行形态的来源（一站一条，供对照代码理解）

1. **seg-v1→v2**：摘引式（模型抄原文片段）→ 句表分区式（模型输出区间号）。引文命中 99.92% 但
   coverage 51 件失败 + 抄写损耗，分区改由结构校验（v4/v5）保证。
2. **百炼 404**：base_url 缺 `/v1` → 200 次无效烧钱；推理模型空返回 → 每 provider max_tokens/timeout。
3. **熔断事故**：共享参数下百炼连败拖死 deepseek、281 件 0 尝试——改 90s 窗 + 成功复位 + per-provider。
4. **首批 494 调用蒸发**（¥8.77 事故账）：C 裸 extract_json 崩溃 + 批尾写盘 → 改增量 append+raws+断点缓存+
   C 合并化（逐字段→记录级一次，调用数从 232 次/批降到 52 次/批 同分歧规模）。
5. **D-002 落地形式**：白名单+构造断言+起跑断言，代码写死不靠自觉。

---

## 9. 开放决策点清单（O1–O12：客观事实 + 待拍板，不做定性）

| # | 事实（行号证据） | 影响 | 候选处置 |
|---|---|---|---|
| O1 | C 仲裁原始响应不落 raws.jsonl（仅 A/B 落，U/run_elements.py:262-266 vs 359-365） | C 成果不可从 raw 恢复，重打付费 | C 改走 ElementsRunner.call 或补落盘 |
| O2 | 裁判解析裸 json.loads（U/arbitrate.py:114），不用 extract_json | 已实测炸 3 件（referee_error） | 一行换用容错 |
| O3 | legal_anchor 以两版本**较小**上限判死（U/arbitrate.py:72-73） | 2025 版合法值（罚 3000–5000、合并拘 16–20）会被误判死 | 按记录 edition 绑定上限（S3 已有 edition 判定可复用） |
| O4 | 站 2-5 无重试无熔断，站 1 有——策略不对称 | 402 类连败时每件仍先烧一次 A 调用 | 统一最低重试策略或 provider 级降级 |
| O5 | validate_teacher_output 的 issue 不反馈重试（U/run_elements.py:344-345） | 结构违规直接进 diff/manual，白花 | 违例回灌一次（站 1 同法） |
| O6 | 分歧判据含 status 与 evidence 坐标（U/run_elements.py:171-174） | 328 条 diff 相当比例是"值同壳异"，推高 C 调用 | value-only 判同 + status 差异降 warn |
| O7 | 公示族仍要求模型输出 zones 再覆写（U/s1.py:274-275,309-311） | 白花 output tokens | 公示族变体提示词去掉 zones 要求 |
| O8 | 裁判/仲裁正文截断 4000 字（U/arbitrate.py:112、U/run_elements.py:361） | 长文关键证据可能在窗外 | 截窗围绕分歧句邻域取 |
| O9 | elements 目录混三代代码账（C 逐字段 232/C-batch 52/A-fail 53 历史段） | 台账口径不一 | 新批用新 run 目录隔离代际 |
| O10 | 预估兜底 0.12/件 vs 实测 0.085/件 | 门槛过保守，可能误拒合法批次 | per_rec 用本 stage 实测中位 |
| O11 | 版本登记分散：seg-v2 硬码 U/s1.py:35，element-v1 在引擎侧 | 回溯需翻两库 | manifest/labels 已有字段，补一份版本对照表即可 |
| O12 | C-batch 降级逐字段调用不写独立 receipts（U/run_elements.py:375-387） | 降级流量在账本不可见 | 补 tag=C-degrade 回执 |

---

## 10. 成本快照（budget.jsonl 全量 + 站 1 心跳）

| 时间 | 批 | 件 | 成本 | 备注 |
|---|---|---|---|---|
| 10-18 03:37 | ds300/elements 首批 | — | ¥8.77 | 事故账（载荷丢失） |
| 10-18 03:50 | ds300/elements 二次 | — | ¥0.73 | 事故账（B-only 无产出） |
| 10-18 04:40 | final300/elements 33 件 | 33 | ¥3.73 | 停批重设计前有效成果（在盘） |
| 10-18 08:10 | final300/elements 55 件 | 55 | ¥4.69 | cap ¥12，预估门槛首跑 |
| （站 1） | final300 seg-v2 | 300 | ¥6.66 | 309 调用，progress.json |

历史累计口径（含调试期）见 spend-review-2026-10-18.md（¥56.4/浪费 ¥21）。**当前要素存量 88 件已配对落盘
（v1.1：结构合格仅 6 件，续批计划已按评审裁定停止，恢复路径=新契约新批）**。

---

## 附录 A：element-v1 字段契约全表（36 字段，运行时 teacher_system_prompt() 实录）

conduct.behavior_type｜BehaviorType｜本人的行为类型。只按事实描述判断，拿不准时选最接近的一项并标'推断'
conduct.role｜Role｜本人在赌博活动中的角色
conduct.method｜GamblingMethod｜赌博方式
conduct.times｜int｜赌博或提供条件的次数（场次）
conduct.duration_days｜float｜持续时间（天），如'持续三个月'记 90
conduct.cheating｜bool｜是否以作弊手段赢取财物（可能转为诈骗）
amounts.personal_stake｜AmountRange｜本人的赌资：本人用作赌注、换取筹码的款物及赢取的款物（元）
amounts.per_bet｜AmountRange｜单注或每局输赢的金额（元）
amounts.onsite_stake_total｜AmountRange｜现场查获的赌资合计（元）
amounts.cumulative_stake｜AmountRange｜累计赌资（元），多次赌博累计
amounts.commission｜AmountRange｜抽头渔利、头钱、水钱、台费等从赌博中获取的收入（元）。只有台费、场地费时也记在这里，但它本身不证明以营利为目的（见 intent.profit_purpose）
amounts.illegal_gain｜AmountRange｜其他违法所得（元）
persons.participant_count｜int｜参赌人数（同一场次在场参赌的人数，不含本人以外的围观者）
persons.cumulative_participants｜int｜累计参赌人数（多场次合计）
persons.minors_involved｜bool｜是否有未成年人参赌
persons.civil_servant｜bool｜本人是否为国家工作人员
persons.relatives_only｜bool｜参与者是否均为亲属
persons.abroad_organized_count｜int｜组织中国公民出境赌博的人数
venue.venue_type｜VenueType｜赌博场所类型
intent.profit_purpose｜bool｜是否以营利为目的。只记两类依据：原文对本人写明'以营利为目的'或'营利性赌博'，或原文写明本人抽头、渔利、收头钱水钱、坐庄获利——都标'明确'为是；本人是场所或条件提供者、原文写了现场有抽头头钱但没说谁收的，标'推断'为是；原文写明'不以营利为目的''娱乐消遣'的标'明确'为否。赌资或输赢金额大小、赌博方式、被当场查获、只收台费场地费、平台名里的'娱乐'、所引法条原文、'构成赌博'等定性用语都不是依据，此时标'未提及'。对其他参赌人的营利事实不算本人的
circumstances.last_prior_penalty_date｜date｜本人最近一次受治安管理处罚的决定日期；只写到月份时取该月 1 日并标'推断'
circumstances.surrendered｜bool｜是否主动投案
circumstances.truthful_statement｜bool｜是否如实陈述违法事实
circumstances.admits_and_accepts｜bool｜是否承认违法事实并愿意接受处罚（认错认罚）
circumstances.remedied_consequence｜bool｜是否主动消除或减轻违法后果
circumstances.victim_forgiveness｜bool｜是否取得被侵害人谅解
circumstances.coerced_or_lured｜bool｜是否出于他人胁迫或诱骗
circumstances.meritorious｜bool｜是否有立功表现
circumstances.instigated_others｜bool｜是否教唆、胁迫、诱骗他人参与
circumstances.retaliation｜bool｜是否对报案人、举报人、证人打击报复
circumstances.obstructed_police｜bool｜是否阻碍民警执行职务
circumstances.minor_circumstance｜MinorLevel｜原文明确认定的'情节轻微'或'情节特别轻微'（只记原文认定，不自行判断；2012 版减轻条件是'特别轻微'，2025 版是'轻微'）
circumstances.first_offense｜bool｜是否初次违反治安管理：本次是第一次被公安机关发现或查处（公通字〔2007〕1号第五项）。曾有仍在追究时效内的违法、曾因不满十六周岁不执行拘留、曾经调解结案、曾被收容教养或劳动教养、曾被判处刑罚或免除刑事处罚的，都不算初次
circumstances.violations_last_year｜int｜本次行为前一年内违反治安管理的次数
person.age｜int｜行为时的周岁年龄
person.pregnant_or_nursing｜bool｜是否怀孕或哺乳自己不满一周岁的婴儿

## 附录 B：关键文件行号索引

| 文件 | 本文引用段 |
|---|---|
| U/s1.py | 58-92 提示词；95-104 用户装配；109-150 Provider；173-203 validate；237-256 熔断；262-352 extract_one；358-372 config；382-398 抽样；401-510 main |
| U/run_elements.py | 39-45 契约 import；53-108 build_inputs；116-154 locate；157-195 merge；198-223 candidates；226-233 ADJ；238-271 Runner.call；329-405 记录流程；414-436 断点+预估门槛；438-461 增量落盘 |
| U/arbitrate.py | 39-41 白名单；43-53 REFEREE_PROMPT；60-64 隔离断言；67-91 法律锚；107-128 referee；131-153 resolve |
| U/progress.py | 25-41 分类；44-77 CostMeter；79-178 Tracker；159-178 原子写 |
| E/element_labels.py | 17 版本；50-73 schema；76-89 系统提示；92-104 messages；137-188 validate |
| $D/config/s1_models.json · s1_prices.json | 参数与价目全景（§1.2/1.3） |

*本文与代码逐条可核；发现与实现不符处以代码为准并升版本修订。*
