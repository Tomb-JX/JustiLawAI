# 裁量能力层：封装、模型配置与可追溯设计（草案）

> 版本 v0.1（草案，待评审）· 2026-10-28
> 关联：
> - [两类服务设计](./discretion-services-design.md) §6；
> - [API 契约](./api-contract.md) §3.12（草案）；
> - [算法文档](../06-algorithm/README.md)：ADR-001、ADR-007、ADR-009。
>
> 负责人要求：
> - 抽取、分段等模型调用直接复用已有信息处理链路的逻辑，只把模型配置改成平台模型管理的形式，可自定义、可调控；
> - 计算器和决定书审查都用要素，不用文本模型；
> - 先探查基座、做好契约与封装，不贸然接入；
> - **裁决逻辑全方位展示、可追溯，不做算法黑箱。**

## 1. 探查结果

### 1.1 应用基座

| 部件 | 现状 | 对能力层的意义 |
|---|---|---|
| 模型网关 `app/model_gateway/gateway.py` | 供应商体系（Ollama / OpenAI 兼容）；平台模型 ID 形如 `ollama/qwen3.5:9b`、`<provider_id>/<model>`；按能力标签路由（completion / embedding / vision / tools / thinking）；默认对话、嵌入模型存在 `settings_db`，管理员通过 `PUT /settings/models` 修改 | 能力层的模型调用一律走网关，按平台模型 ID 选模型 |
| 网关调用接口 | `stream_chat(model_id, messages, params, thinking)`、`complete(...)` 返回（全文, usage）；`params` 只透传 temperature、top_p、max_tokens | **缺口**：没有结构化输出（Ollama `format` / OpenAI `response_format`）、没有 seed、没有调用回执。抽取与分段需要这三样 |
| 设置存储 `app/store.py` | `settings_db`（JSON），平台设置都存在这里 | 能力层的模型槽位配置存在这里，与默认模型并列 |
| 对话与智能体 `app/routers/chat.py` | 智能体注入 system_prompt；SSE 事件里已有 `tool_call`；`card` 事件已预留（`card_type: prediction / case_list / risk_list / document`），尚未实现 | 对话引导以后用 `card_type: "discretion"` 出卡片 |
| 工作流 `app/workflow/engine.py` | 节点：start / llm / retrieval / branch / http / reply | 以后可加 `discretion` 节点；本期不做 |

### 1.2 已有信息处理链路（`research/discretion/unify/`）

| 步骤 | 已有实现 | 模型调用方式 |
|---|---|---|
| 清洗与句表 | `cleanse.cleanse`、`sentence_table`（确定性） | 无 |
| 分段与结果解析（S1） | `s1.py`：编号句表 → 分区（facts / evidence / reasoning / decision / review / meta）、本人、处罚结果、日期、复议结果、是否赌博；`validate` 结构校验；`zoning.merge_fact_fallback` 兜底 | 自带的提供商配置 `$DATA/config/s1_models.json`（OpenAI 兼容）、temperature 0、JSON 输出、重试换提供商、全程回执 |
| 要素抽取 | `run_elements.py` + `element_contract.py`：按 facts / meta 视图组织输入，要素证据按句号定位，`validate_located` 校验，归一化（E-05） | 同上，复用 `s1.load_config` |
| 引擎版抽取原型 | `app/discretion/extract.py`：直连本机 Ollama，JSON Schema 受限解码，证据模糊定位 | 写死地址与模型，不走网关 |

结论：链路逻辑完整、可复用；需要改的只是**模型调用入口**，从自带配置或写死地址，改成平台网关加可配置的模型槽位。

## 2. 能力层结构

