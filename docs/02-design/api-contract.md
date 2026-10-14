# JustiLawAI API 契约（前端 ⇆ 后端）

> 版本 v0.3（已按 justilaw-api 实现对齐） · 2026-10-14
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
```

会话按 `owner_id` 隔离，访问他人会话返回 404（管理员除外）。

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

GET    /providers              → data: ModelProvider[]
POST   /providers 🔒           { name, type: 'ollama' | 'openai_compat', base_url, api_key?, enabled? }
PATCH  /providers/{id} 🔒      （部分更新；api_key 传回打码值表示不修改）
DELETE /providers/{id} 🔒      （内置供应商不可删，返回 40000）
POST   /providers/{id}/ping    → data: { latency_ms }
POST   /providers/{id}/remote-models 🔒  → data: { models: string[] }
                                 （拉取远端模型名列表，只列不存；ollama 读 /api/tags，openai_compat 读 /models）
POST   /providers/{id}/refresh 🔒        （仅 ollama：重新发现模型，新 pull 的模型立即可见）
POST   /providers/{id}/models 🔒         { id 或 name, capabilities?: string[], default_params? }
                                 （手动注册模型，capabilities 默认 ["completion"]；注册嵌入模型时传 ["embedding"]）
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

GET    /admin/users 🔒         → data: (User & { username, agent_count })[]
PATCH  /admin/users/{id} 🔒    { status?: 'active' | 'disabled', role?: 'user' | 'admin' }（不能禁用自己）
GET    /admin/stats/usage 🔒   → data: { date, calls }[]（最近 14 天）
GET    /admin/stats/models 🔒  → data: { name, value }[]（各模型调用次数）
```

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
