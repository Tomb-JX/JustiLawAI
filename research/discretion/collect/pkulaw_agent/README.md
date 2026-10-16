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

## 1. 命令总览（9 个）

| 命令 | 一句话 | 联网 | 下载配额 | 需要登录 |
|---|---|---|---|---|
| `doctor` | 环境自检 | 否 | 0 | 否 |
| `login` | 开真窗口，人工登录一次，固化 profile | 是 | 0 | — |
| `recon` | 捕获一次真实操作（检索/详情/下载）的请求，固化字段 | 是 | 0 | 是 |
| `cluster` | 拉筛选维度与 id 映射（如"江苏省"对应什么值） | 是 | 0 | 是 |
| `call` | 任意 API 直调（探索/对账用） | 是 | 0 | 是 |
| `search` | 按作业单检索：分页、饱和拆分、去重 → `results.jsonl` | 是 | 0 | 是 |
| `fetch` | 逐条开详情页抓正文 → `.txt` + 形态预探（可直连解析链） | 是 | **0** | 是 |
| `download` | 下载文件：逐条 / 结果页勾选 / 库页检索；可人工兜底 | 是 | **有** | 是 |
| `harvest` | 一条命令串完 `search→fetch[→download]` | 是 | 视步骤 | 是 |

通用参数：`--data-dir`（覆盖数据目录）、`--browser`、`--timeout`（等登录秒数，默认 600）。
退出码：`0` 成功；`2` 未登录/登录过期；`3` 撞上安全验证页（需人工在窗口完成验证后重跑）；`130` 手动中断（进度已落盘，可续）。

## 2. 命令详解

### doctor — 环境自检
不联网、不开窗口。检查 Python / playwright / Chrome / Edge / 数据目录可写 / profile 是否已存在。
第一次拿到机器或换机器先跑它。

### login — 登录一次，之后免登录
```bash
... __main__.py login [--timeout 600] [--browser chrome]
```
打开执法库入口页并轮询登录态（`localStorage.access_token`）。**账号密码/微信扫码/图形验证码都由你在窗口里完成**——
工具不代填、不存密码。成功后打印打码 token 与到期时间（JWT `exp`），登录态写入持久 profile
（`$DATA/browser-profile/pkulaw/`，仓库外），此后 `search`/`fetch`/`download` 直接复用。
若窗口里显示"安全验证"页：按页面提示人工完成，再重跑本命令。

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

## 4. 首次联测清单（账号到手后照做）

1. `doctor` —— 环境就绪。
2. `login` —— 窗口里登录；看到"登录成功 + 到期时间"。
3. `recon --tag <日期>` —— 做三个动作（检索/详情/下载），回车；把 `recon-*.jsonl`、`replay-*.json` 发回给模型组。
4. `search --plan …/example-js-2022.json` —— 核对 `run.json` 的命中总数与页面显示是否一致；
   若字段名对不上，改作业单里的 `field_names`（不动代码）。
5. `fetch --run <run_dir> --limit 10` —— 看 `extract.jsonl` 的形态分布与 `docs/` 里文本质量；
   之后 `download --run <run_dir> --cap 2 --manual` 试两篇，确认文件能自动收下来。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| 提示"安全验证"（退出码 3） | 在窗口里按页面提示人工完成验证，重跑命令；不绕过 |
| 提示"[需登录]"（退出码 2） | `login`（登录态可能过期或被清理） |
| 找不到搜索框/下载按钮 | 日志会打印页面候选按钮；把日志发回，按实况补选择器；下载类操作可用 `--manual` 先绕过 |
| `search` 命中数远大于收下的条数 | 正常（去重+单任务上限）；补 `split.values`（如年份）分批，或调大 `--limit` |
| 触发风控（SecurityProtection/验证码） | 工具自动停止；按红线等待并在窗口里人工处理，当天降低批量 |
| 下载的文件没出现 | 看 `downloaded.jsonl`；多半是页面按钮对不上 → 用 `--manual` |

## 6. 设计要点（为什么这么做）

- **必须真窗口**：headless 被站点防护拦截（实测 567）；可见浏览器 + 人类节奏是唯一合规路径。
- **同源 fetch + 回放**：所有 API 在页面上下文里发（自动带会话与防护通行证）；
  响应体不回读网络事件（有竞态），而是回放同一请求确定性取回。
- **预探同源判定**：`fetch` 的形态判定直接调用解析器本体，保证"预探"与"入库解析"结论一致。
- **下载监听 + 人工兜底**：文件由监听器自动收；自动化失灵时人只需点一下，流程不中断。
- **凭据零落库**：登录是人的动作；工具只读 `localStorage` 里的 token；密码/验证码从不进代码、不进日志。

## 7. 状态

- 全部命令的**代码与单测就绪**（48 项），待账号联测一轮；
- 网页版"字段式七字段"的排版需第一份真实抓取样本后适配解析器（叙述式判定已可靠）；
- `report`（要素出现率核对）暂用既有 `research/eval/key_field_presence.py` 手工跑；自适应换词待做。
