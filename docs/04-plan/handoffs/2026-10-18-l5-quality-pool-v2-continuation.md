# L5 quality pool v2/v3b S1 运行续跑（2026-10-18 20:06）

> 新会话先读本页，再读 run 根目录的 `MANIFEST.json` / `batch-plan.json`。**不要并行起第二个 run**。

## 1. 现在在跑什么

- 父进程：`execute_frozen_s1_batches.py --root ...\l5-quality-pool-v2-20261018 --batch ...\input\records.jsonl --workers 4`
- 4 个 `run_seg.py` 子进程：`recovery-batch05`～`08`，代码来自 `C:\Users\17728\.codex\worktrees\l5-quality-s1-run\大创`，`seg-v2-durable-4` + clause refine。
- run 根：`D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018`
- 口径池：**v3b**（`l5-quality-pool-v3b-20261018/MANIFEST.json`），不是 v2 的 377 条 ID。

## 2. 目标与已完成

- v3b：**328 选中**（4 条复用旧输出，**324 条需跑 S1**），212 事件；split：train 222 / valid 48 / test 58。
- 批次：web-r4 140、P1-r6 43、P1b-r2 24、P2-L4word 89、merged 32。
- 20:08 快照：此前 24 条已付费 + 4 条复用 = 28；recovery-batch01–09 各 12 条，10 为 9、11 为 6、12 为 6、13 为 1；全部目录去重后 **130 条完成 / 198 条待跑**（仍在增长）。
- `batch-plan.json`：`run_ids` 300、25 个 recovery 批次、`already_completed` 24；`partial-safe-v3/PROVENANCE.json` 记 `selected 328 / complete 28 / paid_in_cohort 24 / pending 300`。
- 57 条 `screenpass57-20261018-durable4/combined/outputs.jsonl` 是**另一条已完成的 57 条同版本批**（57/57，`seg-v2-durable-4`），不要和 328 池混用。

## 3. 额度与中断

- `partial-safe-v3` 的 28 条是上一轮中断前的安全快照；`PROVENANCE.json` 明确记 **provider HTTP 402 insufficient balance**。
- 当前 recovery 预算 scope：cap **15 元**、max_calls 744；ledger 已 charged **2.195 元**、reserved 14.289 元（reserved 是在途预留，不是实际花费）。
- 若继续 402/额度不足：不要新建版本或改提示词；充值/换可用额度后，用同一 run 的缓存续跑。

## 4. 新会话怎么接

1. **先看进程和锁**：`tasklist`/`Get-CimInstance` 查 `execute_frozen_s1_batches.py`、`run_seg.py`；`find . -name RUNNING.lock`。旧进程还在时不要启动同一批次，避免双跑。
2. **续跑优先用原入口**：同一 `--root/--batch/--workers` 重跑 `execute_frozen_s1_batches.py`；`DurableCalls` 会复用已完成输出，跳过缓存命中。或对 `recovery-batch09`～`25` 逐个用各自 `approved-order.json` 跑 `run_seg.py`。
3. **不要改**：prompt 版本、代码、`ids.json`、`approved-order.json`、manifest；改了会触发中途 fail-fast/合同不一致。
4. **完成后**：对 328 条跑 S3；再用 `partial-safe-v3/l5-teacher-inputs` 的模式生成教师输入；最后 L5 标注/仲裁。当前 **labels_generated=false**，79 条 `l5-handoff-unified-partial` 只是教师输入并集（56 早 + 28 后），不是标签。
5. **不要用 v2 的 377 条 `ids.json` 当目标**；v2 是更大的旧池，当前 batch-plan 与 v3b 才是权威。

## 4.1 新会话开工命令（绝对路径）

工作目录必须是：
`C:\Users\17728\.codex\worktrees\l5-quality-s1-run\大创`

1）查进程与锁：

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Select-Object ProcessId,CommandLine | Format-List
Get-ChildItem 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018' -Recurse -Filter RUNNING.lock
```

2）整批续跑（旧进程停止、锁清理后；已完成批次走缓存）：

```powershell
Set-Location 'C:\Users\17728\.codex\worktrees\l5-quality-s1-run\大创'
C:\Python314\python.exe -B research\discretion\unify\execute_frozen_s1_batches.py `
  --root 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018' `
  --batch 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\input\records.jsonl' `
  --workers 4
