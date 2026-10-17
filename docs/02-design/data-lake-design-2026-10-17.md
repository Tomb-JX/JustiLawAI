# JustiLaw 数据湖设计 v0.2

> 2026-10-17 初稿；2026-10-18 协调评审通过并裁定实施 · 覆盖公开网页、法宝、裁判文书、复议专栏等全部来源
> **2026-10-18 协调裁定**：T-L1 归法宝线立即实现（blob/manifest/catalog/verify＋首个双写批次）；采集不等湖；可重建承诺只适用 lake 化版本（r7+），r1–r6 保持原样；`zstandard` 入 requirements；REGISTRY 与 lake.db 双写至 M4；网页 M2／引擎 M4 在各自接入点后置。
> 目标：把现在的“多套目录 + 多份全文 + 手工对账”收敛为**不可变、可追溯、可重建、去重存储**的数据湖；不改变当前生产路径，按迁移阶段切换。
> 相关：[项目现状总览](../04-plan/project-status.md)、`parse-format-chain-design-2026-10-17.md`（网页线工作树）、[数据交付规格](../05-research/data-spec.md)、`normative-revision-deid-cancel-2026-10-17.md`（协调分支）

## 0. 一句话结论

当前数据量只有约 **1.9 GB**，但同一篇正文在 raw、parsed、unified、delivery 中被重复保存；仅三批 web parsed-1 的 `text_full` 去重后就能从 30.0 MB 降到 9.9 MB（省 67%）。因此不需要数据湖平台软件，**内容寻址 blob + 批级 manifest + SQLite 目录 + 快照/差量**即可完成规范化与存储优化。

## 1. 目标与非目标

### 1.1 目标

1. **单一事实源**：每个正文、每条记录、每次模型运行、每个交付版本都有唯一 artifact id 与哈希。
2. **来源中立**：网页/法宝/裁判文书/复议只在 `extra` 保留源特有字段；模型输入统一为 `unified_raw`，语义产物统一为 `parsed-2`。
3. **可追溯**：任意交付记录可沿 manifest 追到批次、解析器、清理规则、模型/提示词、原始文件。
4. **可重建**：交付版本可由 manifest + blob 重建，不依赖“当时目录还在”。
5. **去重存储**：同一正文只存一份；版本间只存差量与指针。
6. **安全合规**：原始/原文含个人信息，全部留在仓库外的加密数据目录；脱敏只在外发前做。
7. **渐进迁移**：现有脚本、路径、r6 基线不被破坏；新批次先双写，验证后切读。

### 1.2 非目标

- 不自建分布式文件系统、Spark/Flink、对象存储集群；单机 + 本地磁盘足够。
- 不把 raw HTML/PDF/DOC 立即改成 blob-only；原始件保留可读路径，manifest 记哈希。
- 不在本轮修改 r6 或回溯重写 r1–r5。
- 不把 deid/r6_scan 重新拉回主管线；它们只服务外发。

## 2. 现状与约束（实测）

### 2.1 两端链路

**法宝**

```
pkulaw_agent（真浏览器：search / fetch 零配额 / download --cap）
  → raw/pkulaw + ingest/<批次>（legacy 四分级 JSONL）
  → pkulaw_ingest.py merge（跨批去重）
  → pkulaw_ingest.py parsed1 → parsed/pkulaw/<批次>
  → unify/to_unified.py（S0）→ unified_raw/pkulaw/<批次>
  → [S1 模型暂停] → parsed-2
```

**网页**

```
discover/search.py（千帆 API：缓存/预算/限速/饱和拆分）
  → harvest/harvest.py（raw HTML + text + OCR）
  → harvest/parse.py → admin/web_cases.pre_deid.jsonl
  → harvest/to_parsed1.py → parsed/web/<批次>
  → unify/to_unified.py（S0）→ unified_raw/web/<批次>
  → [S1 暂停] → parsed-2
  → harvest/build.py → delivery/<版本>（当前 r6）
```

