# pkulaw_agent — 法宝作业台 CLI 说明书

面向 agent 与人的北大法宝操作工具：**登录一次 → 自己检索 → 零配额抓正文 → 按需下载原件 → 接既有解析链**。
取代"人工换检索词、一页 50 篇盲下、下完才发现没内容"的循环。设计与实测依据见
[`docs/04-plan/pkulaw-agent-design.md`](../../../../docs/04-plan/pkulaw-agent-design.md)。

> **红线（详见设计 §3）**：只用官方检索/浏览/导出功能；不绕验证码与风控；单账号、人类节奏
> （默认 ≥1.5s/请求）；下载消耗配额，必须 `--cap`；账号密码与 profile **不进仓库、不进对话**；
> 一切正文产物只落 `$JUSTILAW_DATA_DIR`（默认 `D:/02_Dev/Data/justilaw-research`，仓库外）。

## 0. 安装与前置

```bash
python -m pip install playwright        # 首次一次即可（引擎自带的 Chrome/Edge 直接复用，无需 playwright install）
python research/discretion/collect/pkulaw_agent/__main__.py doctor   # 自检
```

- 浏览器：本机已安装的 Chrome 或 Edge（`--browser chrome|msedge`）。
- 运行位置：以下示例均在**仓库根目录**执行。
- 为什么要**真窗口**：headless 会被站点防护直接拦掉（实测返回"567 访问安全验证"），
  真窗口的正常访问才是合规姿势——工具**不做指纹伪装、不做挑战绕过**。

## 1. 命令总览（12 个）

| 命令 | 一句话 | 联网 | 下载配额 | 需要登录 |
|---|---|---|---|---|
| `doctor` | 环境自检（含 profile 锁 / session.json / CDP 探测） | 否 | 0 | 否 |
| `serve` | **长驻窗口**：一个浏览器跑完所有命令（CDP 接管，不闪断） | 否 | 0 | — |
| `login` | 稳定登录：**登录成功前窗口不会关闭**，成功后写 `session.json` | 是 | 0 | — |
| `recon` | 捕获一次真实操作（检索/详情/下载）的请求，固化字段 | 是 | 0 | 是 |
| `cluster` | 拉筛选维度与 id 映射（如"江苏省"对应什么值） | 是 | 0 | 是 |
| `call` | 任意 API 直调（探索/对账用） | 是 | 0 | 是 |
| `search` | 按作业单检索：分页、饱和拆分、去重 → `results.jsonl` | 是 | 0 | 是 |
| `fetch` | 逐条开详情页抓正文 → `.txt` + 形态预探（可直连解析链） | 是 | **0** | 是 |
| `download` | 下载文件：逐条 / 结果页勾选 / 库页检索；可人工兜底 | 是 | **有** | 是 |
| `jobs` | **作业单**：MCP 缓存（含原文链接，0 积分）/ 清洗清单 → `jobs.jsonl` | 否 | 0 | 否 |
| `run` | **作业流水线**：打开→抓正文→**六项校验**→（通过才）限额下载→断点/报告 | 是 | **有** | 是 |
| `harvest` | 一条命令串完 `search→fetch[→download]` | 是 | 视步骤 | 是 |

通用参数：`--data-dir`（覆盖数据目录）、`--browser`、`--timeout`。
退出码：`0` 成功；`2` 未登录/登录过期；`3` 撞上安全验证页（需人工在窗口完成验证后重跑）；`130` 手动中断（进度已落盘，可续）。

## 2. 命令详解

### doctor — 环境自检
不联网、不开窗口。检查 Python / playwright / Chrome / Edge / 数据目录可写 / profile 与锁文件 /
`session.json` / CDP 端口（serve 是否在跑）。第一次拿到机器或换机器先跑它。

### serve — 长驻窗口（v1.1）
```bash
... __main__.py serve [--port 9222] [--entry apy]
```
启动一个长驻 Chrome（同一 profile + CDP 调试端口），本进程运行 = 窗口保持。
其它命令启动时会**先探测 CDP**：在 → 直接接管该窗口（不开新窗、不改变你看的页面）；
不在 → 照常临时自启。批量作业建议全程 serve：**一个窗口跑完所有命令，不再有开/关闪断**。
Ctrl+C 结束本进程不影响浏览器（窗口继续开着，可手动使用或关闭）。