```
文本（笔录 / 叙述 / 决定书）
  │ ① 清洗与句表（确定性，复用 cleanse）
  │ ② 分段与结果解析（模型槽 segment，复用 S1 提示与校验）
  │ ③ 要素抽取（模型槽 extract，复用 element_contract 提示、句号证据、归一化）
  ▼
要素草稿（每个字段：值、状态、证据、来源）
  │ ④ 人工确认 / 修改（界面；修改留痕）
  ▼
确认后的要素 + 辖区 + 日期 (+ 拟处罚 / 实际处罚)
  │ ⑤ 法律内核（确定性）：适用法律 → 法定空间 → 修正情节 → 省级定档 → 成文种类与候选
  │ ⑥ 实务参照（学习，线性模型，可分解）：RAP 无文本版
  │ ⑦ 档内数额（统计）：全国按种类分布，法定幅度过滤
  │ ⑧ 偏离检查（确定性对照）：法定空间 / 基准档位 / 实务分位
  │ ⑨ 补查提示（确定性）：哪项要素能收窄候选
  ▼
结果 + 完整追溯记录（trace）+ 审计存档（run）
```

- 计算器（A）：从 ④ 或直接从要素进入，走 ⑤–⑨。
- 公众预期（B）：叙述 → ②③ → ④ 由用户确认 → ⑤–⑦、⑨。
- 决定书审查（C）：决定书 → ①②③ → ④ 可选 → ⑤–⑧，"实际处罚"取自 ② 的结果解析。

**不用文本模型**（ADR-009、C-42）：⑥ 只用规则结论与结构化要素。

## 3. 模型配置：可自定义、可调控

### 3.1 模型槽位

| 槽位 | 用途 | 默认 | 关键参数 |
|---|---|---|---|
| `segment` | 分段与结果解析（S1） | 平台默认对话模型 | temperature 0；JSON 输出；max_tokens；thinking 开关；超时；重试次数；备用模型 |
| `extract` | 要素抽取 | 平台默认对话模型 | 同上；另加"单次 / 多次采样投票"（M1 按需升级） |

- 配置存在 `settings_db["discretion"]["models"][slot]`，形如 `{model_id, params, fallback_model_id}`。
- 只能选平台已登记、带 `completion` 能力的模型。
- 管理员可改；普通用户只能在单次请求里，从管理员允许的列表中选模型。
- 每个槽位绑定**提示版本**（如 `seg-v2`、元素提示指纹）。提示属于代码版本，不在界面上改，保证可复现。

### 3.2 网关需要补的三样（只扩展，不改现有行为）

1. **结构化输出**：`params.response_schema` → Ollama 传 `format`，OpenAI 兼容传 `response_format: {type: json_schema}`；模型不支持时退回"JSON 模式 + 解析校验"。
2. **确定性参数**：`params.seed` 透传（支持的供应商才传）。
3. **调用回执**：返回实际供应商、真实模型名、usage、耗时，供追溯记录使用。

## 4. 可追溯设计（核心原则：不做黑箱）

### 4.1 原则

1. **每个结论都有出处**：
   - 规则结论 → 条文原文（规范库 ID + 逐字原文 + 版本）；
   - 学习结论 → 模型名、版本、训练数据规模与哈希；
   - 统计结论 → 样本数与口径。
2. **规则与学习分开展示**：成文结论（法律怎么说）与实务参照（历史上实际怎么罚）并列，不混成一个数；学习部分明确标"参照，不是法律结论"。
3. **计算过程可读**：定档写成"本人赌资 600 元 ∈ [500, 1000) → 第二档 → 处五日以下拘留"，而不是只给档位名。
4. **学习部分可分解**：RAP 是线性模型，每个要素对每类处罚的贡献可以精确拆开，全部展示。
5. **要素可溯源**：每个要素记录值、状态（明确 / 推断 / 未提及）、证据原文与位置、来源（人工填写 / 模型抽取 / 抽取后人工修改）。
6. **缺什么、为什么定不了，明说**：未知条件、候选从何而来、补哪一项能收窄。
7. **可复现**：每次运行存档，记录引擎版本、规范库版本与哈希、schema 版本、模型调用回执、输入哈希；按 run_id 可以完整取回。

### 4.2 追溯记录结构（trace）

