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
7. **指南 v0.2 惯例只在一侧执行**。ALL-203 推断态 182 条、value=null 为 **0**；
   链路一 wire schema 对 6 个白名单字段允许 null+推断（且校验器"允许"而非"强制"）。
   与 cross-cal times 灰区 9/10 分歧同源。
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
