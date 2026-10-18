# parsed → unified_raw 全量刷新（2026-10-18）

## 做了什么

用 `research/discretion/unify/refresh_unified_batches.py` 把 `$DATA/parsed` 下所有批次重新转换为新的 `unified_raw` 树：

```text
$DATA/unified_raw_refresh/20261018/<channel>/<batch>/
  records.jsonl
  edits.rle.jsonl
  stats.json
```

旧 `$DATA/unified_raw` 和 `$DATA/parsed` 未改动；新树用于 S1 前格式。

## 结果

- 41 批，0 转换错误，26,185 条；
- `format_ok` 24,439 条（93.3%）；
- `content_ready`（有 facts 或 decision）22,659 条；
- canonical 主批次 8,288 条；
- canonical 中 `prefilter.release=true` 且 `content_ready` 3,728 条；
- canonical 中 `release` 且 facts 非空（L5 至少需要 facts）3,557 条。

## 推荐进入 S1 的主批次

| channel | batch | records | released | released+content | released+facts | party_segment |
|---|---|---:|---:|---:|---:|---:|
| web | `20261018-web-r4-table-repair` | 5,037 | 2,362 | 2,225 | 2,086 | 0 |
| pkulaw | `20261018-P1-r6` | 183 | 183 | 181 | 180 | 183 |
| pkulaw | `20261018-P1b-r2` | 115 | 115 | 115 | 114 | 114 |
| pkulaw | `20261018-P2-L4word` | 317 | 317 | 317 | 317 | 0 |
| pkulaw | `merged-20261017-full` | 890 | 890 | 890 | 860 | 817 |

路径统一为：

```text
$DATA/unified_raw_refresh/20261018/<channel>/<batch>/records.jsonl
```

## 已知不合格/受限

- **P2-r1**：1,746 条里有 761 条重复 `P-2963`（权限提示页），`duplicate_ids=760`，`format_ok=false`；只有 591 条有 facts、40 条有 decision。候选内容 602 条也需先清理，不能直接进 S1。
- **web-r4 / P2-L4word**：`text_party=0`。facts/decision 可用，但年龄、身份、前科等 meta 依赖字段受限；不是“整批不可用”。
- 历史/实验批（web-r3、旧 pkulaw、table-row-repair b1/b2）已转换，但不在 canonical 清单；不要和主批次混算。
- 这是格式/可得性清单，不是标签质量验收；`reference_elements` 仍为 null。

## 产物

- `$DATA/unified_raw_refresh/20261018/CATALOG.json`：逐批台账、哈希、字段覆盖、notes；
- `$DATA/unified_raw_refresh/20261018/REPORT.md`：逐批表格；
- `$DATA/unified_raw_refresh/20261018/QUALIFIED.md`：主批次与异常清单。

## 复现

```bash
python -B research/discretion/unify/refresh_unified_batches.py \
  --source-root "$DATA/parsed" \
  --out-root "$DATA/unified_raw_refresh/20261018"
```

`--only <batch1,batch2>` 可只跑指定批次。脚本只读源批次，写新树；不修原文、不产标签。
