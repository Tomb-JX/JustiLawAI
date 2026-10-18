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

## 26,185 不是去重后的数量

全量树是 **41 个 parsed 批次的并集**，包含历史批、重复批和同源页。按输出记录粗算：

| 口径 | 数量 |
|---|---:|
| 总记录 | 26,185 |
| 唯一 `id` | 7,333 |
| 唯一 `text_orig_sha256` | 7,468 |
| 唯一 `text_orig_sha256 + subject_mention` | 7,476 |
| 唯一 `doc_no_hash` | 6,726 |

所以 26,185 里有大量跨批重复：web-r2/web-r3/web-r4 同源重叠，旧 pkulaw 批与 merged/P1/P1b 重叠，P2-r1 还有 761 条重复权限页。**该树只做格式转换，没有做事件去重，不能整体直接喂 S1。**

## 当前可用性评级（operational，不是正式 A/B/C 语料评级）

| 级别 | 规则 | 记录数 | web | pkulaw | 说明 |
|---|---|---:|---:|---:|---|
| A：S1-ready | canonical + format_ok + release + 有 facts 或 decision | **3,728** | 2,225 | 1,503 | 可进 S1；A 内唯一 id 3,613、唯一 text 3,700 |
| B：canonical 但未就绪 | canonical + format_ok，但未 release 或无 facts/decision | 2,814 | 2,812 | 2 | 2,675 未 release；139 release 但无内容 |
| C：canonical 不合格 | canonical 但 format_ok=false | 1,746 | 0 | 1,746 | 全部是 P2-r1（重复权限页/稀疏） |
| 历史/实验 | 非 canonical | 17,897 | 14,927 | 2,970 | 旧 web/旧 pkulaw/实验批；仅作历史 |
| 总计 | — | 26,185 | 19,964 | 6,221 | — |

A 级内部：

- 有源 `text_party`：1,112 条（P1/P1b/merged）；
- 无 `text_party`：2,616 条（web-r4 2,225 + P2-L4word 317 + P1/P1b/merged 中 74 条无 party）；
- 按源 `event_key` 粗算只有 **1,622** 个 event_key，且跨源公式不一致；这是“事件去重会显著缩小数量”的证据，不是权威事件数。

## 事件去重应该在哪

- `to_unified.py` 是**格式转换器**：逐批转 cleaned_text/sentences/edits/zones_det，不做跨批/事件去重。
- `freeze_slice` 为开发切片做保守事件分组（event_key/doc_no_hash/重复正文），但只覆盖切片，不是全量树。
- 正确顺序应是：**先按来源页/文档去重 → 再按 event_key 分事件 → 每个事件保留一人一条记录 → 再进 S1/切片**。不能把 26,185 当成 26,185 个独立事件，也不能把多人事件折叠成一条。

## 已产出的 S1 输入（去重 + 事件归并）

`$DATA/unified_raw_refresh/20261018-s1/`：

| 项 | 数量 |
|---|---:|
| label-ready 记录 | **3,196** |
| event | **1,790** |
| grade A / A-salvage | 2,883 / 313 |
| train / valid / test | 2,202 / 495 / 499 |
| party_available | 1,320 |
| no-subject（单独文件，不送教师） | **558** |
| 唯一 id / 唯一 event+subject | 3,196 / 3,196 |
| release=false / 空文本 / 空句表 | 0 / 0 / 0 |

批次构成：web-r4 1,507、merged-full 825、P2-r1（salvage）313、P2-L4word 295、P1-r6 156、P1b-r2 100。

去重规则：

- 先按 `(channel, doc_key, subject)` 去来源页/人重复；
- 再按 `(event_id, subject)` 去事件/人重复；
- `event_id` 优先源 `event_key`，缺失时用 `doc_no_hash`/`text_sha` 稳定哈希；
- 每个 event 只落一个 split，同一事件不跨 train/valid/test；
- 多人事件保留每人一条，不折叠成一条。

S1 离线 plan 已跑通：`$DATA/s1_runs/s1-20261018-dedup-plan/`，plan hash `ee9cb165…`，`executed=false`，无模型调用。

剔除/隔离：

- `not_released` 2,675；`no_facts_or_decision` 139；P2-r1 无内容 384；
- `duplicate_id_within_batch` 760；`duplicate_page_person` 313；`duplicate_event_person` 263；
- `no_subject` 558 单独写入 `no_subject.jsonl`，不进教师批；其中 web 486、P2-r1 62、P1b 7、P1 3。

**这仍是 S1 输入，不是标签**：`reference_elements` 仍为 null；A-salvage 来自 P2-r1 清理后的 313 条，不是金标；web/P2-L4word 的 party 缺口仍在。

## party 段批量回收（2026-10-18）

用 `recover_party_segments.py` 对 canonical 6 批做保守回收：

- 只取 `text_full` 的连续子串；
- 优先“违法行为人/被处罚人/当事人/行政相对人”开头的当事人句；
- 其次取 `行政相对人：`、`相对人名称`、`行政相对人名称` 等表格行（含下一行取值）；
- 拒绝决定/罚款/拘留/依据等处罚句；
- 写入 `$DATA/parsed_refresh/20261018/`，不改源批。

结果：

| 批次 | 记录 | 原有 party | 回收句 | 回收表格行 | 未回收 |
|---|---:|---:|---:|---:|---:|
| web-r4 | 5,037 | 0 | 2,039 | 261 | 2,737 |
| P2-L4word | 317 | 0 | 0 | 317 | 0 |
| merged-full | 890 | 817 | 1 | 72 | 0 |
| P2-r1 | 1,746 | 982 | 1 | 0 | 763 |
| P1-r6 | 183 | 183 | 0 | 0 | 0 |
| P1b-r2 | 115 | 114 | 0 | 0 | 1 |

合计回收 **2,691** 条（句 2,041 + 表 650），原有 2,096 条，未回收 3,501 条。web 未回收主要是执法公示/复议/处罚摘要；P2-r1 未回收主要是权限页/字段表。

用回收后的 parsed 重新生成：

- `$DATA/unified_raw_refresh/20261018-party/`
- `$DATA/unified_raw_refresh/20261018-s1-party/`：**3,196 条 / 1,790 事件**，与去重版同构；
- `party_available`：**2,460**（原 1,320）；web 772、pkulaw 1,688；
- 仍无 party：736（web 735、pkulaw 1）；
- `no_subject` 558 不变，仍单列，回收 party 不能补 target；
- S1 离线 plan：`$DATA/s1_runs/s1-20261018-dedup-party-plan/`，plan hash `17da2993…`，`executed=false`。

**口径**：回收是 source-grounded 的规则结果，不是人工审核；未回收的记录不能假装有 party。优先用 `20261018-s1-party`，旧 `20261018-s1` 留作对照。

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
