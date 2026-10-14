# 文献与资料库：赌博案件智能裁量引擎

> 版本 v0.1 · 2026-10-15 · 配套：[引擎方案](../02-design/gambling-discretion-engine.md) · [固定对照与阶段门禁](./sota-baselines-and-gates.md)
>
> 机器可读清单：[`research/papers/manifest.csv`](../../research/papers/manifest.csv)（128 条）。下载：在仓库根目录运行 `python research/papers/fetch_papers.py`，PDF 存在 `research/papers/pdf/`（不入库），校验和记录在 `research/papers/checksums.tsv`。
>
> 2026-10-15 下载结果：123 篇成功；TabPFN v2（Nature）与 Bürkner & Vuorre（SAGE）会拦截脚本，需用浏览器手动下载；Super Learner、Stacked Generalization、ML Test Score 没有公开 PDF，只给出 DOI 或页面链接。

## 0. 收录规则

### 0.1 分级

| 级别 | 含义 | 要求 |
|---|---|---|
| **A 核心** | 直接决定架构，或是[门禁文档](./sota-baselines-and-gates.md)中固定对照的数字来源 | 负责该模块的同学必须精读；改动对应设计前要先复核原文 |
| **B 方法** | 某个模块的具体方法来源或备选方案 | 实现该模块前读相关章节 |
| **C 借鉴** | 不是法律领域，但训练、数据、评测、工程方法值得借鉴 | 按需查阅 |

### 0.2 "选择依据"标签

每条文献都标注了选它的理由，取以下一种或几种：

- **【SOTA】** 截至 2026-10 在该任务上报告的最好结果，或最新一代方法
- **【基准】** 提供我们要复现或对照的公开数据集、协议或数字
- **【奠基】** 该方向公认的标准做法，后续工作普遍沿用
- **【警示】** 提供失败模式或反面证据，用来设计防护措施
- **【工程】** 有成熟开源实现，可以直接使用

### 0.3 核实方式

- **身份核实**：所有 arXiv 条目都在 2026-10-15 通过 arXiv 官方 API（`export.arxiv.org/api/query`）逐条核对编号与标题，manifest 中的链接固定了版本号（如 `v3`）。
- **数字核实**：本文和门禁文档中引用的数字，标 ✅ 的是直接从原文表格读取的；标 ⚠️ 的来自二手转述或厂商自报，使用前必须复核原文。
- **会议信息**：不确定的发表场合一律写 arXiv，不猜测。

---

## 1. 法律判决与量刑预测（M3 / M4 的直接来源）

