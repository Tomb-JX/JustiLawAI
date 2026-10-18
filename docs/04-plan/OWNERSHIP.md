# 职责与写入边界（精简版）

> 本文件只回答“谁负责什么、能写哪里”。历史分工与目录细节见 [workstreams.md](./workstreams.md)（其会话状态已过期）；当前循环见 [BOARD.md](./BOARD.md)。

## 1. 角色

| 角色 | 负责 | 不负责 |
|---|---|---|
| Loop owner | 一个跨线结果的推进、激活、验收与回报；有权说“停/下一个” | 不替其他线实现；不绕过 BOARD 开新循环 |
| 引擎 | element 语义：schema、字段裁决、归一化、证据语义、**主体绑定** | 不改 `unify/**`；不跑付费批；不发布 r7 |
| 后处理 | `unify/**` 管线：S0/S1/S2/S3、契约接入、离线回放与诊断 | 不重定义引擎字段；不碰采集/交付正本 |
| 协调 | BOARD/DECISIONS/ARTIFACTS/ISSUES/handoffs；优先级、路由、验收口径 | 不做第二实现者；不改其他线代码/数据 |
| 来源（网页/法宝） | 原文、台账、批次与来源证据 | 不产模型标签；不替引擎判语义 |
| 用户 | 真正的取舍与对外决定 | 不作为日常消息路由器 |

## 2. 写入边界（仓库内）

| 线 | 可写 | 只读 |
|---|---|---|
| 协调 | `docs/04-plan/{BOARD,DECISIONS,ARTIFACTS,ISSUES,OWNERSHIP}.md`、`handoffs/**`、协调记录 | 其他线代码、数据、交付 |
| 引擎 | `justilaw-api/app/discretion/**`、`research/eval/**`、`docs/05-research/**` | `research/discretion/unify/**`、`delivery/**` |
| 后处理 | `research/discretion/unify/**`；`research/discretion/harvest/{parse.py,parse_qc.py,to_parsed1.py}` 及其对应测试（**仅网页原文→parsed-1 前处理：HTML 表格行、字段/事件键、QC**）；管线测试 | 引擎 schema 正本、`delivery/**`、`discover/**`、`collect/**`、`harvest` 其余文件、既有 `unified_raw`/`parsed` 正本 |
| 网页/来源 | `research/discretion/discover/**`、`harvest/**`（**`parse.py`/`parse_qc.py`/`to_parsed1.py` 当前写权限归后处理**）、发现/收割文档 | 引擎字段语义、标签定义、`unify/**` |
| 法宝 | `research/discretion/collect/**`、`ingest/**`、法宝文档 | 引擎字段语义、标签定义 |
| 数据湖 | `research/discretion/lake/**`、`lake/**` | 各源批次正本 |

## 3. 三条硬规则

1. **一个结果一个 owner**：跨线结果只能有一个 loop owner；其他人是贡献方。owner 不在时，协调代管看板但不代做实现。
2. **消费方验收**：交接完成的唯一标准是消费方跑了验收命令并回报；生产方说“已完成”不算。
3. **交接前可见**：handoff 引用的 commit 必须在 origin 上，或明确写“本地 commit + 备份路径”；未提交/未推送的产物不得作为他人输入。
