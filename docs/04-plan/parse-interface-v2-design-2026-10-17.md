# parse-v2 模型接口重设计：句表分区（seg-v2 设计草案，2026-10-17）

> 背景：300 试点双判据未全达标（S3 硬失败率 32.9% > 5%；仲裁判据二已达标 27.1% << 98.6%）。本稿回应评审意见：**不靠提示词硬拧，不引入切块**——把失败映射到任务接口的实质缺陷，改接口形态而非改措辞。
> 结论先行：**把模型输出契约从"引文摘录列表"改为"句表分区（run-length 区间）"**——覆盖率与不重叠由数据结构保证而非模型自觉；定性句归置由确定性规则在边界上执行；长文档不做文本切块、只做任务分解。预计输出 token 降 50–60%，超时类失败清零。

## 1. 问题实质映射（三失败类 → 根因 → 接口归因）

| 试点失败类 | 表面原因 | 实质（接口层） |
|---|---|---|
| coverage 51 件（17%） | 模型输出"摘引式分段"，没覆盖全文主体 | **输出契约与需求形态错配**：契约要求的是"引文（摘录）"，摘录是 LLM 的先验行为；而设计需求是"全覆盖"。用提示把摘录扭成全覆盖＝对抗先验，且达标后引文≈全文复述 → 输出 token 翻倍（效率惩罚）——两个方向都是坏解，说明错的是契约本身 |
| facts 定性句收尾 35 件（12%） | 模型违反"定性句不入 facts"硬规则 | **方向反了**：定性句天然位于事实→说理的过渡带，让模型先做逐句内容分类再拼出边界，误差面＝全部句子；而规范对边界的裁决是**确定性规则**（含定性词的句子归 reasoning）。接口应让模型只给近似边界，规则在边界落点上执行归置——规则前移到接口结构，不靠模型自觉 |
| 超时 5 件（复议长文） | 120 秒上限 | **时延由输出长度驱动**（decode 慢、prefill 快）：一次调用要求"分段引文＋全部字段"的大输出。文本切块＝用跨块信息损失与成本乘数换时延——否决。正确解是**按输出体积分解任务，而非按输入长度切文本** |

## 2. 接口重设计：句表分区（sentence-table zoning）

### 2.1 核心变更

确定性代码先把 cleaned_text 切成**编号句表**（S0 尾部新增：句边界＝。！？；＋换行，句表随 offset 体系带原文坐标——与 B 类裁剪/parse_qc 同一切句口径），模型对**句号区间**做分区，不再输出引文：

```
输入（模型可见）：
  [form] 叙述式-独立成篇 | [source_type] 处罚决定书
  [S1] 经查，张某某在某棋牌室赌博…
  [S2] 2023年5月1日晚，张某某与李某某以麻将牌九方式赌博…
  [S3] …
输出（run-length 分区 + 字段，一次调用）：
  {"zones": [{"type":"facts","from":1,"to":14},
             {"type":"reasoning","from":15,"to":16},
             {"type":"decision","from":17,"to":18}],
   "subject": {"mention": "…", "aliases": []},
   "outcome": {…同 v1.2 Schema…},
   "dates": {"behavior": "2023-05-01", "decision": "2023-05-02"},
   "gambling": {"verdict": "是", "reason": "…"},
   "confidence": "high"}
```

### 2.2 结构性保证（不再依赖模型自觉）

| v1 失败类 | v2 保证机制 |
|---|---|
| coverage | zones 必须单调衔接、完整覆盖 [S1..SN]——**校验器从"阻断性检查"降为"实现断言"**（区间非法＝schema 错误→定向重试，量趋零） |
| 段重叠 | 区间不重叠由结构保证（同上） |
| facts 尾定性 | **边界规则 snap**：facts 区间末句含 `CONCLUSION_MARK` → 该句确定性划归 reasoning（与 B 类裁剪同口径同词表）；模型只负责"近似边界"，规则负责"定性归置" |
| 引文多处命中/模糊对齐 | 引文取消——句号即坐标（句表位置由确定性代码持有），幻觉面只剩"句号 id 编错"，可校验可重试 |
| 超时 | 输出从 ~700–1,000 token（引文复述）降到 **~150–400 token**（分区+字段），decode 时延与输入长度基本解耦——38,859 字复议件不切块即可过（prefill 快、decode 小） |

### 2.3 证据与可审计性不损失

- 分区定出区间后，每段的"证据"取**区间首尾句原文**（供 records.segments 与人工抽检），落盘方式与现契约相同；
- 边界 snap 动作记审计（哪句被规则从 facts 移到 reasoning，供试点统计与评审）；
- `anchor/agreement`、`segment_compare`（边界 F1）、S3 其余检查全部照旧——对照基建不变。

