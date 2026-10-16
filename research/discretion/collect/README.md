# 数据采集工具（渠道 B 已归档 / D 已完成 / C 入库脚本就绪 / A 搁置）

> 配套：[数据收集计划](../../../docs/04-plan/data-collection.md)（v0.4 起为本目录的职责依据）· [固定对照与阶段门禁](../../../docs/05-research/sota-baselines-and-gates.md)
>
> 纪律：礼貌抓取（政府站点 ≥1.5s 间隔）；不绕过任何登录/验证码/JS 盾；原始数据在**仓库外数据目录** `D:/02_Dev/Data/justilaw-research/`（环境变量 `JUSTILAW_DATA_DIR` 可覆盖，不入库）；每批采集登记 `manifest.csv`（本目录，入库）。
>
> **2026-10-16 状态**：公开网页的发现与收割已由发现层接管（`../discover/`、`../harvest/`，周交付 `urls_new.tsv`）；本目录保留渠道 B 归档台账、D 渠道成果与渠道 C/采购入库脚本。

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `common.py` | 公共库：浏览器头会话（trust_env=False 绕环境代理）、重试、SHA-256、manifest 台账（id 按"已有最大序号+1"分配） |
| `fetch_cail.py` | 渠道 D：CAIL2018 本地包 → 赌博子集（A2 协议）——**已完成 4,160 件** |
| `fetch_lecard.py` | 渠道 D：LeCaRDv2 query+label——**已完成**；候选集待手动（Google Drive） |
| `crawl_reconsider.py` | 渠道 B【归档】：复议决定书专栏采集（多站点适配器框架，留作回采参考） |
| `filter_gambling.py` | 渠道 B 初筛【归档】：管辖条款与"第×条"条文语境双降噪，825 件终验 0 强命中 |
| `import_manual.py` | 渠道 C：浏览器手动导出文件统一入台账 |
| `ingest_wenshu.py` | 渠道 C′：裁判文书第三方采购到货入库（替代主键、省份自案号推导、当事人列丢弃）——待到货 |

## 渠道 B 终验状态（2026-10-16 归档）

| 站点 | 产量（台账） | 赌博案初筛（终版规则） |
|---|---|---|
| 浙江省司法厅「行政复议结果公开」 | 58 件（PDF；正文 2026-10-16 补抽，58/58 非扫描件） | **0** |
| 北京东城区政府「行政复议决定公开」 | 124 件（对账：索引 127 / 落盘 124 / 台账 124，3 件当时未下载；盘上多出的 1 份已补录 B-867） | **0**（此前"强命中 1"是《治安处罚法》第十一条收缴条款引文误报，第十四条同） |
| 北京门头沟区司法局 | 49 件 | **0** |
| 北京司法局「通知公告」 | 103 份决定全文 PDF + 194 份公告 | **0** |
| 深圳行政复议平台「公告送达」 | 400 件公告 | **0**（送达公告非决定书全文） |
| **合计** | **台账 869 行（B 867 + D 2）** | **强命中 0** |

**终验结论**：复议专栏赌博案密度实测为零（非"低"）。渠道 B 归档，不再适配新站；`crawl_reconsider.py` 的迭代器写法与下方"已知坑"在需要回采时仍可复用。台账曾有两处账实不符已修复：`B-098` 重复 id 重排为 `B-867`（根因：`manifest_add` 曾按行数计数分配序号，删行重建后冲突，已改为 max+1）；东城 1 份已落盘未登记行补录。

## 已知坑（给后来人）

- **政府站 WAF 头规则**：东城等站点缺 `Accept-Language` 直接 403；`python-requests` 裸 UA 会被拦。一律走 `common.session()` 的完整浏览器头；WAF 节点规则有轮换，403 时多重试几次常能过（`get_with_retry` 已设 5 次）。
- **环境代理**：开发机若设了系统代理，requests 默认走 127.0.0.1 代理出口会被政府站 403——`session()` 已设 `trust_env=False` 直连。
- **编码**：门头沟等站不返回 charset，requests 按 latin-1 误读 UTF-8——统一用 `decode_html(resp)` 嗅探。
- **翻页文件名各站不同**：东城 `index_{n-1}.html`（从 _0 起）、门头沟 `mtgqbm_yjlist_{n}.shtml`（从 _2 起）、浙江 jpaas 用 `paramJson`。翻页失败按存档末尾处理（`RuntimeError` 消息不含状态码，不能匹配 "404" 字样）。
- **浙江专栏**：列表是 JS 壳，真实数据经 `/api-gateway/jpaas-publish-server/front/page/build/unit` 的 **GET**（POST 报"不支持的HTTP方法"）；页面脚本里的 `count` 不可信（显示 1335 实为 58），以"返回空页"为准。
- **湖南**：对 Python TLS 握手报 SSL 错误（curl 可通），适配需降 cipher 或换 http。
- **CAIL2018**：官方仓库（thunlp/CAIL 及子模块）不含数据，用本地压缩包（外置目录 `raw/CAIL2018_ALL_DATA.zip`，哈希见 manifest）；罪名直接存名称（如 `"赌博"`），不需要 accu.txt 映射。
- **深圳 sf.sz.gov.cn**：服务端 ECC 握手与 Python OpenSSL 不兼容（`BAD_ECPOINT`，curl 可通）——用 `session(ciphers=NO_EC_CIPHERS)` 的纯 RSA 套件会话；翻页文件名从 `index_2.html` 起（index_1 不存在）；公告标题全部相同，文件名必须拼 URL 里的 post_id。
- **北京司法局 sfj.beijing.gov.cn**：easysite CMS，翻页是 `ff08cf81-{n}.html`（totalpage=109）；栏目混有法考/采购通知，按标题含"复议/京政复"过滤；页内搜索组件也叫 `id="content"`，正文提取必须匹配 `class="Pub" id="content"`（已固化在 extract_html_text）。
- **信用中国**（渠道 E）：JS 盾（412 + jsluid 挑战），纯 HTTP 无法合规通过，走真实浏览器采集。
- **初筛降噪**：行政文书里"赌博"字样两大误报源——①管辖条款"卖淫、嫖娼、赌博、毒品"（《公安机关办理行政案件程序规定》第十条，任何治安案可引用）；②条文引用语境（如第十一条"赌具、赌资……应当收缴"、第七十条原文）。`filter_gambling.py` 已内置双规则；引擎 `triage.py` 是同思路的更强实现。
