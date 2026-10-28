# JustiLawAI API 契约（前端 ⇆ 后端）

> 版本 v1.0（§3.11、§3.12 由引擎线先实现后补契约，待前端组评审） · 2026-10-28（v0.6 · 2026-10-22）
>
> 本文档是前后端对接的**唯一依据**：任何接口变更必须先修改本文档、双方评审通过后再实现，并记录到文末变更日志。前端将依据本文档先行 Mock 开发。

## 1. 通用约定

- **Base URL**：`/api/v1`
- **鉴权**：所有接口均需请求头 `Authorization: Bearer <access_token>`，token 由 **Logto**（OIDC）签发，详见 §1.3
- **Content-Type**：`application/json`（文件上传为 `multipart/form-data`）
- **响应包**（所有 REST 接口统一）：

```json
{ "code": 0, "message": "ok", "data": { } }
```

- `code = 0` 成功；非 0 为业务错误，HTTP 状态码同时体现类别
- **错误同样走响应包**：`{ "code": 40400, "message": "…", "data": null }`。没有显式业务码的 HTTP 错误按 `HTTP 状态 × 100` 生成（如 400 → 40000），参数校验失败为 42200，未捕获异常为 50000
- **偏移分页**：请求 `?page=1&pageSize=20` → `data: { "list": [...], "total": 100 }`
- **游标分页**（消息历史）：请求 `?cursor=m_xxx&limit=50` → `data: { "list": [...], "next_cursor": "m_yyy 或 null" }`

### 1.1 错误码

| HTTP | code | 含义 |
|---|---|---|
| 400 | 40000 | 请求不合法（如禁用自己、删除内置供应商） |
| 401 | 40100 | 未登录 / token 失效（前端跳登录页） |
| 403 | 40300 | 无权限 / 账号已禁用 |
| 404 | 40400 | 资源不存在 |
| 422 | 42200 | 参数校验失败（message 携带字段级详情） |
| 429 | 42900 | 请求限流 |
| 500 | 50000 | 服务器内部错误 |
| 500 | 50001 | 模型推理超时 / 失败 |

### 1.2 ID 规范

带类型前缀的短 ID，便于日志排查：`u_` 用户、`c_` 会话、`m_` 消息、`a_` 智能体、`w_` 工作流、`d_` 知识库、`doc_` 文档、`ch_` 分段、`f_` 文件。

### 1.3 鉴权（Logto OIDC）

注册、登录、找回密码、社交登录全部由 Logto 托管，**后端不再实现账号密码接口**。

| 项 | 值 |
|---|---|
| Issuer | `https://oglnok.logto.app/oidc` |
| JWKS | `https://oglnok.logto.app/oidc/jwks` |
| Audience（`aud`） | 见下方"鉴权模式" |
| 签名算法 | ES384 / ES256 / RS256（以 JWKS 返回为准） |

**鉴权模式**（后端按环境变量自动选择）：

| 模式 | 后端配置 | 前端发送的 Bearer | `aud` 校验值 |
|---|---|---|---|
| resource | `LOGTO_ENDPOINT` + `LOGTO_API_RESOURCE` | 面向 API Resource 的 access token（前端配 `VITE_LOGTO_RESOURCE`） | API Resource 标识 |
| idtoken | `LOGTO_ENDPOINT` + `LOGTO_APP_ID` | ID Token（`VITE_LOGTO_RESOURCE` 留空时前端自动改发） | SPA 应用 App ID |
| 本地 | 不配 `LOGTO_ENDPOINT` | 不校验 | 不校验；所有请求视为本地管理员 |

**单机模式（前端）**：前端启动时先调 `GET /health`（不需要鉴权）。`auth_enabled=false` 时跳过 Logto 登录，以"本地用户"（管理员）身份直接进入，同一份前端构建既可公网部署也可单机使用。单机模式没有任何访问控制，只能监听 `127.0.0.1`。

idtoken 模式用于 Logto 免费版无法创建 API Resource 的情况。签名、`iss`、`aud`、`exp` 一样全部校验，代价是 ID Token 本身面向客户端，只适合小规模部署。升级 Pro 后补上 `LOGTO_API_RESOURCE` 就切回 resource 模式。

后端对每个请求：
1. 用 JWKS 校验 JWT 签名、`iss`、`aud`、`exp`，失败返回 401 / `40100`（前端会自动重新发起登录）。JWKS 拉取超时 5s，启动时和之后每小时预热一次
2. 以 `sub`（Logto 用户 ID）为键查找本地用户，**首次出现即自动建档**（upsert），业务数据一律按本地用户 ID 隔离。被管理员禁用的用户返回 403 / `40300`
3. 管理员判定：`sub` 在后端 `ADMIN_SUBS` 中，或 token 的 `scope` / `roles` 含 `admin`
4. access token 不含昵称、头像，前端登录后调 `PUT /users/me` 同步 ID Token 里的资料

