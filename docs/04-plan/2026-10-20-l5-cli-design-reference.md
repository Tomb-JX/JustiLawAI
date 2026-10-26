# L5 要素标注 CLI 设计参考（2026-10-20，权威版）

对应代码：`research/discretion/unify/`，分支 `codex/l5-quality-s1-run-aggregate`，
commit `6a0c596`（203/203 离线测试全绿）。本文是设计+使用+约束的单一参照；
与审计（2026-10-20-l5-cli-audit-and-test-plan.md）互补：审计记问题，本文记现状。
**密约：本文不载任何密钥；密钥只存 `$DATA/config/s1_models.json`。**

> **2026-10-21 用户裁决**：允许移除 smoke12/spec36 工单与 36 条小批上限，使用 `--full`
> 跑全量；仍保留“不重复计费、证据逐字可编译、无 answer leakage、test 封存”四条必要保护。
> `--full` 默认 A=deepseek、B=xiaomi-pro、C=bailian(qwen3.8-flash)，数据侧执行，不涉及引擎训练。
> 代码层使用正数 `--cap/--max-calls/--max-input-bytes` 作为执行安全上限，不再是审批门。

---

## 1. 定位与数据流

```
冻结池 freeze_l5_quality_pool ─▶ 物化 materialize_l5_quality_input ─▶ S1 运行(run_seg/durable)
      ─▶ S3 防泄漏闸 run_s3 ─▶ 教师输入 export_l5_inputs（facts/meta 隔离视图，无结论泄漏）
      ─▶ ★ L5 CLI run_elements.py（A/B/C 云模型仲裁标注）★ ─▶ record-{id}.json + diagnostics
      ─▶ 交叉校准 / 采纳 / replay_pipeline 合流
```

L5 CLI 的职责边界：只做"传输与验收"，字段语义本体**引擎侧所有**（engine-owned）——
本体、提示词、取值校验都来自 `JUSTILAW_ENGINE_API` 指向的
`app/discretion/element_labels.py`；web 侧不得重定义字段。

两条链路共用引擎校验器，但强度不同：
| | 链路一 run_elements | 链路二 run_batch（单次直出） |
|---|---|---|
| 模型 | 云 A/B/C 仲裁 | 云 mimo-v2.6-pro（配置键 xiaomi-pro；**2026-10-20 裁决：弃用本地 Ollama qwen3.5:9b**） |
| 证据 | 逐字、原文坐标、句 ID 传输 | 允许规范化+模糊定位（ratio≥0.9），坐标在 facts+"\n"+meta 拼接视图；记录内带 `evidence_strength:"canonical-or-fuzzy"` 分级标记 |
| 失败 | 质量类隔离 / 管线类 fail-fast | 质量类记 failures.jsonl 继续；**balance/auth（402/401）立即停批 exit 3，不重试轰炸**；可续跑同命令 |
| 治理 | 工单+预算账本+心跳 | 轻量：逐条 cost_estimate+累计 spent_estimate 打印落记录；无共享 ledger |

---

## 2. CLI 用法

### 2.1 规划（默认，永远免费、零网络）
```
python research/discretion/unify/run_elements.py \
  --run <S1运行目录(含outputs.jsonl)> --unified <records.jsonl> --parsed <originals.jsonl> \
  --ids <冻结ID数组.json> [--limit N] \
  --out $DATA/s1_runs/<新批目录>
```
二选一输入源：`--run/--unified/--parsed` 三件套（S1+S3 合格线，input_mode=s1_s3_qualified）
或 `--slice <冻结开发视图records.jsonl>`（免额外 S1 调用，input_mode=development_slice_no_s3_certificate）。
`--out` 必须是 `$DATA/s1_runs` 下**新目录**（护栏硬校验）。
产物：`manifest.json`（批身份）、`plan.json`（eligible/rejected/contract_hash/prompt指纹）。

### 2.2 付费执行（必须工单）
追加 `--execute --order <工单.json>`；可选 `--take-over`（见 §6 锁）。
执行前闸门依次：工单四联签 → 分段治理 → 预算上界 → **字节预检** → 模型身份互斥 →
执行设置冻结 → RUNNING.lock → 逐条循环。任何一步不过 ⇒ 零花费退出。

