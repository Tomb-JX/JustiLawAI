# 后处理入口与恢复约定

2026-10-18 接管后的新入口如下。历史 `s1.py`、`arbitrate.py` 保留用于旧运行复核；新付费批次使用 `run_seg.py` / `run_elements.py`。旧脚本没有因此获得新批次资格。`run_elements.py` 的旧命令行和无验证 `merge_labels` 接口已停用，调用方须迁移到下列入口。

## 环境

从仓库根运行，安装本目录 `requirements.txt`；引擎依赖按引擎自己的依赖文件安装，测试另需 pytest。默认读取相邻 `discretion-engine/justilaw-api` 的 `app.discretion.element_labels`，其他布局须设置 `JUSTILAW_ENGINE_API` 为引擎 API 目录；同进程已加载其他引擎时拒绝混用。数据根取 `JUSTILAW_DATA_DIR`，默认 `D:/02_Dev/Data/justilaw-research`。

当前引擎仍是 schema `1.1.0` / prompt `element-v1`。`element-ref-v2` 只更改模型证据传输：模型选择允许句 ID，服务端生成原文 quote/start/end；它不是引擎语义 `element-v2` 的批准声明。

## 免费入口

以下 PowerShell 示例均不加载密钥、不调用模型。输出目录必须是新的批次目录，旧来源及旧标签只读。

```powershell
$taskData = 'D:/02_Dev/Data/justilaw-research'
python -B research/discretion/unify/replay_pipeline.py `
  --unified "$taskData/unified_raw/web/20261017-web-r3/records.jsonl" `
  --parsed "$taskData/parsed/web/20261017-web-r3/records.jsonl" `
  --run "$taskData/s1_runs/s1-20261018-segv2-final300" `
  --out "$taskData/parsed2/<new-replay-batch>"

python -B research/discretion/unify/run_elements.py `
  --unified "$taskData/unified_raw/web/20261017-web-r3/records.jsonl" `
  --parsed "$taskData/parsed/web/20261017-web-r3/records.jsonl" `
  --run "$taskData/s1_runs/s1-20261018-segv2-final300" `
  --out "$taskData/s1_runs/<new-element-plan>"

python -B research/discretion/unify/freeze_slice.py `
  "$taskData/parsed/pkulaw/20261018-P1-r6/records.jsonl" `
  "$taskData/parsed/pkulaw/20261018-P1b-r2/records.jsonl" `
  --out "$taskData/parsed2/<new-slice-batch>"

python -B research/discretion/unify/run_seg.py `
  --batch "$taskData/unified_raw/web/20261017-web-r3/records.jsonl" `
  --out "$taskData/s1_runs/<new-seg-plan>" --ids '<frozen-id-array.json>'

