# Case：final300 missing_target_or_input 58 件分析（2026-10-18）

> From: L5 标注线
> To: 解析/后处理线
> 用途：记录 `run_elements` plan 模式在 final300 上拒绝的 58 件 `missing_target_or_input`，供解析线排查 `subject_mention` 回填

## 1. 合格集概况

| 来源 | eligible | rejected | input_mode |
|---|---|---|---|
| final300（S1+S3 路径） | 216/299 = 72.2% | 84 | s1_s3_qualified |
| 212 开发切片（冻结视图路径） | 212/212 = 100% | 0 | development_slice_no_s3_certificate |

两组零重叠（不同来源）。

## 2. 拒绝原因分布

| 原因 | 数量 | 说明 |
|---|---|---|
| `missing_target_or_input` | 58 | target 不在 facts/meta 投影视图中 |
| `upstream_s3_error` | 25 | S3 校验有 error（facts_quality/decision_present/subject 等） |
| `s1_failed` | 1 | S1 调用失败 |

## 3. missing_target_or_input 详细分类

`build_inputs` 读 `rec.get("subject_mention")`（unified_raw 字段），不读 S1 的 `output.subject.mention`。

| 子类 | 数量 | 根因 |
|---|---|---|
| **uni_empty_s1_has** | 54 | unified_raw `subject_mention` 为空，但 S1 输出有 `subject.mention`（且在原文中可找到） |
| **both_empty** | 3 | unified_raw 和 S1 都无 subject mention |
| **target_not_in_projected_view** | 1 | 两边都有 mention，但投影到 facts/meta 视图后 target 不在其中 |

### 3.1 典型 case（uni_empty_s1_has）

| ID | S1 subject.mention | unified subject_mention | 说明 |
|---|---|---|---|
| W-001006 | 周某某 | （空） | S1 正确提取，unified 未填 |
| W-000861 | 周志香 | （空） | 同上 |
| W-000955 | 曹某某 | （空） | 同上 |
| W-001841 | 杨xxx | （空） | S1 还提取了 aliases: ['杨xx'] |

### 3.2 根因

`run_elements.build_inputs` 的 target 来源是 `rec.get("subject_mention")`，即 unified_raw 记录的 `subject_mention` 字段。该字段在部分记录中未被回填（可能是渠道/收割层未提取，或 S1 提取后未写回 unified_raw）。

S1 输出的 `output.subject.mention` 是模型提取值，54 件中全部能在 `cleaned_text` 中找到。

## 4. 建议处置

1. **回填 unified_raw `subject_mention`**：从 S1 `outputs.jsonl` 的 `output.subject.mention` 回填到 unified_raw 的 54 件记录。回填后重跑 plan，预期 eligible 从 216 升至 270 左右。
2. **排查 both_empty 的 3 件**：W-000075、W-000170、W-000172，需人工确认是否为汇总页/无本人案件。
3. **排查 target_not_in_projected_view 的 1 件**：S1 分区可能把 target 所在句子归到了非 facts/meta 区间。
4. **S3 error 的 25 件**：是 S3 硬失败（8.7% 的一部分），不影响教师标注（教师不看 S3），但这些件不能进标注批次。

## 5. ID 清单

### missing_target_or_input（58 件）

```
W-001006 W-000861 W-000951 W-000871 W-001272 W-000955
W-000880-d12 W-001005 W-001119 W-001917 W-000602 W-000881-d50
W-002066-d13 W-002066-d4 W-001841 W-001313 W-000880-d229 W-000881-d49
W-002065-d56 W-002036 W-000510 W-000882-d7 W-000881-d106 W-000881-d118
W-002048 W-002043 W-000880-d117 W-002058-d2 W-000962 W-000881-d83
W-000223 W-000881-d161 W-000230 W-001511 W-000243 W-000560 W-001842
W-001861 W-000075 W-000172 W-000170 W-001756 W-000344-8 W-000648-360
W-000648-362 W-000649-23 W-000153-d23 W-000074-1 W-000159-d37 W-000477-24
W-000476-29 W-000156-d47 W-000476-32 W-000088-44 W-000477-13 W-000477-26
W-000477-32 W-000476-36
```

### upstream_s3_error（25 件）

```
W-000105 W-000881-d176 W-000107 W-002065-d34 W-000233 W-000798-d4
W-001186 W-000522 W-000205-d4 W-000523 W-000881-d174 W-000963
W-000880-d172 W-000333-d10 W-002126 W-000314-d13 W-000837 W-000412
W-000524 W-000421 W-000429 W-000459 W-000372-d2 W-000204 W-000541-r3
```

### s1_failed（1 件）

```
W-000952
```