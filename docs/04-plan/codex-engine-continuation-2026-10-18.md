# 引擎线续跑交接（深版 · 2026-10-18 · 额度耗尽后）

> 你的角色：**引擎与验收负责人**。独立闸门：规范库、要素本体、M1/M2/M4、验收与一致性唯一实现。
> 工作树 `.claude/worktrees/discretion-engine`，分支 `worktree-discretion-engine`，最后提交 `aeb29b6`。
> **有未提交工作**：`m1_dev_slice_probe.py` 修改；`m2_dev_slice_audit.py`、`m4_negative_diagnosis.py`、`slice_quality_review.py` 新增；M2/M4 结果已产出（10:29/10:33）。只读备份 `$DATA/handoff/2026-10-18/engine/`。

## 1. 你负责的模块（一张图）

```
M0 知识层：schema.py（36 要素+3 meta）· norms/（国层 2012/2025 + 省级两省）· records.py（数据契约）
   │
M1 抽取：extract.py（本地 qwen3.5:9b 零样本原型；学生端，不产标签）
   │            ↕ 契约：element_labels.py（教师 prompt/输出/证据校验，36 字段）
M2 规范层：norm_layer.py（时间效力、Ω、修正情节、涉刑提示；确定性）
   │
M4 裁量：首跑只做多数类 / B4 文本基线 / 简单特征基线（research/eval/dev_slice_first_run.py）
   │
验收：accept_delivery.py（交付）· accept_element_labels.py（I-20 要素）· metrics.py / agreement.py（唯一实现）
```

**分工原则**：引擎定义“什么是正确”（本体/规范/验收），后处理线负责“把文本变成候选并运输”。引擎**不编辑** `research/discretion/unify/**`。

## 2. 模块地图（逐个知道它为什么存在）

| 模块 | 职责 | 关键不变量 |
|---|---|---|
| `schema.py` | 36 可抽取字段（7 组）+3 meta；`Extracted{value,status,evidence}`；`AmountRange`；`KEY_FIELDS` 10 | 字段唯一来源；1.1.0：开口金额 `max=null` 不补上界；营利目的只记原文认定/本人获利事实；不新增字段 |
| `extract.py` | M1 原型：本地 qwen3.5:9b、JSON Schema 受限解码、证据定位、代码规范化 | **只作学生端推理诊断，不产标签**；证据找不到即丢弃；值类型/枚举按 schema |
| `element_labels.py` | 教师提示/输出 schema/校验：36 字段、`{status,value,evidence}`、`quote`、`located=True` 时校验坐标 | 一条输入一名本人；未提及⇒value null/evidence 空；有值⇒证据；不调用模型 |
| `norm_layer.py` | M2：时间效力、合法空间 Ω、修正情节、涉刑提示 | 纯法律确定性推导；不经验打分；不修改历史观察处罚；三值逻辑（是/否/不清楚） |
| `records.py` | parsed/delivery 记录契约与逐条校验 | 字段/枚举/版本；`records check --layer parsed`；交付层不混内部字段 |
| `norms/` | 规范库 YAML：条文逐字、效力区间、罚则、modifiers | 以法宝原文核对；省级分档独立；改条文需版本/签字 |
| `research/eval/accept_delivery.py` | 交付验收：三档结论、版本门控 | r6=format-only；新契约只对新版本；0 error 才可标注 |
| `research/eval/accept_element_labels.py` | I-20 验收：结构/证据/数值/A-B 分歧 | 200–300 件；证据≥95%；A/B 配对；分歧 >20% 回修告警（与脚本 pilot_pass 口径待统一） |
| `research/eval/metrics.py` | 指标唯一实现 | 改公式=改门禁，须登记偏离 |
| `research/eval/agreement.py` | κ 唯一实现（union 口径） | all/valued 只作对照，不得引为过线 |
| `research/eval/key_field_presence.py` | 关键字段文本出现率 | **关键词代理，不是字段真值**；不能强迫标签比例 |
| `dev_slice_first_run.py` | 首跑：切片核查 + 多数类/B4 | 只用 `input.views`；`observed_outcome` 只作目标；test 未动；不调参 |
| `m1_dev_slice_probe.py` | M1 诊断：本地模型按处罚类型取样 | 只报结构/证据/丢弃；不报准确率；不产标签 |
| `m2_dev_slice_audit.py` | E-01 合法空间核对 | 不修改观察值；冲突单列；版本/条号/合并执行分开 |
| `m4_negative_diagnosis.py` | E-03 负结果诊断 | 混淆矩阵/类不平衡/长度；不在 val/test 调参 |
| `slice_quality_review.py` | E-02 切片语义复核 | 只报告不改切片；P-1216 归属待复核 |
| `anchor_a2/` | CAIL 刑事基线 | 刑事结果不能外推行政；只作方法背景 |
| `pkulaw_mcp/` | 法宝 MCP 调用层（预算/缓存/台账） | 只用 `--workstream data` 记账；不绕过限额 |

## 3. 六个必须记住的契约

