# 法宝作业台（pkulaw_agent）——面向 agent 的检索 / 下载 / 核对一体化工具

> 目标：把"人工换检索词 → 一页 50 篇下载 → 解析 → 才发现这批没内容"的低效循环，改成
> **agent 自检索 → 无配额预探 → 只取有内容的 → 解析核对 → 自动回写 → 换下一词**。
> 本文是调查结论 + 设计定稿；实施按 §7 里程碑推进。日期：2026-10-16。

---

## 0. 结论先说

**可行，且路线已用本机实测验证**（不涉及任何账号）：

1. 法宝 V6 是 SPA：登录后 `access_token` 落在 `localStorage`，所有检索走**同源 JSON API**
   `POST /searchingapi/adv/list/{库}`（`apy`=行政执法、`pfnl`=司法案例、`chl`=法律法规，三端点已实测存在，
   匿名返回 `401 {"message":"token error"}`）。在页面上下文里 `fetch` 即可自动带上会话与防护 cookie——
   这是**关键技法**，存量项目 ChHsiching/pkulaw 用它跑通了整个司法案例库。
2. 站点有腾讯 **EdgeOne 机器人防护**：headless Chrome 被拦（返回 567"访问安全验证"页）；
   **真窗口 Chrome 1.6 秒正常加载**（首页 1.68MB）。→ 工具必须跑**可见浏览器**；
   **绝不尝试指纹伪装或挑战绕过**（见 §3 红线），真浏览器正常访问本身就是合规操作。
3. 检索条件可程序化：除 `adv/list` 外还有 `POST /searchingapi/adv/cluster/{库}`
   （返回筛选维度与 id 映射，如案由树）。执法库的维度（地域/机关/处罚种类/日期）由一次登录态
   `recon` 捕获后固化，不再靠猜。
4. 因此本工具能做到 MCP 做不到的事：**取正文、预探形态、按需下载、批量核对**。
   MCP（`search_enforcement`，75 分/次，20 条/次不可翻页）退为**交叉核验与兜底**。

## 1. 痛点（为什么要造这个工具）

| # | 现状 | 浪费 |
|---|---|---|
| 1 | 一次导出/下载只能处理一页 50 篇 | 想要 500 件金标 ≈ 10–12 轮人工操作 |
| 2 | 下载前**无法预知**哪篇是叙述式、哪篇只有结果 | 已实测：A 批 50 篇里仅 33% 是独立事件、含金额 98%；B 批事件率 64% 但含金额仅 54% |
| 3 | 解析后才知道内容层级，检索词选错要重来 | "抽头/营利"类要素词预计能把 `amounts.commission`、`intent.profit_purpose` 出现率从 0–2% 拉起来，但人工试错成本高 |
| 4 | 网页端逐条看不可行、MCP 只回目录 | 人工逐条浏览 50 篇要半小时以上 |

## 2. 技术侦察（2026-10-16 实测 + 存量项目）

### 2.1 本机实测事实（匿名，无凭据；脚本留档于 `$JUSTILAW_DATA_DIR/recon/`）

| 事实 | 证据 |
|---|---|
| 匿名 HTTP 直取文档页 → 984 字节空壳，内含 `EO_Bot_Ssid`/`__tst_status` 挑战脚本 | `curl` 保存的 `pkulaw_anon.html` |
| headless Chrome → **被拦**：`访问安全验证 / 567`，EdgeOne 防护页（`static.pkulaw.com/EdgeOne/…`） | `spike_result.json` `runs[0]` |
| 真窗口 Chrome（`channel="chrome"`）→ **正常**：1.6s 加载首页，cookies 含 `pkulaw_v6_sessionid`，无挑战 | `spike_result.json` `runs[1]` |
| `POST /searchingapi/adv/list/apy`、`…/pfnl`、`…/chl` 均存在；匿名 `401 {"code":"1","message":"token error"}` | 同上，页面上下文 fetch |
| 库入口 URL：行政执法 `/penalty?way=topGuid`、司法案例 `/case?way=topGuid`、高级检索 `/advanced/case` | `spike2_result.json` `nav_links` |
| 登录形态：密码 + 微信扫码（`isWechatLogin`、`passwordLoginTimePeriod`、`weixinloginTimePeriod`）；存在图形验证码路径（robots.txt 禁 `/VerificationCode`） | 首页隐藏字段 dump |
| robots.txt 禁抓路径含 `/downloadfile`、`/newlogin`、`/ssologinurl`、`/usercenter`、`/gateway` 等 | `curl robots.txt` |

### 2.2 存量项目情报（GitHub，六项目对照）

