# L5 CLI 封装严格审计报告 + 测试计划（2026-10-20）

审计对象：链路一 `research/discretion/unify/run_elements.py`（云侧 A/B/C 仲裁标注 CLI）
及其支撑层（element_contract / durable_calls / budget_scope / provider_contract /
task_result / audit_run / status），对照链路二
`s1_runs/l5-v3b-elements-single-m1-203-20261018/run_batch.py`（引擎 M1 单模型）与
人工通道 `manual-batches/ALL-203/labels.jsonl`。全部结论有代码行号或离线实测支撑。

## 0. 模块地位

上游 S1(seg-v2-durable-4)→S3→export_l5_inputs（教师输入 203/125 隔离）→
**L5 CLI** → labels（record-{rid}.json / diagnostics）→ 交叉校准、采纳。
两条链路共用引擎侧校验器（JUSTILAW_ENGINE_API 指向 discretion-engine 的
app/discretion/element_labels.py），但输入构造、证据强度、落盘形态、失败处理各自为政。

## 1. P0——阻断重启/计费管线安全

1. **实现哈希即全局契约，代码与缓存同生命周期**。
   `contract_snapshot.implementation = 全 unify/*.py 哈希`（element_contract.py:124-129），
   且 `contract_bundle_hash` 混进 user 消息内容（element_contract.py:171）→ 调用缓存 key。
   实测：当前代码重算 smoke v5 全部 A/B 请求 key，**0/24 命中**——v5 之后任何一行改动
   （哪怕注释）都使既有 raws 全部失效：续跑 = 全部重买，或重新冻结全套 order。
   "修复后免费重放"只在 ledger 层成立（直接重放 raws.jsonl 过校验器），runner 层不成立。
2. **fail-fast/隔离边界靠错误文案前缀字符串**（run_elements.py:343-348）。
   隔离白名单与 element_contract/durable_calls 的 raise 文案紧耦合：文案改一个词，
   隔离静默退化为全批死亡；`request_too_large`、cap、核账类刻意 fail-fast 同样依赖前缀。
   现有 18 个 tests 无一守卫该边界。
3. **进程被杀后的 stale lock 无接管**。RUNNING.lock `open("x")` FileExistsError 未被
   捕获（run_elements.py:290）→ 恢复时裸 traceback（微测证实）；BudgetScope WRITER.lock
   5 秒自旋后 raise（budget_scope.py:41-46），无 PID 活性检查。本批 6 并发 TaskStop
   正是这种场景，恢复全靠手工删锁且无工具提示。
4. **工单字节闸跨代漂移**。spec36 v2 order `max_input_bytes=50000`，smoke v5 已是 120000。
   实测：当前 6 批 ID 池最大请求 46KB 不炸；但全池 326 个合格项有 2 条 57KB——
   若补齐 191 条沿用 v2 工单，1 条 request_too_large（非白名单）→ 拖死整批。
5. **瞬断无重试、失败即永久占账**。DurableCalls 对 timeout/rate_limit/server 零重试，
   且失败后 key 滞留 `unknown`（reserved 不释放、再跑即"先人工核账"，durable_calls.py:102-103,138-147）。
   请求未必真的计费（如 DNS 失败）也必须人工清账；failed-without-raw 无任何恢复路径。
   audit_run 只帮到 raw_recoverable（有 raw 无 finished）。

## 2. P1——数据对齐（两链路互不流通）

6. **标签三形态，转换器不在任何仓库**。ALL-203（provenance=manual-subagent 180 +
   manual-coordinator 23，schema 1.1.0）evidence 带 `start/end=null` 冗余键 →
   实测 203/203 在引擎 located=False 校验下全灭（bad_evidence_shape 共 1314 条）；
   剥掉 null 坐标后 203/203 通过。机械验收/合流必须先落一个入库 repo 的转换器。
7. **推断态语义分叉（初判见 §2A 修正）**：初判"人工 0/182 推断+null 未按惯例"经深挖不成立——
   人工推断全是可推导值、模糊量词走未提及；未决点是"单日期→times=推断 1"两侧不一致，交指南 v0.3。
8. **三套坐标系 + 两档证据强度**。链路一坐标在原文（text_full，逐字，reference_source_mismatch）；
   链路二本地 records 坐标在 `facts+"\n"+meta` 拼接视图；ALL-203 无坐标。且
   extract.locate 允许 SequenceMatcher ratio≥0.9 模糊定位（extract.py:136），
   链路一必须逐字——同为"有证据"，强度不可比。
9. **C 仲裁退化为同模型复核**。所有工单 B=C=xiaomi-pro（同端点同参数）；
   check_models 仅禁 C=deepseek（durable_calls.py:47-48）。白名单里有
   qwen3.8-max/kimi-k3 可用，但改配置键即改实现哈希（见 1），事实上锁死了选型。