```json
{
  "run_id": "dr_…",
  "created_at": "…",
  "versions": {"engine": "de-0.2.0", "norm_library": "…@sha", "schema": "1.2.0", "practice_model": "rap-nt-…@sha"},
  "inputs": {
    "region": "320000", "behavior_date": "…", "decision_date": "…",
    "elements": {"amounts.personal_stake": {"value": {"min": 600, "max": 600}, "status": "明确",
                  "origin": "extracted_then_confirmed", "evidence": [{"quote": "…", "sentence": 7, "span": [120, 138]}]}},
    "proposed_or_actual": {"type": "罚款", "fine": 500, "source": "proposed | decision_document"}
  },
  "steps": [
    {"id": "law", "title": "适用法律", "status": "determined", "result": "治安管理处罚法（2012 修正）",
     "reasoning": "行为日 …、决定日 …，从旧兼从轻 …", "basis": [{"ref": "…", "text": "原文"}]},
    {"id": "legal_space", "title": "法定处罚空间", "result": {"一般": "…", "情节严重": "…"}, "basis": ["…"]},
    {"id": "modifiers", "title": "修正情节", "result": [], "unknown": ["…"]},
    {"id": "band", "title": "省级基准定档", "status": "determined | candidates | unknown",
     "measure": "本人赌资", "value": 600, "thresholds": [100, 500, 1000], "category": "其他赌博活动",
     "computation": "600 ∈ [500, 2000) → 第一档", "band_text": "处500元以下罚款",
     "basis": [{"ref": "苏公规〔2019〕1号 三(一)2", "text": "原文"}], "unknown_conditions": []},
    {"id": "written_type", "title": "成文处罚种类", "result": "罚款", "route": "rule_single", "candidates": ["罚款"]},
    {"id": "practice", "title": "实务参照（历史决定统计，非法律结论）", "distribution": {"罚款": 0.82},
     "model": {"name": "RAP 无文本版", "version": "…", "trained_on": {"n": 391, "sha256": "…"}},
     "contributions": [{"feature": "规则唯一=罚款", "effect": {"罚款": 1.9, "拘留": -0.7}}],
     "note": "与成文结论不一致时见 deviation"},
    {"id": "amount", "title": "档内数额参照", "distribution": {"fine": [[500, 0.47]]}, "source": {"n_events": 750, "scope": "全国、旧法时期、按种类"}},
    {"id": "deviation", "title": "偏离检查", "levels": [
      {"level": "legal_space", "ok": true}, {"level": "written_band", "ok": true},
      {"level": "practice", "percentile": 0.6, "ok": true}]},
    {"id": "missing", "title": "补查提示", "items": [{"field": "conduct.gambling_form", "why": "江苏两类门槛不同", "effect": "可把候选 {罚款, 拘留} 收窄为一个"}]}
  ],
  "model_calls": [{"slot": "extract", "platform_model_id": "…", "provider": "…", "prompt_version": "…",
                   "input_sha256": "…", "output_sha256": "…", "latency_ms": 0, "usage": {}}],
  "needs_review": ["…"],
  "disclaimer": "仅供辅助参考，不构成法律意见；结论须由办案人员审核确认"
}
```

### 4.3 界面展示要求（给前端）

- **结论卡**：成文结论与实务参照并列；有偏离时显著标出。
- **推理链**：按 steps 顺序逐步展开，每步都可点开看原文依据。
- **要素表**：每个值可点开看证据原文，高亮在原文中的位置；标出来源（人工 / 抽取 / 改过）。
- **学习部分**：贡献条形图，加训练数据规模与"参照"标识。
- **审计**：显示 run_id，可导出完整记录。

### 4.4 追踪信息由谁产生、现状如何（2026-10-28 实测引擎第一版）

实测输入：江苏、麻将、组织形式"其他"、本人赌资 600 元、2023 年。