| 项目 | 星/更新 | 做法 | 对本工具的价值 |
|---|---|---|---|
| **ChHsiching/pkulaw** | 2★ / 2026-09 | Playwright + `localStorage.access_token` + 页面内 fetch `adv/list/pfnl`；**递归分区**突破分页上限（按年份/案由/参照级别切分，多种排序）；断点续爬；导出 JSON/XLSX/CSV | **主要蓝本**：认证、调用、分区、容错模式全部可直接借鉴 |
| hjhhoni/pkulaw | 54★ / 2025-09 | DrissionPage 接管**本机已登录 Chrome**（9333 端口），GUI，随机 1–10s 等待，含附件下载 | 备选会话方案（人工接管更顺）；"随机等待"节奏设计 |
| NEU-ZHA/legal-ai-skills | 65★ / 2026-10 | agent skills 集：MCP 优先 + **网页兜底**流程（机构登录/详情页核验） | 佐证"MCP 不够、必须补网页层"是社区共识 |
| zhucl123/PKULAWSpider | 9★ / 2025-01 | Selenium 检索 + 裁判文书下载 | 早期做法，已被前述方案超越 |
| Kevinlkc/Pkulaw_scraper | 8★ / 2023-04 | Jupyter，V6.0 学术用途 | 端点命名的历史佐证 |
| Liu8Can/pkulaw-mcp-router | 3★ / 2026-04 | 把 mcp.pkulaw.com 多个 MCP 子服务聚合成一个本地入口（读 swagger） | 证实 MCP 能力边界：**只有检索目录，无正文** |

### 2.3 端点族与调用范式（已证实部分 + 待 recon 固化部分）

已证实（可直接写进代码）：

```text
POST https://www.pkulaw.com/searchingapi/adv/list/{lib}          # lib ∈ {apy, pfnl, chl}
  headers: {"Content-Type": "application/json", "Authorization": <access_token>}
  body: { "orderbyExpression": "...", "pageIndex": 0, "pageSize": 100,
          "fieldNodes": [ {text/select 节点…} ], "clusterFilters": {...}, "groupBy": {...} }
POST https://www.pkulaw.com/searchingapi/adv/cluster/{lib}
  body: { "dimensionId": "CategoryNew" }                          # 返回筛选维度（name↔id）
页面上下文执行：page.evaluate(fetch(...))  # 自动带 cookie + EdgeOne 通行证 + 同源
```

待 recon 捕获后固化（第 3 节的 `recon` 命令一次搞定）：

1. 执法库 `/searchingapi/adv/list/apy` 的**检索字段名与 id**（地域/执法机关/处罚种类/公布日期/发文案号…）——也可用 `cluster/apy` 动态拉维度表；
2. **详情内容路由**：`/apy/<hash>.html` 的正文由哪个 XHR 返回（DOM 直读 vs 详情 API）、网页可见内容与 Word 导出的差异（**预探功能的判定依据**）；
3. **下载按钮的请求**（点"下载"后走什么端点、配额如何提示）——仅在需要 Word 存档时才用；
4. token 生命周期（JWT `exp`）、吊销/刷新行为；
5. 每次请求的合理间隔下限与 EdgeOne 触发阈值（用一个上午用小配额标定）。

## 3. 设计原则与红线

1. **只用官方功能**：检索、浏览、导出、下载都是订阅内正常操作；**不做验证码破解、不做指纹伪装、
   不做挑战绕过、不多账号轮换、不并发轰炸、不绕配额**。被风控拦住就**降速/暂停/通报用户**。
2. **单账号、人类节奏**：默认请求间隔 ≥1.5s + 随机抖动；连续请求上限、每日调用上限、下载配额上限都可配；
   串行执行；出现 `SecurityProtection`/验证码 → 立即停 15–30 分钟并提示人工处理。
3. **零凭据落库**：推荐**手动登录一次**（工具开好窗口，用户在窗口里完成账号密码/微信/验证码），
   登录态靠持久化浏览器 profile 保存（目录在 `$JUSTILAW_DATA_DIR`，**在仓库外**）。
   凭据不写入代码、不进仓库、**不进对话记录**；recon 捕获在登录**之后**才开始，登录流量不入档。
4. **产物边界**：正文/JSONL 只落 `$JUSTILAW_DATA_DIR`；仓库只提交脚本、检索计划、脱敏统计与哈希台账。
5. **可复核**：每个批次留下 `run.json`（检索条件、页数、命中数、各项计数）与 `SHA256SUMS`，
   与现有 `pkulaw_ingest.py` 的批次约定一致。

## 4. 架构与子命令

