# 契约绑定对账（引擎线，2026-10-18）

> 全面审视引擎线各契约/规范文档之间的版本引用、字段声明、绑定关系。
> 发现 **3 项版本过期引用**、**7 项绑定表遗漏**、**2 项待解决对账差异**。

## 1. 版本引用矩阵

| 文档 | 声明版本 | 引用的 schema 版本 | 引用的指南版本 | 实际当前 |
|---|---|---|---|---|
| `schema.py` | **1.1.0** | — | — | 1.1.0 ✅ |
| `element_labels.py` | PROMPT=**element-v1** | import SCHEMA_VERSION | — | 1.1.0 / element-v1 ✅ |
| `annotation-guideline.md` | **v0.4** | v1.1.0（§5 字段表） | — | v0.4 ✅ |
| `element-teacher-v1.md` | — | 1.1.0 ✅ | **v0.2.1** ❌ | 应为 v0.4 |
| `accept_element_labels.py` | CHECKER=**element-accept-v2** | import 1.1.0 ✅ | import element-v1 ✅ | ✅ |
| `agreement.py` | CHECKER=**agreement-1.0** | import 1.1.0 ✅ | — | ✅ |
| `data-spec.md` | **v0.5.1** | 示例 JSON 写 **1.0.0** ❌ | — | 应为 1.1.0 |
| `sota-baselines-and-gates.md` | **v0.6** | — | 引用 v0.2.1（G0.3）❌ | 应为 v0.4 |
| `normalization_spec.py` | — | — | — | 新增，无历史引用 ✅ |
| `evidence_contract.py` | — | — | — | 新增，无历史引用 ✅ |

### ❌ 过期引用（需修复）

| # | 文件 | 问题 | 修复 |
|---|---|---|---|
| V-1 | `element-teacher-v1.md` L4 | 引用"标注指南 v0.2.1"，实际已升至 v0.4 | 改为 v0.4 |
| V-2 | `data-spec.md` L133 示例 JSON | `schema_version: "1.0.0"` 应为 `"1.1.0"` | 更新示例 |
| V-3 | `sota-baselines-and-gates.md` G0.3 | G0.3 行只写"标注指南完成"未固定版本号，无需修改 | 无需修复 ✅ |

## 2. 字段数对账

| 声明方 | 字段数 | 组数 | 来源 |
|---|---|---|---|
| `schema.py` iter_fields() | **36** | 7 | 代码唯一来源 ✅ |
| `element_labels.py` FIELD_INFO | **36** | 7 | 从 schema.py 导入 ✅ |
| `annotation-guideline.md` §5 字段表 | **36** | — | schema.py 自动生成 ✅ |
| `element-teacher-v1.md` | **36** | 7 | 明确声明 ✅ |
| 协调单 I-20 | **37** ❌ | — | 过期误计，collab-log 已纠正 |

**结论**：引擎线内部 36 字段一致。协调单 I-20 的"37"是过期误计，已在 collab-log 登记纠正，但协调单本身未回修。

## 3. 枚举值对账

| 枚举 | schema.py 成员数 | 指南 §3 裁决规则覆盖 | 对齐 |
|---|---|---|---|
| BehaviorType | 7 | ✅ 有正反例 | ✅ |
| GamblingMethod | 9 | ✅ "打牌"默认映射 | ✅ |
| Role | 7 | ✅ 多角色优先级 | ✅ |
| VenueType | 7 | ✅ 多场所规则 | ✅ |
| MinorLevel | 2 | 指南 §3 未单独裁决（罕见） | ⚠️ 可接受 |
| FieldStatus | 3 | ✅ 三态贯穿全文 | ✅ |

## 4. 绑定表遗漏（任务书 + 依赖表）

任务书 `engine-task-assignment-2026-10-18.md` 的依赖表和 workstreams.md 未追踪以下绑定关系：

| # | 遗漏项 | 方向 | 影响 | 建议 |
|---|---|---|---|---|
| B-1 | E-05 归一化/证据契约 | 引擎 → Codex | `normalization_spec.py` + `evidence_contract.py` 是 Codex element_contract 的输入，未在依赖表登记 | 追加到依赖表 |
| B-2 | E-04 丢弃建议 → element-v2 | 引擎 → Codex | 丢弃榜中的枚举修订建议是 element-v2 的输入，任务书只在 E-04 描述中提到，未在依赖表登记 | 追加 |
| B-3 | E-06 分歧类型接口 | 引擎 ↔ Codex | `status/value/evidence-only` 三种分歧类型是 accept_element_labels 与 Codex element_contract 的接口，未在绑定表登记 | 追加 |
| B-4 | text_party 字段 | Web → 引擎 I-20 | collab-log 记录 web 数据 `text_party` 覆盖率 0/1,722，是 I-20 教师输入的依赖，任务书未提及 | 追加到依赖表 |
| B-5 | S3 硬失败率 8.7% | Web → 引擎 parsed-2 | 超过 5% 门槛，阻塞 parsed-2 组装，任务书未提及 | 追加到依赖表 |
| B-6 | legal_caps.json 正式化 | 协调 → 引擎 | collab-log 记录"待引擎复核并正式化"，任务书只写"Ready" | 更新状态 |
| B-7 | I-20 协调单 37→36 纠正 | 引擎 → 协调 | collab-log 已登记，但协调单本身未回修 | 请协调线回修 |

## 5. 待解决对账差异

| # | 差异 | 详情 | 状态 |
|---|---|---|---|
| D-1 | I-20 字段数 37 vs 36 | 协调单写 37，代码实际 36。collab-log 2026-10-18 已纠正"37 是过期误计" | 已知，协调单待回修 |
| D-2 | G0.3 pilot κ 口径 | pilot50 报告 κ=0.838（all 口径），但门禁要求 union 口径 κ≥0.80，实测 0.691 不通过 | 已知，指南验证证据而非 G0.3 通过 |

## 6. 已交付但未在绑定表登记的新产物

| 产物 | 路径 | 性质 | 登记状态 |
|---|---|---|---|
| normalization_spec.py | `research/eval/` | 引擎侧唯一归一化规则（E-05 批准包） | collab-log 已登记，依赖表未登记 |
| evidence_contract.py | `research/eval/` | 证据语义校验契约（E-05 批准包） | collab-log 已登记，依赖表未登记 |
| m1_efficiency_audit.py | `research/eval/` | M1 效率检察辅助系统 | collab-log 已登记 |
| p0-closure-2026-10-18.md | `docs/05-research/` | P0 收口报告 | 无需绑定表登记 |

## 7. 修复清单

### 立即修复（引擎线可做）

| # | 操作 | 文件 |
|---|---|---|
| F-1 | element-teacher-v1.md 引用指南 v0.2.1 → v0.4 | `docs/05-research/element-teacher-v1.md` |
| F-2 | data-spec.md 示例 JSON schema_version 1.0.0 → 1.1.0 | `docs/05-research/data-spec.md` |
| F-3 | ~~sota-baselines-and-gates.md G0.3~~ 不需要——G0.3 只写"标注指南完成"未固定版本号 | — |

### 需协调线配合

| # | 操作 | 责任方 |
|---|---|---|
| F-4 | 协调单 I-20 回修 37→36 | 协调线 |
| F-5 | 任务书依赖表追加 B-1 至 B-7 | 协调线（或引擎在 collab-log 登记后由协调线确认） |
| F-6 | legal_caps.json 引擎正式复核 | 引擎 |