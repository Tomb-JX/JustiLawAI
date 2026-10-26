# 现行状态（2026-10-22）：要素供给、字段/前科闭环、千问 S1、706 湖文本批
> **归档注记（2026-10-26，协调线提交时加）**：本文件为 2026-10-22 协调快照，数据侧现状已被
> main 的 [data-pipeline-status.md（10-26 核对版）](./data-pipeline-status.md) 取代、引擎侧以
> [engine-line-status-2026-10-26](../05-research/engine-line-status-2026-10-26.md) 为准；
> 实时状态看 `$DATA/coordination/CURRENT.md`（events.jsonl 自动渲染）。本文保留为过程历史。


> **本文是 2026-10-22 的现行状态主文档。** 之前 2026-10-18/10-20/10-21 的 BOARD、handoff、
> EXPANSION-STATUS、I-25 §1–7 保留为历史过程；冲突时以本文为准。
> 数据根 `$DATA = D:/02_Dev/Data/justilaw-research`。
> 全项目 L0–L5/S0–S4/M0–M6 的分层状态见 [PROJECT-PANORAMA-STATUS-2026-10-22.md](./PROJECT-PANORAMA-STATUS-2026-10-22.md)。
> 不训练 M1/M4、不改发布门槛、不打开 203 封存 test；所有新标签仍是 training-only silver。

## 1. 一句话

909 条扩产标签已完成 `times` 统一修正并可过 schema，但仍是 training-only silver；
字段/前科类型化闭环已在 37+12 条样本跑通（当前结果泄漏 0、8 条前科残余恢复）；
千问 3.7-flash 单条 S1 成功、12 条约 DeepSeek 1/8 费用，但 30 条被 Arrearage 截断；
706 条湖文本批已换新根 `lake-text-706b` 重跑 pilot12 12/12；full **567/706 incomplete**（139 missing；113 Arrearage + 9 outcome 数值 + 4 timeout + 4 clause ID + 3 budget + 6 无诊断），¥10.618；no active。

## 2. 909 条扩产标签：已修/未修

### 2.1 已修

- `times`：903 未提及 / 6 非空（1×明确1、3×明确2、1×推断18、1×推断null）；
  212 条“无次数字样但 times=1”已降未提及；禁止“推断 + value=1”。
- 909/909 引擎 schema 通过；原始标签包保留，修正包在 `labels-909-timesfix/`。
- 证据引文泄漏词 0；36 字段齐全；4,731 段证据。
- 8 条前科残余、16 条 A 类结果行不在 909；新字段/前科层已能恢复 8 条前科残余。
- 拆分：train 763 / valid 146 / test 0；726 事件；与 203/test 无事件重叠。

### 2.2 未修（仍是 training-only 的原因）

| 问题 | 现状 | 影响 |
|---|---|---|
| M1 证据坐标 | 4,731 段中 **587 段/219 条**无法回投原文连续引文（恢复批 585/218） | M1 `located=True` 训练未就绪；M4 值特征可用 |
| 57 条复议 | 54 条视图含当事人语言，38 条证据引用复议语言，53/57 单模型 | 结构性任务污染，应路由 review/outcome |
| 26 条前科 | 23 明确 + 3 推断；`2a14` 把本案处罚当前科（假阳性）；4 条 `first_offense=未提及`；3 条无日期 | 旧标签需逐条审计，不能直接训练 |
| 199 条公示 | 约 89 条字段/表头结构；36 无候选、36 meta-only；“违法事实”常为空 | 应 outcome-only/选择排除，不是要素事实来源 |
| 新字段/前科视图未落到 909 | 37+12 条样本通过，909 仍是旧视图 | 换视图会改 `view_hash`，需重校验/重标 |
| 模型来源 | 125 三模型（单域降级）+ 784 单模型；无真三向、无人工金标 | 只能 silver，不能当准确率/正式测试 |

**结论：909 可做 M4 值特征试点（排除 11 条 S1 非赌博、146 valid 只作分布诊断），
不能做 M1 原文定位训练，不能当 gold/parsed-2/正式测试。**

## 3. 字段/前科类型化闭环（已实现，样本通过）

### 3.1 实现