### 2.3 配套 CLI
| 工具 | 一句话用法 |
|---|---|
| `status.py` | 无参列全部运行（含元素批）；`--run latest --watch` 2s 刷新 |
| `audit_run.py <批>` | 只读核账；`--settle <attempt_id> --charged X --evidence 依据 [--scope-dir]` 人工清未知 |
| `export_l5_inputs.py` | S3 后再过泄漏正则，产教师输入+quarantine |
| `freeze_l5_quality_pool.py` | 冻结候选池；`--expect-reuse N`（默认57） |
| `aggregate_l5_quality_s1.py` | 多批聚合；`--pool/--pool-scoped` 池内过滤 |
| `contract_bundle.py` | 导出完整执行契约包（提示词+schema+中间态schema） |
| 链路二 run_batch.py（数据目录） | `python run_batch.py [--inputs 教师输入] [--out 目录] [--provider xiaomi-pro] [--shard i --shards n] [--limit N]`；云单次直出，续跑=重跑同命令 |

**2026-10-20 裁决已同步**：C=qwen3.8-flash 登记、链路二转云 mimo-v2.6-pro、max_tokens 提高——
均为配置/数据目录脚本层变更，unify 代码保持 6a0c596（203 测试仍全绿）。

---

## 3. 工单（order JSON）字段与治理闸

必填：`stage`（smoke12|spec36 二选一）、`ids`（=批 ID 序，逐一相等）、
`contract_hash`（= prompt_fingerprint 或全量快照摘要，二者任一命中放行）、
`review_record`/`executor_review`/`engine_ack`（三联签，非空即可）、`free_replay_pass: true`、
`cap`/`max_calls`/`max_input_bytes`（正数）、`providers: {"A","B","C"}`（配置键名）、
`budget_scope: {"path","cap","max_calls"}`（path 限 $DATA/s1_runs 下；缺则拒执行）。
spec36 额外：`prior_stage_receipt` 指向上游回执文件且其 `pass=true`、契约一致。

**治理硬闸（代码常量，run_elements.py）**：
- smoke12：`len(work) ≤ 12` 且 `cap ≤ ¥4`
- 通用：`0 < cap ≤ ¥12`、`0 < max_calls ≤ 252`、`len(work) ≤ 36`（全量须另审工单=改码另议）
- 字节预检：每条真实 messages 字节数（UTF-8 +1024 framing）> `max_input_bytes` ⇒ 发射前点名拒跑
- 单条预留 = (请求字节+1024)×输入单价 + max_tokens×输出单价（元/百万 token）；
  累计预留超 cap 或调用数超 max_calls ⇒ `budget_stop`
- reservation_exceeded（实收>预留）⇒ 该 provider 本批判死并停批（查 token 口径）

可选：`capabilities`（逐 tag 声明 endpoint/model/mode，与运行时实核一致才放行）。

---

## 4. 模型提供商（配置文件，非硬编码；值以现状实录）

**2026-10-20 裁决记录**：① 仲裁 C 改 **qwen3.8-flash**（配置键 bailian），已登记进
`$DATA/config/arbiter_models.json`（文件白名单上线，码内常量退居兜底）；
② 单次直出链路弃用本地 Ollama，改云 **mimo-v2.6-pro**（run_batch.py --provider 默认 xiaomi-pro）；
③ 适当提高 token 截断阈值（下表已生效；预留=字节×入价+max_tokens×出价，随上限同步放大，
smoke 预算 ¥4 内 A 单条预留约 0.13→0.17 量级，仍充足）。

`$DATA/config/s1_models.json`（全局 params 可被逐 provider params 覆盖）：

| 配置键 | 模型 | 端点(host) | max_tokens（裁决后） | timeout_s | 定价 元/M（入/出） |
|---|---|---|---|---|---|
| deepseek | deepseek-flash | api.deepseek.com | **16000**（原 12000） | 240 | 2.0 / 8.0 |
| xiaomi | mimo-v2.6-flash | token-plan-cn.xiaomimimo.com | **12000**（原 8000） | 180 | 1.0 / 4.0 |
| xiaomi-pro | mimo-v2.6-pro | 同上 | **12000**（原 8000） | 180 | 4.0 / 16.0 |
| xiaomi-pro-long | mimo-v2.6-pro | 同上 | 20000 | 300 | 4.0 / 16.0 |
| bailian | qwen3.8-flash | dashscope.aliyuncs.com | **12000**（原 6000） | 120 | 1.0 / 4.0 |
| bailian-max | qwen3.8-max | 同上 | **12000**（原 8000） | 180 | 8.0 / 24.0 |