## 2. 核心数据模型（TypeScript 定义，前后端共用）

```ts
interface User {
  id: string;            // 本地用户 ID（u_ 前缀）
  logto_id: string;      // Logto 用户 ID，即 JWT 的 sub
  username?: string; nickname: string; email?: string; avatar?: string;
  role: 'user' | 'admin'; status: 'active' | 'disabled'; created_at: string;
}

interface Conversation {
  id: string; title: string; agent_id?: string;
  pinned: boolean; last_message_at: string; created_at: string;
}

interface Citation { index: number; source: string; snippet: string; score: number; doc_id?: string; chunk_id?: string; }

interface Message {
  id: string; conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content_type: 'markdown' | 'card';
  content: string;                       // markdown 文本，或 card 时的摘要
  card?: { card_type: 'prediction' | 'case_list' | 'risk_list' | 'document'; payload: unknown };
  citations?: Citation[];
  reasoning?: string;                    // 思维链（可选）
  status: 'streaming' | 'done' | 'error' | 'aborted';
  usage?: { prompt_tokens: number; completion_tokens: number };
  created_at: string;
}

interface Agent {
  id: string; name: string; avatar?: string; category: string; description: string;
  system_prompt: string; opening_statement?: string; suggested_questions?: string[];
  tool_ids: string[]; dataset_ids: string[];
  scope: 'private' | 'org' | 'public';
  status: 'draft' | 'published' | 'offline';
  usage_count: number; created_by: string; created_at: string;
}

interface Workflow {
  id: string; name: string; description: string;
  dsl: { nodes: WorkflowNode[]; edges: WorkflowEdge[] };   // React Flow 序列化结构
  status: 'draft' | 'published'; created_at: string;
}

interface Dataset {
  id: string; name: string; description?: string;
  chunk_config: { max_length: number; overlap: number };
  retrieval_config: { top_k: number; score_threshold: number };
  embed_model?: string;  // 平台模型 ID（如 ollama/bge-m3）；为空用默认嵌入模型，更换后须 reindex
  doc_count: number; created_at: string;
}

interface Document {
  id: string; dataset_id: string; filename: string; size: number;
  status: 'queued' | 'parsing' | 'completed' | 'failed';
  error?: string; chunk_count: number; created_at: string;
}

interface Chunk { id: string; document_id: string; index: number; content: string; enabled: boolean; }

interface ModelInfo {
  id: string;            // 平台模型 ID：`{provider_id}/{模型名}`，如 ollama/qwen3.5:9b
  name: string; provider: string; provider_name?: string; provider_type?: 'ollama' | 'openai_compat';
  capabilities?: ('completion' | 'embedding' | 'vision' | 'tools' | 'thinking')[];
  description?: string;
  default_params: { temperature: number; top_p: number; max_tokens: number };
}

interface ModelProvider {            // 自定义模型网关（供应商）
  id: string; name: string; type: 'ollama' | 'openai_compat';
  base_url: string;                  // 粘贴完整地址时自动去掉 /chat/completions、/embeddings
  api_key: string;                   // 回传打码为 ****xxxx；PATCH 时传回打码值表示不修改
  enabled: boolean;
  models: { id: string; name: string; capabilities: string[]; default_params: object }[];
}
```

## 3. 接口明细

> 标 🔒 的接口需要管理员。当前实现里列表接口暂时一律返回**完整数组**（`data: T[]`），没有分页；数据量上来后再按 §1 的分页约定改造。

### 3.1 认证与用户

```
# 注册 / 登录 / 登出由 Logto 托管（见 §1.3），无对应后端接口
GET  /auth/me          （首次调用时按 JWT 自动建档）       → data: User & { auth_enabled: boolean }
PUT  /users/me         { nickname?, username?, email?, avatar? }  → data: User
                       （前端登录后用 ID Token 资料同步；mock 模式不调用）
```

### 3.2 会话与消息

```
GET    /conversations                   ?agent_id?                 → data: Conversation[]（置顶优先，按最近消息倒序）
POST   /conversations                   { title?, agent_id? }      → data: Conversation
PATCH  /conversations/{id}              { title?, pinned? }        → data: Conversation
DELETE /conversations/{id}                                         → data: null
GET    /conversations/{id}/messages                                → data: { list: Message[], next_cursor: null }
DELETE /conversations/{id}/messages     （清空会话消息）            → data: null
DELETE /conversations/{id}/messages/{mid}   （删除单条消息）        → data: null
POST   /conversations/{id}/messages/{mid}/feedback { rating: 'up'|'down'|null } → data: { id, feedback }
```

会话按 `owner_id` 隔离，访问他人会话返回 404（管理员除外）。消息反馈（点赞/点踩）随 `Message.feedback` 下发，传 `null` 取消。