10. **E-05 批准包不在契约哈希里**。contract_snapshot 只 hash engine 三件 +
    harvest/parse、parse_qc、key_field_presence、legal_caps（element_contract.py:107-121），
    **normalization_spec.py / evidence_contract.py / binding_rules.py 不在内**——
    单改引擎 repo 的金额对账/证据语义，web 侧契约冻结毫无感知。

## 3. P1——会话调控与监控

11. L5 无心跳：status.py 只 glob `s1-*` 且读 progress.json（S1 Runner 专用），
    L5 目录只有终态可 audit；运行中无 ETA/延迟/在飞费用。observability 是验收诊断非运行时监控。
12. 硬编码清单：`_DEFAULT_DATA` 绝对路径（有 env 覆盖✓）、engine sibling 路径推断（env✓）、
    provider_identity 域名后缀表、**ARBITER_MODEL_WHITELIST 码内集合（改白名单=改契约，自相矛盾）**、
    smoke12/spec36 阈值（12/¥4/¥12/252/36，run_elements.py:267-281）、
    prices/legal_caps 固定路径；api_key 明文存 `$DATA/config/s1_models.json`（文件权限未审计）。
13. 并发模型：runner 单线程逐条（2-3 调用/条），并行=多进程×多目录+共享 ledger——
    WRITER 5s 锁超时在高并发下偶发整批死；无全局限流（429 分类但不重试）。
14. 效率实测（smoke v5，12 条）：36 次提交=¥3.13（预算 4 元 78%），延迟 p50 41s/p90 93s/max 135s，
    1 次 completion 顶满 max_tokens 12000（输出被切→repair 重买 4 次，模型输出失败率≈11%）。

## 2A. 断层深挖（2026-10-20 补充实测，覆盖 §2.6-8 的初判）

对 ALL-203 全部 1314 条证据 × 7308 个字段值做了逐条机器锚定，结论修正如下：

- **键形 100% 统一**：1314/1314 条 evidence 都是 {quote,start,end} 且 start/end 恒 null——
  即人工通道按 located 入库 schema 输出、只是坐标留空。剥键转换器是平凡的、无损的。
  7308 个字段全部三态齐全（未提及 6003 / 明确 1123 / 推断 182），未提及从不带证据或值。
- **锚定矩阵**（对照原文 text_full）：1244 逐字+区内唯一；22 逐字但原文歧义、限入视图区后唯一；
  **35 区内仍歧义**（需首现/句级 tie-break 策略）；11 需引号规范化或省略号多段拼接（链路二 locate 强度）；
  2 改写不可锚（应拒收该字段值）。跨视图拼接界 0 条、**视图区外证据 0 条**——人工通道
  与链路一同样严守 facts/meta 来源限制，无泄漏取数。与 DENSITY_REVIEW 自审 evidence_quote_fail=13 吻合。
- **推断惯例判断修正**：初判"人工未按 v0.2 白名单惯例（推断+null=0/182）"不成立——
  抽查证实 ALL-203 的推断态全是**可推导值**（person.age 74 条中 73 条证据=出生日期反推；
  violations_last_year=0 的证据=「无违法犯罪经历」），且 times 从不引模糊量词做证据
  （「多次」被处理为未提及或精确计数）。真正的未决灰区是"单一日期 → times 推断值 1"，
  这条**链路一模型自己在产出**（14 条 smoke 中 3 条），指南 §3.5 表外，是 v0.3 唯一要裁的点。
- **证据级联合分布**（12 条重叠记录 × 36 字段 = 432）：
  同值+证据逐字相同 325；同值+证据全不相交 58；异值 49；部分重叠 0。
  值一致率 88.7%（与既有交叉校准吻合），但值一致字段中 15% 证据句选择不同——
  两通道分歧在**句粒度选择**而非片段边界，下游训练用标签须声明"证据句非唯一正确"。
- 转换器可行性结论：确定性重锚可覆盖 1266/1314（96.4%），策略可再覆盖 35，
  仅 13（1%）需要"是否接受链路二强度证据"的裁定，2 条拒收。断层是工程问题不是数据可信度问题。

## 4. 测试计划

**T0 静态守卫（免费，pytest 扩展现有 18 测）**
- 错误前缀契约表：raise 文案前缀常量化为 PREFS，测试断言白名单 ⊆ 实际 raise 前缀集合（红→修）。
- 契约覆盖完整性：断言三个 E-05 lazy 模块在 contract_snapshot.dependencies（现为红，暴露问题 10）。
- stale lock：预置 RUNNING.lock → 断言干净报错（现为裸 traceback，红）。
- 字节闸预估器：对任意 ID 池离线算 messages() 字节 vs 工单闸，超闸点名（复用本次实测代码）。

**T1 重放族（免费）**
- ledger 级重放：raws.jsonl 全量重过 compile_references，固化为回归脚本（金额修复的 32/32 同族）。
- 缓存漂移预报：当前代码重算旧批 keys，报告命中率（实测 0/24 为基线）→ 决定"改码前先跑完"纪律。
- ALL-203 转换器：剥 null 坐标 → located=False 203/203（已实测），转换器入库 + 测试。