**当前收敛点**：两端都已产出 `unified_raw`；但 **parsed-2 不存在**，r6 仍从 parsed-1 构建，分段/outcome 仍是正则，`event_key` 为空，`province` 仍是执法地域。

### 2.2 存储实测

| 目录 | 文件数 | 占用 | 说明 |
|---|---:|---:|---|
| `raw/` | 928 | 1,021.5 MB | CAIL 压缩包 984.6 MB + 法宝原件 37 MB |
| `browser-profile/` | 2,604 | 297.3 MB | 登录态 + 缓存；不属于数据层 |
| `harvest/` | 4,487 | 157.4 MB | raw HTML 142.8 MB、正文 10.9 MB、OCR |
| `discover/` | 688 | 108.9 MB | 缓存 65 MB、运行产物 28.7 MB |
| `parsed/` | 63 | 89.3 MB | web 三批各约 24 MB；pkulaw 全量约 7.5 MB 文本 |
| `admin/` | 19 | 69.4 MB | 含三份旧 `web_cases.pre_deid*` 约 64 MB |
| `delivery/` | 34 | 41.9 MB | r2–r6 五版，每版约 8 MB |
| `unified_raw/` | 27 | 26.2 MB | web r3 17.6 MB + pkulaw 约 8 MB |
| `ingest/` | 99 | 15.5 MB | 法宝 legacy 四分级 JSONL |
| `engine/` | 1,886 | 19.9 MB | 验收报告、缓存、台账 |

**文本去重实测**（按 `text_full` 的 SHA-256）：

| 范围 | 总文本 | 唯一文本 | 去重可省 |
|---|---:|---:|---:|
| parsed/web 三批 | 30.0 MB | 9.9 MB | 67% |
| delivery r2–r6 | 12.1 MB | 5.7 MB | 53% |
| parsed/pkulaw 全部批次 | 7.5 MB | 1.9 MB | 74% |

### 2.3 现有问题

1. 正文多份复制：raw/text/parsed/unified/delivery 各存一份。
2. 交付版本全量快照：r2–r6 每版完整正文，无法只保留差量。
3. `admin/` 留着脱敏时代的三份 20 MB 级副本，D-003 后已属历史。
4. `browser-profile` 297 MB 中大量是浏览器缓存，登录态只占很小一部分。
5. 同一记录在 parsed-1、unified_raw、delivery 中的字段语义不完全一致（`province`、`event_key`、`subject`）。
6. 批次/版本靠文件名和 REGISTRY 人工对账，缺少机器可查的 artifact 关系。

## 3. 设计原则

1. **不可变**：批次的 records/正文/模型输出发布后不原地修改；新版本 = 新 artifact。
2. **内容寻址**：正文、清单、交付 manifest 都以 SHA-256 为键；路径可由哈希推导。
3. **清单优先**：先有 manifest，后有数据；没有 manifest 的文件不算“已发布”。
4. **单一职责**：渠道层只抽文本/源标记；S0 只做确定性清理；S1 只做语义；S2 只做定位；S3 只做校验；build 只做组装/事件键/区划。
5. **版本门控**：r6 等历史版本按 `pipeline_version`/`schema_version` 兼容；新要求只对新版本生效。
6. **本地优先**：单机、SQLite/DuckDB、zstd；不引入需要运维的分布式组件。
7. **内外双口径**：内部保留原文；对外发布前离线跑 deid/r6_scan，生成独立 export。

## 4. 目标架构

### 4.1 分区