### login — 稳定登录（v1.1 重写）
```bash
... __main__.py login [--timeout 0] [--hold] [--grace 4]
```
登录态读页面**隐藏域 `#AccessToken`**（localStorage 可能为空，两处都读）；API 调用带
`Authorization: Bearer <token>`。语义：
- **登录成功前窗口不会关闭**（每 3 秒自动检测；任何校验异常都**不关窗**，只打印状态）；
- 成功判据 = 读到 token **且**一次真校验（`verify_login`，1 次检索 0 配额）；
- 成功后写 `session.json`（仓库外：时间/到期/机构线索），打印账号线索与到期时间；
- `--hold`：成功后保持窗口（交互终端默认保持，回车关；非交互默认 4 秒后自动关）；
- `--timeout 0`（默认）不设上限——慢慢登录；撞上安全验证页时按页面提示人工完成，工具等待不绕过。

### recon — 一次人工操作，固化全部字段
```bash
... __main__.py recon [--tag 20261016] [--seconds 0] [--no-replay]
```
确保登录后开始**脱敏记录**（登录/鉴权/静态资源路径不记录；敏感键值打码；响应只留字段名）。
然后在窗口里按提示做三件事：① 做一次带筛选（地域/机关/日期）的检索；② 打开一篇有正文的详情页；
③（可选）点一次下载。回车结束后，工具**自动回放**捕获到的检索请求，拿到完整响应字段
（网络事件里读响应体有竞态，回放是确定性做法）。

产物：`$DATA/recon/recon-<tag>.jsonl`（端点/请求体/状态/字段名）、`summary-<tag>.json`、`replay-<tag>.json`。
**这是唯一一次需要"人带着做"的侦察**；拿到产物后，`search` 的字段名即可对齐（改作业单，不改代码）。

### cluster — 拉筛选维度
```bash
... __main__.py cluster --lib apy [--dim CategoryNew]
```
把筛选字典（名称↔id）落盘 `$DATA/recon/filters-apy-<dim>.json`。用于确认"江苏省""罚款"等筛选值
在请求体里怎么写；也是 recon 之外的兜底手段。

### call — 任意 API 直调
```bash
... __main__.py call --path /searchingapi/adv/list/apy --body '{"pageIndex":0,"pageSize":5}' [--save out.json]
```
`--body` 支持 `@文件`。用于探索端点、抽查数据、和页面计数对账。agent 交互式排障主要靠它。

### search — 自己检索
```bash
# 作业单方式（推荐，可同时排多词×多省×多窗）
... __main__.py search --plan research/discretion/collect/pkulaw_agent/plans/example-js-2022.json
# 单任务方式
... __main__.py search --lib apy --term 抽头 --region 江苏省 --window 2022-01-01:2022-12-31
# 打印作业单模板
... __main__.py search --template
```
做什么：组请求体（作业单里给了 `field_nodes` 就原样用，否则用"关键词+地域"简化节点）→ 分页
（`page_size` 默认 50、`max_pages` 默认 40）→ 命中超过单任务上限时按 `split.values`（如年份）
拆分续跑 → 按 gid/链接/文号去重。每页请求体原样写进 `run.json`（首轮联测据此对齐真实字段）。
常用参数：`--limit`（本次最多收多少条）、`--run-id`（只跑作业单里的某一个）、`--dump-body`（打印请求体）。
产物：`<out>/<run_id>/results.jsonl` + `run.json`（条件/命中总数/页记录）。

### fetch — 零配额抓正文（核心省钱点）
```bash
... __main__.py fetch --run $DATA/inbox/pkulaw/js-2022/search/js2022-现场查获赌资 [--ingest] [--only-narrative] [--limit 50]
```
做什么：逐条打开详情页 → 等渲染 → 用"文本多、链接少的最大块"定位正文 → 落 `.txt`；
同时做**形态预探**：直接调用既有解析器 `pkulaw_ingest.parse_any_doc`（**同源判定**，
不会出现"预探说有、解析说无"），产出 `narrative`（有事实段）/ `table`（只有结果字段）/ `other`。
**查看详情不消耗下载配额**——这就是"先看后下"的关键。
产物：`<run>/fetch/docs/*.txt`、`extract.jsonl`（逐条：形态/是否叙述式/含金额/文号/引证码/正文长度/错误）、
`fetch.json`。每 20 条中途落盘，可断点续跑。`--ingest` 会继续走 `pkulaw_ingest docs` 解析 →
规格 JSONL（按 tier 分流到 admin_cases / admin_outcomes_only / …）。

