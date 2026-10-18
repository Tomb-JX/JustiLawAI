# I-20 要素教师 v1 接口（2026-10-18）

## 边界与输入

字段唯一来源是 `app.discretion.schema.iter_fields()`（schema 1.1.0）和标注指南 v0.4。现行枚举为 **7 组、36 字段**；协调单 I-20 所写的 37 与代码不符，需协调线核账，接入时不可凭空补一个字段。

网页线以 `unified_raw` 的一人一条记录为单位，`subject_mention` 是目标本人；`subject.aliases` 只表示同一人的其他写法。教师输入用 seg-v2 句表中的 facts 句和 facts 前的 meta/当事人句，不能喂说理、决定、复议结论或所引法条。元数据句可能存在而 facts 句缺失；若二者都为空，记录送人工分流，不调用教师。

调用 `app.discretion.element_labels.teacher_messages(target=..., facts_text=..., meta_text=..., aliases=...)` 构造消息。系统提示从本体说明动态生成，每次 schema 版本变化须重新冻结提示版本。教师只回七组 `elements`，各字段 `{status,value,evidence}`，`status` 为 `明确`、`推断`、`未提及`。未提及必须 `value=null,evidence=[]`；有值必须附 facts/meta 的连续逐字 `quote`。字段取值、枚举、金额下界和开口上界由 `teacher_output_schema()` 与 `validate_teacher_output()` 校验。只收台费可记 `amounts.commission`，不得据此标营利目的。

**绑定不在教师输出中**：教师只回七组 `elements`，不输出 `binding`；绑定由后处理按引擎语义表 + 证据判定。当前 v5 诊断 61 shared / 1120 target / 528 review，已做证据感知 3 步；但 212 切片无多人案例，joint 分支未触发；528 review 为 unclassified role；shared 已在 `resolve_binding` 代码接受，但 contract v4 的 `accept_in_resolve` 仍只写 lexical/target；BIND-03/CONTRACT-01 未关闭。教师契约通过不等于绑定质量验收。

## S2 定位与 parsed-2 结构（答 I-20 §6.3）

教师输出的引文先无坐标。S2 把每条引文定位到 **原文正本** `text_full`，在 `elements.<group>.<field>.evidence[]` 回填 `start,end`，采用 Python/JSON 字符串从 0 起、左闭右开的字符位移。入库每个证据为 `{quote,start,end}`，必须满足 `text_full[start:end] == quote`；不存在或有歧义的定位进入复核，不能在规范化文本里凑坐标。`text_orig_sha256` 是 `text_full` UTF-8 的 SHA-256。parsed-2 顶层建议放 `elements`（七组），并显式存 `element_schema_version=1.1.0`、`element_prompt_version=element-v1`、`label_provenance=model-adjudicated`、`human_review=false`。现有 zones/subject/outcome/dates 等结构继续由 seg-v2 负责。`teacher_output_schema(located=True)` 和 `validate_teacher_output(..., located=True)` 是定位后契约。

**r6 只承担交付格式和原文冻结参考，不可当标注输入**；要素生产以通过 G2.2 质量证据包的 parsed-2/seg-v2 句表为准。要素首批未验收前，parsed-2 不能宣称要素可用。

## 教师、M1 与学生（答 I-20 §6.4）

`element-v1` 是离线云教师的字段定义与产标提示。M1 `extract.py` 是消费相同本体的在线/本地抽取器，当前零样本实现不因此自动变成教师，也不能把教师标签当成人工真值。后续蒸馏学生沿用 1.1.0 字段和值域、状态及证据契约；可压缩提示，但应保留原文证据和三态口径。学生模型的加载方式在首批标签和独立开发性评测形成后单独改造 `extract.py`，此处不改运行时。

按 D-002，教师 A/B 双盲与非 DeepSeek 提供方 C 仲裁，A、B 至多一个与教师 B1（DeepSeek）同提供方。产物只记 `model-adjudicated`、`human_review=false`，不计入人工金标；用它做的评测只称开发性评测，不能报告人工字段准确率。

## 首批验收

网页线产出 200–300 条 JSONL，每条：

```json
{"id":"T-1","input":{"target":"甲","facts_text":"...","meta_text":"...","text_full":"...","text_orig_sha256":"64位小写十六进制"},"elements":{"conduct":{"behavior_type":{"status":"未提及","value":null,"evidence":[]}}},"element_schema_version":"1.1.0","element_prompt_version":"element-v1","label_provenance":"model-adjudicated","human_review":false}
```

示意 JSON 省略其余 35 字段；实际必须齐全。A/B 原始结果另存两份同 ID JSONL。运行：

```powershell
python research/eval/accept_element_labels.py labels.jsonl --a A.jsonl --b B.jsonl --out acceptance.json
```

门槛：200–300 件、输出结构/版本/来源/原文哈希 100% 有效、坐标逐字命中率 ≥95%、A/B 全部记录配对、仲裁分歧率 ≤20%。关键字段的未提及率与 `key_field_presence.py` 文本标记出现率差异超过 20 个百分点时告警；文本标记只是代理，不能作真值。报告另列可机械核对的阿拉伯数额一致率、双模型关键数值完全一致率；中文数额或复杂推算未机械核对时显示不可判，不能默认为通过。分歧率 >20% 回修提示后重跑。验收通过也只是**模型产标管线可继续扩量**，不构成人工字段准确率结论。