```
$JUSTILAW_DATA_DIR/
  lake/
    landing/<source>/<batch>/          # 收取的原始文件 + landing.manifest.json
    raw/<source>/<batch>/              # 不可变原始件（HTML/PDF/DOC/图片）
    blobs/sha256/<aa>/<hash>.zst       # 文本/附件内容寻址；原始件也可按需纳入
    parsed/<source>/<batch>/           # L1：轻记录（正文用 blob 引用）
    unified/<source>/<batch>/          # S0：cleaned blob 引用 + edits.rle.jsonl
    runs/s1/<run_id>/                  # manifest/receipts/outputs；模型原始返回
    parsed2/<batch>/                   # 模型+组装后的统一产物（JSONL + Parquet）
    curated/delivery/<version>/        # 交付 manifest + 轻记录；正文解析自 blob
    labels/<schema>/                   # 金标/代理标签
    catalog/lake.db                    # SQLite：artifact/批次/文档/记录/运行/交付
    catalog/views/                     # DuckDB/Parquet 只读视图
    ops/
      manifests/<artifact_id>.json     # 每个产物的清单
      schemas/<name>/<version>.json    # JSON Schema 注册表
      gc/                              # GC 报告（默认 dry-run）
  # 兼容层：现有路径在迁移期保留，构建脚本按配置切换
  parsed/ unified_raw/ delivery/ ...
```

### 4.2 数据流

```
source adapter → landing manifest
  → raw（原始件，哈希入清单）
  → text extraction → text blob（text_orig_sha256）
  → channel parser（只产源标记 + 参考段）→ parsed（轻记录）
  → S0 → cleaned blob（text_clean_sha256）+ edits.rle.jsonl → unified
  → S1（模型，run manifest + cache）→ 原始输出
  → S2（引文定位）→ S3（校验）→ parsed2（模型分段/outcome）
  → build（event_key/region/tier/linked_ids）→ curated delivery manifest
  → labels/qa（按版本引用，不复制正文）
  → export（外发前 deid/r6_scan）
```

### 4.3 兼容策略

- 迁移期保留现有 `parsed/`、`unified_raw/`、`delivery/` 路径只读；新批次写入 `lake/`，同时写一份兼容视图。
- `build.py` 通过配置选择“旧路径”或“lake manifest”；r6 继续按旧路径冻结。
- 切读顺序：新批次 → 全量 parsed → delivery；任何一步验证失败可回退。

## 5. 数据模型

### 5.1 核心实体

| 实体 | 键 | 说明 |
|---|---|---|
| `Source` | `source_id` | 公开网页、复议专栏、法宝执法库、法宝案例库、裁判文书、合作案卷 |
| `Batch` | `batch_id` | 一次采集/解析批次；不可变；含输入/输出清单 |
| `Document` | `doc_id` | 一篇文书/页面；`source + source_ref` 唯一；含 `doc_no_hash`、机关、日期、区划 |
| `Blob` | `sha256` | 正文/附件字节；zstd 压缩；原文/清洗文各一 |
| `Record` | `record_id` | 解析/交付记录；`text_sha256` 引用 blob；`record_hash` 规范化哈希 |
| `Run` | `run_id` | S1/S2/S3 一次运行；含模型、提示词、输入批次、receipts |
| `Delivery` | `version` | 交付版本；manifest 列出记录 id + record_hash + text_sha256 |
| `Label` | `label_id` | 金标/代理标签；引用 record_id 与 schema 版本 |
| `Issue` | `issue_id` | 验收/质检/回退问题；关联 record_id、规则、状态 |
| `Artifact` | `artifact_id` | 任意文件/目录产物；含 kind、path、sha256、parents、producer、version |

### 5.2 记录引用规则

- `text_full` 不再直接嵌入每条记录；记录只保留：
  - `text_orig_sha256`（抽取后的原文；等价于现有契约的 `text_sha256`）
  - `text_clean_sha256`（S0 后，模型输入；现有 parsed-1 没有，新增）
  - `text_len`、`encoding`
  - `segments`/`text_*`（段文本可保留，但必须能由 blob + offsets 重建）
