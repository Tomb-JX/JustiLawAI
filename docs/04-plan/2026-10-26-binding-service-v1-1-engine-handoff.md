# 绑定服务 v1.1 代修与引擎交接（2026-10-26）

依据引擎接入审核 `BIND-SVC-01`，引擎线代修 `codex/seg-v2-design-review` 提交 `8862e3b` 的服务代码。旧 `binding-v1` 权重保留；本次没有训练、调用大模型或把绑定输出写入要素训练集。

## 修改

1. `amounts.personal_stake` / `amounts.onsite_stake_total` 的自动绑定要求冻结链路、语义模型、pair 模型的**值键和原文候选 ID 同时一致**。三路同为 100 元但分别指向不同人时，返回 `unresolved:relation_ambiguous`，保留各路建议与候选证据。
2. 金额键将确切 100 元记为 `amount:100`，开口 `{100,null}` 记为 `amount:100+`；bound 输出直接保存结构化 `{min,max}`，且必须与选中候选的引擎归一化投影一致。不再让接入方从字符串猜上界。
3. 服务入口强制核验 `source_sha256`、按现有规范重算 `sentence_view` 的 `view_hash`，绑定记录使用供应包生成的 person ID，顶层继续保留 record ID。
4. 新 manifest 绑定所有运行时已导入的 `unify` 模块文件、引擎 `app/discretion/*.py` 及 E-05 的三份批准模块哈希。服务启动时逐项核验，任何实现漂移均拒绝启动。`engine_root` 传入值同时用于 E-05 模块定位；一个进程不能混用两个不同引擎根目录。

## 版本与运行

- 代码提交：`d79d76b`（数值与候选共识），`06ae039`（E-05 运行根目录与来源哈希）。工作树：`binding-service-v1-fix`，从 `8862e3b` 隔离创建，未覆盖 `codex/seg-v2-design-review` 在途修改。
- 冻结目录：`$DATA/serving/binding-v1.1-06ae039/`，版本 `binding-v1.1`，`MANIFEST.json` 记录代码提交及 32 个运行时、9 个引擎、3 个 E-05 文件哈希。由 `reseal_binding_service.py` 从旧 `binding-v1` **复制原权重**并写新 manifest；旧目录不改。
- 一次尝试生成的 `$DATA/serving/binding-v1.1/` 对应中间代码，哈希校验会拒绝当前运行时；**不要使用**。权威新目录带 `-06ae039` 后缀。
- 运行命令：`py -3.14 research/discretion/unify/binding_service.py --artifacts $DATA/serving/binding-v1.1-06ae039 --engine-root <discretion-engine/justilaw-api> --inputs <S1允许视图.jsonl> --out <输出.jsonl> --threads 8`。

## 验证与放行边界

- `research/discretion/unify/tests`：216 passed；新增同额异人、开口/确切金额、来源/视图哈希反例。
- 三条冻结输入的 CLI 烟测成功，输出在 `$DATA/engine/binding-service-audit-20261026/outputs-v1.1-fixed.jsonl`。
- H3 171 条的离线回放结果待填；同一批已用于开发，不能作为独立上线验收。
- 当前仍为**影子接入**。4 个字段 `bound` 不能直接转换为 `reference_elements`、M4 训练特征或在线裁量输入。引擎线需完成字段适配、证据坐标校验和独立样本评估，逐字段放行。`unresolved` 必须留在人工复核队列，不可自动当作“未提及”。

`$DATA` = `D:/02_Dev/Data/justilaw-research`。原文只留在外置数据目录，本交接不包含原文正文。
