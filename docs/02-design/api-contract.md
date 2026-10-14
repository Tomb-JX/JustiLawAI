# JustiLawAI API 契约（前端 ⇆ 后端）

> 版本 v0.1（草案，**待后端评审**） · 2026-10-14
>
> 本文档是前后端对接的**唯一依据**：任何接口变更必须先修改本文档、双方评审通过后再实现，并记录到文末变更日志。前端将依据本文档先行 Mock 开发。

## 1. 通用约定

- **Base URL**：`/api/v1`
- **鉴权**：除 `POST /auth/register`、`POST /auth/login` 外，均需请求头 `Authorization: Bearer <JWT>`
- **Content-Type**：`application/json`（文件上传为 `multipart/form-data`）
- **响应包**（所有 REST 接口统一）：

```json
{ "code": 0, "message": "ok", "data": { } }
```

- `code = 0` 成功；非 0 为业务错误，HTTP 状态码同时体现类别
- **偏移分页**：请求 `?page=1&pageSize=20` → `data: { "list": [...], "total": 100 }`
- **游标分页**（消息历史）：请求 `?cursor=m_xxx&limit=50` → `data: { "list": [...], "next_cursor": "m_yyy 或 null" }`

### 1.1 错误码

| HTTP | code | 含义 |
|---|---|---|
| 401 | 40100 | 未登录 / token 失效（前端跳登录页） |
| 403 | 40300 | 无权限 |
| 404 | 40400 | 资源不存在 |
| 422 | 42200 | 参数校验失败（message 携带字段级详情） |
| 429 | 42900 | 请求限流 |
| 500 | 50000 | 服务器内部错误 |
| 500 | 50001 | 模型推理超时 / 失败 |

### 1.2 ID 规范

带类型前缀的短 ID，便于日志排查：`u_` 用户、`c_` 会话、`m_` 消息、`a_` 智能体、`w_` 工作流、`d_` 知识库、`doc_` 文档、`ch_` 分段、`f_` 文件。

## 2. 核心数据模型（TypeScript 定义，前后端共用）

```ts
interface User {
  id: string; username: string; nickname: string; avatar?: string;
  role: 'user' | 'admin'; created_at: string;
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
  doc_count: number; created_at: string;
}

interface Document {
  id: string; dataset_id: string; filename: string; size: number;
  status: 'queued' | 'parsing' | 'completed' | 'failed';
  error?: string; chunk_count: number; created_at: string;
}

interface Chunk { id: string; document_id: string; index: number; content: string; enabled: boolean; }

interface ModelInfo {
  id: string; name: string; provider: string; description?: string;
  default_params: { temperature: number; top_p: number; max_tokens: number };
}
```

## 3. 接口明细

### 3.1 认证与用户

```
POST /auth/register    { username, password, nickname }            → data: { token, user }
POST /auth/login       { username, password }                      → data: { token, user }
GET  /auth/me                                                      → data: User
PUT  /users/me         { nickname?, avatar? }                      → data: User
```

### 3.2 会话与消息

```
GET    /conversations                   ?page&pageSize&agent_id?   → data: { list: Conversation[], total }
POST   /conversations                   { title?, agent_id? }      → data: Conversation
PATCH  /conversations/{id}              { title?, pinned? }        → data: Conversation
DELETE /conversations/{id}                                         → data: null
GET    /conversations/{id}/messages     ?cursor&limit              → data: { list: Message[], next_cursor }
```

### 3.3 对话补全（核心，SSE 流式）

```
POST /chat/completions
{
  "conversation_id": "c_xxx",
  "agent_id": "a_xxx",              // 可选；不传为通用助手
  "model": "justilaw-xx",
  "messages": [ { "role": "user", "content": "…" } ],
  "stream": true,
  "params": { "temperature": 0.7, "top_p": 0.9, "max_tokens": 2048 },
  "retrieval": { "dataset_ids": ["d_1"], "top_k": 5 }   // 可选 RAG
}
```

**SSE 事件流**（`Content-Type: text/event-stream`，前端按事件分发渲染）：

| event | data | 说明 |
|---|---|---|
| `message` | `{"delta":"文本增量"}` | 正文增量，多次推送 |
| `reasoning` | `{"delta":"思维链增量"}` | 可选 |
| `citations` | `{"items":[{index,source,snippet,score,doc_id}]}` | RAG 命中，正文输出前推送 |
| `tool_call` | `{"name":"case_search","status":"running"}` | 工具调用状态 |
| `workflow` | `{"node_id":"llm_1","status":"succeeded","elapsed":2100}` | 工作流节点进度 |
| `card` | `{"card_type":"prediction","payload":{…}}` | 结构化输出卡片 |
| `done` | `{"message_id":"m_x","usage":{"prompt_tokens":120,"completion_tokens":480}}` | 结束标志 |
| `error` | `{"code":50001,"message":"模型超时"}` | 中途错误 |

**中断约定**：客户端断开连接（AbortController）即视为"停止生成"，后端应终止推理，并将已生成内容落库为 `status=aborted`。
**重新生成 / 编辑重发**：由前端按消息数组重新调用本接口实现，不单独建接口。

### 3.4 智能体

```
GET    /agents            ?scope=market|mine&category=&keyword=&page&pageSize
POST   /agents            { name, category, description, system_prompt, opening_statement?,
                          suggested_questions?, tool_ids?, dataset_ids?, scope }
GET    /agents/{id}                                                   → data: Agent
PATCH  /agents/{id}      （部分更新）                                  → data: Agent
DELETE /agents/{id}
POST   /agents/{id}/publish                                          → status=published
POST   /agents/{id}/offline                                          → status=offline
```

### 3.5 工作流

```
GET    /workflows            ?page&pageSize
POST   /workflows            { name, description, dsl }
GET    /workflows/{id}                                    → data: Workflow
PATCH  /workflows/{id}       { name?, description?, dsl? }
DELETE /workflows/{id}
POST   /workflows/{id}/run   { inputs, stream: true }     → SSE（message/citations/workflow/done/error）
```

### 3.6 知识库（RAG）

```
GET    /datasets                       ?page&pageSize
POST   /datasets                       { name, description?, chunk_config, retrieval_config }
GET    /datasets/{id}                  → data: Dataset
PATCH  /datasets/{id}                  → data: Dataset
DELETE /datasets/{id}

POST   /datasets/{id}/documents        multipart/form-data, file[]（PDF/DOCX/TXT/MD，单文件 ≤ 20MB）
                                       → data: Document[]（status=queued）
GET    /datasets/{id}/documents        ?page&pageSize（前端轮询解析状态）
GET    /documents/{id}/chunks          ?page&pageSize
PATCH  /chunks/{id}                    { enabled?, content? }

POST   /datasets/{id}/hit-testing      { query, top_k? }
                                       → data: { items: [ { chunk: Chunk, score: 0.91 } ] }
```

### 3.7 模型与通用文件

```
GET  /models               → data: ModelInfo[]
POST /models/{id}/ping     → data: { latency_ms } | error(50001)
POST /files                multipart/form-data（对话附件）→ data: { file_id, filename, url }
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
