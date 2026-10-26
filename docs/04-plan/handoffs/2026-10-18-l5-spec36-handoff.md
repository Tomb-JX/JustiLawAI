# L5 标注线交接：spec36 就绪（2026-10-18 17:30）

> 给接手的新会话：读 `2026-10-18-labeling-role-handoff.md` 建立角色，再读本文件了解当前进展。

## 1. 本轮做了什么

### 1.1 文档阅读（已完成）

按 §2 阅读路径读完了全部关键文档：
- `CURRENT.md`：实时状态，blocked，主线 L5 标签 + S3
- `data-spec.md` v0.4：数据交付规格
- `annotation-guideline.md` v0.2：字段标注规则（36 字段、三态、金额开口上界）
- `element-teacher-v1.md`：教师接口设计（S2 定位、教师/M1 关系、首批验收）
- `parse-engineering-design-v2` v2.8：解析管线五阶段 S0–S4 + L5 独立支线
- `i20-interface-for-engine`：网页→引擎接口包
- `element-contract-v1` handoff：契约交接详情
- `pilot300-quality-report`：S3 硬失败率轨迹 32.9%→5%、边界 F1、seg-v2 判据
- `schema.py` v1.1.0：7 组 36 字段源码
- `element_labels.py`：teacher_messages/teacher_output_schema/validate_teacher_output

### 1.2 合格集 plan（已完成）

跑通 `run_elements` plan 模式，两组合格集：

| 来源 | eligible | rejected | 文件 |
|---|---|---|---|
| final300（S1+S3 路径） | 216/299 = 72.2% | 84 | `$DATA/s1_runs/elements-final300-plan-20261018/plan.json` |
| 212 开发切片（冻结视图路径） | 212/212 = 100% | 0 | `$DATA/s1_runs/elements-devslice-plan-20261018/plan.json` |

两组零重叠（不同来源：final300=web-r3，212=pkulaw 冻结切片）。

### 1.3 missing_target_or_input 分析（已记录）

**交接文档**：`docs/04-plan/handoffs/2026-10-18-missing-target-cases.md`

| 子类 | 数量 | 根因 |
|---|---|---|
| uni_empty_s1_has | 54 | unified_raw `subject_mention` 为空，但 S1 有提取值 |
| both_empty | 3 | 双方都无 mention |
| target_not_in_projected_view | 1 | target 不在 facts/meta 投影视图 |

核心问题：`build_inputs` 读 `rec.get("subject_mention")`（unified_raw），不读 S1 的 `output.subject.mention`。54 件 S1 已正确提取但 unified 未回填。回填后 final300 eligible 预期从 216→270。

### 1.4 spec36 设计（已完成）

**设计文档**：`docs/04-plan/2026-10-18-spec36-design.md`

- 来源：212 开发切片（冻结视图，100% eligible）
- 抽样：36 件分层抽样（短<500: 10 件、中 500–800: 21 件、长≥800: 5 件）
- ID 清单：`$DATA/s1_runs/spec36-ids.json`（已生成）
- plan 验证：36/36 全部 eligible
- A/B/C：A=deepseek-flash, B=mimo-v2.6-pro, C=mimo-v2.6-pro
- 核心指标：证据定位率≥95%、A/B κ≥0.80/数值一致率≥95%、仲裁分歧率≤20%

## 2. 当前阻塞

### 2.1 smoke12 schema 校验失败

smoke12（`$DATA/s1_runs/smoke12-elements-e05/`）仅执行了 1 件（W-000023），失败：

```
wire_schema:['amounts','cumulative_stake','evidence',0,'sentence_ids',0]:type;...
```

`sentence_ids` 类型不匹配。smoke12 的 `execution-manifest.json` 显示 B=qwen3.8-flash、C=mimo-v2.6-flash（非 pro），需确认 wire schema 版本是否与 `element-ref-v2` 一致。

**需修复 smoke12 才能执行 spec36**（工单要求 smoke12 验收回执）。

### 2.2 B/C 模型配置需更新

smoke12 用的是 B=qwen3.8-flash / C=mimo-v2.6-flash，spec36 设计要求 B/C=mimo-v2.6-pro。需在 order 文件中更新。

## 3. 下一步（按优先级）

1. **修 smoke12 schema 问题**：检查 `element-ref-v2` wire schema 中 `sentence_ids` 字段定义，确认类型是否与 `element_labels.py` 的 `teacher_output_schema()` 一致。可能是 `compile_references` 回填 `sentence_ids` 时类型不对。
2. **重跑 smoke12**：修复后用正确的 A/B/C 配置重跑 12 件，拿到验收回执。
3. **执行 spec36**：smoke12 通过后，用 `spec36-ids.json` + 冻结工单执行 36 件。
4. **分析 spec36 结果**：字段准确率、A/B 一致率、仲裁分歧率、证据定位率。
5. **记录 S1 输入问题**：58 件 missing_target_or_input + 25 件 upstream_s3_error 交解析线。

## 4. 关键路径

```
$DATA = D:/02_Dev/Data/justilaw-research
实时状态：$DATA/coordination/CURRENT.md
final300 plan：$DATA/s1_runs/elements-final300-plan-20261018/plan.json
212 plan：$DATA/s1_runs/elements-devslice-plan-20261018/plan.json
smoke12（已执行）：$DATA/s1_runs/smoke12-elements-e05/
smoke12 plan（从 final300 选 ID）：$DATA/s1_runs/smoke12-elements-e05-plan/
spec36 ID：$DATA/s1_runs/spec36-ids.json
spec36 输出目录（待执行）：$DATA/s1_runs/spec36-devslice-20261018/
case 文档：docs/04-plan/handoffs/2026-10-18-missing-target-cases.md
设计文档：docs/04-plan/2026-10-18-spec36-design.md
角色交接：docs/04-plan/handoffs/2026-10-18-labeling-role-handoff.md
引擎代码：.claude/worktrees/discretion-engine/justilaw-api/app/discretion/
后处理代码：.claude/worktrees/seg-v2-design-review/research/discretion/unify/
```

## 5. 已登记事件

- `evt-20261018172518-fe75b8`：L5 final300 plan 结果（216 eligible, 58 missing_target）
- `evt-20261018172845-e830d2`：spec36 设计 draft

## 6. 开放问题（同角色交接 §9）

1. 回填 unified_raw `subject_mention` 后重跑 plan——是否需要先做？
2. smoke12 schema 修复——需检查 wire schema vs element_labels.py 的 `sentence_ids` 类型
3. mimo-v2.6-pro 可用性——需确认 xiaomi 提供商的 pro 模型是否可调用