| 追踪项 | 由谁产生 | 现在接口有没有 | 缺口 |
|---|---|---|---|
| 适用法律及理由 | `norm_layer.assess` | **有**：`law_id`、`temporal_note`（"行为时与决定时均适用……2012年修正"） | 无 |
| 法定处罚空间 | `norm_layer._statutory` / `_mitigated` | **有**：各档 options（拘留区间、罚款区间、`via`、`basis` 如 `psal-2012#70`） | 只给条文 ID，**不给原文**；原文在规范库里已有（`NormLibrary.cite` 能取到第七十条全文），只差一步解析 |
| 修正情节 | `_active`、`_not_executed` | **有**：`directions`、不执行拘留理由 | 未触发时为空，不说明"查过哪些、因未知而未判定" |
| 涉刑提示 | `_referral` | **有**：`referral` | 无 |
| 省级定档 | `_stake_threshold` | **部分**：档位名、档位处罚原文、用到的度量名（"个人赌资"）、基准文号、核验状态、未知条件、状态 | **缺计算过程**：没写用的是哪个数值（600）、哪一类门槛（江苏"其他赌博活动" 500 / 2000 / 5000）、比较结果、是否用了一场赌资托底或升档；**缺条款原文**：只有文号，没有对应档位的条款句。函数内部这些变量都有，只是没输出 |
| 成文种类与路由 | `decide.band_types`、`decide` | **有**：`penalty_type`、`route`、`candidates` | 无 |
| 档内数额 | `decide._legal_distribution` | **部分**：取值与占比 | 数据来源在 `band_quantities.json` 元数据里（样本事件数、旧法时期、源文件 sha256），没有输出 |
| 要素来源与证据 | 输入方 | **没有**：接口只收裸值，分不出人工填写、抽取还是修改过 | 请求与 `Facts` 都需要带 status、evidence、origin |
| 实务参照及贡献分解 | RAP | **没有**：只在研究脚本里 | 导出系数；RAP 是逻辑回归，贡献 = 系数 × 标准化特征值，可精确分解 |
| 偏离检查、补查提示 | 新增 | **没有** | 待实现 |
| 模型调用回执 | 网关 / 抽取 | **没有**：抽取未上接口 | 复用 S1 链路的回执格式（`receipts.jsonl`：提供商、模型、提示版本、请求与响应摘要 sha256、耗时、token，密钥掩码） |
| 版本与存档 | 新增 | **没有**：无引擎版本、规范库版本或哈希、schema 版本、run_id，也不存档 | `SCHEMA_VERSION`、各 YAML 的版本与核验信息都已有，只差汇总；存档用 `store.JsonDB` 或单独文件 |

小结：
- 规则引擎已经产出了**结论层**的结构化追踪：用了哪部法、法定空间、档位名、依据文号、未知条件。
- 还缺**计算层**：具体数值与门槛的比较、条款原文。
- 还缺**来源层**：要素证据、版本、存档。
- 这些信息在函数内部或数据文件里大多已经存在，属于"没导出"，不是"算不出"。
- 学习部分（RAP）与模型调用目前完全没有对外暴露。

## 5. 不做的事（本期）

- 不接文本模型（ADR-009）。
- 不在线训练；RAP 系数随版本发布，换版本即换 `practice_model` 版本号。
- 不在界面暴露提示词编辑（保证可复现）；提示随代码版本走。
- 对话引导、工作流节点、类案检索，等契约评审后再排期。

## 6. 实现顺序（契约评审通过后）

1. 网关扩展（结构化输出、seed、回执）与模型槽位配置；
2. `assess`：⑤–⑨ 与 trace（不依赖模型，先做）；
3. `parse` / `extract`：把 S1 与要素链路的模型入口改到网关；
4. `review`：串起 ①–⑧；
5. run 存档与查询；
6. 前端：推理链与要素证据展示。

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-28 | v0.2 | 加 §4.4：追踪项由谁产生、现状与缺口（实测引擎第一版） | 引擎（规则链路） |
| 2026-10-28 | v0.1 | 草案：基座与信息处理链路探查；能力层九步结构；模型槽位与网关扩展；可追溯设计（原则、trace 结构、界面要求）；实现顺序 | 引擎（规则链路，负责人指示） |