```text
                    ┌──────────────────────────────────────────────┐
 作业单 plan.json → │              作业调度（harvest）              │
                    └──────┬───────────────┬───────────────┬───────┘
                           ▼               ▼               ▼
                 ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                 │ search 检索   │ │ probe 预探    │ │ fetch 提取    │
                 │ adv/list/{lib}│ │ 无配额判形态  │ │ 详情→spec JSONL│
                 └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
                        ▼                ▼                ▼
                 ┌──────────────────────────────────────────────┐
                 │  session 层：Playwright 真窗口 + 持久 profile  │
                 │  token 生命周期 / 退避熔断 / 人工接管点        │
                 └──────────────────────────────────────────────┘
                        │                                    ▲
                        ▼                                    │
                 ┌──────────────┐                    ┌──────────────┐
                 │ state 层      │                    │ verify 核对   │
                 │ sqlite 台账   │◄───────────────────│ ingest+presence│
                 └──────────────┘                    └──────────────┘
```

子命令（全部 `python research/discretion/collect/pkulaw_agent/__main__.py <cmd>`）：

| 命令 | 作用 | 需要登录 | 配额 |
|---|---|---|---|
| `doctor` | 环境自检（playwright/Chrome/profile/登录态） | 否 | 0 |
| `login` | 打开真窗口，用户手动登录；轮询 `access_token` 成功后固化 profile | — | 0 |
| `recon` | 登录后开始捕获 XHR：写脱敏 `recon.jsonl`（端点/字段/请求体形态） | 是 | 0 |
| `cluster --lib apy --dim X` | 拉筛选维度与 id 映射 → 生成 `filters-apy.json` | 是 | 0 |
| `call --path P --body @f` | 任意 API 直调（agent 探索用，同 `pkulaw_mcp call`） | 是 | 0 |
| `search --plan p.json` | 按作业单执行检索、分页、饱和拆分、去重 → `results.jsonl`（每页请求体原样落 `run.json`，首轮联测据此对齐真实字段） | 是 | 0 |
| `fetch --run <run_dir>` | **零配额**逐条开详情页抓正文（主文本块定位）→ `.txt` + 形态预探（`probe` 内嵌：**直接复用 `pkulaw_ingest.parse_any_doc`，与下游解析同源判定**）；`--ingest` 直接接解析链 | 是 | 0 |
| `download` | 下载文件：`--run`（逐条详情页点下载）/ `--url`（结果页勾选→下载）/ `--ui-search`（库页检索后下载）；**`--manual` 兜底：agent 把页面铺好，人点一下，文件由监听器自动落盘**；`--cap` 强制配额上限 | 是 | **有** |
| `harvest --plan p.json` | 一条命令串完 `search → fetch[→ download]`（多词×多省×多窗串行） | 是 | 视步骤 |

**三步上手**（账号到手后，agent 或人都能跑）：

```bash
# ① 登录一次（之后 profile 免登录）
python research/discretion/collect/pkulaw_agent/__main__.py login
# ② 侦察一次（固化执法库字段映射；之后 search 用 --plan 里的 field_nodes 或简化节点）
python research/discretion/collect/pkulaw_agent/__main__.py recon --tag 20261016
# ③ 干活：检索→抓正文→（要原件再）下载
python research/discretion/collect/pkulaw_agent/__main__.py search  --plan js-2022H1.json
python research/discretion/collect/pkulaw_agent/__main__.py fetch   --run $DATA/inbox/pkulaw/js-2022H1/search/js-2022-抽头 --ingest
python research/discretion/collect/pkulaw_agent/__main__.py download --run <同上> --cap 50 --manual
```

## 5. 数据流与核对闭环

```text
检索计划(词×省×时间窗) → search → results.jsonl（gid/文号/机关/日期/链接 + raw 原样保留）
     → fetch（零配额开详情页抓正文；内嵌预探判形态）→ .txt（叙述式才留文件）
     → pkulaw_ingest.py 解析 → spec JSONL（tier 分流）
     → 核对（key_field_presence 十要素出现率 + 事件折算率 + 与上一批对比；report 复用现有工具）
     → 若要素出现率不升：agent 换检索词/换省/换窗；若饱和：换下一窗口
```

关键收益：**预探用"看"代替"下"**，把下载配额花在刀刃上；预探结论=解析器能抽到什么
（`fetch` 内嵌的 `probe_text` **直接调用 `pkulaw_ingest.parse_any_doc`**，同源判定，不会出现
"预探说有、解析说无"的分叉）。`download` 仅在需要 Word 原件存档时用；若 recon 证明详情页
内容与 Word 导出不一致（存在阉割），下载路线退回批量导出（`--url`/`--ui-search` 勾选页下载）。

## 6. 与现有资产的关系