1. **字段唯一来源**：36 字段＋枚举＋状态＋金额/营利口径由 `schema.py`/指南定义；任何改动升版并在指南中写裁决规则。
2. **三态与证据**：`未提及`⇒无值无证据；`明确/推断`⇒有值＋逐字证据；证据必须支持该值。
3. **开口金额**：`min=X, max=null`，禁止按数量级补上界；"X 余元"按末位非零数位；“带等”上界空。
4. **营利目的**：只记原文对本人“以营利为目的”认定，或本人抽头/渔利/头钱等获利事实；赌资、方式、只收台费、平台“娱乐”、法条原文都不是依据。
5. **历史观察 vs 规范结论**：实际处罚是训练目标/观察值，规范层不得改写；F5 分离；规范冲突单列。
6. **验证纪律**：无独立参考 ⇒ 字段准确率“暂缺”；本地模型只诊断；test 不参与训练/选参；小样本不宣称显著。

## 4. 常见坑（现象→后果→做法）

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 把本地模型输出当标签 | 训练集被弱模型污染 | 本地只诊断；标签用远程教师＋仲裁 |
| 无参考报准确率 | 内部一致率冒充正确率 | 标“暂缺”；先产出 reference_elements |
| 用处罚上限改写观察值 | 训练目标被规范层重写 | 保留观察值；冲突单列；F5 分离 |
| 把“情节严重/从轻”当输入 | 用处罚后信息预测处罚 | 作标签/待预测目标；部署可知才可作输入 |
| 在 val/test 调参 | 乐观偏差 | 参数预固定；val 只评估；test 不动 |
| 用完整 `source_text` 当特征 | 答案泄漏 | 只用 `input.views`/facts |
| 事件随机划分 | 同一事件跨集泄漏 | 用切片 `development_split`（事件级） |
| 忽略类别不平衡 | 罚款 F1=0 被平均值掩盖 | 逐类报 P/R/F1；报预测分布 |
| 改 `unify/**` | 与后处理线冲突 | 只改引擎目录；契约变更走协作记录 |
| 把关键词出现率当字段真值 | 买数据/改提示依据错误 | 仅作 >20pp 告警代理 |

## 5. 当前结果与未提交进展

**已完成（已提交）**
- `113db42` I-20 教师契约；`d7b7e74` 首跑（M1 诊断 + B4）；`aeb29b6` 大写金额测试。
- M1：64/64 成功、过滤后证据 363/363、原始 390 项丢弃 58；字段准确率暂缺。
- M4：B4 类型准确率 35.94% vs 多数类 42.19%；Macro-F1 0.263 vs 0.198；拘留 MAE 3.63 vs 3.81；罚款 MAE 1,081 vs 1,053；罚款 ±20% 0% vs 10.94%。

**未提交（额度耗尽前跑出）**
- `m2_dev_slice_audit.py` → **M2**：212 条；可核对 176；**166 在默认法定选项内=94.3%**；flags：未引赌博罚则 36、法律版本未知 36、超默认选项 10、行为日期只到月 36、拘留合并审查 2、罚款合并审查 1、非标准结果 1、决定早于行为 1。
- `m4_negative_diagnosis.py` → **M4 诊断**：罚款 P/R/F1=0（10 真值只预测 1）；拘留 F1 0.375；拘留并罚 0.415；输入长度四分位准确率 0.25→0.50；已知 n-gram 非单调。
- `slice_quality_review.py` → E-02 初步；`m1_dev_slice_probe.py` 修改。

## 6. 续跑步骤

1. **恢复**：对照 `$DATA/handoff/2026-10-18/engine/{status.txt,log.txt,uncommitted.patch,files/}`。
2. **测试**：`python -B -m pytest justilaw-api/tests/discretion research/eval/tests -q`；先绿。
3. **小提交**：① M2/M4/slice 脚本与结果；② m1 probe 改动；③ 报告 `docs/05-research/`。每步测试。
4. **核对数字**：M2 的 166/176、10 条超默认选项、2/1 条合并审查；M4 的混淆矩阵与罚款 F1=0；与 JSON 哈希/切片 manifest 一致。
5. **P0 收口**：E-01（冲突逐条说明）、E-03（负结果解释＋预注册下一步基线）、E-02（P-1216、不可核对项）、E-04（M1 丢弃按字段）。
6. **P1 契约**：E-05 七字段裁决规则＋日期/金额归一＋证据语义（升 element-v2 草案，协作记录交后处理线）；E-06 验收适配 `element-ref-v2` 与分歧类型。
7. **P2 等参考**：字段准确率、金标特征上界、与 B4 同切片比较；卡片 v2。

## 7. 验证你已读懂（必做）

- 能解释 r6 为什么只是格式关口、不能标注；
- 能复现 M2 的 94.3%（166/176）与 10 条超默认选项清单；
- 能解释 M4 罚款 F1=0 的原因（10 真值只预测 1、类别不平衡）与长度效应；
- 能说明为什么字段准确率暂缺、什么时候才能算；
- 能列出七字段（role/venue/behavior/method/times/participant/age）的当前定义缺口；
- 跑通引擎测试并报告数量。

## 8. 阅读顺序

`docs/05-research/dev-slice-first-run-2026-10-18.md` → `schema.py` → `element_labels.py` → `annotation-guideline` v0.3 → `data-spec` v0.5.1 → `norm_layer.py` → `dev_slice_first_run.py`/`m2_dev_slice_audit.py`/`m4_negative_diagnosis.py` → `accept_element_labels.py` → `metrics.py`/`agreement.py`。