### download — 下载文件（配额操作，谨慎）
```bash
# A. 对检索结果逐条开详情页下载（同你手工的 Word 流）
... __main__.py download --run <run_dir> --cap 50 [--manual]
# B. 对已有结果页勾选→批量下载（可翻页）
... __main__.py download --url <结果页URL> --pages 3 --cap 50 [--manual]
# C. 先在本机库页检索再下载
... __main__.py download --ui-search --term 抽头 --pages 2 --cap 50 [--manual]
```
机制：`context` 级下载监听器 —— 文件一落地就改名保存到输出目录（重名自动 `-1/-2`），
并记 `downloaded.jsonl`（逐条成败）与 `downloads.json`（文件清单）。
自动化找不到按钮时会**打印页面上所有"下载/导出"类候选按钮**（不瞎试），此时加 `--manual`：
你点一下"下载"（或从弹出的格式菜单里点 Word），文件自动被收进目录。
`--cap` 是配额红线（默认 50），到达即停；之前下过的会自动跳过（按 `downloaded.jsonl`）。

### harvest — 一条命令串跑
```bash
... __main__.py harvest --plan <plan.json> [--steps search,fetch] [--manual-download]
```
按作业单展开所有检索单元串行执行；`--steps` 里含 `download` 才动配额（每 run 上限取
`plan.download.per_run`）。适合挂机跑一批：例如半日无人值守跑完"多词×多省×多窗"。

### jobs — 作业单（v1.1）
```bash
# A. MCP 缓存 → 作业单（0 积分；行内自带原文链接，直达详情页）
... __main__.py jobs from-mcp \
    --cache $JUSTILAW_DATA_DIR/engine/pkulaw_mcp/cache/pkulaw-enforcement-doc_mcp \
    --year 2026 --law 新法 --out jobs/2026T-82.jsonl
# B. 清洗候选清单（含「原文链接」列）→ 作业单
... __main__.py jobs from-csv --csv "$JUSTILAW_DATA_DIR/inbox/pkulaw/2026T/worklist-清洗版-2026.csv" \
    --out jobs/2026T-165.jsonl
```
产物 `jobs.jsonl`（doc_no/url/机关/日期/依据法条/law=新法标记）+ `jobs.meta.json`（计数、
过滤条件、输入哈希）。无链接的条目会被剔除（无法执行）。

### run — 作业流水线（v1.1 核心）
```bash
... __main__.py run --jobs jobs/2026T-82.jsonl --window 2026 [--dry-run] [--cap 30]
```
逐件：打开链接（零配额）→ 抓正文落 `fetch/docs/*.txt` → **六项原文校验**：
`doc_no`（页面文号==作业文号）/ `gambling`（赌博要素词、非烟草）/ `year`（处罚日期或正文
年份在窗内，排除"2025修订"字样）/ `narrative`（叙述式且事实段 ≥ `--min-facts`）/ `masked`
（无 xx/＊/□ 式打码）/ `dedupe`（文号与正文哈希不与台账、本批重复）。
**六项全过才点下载**（`--cap` 强制上限；文件落盘后做完整性检查），未过件分类留档。
逐件状态写 `run.jsonl`（追加即刷盘）：`--resume`（默认开）跳过已完成，`--force` 全重做；
撞上安全验证页整批停（红线），人工处理后 `--resume` 续跑。产物：`run_report.md`（计数 +
失败原因分布 + 逐件表）、`run.json`、`downloads/`（通过件原件）。下载目录可直接接
`import_manual.py --channel P` → `pkulaw_ingest` → `parsed1` → L2 构建。

## 3. 产物目录布局

```text
$JUSTILAW_DATA_DIR/                       # 默认 D:/02_Dev/Data/justilaw-research（仓库外）
├── browser-profile/pkulaw/               # 登录态（含 cookie，绝不入库）
├── recon/
│   ├── recon-<tag>.jsonl                 # 侦察捕获（脱敏）
│   ├── summary-<tag>.json / replay-<tag>.json
│   └── filters-<lib>-<dim>.json          # 筛选维度字典
└── inbox/pkulaw/<batch>/
    ├── search/<run_id>/results.jsonl     # 检索结果
    │                  └── run.json
    ├── search/<run_id>/fetch/docs/*.txt  # 抓下来的正文
    │                  ├── extract.jsonl  # 逐条预探结论
    │                  └── fetch.json
    ├── search/<run_id>/ingest/           # --ingest 后的规格 JSONL（tier 分流）
    └── downloads/                        # download 收到的文件（.doc/.zip…）
        ├── downloads.json
        └── downloaded.jsonl
```

