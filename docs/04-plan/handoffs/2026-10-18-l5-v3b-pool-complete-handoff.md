# L5 v3b 池轨道完成交接：S1→聚合→S3→教师输入（2026-10-18 21:00）

> 承接 `2026-10-18-l5-quality-pool-v2-continuation.md`（该文件是 20:06 快照，本页是终态）。
> 本页覆盖池轨道（l5-quality-pool-v3b，328 条）；devslice 212 冻结视图轨道见
> `2026-10-18-l5-spec36-handoff.md`，两者独立、互不混用。

## 1. 已完成（全部验证通过）

1. **S1 付费跑完**：`executor-summary.json` 25/25 批全部成功（s1/s3 exit 0），
   池内 324 条 paid 输出 **324/324** 完整。花费 charged **8.709 元** / cap 15 元；
   本轮无 402。账本有 **27 条 402 时代遗留的 unknown-reserved**（每 safe-batch 一条，
   设计性保留、不再自动重发），非新增开销。
2. **聚合完成**（交接 §4.2 的聚合陷阱已解决）：
   - 聚合根：`D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v3b-run\`
     （junction 指向真实批次目录，零复制；`batch-plan.json` 为该根自有的聚合视图副本
     run_batches=safe-batch01..04+recovery-batch01..25，原 run 根 batch-plan 未动）。
   - 方式＝交接允许的第二条路："给聚合器加 `--pool`"——已实现并代码评审：
     `aggregate_l5_quality_s1.py` 新增 `--pool` 与 `--pool-scoped`
     （分支 `codex/l5-quality-s1-run-aggregate` 提交 `5bf78d4`，基于 `001324d` 线）。
     pool-scoped 语义＝池内过滤：pilot5 的 1 条池外输出与 reused-outputs 的第 5 行
     （v2 池残留 `S1-06594f87226a72852c70`）被过滤并记入 PROVENANCE.pool_scoping；
     safe-batch01-04 部分快照按子集校验，全局 `set(paid)==missing` 仍兜底完整性；
     遗留未知预留仅在 `executor-summary.json` 存在（全批成功）时容忍。默认行为不变。
   - 产物：`l5-quality-pool-v3b-run/combined/outputs.jsonl` **328 行＝324 paid＋4 reused**，
     按池序、全部 ok、单一 `seg-v2-durable-4`；`combined/PROVENANCE.json` 的
     pool_sha256＝v3b MANIFEST、outputs_sha256 复核一致；paid_calls 325、settled 8.70879 元。
3. **S3 全量**：`combined/s3/` 328 条＝pass 231 / warn 95 / **error 2**
   （value_grounded|error 2 条，均为叙述式-独立成篇）。
4. **教师输入 v4**：`l5-quality-pool-v3b-run/l5-teacher-inputs-v4/`
   **accepted 203 / quarantine 125**（answer_leakage 123 + upstream_s3_error 2）。
   运行需 `JUSTILAW_ENGINE_API=D:\02_Dev\Projects\大创\.claude\worktrees\discretion-engine\justilaw-api`。
   accepted 分布：split train140/valid23/test40；批次 web-r4 137 / P1-r6 40 / P1b-r2 24 /
   merged 2；**P2-L4word 批次 0 通过**（89 条全部泄漏隔离——L4 Word 文本的视图含
   legal_basis/penalty_amount 特征，值得后续单独复核是否视图构造不适配）。

## 2. 重要勘误与证据链

- partial-safe-v3/l5-teacher-inputs 的 **28/28 全过（19:58 生成）不可复现**：用现行冻结
  代码（001324d 谱系）对同一 28 行输出重跑导出，结果 **26/2**，被隔离的正是
  `S1-4e84a21f9a0266f1bcdc`（legal_basis+penalty_amount）与 `S1-5f1a714c4322a214feef`
  （legal_basis）——两行 S1 输出字节级一致。19:58 那次属旧代码谱运行，作废；
  **以 v4 为准**（labels_generated=false 状态不变）。
- v2 的 377 池 `ids.json` 继续无效为聚合目标；v3b 328 是唯一权威（batch-plan.pool 已指 v3b）。

## 3. L5 标注准备（停在用户授权，未扣费）

- 池轨道 smoke12 计划已生成（plan 模式，免费）：`s1_runs/l5-v3b-smoke12-plan-20261018/`
  eligible 12/12；**contract_hash `dda4c88bd6ad985ded76333dd84cbdfcafc3ae8511bcf3c15ab7e9dcb7102006`**。
- 12 条分层样本（自 accepted 203）：train8/valid2/test2；web-r4 7/P1-r6 4/P1b-r2 1。
  ids 冻结：`s1_runs/l5-v3b-smoke12-ids-20261018.json`。
- 工单草稿：`s1_runs/l5-v3b-smoke12-order-DRAFT.json`——stage smoke12、cap 4 元、
  max_calls 72、providers A=deepseek/B/C=xiaomi-pro、budget_scope=新目录
  `s1_runs/l5-v3b-elements-budget`。**三个 review 字段＝PENDING-USER-AUTHORIZATION、
  free_replay_pass=false**：执行前须由用户改为 `user-authorized-*` 并置 true
  （先例：`smoke12-order-r2.json`）。
- 治理约束（runner 硬编码）：smoke12≤12 件/≤4 元 → spec36 需 smoke12 pass 回执 →
  **全量 203 条必须另审工单**（本 runner 上限 36 件/单）。
- 待用户决策：① 批准并执行池轨道 smoke12（约 1 元内）；② smoke12 验收 pass 后是否
  组 spec36；③ 203 全量的另审工单设计；④ P2-L4word 0 通过是否需要视图侧排查。

## 4. 关键路径速查

- 聚合根 `D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v3b-run\`
  （combined/ + combined/s3/ + l5-teacher-inputs-v4/ + batch-plan/executor-summary 副本 + junctions）
- 池清单 `l5-quality-pool-v3b-20261018/MANIFEST.json`（328/4/324，pool_sha 见 PROVENANCE）
- 代码 `C:\Users\17728\.codex\worktrees\l5-quality-s1-run\大创` @ `5bf78d4`
  （分支 codex/l5-quality-s1-run-aggregate；引擎 env 见 §1.4）
- 工单与样本 `s1_runs/l5-v3b-smoke12-{ids-20261018.json, plan-20261018/, order-DRAFT.json}`
- 预算 `l5-quality-pool-v2-20261018/shared-budget/`（charged 8.709/15；27 条遗留 unknown 已入 PROVENANCE）

## 5. 其他备忘

- devslice 轨道的 `smoke12-elements-pin-20261018/` 留有**陈旧 RUNNING.lock**（中断残留；
  runner 用 `open('x')`，续跑该目录前须人工删锁）。其"spec36 须同 pin(7b0d9ff)"约束只适用
  devslice 轨道回执链，池轨道自身契约独立（dda4c88b…）。
- collab-log.md 有多会话未提交改动，本文件单独提交，不代管他人条目。

## 6. 一句话

**v3b 池 S1+聚合+S3+教师输入全部完成并验证（328=324+4；accepted 203）；池轨道 smoke12
工单已备草稿、契约哈希已固定，唯一停点是用户授权扣费与后续阶梯（spec36/全量另审）。**