### 3.3 对话补全（核心，SSE 流式）

```
POST /chat/completions
{
  "conversation_id": "c_xxx",       // 不存在时自动建会话
  "agent_id": "a_xxx",              // 可选；不传为通用助手
  "model": "ollama/qwen3.5:9b",     // 可选；不传用默认对话模型（GET /settings/models）
  "messages": [ { "role": "user", "content": "…" } ],
  "stream": true,
  "thinking": false,                // 可选；只对带 thinking 能力的模型生效
  "params": { "temperature": 0.7, "top_p": 0.9, "max_tokens": 2048 },
  "attachments": [ { "file_id": "f_xxx", "filename": "合同.docx", "size": 1024 } ],  // 可选，见 POST /files
  "retrieval": { "dataset_ids": ["d_1"], "top_k": 5 }   // 可选 RAG；不传时用智能体绑定的知识库
}
```

附件解析为文本后注入上下文，单个附件最多 8000 字（`ATTACHMENT_MAX_CHARS`）。

**SSE 事件流**（`Content-Type: text/event-stream`，前端按事件分发渲染）：

| event | data | 说明 |
|---|---|---|
| `message` | `{"delta":"文本增量"}` | 正文增量，多次推送 |
| `reasoning` | `{"delta":"思维链增量"}` | 可选 |
| `citations` | `{"items":[{index,source,snippet,score,doc_id,chunk_id}]}` | RAG 命中，正文输出前推送 |
| `tool_call` | `{"name":"knowledge_retrieval","status":"running" \| "failed","message"?}` | 工具调用状态；检索失败时 `status=failed` 并带原因，对话继续（不带引用） |
| `workflow` | `{"node_id":"llm_1","status":"succeeded","elapsed":2100}` | 工作流节点进度（见 §3.5） |
| `card` | `{"card_type":"prediction","payload":{…}}` | 结构化输出卡片（预留，当前未实现） |
| `done` | `{"message_id":"m_x","usage":{"prompt_tokens":120,"completion_tokens":480}}` | 结束标志；usage 取模型真实计数，拿不到时按字数估算 |
| `error` | `{"code":50001,"message":"模型超时"}` | 中途错误 |

**中断约定**：客户端断开连接（AbortController）即视为"停止生成"，后端终止推理，并将已生成内容落库为 `status=aborted`。
**重新生成 / 编辑重发**：由前端按消息数组重新调用本接口实现，不单独建接口。

#### 3.3.1 浏览器直连本机模型（模型 ID 以 `local/` 开头）

推理在用户电脑上的 Ollama 里进行（浏览器直接请求 `http://127.0.0.1:11434/api/chat`），服务端不推理，只负责组装上下文与落库。`/chat/completions` 收到 `local/` 模型返回 42200。

```
POST /chat/prepare   请求体同 /chat/completions
                     → data: { assistant_id, llm_messages: [{role, content}], citations: Citation[] | null, rag_error: string | null }
                     （完成会话校验、用户消息落库、智能体提示词 / 附件文本 / 知识库检索注入）
POST /chat/commit    { conversation_id, assistant_id, model, content, reasoning?, status: done|aborted|error,
                       usage?, citations? }   → data: { message_id, usage }
                     （生成结束、中止或出错都要调用；同一 assistant_id 重复提交只覆盖内容，不重复计数）
```

- `llm_messages` 含智能体的 `system_prompt` 与检索资料原文，会下发到浏览器。这是浏览器直连的必要代价：智能体提示词对使用者可见
- 知识库检索仍在服务端用服务端的嵌入模型完成；服务端没有嵌入模型时 `rag_error` 给出原因，对话照常进行
- 前提：Ollama 允许本站跨域（`OLLAMA_ORIGINS`）。Ollama 默认只放行 localhost / 127.0.0.1 等本机来源，公网站点需要用户把站点源加入该变量（前端向导提供一键脚本）

### 3.4 智能体

```
GET    /agents            ?scope=all|market|mine     → data: Agent[]
                          （market = 已发布且 public/org；mine = 自己创建的；all = 自己可见的全部）
POST   /agents            { name, category, description, system_prompt, opening_statement?,
                          suggested_questions?, tool_ids?, dataset_ids?, scope }
GET    /agents/{id}                                                   → data: Agent
PATCH  /agents/{id}      （部分更新，仅创建者或管理员）                  → data: Agent
DELETE /agents/{id}
POST   /agents/{id}/publish                                          → status=published
POST   /agents/{id}/offline                                          → status=offline
```

### 3.5 工作流