- `province` 只存真省名；执法地域（市/区/旗）保留在 `extra.region_text`，不再冒充省。`region` 由 build 层按机关名解析并回写交付；parsed-1 只有省直管市等可直接确定的情况才带区划码。
- `doc_no` 明文与 `subject_mention` 允许进入内部交付（D-003）；`labels/` 不收录姓名/证件类字段，M1 用 `subject_mention` 定位。
- `event_key` 只由 build 层生成；源端旧 `event_key` 降为参考，不再作为交付键。
- `record_ref = batch_id + ":" + record_id`；同一记录可出现在多个批次，跨批次引用必须带批次。
- 交付层可继续输出 `text_full` 供下游直接使用，但构建时从 blob 解析，不把全文写进交付 manifest。
- `record_hash` 规范化：UTF-8、键排序、无多余空白；用于版本 diff 与去重。
- 任何正文缺失/哈希不匹配 = 硬失败，不生成交付。

## 6. 存储布局与格式

### 6.1 Blob

```
blobs/sha256/<前两位>/<sha256>.zst
```

- 压缩：zstd（级别 3；文本/JSONL 均可）。
- 哈希：对**未压缩字节**计算 SHA-256；路径只由哈希决定。
- 元数据：`size_raw`、`size_zst`、`media_type`、`created_at` 放 catalog，不放进 blob 文件。
- 同一正文在 parsed/unified/delivery 中只保留引用；跨批次自动去重。

### 6.2 记录文件

- 交换/增量：JSONL（UTF-8，一行一条）。
- 分析/大表：Parquet（按 `source/batch` 或 `year` 分区，zstd）。
- 交付目录保留 JSONL + `SHA256SUMS` + manifest；轻记录中的正文由 blob 解析。
- `edits.rle.jsonl` 与 unified 批次同目录；作为可回放审计件，压缩后入库。

### 6.3 目录与命名

- 批次：`<source>/<YYYYMMDD>-<说明>[-rN]`；发布后不可变。
- 版本：`delivery/<YYYY-MM-DD>.rN`；`LATEST` 只是指针。
- artifact id：`<kind>-<sha256前16>`（Windows 文件名不能含冒号）；manifest 文件名同 id。目录表内部仍可用 `kind:hash` 逻辑引用，但落盘名统一用连字符。
- 双写期对外引用统一写“交付版本号 + artifact id”；REGISTRY 保留至 M4，与 lake.db 双写。
- 禁止用“同名 + 覆盖”表达新版本；脚本默认拒写已存在路径。

## 7. 清单与血缘

### 7.1 批级 manifest

```json
{
  "manifest_version": "1.0",
  "batch_id": "parsed/pkulaw/merged-20261017-full",
  "source": "法宝执法库",
  "created_at": "2026-10-17T21:00:00+08:00",
  "producer": {"name": "pkulaw_ingest.py", "version": "0.3", "commit": "..."},
  "inputs": [{"path": "...", "sha256": "...", "bytes": 123}],
  "outputs": [{"path": "...", "sha256": "...", "records": 890}],
  "versions": {"schema": "1.0.0", "parser": "pkulaw_ingest.py@0.3", "clean": "clean:v1"},
  "counts": {"records": 890, "by_tier": {"L1-金标候选": 856}},
  "status": "published",
  "parents": ["batch:..."],
  "notes": ""
}
```

### 7.2 交付 manifest

```json
{
  "manifest_version": "1.0",
  "version": "2026-10-17.r6",
  "base_version": null,
  "created_at": "...",
  "build": {"producer": "harvest/build.py", "version": "harvest-0.6", "commit": "..."},
  "inputs": [{"batch_id": "...", "manifest_sha": "..."}],
  "records": [{"id": "P-115", "record_hash": "...", "text_sha256": "..."}],
  "counts": {"main": 1695, "outcomes": 576, "events": 846},
  "diff": {"added": [], "changed": [], "removed": []},
  "acceptance": {"report": "...", "verdict": "..."}
}
```

### 7.3 血缘

- 每个 artifact 写 `parents`（输入 artifact id 列表）。
- 目录表 `lineage(child_id, parent_id, relation)`；支持“这条交付记录由哪个批次/模型/规则产生”的递归查询。
- manifest 本身也内容寻址：`artifact:manifest:<sha256>`。