```

脚本按 `batch-plan.json` 跑 25 个 recovery 批次；全成功才写 `executor-summary.json`。每批结果在 `<batch>/executor-result.json`，S3 在 `<batch>/seg-run/s3/`。

3）单批续跑（以 recovery-batch12 为例）：

```powershell
C:\Python314\python.exe -B research\discretion\unify\run_seg.py `
  --batch 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\input\records.jsonl' `
  --out 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\recovery-batch12\seg-run' `
  --ids 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\recovery-batch12\ids.json' `
  --clause-refine --execute `
  --order 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\recovery-batch12\approved-order.json'
C:\Python314\python.exe -B research\discretion\unify\run_s3.py `
  --batch 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\input\records.jsonl' `
  --run 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\recovery-batch12\seg-run' `
  --out s3
```

## 4.2 聚合陷阱（必须先看）

- 当前 run 根 `MANIFEST.json` 是 **v2 377**，`batch-plan.json` 是 **v3b 328/300**；两者不一致。
- `aggregate_l5_quality_s1.py --root <run>` 读根 MANIFEST + batch-plan，直接跑会报 `incorrect paid/reused partition`。
- 解决：用 `l5-quality-pool-v3b-20261018\MANIFEST.json` 建独立聚合根（如 `l5-quality-pool-v3b-run`，链接 `input/`、`pilot5/`、`recovery-batch01-25/`、`shared-budget/`），再跑 aggregate；或给聚合器加 `--pool` 参数（需代码评审）。不要覆盖 v2 MANIFEST，不要重跑已完成批次。
- 聚合成功后产物是 `combined/outputs.jsonl` + `combined/PROVENANCE.json`。

4）教师输入（聚合后）：

```powershell
C:\Python314\python.exe -B research\discretion\unify\export_l5_inputs.py `
  --run 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\combined' `
  --unified 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\input\records.jsonl' `
  --parsed 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\input\originals.jsonl' `
  --out 'D:\02_Dev\Data\justilaw-research\s1_runs\l5-quality-pool-v2-20261018\l5-teacher-inputs-v4'
```

`input/` 已有 `edits.rle.jsonl`，满足 `load_work` 的同目录要求。

5）L5 教师/仲裁：用 `run_elements.py`，必须新建 reviewed order，不能复用 smoke12 的 order；当前 79 条 `l5-handoff-unified-partial` 只是教师输入并集，`labels_generated=false`。

## 5. 关键路径

- `l5-quality-pool-v2-20261018/MANIFEST.json`（v2 旧池 377）
- `l5-quality-pool-v3b-20261018/MANIFEST.json`（当前 328 池）
- `l5-quality-pool-v2-20261018/batch-plan.json`（300 待跑 + 24 已完成 + 25 批）
- `l5-quality-pool-v2-20261018/partial-safe-v3/PROVENANCE.json`（28 完成、402 中断）
- `l5-quality-pool-v2-20261018/shared-budget/{policy,ledger}.jsonl`（15 元 cap / 花费）
- `l5-handoff-unified-partial-20261018/MANIFEST.json`（79 教师输入，无标签）
- `screenpass57-20261018-durable4/combined/PROVENANCE.json`（57/57 同版本批）

## 5.1 L5 之前必须做的密度/正例率审计（不要跳过）

534 strict 池的正文密度（parsed facts + party 段，免费实测）：

- facts 中位 84 字；≥100 字 191/534，≥200 字 69/534。
- 关键要素出现：年龄可用 **0**（出生日期多为打码）、前科 **4**、参赌人数 **14**、营利目的 **67**、个人赌资 **152**、现场赌资 **115**、赌博方式 **297**、当事人段 **124**；**125/534 八个关键要素一个都没有**，只有 98 条有 3 个以上。
- 分渠道：法宝 170 条明显更密（个人赌资 54.1%、现场 45.9%、营利 31.8%、前科 20.6%、参赌 7.6%）；网页 364 条很稀（个人赌资 16.5%、现场 10.2%、营利 3.6%、参赌 0.3%，年龄仍是打码出生日期）。

**结论：S1/S3 质量通过不等于训练有效。** CAIL 1,400 条稀疏集训练失败是前车之鉴；534 更小且分字段极不均匀。L5 不要直接 328/534 全量标 36 要素；先抽 50–100 条做标签正例率/证据正确率/未提及率审计，并在支持字段上做一个小模型增益对照。只有正例率和下游增益过关，才扩量；否则先补密度（法宝叙述式、当事人段）或缩窄训练目标。

## 6. 一句话

**328 池在跑，20:08 快照 130 条完成、198 条待跑；recovery 01–09 已完成，10–13 在跑（parent 会继续到 25）。新会话先确认旧进程/锁，再用原 order 续跑；402 是 provider 余额，不是本地 15 元 cap；聚合前先解决 v2 377 / v3b 328 的 MANIFEST 不一致；labels 尚未生成。**