### 2.4 形态分治（效率与准确双收益）

| form | 分区来源 | 模型职责 |
|---|---|---|
| 字段表公示 / 标题汇总 | S0 键值行**确定性生成分区**（标签行=分段已成） | 仅字段抽取 |
| 叙述式（独立成篇/复议/结果栏内） | 模型句表分区 | 分区+字段一次调用 |
| 判决书/合作案卷 | 同叙述式（预留） | 同上 |

### 2.5 失败语义

区间非法（断号/越界/类型非法）→ 定向重试一次（只重发分区调用）→ 低置信队列；字段部分与分区部分独立校验，字段成功可保留，避免整件报废。

## 3. 切块方案否决论证（评审点正面回应）

| 切块的代价 | 量级 |
|---|---|
| 信息损失 | 跨块边界的段落被截断（复议"决定如下"常在文末，事实在文首——分属两块后全局分段不可能）；滑动窗口缓解=重复内容进两次输出，成本与一致性都恶化 |
| 成本乘数 | 36 件长文 ×2–3 块＝调用数×1.1，且每块都要全套字段输出（重复解码） |
| 对照基建破坏 | anchor/segment_compare 的"一件一份分区"前提失效，边界 F1 无法计算 |
| 替代解 | 句表分区的输出体积与输入长度解耦——超时的根因（大输出）直接消失，无需切块 |

## 4. 市面方案映射（探索讨论的锚点）

| 市面方案 | 与本设计的关系 |
|---|---|
| [LMDX：anchor-based decoding（ACL 2024）](https://aclanthology.org/2024.findings-acl.899.pdf) | 与 v1 的"引文逐字锚定"同族（生成文本锚→解码到文档位置）；句表分区是它的结构化强化：锚＝句号，由确定性句表给定，模型不生成文本锚 |
| [Instructor: Document Segmentation](https://python.useinstructor.com/examples/document_segmentation) | LLM 结构化输出做分段的通行做法——其"分段对象列表"覆盖性靠提示约定，正是 v1 踩的坑；佐证句表分区的结构化覆盖是差异点 |
| [Explicit Sentence Boundaries（arXiv 2026）](https://arxiv.org/html/2604.10135v1) | 显式句子边界增强 LLM 文本处理——支持"给模型编号句表"的输入形态 |
| [长文档 chunking 信息损失讨论](https://medium.com/@QuarkAndCode/chunking-strategies-for-entity-and-relationship-extraction-48a09c19f00e)、[Unstract: 长文档抽取](https://unstract.com/blog/how-intelligent-chunking-strategies-makes-llms-better-at-extracting-long-documents) | 业界缓解＝overlap 滑窗（重复成本）或 section-first（先分区后抽取）——后者即本设计"切任务不切文本"；[Rethinking Chunk Size（arXiv 2025）](https://arxiv.org/html/2505.21700v2)与 [Pinecone chunking](https://www.pinecone.io/learn/chunking-strategies) 的分块合理性属**检索**场景，抽取场景引用需谨慎（正是评审警示点） |
| [Structured Outputs for Document Processing](https://generative-ai-newsroom.com/structured-outputs-making-llms-reliable-for-document-processing-c3b6b2baed36) | run-length 分区 JSON 可上 schema 约束解码（比 json_object+自觉更强），seg-v2 实现项 |
| [Grounding in document extraction（PyMuPDF）](https://pymupdf.io/blog/grounding-in-document-extraction) | 输出锚定回可验证源位置——审计要求与我们一致 |

## 5. 迁移与回归路径

1. S0 尾部新增句表（编号+原文坐标），入 unified_raw 契约（edits 同目录，句表作为分区调用的确定性输入）；
2. seg-v2 提示重写（分区+字段 schema），上 grammar/schema 约束解码；
3. S2 定位层简化：句表坐标直读，引文定位仅用于"区间首尾句取证"；
4. S3：coverage/overlap 降为实现断言，facts_quality 保留（区间内容检查仍有意义），quote 检查取消；
5. 规约测试（§8，30–50 件 qwen3.8-max）：分区与正则分段的边界 F1（segment_compare 现成基线 0.839/0.994/0.688 可直接对照）＋歧义率；
6. 重跑 300 试点复测双判据 → 达标后报全量预算回填。

## 待评审确认

1. 句表分区接口方向是否成立（相对"引文列表"的契约变更）；
2. 边界 snap 的规则集（CONCLUSION_MARK 词表）是否需要法律组补词；
3. 字段表形态"跳过分区调用"是否采纳（该形态 ~1,100 件，省 1/3 调用）；
4. 证据降级为"区间首尾句原文"是否接受（原契约要求逐字引文定位，句表坐标下等价更强）。