## 8. 采集与处理契约

### 8.1 Source adapter

每个来源实现同一接口：

```
ingest(source, batch, input) -> LandingManifest
  - 原始文件路径 + sha256 + bytes
  - source_ref、抓取时间、HTTP 状态/内容类型（网页）
  - 法宝引证码/文号/库类型（法宝）
  - 合法来源标记（公开页 URL、法宝订购/导出记录）
```

### 8.2 渠道解析

- 只输出：`text_orig`、`form`、`source markers`、参考段（可选）。
- 不再新增语义抽取规则；正则 outcome/分段仅作对照，不进 parsed-2 权威字段。

### 8.3 S0/S1/S2/S3

- S0 规则注册表按源分册，版本 `clean:v1`；输出 cleaned blob + RLE edits。
- S1 运行必须写 `manifest.json`、`receipts.jsonl`、`outputs.jsonl`；缓存键 = `text_clean_sha256 + prompt_version + model`。
- S2 只接受 S1 的引文；失败进低置信队列，不猜坐标。
- S3 校验字段/枚举/法条/日期/引文/段重叠；硬失败换模型重试一次，仍失败入队。

### 8.4 build

- 唯一负责 `event_key`、`event_id`、`region`、`tier`、`linked_ids`。
- 只读 manifest/轻记录；正文从 blob 解析。
- 交付版本写 manifest + diff；不覆盖旧版本。

## 9. 目录与查询

### 9.1 SQLite 表

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE artifacts (
  artifact_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,              -- blob / batch / record / run / delivery / label
  sha256 TEXT NOT NULL,
  path TEXT,
  bytes INTEGER,
  parents TEXT,                    -- JSON array
  producer TEXT,
  version TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  manifest_sha TEXT NOT NULL,
  records INTEGER,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_ref TEXT,
  doc_no_hash TEXT,
  authority TEXT,
  region_code TEXT,
  behavior_date TEXT,
  decision_date TEXT,
  law_version TEXT,
  text_orig_sha256 TEXT,
  meta TEXT
);
CREATE TABLE records (
  batch_id TEXT NOT NULL,
  record_id TEXT NOT NULL,
  doc_id TEXT,
  tier TEXT,
  outcome_type TEXT,
  event_id TEXT,
  text_clean_sha256 TEXT,
  record_hash TEXT NOT NULL,
  record_path TEXT NOT NULL,
  PRIMARY KEY (batch_id, record_id)
);
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  model TEXT,
  prompt_version TEXT,
  input_batch TEXT,
  manifest_sha TEXT,
  status TEXT,
  created_at TEXT
);
CREATE TABLE deliveries (
  version TEXT PRIMARY KEY,
  manifest_sha TEXT NOT NULL,
  records INTEGER,
  status TEXT,
  created_at TEXT
);
CREATE TABLE lineage (
  child_id TEXT NOT NULL,
  parent_id TEXT NOT NULL,
  relation TEXT,
  PRIMARY KEY (child_id, parent_id, relation)
);
CREATE INDEX idx_documents_docno ON documents(doc_no_hash);
CREATE INDEX idx_documents_region ON documents(region_code);
CREATE INDEX idx_records_id ON records(record_id);
CREATE INDEX idx_records_event ON records(event_id);
CREATE INDEX idx_records_text ON records(text_clean_sha256);

CREATE VIEW v_missing_blob AS
SELECT r.batch_id, r.record_id, r.text_clean_sha256
FROM records r
WHERE r.text_clean_sha256 IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM artifacts a
    WHERE a.kind = 'blob' AND a.sha256 = r.text_clean_sha256
  );
