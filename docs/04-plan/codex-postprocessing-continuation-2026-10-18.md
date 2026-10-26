# Codex 后处理线续跑交接（深版 · 2026-10-18 · 额度耗尽后）

> 你的角色：**后处理链路实现负责人（B 职能）**。网页线只剩 A 运维下载；`research/discretion/unify/**` 归你。
> 工作树 `.claude/worktrees/seg-v2-design-review`，分支 `codex/seg-v2-design-review`，最后提交 `ba12e6f`。
> **有大量未提交工作，先保住再继续**：8 改＋17 新；只读备份 `$DATA/handoff/2026-10-18/postprocessing/`。

## 1. 你负责的链路（一张图）

```
L0 原始/台账
  → parsed-1（渠道解析，网页/法宝）
  → S0 清洗（cleanse.py）：cleaned_text + RLE 区间日志
  → 预筛（prefilter.py）+ form 判别（form.py）
  → unified_raw（to_unified.py：records/edits.rle/stats）
  → S1 seg-v2（s1.py 历史运行 / run_seg.py 新入口）：句表分区 zones + 结果/日期/复议/赌博判定
  → S2 定位（locate.py）：quote/句 ID → 原文坐标
  → S3 校验（s3.py / run_s3.py）：11 项确定性检查
  → elements（run_elements.py + element_contract.py）：36 字段参考
  → 组装 parsed-2（replay_pipeline.py）
  → 交付（网页线原职责，现冻结；不归你）
```

**分工原则**：渠道层只抽文本/源标记；S0 确定性清理；S1 语义；S2 定位；S3 校验；elements 产参考；build/交付另属。不要把语义塞回正则，也不要在网页侧重定义引擎本体。

## 2. 模块地图（逐个知道它为什么存在）

| 模块 | 职责 | 关键不变量 |
|---|---|---|
| `cleanse.py` | S0 规则册，按源分册；表续行、管道、逗号续行、空白/全角归一；输出 cleaned_text + RLE | 纯确定性、可单测、可回放；`cleaned[c]==orig[map[c]]`；删除类规则白名单化 |
| `form.py` | 8 值 form 判别（叙述式独立/结果栏内/字段表/标题汇总/复议/判决/混合/合作） | S0 确定性标记，**严禁模型预测**；pkulaw 三值是子集 |
| `prefilter.py` | 放行阀：是 ∪ 待定 ∪ borderline | 规则是阀门不是语义；待定默认放行；不给模型加负担 |
| `to_unified.py` | parsed-1 → unified_raw（records/edits.rle/stats） | 只读输入、输出新批次目录；不覆盖旧批次 |
| `s1.py` | 历史 S1 运行器（模型客户端/提示/重试/缓存/回执） | 仅供历史回放；新付费批不得直接用它 |
| `run_seg.py` | 新 S1 入口；默认离线 plan | 只有 `--execute --order <reviewed>` 才调用；要求 stage/review/executor/engine ack/free replay pass/cap/max_calls |
| `s3.py` / `run_s3.py` | 11 项校验：覆盖/重叠、outcome 一致性、罚幅、法条版本、日期、主体、值-文对账等 | 确定性阻断；硬失败→重试→低置信队列；不得用内部 ok 冒充外部正确性 |
| `zoning.py` | 公示族确定性分区（zones_det） | 模型只抽字段；分区由规则给定后覆写；规则也要抽检引用范围 |
| `locate.py` | S2：quote/句 ID → cleaned → orig | 半开区间 `[start,end)`；clean→orig 只投影一次；有歧义进复核，不猜 |
| `run_elements.py` | 要素参考运行器；默认离线 plan | 引擎语义引擎所有；A/B 不同提供方、C 非 DeepSeek；逐记录提交；cap/工单 |
| `element_contract.py` | 从引擎读 36 字段契约；wire `element-ref-v2`；证据用句 ID | **wire v2 是传输版本，不是 element-v2 本体批准**；`compile_references` 后调引擎 `validate_teacher_output(located=True)` |
| `contract_bundle.py` | 导出可执行引擎/传输契约＋拟议归一化 IR | 契约哈希冻结；代码/提示/依赖变化即换 hash |
| `normalization.py` | 中文时间/数量适配（JioNLP 只做表达式解析） | 证据绑定；精度/开口/兼容损失显式；不覆盖引擎本体；不读时钟/不猜事件锚 |
| `field_rules.py` | 读引擎定义、保留 K 字段、只解析批准别名 | 不新造字段；不把未批准别名当本体 |
| `evidence_graph.py` | 来源锚定候选图；主体/事件/角色边 | 词法绑定只是候选，不是真值；不可支持/代词/联合关系留 unresolved |
| `outcome_arbitration.py` | 保留历史观察值的结果裁决，与规范诊断分离 | **处罚上限不得用来选候选**；每个决定须有自己的允许来源引用 |
| `run_outcomes.py` | 裁决入口；默认离线 plan | 一次记录一次请求；不自动扩量 |
| `experiment_plan.py` | 冻结事件不交叉的小批计划 | 只用独立参考评估；不得用旧批准推断新版本 |
| `observability.py` | 36 字段可观测性诊断 | 与来源真值/准确率严格分开；不是字段正确率 |
| `diagnose_pipeline.py` | 离线图/归一/分节/36 字段报告 | 只读冻结输入；不改产物 |
| `durable_calls.py` | 有界 HTTP 尝试、原响应落盘、预算预留 | append-only 尝试账本；**不承诺远端恰好一次计费**；未知请求不重发 |
| `budget_scope.py` | 跨进程/跨阶段预算预留与恢复审计 | 每阶段 cap 是批次上限，不是总预算 |
| `provider_contract.py` | 提供方协议声明与无密钥执行冻结 | 不把配置/价格当已核定账单 |
| `section_refs.py` | 细粒度引用（法条/结果/执行/救济）可重叠 | S1 分区互斥语义不动 |
| `binding_contract.py` | 把候选选择编译成字段 grounding（引擎批准策略） | 不猜缺失关系；值必须有自己的引用 |
| `evidence_types.py` | 坐标类型 | Python 字符，半开 `[start,end)` |
| `task_result.py` | 执行结果 | 失败**不得**伪造“未提及”等字段内容 |
| `audit_run.py` | 只读崩溃恢复/费用审计 | 不丢弃截断尾；不重试 HTTP |
| `replay_pipeline.py` | 离线 S0/坐标/S3/要素回放与 parsed-2 开发组装 | 不实例化 HTTP provider；每条输出 `release_approved=false` |
| `freeze_slice.py` | 冻结开发切片 | fail-closed；原文/本人/视图/处罚证据/事件检查；不认证参考标签/r7 |

