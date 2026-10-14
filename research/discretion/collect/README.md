# 数据采集工具（渠道 D 已全自动 / B 多站已通 / C・E 半自动 / A 搁置）

> 配套：[数据收集计划](../../../docs/04-plan/data-collection.md) · [固定对照与阶段门禁](../../../docs/05-research/sota-baselines-and-gates.md)
>
> 纪律：礼貌抓取（政府站点 ≥1.5s 间隔）；不绕过任何登录/验证码/JS 盾；原始数据在**仓库外数据目录** `D:/02_Dev/Data/justilaw-research/`（环境变量 `JUSTILAW_DATA_DIR` 可覆盖，不入库）；每批采集登记 `manifest.csv`（本目录，入库）。

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `common.py` | 公共库：浏览器头会话（trust_env=False 绕环境代理）、重试、SHA-256、manifest 台账 |
| `fetch_cail.py` | 渠道 D：CAIL2018 本地包 → 赌博子集（A2 协议）——**已完成 4,160 件** |
| `fetch_lecard.py` | 渠道 D：LeCaRDv2 query+label——**已完成**；候选集待手动（Google Drive） |
| `probe_sites.py` | 渠道 B：省/市站点批量探查（首页浅抓，复议语义链接发现） |
| `crawl_reconsider.py` | 渠道 B：复议决定书专栏采集（多站点适配器框架） |
| `filter_gambling.py` | 渠道 B：收割后的赌博案初筛（强/弱关键词 + 上下文摘录） |
| `import_manual.py` | 渠道 C：浏览器手动导出文件统一入台账 |

## 复议专栏适配状态（2026-10-15）

| 站点 | 状态 | 产量 | 赌博案初筛 |
|---|---|---|---|
| 浙江省司法厅「行政复议结果公开」 | ✅ 已全量 | 58 件（PDF，已脱敏） | **0**（信息公开/建设用地类为主） |
| 北京东城区政府「行政复议决定公开」 | ✅ 已全量 | 127 件（2019–2026，HTML 全文） | 强命中 1，另 14 件治安处罚类 |
| 北京门头沟区司法局「行政复议决定公开」 | ✅ 已全量 | 49 件（HTML 全文） | 待细筛（密度同东城） |
| 北京司法局（市政府复议决定 PDF） | 📌 已定位 | tzgg75 送达公告附全文 PDF | 待适配 |
| 朝阳/丰台/海淀/西城/大兴（北京各区） | ⚠️ JS 壳或路径未知 | — | 待逐区适配 |
| 南京司法局「行政复议决定书网上公开」 | ⚠️ 二级壳页 JS 渲染 | — | 待适配 |
| 济南司法局（汉网家族） | ⚠️ webId 未暴露 | — | 待适配 |
| 广州司法局 | ⚠️ 栏目未定位 | — | 搜索引擎已见 PDF 附件 |
| 湖南司法厅 | ⚠️ Python TLS 握手失败（curl 可通） | — | 需降 cipher |
| 上海/广东/安徽/云南/省级司法厅 | ⚠️ 首页 JS 菜单，浅抓无效 | — | 需逐站深探 |

**关键结论（密度数学）**：已收 234 件全量复议决定，赌博案强命中 ≈1 件（<1%）。按此密度，渠道 B 要凑够 300–600 件赌博案需全量收割 **3–6 万件**（约 100+ 站点）。两条路：① 把适配+收割列入每周例行（框架已就绪，新站只需写一个迭代器函数）；② 赌博案密度更高的来源是渠道 C（商用库按法条+关键词检索复议决定，人工导出但精准）。

## 已知坑（给后来人）

- **政府站 WAF 头规则**：东城等站点缺 `Accept-Language` 直接 403；`python-requests` 裸 UA 会被拦。一律走 `common.session()` 的完整浏览器头；WAF 节点规则有轮换，403 时多重试几次常能过（`get_with_retry` 已设 5 次）。
- **环境代理**：开发机若设了系统代理，requests 默认走 127.0.0.1 代理出口会被政府站 403——`session()` 已设 `trust_env=False` 直连。
- **编码**：门头沟等站不返回 charset，requests 按 latin-1 误读 UTF-8——统一用 `decode_html(resp)` 嗅探。
- **翻页文件名各站不同**：东城 `index_{n-1}.html`（从 _0 起）、门头沟 `mtgqbm_yjlist_{n}.shtml`（从 _2 起）、浙江 jpaas 用 `paramJson`。翻页失败按存档末尾处理（`RuntimeError` 消息不含状态码，不能匹配 "404" 字样）。
- **浙江专栏**：列表是 JS 壳，真实数据经 `/api-gateway/jpaas-publish-server/front/page/build/unit` 的 **GET**（POST 报"不支持的HTTP方法"）；页面脚本里的 `count` 不可信（显示 1335 实为 58），以"返回空页"为准。
- **湖南**：对 Python TLS 握手报 SSL 错误（curl 可通），适配需降 cipher 或换 http。
- **CAIL2018**：官方仓库（thunlp/CAIL 及子模块）不含数据，用本地压缩包（`research/data/raw/CAIL2018_ALL_DATA.zip`，哈希见 manifest）；罪名直接存名称（如 `"赌博"`），不需要 accu.txt 映射。
- **深圳 sf.sz.gov.cn**：服务端 ECC 握手与 Python OpenSSL 不兼容（`BAD_ECPOINT`，curl 可通）——用 `session(ciphers=NO_EC_CIPHERS)` 的纯 RSA 套件会话；翻页文件名从 `index_2.html` 起（index_1 不存在）；公告标题全部相同，文件名必须拼 URL 里的 post_id。
- **北京司法局 sfj.beijing.gov.cn**：easysite CMS，翻页是 `ff08cf81-{n}.html`（totalpage=109）；栏目混有法考/采购通知，按标题含"复议/京政复"过滤；页内搜索组件也叫 `id="content"`，正文提取必须匹配 `class="Pub" id="content"`（已固化在 extract_html_text）。
- **信用中国**（渠道 E）：JS 盾（412 + jsluid 挑战），纯 HTTP 无法合规通过，走真实浏览器采集。