CREATE INDEX idx_artifacts_sha ON artifacts(sha256);
```

- 写入：单写者（批次脚本）持有 SQLite 写锁；读并发走 WAL。
- 分析：DuckDB 直接读 Parquet/JSONL，或 `ATTACH` SQLite；不把大表塞进 SQLite。

### 9.2 常用视图

- `v_current_delivery`：`deliveries` 中 status=现行 的唯一行。
- `v_record_current`：最新交付中的记录 + 文档元数据 + blob 路径。
- `v_batch_lineage`：批次 → artifact → run → delivery。
- `v_missing_blob`：records 引用的 text_sha256 不在 artifacts/blobs 中。

## 10. 版本、快照、GC 与保留

### 10.1 版本

- 每个批次/交付/运行有独立版本号；`schema_version`、`clean_version`、`model_id`、`prompt_version`、`build_version` 分开记录。
- `LATEST`/`CURRENT` 只是指针；不是“内容安全批准”。
- r6 作为冻结基线：新契约要求只对 `pipeline_version != harvest-0.6` 生效。

### 10.2 快照与差量

- `delivery/<version>/manifest.json` 记录每条 record_hash/text_sha256。
- 与 base_version 比较生成 `diff`；交付目录只存变更记录与 manifest，未变记录由 base manifest 解析。
- 需要完整快照时按 manifest 物化到临时目录；物化结果写 `materialized_at` 与哈希，便于审计。

### 10.3 GC

- 默认 `dry-run`；只删除**无任何 manifest 引用**的 blob/artifact。
- 保留类：
  - 原始件/交付 manifest/验收报告：长期（审计）；
  - 模型 runs/receipts：180 天或复现窗口；
  - 解析中间件：可重建的，保留最近 N 版；
  - 缓存：30 天；
  - `browser-profile`：不纳入 lake GC，单独清缓存。
- GC 报告写 `ops/gc/<date>.json`，列出保留/删除/引用计数。

## 11. 安全与合规

1. `lake/raw`、`lake/blobs`、`parsed2` 含原文与个人信息：仓库外、全盘加密、目录 ACL；禁止入 Git。
2. `browser-profile` 含登录态：独立 vault；只清缓存，不复制进 lake；凭据不进 manifest/日志。
3. `labels/` 不收录姓名/证件类字段；M1 用 `subject_mention` 定位。
4. 外发：只从 `curated/delivery` 物化 export，先跑 deid/r6_scan，生成独立 `export/<version>`；不得直接对外共享 lake 路径。
5. 日志/回执：模型请求与响应只留摘要/哈希；密钥掩码；例外人工审批。
6. 删除：只走 GC + 审批；交付版本与验收报告不做物理删除。

## 12. 迁移方案

### Phase 0：盘点与 manifest 骨架（不移动文件）

- 对现有 `parsed/`、`unified_raw/`、`delivery/`、`ingest/` 逐文件算 SHA-256。
- 建 `lake.db` 的 artifacts/batches/deliveries 行；状态 `legacy`。
- 产出 `migration-inventory.json`：文件数、总大小、重复文本统计。

### Phase 1：新批次双写

- 法宝/网页新批次同时写旧路径与 `lake/`：blob + manifest + catalog。
- 旧的 `build.py` 仍读旧路径；新增 `--lake` 开关读 manifest。
- 验收：同一批次两条路径的记录数/哈希一致。

### Phase 2：迁移现有 parsed/unified

- 提取 `text_full` → blob；记录改为引用；保留 `text_full` 兼容字段直到下游切换。
- 重写 records 文件（新批次目录），不覆盖旧文件；对比旧/新记录除正文引用外逐字段一致。
- 验证：随机 10% + 全量哈希抽查；`v_missing_blob` 为空。

### Phase 3：交付差量化 + parsed-2

- `build.py` 输出 manifest + diff；r6 保持原样，新版本开始使用。
- S1/S2/S3 产物写入 `runs/` 与 `parsed2/`；build 只读 parsed-2 manifest。
- 引擎验收改为读 delivery manifest，不再扫目录。

### Phase 4：GC 与分层

- 归档 `admin/web_cases.pre_deid*`（约 64 MB）与旧 delivery 全文副本，保留 manifest/哈希。
- 压缩 raw/harvest 冷层；清 browser cache；配置保留策略。
- 目标：文本层去重 ≥50%，目录可查，交付可重建。

### 回退

- 配置开关 `LAKE_READ=legacy|lake`；Phase 1–2 旧路径不动；任何验证失败切回 legacy。
- r6 不接受新契约字段；直到网页线/引擎线明确 r7。

## 13. 容量与性能

- 当前 1.9 GB；其中 raw 1.02 GB 为冷层，browser-profile 297 MB 为登录 vault。
- 文本层去重后：web 9.9 MB + pkulaw 1.9 MB + 交付 5.7 MB（有重叠）→ blob 压缩后预计 < 20 MB；加上 metadata/manifest 仍远小于现状。
- 增长假设：每年 5,000 篇、每篇 2 KB 文本 + 1 KB 元数据 → 文本约 10 MB/年；模型输出/回执约 5 MB/年；不需要分片数据库。
- 查询：SQLite 索引下按 id/文号/事件/区划为毫秒级；DuckDB 全量统计在秒级。
- 写入：单批次 < 1 万条，SQLite 事务足够；模型 runs 按目录分片。

## 14. 验收标准

1. **manifest 覆盖**：活跃批次 100% 有 manifest；每个 artifact 有 sha256。
2. **可解析**：所有 records 的 `text_orig_sha256`/`text_clean_sha256` 均能在 blob 找到；`v_missing_blob` 为空。
3. **可重建（仅 lake 化版本）**：r7 及之后的 lake 化交付，随机 3 个版本从 manifest + blob 重建，记录数与 `record_hash` 完全一致；r1–r6 保持原样目录，不承诺重建、不回溯改写。
4. **去重收益**：文本层总字节较现状下降 ≥ 50%；同一正文只存一份。
5. **契约兼容**：r6 在 D-003 兼容修改后 acceptance 为 0 error（warning 保留）；新契约不追溯 r6。
6. **安全**：仓库中无原文/凭据；export 目录均经过 deid/r6_scan；browser-profile 不入 lake。
7. **性能**：目录查询 P95 < 100 ms；全量统计 < 10 s；批次写入不因目录锁失败。
8. **测试**：blob/manifest/catalog/migration 各有单测；旧 build 测试全绿。

## 15. 风险与未决

| 风险/未决 | 处置 |
|---|---|
| Windows 路径长度/文件锁 | 短路径、批次目录不嵌套过深；SQLite WAL；写入串行 |
| blob 损坏/丢失 | 写入时校验；`verify` 全量扫描；manifest 记录原始哈希 |
| schema 漂移 | JSON Schema 注册表 + 版本门控；旧版本不追溯 |
| 多会话并发写 | 单写者原则；批次级锁；catalog 事务 |
| r6 与新契约冲突 | version gate；先做 D-003 兼容补丁；新要求只对 parsed-2 |
| PII 外泄 | 数据目录加密/ACL；export 前 deid；禁止入 Git |
| GC 误删 | 默认 dry-run；manifest 引用计数；审批后执行 |
| 目录 DB 选型 | v0.1 采用 SQLite 元数据 + DuckDB/Parquet 分析；不引入服务端 |
| 原始件是否入 blob | 首期保留 raw 可读路径；只对文本/派生件做 blob |

## 16. 实施排期（建议）

| 阶段 | 内容 | 产物 | 负责 |
|---|---|---|---|
| M0 | 本设计评审；字段/目录/版本口径定稿 | 设计 v0.2 | 协调 + 引擎 + 网页 + 法宝 |
| M1 | blob + manifest + catalog 原型；法宝一个新批次双写 | 原型 + 单测 | 法宝线 |
| M2 | 网页一个新批次接入；`build.py --lake` 读 manifest | 双写验证 | 网页线 |
| M3 | 迁移 parsed/unified；去重与重建验证 | 迁移报告 | 数据线/法宝 |
| M4 | 交付 manifest/diff；引擎验收改读 manifest | r7 预演 | 引擎 + 网页 |
| M5 | GC/保留/压缩/目录视图 | 运维手册 | 协调 |

## 17. 实施状态（T-L1，2026-10-18）

| 项 | 状态 |
|---|---|
| 代码 | `research/discretion/lake/{blob,manifest,catalog,verify,dualwrite}.py` |
| 单测 | 5 passed（blob 往返/损坏、manifest、catalog、dualwrite、verify） |
| 首个双写批次 | `merged-20261017-full`，890 条 |
| 第二个验证批次 | `20261016-2026T作业台-b4-r2`，2 条；复用同一批 blob，验证跨批去重 |
| P1 批次 | `20261018-P1-r5`，144 条；id P-928–P-1110，build 区划 144/144，text_party 144/144 |
| P1b 批次 | `20261018-P1b-r1`，76 条（74 L1）；id P-1111–P-1225，text_party 73/76 |
| blob | 1,110 个；原文 2.37 MB → zstd 1.17 MB |
| manifest | `batch-ee759153fcbc10fd`（merged）＋ `batch-46df7f33b2762a42`（b4-r2）＋ `batch-c57c8429815e0850`（P1-r5）＋ `batch-2b7c17ae054debe8`（P1b-r1） |
| catalog | artifacts 1,122（1,110 blob + 4 input + 4 records + 4 manifest）/ documents 1,110 / records 1,112 / lineage 12 |
| verify | blobs 1,110、manifests 4、records 1,112，0 error；lake 9.2 MB |
| 未做 | 网页 M2、引擎 M4、存量迁移、P1 并入 r7 |

T-L1 当前验收：manifest 覆盖首批、blob 可解析、单测绿。P1 新批次落盘后按同一命令补双写即可，采集不等湖。

## 附录 A：旧路径 → lake 映射

| 现状 | lake 目标 | 切换方式 |
|---|---|---|
| `parsed/pkulaw/<batch>/records.jsonl` | `lake/parsed/pkulaw/<batch>/records.jsonl` + blob | 双写 → 切读 |
| `parsed/web/<batch>/records.jsonl` | 同上 | 双写 → 切读 |
| `unified_raw/<channel>/<batch>/` | `lake/unified/<channel>/<batch>/` | 新批次直接写 lake |
| `delivery/<version>/` | `lake/curated/delivery/<version>/` | 新版本写 lake；旧版本 manifest 化 |
| `admin/web_cases.pre_deid*` | 归档冷层 | Phase 4 压缩归档 |
| `engine/acceptance/<hash>/` | `lake/ops/acceptance/<hash>/` | 验收器改读 manifest |
| `REGISTRY.csv` | `lake/catalog/lake.db` + 兼容 CSV | 双写一段时间 |

## 附录 B：最小验收命令（设计目标）

```bash
# 1) 校验所有 manifest 引用的 blob 存在且哈希一致
PYTHONPATH=research/discretion python -m lake.verify --lake "$DATA/lake"

# 2) 从 manifest 重建一个交付版本到临时目录（materialize 在 M4 提供）
# python research/discretion/lake/materialize.py delivery/<版本> --out /tmp/rebuild

# 3) 目录查询
sqlite3 "$DATA/lake/catalog/lake.db" "select count(*) from records;"
```

> 本设计不改变当前 r6；M1 起新批次双写，M3 后才切读。任何迁移步骤失败均可回退到现有路径。

## 变更日志

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-18 | v0.2 | 协调评审通过并裁定实施；T-L1 法宝线立即；artifact id 改为 Windows 安全形式；可重建承诺收窄到 lake 化版本（r7+）；zstandard/REGISTRY 双写口径；补 T-L1 实施状态 |
| 2026-10-17 | v0.1 | 初稿：现状实测、分区、数据模型、blob/manifest/catalog、迁移与验收 |