| 文献 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **MSR²** Multi-Source Retrieval and Reasoning for Legal Sentencing Prediction | arXiv 2602.04690 (2026)；代码 Apache-2.0 | A | 【SOTA】【基准】截至目前公开的量刑预测最好结果：Qwen3-8B 经 GRPO 训练，CAIL2018 区间准确率 46.18 ✅，CJO22 44.29 ✅ | 刑事锚点 A2 的对照数字；四源检索（含 200 份地方量刑文件）的设计依据；扩展阶段 RL 奖励设计（0.8 结果 + 0.2 过程）的参考 |
| **PLJP** Precedent-Enhanced LJP with LLM and Domain-Model Collaboration | EMNLP 2023 | A | 【基准】【奠基】提出 CJO22（2022 年后案件，规避预训练数据泄漏）和"小模型给候选、LLM 读判例"的协作范式 | 冻结基线 B2 的实现方式；CJO22 用作抗污染测试集；数据划分沿用其协议 |
| **ADAPT** Enabling Discriminative Reasoning in LLMs for LJP | EMNLP 2024 Findings | A | 【SOTA】Ask–Discriminate–Predict 三步判别式推理，在易混罪名上提升最大 | M3 开放性概念判断的推理流程；冻结基线 B3 |
| **GLARE** Agentic Reasoning for LJP | arXiv 2508.16383 (2025) | A | 【SOTA】候选扩展、判例推理、法律检索三个可调用模块；消融显示去掉判例推理后罪名准确率从 89.7 降到 80.0 ✅ | M3 中类案作为推理证据；"判例 + 离线生成的推理路径"作为上下文示例 |
| **SMS** Adaptive Sentencing Prediction with Guaranteed Accuracy and Legal Interpretability | arXiv 2505.14011 (2025) | A | 【SOTA】按量刑流程建模（起点 + 情节增量 × 调节系数，截断到法定区间），小数据下胜过 CatBoost（重伤组 91.34 vs 87.36 ✅） | M4 专家 A 的结构先验："法律结构 + 学参数 + 饱和截断" |
| **RLJP** LJP via First-Order Logic Rule-enhanced with LLMs | arXiv 2505.21281 (2025) | A | 【SOTA】规则用一阶逻辑表示，再用易混案例做对比学习修正 | M2 规范层的表示方式；"规则可被数据修正"的论据 |
| **PDP-Bench** The Cases LJP Never Sees: Prosecution Decision Prediction | arXiv 2605.28464 (2026) | A | 【警示】【基准】4,630 份不起诉决定；LLM 在"是否追责"上明显差于 LJP，**仅用结果奖励的 RLVR 学不到可泛化的区分能力** | 直接对应行政案件的"不予处罚 / 不构成违法"边界：该类别单独设门禁；扩展阶段 RL 必须加过程奖励 |
| Legal Syllogism Prompting | arXiv 2307.08321 (2023) | B | 【奠基】三段论提示（大前提法条、小前提事实、结论） | M6 说理格式 |
| LADAN: Distinguish Confusing Law Articles | ACL 2020 | B | 【奠基】易混法条的图区分方法 | M3"提供条件 vs 开设赌场"等易混定性的思路 |
| Charge-Based Prison Term Prediction | EMNLP 2019 | B | 【奠基】按罪名分别预测刑期，提升准确率与可解释性 | M4 分层目标（先定性再裁量）的依据 |
| Rethinking LJP in a Realistic Scenario | arXiv 2410.10542 (2024) | B | 【基准】只给事实、法条、判例的现实设定评测 | 端到端评测协议参考 |
| Evaluating Test-Time Scaling LLMs for Legal Reasoning | arXiv 2503.16040 (2025) | B | 【基准】o1、DeepSeek-R1 等推理模型在 CAIL2018 上的表现 | 判断"换更强推理模型"能带来多少提升，避免盲目堆模型 |
| JurisMMA / Agents on the Bench / AgentsCourt | arXiv 2601.12815 / 2412.18697 / 2403.02959 | B | 【SOTA】多智能体模拟庭审 | 仅作 M6 说理的备选方案，暂不采用（对数值裁量的提升未被证明） |
| DISC-LawLLM | arXiv 2309.11325 (2023) | A | 【奠基】法律三段论 SFT 数据构造 + 检索模块；公开 30 万条 SFT 数据 | 说理 SFT 数据格式参考 |
| 法律 LLM 综述 When LLMs Meet Law | arXiv 2507.07748 (2025) | B | 【奠基】2025 年综述，覆盖判决预测、检索、伦理 | 新成员入门读物 |

## 2. 法律基准与数据集（固定对照的数据来源）