```
GET    /workflows                                         → data: Workflow[]（自己的 + 模板 + 已发布的）
POST   /workflows            { name, description, dsl }
GET    /workflows/{id}                                    → data: Workflow
PATCH  /workflows/{id}       { name?, description?, dsl? }
DELETE /workflows/{id}
POST   /workflows/{id}/run   { inputs: { 变量名: 值 }, dsl? }  → SSE
                             （带 dsl 时运行这份画布而不是已保存版本，用于编辑器试运行）
```

**运行事件**：

| event | data |
|---|---|
| `workflow` | `{"node_id","name","status":"running" \| "succeeded" \| "failed" \| "skipped","elapsed"?,"output"?}` |
| `message` | `{"delta":"最终回复全文"}`（回复节点的输出，一次下发） |
| `done` | `{"outputs":{节点 ID: 输出}}`（每项截断到 2000 字） |
| `error` | `{"code":50001,"message":"…"}` |

**执行语义**：节点按拓扑序执行。`{{变量}}` 依次在输入变量、节点 ID、节点名、节点类型里查找。分支节点条件不成立时，下游节点标为 `skipped`。HTTP 节点只允许 http(s)，超时 20s。支持的节点类型：start / llm / retrieval / branch / http / template / aggregate / reply。

### 3.6 知识库（RAG）

```
GET    /datasets                                → data: Dataset[]
POST   /datasets                       { name, description?, embed_model?, chunk_config?, retrieval_config? }
                                       （embed_model 不传用默认嵌入模型；传了不存在的返回 42200）
GET    /datasets/{id}                  → data: Dataset
PATCH  /datasets/{id}                  → data: Dataset（仅创建者或管理员）
DELETE /datasets/{id}                  （同时删除文档、分段与向量）

POST   /datasets/{id}/documents        multipart/form-data，字段名 file，可多个（PDF/DOCX/TXT/MD，单文件 ≤ 20MB）
                                       → data: Document[]
                                       （支持的格式 status=queued，后台按 parsing → completed/failed 推进；
                                         不支持的格式直接 status=failed 并给出 error，如 .doc 提示另存为 .docx）
GET    /datasets/{id}/documents        → data: Document[]（前端轮询解析状态）
DELETE /documents/{id}
GET    /documents/{id}/chunks          → data: Chunk[]
PATCH  /chunks/{id}                    { enabled?, content? }（改 content 会用知识库的嵌入模型重新向量化）

POST   /datasets/{id}/reindex          { embed_model? }
                                       → data: { chunk_count, embed_model }
                                       （用新的或当前的嵌入模型重建全部向量；分段内容与启停状态保留）
POST   /datasets/{id}/hit-testing      { query, top_k? }
                                       → data: { items: [ { chunk: Chunk, score: 0.91 } ] }
```

分段参数只对之后上传的文档生效。检索时按各知识库自己的嵌入模型分别向量化查询，并按各自的 `score_threshold` 过滤。

### 3.7 模型网关与通用文件

```
GET    /models                 ?capability=completion|embedding|vision|tools|thinking  → data: ModelInfo[]
POST   /models/{model_id}/ping → data: { latency_ms } | error(50001)
                                 （嵌入模型实际嵌入一次；对话模型只测供应商连通，不消耗生成额度）

GET    /settings/models        → data: { default_chat_model, default_embed_model }
PUT    /settings/models 🔒     { default_chat_model?, default_embed_model? }
                                 （须是具备对应能力的已注册模型，否则 42200）

GET    /providers              → data: (ModelProvider & { status? })[]
                                 （ollama 类附带最近一次连接结果 status: { reachable, version, error, checked_at }；
                                   模型清单每 30 秒在后台刷新，Ollama 不可达不会拖慢接口）
POST   /providers 🔒           { name, type: 'ollama' | 'openai_compat', base_url, api_key?, enabled? }
PATCH  /providers/{id} 🔒      （部分更新；api_key 传回打码值表示不修改；Ollama 类改 base_url 后立即按新地址重新发现）
DELETE /providers/{id} 🔒      （内置供应商不可删，返回 40000）
POST   /providers/{id}/ping    → data: { latency_ms }
POST   /providers/{id}/remote-models 🔒  → data: { models: { id, capabilities: string[] }[] }
                                 （拉取远端模型列表，只列不存；能力标签直接读上游字段识别：
                                   openai_compat 读 /models 条目的 capabilities/features、supported_parameters、architecture.input_modalities，
                                   无字段时按族名兜底（embed/bge/m3e/gte → embedding，其余 completion）；ollama 读 /api/tags 的 capabilities）
POST   /providers/{id}/refresh 🔒        （仅 ollama：重新发现模型，新 pull 的模型立即可见）
POST   /providers/ollama/detect 🔒       { base_url? } → data: { base_url, reachable, version, models: string[], error }
                                 （只测不存；不传 base_url 时依次尝试当前地址、127.0.0.1:11434、host.docker.internal:11434，返回第一个可达的）
POST   /providers/{id}/pull 🔒           { model } → SSE：progress {status, completed?, total?} → done {model} | error
                                 （仅 ollama：让 Ollama 下载模型；完成后刷新清单，平台此前没有同类模型时自动设为默认对话 / 嵌入模型；
                                   客户端断开不会中止 Ollama 端的下载，再次拉取会断点续传）
POST   /providers/{id}/models 🔒         { id 或 name, capabilities?: string[] | null, default_params? }
                                 （注册模型。**capabilities 缺省/null/空数组时服务端自动识别**：按 remote-models 同源规则读上游字段，
                                   列表查不到该模型时按族名兜底；仅显式传入数组才视为人工指定（覆盖识别结果））
PATCH  /providers/{id}/models/{model} 🔒
DELETE /providers/{id}/models/{model} 🔒

POST   /files                  multipart/form-data，字段名 file（对话附件，≤ 20MB）
                               → data: { file_id, filename, size }（按上传者隔离，首次被对话引用时解析文本并缓存）
```

