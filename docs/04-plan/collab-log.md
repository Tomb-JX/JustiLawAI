# 协作记录

> 配套：[并行工作流与分工](./workstreams.md)。**只追加，不修改已有行**；每行一条，写在表格末尾。
> 本文件在 `.gitattributes` 中设为 `merge=union`：多条工作流同时追加时，git 自动保留双方的行，不会产生冲突。

| 日期 | 工作流 | 内容 |
|---|---|---|
| 2026-10-15 | 引擎 | 新开 `discretion-engine` 工作树；原工作树留给数据链路。请数据链路完成 §3 的数据目录迁移 |
| 2026-10-15 | 数据链路 | 完成 §3 迁移：research/data/ → `D:/02_Dev/Data/justilaw-research/`（432 文件 / 1.33 GB，前后 SHA-256 逐文件一致，审计存 `_migration_audit_*.json`）；common.py DATA_DIR 改为优先读 `JUSTILAW_DATA_DIR` |
| 2026-10-15 | 数据链路 | 已推 main：4080e41 门头沟适配+赌博初筛、台账 230 件；7d95241 数据目录外置；f77f51b 批量采集规划（crawler-ops.md）与站点台账（sites.csv）。引擎可经 JUSTILAW_DATA_DIR 只读数据目录 |
| 2026-10-15 | 引擎 | **接口发布：要素本体 schema v1.0.0**（`justilaw-api/app/discretion/schema.py`）与[标注指南](../05-research/annotation-guideline.md) v0.1，数据链路可按此准备 50 件试标样本 |
| 2026-10-15 | 引擎 | 共享文件改动：`justilaw-api/requirements.txt` 增加 `pyyaml`（规范库）；`.gitignore` 增加 `research/.venv/`（研究用虚拟环境） |
| 2026-10-15 | 数据链路（采集审计，工作树 `project-data-collection-audit-4bac93`，只写文档） | 已推 main：342d993 新增 [人工采集指南](./manual-collection-guide.md)——赌博案公开文书集中在县级政府网站（公安处罚决定书公示 + 县/区政府复议决定书），百度 `site:gov.cn` 定向检索为主力，信用中国降级。**请数据链路**：① 实现 URL 导入脚本（指南 §4.2）；② 修审计发现的 4 处缺陷——台账 `B-098` 重复 id（`manifest_add` 按行数编号）、浙江 58 件未抽正文（缺 `pypdf`）、初筛把引用法条中的"赌资"计为命中（东城唯一强命中为误报，B 渠道实际赌博案 0）、东城索引 127 / 落盘 124 / 台账 123 不一致 |
| 2026-10-15 | 引擎 | **请数据链路更新数据收集计划 §5**（引擎方案 v0.4、门禁 v0.2 已改）：标注改为"教师银标 + 主动学习 + 人工校正"——① 教师模型（B1）给 CAIL 赌博子集 4,160 件与采集文书全部打银标；② 人工只校正随机抽样（≥100 件，用于估计银标质量，门禁 G2.12）和引擎挑出的最不确定案例；③ 银标只用于训练，测试集只用金标，被打过银标又进入测试集的案例须人工重标（门禁 §7）。教师模型选定前先不动 |
| 2026-10-15 | 引擎 | 协作记录从分工文档 §6 移到本文件并设为 union 合并，以后追加记录不再冲突。另：据上一行，存在第三条工作流"采集审计"（工作树 `project-data-collection-audit-4bac93`），请其在分工文档 §1 登记 |
| 2026-10-15 | 引擎 | **请数据链路修复 bug**：`research/discretion/collect/fetch_cail.py` 第 141 行 `fout.write(line)` 前已 `strip()`，写出的 `cail/gambling/*.jsonl` 记录之间没有换行（`wc -l` 为 0），不是合法 JSONL。改为 `fout.write(line + "\n")` 并重跑、更新台账哈希。引擎侧读取已兼容两种格式，不阻塞 |
| 2026-10-15 | 发现层 | **登记新工作流"发现层"**（即上文的"采集审计"工作树 `project-data-collection-audit-4bac93`，已写入分工文档 §1/§2，负责 `research/discretion/discover/**`）。新增[发现层设计](./search-discovery-design.md)：百度 robots 禁止抓结果页，改用千帆"百度搜索"官方 API，用饱和拆分换覆盖面，交付 `urls.tsv` 与 `columns.csv`（设计 §6）。**请数据链路关注**：浙江县级站点与浙江司法厅同为 jpaas 平台（武义 `webId=3558`），建议把 `iter_zhejiang` 泛化为 `iter_jpaas(webId, tplSetId, pageId)`；广东 gkmlpt 平台 `/gkmlpt/api/all/0?page=N&sid=` 直接返回 JSON，建议新增 `iter_gkmlpt` |
| 2026-10-15 | 数据链路 | 适配窗口 1：北京市司法局（103 份决定全文 PDF + 194 份公告）与深圳复议平台（400 件公告，BAD_ECPOINT 走非 EC 套件会话）已通并全量收割；manifest 加固为按 URL 去重、字段清洗换行；台账重建后五站 866 件（含 103 份全文 PDF）。广州/南京/济南仍待适配。涉及提交 40cf582 起 |
| 2026-10-15 | 数据链路 | 已修复 fetch_cail.py JSONL 缺换行 bug（fout.write(line + "\n")），四个 split 重建并逐行校验合法（2468/293/558/841），gambling 目录附 SHA256SUMS。接受发现层两项建议：iter_jpaas(webId, tplSetId, pageId) 泛化与 iter_gkmlpt（广东）列入下一适配窗口；银标+主动学习标注变更已知悉，教师模型（B1）选定后执行 |
| 2026-10-15 | 数据链路 | 学院有北大法宝账号，渠道 C 升为主力：使用手册入库（docs/04-plan/pkulaw-playbook.md，检索式 R1–R5 + 导出 SOP）。分工边界：发现层探针管公开源 URL 发现；北大法宝只做官方检索/批量导出（不写抓取脚本、不绕限额），导出经 import_manual.py 入台账（channel=C）。若学校采购含法宝 API 额度请知会 |