| 数据集 / 基准 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **CAIL2018** | arXiv 1807.02478 / 1810.05851；<https://github.com/thunlp/CAIL> | A | 【基准】中文 LJP 标准数据集，含赌博罪、开设赌场罪；刑期评分采用对数距离分档 | 刑事锚点 A2 的数据；刑期评分公式见门禁文档 §3 |
| **LawBench** | EMNLP 2024；<https://github.com/open-compass/LawBench> | A | 【基准】20 个任务、51 个模型的公开分数；含命名实体识别（2-6）、事件检测（2-9）、犯罪金额计算（3-7） | 抽取器锚点 A1：GPT-4 的公开分数作为下限 ✅ |
| **CLaw** | EMNLP 2025 Findings | A | 【警示】【基准】306 部国家法律细化到项；**多数 LLM 不能准确复述法条** | M6 法条一律从规范库取原文的依据；法条精确匹配设为红线 |
| **Hallucination-Free?**（斯坦福） | J. Empirical Legal Studies；arXiv 2405.20362 | A | 【警示】Lexis+ AI、Westlaw AI-Assisted Research、Ask Practical Law AI 等商用法律 RAG 工具的幻觉率在 17%–33% 之间 ✅ | M6 幻觉率门禁的外部参照 |
| Large Legal Fictions | J. Legal Analysis 2024 | B | 【警示】系统刻画法律幻觉的类型 | M6 校验器的错误分类 |
| CJO22 | 随 PLJP 发布（百度网盘） | A | 【基准】2022 年后的新案件，可检验预训练数据泄漏 | 刑事锚点的抗污染测试集 |
| LexEval | NeurIPS 2024 D&B | B | 【基准】中文法律能力分层评测 | 通用法律能力回归检查 |
| LAiW | arXiv 2310.05620 | B | 【基准】含刑期三分类 | 备用对照 |
| JuDGE | SIGIR 2025 | B | 【基准】从事实生成完整裁判文书，多源 RAG 有提升但仍有很大差距 | 处罚决定书起草（PRD §4.2）的评测参考 |
| LEVEN | ACL 2022 Findings；<https://github.com/thunlp/LEVEN> | B | 【基准】中文法律事件检测 | 抽取器预训练与锚点（LawBench 2-9 / 2-10 来自它） |
| MultiJustice | arXiv 2507.06909 | B | 【基准】多被告、多罪名 | 共同违法、多名行为人案件的划分与评测参考 |
| LegalAgentBench | arXiv 2412.17259 | B | 【基准】法律智能体多步工具调用评测 | 若做智能体编排，作为参考 |

## 3. 类案检索（M5）

| 文献 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **LeCaRDv2** | arXiv 2310.17609；<https://github.com/THUIR/LeCaRDv2> | A | 【基准】800 个查询、5.5 万候选；相关性按定性、处罚、程序三个维度标注 | 检索锚点 A3 的数据；要素对齐打分按这三个维度设计 |
| **KELLER** | arXiv 2406.19760 (2024) | A | 【SOTA】用法律知识把案件改写为"罪名–事实"子事实再检索；LeCaRDv2 MAP 68.29、NDCG@10 87.61 ✅（微调设定，160 个测试查询） | 检索锚点 A3 的上限参照；"按要件重写案情"可直接用于 M5 |
| **SAILER** | SIGIR 2023；<https://github.com/CSHaitao/SAILER> | A | 【SOTA】【工程】结构感知的法律预训练检索模型；LeCaRDv2 MAP 60.62、NDCG@10 81.41 ✅ | 检索锚点 A3 的必达线；可作为召回模型之一 |
| **BGE-M3** | ACL 2024 Findings | A | 【工程】平台已在用；稠密 + 稀疏 + 多向量 | 召回基线 |
| **Qwen3 Embedding / Reranker** | arXiv 2506.05176 (2025) | A | 【SOTA】Qwen3-Reranker-8B 在 CMTEB-R 上 77.45，bge-reranker-v2-m3 为 72.16 ⚠️（厂商自报） | 重排器候选：必须在我们的数据上与 bge-reranker 对比后再选 |
| mGTE | EMNLP 2024 Industry | B | 【工程】gte-multilingual-reranker-base（0.3B）在 CMTEB-R 上 74.08 ⚠️，体积小 | 本机 8GB 显存下的轻量重排候选 |
| Reciprocal Rank Fusion | SIGIR 2009 | B | 【奠基】混合检索结果融合的标准做法，无需调参 | BM25 + 稠密召回的融合 |
| Lost in the Middle | TACL 2024 | B | 【警示】长上下文中间位置的信息容易被忽略 | M3 放入类案时把最相关的放在首尾 |