### 3.8 提示词库与管理后台

```
GET    /prompts                → data: Prompt[]（平台共享）
POST   /prompts                { name, content, category? }
PATCH  /prompts/{id}           { name?, content?, category?, starred? }
DELETE /prompts/{id}
        （PATCH/DELETE 仅创建者或管理员；种子提示词仅管理员可改删）

GET    /admin/users 🔒         → data: (User & { username, agent_count })[]
PATCH  /admin/users/{id} 🔒    { status?: 'active' | 'disabled', role?: 'user' | 'admin' }（不能禁用自己）
GET    /admin/stats/usage 🔒   → data: { date, calls }[]（最近 14 天）
GET    /admin/stats/models 🔒  → data: { name, value }[]（各模型调用次数）
```

### 3.9 服务状态（无需鉴权）

```
GET /health  → data: {
  service: 'justilaw-api', status: 'up' | 'degraded',
  auth_enabled: boolean,                 // false = 单机模式，前端免登录
  setup_required: boolean,               // 没有可用对话模型，前端展示「模型连接向导」
  ollama: { enabled, reachable: boolean | null, version, base_url },   // reachable=null 表示尚未检测；
                                         // base_url 仅单机模式返回（公网部署不暴露内网地址）
  default_chat_model, default_embed_model, warnings: string[]
}
```

### 3.10 托管前端

后端检测到 `WEB_DIST_DIR`（默认 `../justilaw-web/dist`）存在时，直接托管前端：`/api/*` 以外的路径返回静态文件或 `index.html`（SPA 回退），`assets/` 下不存在的文件返回 404（让旧页面触发整页刷新）。单机部署只需一个端口。

### 3.11 裁量建议（赌博类治安处罚，引擎第一版）

输入为办案人员填写的要素（不经大模型抽取）；输出是裁量建议，不是处罚决定。设计见[引擎方案](./gambling-discretion-engine.md) v0.6。前端 Mock 模式下也直连后端。

```
GET  /discretion/meta    → data: { behavior_types, methods, gambling_forms, venue_types, minor_levels: string[],
                                   provinces: { code, name }[], laws: { id, title }[] }
POST /discretion/decide  { behavior_date (必填), behavior_type (必填), decision_date?, region? (六位区划码),
                           personal_stake? / onsite_stake_total? / commission?: { min, max | null },
                           method?, gambling_form?, venue_type?, civil_servant?, age?, first_offense?, role?, … }
                           // role（v1.0.1）：本人角色，枚举见 GET /discretion/meta 的 roles；江苏为赌博提供条件中放贷者、望风者升第三档
                           // 字段与 norm_layer.Facts 同名；未传 = 未知（不是"否"）；未知字段 → 422
  → data: {
      penalty_type: string | null,       // 罚款 / 拘留 / 拘留并处罚款 / 不予处罚；null = 未确定
      route: 'rule_single' | 'rule_candidates' | 'model_fallback' | 'undetermined',
      candidates: string[],              // 省级分档允许的种类；空 = 无省级分档
      quantities: { fine?: [值, 占比][], detention_days?: [值, 占比][] },   // 档内历史分布，已按法定幅度过滤
      assessment: { law_id, temporal_note, tiers: { 一般, 情节严重 → { options: [{ detention, fine, via, basis, kind }],
                    detention_executable, not_executed_reason } }, directions, referral, stake_threshold, needs_review },
      notes: string[]
    }
  // 行为日期晚于决定日期、日期超出规范库覆盖范围 → 422 { code: 42200, message }
```

### 3.12 裁量能力层（待前端组评审；**全部已实现**，v1.0）