- `research/discretion/unify/field_table.py`：
  - 标签 → role（person/case/prior/outcome/other）的字段词汇表；
  - 解析 pkulaw 页头、公示字段表、身份/前科块为字段 ID + span；
  - `build_field_inputs`：facts 扣除字段/前科 span；meta 只收 person/prior；outcome 永不进视图；
  - `build_prior_records`：date/date_status/explicit_none/subject_binding/source_ref。
- `s1.py` 新增 `prior_sentence_ids`（只回句子 ID，不抄原文）；`run_seg.py --prior-refine` 校验。
- 没有为前科/meta 再发额外模型调用：zones/outcome/prior 句 ID 同一次 S1。
- 字段解析器是本地确定性代码，不写 quote；未知标签 role=other 不进视图。

### 3.2 测试

| 样本 | 结果 |
|---|---|
| 37 条离线（8 残余 + 3 无日期 + 26 旧前科） | 37/37 建视图、target 37、outcome 0；8 条残余 8/8；22/26 前科可定位；19/26 日期 |
| 12 条 qwen3.7-flash | 11/12 有效；14 调用 ¥0.075；11/11 建视图/target/outcome 0；prior 10/11；86f1 恢复、2a14 正确空；63ae zone 覆盖失败 |
| 12 条 qwen 11 + DeepSeek 1 回退 | 12/12 建视图/target/outcome 0；prior 11/12（唯一空是 2a14 假阳性） |
| 30 条 qwen3.7-flash | 11/30 qwen（全是 pkulaw）+ 19 旧 DeepSeek 回退；18 Arrearage + 1 timeout；费用 ¥0.082；**不是 qwen 30 条成绩** |
| 30 条 qwen3.7-flash 新 key（30c，完成） | 26/30 qwen 输出；4 诊断（2 zone 覆盖 + 2 review outcome.type 非法）；4 条 DeepSeek 回退；¥0.235；视图 outcome 0 |

### 3.3 关键质量发现

- `2a14` 旧标签把本案 2021-12-21 罚款当前科；新链路返回空，正确。
- `86f1`（“六个月内曾受过治安管理处罚”）DeepSeek 漏、qwen3.7 找回。
- `00760` 原文只到月，prior 日期记 2011-07-01 **推断**，不再标“明确”。
- 63ae 在 qwen3.7 上稳定返回 `zones to=12 ≠ 14`，需要 fallback 或定向 repair；不是 token/预算问题。

## 4. 千问 S1：价格、配置、当前状态

### 4.1 官方北京按量价（元/百万 tokens）

| 模型 | 输入 | 输出 | 备注 |
|---|---:|---:|---|
| qwen3.7-flash | 0.2 | 0.8 | ≤32K；32–256K 0.6/2.4；256K–1M 1.2/4.8 |
| qwen3.8-flash | 0.8 | 2.7 | ≤1M；支持结构化输出 |
| qwen-flash | 0.15 | 1.5 | ≤128K；输入更便宜、输出更贵 |
| qwen3.6-flash | 1.2 | 7.2 | 旧价，反而更贵 |
| deepseek-flash（基准） | 2 | 8 | 原 S1 约 ¥29.5/1000 |

S1 prompt 约 2K，qwen3.7-flash 落 0–32K 档；12 条 qwen 费用 ¥0.075，DeepSeek 同 12 条 ¥0.62。

### 4.2 连接/配置

- 工作区 MaaS `ws-...maas.aliyuncs.com`：**403 Workspace endpoint access denied**；
- 公网 `dashscope.aliyuncs.com`：**200**，qwen3.7/3.8 均可用；
- 配置已切公网 + 新 key；`bailian` / `bailian-37-flash` / `bailian-max` 同步；
- `bailian` 与 `bailian-37-flash` 的 `max_tokens` 均已提到 64000，避免 qwen 长输出触发 reservation；
- 1 条 S1 端到端成功：prior [6]、无诊断、¥0.0048、completion 5,606/reasoning 4,724；
- **key 已在对话暴露，测试后必须轮换/作废；不写入仓库。**

### 4.3 qwen 质量注意