**T2 结构对齐（免费）**
- 三形态 join 性断言：字段集/状态三值/坐标系/证据强度逐项 diff，产出统一入库 schema 决策依据。

**T3 小额付费端到端（≤¥4，复用 smoke 阈值）**
- 3 条：57KB 超长 ×1 + 金额合成 ×1 + 常规 ×1；新 order：max_input_bytes=120000、
  C=bailian-max（qwen3.8-max，白名单内，真三向）。验证：超长不炸批、B≠C 仲裁可恢复、
  reservation vs 实收偏差。
- 前置修复：问题 10（E-05 入哈希）、3（stale lock 报错）、4（统一字节闸）。

**T4 故障注入彩排（本地 fake provider，免费）**
- kill 中途恢复（subprocess 测试）；failed-without-raw 核账路径演练；
  双进程并发 reserve WRITER 竞争压测；reservation_exceeded 熔断后人工恢复剧本。

优先级：spec36 补齐 191 条重启前必须过 T0 全绿 + T3；203 条采纳前必须 T1 转换器落地。

## 5. 修复记录（2026-10-20，commit 18cf39e @ codex/l5-quality-s1-run-aggregate）

| 审计项 | 修复 | 新测试守卫 |
|---|---|---|
| P0-1 实现哈希灭缓存 | 双阶哈希：`prompt_fingerprint`（system 全文+信封+版本）成为缓存 key/工单准入/续跑身份；全量实现快照仍记录于 manifest/记录内供审计 | fingerprint 无 implementation 键、manifest_matches 容忍漂移、信封断言 |
| P0-2 前缀字符串耦合 | `MODEL_QUALITY_PREFIXES` 单一事实源 + `is_model_quality_failure` | 逐前缀参数化正例/反例（含 JSONDecodeError） |
| P0-3 残留锁裸 traceback | process_guard（Windows OpenProcess，宁误判存活）；RUNNING.lock 死亡→`--take-over` 明示接管、活锁拒双跑；WRITER.lock 死亡自动清 | 活/死持有者两路、writer 接管 |
| P0-4 字节闸漂移 | 发射前 `preflight_request_sizes` 全批点名（与 DurableCalls 同口径） | 口径一致性断言 |
| P0-5 瞬断占账 | not-sent（DNS/拒连，保守白名单）写 released 回滚预留+预算 release（可再购同 key）；有 raw 无 finished 重启自动补账；真未知保留人工出口 `audit_run --settle`（evidence 必填、超预留 4 倍拒绝、幂等防二次结算） | 分类保守性、released 免核账续跑、raw 补账零重发、settle 三拒一放 |
| P1-10 E-05 不入契约 | normalization_spec/evidence_contract/binding_rules 入 dependencies | 三文件名断言 |
| P1-11 L5 无心跳 | runner 接 ProgressTracker（进度/延迟/成本/错误分类）；status.py 认识元素批（账本合成 + 审计提示） | element_summary 合成断言 |
| P1-13 白名单码内 | `$DATA/config/arbiter_models.json` 优先，常量兜底 | — |
| P1-15 魔数 57 | freeze pool `--expect-reuse` 参数 | — |

连带修正：attempt 编号改用历史提交总数（released 重试不复用 attempt_id）；`--take-over` 新开关。
**一次性代价**：信封改动使 v5 时代 raws 的 key 不再命中（本就终局完结、不受影响）；旧 spec36/smoke 目录
manifest 无 prompt_fingerprint 字段 ⇒ 不再可 resume（治理上正确：它们已终局）。
**遗留待办**：spec36 补齐 191 条需按新契约重生成工单（max_input_bytes≥60000 覆盖 57KB 记录；
建议 C 换非 xiaomi-pro 做真三向）；6 条历史在飞 unknown 用 `audit_run --settle` 对账（3 条 402 实证、3 条 TaskStop 中断）。
回归：201/201 离线全绿（1.45s，零网络零付费）。

### 5b. 监控诚实化补丁（commit 6a0c596，同日第二轮）

复盘四问（效率覆盖？阻塞可发现？答案不丢？）时自查出第一轮修复的两处失真并修正：
- `finally` 无条件报 done → 中止批假报完成。改为：全批走完 done；任何异常 aborted，且 abort 前把
  "谁/在哪条/为何"写入 diagnostics + progress.errors_recent；锁仍清理，状态可区分。
- finish_reason 不入 meta → 输出截断（顶满 max_tokens 付费）不可见。Provider.chat 成功路径补记；
  status 元素批显示"截断(length) N"。
- 新增 runner 端到端离线演练两枚（fake 调用层零网络）：happy=落盘+done+无锁残留；
  fatal=诊断行+aborted+errors_recent 可见+状态板同步。203/203 全绿。

覆盖声明（诚实版）：监控为**拉取式**（status.py / --watch / audit_run），无推送告警；
链路二（本地 Ollama）无统一效率视图（per-record seconds 已存记录内）；
延迟 p50/p90 为记录级（raw 级数据齐备但未聚合展示）。
