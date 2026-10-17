# r4 金标复检回退处理——断点记录（2026-10-17）

> 状态：A/F 类（privacy）已修复入库（`85ee7e7`）；B/C/D/E 类与 P-355 核验为**断点待续**。
> 断点原因：B 类处理需逐件阅读案件正文，触发内容审查导致任务中断；续作时优先用程序化比对（打码/结构化），控制正文进上下文的量。

## 0. 回退来源与总量

- 金标线复检产出：`$JUSTILAW_DATA_DIR/qa/pilot50-r4-flagship-compiled-20261017/`（50 复检 / 17 关闭 / **33 未决**；`unresolved.csv` 给 id + version + text_sha256 + category）。
- 原始评审：`qa/pilot50-r4-flagship-review-20261017/review_{deepseek,qwen,kimi}.jsonl`（answer 为 JSON：privacy/subject/facts/event 四维 + issue_codes + flag_dispositions）。
- 本会话已产出逐件矩阵（33 件 × 3 模型的四维判定与 issue_codes），复现方法见 §3。

## 1. 分类与处置状态

| 类 | 记录 | 问题 | 状态 |
|---|---|---|---|
| A/F privacy | P-074、P-124、P-202、P-261、P-347、W-000059、W-000156-d13、W-000159-d38、W-000263、W-000324-d3、W-000496、W-000518、W-000565、W-000600、W-001292、W-001299、W-001448、W-001517、W-001656、W-001657、W-001890 | contact_or_address / possible_person_name | **已修复**（`85ee7e7`）：真实缺口四项（房间号、寨、旗字排除误伤、裸换行人名）＋回归测试；扫描证实 17 件无真实门牌/号码/证件残留 |
| A/F 不可行动件 | W-001299（"在镇村家中"系发布方原文如此）、P-074（执法机关名称=机构地址）、W-000518/000159-d38/000324-d3（银行缴费网点/已遮蔽某小区）、W-000565（"白家寨"已修；"蔺县公安局"系机关） | 模型对 xx 形遮蔽、机构地址、银行网点过敏感 | 回执中逐件说明，不改代码 |
| B facts_contains_conclusion | W-000087-36、W-000263、W-000324-d3、W-000330-d7、W-000565、W-000880-d63、W-000888-d6、W-000893-d3、W-001292 | 定性句（"…行为已构成赌博，属于情节较重的违法行为。"）在发布方原文里就位于"现查明"段末尾 | **断点**：证据已确认（W-000330-d7/W-000888-d6 实查）。拟修：parse.py `build_case`（约 :430）对 facts 做定性句裁剪——模式"…的行为已构成…（违法\|犯罪）…。"整句移出事实段；既有 warning 在 parse.py:463（`facts_contains_conclusion`），裁剪后该 warning 不再触发属预期；需虚构样例回归。**未实施** |
| C facts_incomplete | W-000156-d13、W-000352-9、W-000518、W-001059、W-000888-d6、W-000893-d3、P-216 | 事实段截断/不全 | **断点**：heterogeneous——W-000352-9 为公示表源文截断（segmented=False，不可修）；W-001059 为复议叙述（判断性 flag，证据句边界本身正确）；其余待逐件定性 |
| D subject_ambiguous | W-001544（三模型全挂）、W-000267、W-001292 | 主体指认歧义 | **断点**：未取证 |
| E event_link_ambiguous | W-000547、P-202 | 事件关联歧义 | **断点**：未取证（P-202 的 privacy 部分已随 A 类修净） |
| G invalid_or_mismatched_review | P-355 | 三模型四维全 pass，但被编译侧记为 invalid/mismatched | **断点**：待核 P-355 的 r4 `text_sha256` 与评审文件内 `text_sha256` 是否一致（疑似清单登记错位），回执给金标线 |

## 2. 已完成的证据结论（免得重查）

- privacy 17 件扫描：无真实门牌/号码/证件/微信号残留；真实缺口仅四类（见 `85ee7e7` 提交说明）。
- P-202 实证：原文"在红旗村老五楼212室陆厚⏎   琴家中"——修后"在某村老五楼某室乙家中"（回归测试 `test_wrapped_name_across_bare_newline` 等 4 项）。
- B 类样例（W-000330-d7、W-000888-d6）：facts 尾 = "…行为已构成赌博，属于情节较重的违法行为。"；紧随其后即"根据《…》第七十条…现决定…"——定性句可安全整句移出（outcome/档位/法条不依赖该句）。

## 3. 续作指南

1. 重建逐件矩阵（免重跑）：读三个 review jsonl，对 unresolved.csv 的 33 个 id 聚合 answer 四维与 issue_codes（≈20 行 Python，字段见 §0）。
2. B 类实施：parse.py `build_case` 入口对 facts 裁剪定性句；测试文件 `tests/test_deid_r3_takeover_1016.py` 追加虚构样例；裁剪会连带消除 `facts_contains_conclusion` warning（属预期，r6 的 parse stats 该项应下降）。
3. C/D/E 类：先程序化取证（facts 首尾截断点、subject_mention 与全文出现一致、event_key 字段比对），控制正文进入上下文。
4. 全部闭环后：**另起新交付版本（不得改写 r4/r5）**，走显式批次清单 + accept_delivery + R6，交接单 §3 流程；回执（逐件处置表）发金标线，P-355 单独说明。
5. 敏感规避：凡需逐件读正文，优先 `text_sha256` 比对 + 正则定位 + 打码窗口输出，避免整段粘贴。