## 4. 首次联测清单（v1.1）

1. `doctor` —— 环境就绪（看 profile 锁 / session.json / CDP 三项）。
2. `login` —— 窗口里登录；看到"✅ 登录成功 + 到期时间 + session.json 已更新"。
   窗口在登录成功前不会关（旧版会闪关，已修）；之后随时 `doctor` 可看登录健康。
3. `jobs from-csv --csv …/worklist-清洗版-2026.csv --out jobs/2026T-165.jsonl` —— 核对条数。
4. `run --jobs jobs/2026T-165.jsonl --window 2026 --dry-run --limit?`（先 3 件：把作业单
   切前 3 行）—— 看 `run_report.md`：六校验结论是否符合预期（打码件应被判 `masked`、
   烟草件应被判 `gambling`、字段式应被判 `narrative`）。
5. `run --jobs … --window 2026 --cap 10` —— 小批真下载；确认 `downloads/` 有文件、
   `run_report.md` 与 `downloaded.jsonl` 对得上；再 `--resume` 续跑扩批。
6. `search --plan …/example-js-2022.json` / `fetch --run <run_dir>` —— 老的检索→预探链路
   照旧可用（需 recon 固化过字段）。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| 提示"安全验证"（退出码 3） | 在窗口里按页面提示人工完成验证，重跑命令；不绕过 |
| 提示"[需登录]"（退出码 2） | `login`（登录态可能过期或被清理） |
| login 窗口被关掉 | 说明是旧版行为，v1.1 起登录成功前不会关窗；若你手动关的窗口，重跑 `login` |
| `serve` 起不来（CDP 未就绪） | 多半是本机已有同 profile 的 Chrome 在跑——先全部关闭再重跑 |
| 找不到搜索框/下载按钮 | 日志会打印页面候选按钮；把日志发回，按实况补选择器；下载类操作可用 `--manual` 先绕过 |
| `search` 命中数远大于收下的条数 | 正常（去重+单任务上限）；补 `split.values`（如年份）分批，或调大 `--limit` |
| 触发风控（SecurityProtection/验证码） | 工具自动停止；按红线等待并在窗口里人工处理，当天降低批量 |
| `run` 下载失败（未收到文件） | 看 `run_report.md` 原因；可在窗口中人工点一次下载，再 `--resume` 重跑该批 |
| 下载的文件没出现 | 看 `downloaded.jsonl`；多半是页面按钮对不上 → 用 `--manual` |

## 6. 设计要点（为什么这么做）

- **必须真窗口**：headless 被站点防护拦截（实测 567）；可见浏览器 + 人类节奏是唯一合规路径。
- **同源 fetch + 回放**：所有 API 在页面上下文里发（自动带会话与防护通行证）；
  响应体不回读网络事件（有竞态），而是回放同一请求确定性取回。
- **预探同源判定**：`fetch` 的形态判定直接调用解析器本体，保证"预探"与"入库解析"结论一致。
- **下载监听 + 人工兜底**：文件由监听器自动收；自动化失灵时人只需点一下，流程不中断。
- **凭据零落库**：登录是人的动作；工具只读 `localStorage` 里的 token；密码/验证码从不进代码、不进日志。

## 7. 状态

- v1.1（2026-10-16 作业台开放后）：**会话稳定化**（登录永不自关 / `serve` 常驻 + CDP 接管 /
  `session.json` / doctor 锁检测）、**作业流水线**（`jobs` + `run` 六校验限额下载 + 断点 + 报告）
  已实现，单测 37 项（本文件所在目录 tests/test_pkulaw_agent.py）+ collect 全量 78 项全绿；待联测验证。
- 全部命令的**代码与单测就绪**，账号联测进行中；
- 网页版"字段式七字段"的排版需第一份真实抓取样本后适配解析器（叙述式判定已可靠）；
- `report`（要素出现率核对）暂用既有 `research/eval/key_field_presence.py` 手工跑；自适应换词待做。
