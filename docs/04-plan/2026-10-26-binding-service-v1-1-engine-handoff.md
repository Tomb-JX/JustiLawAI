# 绑定服务 v1.1 代修与引擎交接（2026-10-26）

依据引擎接入审核 `BIND-SVC-01`，引擎线代修 `codex/seg-v2-design-review` 提交 `8862e3b` 的服务代码。旧 `binding-v1` 权重保留；本次没有训练、调用大模型或把绑定输出写入要素训练集。

## 修改

1. `amounts.personal_stake` / `amounts.onsite_stake_total` 的自动绑定要求冻结链路、语义模型、pair 模型的**值键和同一原文金额候选同时一致**。旧 S2 的 `C-amount-*` 与供应包 `Q-*` 仅在**原文起止坐标、原文金额文字及结构化数值完全一致**时映射；同为 100 元但位于不同人的两处原文时，返回 `unresolved:relation_ambiguous`，保留各路原始 ID、建议与候选证据。
2. 金额键将确切 100 元记为 `amount:100`，开口 `{100,null}` 记为 `amount:100+`；bound 输出直接保存结构化 `{min,max}`，且必须与选中候选的引擎归一化投影一致。不再让接入方从字符串猜上界。
3. 服务入口强制核验 `source_sha256`、按现有规范重算 `sentence_view` 的 `view_hash`，绑定记录使用供应包生成的 person ID，顶层继续保留 record ID。
4. 人数绑定的“明确人数＋姓名名单”两条依据均输出原文坐标；名单候选的待审建议也带坐标，不再只有 `kind=name_list`。
5. 新 manifest 绑定所有运行时已导入的 `unify` 模块文件、引擎 `app/discretion/*.py` 及 E-05 的三份批准模块哈希。服务启动时逐项核验，任何实现漂移均拒绝启动。`engine_root` 传入值同时用于 E-05 模块定位；一个进程不能混用两个不同引擎根目录。

## 版本与运行

- 代码分支：`codex/binding-service-v1-fix`，基于 `8862e3b` 的隔离工作树；核心提交 `d79d76b`、`06ae039`、`18eb2d6`、`47bffae`，未覆盖 `codex/seg-v2-design-review` 在途修改。
- 冻结目录：`$DATA/serving/binding-v1.1-47bffae/`，版本 `binding-v1.1`，`MANIFEST.json` 记录代码提交及 32 个运行时、9 个引擎、3 个 E-05 文件哈希。由 `reseal_binding_service.py` 从旧 `binding-v1` **复制原权重**并写新 manifest；旧目录不改。
- 早期尝试目录 `$DATA/serving/binding-v1.1/`、`binding-v1.1-06ae039/`、`binding-v1.1-18eb2d6/` 对应中间代码，哈希校验会拒绝当前运行时；**不要使用**。
- 运行命令：`py -3.14 research/discretion/unify/binding_service.py --artifacts $DATA/serving/binding-v1.1-47bffae --engine-root <discretion-engine/justilaw-api> --inputs <S1允许视图.jsonl> --out <输出.jsonl> --threads 8`。

## 验证与放行边界

- `research/discretion/unify/tests`：217 passed；新增同额异人、旧/新候选同坐标映射、开口/确切金额、来源/视图哈希反例。
- 三条冻结输入的 CLI 烟测和引擎影子审计通过，输出在 `$DATA/engine/binding-service-audit-20261026/outputs-v1.1-47bffae-smoke.jsonl`，审计在同目录 `smoke-47bffae-audit.json`。
- H3 171 条的离线回放结果待填；同一批已用于开发，不能作为独立上线验收。
- 当前仍为**影子接入**。4 个字段 `bound` 不能直接转换为 `reference_elements`、M4 训练特征或在线裁量输入。引擎线需完成字段适配、证据坐标校验和独立样本评估，逐字段放行。`unresolved` 必须留在人工复核队列，不可自动当作“未提及”。

`$DATA` = `D:/02_Dev/Data/justilaw-research`。原文只留在外置数据目录，本交接不包含原文正文。