> 设计：[裁量能力层](./discretion-capability-layer.md)。原则：要素是规范输入（不接文本模型）；模型调用走平台网关，按槽位配置；**每个结果都带 `trace`**（推理步骤、原文依据、计算过程、学习部分贡献分解、模型调用回执、版本），可按 `run_id` 取回。§3.11 的 `/discretion/decide` 保留兼容，后续由 `/discretion/assess` 取代。
> parse / extract / review(text) 复用 `research/discretion/unify` 的 S1 与要素链路（提示、输入视图、校验、引用编译原样调用，只把模型请求改走网关）。部署镜像已复制链路目录（v0.9.1）；链路不可用时这三个接口返回 503，`GET /discretion/settings` 的 `chain.available=false`。
> **模拟数据**：`justilaw-web/src/mocks/fixtures/discretion/`（`index.json` 列出每个文件对应的接口与场景），由 `justilaw-api/scripts/export_discretion_fixtures.py` 从真实路由生成，契约变化后重跑即可同步。

**任务号 + 轮询（v1.0）**：调用模型的 `parse`、`extract`、`review` 一律异步——提交后立即返回 **202**，工作在后台执行，前端轮询 `GET /discretion/runs/{run_id}` 直到 `status` 不是 `running`。真实模型下抽取约 40 秒、审查约 60 秒，不受前端 30 秒请求超时限制。`assess`（无模型调用，毫秒级）保持同步。

```
提交（parse / extract / review）→ 202
  data: { run_id, kind, status: 'running', poll: '/api/v1/discretion/runs/<run_id>', poll_interval_ms: 2000 }
  // 不需要模型就能发现的错误在提交时同步返回、不建任务：参数缺失 / 冲突 → 422；槽位未配置、链路不可用 → 503；
  //   普通用户临时指定模型而槽位不允许 → 403；parse_run_id 不存在 → 404，分段任务未成功 → 409

GET  /discretion/runs/{run_id}     （仅本人与管理员）
  → data: { run_id, kind: 'parse' | 'extract' | 'assess' | 'review', status: 'running' | 'succeeded' | 'failed',
            created_at, finished_at | null, request_sha256,
            result: <下列各接口的结果> | null,                       // succeeded 时
            error: { http_status, code, message } | null,             // failed 时；http_status 为同步调用时会用的状态码
            partial: { parse?, extraction?, model_calls } | null }    // failed 时已完成的部分（已花费的模型调用不丢）
  // 服务重启时未完成的任务 → failed，code 50001（"服务重启，任务中断，请重新提交"）
  // 原始模型输出只留在服务端存档，不返回
```

```
GET  /discretion/settings          → data: { models: { segment | extract: { title, model_id, effective_model_id, fallback_model_id,
                                                                           params: { temperature, top_p?, max_tokens, seed, thinking, timeout_s, retries, extra_body? },
                                                                           allow_user_override } },
                                             chain: { available, reason?, segment_prompt: { version, system_sha256 },
                                                      extract_prompt: { version, wire, schema, fingerprint_sha256 }, chain_files_sha256 } }
                                   // model_id 为空 = 用平台默认对话模型（effective_model_id 为实际生效值）
PUT  /discretion/settings          （管理员）{ models: { segment?: {...}, extract?: {...} } }   // 只改给出的键
                                   → 同 GET；模型不是已登记的对话模型、params 含不支持的键 → 422；非管理员 → 403
                                   // 提示词不可在此修改（随代码版本走，保证可复现）

POST /discretion/parse             { text, doc_kind: '笔录' | '叙述' | '决定书' = '叙述', target?, model_id? }
  → 202；result: { sentences: string[], zones: [{ type, from, to }], subject: { mention, aliases },
            outcome?: { type, detention_days, fine, articles, not_executed, … },   // 仅 doc_kind=决定书
            dates: { behavior, decision }, gambling: { verdict, reason }, review,
            validation: { ok, violations: string[] }, trace: { versions, inputs, model_calls } }

POST /discretion/extract           { text? | parse_run_id?, doc_kind?, target?, region?, behavior_date?, decision_date?,
                                     model_id?（extract 槽位）, segment_model_id?（需要先分段时） }
  → 202；result: { run_id, schema_version, target,
            elements: { '<组>.<字段>': { value, status: '明确' | '推断' | '未提及',
                                         evidence: [{ quote, sentence, span: [start, end] }],
                                         origin: 'extracted', fact_field: <assess 字段名> | null } },
            assess_input: { <assess 扁平要素>, provenance },     // 可直接（经人工确认后）提交 assess
            dropped: [{ path, reason }],                         // 校验不通过而剔除的字段（最多 3 个），elements 中 status='待核实'，不进 assess_input
            meta_missing: ('behavior_date' | 'region')[],         // 评估前须补齐
            note, trace: { versions, inputs: { text_sha256, parse_run_id, target, input_view }, model_calls } }
  // 给 parse_run_id 时复用该次分段结果，不再调用分段模型；target 缺省取分段结果的 subject.mention
```

