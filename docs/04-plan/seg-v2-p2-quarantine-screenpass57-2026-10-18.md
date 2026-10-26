# P2-r1 隔离与 57 件同版本候选复跑（2026-10-18）

## P2-r1 清理：新 S1 输入

旧 `$DATA/unified_raw_refresh/20261018-s1-party/` 原样保留。`quarantine_p2_salvage.py` 在新目录 `$DATA/unified_raw_refresh/20261018-s1-party-p2-clean/` 重建 `records.jsonl`、`events.jsonl`、`no_subject.jsonl`、`MANIFEST.json` 和 `DEDUP_REPORT.md`。原 3,196 条中 `A-salvage`/P2-r1 的 313 条全部移到 `quarantine/records.jsonl`，S1 可消费记录变为 **2,883 条、1,580 事件**；同来源的无主体 62 条另移到 `quarantine/no_subject.jsonl`，未冒充可标注输入。保留集为 1,507 web + 1,376 pkulaw，train/valid/test = 1,996/427/460。

按文号哈希审计，旧输入存在 **17 个 train/valid 跨集组**，新输入为 **0**；保留集原文 SHA-256 和 event_id 也均无跨 split 重叠。因此此前那对 P2-r1 涉及的 train/valid 重复已不在新输入中。文号哈希可能碰撞或代表多人，审计项是泄漏预警，不替代人工同案判定。新 MANIFEST 保存父批次哈希、五份输出哈希与隔离计数；既有数据文件未覆盖或删除。新批次尚未让引擎消费，也未生成标签。

## 57 件同版本 S1＋S3

固定 final300 的 `fixed-quality-strata-20261018.json` 中 `candidate_screen_pass` 57 件先冻结 ID 和来源 SHA-256。此为**事后筛选的生产候选集**，并非固定 299 件总体。来源仍为 `$DATA/unified_raw/web/20261017-web-r3/records.jsonl`。采用 `seg-v2-durable-4`、同一实现快照、`--clause-refine`、DeepSeek Flash，先用包含原 3 件 screen-pass 错误的 5 件试点做付费 S1＋免费 S3，0/5 error 后再分 12/12/12/12/4 继续。每批显式工单、请求哈希、回执与共同 ¥2 上限保存在 `$DATA/s1_runs/screenpass57-20261018-durable4/`。

第 2 批运行时，共享工作树的无关 `unify` 文件被并行改动，实现快照正确阻断。以原提交建立独立执行工作树，并逐文件校验其实现哈希与已冻结的批次 manifest 完全一致；中断时已付费的响应通过原始回执缓存恢复，没有重买。六批合并前验证了 57 个唯一 ID、输出合法性、每件请求哈希、同版本/同来源/同实现快照与账本全结算。合并材料为 `combined/{outputs.jsonl,PROVENANCE.json,s3/summary.json,s3/findings.jsonl}`。

**同版本实测：57/57 S1 合法输出；免费 S3 为 44 pass、13 warn、0 error，候选集阻断错误率 0/57。** 57 次模型调用全部结算，费用 **¥1.217858**。这使原先的 shadow 0/57 预期有了同版本实测依据，但不改写固定 299 件官方分母，也不推断未经筛选原料的错误率。13 件 warn 尚需按用途审阅；S3 通过亦非人工语义金标。没有为 9 件 screen-fail 可修件追加规则，也未触发条件性的 299 件全量付费复跑。