## 4. 要素抽取与受限解码（M1）

| 文献 / 工具 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **Let Me Speak Freely?** | EMNLP 2024 Industry | A | 【警示】严格的格式约束（如 JSON 模式）会降低 LLM 的推理表现 | M1 采用"先自由推理、再受限输出"两步法；门禁要求对比约束与不约束两种方式 |
| GoLLIE | ICLR 2024 | B | 【SOTA】把标注指南写进提示（代码化 schema），零样本抽取明显提升 | 要素本体的字段定义直接附上标注指南原文 |
| XGrammar | MLSys 2025 | B | 【工程】高效的结构化生成引擎（vLLM、SGLang 默认后端） | 若从 Ollama 迁到 vLLM，用它做受限解码 |
| Outlines | arXiv 2307.09702 | B | 【奠基】【工程】基于有限状态机的受限生成 | 备选 |
| JSONSchemaBench | arXiv 2501.10868 (2025) | B | 【基准】比较各受限解码框架的覆盖率与正确率 | 选择受限解码框架的依据 |
| LangExtract（Google） | <https://github.com/google/langextract>，Apache-2.0，2025 | B | 【工程】每个抽取值都映射回原文的字符区间，支持 Ollama | M1 证据定位的现成实现，或作为对照 |
| SelfCheckGPT | EMNLP 2023 | B | 【奠基】多次采样的一致性可以检测幻觉 | M1 关键字段多次采样投票、标记低置信 |
| Self-Consistency | ICLR 2023 | B | 【奠基】多条推理路径投票 | M1、M3 的采样投票 |

## 5. 裁量模型：表格学习、有序回归、贝叶斯分层（M4）

| 文献 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **TabPFN v2** | Nature 2025 | A | 【SOTA】小样本表格数据的基础模型，在 1 万样本以内的数据上超过调过参的 GBDT 集成 ⚠️（PDF 待手动下载后核对） | M4 的研究对照（冻结基线 B6 选用许可更宽松的 TabICLv2） |
| **TabICLv2** | ICML 2026；arXiv 2602.11139；<https://github.com/soda-inria/tabicl> | A | 【SOTA】【工程】开源权重，BSD-3-Clause；在 TabArena 与 TALENT 上不调参即超过调参 + 集成 + 真实数据微调的 RealTabPFN-2.5（✅ 已读原文摘要，属作者自报） | 冻结基线 B6 的首选（许可更宽松） |
| **TabArena** | arXiv 2506.16791 | A | 【基准】持续更新的表格学习排行榜，规范了调参与评测协议 | M4 模型选择流程参照其协议（交叉验证、调参预算、Elo） |
| TabPFN-2.5 / TabPFN-3 / TabPFN-3.5 | arXiv 2511.08667 / 2605.13986 / 2609.17895 | B | 【SOTA】⚠️ 厂商报告：TabPFN-3 系列在 TabArena 各视图排名第一；2.5 起商用需授权 | 只用于研究对照，不进入产品依赖 |
| Mitra-v2 | arXiv 2609.04540 (2026) | B | 【SOTA】⚠️ 回归任务在 TabArena 一小时协议下排名第一 | 罚款数额（回归）的备选对照 |
| TabM | ICLR 2025 | B | 【SOTA】参数高效集成的表格深度模型 | 备选专家 |
| LightGBM / XGBoost / CatBoost | NeurIPS 2017 / KDD 2016 / NeurIPS 2018 | B | 【奠基】【工程】GBDT 三大实现；LightGBM 支持单调约束 | 专家 B、冻结基线 B5 |
| Deep Lattice Networks | NeurIPS 2017 | B | 【奠基】可保证部分单调的模型 | 单调性需求的备选实现 |
| **Bayesian Workflow** | arXiv 2011.01808 (Gelman 等) | A | 【奠基】贝叶斯建模的标准流程：先验预测检查、后验预测检查、模型比较 | 专家 A 必须按此流程，每一步留存图表作为门禁证据 |
| Simulation-Based Calibration | arXiv 1804.06788 | B | 【奠基】检验贝叶斯推断实现是否正确 | 专家 A 上线前的推断正确性检验 |
| NUTS / NumPyro | JMLR 2014 / arXiv 1912.11554 | B | 【工程】HMC 自适应采样与实现 | 专家 A 的推断引擎 |
| Ordinal Regression Models in Psychology（Bürkner & Vuorre） | AMPPS 2019 | B | 【奠基】累积、序贯、相邻类别三类有序模型的对比教程 | 拘留天数有序模型的选型 |
| CORAL / CORN | PRL 2020 / PAA 2023 | B | 【奠基】秩一致的神经有序回归 | 若专家采用神经网络，用它保证累积概率单调 |
| Stacked Generalization / Super Learner | Neural Networks 1992 / SAGMB 2007 | C | 【奠基】交叉拟合的堆叠，理论上不劣于最好的单个模型 | 三专家融合必须用交叉拟合（out-of-fold）预测来学权重，防止泄漏 |
| Deep Ensembles | NeurIPS 2017 | C | 【奠基】集成可显著改善不确定性估计 | 多种子集成 |