全局默认 params：`temperature 0`、max_tokens 12000、timeout 240（逐 provider params 覆盖之）。
定价表 `$DATA/config/s1_prices.json`，**缺价格=拒绝执行**（无法预留不放行）。
请求形态：OpenAI 兼容 `/chat/completions`，`response_format=json_object`、非流、
Authorization Bearer。temperature/max_tokens/timeout **每次发射时冻结进 `execution-manifest.json`**，
中途改配置 ⇒ `execution_settings_changed`，必须换批。

**A/B/C 身份约束（durable_calls.check_models）**：A 与 B 必须不同供应商域
（防"配置键伪装隔离"）；C 不得为 deepseek 且模型须在册裁判白名单。
白名单权威 = `$DATA/config/arbiter_models.json`（2026-10-20 已上线），现值
`{qwen3.8-max, kimi-k3, mimo-v2.6-pro, mimo-v2.6-flash, qwen3.8-flash}`；码内常量仅兜底。
**现行编制（裁决后）**：A=deepseek、B=xiaomi-pro（mimo-v2.6-pro）、C=bailian（qwen3.8-flash）——
三供应商真三向。历史 smoke/spec36 工单 B=C=xiaomi-pro 的退化二向票不再用于新批；
约束层仍允许 B=C 同域（如 mimo 双型号），如需强制 C≠B 域属进一步治理决策。

---

## 5. 契约与缓存：双阶哈希（审计 P0-1 修复后的现状）

**prompt_fingerprint（稳定身份）** = wire 版本 + 引擎版本 + **system 全文 sha** + user 信封字段名。
用途：调用缓存 key 的 context、工单准入、续跑识别（manifest 身份键：
version/prompt_fingerprint/ids/views/source_hashes）。
含义：**改校验器/计费/runner 等不影响提示词的代码 ⇒ 缓存、工单、续跑全部存活。**

