# 旗舰模型首批 50 件运行手册

状态（2026-10-17）：r4 候选 50 件未冻结，模型仲裁标注 0/500。r4 同哈希交付已由引擎验收为「通过」（1404 条 error 0）。三模型复检的 17/50 仅是额外试验门槛的通过数，**不是标注放行数**。本手册第 3–5 步的三模型安全全票门槛已撤销为正式流程要求；模型发现的具体隐私疑点交来源线核查，未核清的具体记录暂缓送模型。正式冻结入口需改按来源验收、哈希与逐件风险处置建立；在入口修正前不运行第 6–8 步真实批次。详见[口径纠正](./annotation-execution-strategy.md)。

## 模型与凭据

| 角色 | 官方模型 ID | 环境变量 | 接口 |
|---|---|---|---|
| A / 安全复检之一 | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` | DeepSeek 官方 API |
| B / 安全复检之一 | `qwen3.8-max` | `DASHSCOPE_API_KEY` | 阿里云百炼；可选 `QWEN_BASE_URL` 为官方 HTTPS 地域端点 |
| C / 安全复检之一 | `kimi-k3` | `DASHSCOPE_API_KEY` | 百炼部署的 Kimi 官方兼容接口 |

模型依据：[DeepSeek API 文档](https://api-docs.deepseek.com/api/list-models/)、[Qwen3.8 Max](https://docs.bailian.console.aliyun.com/en/model-studio/qwen3-8-max)、[Kimi K3](https://help.aliyun.com/zh/model-studio/kimi-k3)。运行时只接受白名单模型和官方端点；响应模型 ID 不一致的记录退回。DeepSeek 是独立提供方，Qwen 与 Kimi 虽为不同模型家族，但共享百炼平台和凭据；这一相关性写入数据卡。小模型和 Ollama 不参与本流程。百炼凭据与端点地域须一致，见[百炼兼容接口说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)。未调用的 GPT 原计划及改用 Kimi 的记录保存在受控目录 `model_policy_change.json`。

## 执行顺序

1. 设置 DeepSeek 与百炼两项环境变量，或用 `--prompt-keys` 临时输入；不要将密钥写进仓库或聊天。运行 `python research/qa/run_flagship_review.py --preflight`，检查三路模型 `configured=true`。无凭据时不发送请求。
2. 用三家旗舰模型和合成案卷先完成接口冒烟、字段格式、证据命中及中断恢复检查。实际源文调用须待 r4 交付主文件 SHA-256 与候选清单仍相同。
   同时运行 `screen_standard_risks.py <candidate_manifest.json> <delivery.jsonl> <output.json>`。开放金额依 schema 1.1.0 记 `max:null`；关键词预警只提示需核对金额归属，不能代替语义判断。
3. 调用 `run_flagship_review.py <candidate_manifest.json> <delivery.jsonl> <record_review_queue.csv> <仓库外新目录>`。脚本逐件落盘三方安全复检；只传本条案卷，不传其他模型结果。支持 `--providers` 分路、`--resume` 续跑、`--retry-invalid` 重试无效行、`--timeout` 与 `--workers` 控制调用。任何请求、格式或语义矛盾都记为无效，不能产生通过回执。
4. 调用 `compile_flagship_review.py <candidate_manifest.json> <record_review_queue.csv> <复检运行目录> <仓库外新目录>`。三方四项均通过、无风险代码、自动信号均一致判为误报且模型 ID 匹配，才生成逐件候选回执；退回项以 ID、版本、哈希和类别单列。若不足 50 件，解决、替换并重新复检，不能让其余记录借此放行。
5. 回执 50/50 且标准冲突已决议后，调用 `freeze_safe_subset.py` 冻结只读子集。冻结 manifest 必须保留来源哈希、回执哈希和“模型复检”性质。
6. 调用 `run_flagship_blind_annotation.py <safe_manifest.json> <pilot50-safe.jsonl> <annotation-guideline.md> <仓库外新目录>`。A/B/C 收到同一协议和本人信息、事实段，互不见对方输出；逐件写原标，失败行不计完成。用 `validate_annotations.py` 对三份原标分别做 50/50 覆盖、类型和证据核验。
7. 调用 `run_flagship_arbitration.py <safe_manifest.json> <pilot50-safe.jsonl> <annotation-guideline.md> <盲标目录> <仓库外新目录>`。C 已落盘的盲标保留；C 后续只看每件的 A/B/C 分歧字段，逐字段返回采纳来源、原因代码或未决。调用失败和未决项不自动补齐。
8. 调用 `assemble_flagship_candidate.py <safe_manifest.json> <pilot50-safe.jsonl> <annotation-guideline.md> <盲标目录> <仲裁目录> <仓库外新目录> <字段口径决议 JSON>`，末项使用[已绑定哈希的字段口径决议](./field-standard-resolution-20261017.json)。脚本确定性地实际复制 A/B/C 被采纳字段、检查所有分歧均裁决、证据在模型输入中的唯一字符偏移以及 `GamblingElements` Pydantic schema。字段口径决议绑定指南 SHA-256、schema 1.1.0 源文件哈希与引擎裁定来源；任一不匹配时产物只叫工作集，`model_adjudicated_completed=0`。

所有带原文和证据的输入、输出目录必须在受控数据区，仓库只存 ID、问题代码、版本、哈希和汇总。营利目的与开放金额以引擎 schema 1.1.0、指南 v0.2 为准；无法按该规则归属的字段保留异常。模型仲裁产物标 `label_origin=model-adjudicated`、`human_review=false`，不能替代 G1.1/G1.2 人工金标。