## 6. 校准与共形预测（M4 区间、M3 概率）

| 文献 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| **Gentle Introduction to Conformal Prediction** | FnT ML | A | 【奠基】共形预测标准教材 | 团队统一术语与实现 |
| **APS** Classification with Valid and Adaptive Coverage | NeurIPS 2020 | A | 【奠基】自适应预测集 | 预测集的基础算法 |
| **Conformal Prediction Sets for Ordinal Classification**（Dey 等） | NeurIPS 2023 | A | 【SOTA】单峰分布 + APS → 连续的有序预测集 | 拘留天数预测集；与 Ω 合法区段求交 |
| **Conformal Prediction With Conditional Guarantees** | arXiv 2305.12616 | A | 【SOTA】在指定分组上给出条件覆盖保证 | 地域 × 档次分组覆盖（替代/补充 Mondrian） |
| **On Calibration of Modern Neural Networks** | ICML 2017 | A | 【奠基】温度缩放；ECE 指标 | M3 概率与 M4 档次概率的校准；ECE 计算方式 |
| Ordinal CP（RPS 非一致性分数） | UAI 2026 | B | 【SOTA】基于 RPS，按构造得到以中位数为中心的连续集合 | 与 Dey 方法对比，取集合更小者 |
| Ordinal CP（FWER 版） | arXiv 2404.16610 | B | 【SOTA】同时给出边际与类别条件覆盖 | 备选 |
| Ordinal CP 医学分级应用 | MICCAI 2022 | B | 【工程】有序共形在严重程度分级上的落地 | 实现参考 |
| RAPS | ICLR 2021 | B | 【奠基】正则化 APS，集合更小更稳定 | 对照 |
| CQR | NeurIPS 2019 | B | 【奠基】分位数回归 + 共形 | 罚款数额（连续量）的区间 |

## 7. 可溯源、幻觉检测与解释（M6）

