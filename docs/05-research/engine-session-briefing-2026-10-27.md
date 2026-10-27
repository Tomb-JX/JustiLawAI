# 引擎算法会话开工包（2026-10-27，宏观指引会话代负责人整理）

> **使命**：按总工单 `m4-full-route-20261027`（看板 `ho-20261027134432-127ff9`）攻克 M4 裁量引擎算法——七工作包中你接手 WP1（评估地基）、WP3②–⑤（法律知识接入）、WP4（表示学习对照）、WP5（分布输出）、WP6（类案 M5）及 WP0 余量。执行权威＝执行计划；诊断权威＝ml-review；门槛权威＝gates v0.7。三者冲突时以门槛文件为准，且 §3 不降级约束 8 条不可违反。

## 0. 开工即须知（2026-10-27 当日已发生的事）

1. **WP0 已收官**（13:56 看板 evt-…135631）：P9 叙述式全量产出 1,532/1,664=92.1%，质量口径 94.4%，**净入库 1,156 条**（train 992/418 事件 + valid 164/100 事件），~¥14.7。余量：132 条 stage4（tb1500 充值后一轮，~¥1.3）、58 条质量排除复核、公示 643 条路由、校验器 patch 合入 main。
2. **两省基准已核验**（WP3①）：河北/江苏 YAML `verification=已核验`（三方逐字 27/27、32/32 句）；**双法纪元**——治安法 2025 修订第 82 条 2026-01-01 施行（罚款上限 1000/1000–5000），≥2026 决定的档位映射须旗标"待定"。
3. **B-Hist v1 已出**（WP2，宏观会话）：同事件跨人噪声地板≈0（772 对）→ **不触发门槛修订**；跨事件离散（天数 2–3、罚款 ±20% 仅 25–43%）= 你要解释的信号；罚款胜负手＝锚点/档位分类。
4. **方案 C §3.2 删失 EM 已验证**（引擎线 10-27 晨）：机制成立（top2 42%→56%、熵 1.45→1.11、覆盖 86%）、精度受供给饿限制；226 条赌资后验在 `stake_posteriors.jsonl`。
5. **现行训练基座**：`m4-facts-silver-1740-v3-clean`（train 1,682/1,294 事件）；P9 的 1,156 条**待并入**下一版训练包（并入时须跑事件级查重＋分层评测协议）。

## 1. 阅读清单（按优先级；路径相对仓库根，@wt = 只在 discretion-engine 工作树、未合入 main）

### 第 0 层·开工必读（约 40 分钟，读不完不开工）

| # | 文档 | 读什么 |
|---|---|---|
| 1 | `docs/05-research/2026-10-27-m4-route-full-execution-plan.md`（v1.2） | 七工作包定义、每 WP 预注册判据、§3 不降级 8 条、§4 两省核验记录、排程与关键路径 |
| 2 | `docs/05-research/2026-10-27-discretion-engine-ml-review.md` | 为什么这么走：实现偏离设计的逐模块对照、评估三重乐观、批次轴不可部署、§7 六步依据 |
| 3 | 看板 `D:\02_Dev\Data\justilaw-research\coordination\CURRENT.md` ＋ 你的总工单（handoff `ho-20261027134432-127ff9`）与最近 5 条 engine 事件 | 当前循环状态、待 ack 交接、未关闭阻塞 |

### 第 1 层·数据与现状（约 50 分钟）

| # | 文档 | 读什么 |
|---|---|---|
| 4 | `docs/05-research/engine-line-status-2026-10-26.md`（v1.9） | 现状权威：§2.5 基座链（1740-v2→v3-clean→P9 待并入）、§5.1 三方对照表＋五条读法警示、§7 指针 |
| 5 | `docs/05-research/m4-forensic-diagnosis-2026-10-26.md`（v1.1） | 数据结构三问题（队列先验漂移/污染与特殊机制/目标编码错位）＋E8 碰撞定案 |
| 6 | `docs/05-research/b-hist-ceiling-2026-10-27.md` | 噪声地板结论与 L2 口径；G3.5/G3.6 判"临界"的依据；WP3② 后补 L2′ |
| 7 | `docs/04-plan/data-pipeline-status.md`（v2.3） | 湖 14,257/19 批底账、L5 六批银标、密度定论（§7）、阻塞清单（§8） |

### 第 2 层·方法与证据链（按需精读）

