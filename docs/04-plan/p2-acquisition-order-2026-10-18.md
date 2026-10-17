# P2 增量采集工单（2026-10-18 · 用户批准 · 协调层下发）

> 依据：[数据分布与增量方向](./data-distribution-2026-10-18.md) §4；用户 2026-10-18 批准"只买密度"方案。
> 执行方：法宝线（主检出目录 `zcode/pkulaw-agent-stable`）。协调层只核账，不代跑。
> **时限：今日（10-18）内用完到期积分**；10,000 分今日到期，过期作废。

## 1. 预算与停止规则

| 项 | 值 |
|---|---|
| 账号 | 新临时 Token（`~/.pkulaw/mcp/config.json`，余额 10,275；**内置 ZCode MCP 仍是旧 Token，禁止使用**） |
| 调用预算 | **≤120 次（9,000 分）**；预留约 1,275 分（含 275 非到期）作重试/核验 |
| 计费 | 每次 `search_enforcement` 75 分；一律 `--workstream data` 记账 |
| 停止规则 | 单格（省×词）最近一次调用新增去重候选 <5 条即停止该格；总调用达 120 次即停 |
| 采前/采后 | 各跑一次 `balance` 记余额；`ledger` 导出本轮台账 |

## 2. 检索矩阵（核心 66 格，按需追加）

**省份（6）**：江苏省、河北省（目标省）；湖南省、浙江省（法宝富矿）；山东省、湖北省（面扩）。
**词（11）**：

| 组 | 词 | 目标要素 |
|---|---|---|
| P1 年龄/前科 | `周岁`、`前科`、`曾因赌博`、`被行政拘留` | age / last_prior_penalty_date |
| P2 赌资/抽头 | `携带赌资`、`个人赌资`、`抽头`、`渔利`、`台费` | personal_stake / commission |
| P3 人数/现场 | `参赌人员`、`现场查获赌资` | participant_count / onsite_stake_total |

- 6 省 × 11 词 = 66 次；剩余约 54 次用于：高产出格的**机关/年份细分**（同一机关批次集中，按机关名再切一次）、高产出格的**近义变体**（如 `赌资较大`、`抽头渔利`、`营利`）。
- 每次只传**一个省**（`lawRegional: ["江苏省"]`），避免多省合并被单机关占满。
- 不设公布日期窗（要素密度不依赖年份）；如某格 total 极大，再按 2020–2026 切片。
- **不采**：`不决字`（已 66 件）、2026 T-time（已 89 件）、网页公示扩面（密度低）。

## 3. 计数纪律

- MCP `queryText` 是**词元 AND、顺序无关**，`total` 不是短语命中；计数型勘探必须带**乱序词对照**（playbook v0.6），并把 `total` 标为"词元命中"。
- 每格记录：`total`（命中总数）、`returned`（本页 ≤20）、`new`（去重后新增）、`points`。
- 候选质量以**下载后六校验**为准，不以标题/摘要判断（标题无赌博字样 ≠ 非赌博，实测已证）。

## 4. 产出与去重

1. 目录：`$JUSTILAW_DATA_DIR/inbox/pkulaw/20261018-P2/`
2. `worklist.csv`：列 `cell_province, cell_term, rank, doc_no, title, authority, publish_date, url, source_ref, fetched`
3. `cells.csv`：列 `province, term, total, returned, new, points, last_call_at`
4. `report.md`：本轮调用数、花费、余额前后、逐格产出、Top 机关/年份、去重统计
5. **去重**：与现有台账（P- 前缀全部）、`20261018-P1/P1b` 批次、`补缺轮`、`2026T` 工单按文号/引证码交叉去重；同文号保留最早入台账者
6. 下载：零积分，按 `--cap` 分批；优先 江苏/河北 × (周岁/前科/携带赌资/抽头/参赌人员)；六校验照旧（文号/赌博/年份窗/叙述式/未打码/去重）
7. 入库：下载件 → 台账 → `pkulaw_ingest.py docs` → `parsed1` → `unified_raw` → lake 双写（T-L1 流程）；批次名 `20261018-P2`（如分批 `-r2`）

## 5. 交付时点与验收

- **今日 24:00 前**：`worklist.csv` + `cells.csv` + `report.md` + 余额/台账截图级记录（数字即可）。
- 下载与入库可延续到次日；每批完成在 collab-log 报一行（批次/条数/L1 数/要素率/哈希）。
- 验收：worklist 去重率 100%、每格有 total/new 记录、台账无重复文号、余额与 ledger 对账一致。

## 6. 注意事项

1. 使用本地客户端：`research/.venv/Scripts/python research/eval/pkulaw_mcp/__main__.py --workstream data call enforcement-doc search_enforcement '<json>' --budget 75`；不要用 ZCode 内置 MCP（旧 Token）。
2. 遇验证码/风控/限额：停下报告，不做绕过。
3. 凭据不入库、不入对话；正文只落数据目录。
4. 本工单只解决"密度"；**不改变 r7 的显式批次清单流程**——新批次仍需协调层登记后并入。