| 文献 | 出处 | 级别 | 选择依据 | 我们怎么用 |
|---|---|---|---|---|
| ALCE: Generate Text with Citations | EMNLP 2023 | B | 【基准】引用召回率与精确率的评估方法 | 说理中每条引用的评估 |
| FActScore | EMNLP 2023 | B | 【奠基】把长文本拆成原子事实逐条核验 | 说理事实支持率指标 |
| Chain-of-Verification | ACL 2024 Findings | B | 【奠基】生成后自我核验 | 说理校验失败时的重写流程 |
| RAGAS | EACL 2024 Demo | B | 【工程】RAG 忠实度、相关性指标 | 开发期快速评估（不作门禁依据） |
| **Judging LLM-as-a-Judge** | NeurIPS 2023 D&B | B | 【警示】LLM 评审存在位置、冗长、自我偏好等偏差 | LLM 评审进入门禁前，必须先与法律组人工评分校准一致 |
| SHAP | NeurIPS 2017 | B | 【奠基】基于博弈论的特征归因 | 专家 B 的归因；与 M6 反事实结果交叉检验 |
| Counterfactual Explanations（Wachter 等） | Harvard JOLT 2018 | B | 【奠基】"要改变结论，最少需要改变什么" | M6 情节影响与偏离度预警的解释形式 |
| Unfaithful CoT（Turpin 等） | NeurIPS 2023 | B | 【警示】思维链不一定反映模型真实的决策依据 | 解释一律由模型重算得到，不采信 LLM 自述 |
| Counterfactual Fairness | NeurIPS 2017 | B | 【奠基】改变受保护属性，预测不应改变 | 不变性测试的理论依据 |

## 8. LLM 训练方法（C 级借鉴：抽取器 SFT、M3 推理、扩展阶段 RL）

| 文献 | 出处 | 选择依据 | 借鉴点 |
|---|---|---|---|
| LoRA / QLoRA / DoRA | ICLR 2022 / NeurIPS 2023 / ICML 2024 | 【奠基】【工程】参数高效微调；QLoRA 让 8GB 显存也能跑小规模实验 | 抽取器 SFT 的默认方案 |
| **LoRA Learns Less and Forgets Less** | TMLR 2024 | 【警示】LoRA 学得少但遗忘也少 | 门禁中加入"通用能力回归 ≤ 2 分"的检查 |
| **LIMA** | NeurIPS 2023 | 【奠基】约 1000 条高质量数据即可完成对齐 | 金标数据宁少勿脏；300–500 条高质量标注优先于大量低质量数据 |
| DEITA | ICLR 2024 | 【SOTA】按复杂度、质量、多样性自动筛选指令数据 | 教师模型预标注数据的筛选 |
| **STaR** | NeurIPS 2022 | 【奠基】只保留推出正确答案的推理链来迭代训练；答错时给出答案"反推"推理 | 用已知处罚结果反推说理，构造 M3/M6 的训练数据 |
| Distilling Step-by-Step | ACL 2023 Findings | 【奠基】让小模型同时学习标签和推理理由，所需数据更少 | 教师模型 → 9B 抽取器的蒸馏方式 |
| RFT（拒绝采样微调） | arXiv 2308.01825 | 【奠基】多次采样，只用答对的样本做 SFT | M3 SFT 数据构造 |
| DPO | NeurIPS 2023 | 【奠基】无需奖励模型的偏好优化 | 法律组对说理做两两偏好标注后可用 |
| GRPO（DeepSeekMath）/ DeepSeek-R1 | arXiv 2402.03300 / Nature 2025 | 【奠基】组内相对优势、无价值网络的 RL；可验证奖励 | 扩展阶段 RL 的基础算法 |
| DAPO / Dr. GRPO / GSPO | arXiv 2503.14476 / COLM 2025 / arXiv 2507.18071 | 【SOTA】分别修正 GRPO 的熵塌缩与截断、长度偏差、token 级重要性比带来的不稳定 | 若做 RL，在三者中选一，不直接用原始 GRPO |
| **Rubrics as Rewards** | ICLR 2026 | 【SOTA】把多维评分细则作为奖励，用于没有唯一正确答案的领域 | 法律组写的情节分析评分细则直接作为过程奖励（PDP-Bench 已证明单靠结果奖励不够） |
| Let's Verify Step by Step（PRM） | ICLR 2024 | 【奠基】过程监督优于结果监督 | 同上 |
| Search-R1 | COLM 2025 | 【奠基】在推理中调用检索的 RL 训练（MSR² 基于它） | 若 M3 做检索交错推理的 RL |
| verl / LlamaFactory | EuroSys 2025 / ACL 2024 Demo | 【工程】RL 与 SFT 训练框架（MSR² 用 verl） | 云 GPU 上的训练框架 |
| Model Soups | ICML 2022 | 【奠基】平均多个微调模型的权重，不增加推理成本就能提升精度与鲁棒性 | 多个超参训练的 LoRA 做权重平均 |
| Optuna | KDD 2019 | 【工程】超参搜索 | 统一调参预算，所有对照方法给同样的预算 |