| # | 文档 | 读什么 |
|---|---|---|
| 8 | `docs/05-research/sota-baselines-and-gates.md`（v0.7 冻结） | 全部数值门槛原文＋D-004 零预算口径（经核验结果标签/B-Hist/MCP 查证留痕）；红线 R1–R8 |
| 9 | `docs/05-research/outcome-constraint-calibration-2026-10-26.md` | 方案 C 校准：tier3 硬可用/tier1-2 软先验、实践偏离 ~36%＝偏差头目标；前提已解除 |
| 10 | `docs/05-research/p9-narrative-final-20261027.md` @wt | WP0 收官全数字：分层质量、防泄漏排除语义、残余排除家族（你要复核的 58 条清单在 §3） |
| 11 | `docs/05-research/stake-censored-em-2026-10-27.md` @wt | 删失似然设计与 V1–V4 消融；226 条后验的字段口径（WP3④ 专家 A 直接复用） |
| 12 | `docs/05-research/external-model-comparison-2026-10-26.md`（v1.4） | 外部同类带（CAIL 42–46%/SMS/GLARE/实务系统）＋§8 稀疏要素技术 A–G |
| 13 | `docs/05-research/p9-canary-2026-10-27.md` @wt | 两族校验器假阳性修复过程（stage4 前置知识） |

### 第 3 层·设计与规范（对照用，选读）

| # | 文档 | 读什么 |
|---|---|---|
| 14 | `docs/02-design/gambling-discretion-engine.md` | 目标形态：Ω＋基准档位＋档内分布＋偏离预警；M0–M6 分工（ml-review §1 的"设计"列出自它） |
| 15 | `justilaw-api/app/discretion/norms/`（national/interpretations.yaml＋provinces/130000、320000.yaml） | 法定空间与两省档位（`verification=已核验`）；WP3② 的输入 |
| 16 | `docs/04-plan/collab-log.md` 近 3 日 | 各线动作脉络（10-26 起 macro 会话条目串起诊断→门禁修订→法医→方案 C→计划） |

## 2. 数据与产物路径速查（$DATA = `D:\02_Dev\Data\justilaw-research`）

| 用途 | 路径 |
|---|---|
| 现行训练基座 | `$DATA/engine/training/m4-facts-silver-1740-v3-clean-20261026/`（train 1,682；fields: id/event_id/input.facts_text/target.{type,detention_days,fine}/metadata.{cohort,source_batch,mechanism}） |
| P9 净入库（待并入） | `$DATA/s1_runs/p9-narrative-full-20261027/merged-outputs.jsonl`（1,532 产出）；accepted 清单 @wt `research/data/p9-narrative-final-s3-20261027` |
| 冠军栈对照产物 | `$DATA/engine/development/{expert-a-group-axes-clean, tier-batch-combined, batch-pooling-lobo}-20261026/report.json` |
| B-Hist | `$DATA/engine/development/b-hist-ceiling-20261027/`（脚本已入库 `research/eval/b_hist_ceiling.py`） |
| 方案 C | `$DATA/engine/development/outcome-constraint-calib-20261026/`（weak_stake_intervals.jsonl 226 条）；删失 EM 后验 `$DATA/engine/development/stake-censored-em-20261027/stake_posteriors.jsonl`（226 条，tier3 高置信 71） |
| 数据湖 | `$DATA/lake/catalog/lake.db`（14,257 records/12,031 docs/19 批；表 records/documents；region_code 在 documents） |
| 看板/事件 | `$DATA/coordination/`（events.jsonl append-only；coord_event.py 登记命令族） |

## 3. 纪律红线（摘自执行计划 §3，违者须先走 D-00X 偏离）

数值门槛 G3.2–G3.8/R1–R8 不动；T-admin ≥300 按事件；MCP 核验留痕不可省；对外只认 LOBO/未见机关口径（混池进附录）；RoBERTa/Lawformer 对照不可跳过；模型选择一律事件×机关分组 CV；**test40 封存不碰**；判据预注册、正负结果都留痕。另：看板禁发无口径标签的单值指标（`m4-stratified-eval-20261026` 工单延续）；付费调用走 B-12 对账。

## 4. 当前挂账（与你相关的）

tb1500 余额充值（stage4 132 条 ~¥1.3）｜58 条 P9 质量排除复核（@wt 报告 §3）｜公示 643 条路由裁定（后处理线已裁 592 并入 Claude 队列，看板确认）｜校验器 patch 合入 main｜Word 下载权限（机构）未生效｜D-004 指导老师/周会补确认。

## 5. 建议第一步

WP1 评估地基（零成本、解锁一切对照）：先写总体定义（河北＋江苏×机关×年份分层框），再把 P9 1,156 并入 v3-clean 出 v4 训练包（事件级查重＋净化闸同口径），然后分层抽 T-admin ≥300 事件封存、搭事件×机关分组 CV harness——判据全部在执行计划 §1 WP1。WP3② 可并行开工（YAML 已核验，特征编码与 82 条双纪元旗标）。

## 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-27 | v1 | 初版：新引擎算法会话开工包（阅读清单 16 项分层、路径速查、红线、挂账、建议第一步）；配套刷新 engine-line-status v1.9 / data-pipeline-status v2.3 / 执行计划 v1.2 | 宏观指引会话（负责人指示） |