**contract_snapshot（全量审计身份）** = 引擎三件（element_labels/schema/extract）+
**E-05 批准包**（normalization_spec/evidence_contract/binding_rules，P1-10 修复）+
harvest/parse、parse_qc、key_field_presence、legal_caps + 全部 unify/*.py 实现哈希。
每次发射记录进 manifest['contract'] 与每条 record 的 contract_hash；循环内两次核对，
中途漂移即 `engine_contract_changed`/`contract_changed_during_call`（保 raw、不提交混合标签）。

一次性代价：信封字段从 bundle_hash 换成 prompt_fingerprint，2026-10-20 前旧批 raws 的
key 不再命中（旧批均已终局，无损失）。

---

## 6. 断链与并发

**传输**：单线程逐条（每条 2-3 调用），批间并行=多进程×多目录×共享 budget_scope。
`unknown_remote_outcome`（可能已送达的失败）⇒ 保留全预留、禁止自动重发、要求核账。

**三类失败的账本语义**：
1. not-sent（DNS 失败/连接被拒，保守匹配：getaddrinfo/10061/connection refused/no such host）
   ⇒ `released` 事件、预留回滚、预算 release（同 key 之后可重购，attempt 编号按历史总数不复用）。
2. 可能已送达（timeout/402/5xx/掐断）⇒ `failed` + 保持 unknown（宁占账不重付）。
3. 有 raw 无 finished（落 raw 后被打断）⇒ 重启 `execute=True` **自动补账**（零 HTTP）。

**锁**：`RUNNING.lock`（x-open+PID 写入）——持有者活⇒拒双跑报 PID；死⇒干净报错，
`--take-over` 明示接管（探测原则：宁误判存活，绝不误判死亡；Windows OpenProcess 实现）。
`WRITER.lock`（budget_scope 全局写锁，5s 自旋）——死持有者自动清锁重入。
budget_scope 跨批防重复购买：同 key 二次 reserve ⇒ `shared_attempt_exists`。

**失败分诊（单一事实源）**：`element_contract.MODEL_QUALITY_PREFIXES` 13 前缀 + JSONDecodeError ⇒
隔离（diagnostics 记 invalid/transport_failed 后 continue）；其余 ValueError/TypeError/RuntimeError ⇒
fail-fast（停批前 diagnostics 记"哪条+为何"，progress phase=aborted，锁清理）。
前缀表变更由 `test_model_quality_prefixes_are_isolated` 参数化守卫。

---

## 7. 监控

每完成一条原子刷 `progress.json`（tmp+rename，Windows 占用重试后降级覆盖，心跳失败绝不断管线）：
done/total/ok/fail/in-flight、phase（running|done|**aborted**）、rate/ETA、
延迟 p50/p90（记录级）、attempts_dist、error_categories、errors_recent(10)、
分模型 token 与费用、cost_total。
raws.jsonl.meta：调用级 latency_ms、usage、**finish_reason**（length=截断付费，状态板计数展示）、response_id。
`status.py`：s1-* 读心跳；元素批读 progress+账本合成（calls/charged/在飞预留/unknown/capped），
未知时直接打印 `audit_run --settle` 下一步指令。
`audit_run`：issues（重复 attempt、孤儿 finished）、unknown 清单、raw_recoverable 提示、
`--settle` 三拒（无证据/超预留4倍/重复结算）一放（附 evidence 落 finished, manual_reconcile:true）。

诚实边界：**拉取式**，无推送告警；延迟分位数记录级；链路二无统一效率视图。

---

## 8. 产物格式

**record-{id}.json**：`{id, status:"valid", elements(七组×36字段, 证据含逐字 quote+原文 start/end),
input{target,facts_text,meta_text,text_full,text_orig_sha256}, element_schema_version(1.1.0),
element_prompt_version(element-v1), wire_version(element-ref-v3), contract_hash(全量),
prompt_fingerprint, view_hash, label_provenance:"model-adjudicated", human_review:false,
release_approved:false}`。tmp+fsync+rename 原子提交；已存在则摘要必须全等，否则拒覆盖。

**diagnostics.jsonl**：valid 行（n_diffs、difference_kinds 分布）；失败行
`{id,status(invalid|transport_failed|unresolved),error_type,category,reason(≤500字),release_approved:false}`。

**attempts.jsonl**：submitted（key/attempt_id/reservation/provider/model/context/request_hash/price）→
finished（charged/usage，可带 recovered_from_raw/manual_reconcile）/ failed（category）/ released。
**raws.jsonl**：先于一切解析校验落盘。

预算 ledger.jsonl：reserved/settled/released 事件流 + policy.json 冻结（改政策⇒换 scope）。

---

## 9. 硬编码清单（现状：位置→改法）

| 常量 | 位置 | 覆盖途径 |
|---|---|---|
| smoke12/spec36 阈值 12/¥4/¥12/252/36 | run_elements.py 治理闸 | 改码（=全量快照变、prompt 指纹不变） |
| framing +1024 字节 | durable_calls / preflight 同口径 | 改码 |
| not-sent 保守匹配词表 | durable_calls.is_not_sent | 改码（测试守卫） |
| A/B/C 供应商域识别 | provider_identity(deepseek.com/xiaomimimo.com) | 改码 |
| 裁判白名单 | **config/arbiter_models.json（现权威，2026-10-20 裁决后上线）** + arbitrate.py 兜底 | 配置文件 |
| 定价 | config/s1_prices.json（缺价=拒跑） | 配置文件 |
| legal caps | config/legal_caps.json（入契约哈希） | 配置文件 |
| 数据根 | s1._DEFAULT_DATA=D:\02_Dev\Data\justilaw-research | `JUSTILAW_DATA_DIR` |
| 引擎路径 | element_contract 兄弟目录推断 | `JUSTILAW_ENGINE_API` |
| 链路二模型 | **裁决后默认云 xiaomi-pro（run_batch.py --provider，走 s1.load_config）**；本地 Ollama 常量（qwen3.5:9b、127.0.0.1:11434、num_ctx 8192/num_predict 3000 等）仅残留在引擎 extract()，链路已不再使用 | --provider 参数 |
| 链路二停批词表 | run_batch.FATAL_MARKS=("402","Insufficient Balance","401") | 改数据目录脚本 |
| WIRE_VERSION=element-ref-v3 | element_contract | 改码=改指纹（本就该改工单） |

## 10. 环境与方法

Python `C:\Python314\python.exe -B`；工作目录 unify/；必设 `JUSTILAW_ENGINE_API`。
回归：`python -m pytest tests/ -q` ⇒ **203 passed**，全离线（fake provider/tmp data root/
monkeypatch e2e），零网络零付费。新增 runner e2e：happy（落盘+done+无残锁）与
fatal（诊断行+aborted+errors_recent 可见）各一枚。