python -B -m pytest research/discretion/unify/tests -q -p no:cacheprovider
```

`replay_pipeline.py --elements <new-run>` 可读取新入口产生的 `record-<id>.json`；只有原文、本人、事实/元数据视图、契约哈希和最终校验均匹配的候选才接入。未提供新要素时显式写 `elements_status=not_available`，不会继承历史标签。所有输出保留 `release_approved=false`。

## 实际调用前的工单

只有显式 `--execute --order <reviewed-order.json>` 才可能调用。工单由协调登记并经复核；本提交没有代填批准或生成可执行工单。配置中的价格必须先核实，尤其不能将占位价视作已核定账单。

两个入口均要求 `stage`、`review_record`、`executor_review`、`engine_ack`、`free_replay_pass=true`、正数 `cap`、`max_calls`、`max_input_bytes`；还需如下字段：

| 入口 | 绑定字段 | 支持范围 |
|---|---|---|
| `run_seg.py` | `plan_hash`、`provider`（配置键） | 首段 `smoke12`，≤12 条、≤¥4 |
| `run_elements.py` | `contract_hash`、有序 `ids`、`providers={A,B,C}`（配置键） | `smoke12` 同上；`spec36` 须 `prior_stage_receipt` 指向同契约 `pass=true` 回执，本批选择≤36 条、批次≤¥12 |

这两个入口的 cap 是各自批次上限，不能自动代表跨阶段总预算；总工单须核算各阶段实际已耗与剩余额度，不能各自重获一份总预算。最大调用数均≤252，包含修复请求。正式试点/全量不在这两个小批执行模式中。`--ids` 必须是预冻结 JSON ID 数组；不以 `--limit` 的完成顺序替代分层烟测设计。

A/B 按实际端点校验提供方不同；C 使用既有白名单且非 DeepSeek。C 与教师共享全部 schema、本人及允许视图，输出完整字段；只有通过同一最终验证的候选才能合并。按 status/value/证据坐标集合严格比较；未变更现有“证据不同也算分歧”的口径。

## 账本、失败和恢复

- `manifest.json` 冻结来源、视图、引擎文件及本目录 Python 实现哈希。中途代码变化即停，不能在同批换规则。
- `attempts.jsonl` 在提交 HTTP 前持久化费用预留；`raws.jsonl` 在 JSON 解析前持久化原响应和 usage；新要素逐条提交文件。写盘包含 flush/fsync。
- 每个输出最多一次同上下文反馈修复；无自动换厂商。超时或传输失败可能已计费，保留整笔预留并标记未知，禁止自动重发；认证/余额故障熔断跨重启保留。
- 重启只复用相同请求哈希的原响应，并重新校验。残缺 JSONL 明确报错，不静默丢尾。`RUNNING.lock` 防同批并跑；异常进程遗留锁须确认进程已结束后再处理，不能据此推断未知请求未计费。
- 费用采用登记价格估算，包含在途和未知预留；服务端 usage 超过预留则立即停机核账。账本不保证远端恰好一次计费。

日期/金额的共享中文归一化由引擎契约决定。本地金额支持检查只核对引用内可解析的金额，不证明“该金额属于本人赌资”的语义关系；未支持的表达直接拒收。禁止为通过检查而从全文借数。

## 2026-10-18 新增模块

- 契约与哈希：`element_contract.py`（36 字段契约读取、实现/依赖快照、分歧分类）、`contract_bundle.py`（可执行契约 bundle 导出与哈希冻结）、`field_rules.py`（只读引擎字段定义、只解析批准别名，不新造字段）。
- 归一与证据：`normalization.py`（证据绑定的中文时间/金额适配；JioNLP 只做表达式解析，不读时钟、不猜事件锚，精度/开口/兼容损失显式）、`evidence_graph.py`（来源锚定候选图；当前 `classify_graph_bindings` 是**字段默认映射**，不是证据级主体判定；词法绑定只是候选，代词/联合/未映射 role 留 unresolved/needs_review）、`binding_contract.py`（候选选择编译为字段 grounding，不猜缺失关系）、`section_refs.py`（可重叠细引用，不动 S1 互斥分区）、`evidence_types.py`（半开区间 `[start,end)` 坐标类型）、`locate.py`（quote/句 ID → cleaned → orig，clean→orig 只投影一次）。
- 结果裁决：`outcome_arbitration.py` / `run_outcomes.py`（保留历史观察值；处罚上限不得用来选候选，规范诊断单独报告）；`arbitrate.py` 的旧法律锚选候选与无预算裁判路径已退役，历史决定不改动；`experiment_plan.py`（事件不交叉的小批计划，只用独立参考评估）。
- 执行可靠性：`durable_calls.py`（有界尝试、原响应落盘、append-only 尝试账本，不承诺远端恰好一次计费）、`budget_scope.py`（跨进程/跨阶段预算预留与恢复审计）、`provider_contract.py`（提供方协议声明与无密钥执行冻结）、`task_result.py`（执行失败不得伪造“未提及”等字段内容）、`audit_run.py`（只读崩溃恢复/费用审计，不丢截断尾、不重试 HTTP）。
- 诊断：`observability.py`（36 字段可观测性，与来源真值/准确率严格分开）、`diagnose_pipeline.py`（只读冻结输入的离线图/归一/分节/36 字段报告）。

以上模块只做传输、校验与诊断，不重定义引擎本体。E-05/绑定 v4 已落地：引擎 `binding_rules.py` 只定语义（8 shared / 28 target）；后处理 `classify_graph_bindings` 目前是**字段默认映射**，不是证据级主体判定；v4 诊断 61 shared / 1120 target / 528 review，`semantic_rules_approved=true`；`resolve_binding` 代码接受 shared/target/lexical，但 contract v4 的 `accept_in_resolve` 仍只写 lexical/target，artifact 与代码待统一；528 review 的 `binding_reason` 主要是未映射 role/字段，不是完整主体歧义；无绑定准确率。`element-ref-v2` 仍是传输版本，不是 `element-v2` 本体批准。