`model_calls[]`（模型调用回执，每次尝试一条，失败也记）：`{ slot, attempt, prompt: { version, … }, platform_model_id, provider_id, provider_type, model, response_model, response_id?, params, structured, schema_fallback?, request_sha256, response_sha256, usage, latency_ms, finish_reason, status: 'ok' | 'fail', error?, validation: { ok, violations } }`。不含密钥与原始提示全文（提示由版本与哈希确定）。

重试规则（每个槽位）：主模型最多 `1 + retries` 次，校验不过时把违例回灌重试；仍失败换 `fallback_model_id` 一次。全部失败 → 任务 `failed`，`error: { http_status: 502, code: 50200 }`，`partial.model_calls` 含全部回执。

```
POST /discretion/assess            【已实现，同步】要素字段与 §3.11 decide 相同（扁平，未填 = 未知），另加：
                                   { provenance?: { <要素字段名>: { status: '明确' | '推断', origin: 'human' | 'extracted' | 'extracted_then_confirmed' | 'edited',
                                                                 evidence: [{ quote, sentence?, span? }] } },   // 未给的要素按 human、明确处理
                                     proposed?: { type, detention_days?, fine? } }
  → data: { run_id,
            written: { type | null, route, candidates: string[], legal_space, band },    // 成文结论（法律）
            practice: { status: 'reference' | 'out_of_scope' | 'unavailable', distribution?: { <type>: p }, predicted?, reading?: string[], note? },   // 实务参照（学习，非法律结论）
            amounts: { fine?: [值, 占比][], detention_days?: [值, 占比][] },
            deviation?: { levels: [{ level: 'legal_space' | 'written_band' | 'amount_reference' | 'practice', ok, detail, probability? }] },   // 有 proposed 时
            missing: [{ field, why, effect }],
            needs_review: string[], trace }
  // practice 由 RAP 给出：10-28 起线上为 rap-ruleonly-v2（只用规则结论，trace.practice.model.version 标明；v1.0.2）；此前为无文本版 v1（v0.8.2）；两省以外、其他行为类型、新法时期为 out_of_scope，不外推。
  // trace 的 practice 步骤另含 explanation：baseline_logits、logits、groups（按要素组汇总的贡献）、margin_for_predicted、
  //   contributions[{ name, label, group, value, train_mean, contribution: { <type>: 对数几率贡献 } }]；基线 + 逐项贡献 = 对数几率，可精确复算
  // practice 的 ok 恒为 null：实务参照只报比例，不判对错
  // 每次调用存档（status=succeeded），run_id 可用 GET /discretion/runs/{run_id} 取回

POST /discretion/review            【已实现】决定书审查，两种输入：
                                   A. { text, target?, region?, behavior_date?, decision_date?, model_id?, segment_model_id? }
                                      → 分段（doc_kind=决定书）→ 抽取 → actual 取自分段结果的 outcome → assess
                                   B. { elements: <assess 请求体>, actual: { type, detention_days?, fine? } }   // 已确认要素，不调用模型
  → 202（B 也走任务，立即完成）；result: { <assess 的全部字段>, actual, parse?, extraction?: { elements, dropped, assess_input, meta_missing, target },
            deviation: { levels: [...], summary } }   // trace.model_calls 含两次调用回执；result.run_id 即任务号
  // 任务内失败（error.code 42200）：抽取后缺地区或行为日期（partial 含解析与抽取，补齐后可改用 B 提交）；
  //   决定书种类不在 不予处罚 / 罚款 / 拘留 / 拘留并处罚款
```

`trace` 结构见设计文档 §4.2：`versions`、`inputs`（要素逐项含证据与来源）、`steps`（law / legal_space / modifiers / band / written_type / practice / amount / deviation / missing，每步含 result、reasoning 或 computation、basis 原文）、`model_calls`（槽位、平台模型 ID、供应商、提示版本、输入输出哈希、耗时、usage）。

错误：同步返回的见上方"提交"说明；任务内失败通过轮询的 `error` 返回，`code` 与同步时一致（日期矛盾或超出规范库覆盖、要素不可用 42200；模型调用全部失败 50200；链路不可用 50300；服务重启中断 50001）。

## 4. 联调约定

1. 前端基于 MSW 按本契约**全量 Mock**（SSE 用 ReadableStream 模拟增量），先行开发
2. 后端按模块交付（建议顺序：auth → chat → datasets → agents → workflows），每交付一组即切换真实 baseUrl 联调
3. 契约变更流程：修改本文档 → 双方评审 → 同步更新 mock 与实现 → 记录变更日志
4. 字段一律 `snake_case`；时间 ISO 8601（UTC）

## 5. 变更日志

