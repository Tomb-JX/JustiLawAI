# binding-v1 引擎接入审核（2026-10-26）

审核对象：`codex/seg-v2-design-review` 提交 `8862e3b`，主要为 `research/discretion/unify/binding_service.py`，说明为 `docs/04-plan/2026-10-27-binding-service-v1.md`。冻结产物在 `$DATA/serving/binding-v1/`。本次只读审核及离线推理；未修改 `unify/**`，未接入训练或在线裁量。

## 已验证

- Python 3.14 下 `onnxruntime/tokenizers/numpy/jionlp` 可导入。取 `model-draft-20261026-v3` 的 3 条冻结输入，执行官方 CLI，3/3 产出 JSONL；输出存 `$DATA/engine/binding-service-audit-20261026/outputs.jsonl`。每条均有 4 个字段、服务版本与 artifact manifest 哈希。此烟测只证明能运行，不证明字段正确。
- `supply_packet.build_packet` 会检查提供的 `source_sha256` 与全文一致，检查每个允许句的坐标、文本、facts/meta 来源和不重叠；`binding_service` 启动时检查 manifest 所列产物文件 SHA256。
- H3 报告显示金额三路一致策略覆盖较低；171 条里 141 条至少有一个字段需人工处理。金额、年龄、人数的 H3 结果来自模型投票与 Claude 复核，不是独立真人金标；服务文档也要求全新批次复测。

## 阻止直接接入的缺口

### P0：三路只比较金额值，不比较金额候选或本人归属

`binding_service.py:158–167` 以 `len({proposal.value}) == 1` 判三路一致，然后只取 `softmax/semantic_pair` 的 `candidate_id` 生成证据。构造原文“甲赌资100元，乙赌资100元”，冻结链路与语义路线均指向乙的候选 `Q-other`，pair 路线指向甲的候选 `Q-target`，三路值均为 `amount:100`；实际返回 `binding_status=bound`、`candidate_ids=[Q-target]`。这使“同额不同人”成为假一致，破坏本人赌资字段的接入前提。

**修复验收**：三路对本人字段的同意条件至少包括同一个源候选或可审计的同一本人归属等价类；同值异人必须 `unresolved:relation_ambiguous`。补上述回归测试，并用 H3 及独立批次重新计数 precision/coverage。不可简单将 pair 路线候选覆盖其他路线候选。

### P0：金额键把确切值和开口上界压成同一个值

`evaluate_relation_model_labels.py:50–55` 的 `amount_key` 对 `{min:100,max:100}` 与 `{min:100,max:null}` 均返回 `amount:100`；`binding_service.py` 的金额输出也只给这个字符串。引擎 schema 的 `AmountRange` 明确区分两者，开口数额不能按确切 100 元输入裁量。最小函数探测已复现。

**修复验收**：输出保留结构化 `{min,max}`，三路比较时也区分确切、范围与开口；端点和开口写法必须在本字段原文证据中接地。旧 `amount:100` 不能由引擎适配层猜成 `{100,100}`。

### P1：版本与来源绑定不足

- `MANIFEST.json` 的 `code_revision` 是 `5dc7802`，而本次服务代码在 `8862e3b` 才加入。服务只校验产物文件哈希，没有校验当前服务代码、`engine_root` 下 `normalization.py`/`binding.py` 的哈希；同一 manifest 可配不同推理代码运行。冻结产物版本应绑定实现与权威归一化实现的哈希，或在审计记录中逐次冻结并验证这些哈希。
- `supply_packet.py:168` 验证提供的全文 SHA，但 `view_hash` 在第 173 行仅透传，不核验允许视图内容。接入适配层须重新计算视图哈希并拒收不匹配输入，防止同一全文的视图变动后沿用旧审计身份。
- `binding_service.py:141` 将 `target_id` 写为记录 `id`，而 `supply_packet` 已计算源文加目标人生成的 person ID。若按供应契约的 `target_id` 关联 claim/person，需要改用实际 person ID 并留 record ID 在顶层。

### P1：人数与年龄仍需独立口径检查

`_count` 自动绑定仅在显式人数和姓名名单一致时；`_age` 仅在行为日、生日推导唯一时。策略方向合理，但 H3 的 bound 年龄为 9/10 正确、现场总额 17/18 正确；“bound”不能解释为零错误。人数若采用名单候选，`_count` 回退证据可能只有 `candidate_id/kind=name_list`，没有原文坐标，不能直接落入现有要素证据结构。

## 接入裁定与后续动作

当前只接受**影子推理**：输入可用已冻结的 S1 允许视图，输出单独保存，供四字段诊断和人工复核。不得将 `bound` 自动转换为 `reference_elements`、M4 训练特征或在线裁量输入，也不得把 `unresolved:no_candidate` 一概当“原文未提及”。

后处理线先修两项 P0 并重冻产物；引擎线随后实现适配层，校验版本、全文/视图哈希、字段路径、结构化值、候选和引文坐标，并保留 unresolved 状态。用全新来源批次做字段级独立复核，再决定 4 个字段逐一放行。引擎侧 `normalization.py` 和 `binding.py` 当前均未纳入提交，正式跨工作树部署前需先把这两个权威依赖及测试纳入可复现提交。

相关输入输出：`$DATA/engine/binding-service-audit-20261026/{inputs,outputs}.jsonl`。`$DATA` 为 `D:/02_Dev/Data/justilaw-research`。本次样例不写入代码库，以保留原文数据权限边界。

## 代修进度（2026-10-26）

按负责人指示，引擎线在隔离分支 `codex/binding-service-v1-fix` 代修上述缺口，不覆盖研究工作树。代码已做到：同额不同原文位置转 `relation_ambiguous`；旧 `C-amount-*` 和新 `Q-*` 仅在原文坐标、原文金额文字、结构化数值全相同才视为同一候选；bound 金额保留 `{min,max}`，`amount:100` 与 `amount:100+` 分开；核验全文、允许视图、运行代码、引擎及 E-05 文件哈希；人数的明确值与名单两份依据均携带原文坐标。后处理线测试 217 passed。

新权威产物为 `$DATA/serving/binding-v1.1-47bffae/`，旧 `binding-v1` 不变，所有早期试冻结的 v1.1 目录不用于接入。引擎新增**只读影子审计** `research/eval/audit_binding_service_shadow.py`：核对四字段类型、来源/视图/目标 person ID、manifest 哈希、候选共识及证据坐标；烟测 3/3 通过，改坏目标 ID、视图哈希、引文或金额值均能拒收。影子审计通过仍不是训练或在线裁量放行。

**最终离线复核**：H3 171 条在 `binding-v1.1-47bffae` 下全部通过影子审计（0 来源、坐标、结构错误），自动绑定个人赌资 17、现场总额 19、人数 6、年龄 10；结果见 `$DATA/engine/binding-service-audit-20261026/h3-v1.1-47bffae{.jsonl,-shadow-audit.json,-quality.json}`。与模型投票参照对账：个人赌资 16/16、现场总额 17/18；Claude 双盲复核中可评分的 bound 分别为 3/4、6/7。仍有真实字段语义错判，且 H3 已用于开发，不能作为独立放行依据。工程缺陷已修，训练/在线裁量继续隔离。完整交接见隔离分支 `codex/binding-service-v1-fix` 的 `docs/04-plan/2026-10-26-binding-service-v1-1-engine-handoff.md`。