## 9. 数据质量、弱监督与合成数据（C 级借鉴）

| 文献 | 出处 | 选择依据 | 借鉴点 |
|---|---|---|---|
| **Confident Learning（cleanlab）** | JAIR 2021 | 【奠基】【工程】自动找出疑似标错的样本 | P1 门禁：标签错误率审计 |
| Dataset Cartography | EMNLP 2020 | 【奠基】按训练动态把样本分成易学、难学、模糊三类 | 找出"模糊"案例交给法律组复核 |
| Snorkel | VLDB 2018 | 【奠基】用多个弱规则合成训练标签 | 规范库门槛可作为弱标注函数，给未标注案例打初始标签（只用于训练，不作金标） |
| Active Learning Survey（Settles） | Tech Report 2009 | 【奠基】不确定性采样等主动学习策略 | 选择最值得法律组标注的案例 |
| Self-Instruct | ACL 2023 | 【奠基】用模型自生成训练数据 | 合成案情生成方法 |
| **The Curse of Recursion** | Nature 2024 | 【警示】反复用生成数据训练会导致模型崩溃 | 合成数据只用于抽取器鲁棒性训练，比例设上限，且不作类案、不作裁量标签 |

## 10. 评测方法学与防漂移治理（C 级借鉴，门禁文档的方法依据）

| 文献 | 出处 | 选择依据 | 借鉴点 |
|---|---|---|---|
| **CheckList** | ACL 2020 最佳论文 | 【奠基】最小功能测试、不变性测试、方向性测试三类行为测试 | 单调性 / 不变性 / 变形测试套件的组织方式 |
| **Reusable Holdout**（Dwork 等） | Science 2015 / NeurIPS 2015 | 【奠基】反复查看测试集会让测试集过拟合 | 封存测试集，限制查看次数 |
| **Leakage and the Reproducibility Crisis** | Patterns 2023 | 【警示】8 类数据泄漏的分类法；在 17 个领域找到受泄漏影响的论文共 329 篇 ✅（arXiv v1 摘要） | 门禁中的泄漏检查清单 |
| Koehn 2004 / Dror 2018 | EMNLP 2004 / ACL 2018 | 【奠基】配对自助法显著性检验；NLP 显著性检验选择指南 | "显著优于"的统一判定方法 |
| WILDS | ICML 2021 | 【基准】时间、地域等真实分布偏移下的评测 | 时间外推、地域外推测试集 |
| Shortcut Learning | Nature MI 2020 | 【警示】模型会利用数据中的捷径 | 变形测试：改写事实表述，结论不应改变 |
| HELM | TMLR 2023 | 【奠基】多指标、多场景的整体评测 | 不以单一指标判定好坏 |
| REFORMS | Science Advances 2024 | 【奠基】基于机器学习的科研报告规范清单 | 结题评测报告按其清单填写 |
| Model Cards / Datasheets for Datasets | FAT* 2019 / CACM 2021 | 【奠基】模型卡、数据卡 | 每个发布版本附模型卡与数据卡 |
| Hidden Technical Debt / ML Test Score | NeurIPS 2015 / IEEE BigData 2017 | 【奠基】ML 系统的技术债与生产就绪评分表 | 回归测试与上线检查清单 |

---

## 11. 开源代码与数据