## 3. 五个必须记住的契约

1. **本体归引擎**：36 字段、枚举、三态、金额开口、营利目的口径，全部来自引擎 `schema.py`/`element_labels.py`；网页侧只做传输与校验调用。**不要重定义字段**。
2. **坐标**：半开区间 `[start,end)`；clean→orig 只投影一次；证据必须 `text_full[start:end]==quote`；句 ID 只能引用 `sentence_view` 内的句。F3 坐标混用（64/88）是已知历史缺陷，不要重复。
3. **证据/状态**：`未提及` ⇒ `value=null, evidence=[]`；`明确/推断` ⇒ 有值且至少一条证据；证据要支持该值，不是“文中出现过”。
4. **历史观察值 vs 规范结论**：实际处罚是训练目标/观察值，**任何上限/法律锚都不得改写它**；规范冲突单独报告。
5. **版本/留痕**：契约 bundle hash、引擎文件 hash、依赖 hash、提示/模型版本、原响应、usage、预算预留；代码变化即停批，不在批内换规则。

## 4. 常见坑（现象→后果→做法）

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 在网页侧重定义本体 | 字段名同、语义漂移 | 读引擎契约；不新增/改名/改枚举 |
| 让模型抄引文 | 转写走样、坐标错、S2 擦屁股 | 只回句 ID，服务端编译 quote/坐标 |
| 把“候选”当“参考” | 旧 88 标签/模型共识被当真值 | 旧标签隔离；参考必须独立、有版本、可验收 |
| 用处罚上限选候选 | 历史观察值被改写 | `outcome_arbitration` 只保留观察值；规范诊断分开 |
| 分歧当成本 | 付钱仲裁掩盖定义歧义 | 先做字段级分歧榜/定义修订；仲裁只处理合法候选 |
| 无工单直接跑 | 超预算/不可复现 | 必须 `--execute --order`，带 review/ack/free replay/cap |
| 批内改规则 | 同批数据污染 | 设计变更只从下一整批边界生效 |
| 截断 JSONL 静默丢尾 | 账目/恢复失真 | `audit_run` 报错；不静默丢 |
| 未知计费自动重发 | 重复付费 | 保留预留、标记未知、人工核账 |

## 5. 未提交工作与当前产物

**修改（8）**：`arbitrate.py`（退役旧法律锚选候选）、`element_contract.py`（依赖哈希/分歧分类）、`durable_calls.py`、`locate.py`、`replay_pipeline.py`、`requirements.txt`、`run_elements.py`、`run_seg.py`。
**新增（17）**：`audit_run/field_rules/normalization/outcome_arbitration/evidence_graph/contract_bundle/experiment_plan/binding_contract/budget_scope/diagnose_pipeline/evidence_types/observability/provider_contract/run_outcomes/section_refs/task_result/tests/test_engineering_completion`。
**诊断产物**：`$DATA/parsed2/engineering-diagnostics-20261018-codex-v1/`（summary/field-catalog/observability/field-diagnostics/candidate-graphs）。

## 6. 续跑步骤

1. **恢复**：对照 `$DATA/handoff/2026-10-18/postprocessing/{status.txt,log.txt,uncommitted.patch,files/}`；确认没有丢文件。
2. **测试**：`python -B -m pytest research/discretion/unify/tests -q -p no:cacheprovider`；先绿再改。
3. **小提交**（每组一测）：① 契约/依赖哈希/分歧分类；② normalization/field_rules/evidence_graph；③ outcome_arbitration/run_outcomes；④ durable_calls/budget_scope/provider_contract/audit_run；⑤ run_seg/run_elements/replay；⑥ 测试/README。
4. **读诊断**：`summary.json`/`observability.json`/`field-diagnostics.jsonl`，确认字段可观测性与缺口；与引擎 E-04 丢弃分析对照。
5. **等引擎 E-05**：七字段裁决规则＋日期/金额归一＋证据语义；接入后做免费回放。
6. **小批**：契约冻结、回放通过、引擎 E-06 验收适配后，≤12 条烟测 → ≤36 条规约批；全量 2,451/r7 不在本批。

## 7. 验证你已读懂（必做）

- 能解释 `element-ref-v2` 与 `element-v2` 的区别；
- 能复现 `replay-final300-...-v3` 的 S3 26/299=8.7%；
- 能指出 `freeze_slice` 的 86 条剔除原因；
- 能说明为什么 `outcome_arbitration` 不允许处罚上限选候选；
- 能说清 `attempts.jsonl`/`raws.jsonl`/`RUNNING.lock` 的恢复语义；
- 跑通全部单测并报告数量。

## 8. 阅读顺序

`unify/README.md` → `parse-format-chain-design`（变更日志 v1.3）→ `parse-interface-v2-design` → `seg-v2-pipeline-implementation-report` → 本目录各模块 docstring → `tests/`。
