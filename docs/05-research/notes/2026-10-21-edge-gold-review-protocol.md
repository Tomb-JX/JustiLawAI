# 下一轮关系边盲标协议（2026-10-21）

> 状态：标注包已经准备，但用户决定暂不逐案复核。本协议和本地工具仅作备选；当前算法实验不把空模板计作金标。

## 目的与样本

用同一批 `train+valid` 允许视图，评价数字候选到**字段角色、当事人、行为事件**的边，并核对年龄推导所需的生日和行为日期。先回放原引擎 `binding.py` 与 E2 规则基线，再对它们的分歧做人工裁决。首批 24 个不同事件：个人赌资分歧 4、现场总额分歧 4、参赌人数分歧 6、年龄操作数 4、确定性随机对照 6。挑战样本经过选取，**不能据此估计总体准确率**。test 40 完全封存。

原 S2 的配对结果在 `docs/05-research/gate-reports/2026-10-21-original-s2-paired-train-valid.json`，只用于选样和后来对比；标注员不得先看它、银标值或规则提示。盲标包的 `blind-cases.jsonl` 只有目标人、允许 facts/meta 视图、带原文坐标的数值/日期候选；模板各有一份供 A/B 独立填写。`manifest.json` 的分层信息也应在标注结束前对标注员隐藏。

同视图配对回放（仍只是与银标值一致）：

| 字段 | 银标有值 | 原 S2 | E2 角色唯一值 | 两者都一致 | 只原 S2 一致 | 只 E2 一致 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 个人赌资 | 53 | 10 | 12 | 8 | 2 | 4 |
| 现场总额 | 62 | 39 | 41 | 38 | 1 | 3 |
| 参赌人数 | 61 | 3 | 32 | 2 | 1 | 30 |
| 年龄 | 59 | 8 | 8 | 8 | 0 | 0 |

原 S2 和 E2 各自执行候选抽取，参赌人数差异特别大也不能直接归结为关系判定。原 S2 使用记录元数据中的行为日期；这不是从文本自动选出的事件日期。分歧表只用于挑出需要人工看边的案例，不能替代边金标。

## 标什么

每条记录先给人物实体和行为事件分配 `T`、`P1`…及 `E1`、`E2`…等本记录内 ID。人物实体需标可见提及的原文起止位置；事件需标支持该事件划分的原文位置。同一人多次出现要合并，同一案件的不同场次不能仅因金额相同合并。`event_membership_edges` 单独回答目标人是否参加该事件；现场总额属于事件，不自动属于每个被拆出的当事人。

对每个候选填写 `quantity_edges`：

- `decision`：`asserted`（原文断言该数值）、`negated`、`not_relevant`、`uncertain`。必须逐候选填写；未填不等于负边。
- `field_role`：`amounts.personal_stake`、`amounts.onsite_stake_total`、`persons.participant_count`、`person.age`、`birth_date`、`behavior_date`、`other_numeric`。若一个数值承担多个角色，用多条边指向同一 `candidate_id`，并写清支持位置。
- `actor_ids`：实际所属人物；可为空表示纯场景量，不能因为目标人在同句就默认填 `T`。共同、分别、人均等分配语义写入 `note`。
- `event_id`：数值所属行为事件；无法区分时标 `uncertain`，不要猜最近的事件。
- `polarity`：`positive`、`negative`、`uncertain`；与数字是否带负号无关。
- `support_spans`：原文 `[start,end)` 坐标，可多段；跨句关系同时引用人物和行为/数值的支持段。

缺失的数值或限定词（如“约”）写进 `missed_candidate_spans`，给出完整原文区间和类型；不要把残缺候选默认为正确 span。年龄与名单人数在 `derived_fields` 填操作类型、操作数候选或新增 span、事件和结果范围；生日只有年/月精度时保留可行区间。名单须标是否完整以及人员是否去重，未能证明完整则 `uncertain`。

只允许使用 `allowed_views`；不得看 decision/review/outcome 来补关系。源文无法判定的人物或事件边记 `uncertain`，与确定的 `negated` 或 `not_relevant` 分开。银标字段存在与否不是真实正负标签。

## 金标门槛与评估

模板是**待填表，不是金标**。本轮用户已决定亲自单人复核，因此完成后标 `single_human_review`，不宣称双人仲裁金标。若后续增加第二位真人独立填写，对候选边、漏候选、场次及推导操作数逐项比较并裁决，才能标 `human_adjudicated_gold`。AI 预填只能标 `model_draft`。无论采用哪种复核，均需原文坐标校验、所有候选显式决定和标注人代号。

评估至少分别报：候选 span 覆盖、给定正确候选的角色/主体/事件边 P/R/F1、完整链可投影字段的准确率与弃判率、年龄操作数与计算、同值异人和跨场次错误。将 `uncertain` 作为弃判而非负例。当前 `evaluate_edge_review.py` 的第一版只计算**同原文候选区间、字段角色且可投影给目标人**的边，并报告原 S2 无法对齐的 span；它还不是完整字段或图的总评估。先在这 24 条做错误定位，再按事件随机抽样扩充独立验证集；训练和阈值选择不能反用同一裁决集。原 S2 和 E2 候选不同，系统级差额不能直接归因于关系模型；做同候选消融时需固定候选并按原文 span 对齐。

## 文件与复现

私有本地包位于工作树 `.tmp-edge-review-20261021/`。`blind-review.html` 是本地交互页，可逐候选填写、自动暂存于浏览器并导出 `single-human-review.jsonl`；也有适合阅读的 `blind-review.md`、结构化 `blind-cases.jsonl`、A/B 空模板和 `manifest.json`。导出后运行 `python research/discretion/unify/validate_edge_review.py --cases .tmp-edge-review-20261021/blind-cases.jsonl --review <导出文件>`，检验记录、候选 ID 和原文坐标；评分入口 `evaluate_edge_review.py` 对未完成的模板会拒绝运行。源文件及私有包哈希在公开的 `docs/05-research/gate-reports/2026-10-21-edge-review-manifest.json`。生成器为 `research/discretion/unify/prepare_edge_review.py`。私有包包含原文片段，未提交到 Git。现阶段没有任何人工边金标，不能报告边 F1 或宣称这 24 条已经标完。