| 现有资产 | 关系 |
|---|---|
| `collect/pkulaw_ingest.py` | **解析内核**：`parse_doc`/`build_record`/`tier_of`/`event_key` 原样复用；本工具产出的文本直接喂给它 |
| `eval/key_field_presence.py` | **核对层**：report 调用它产出对照表 |
| `worklist.csv` 约定 | 不变；本工具回写时附 `叙述式=是/否（预探）` 与实际下载结果 |
| `eval/pkulaw_mcp/`（预算网关） | **降级为核验工具**：用 `search_enforcement`（75 分/次）对 1–2 个查询抽样对账页内命中数；日常检索不再耗积分 |
| `docs/04-plan/pkulaw-ingest-design.md` | 上游设计（形态/口径/分级）；本工具替代其 §5 中的人工操作循环，口径不变 |
| 浏览器 profile | `$JUSTILAW_DATA_DIR/browser-profile/pkulaw/`（在仓库外，含登录态，**绝不入库**） |

## 7. 里程碑与验收

| 阶段 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| **M0 会话层** | `doctor`/`login`；持久 profile；安全验证页明确报错 | 真窗口打开、手动登录后 `access_token` 落 profile；二次运行免登录 | ✅ 已实现（待账号联测） |
| **M1 侦察** | `recon`/`call`/`cluster`：脱敏捕获 + 回放固化响应 + 任意直调 | 一次人工操作捕获到：检索、详情、下载三类请求；产出 `filters-apy.json` | ✅ 已实现（待账号联测） |
| **M2 检索+预探** | `search`（分页/饱和拆分/去重）+ `fetch` 内嵌预探（同源判定） | 同一查询：`search` 命中数与页面一致；预探与随机 10 篇实下结果一致率 ≥90% | ✅ 代码就绪（待账号联测） |
| **M3 提取+下载** | `fetch`（正文 → .txt → 解析链）+ `download`（逐条/结果页/人工兜底，`--cap` 卡配额） | 一个 50 篇窗口全自动跑通；下载文件自动落盘且不超 `--cap` | ✅ 代码就绪（待账号联测） |
| **M4 作业单** | `harvest`：多词×多省×多窗串行；自适应换词 | 半日无人值守完成一批 ≥500 件候选，回写 worklist | ✅ 代码就绪（待账号联测） |

## 8. 待确认 / 需用户动作

1. **账号**：建议你亲自在 `login` 打开的窗口里登录（不把密码给我、不贴进对话）。
   若确需脚本代填，只放本机环境变量，但仍会被验证码挡住 → **不推荐**。
2. **自动化操作与下载配额以账号实际权限为准**：工具不假设额度——`--cap` 强制本次上限、
   请求间隔 ≥1.5s、异常即停；配额提示以页面显示为唯一事实来源。
3. **速率参数**：默认 1.5–3s/请求、单次运行 ≤300 请求、下载 ≤2 页 50 篇/日，是否放行（保守值，可调）。
4. **司法案例库**：同一作业台同样适用（`--lib pfnl`）；是否也纳入本次三天窗口？
5. **运行时段**：建议在你在场时首次联测（验证码/风控需要人工接管）。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| EdgeOne 风控升级（自动访问也可能弹验证） | 降速/停批/通报；人工在窗口里完成验证后继续；**不绕过** |
| 账号被限或异常提示 | 单账号 + 人类节奏 + 上限闸门；异常即停 |
| 页面改版 / 端点更名 | `recon` 可随时重跑；字段映射集中在 `filters-*.json`，改版只改数据不改代码 |
| 详情页内容与导出 Word 不一致 | recon 第 2 项专项比对 3 篇同源文件；不一致则退回批量导出路线 |
| 令牌过期（JWT） | `login` 二次运行；运行中 401 → 自动读 localStorage 刷新，失败则暂停提示 |

## 10. 变更日志

| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-16 | v0.2 | **补全"检索下载"操作层（用户指出上一版只有基础设施）**：`search`（作业单/分页/饱和拆分/去重，每页请求体原样留档）、`fetch`（零配额抓正文 + 内嵌预探**直接复用 `parse_any_doc`** 同源判定 + `--ingest` 接解析链）、`download`（逐条/结果页/库页三种入口；`--manual` 人工兜底+监听器自动收文件；`--cap` 卡配额）、`harvest`（一条命令串完）；单测 47 项。顺带修解析器真 bug：`DOC_NO_RE` 不允许"沪公长(长新)"式多字机关代号（网页抓取无管道表格，文号全靠它兜底）→ 放宽并防前缀吸附（新增回归测试） | 模型组 |
| 2026-10-16 | v0.1 | 初版：实测侦察（EdgeOne/端点族/入口 URL）、六项目存量对照、架构与子命令、里程碑 M0–M4、红线与待确认清单；代码实现 M0（doctor/login）与 M1（recon/call/cluster） | 模型组 |