- qwen3.7-flash 默认 thinking，12 条平均 completion 6,270、reasoning 5,302；
- 30 条 qwen 11 条 pkulaw 全部建视图/target/outcome 0，但 web/public/review 没测到（Arrearage）；
- 30c 新 key 已完成：26/30 qwen 输出、4 诊断（2 zone 覆盖 + 2 review outcome.type 非法）、4 条 DeepSeek 回退；视图 outcome 0；web/public 分别 5/6、6/6，review 3/5；review 的失败正是应路由 review/outcome 的证据。
- 仍未做：非 thinking/low effort、从 S1 基础提示词移除 `meta_fields`、Arrearage/access denied 硬停、自动 fallback。

## 5. 706 条湖文本批

- 来源：数据湖 3,194 条筛选后的 **706 条待 S1**（train 561/337 事件，valid 145/72 事件）；
  队列冻结在引擎工作树 `research/data/lake-text-s1-batch-20261021/`，有输入 SHA-256。
- 旧批 `lake-text-706-20261021`：pilot12 只有 5/12 成功，7 条 Arrearage，已停；
  不能原地续——provider `max_tokens`/价格变化触发 `execution_settings_changed`。
- 新批 `lake-text-706b-20261022`：复用同一 706 队列，新根目录、新 execution manifest；
  - 模型 qwen3.8-flash，clause-refine；
  - pilot12 **12/12**；full **567/706 incomplete**（139 missing；113 Arrearage + 9 outcome 数值 + 4 timeout + 4 clause ID + 3 budget + 6 无诊断），¥10.618；no active；
  - 状态：`status.json` = `incomplete`；`missing-ids.json` 139 条；`INCOMPLETE-SUMMARY.json`。
- 706 批只产 S1 facts/decision/outcome 文本观察值，不跑 L5、不当金标；pilot 质量门和预算 cap 仍按原计划。

## 6. 当前优先级

1. **收 706b 剩余 139**：30c 已完成（26/30）；706b full 567/706 incomplete，139 missing（113 Arrearage），top-up 后 resume；看 qwen3.8 有效率/费用/fallback。
2. **909 落地字段/前科视图**：先路由 57 复议、89 字段表；再审计 26 前科（2a14/4 条 first_offense/3 无日期）；再重校验/重标受影响记录。
3. **M1 证据坐标**：587 段/219 条逐字段降级或拆原文连续 span；M1 located 训练前必须复跑。
4. **S1 工程化**：Arrearage/Access denied 硬停；zone 失败自动换 provider；非 thinking/去 meta_fields 短提示词；12→30→100 阶梯。
5. **不再**：直接全量 909 重标、把 qwen 30 的 19 条回退当 qwen 成绩、把 706 的 S1 文本观察值当金标、在对话里传 key。

## 7. 产物索引

| 内容 | 路径/文件 |
|---|---|
| 909 修正包 | `$DATA/s1_runs/expansion-1000-20261021/labels-909-timesfix/` |
| 909 审计 | `.../labels-909-audit.json`（旧口径，见引擎复核的 587/219） |
| 字段/前科实现 | `research/discretion/unify/field_table.py`、`s1.py`、`run_seg.py` |
| 字段/前科报告 | `.../FIELD-PRIOR-CLOSED-LOOP.md`、`.../NON-SENTENCE-FIELD-AUDIT.md` |
| 37 条机器结果 | `.../FIELD-PRIOR-CLOSED-LOOP.json` |
| 12 条 qwen 报告 | `$DATA/s1_runs/qwen37-prior-test2-20261021/QWEN37-PRIOR-TEST.md` |
| 30 条 qwen 报告 | `$DATA/s1_runs/qwen37-30b-20261021/QWEN37-30-TEST.md` |
| 30c 完成（26/30） | `$DATA/s1_runs/qwen37-30c-20261022/seg-run/` |
| 706b incomplete（567/706，139 missing） | `$DATA/s1_runs/lake-text-706b-20261022/`；`missing-ids.json`、`INCOMPLETE-SUMMARY.json` |
| 706 原计划 | 引擎 `docs/05-research/lake-text-s1-batch-plan-2026-10-21.md` |
| 价格/模型配置 | `$DATA/config/s1_prices.json`、`$DATA/config/s1_models.json`（凭据不入库） |