| 日期 | 版本 | 变更 | 提出方 |
|---|---|---|---|
| 2026-10-14 | v0.1 | 初稿（待后端评审） | 前端组 |
| 2026-10-14 | v0.2 | 鉴权改为 Logto OIDC：移除 `/auth/register`、`/auth/login`；新增 §1.3 JWT 校验约定；`User` 增加 `logto_id`、`email` | 前端组 |
| 2026-10-14 | v0.3 | 按 justilaw-api 实现对齐：§1.3 增加 resource / idtoken / 本地三种鉴权模式与管理员判定；错误响应包与 40000；`Dataset.embed_model`、`ModelInfo.capabilities`、`ModelProvider`；新增 `/settings/models`、`/providers/*`（含 remote-models / refresh / 模型注册）、`/datasets/{id}/reindex`、`DELETE /documents/{id}`、`DELETE /conversations/{id}/messages`、§3.8 提示词与管理后台；`/chat/completions` 增加 `thinking`、`attachments`，`tool_call` 增加 failed；`/workflows/{id}/run` 改为 `{inputs, dsl?}` 并定义运行事件；列表接口暂不分页 | 模型组 |
| 2026-10-15 | v0.4 | 用户本地 Ollama 接入：§1.3 增加前端单机模式；新增 §3.3.1 浏览器直连本机模型（`/chat/prepare`、`/chat/commit`，`local/` 模型前缀）；`/providers/ollama/detect`、`/providers/{id}/pull`；`/providers` 附带 Ollama 连接状态；内置 Ollama 地址可修改；新增 §3.9 `/health` 字段（`setup_required`、`ollama`）与 §3.10 后端托管前端 | 模型组 |
| 2026-10-16 | v0.5 | 平台功能补全：§3.2 新增单条消息删除与点赞/点踩反馈（`Message.feedback`）；§3.8 提示词改删限创建者/管理员；§3.6 知识库列表/详情按创建者过滤（自己的 + 系统种子库对所有人可见，其余仅管理员）；`AdminUser` 增加 `logto_id` | 模型组 |
| 2026-10-28 | v1.0.2 | assess 的实务参照模型切换为 rap-ruleonly-v2（结构不变；contributions 只含规则结论特征） | 引擎 |
| 2026-10-28 | v1.0.1 | decide / assess 要素加 `role`（本人角色）；`GET /discretion/meta` 加 `roles` | 引擎 |
| 2026-10-28 | v1.0（待评审） | §3.12 parse / extract / review 改为**任务号 + 轮询**：提交返回 202 + run_id，轮询 `GET /discretion/runs/{run_id}`（status / result / error / partial）；配置与参数错误仍同步返回；assess 保持同步；附模拟数据目录与生成脚本 | 引擎 |
| 2026-10-28 | v0.9.1（草案） | extract / review 加 `dropped`（字段级剔除，交人工核实）；review 的 422 也存档并返回 run_id；镜像已带链路 | 引擎 |
| 2026-10-28 | v0.9（草案） | §3.12 全部实现：`settings`（segment / extract 槽位，管理员可改，提示随代码版本）、`parse`、`extract`（证据含句号与坐标，给出可直接提交 assess 的 `assess_input`）、`review`（决定书文本或已确认要素 + 实际处罚）；模型调用回执 `model_calls` 结构与重试规则；错误码 403 / 502 / 503 | 引擎 |
| 2026-10-28 | v0.8.2（草案） | §3.12 assess 的 `practice` 接入 RAP 无文本版：status / distribution / predicted / reading；trace 的 practice 步骤给逐特征贡献分解与模型元数据；deviation 加 practice 层（拟处罚种类在相近历史案件中的比例）；versions.practice_model | 引擎 |
| 2026-10-28 | v0.8.1（草案） | §3.12 `assess`、`runs` 已实现：assess 请求改为与 decide 同名的扁平要素 + provenance + proposed；trace 含适用法律、法定空间（条文原文）、修正情节、涉刑提示、省级定档（计算过程 + 档位条款原文）、成文种类、数额参照（数据来源）、实务参照（待接入）、偏离、补查、版本 | 引擎 |
| 2026-10-28 | v0.8（草案） | 新增 §3.12 裁量能力层草案：settings（模型槽位）、parse、extract、assess、review、runs；结果统一带 trace（待评审，未实现） | 引擎 |
| 2026-10-28 | v0.7 | 新增 §3.11 裁量建议：`GET /discretion/meta`、`POST /discretion/decide`（引擎第一版，人工要素输入） | 引擎 |
| 2026-10-22 | v0.6 | 模型能力自动识别（免手动填写）：`/providers/{id}/remote-models` 返回 `{ id, capabilities }[]`（读上游 capabilities/supported_parameters/architecture.input_modalities，族名兜底）；`POST /providers/{id}/models` 的 `capabilities` 可缺省，缺省时服务端自动识别，显式数组仅表人工覆盖 | 前端平台 |