| 名称 | 地址 | 许可 / 说明 | 用途 |
|---|---|---|---|
| CAIL2018 | <https://github.com/thunlp/CAIL> | 数据较大，按 `.gitignore` 规则不入库 | 刑事锚点 |
| PLJP + CJO22 | <https://github.com/wuyiquan/PLJP> | 数据走百度网盘；仓库未标许可 | B2 基线、CJO22 |
| MSR² | <https://github.com/cjj826/MSR2> | Apache-2.0；基于 verl + Search-R1 | 刑事锚点复现、RL 参考 |
| LawBench | <https://github.com/open-compass/LawBench> | 含评测脚本 | 抽取器锚点 A1 |
| LeCaRDv2 | <https://github.com/THUIR/LeCaRDv2> | — | 检索锚点 A3 |
| SAILER | <https://github.com/CSHaitao/SAILER> | — | 检索锚点 A3 |
| LEVEN | <https://github.com/thunlp/LEVEN> | — | 抽取预训练 |
| JuDGE | <https://github.com/oneal2000/JuDGE> | — | 文书生成评测 |
| TabICL | <https://github.com/soda-inria/tabicl> | BSD-3-Clause（已读 LICENSE 文件） | B6 基线 |
| TabPFN | <https://github.com/PriorLabs/TabPFN> | 代码 Apache-2.0；据报道 2.5 起的模型权重商用需授权 ⚠️ | 研究对照 |
| LangExtract | <https://github.com/google/langextract> | Apache-2.0 | M1 证据定位 |
| MAPIE / crepes | <https://github.com/scikit-learn-contrib/MAPIE> / <https://github.com/henrikbostrom/crepes> | BSD-3-Clause | 共形预测实现 |
| cleanlab | <https://github.com/cleanlab/cleanlab> | Apache-2.0 | 标签错误审计 |
| NumPyro / LightGBM | <https://github.com/pyro-ppl/numpyro> / <https://github.com/lightgbm-org/LightGBM> | Apache-2.0 / MIT | 专家 A / B |
| verl / LLaMA-Factory | <https://github.com/verl-project/verl> / <https://github.com/hiyouga/LlamaFactory> | Apache-2.0 | 训练框架 |
| CheckList | <https://github.com/marcotcr/checklist> | MIT | 行为测试 |

## 12. 规范性文件（由法律组取得官方原文后入规范库）

| 文件 | 目前掌握的来源 | 状态 |
|---|---|---|
| 《治安管理处罚法》（2025 修订，2026-01-01 施行）第十六、二十至二十三、八十二条 | 新华网全文 <https://www.news.cn/legal/20250627/c1e6a443860a4606b98fc23496e56c8d/c.html> | 已读，待对照国家法律法规数据库 |
| 《治安管理处罚法》（2012 修正）第七十条 | — | 待取原文 |
| 《行政处罚法》第三十七条（从旧兼从轻） | — | 待取原文 |
| 公通字〔2005〕30 号（赌资认定） | 行政复议决定书中的引用 | 待取原文 |
| 两高 2005 赌博刑事司法解释；2010 网络赌博意见；2014 赌博机意见；2020 跨境赌博意见 | — | 待取原文 |
| 目标省份的公安行政处罚裁量基准（如晋公通字〔2022〕82 号、湘公发〔2022〕6 号、云公规〔2024〕1 号、皖公通〔2023〕17 号、浙公通字〔2021〕12 号、沪公行规〔2023〕5 号） | 二手汇编 | 选定目标省后取原文 |
| 法发〔2022〕33 号（人工智能司法应用） | <https://www.court.gov.cn/fabu/xiangqing/382461.html> | 合规依据 |
| 国办发〔2022〕27 号（行政裁量权基准） | — | 待取原文 |

## 变更日志
| 日期 | 版本 | 变更 | 作者 |
|---|---|---|---|
| 2026-10-15 | v0.1 | 初版：128 条文献（A 33 / B 56 / C 39），全部经 arXiv API 核对；附开源代码与规范性文件清单 | 模型组 |
