# 数据采集工具（渠道 D 已全自动 / B 已全自动 / C 半自动 / E 半自动 / A 搁置）

> 配套：[数据收集计划](../../../docs/04-plan/data-collection.md) · [固定对照与阶段门禁](../../../docs/05-research/sota-baselines-and-gates.md)
>
> 纪律：礼貌抓取（政府站点 ≥2s 间隔）；不绕过任何登录/验证码/JS 盾；原始数据只在 `research/data/`（不入库）；每批采集登记 `manifest.csv`（本目录，入库）。

## 脚本一览

| 脚本 | 渠道 | 说明 |
|---|---|---|
| `common.py` | — | 公共库：路径约定、重试 HTTP、SHA-256、manifest 台账 |
| `fetch_cail.py` | D | 从本地 CAIL2018 压缩包抽取赌博子集（A2 协议）——**已完成，4,160 件** |
| `fetch_lecard.py` | D | LeCaRDv2 query+label 自动下载——**已完成**；候选集需手动（Google Drive） |
| `crawl_reconsider.py` | B | 复议决定书公开专栏采集（已适配：浙江司法厅）——**实测通过** |
| `import_manual.py` | C | 浏览器手动导出的 docx/html/pdf/csv 统一导入台账 |
| `manifest.csv` | — | 数据来源台账（入库；只记来源与哈希，不含正文） |

## 各渠道自动化现状（2026-10-15 实测）

| 渠道 | 状态 | 结论 |
|---|---|---|
| **D 公开数据集** | ✅ 全自动 | CAIL2018 赌博子集 4,160 件（train 2,468 / valid 293 / test 558 / final_test 841）；LeCaRDv2 800 查询 + 160 测试 + 标注就位。候选集 5.5 万件仅发布在 Google Drive，P4 前手动获取 |
| **B 复议决定书** | ✅ 管线全自动（浙江已通，产量待扩） | 浙江司法厅「行政复议结果公开」专栏：汉网 jpaas 接口，58 条已脱敏 PDF 已全量采集；**正文筛查 0 件赌博案**（该专栏以信息公开/建设用地类为主）。管线（适配器+翻页+下载+台账+正文抽取）可直接复用到其他省市站点，赌博案产量取决于多省适配 |
| **C 诉讼文书** | ⚠️ 半自动 | 裁判文书网需登录+验证码、商用库需校内账号——**不做自动抓取**；浏览器人工导出后用 `import_manual.py` 入台账 |
| **E 公开公示** | ⚠️ 半自动 | 信用中国有 JS 盾（412 + jsluid 挑战），纯 HTTP 无法合规通过；建议真实浏览器采集或人工。浙江政务服务网「行政处罚结果公开」是备选（未试） |
| **A 公安合作** | ⏸ 搁置 | 按计划由指导老师对接，自动化不适用 |

## 已知坑（给后来人）

- 浙江专栏列表是 JS 壳，真实数据经 `/api-gateway/jpaas-publish-server/front/page/build/unit` 的 **GET**（POST 会报"不支持的HTTP方法"）；翻页要传 `paramJson={"pageNo":n,"pageSize":15,"search":""}`，直接传 `pageNo` 参数无效。页面脚本里的 `count`（曾显示 1335）不可信，实际以"返回空页"为准（该专栏实测只有 58 条）。
- 湖南司法厅 sft.hunan.gov.cn 对 Python TLS 握手报 SSL 错误（curl 可通），适配时需要降 cipher 或走系统证书，暂列未通。
- 广东司法厅 HTTP 500、安徽司法厅首页无静态链接（SPA）、云南司法厅只有指南栏目没有决定书公开——均有待进一步人工调研。
- CAIL2018 官方仓库（thunlp/CAIL 及子模块）不含数据，实际数据靠本地压缩包（`research/data/raw/CAIL2018_ALL_DATA.zip`，哈希见 manifest）；罪名在数据里直接存名称（如 `"赌博"`），不需要 meta/accu.txt 映射。
