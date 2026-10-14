import { USE_MOCK, delay, http } from './client'
import { mockApi } from '@/mocks/mock-api'
import type {
  Agent,
  AdminUser,
  Chunk,
  Conversation,
  Dataset,
  Document,
  ModelDist,
  ModelInfo,
  ModelProvider,
  ModelSettings,
  Health,
  OllamaProbe,
  ChatPrepared,
  ChatCompletionRequest,
  Message,
  Prompt,
  UsagePoint,
  Workflow,
} from '@/types/api'

/* ============ 会话 ============ */

export async function listConversations(): Promise<Conversation[]> {
  if (USE_MOCK) return mockApi.listConversations()
  return (await http.get('/conversations')) as Conversation[]
}

export async function createConversation(body: { title?: string; agent_id?: string }): Promise<Conversation> {
  if (USE_MOCK) return mockApi.createConversation(body)
  return (await http.post('/conversations', body)) as Conversation
}

export async function updateConversation(
  id: string,
  patch: { title?: string; pinned?: boolean },
): Promise<Conversation> {
  if (USE_MOCK) return mockApi.updateConversation(id, patch)
  return (await http.patch(`/conversations/${id}`, patch)) as Conversation
}

export async function deleteConversation(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteConversation(id)
  await http.delete(`/conversations/${id}`)
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  if (USE_MOCK) return mockApi.listMessages(conversationId)
  const data = (await http.get(`/conversations/${conversationId}/messages`)) as { list: Message[] }
  return data.list
}

export async function clearMessages(conversationId: string): Promise<void> {
  if (USE_MOCK) return mockApi.clearMessages(conversationId)
  await http.delete(`/conversations/${conversationId}/messages`)
}

/* ============ 智能体 ============ */

export async function listAgents(): Promise<Agent[]> {
  if (USE_MOCK) return mockApi.listAgents()
  return (await http.get('/agents')) as Agent[]
}

export async function getAgent(id: string): Promise<Agent> {
  if (USE_MOCK) return mockApi.getAgent(id)
  return (await http.get(`/agents/${id}`)) as Agent
}

export async function createAgent(body: Partial<Agent>): Promise<Agent> {
  if (USE_MOCK) return mockApi.createAgent(body)
  return (await http.post('/agents', body)) as Agent
}

export async function updateAgent(id: string, patch: Partial<Agent>): Promise<Agent> {
  if (USE_MOCK) return mockApi.updateAgent(id, patch)
  return (await http.patch(`/agents/${id}`, patch)) as Agent
}

export async function deleteAgent(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteAgent(id)
  await http.delete(`/agents/${id}`)
}

/* ============ 知识库 ============ */

export async function listDatasets(): Promise<Dataset[]> {
  if (USE_MOCK) return mockApi.listDatasets()
  return (await http.get('/datasets')) as Dataset[]
}

export async function getDataset(id: string): Promise<Dataset> {
  if (USE_MOCK) return mockApi.getDataset(id)
  return (await http.get(`/datasets/${id}`)) as Dataset
}

export async function createDataset(body: Partial<Dataset>): Promise<Dataset> {
  if (USE_MOCK) return mockApi.createDataset(body)
  return (await http.post('/datasets', body)) as Dataset
}

export async function updateDataset(id: string, patch: Partial<Dataset>): Promise<Dataset> {
  if (USE_MOCK) return mockApi.updateDataset(id, patch)
  return (await http.patch(`/datasets/${id}`, patch)) as Dataset
}

export async function deleteDataset(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteDataset(id)
  await http.delete(`/datasets/${id}`)
}

export async function listDocuments(datasetId: string): Promise<Document[]> {
  if (USE_MOCK) return mockApi.listDocuments(datasetId)
  return (await http.get(`/datasets/${datasetId}/documents`)) as Document[]
}

export async function uploadDocument(datasetId: string, file: File): Promise<Document> {
  if (USE_MOCK) return mockApi.uploadDocument(datasetId, file.name, file.size)
  const form = new FormData()
  form.append('file', file, file.name)
  // 后端按契约返回 Document[]（支持一次多文件）
  const docs = (await http.post(`/datasets/${datasetId}/documents`, form)) as Document[]
  return docs[0]
}

export async function reindexDataset(
  datasetId: string,
  embedModel?: string,
): Promise<{ chunk_count: number; embed_model: string }> {
  if (USE_MOCK) return mockApi.reindexDataset(datasetId, embedModel)
  return (await http.post(`/datasets/${datasetId}/reindex`, { embed_model: embedModel })) as {
    chunk_count: number
    embed_model: string
  }
}

export async function deleteDocument(documentId: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteDocument(documentId)
  await http.delete(`/documents/${documentId}`)
}

export async function listChunks(documentId: string): Promise<Chunk[]> {
  if (USE_MOCK) return mockApi.listChunks(documentId)
  return (await http.get(`/documents/${documentId}/chunks`)) as Chunk[]
}

export async function updateChunk(
  chunkId: string,
  patch: { enabled?: boolean; content?: string },
): Promise<Chunk> {
  if (USE_MOCK) return mockApi.updateChunk(chunkId, patch)
  return (await http.patch(`/chunks/${chunkId}`, patch)) as Chunk
}

export async function hitTesting(
  datasetId: string,
  query: string,
  topK = 5,
): Promise<{ items: { chunk: Chunk; score: number }[] }> {
  if (USE_MOCK) return mockApi.hitTesting(datasetId, query, topK)
  return (await http.post(`/datasets/${datasetId}/hit-testing`, { query, top_k: topK })) as {
    items: { chunk: Chunk; score: number }[]
  }
}

/* ============ 工作流 ============ */

export async function listWorkflows(): Promise<Workflow[]> {
  if (USE_MOCK) return mockApi.listWorkflows()
  return (await http.get('/workflows')) as Workflow[]
}

export async function getWorkflow(id: string): Promise<Workflow> {
  if (USE_MOCK) return mockApi.getWorkflow(id)
  return (await http.get(`/workflows/${id}`)) as Workflow
}

export async function createWorkflow(body: {
  name: string
  description?: string
  from_workflow_id?: string
}): Promise<Workflow> {
  if (USE_MOCK) return mockApi.createWorkflow(body)
  return (await http.post('/workflows', body)) as Workflow
}

export async function updateWorkflow(id: string, patch: Partial<Workflow>): Promise<Workflow> {
  if (USE_MOCK) return mockApi.updateWorkflow(id, patch)
  return (await http.patch(`/workflows/${id}`, patch)) as Workflow
}

export async function deleteWorkflow(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteWorkflow(id)
  await http.delete(`/workflows/${id}`)
}

/* ============ 模型 / 供应商 / 提示词 / 文件 ============ */

export async function listModels(): Promise<ModelInfo[]> {
  if (USE_MOCK) return mockApi.listModels()
  return (await http.get('/models')) as ModelInfo[]
}

export async function getModelSettings(): Promise<ModelSettings> {
  if (USE_MOCK) return mockApi.getModelSettings()
  return (await http.get('/settings/models')) as ModelSettings
}

export async function setModelSettings(patch: Partial<ModelSettings>): Promise<ModelSettings> {
  if (USE_MOCK) return mockApi.setModelSettings(patch)
  return (await http.put('/settings/models', patch)) as ModelSettings
}

export async function pingModel(id: string): Promise<{ latency_ms: number }> {
  if (USE_MOCK) return mockApi.pingModel(id)
  return (await http.post(`/models/${encodeURIComponent(id)}/ping`)) as { latency_ms: number }
}

export async function listProviders(): Promise<ModelProvider[]> {
  if (USE_MOCK) return mockApi.listProviders()
  return (await http.get('/providers')) as ModelProvider[]
}

export async function addProvider(body: {
  name: string
  base_url: string
  api_key?: string
  type?: 'ollama' | 'openai_compat'
}): Promise<ModelProvider> {
  if (USE_MOCK) return mockApi.addProvider(body)
  return (await http.post('/providers', body)) as ModelProvider
}

export async function updateProvider(id: string, patch: Partial<ModelProvider>): Promise<ModelProvider> {
  if (USE_MOCK) return mockApi.updateProvider(id, patch)
  return (await http.patch(`/providers/${id}`, patch)) as ModelProvider
}

export async function deleteProvider(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deleteProvider(id)
  await http.delete(`/providers/${id}`)
}

export async function refreshProvider(id: string): Promise<ModelProvider> {
  if (USE_MOCK) return mockApi.refreshProvider(id)
  return (await http.post(`/providers/${id}/refresh`)) as ModelProvider
}

export async function pingProvider(id: string): Promise<{ latency_ms: number }> {
  if (USE_MOCK) return mockApi.pingModel(id)
  return (await http.post(`/providers/${id}/ping`)) as { latency_ms: number }
}

/** 拉取远端供应商的模型名列表（只列不存，供「添加模型」点选） */
export async function fetchProviderRemoteModels(providerId: string): Promise<string[]> {
  if (USE_MOCK) return mockApi.fetchRemoteModels(providerId)
  const r = (await http.post(`/providers/${providerId}/remote-models`)) as { models: string[] }
  return r.models
}

export async function addProviderModel(
  providerId: string,
  model: { id?: string; name: string; capabilities?: string[] },
): Promise<ModelInfo> {
  if (USE_MOCK) return mockApi.addProviderModel(providerId, model)
  return (await http.post(`/providers/${providerId}/models`, model)) as ModelInfo
}

export async function removeProviderModel(providerId: string, modelId: string): Promise<void> {
  if (USE_MOCK) return mockApi.removeProviderModel(providerId, modelId)
  await http.delete(`/providers/${providerId}/models/${encodeURIComponent(modelId)}`)
}

export async function uploadFile(file: File): Promise<{ file_id: string; filename: string; size: number }> {
  if (USE_MOCK) return mockApi.uploadFile(file.name, file.size)
  const form = new FormData()
  form.append('file', file, file.name)
  return (await http.post('/files', form)) as { file_id: string; filename: string; size: number }
}

export async function listPrompts(): Promise<Prompt[]> {
  if (USE_MOCK) return mockApi.listPrompts()
  return (await http.get('/prompts')) as Prompt[]
}

export async function createPrompt(body: { name: string; content: string; category?: string }): Promise<Prompt> {
  if (USE_MOCK) return mockApi.createPrompt(body)
  return (await http.post('/prompts', body)) as Prompt
}

export async function deletePrompt(id: string): Promise<void> {
  if (USE_MOCK) return mockApi.deletePrompt(id)
  await http.delete(`/prompts/${id}`)
}

/* ============ 当前用户 ============ */

/** 登录后把 ID Token 中的昵称/邮箱/头像同步到后端（access token 不含这些资料） */
/** 同步资料并返回后端用户（含角色：后端 ADMIN_SUBS 也能授予管理员） */
export async function syncProfile(profile: {
  nickname?: string
  email?: string
  avatar?: string
}): Promise<{ role: 'user' | 'admin' } | null> {
  if (USE_MOCK) return null
  return (await http.put('/users/me', profile)) as { role: 'user' | 'admin' }
}

/* ============ 服务状态与模型连接向导 ============ */

export async function getHealth(): Promise<Health> {
  if (USE_MOCK) return mockApi.getHealth()
  return (await http.get('/health')) as Health
}

/** 服务端探测 Ollama（管理员）；不传地址时自动尝试常见本机地址 */
export async function detectOllama(baseUrl?: string): Promise<OllamaProbe> {
  if (USE_MOCK) return mockApi.detectOllama(baseUrl)
  return (await http.post('/providers/ollama/detect', { base_url: baseUrl || undefined })) as OllamaProbe
}

/** 浏览器直连本机模型：服务端组装上下文（智能体提示词 / 附件 / 知识库检索） */
export async function chatPrepare(body: ChatCompletionRequest): Promise<ChatPrepared> {
  return (await http.post('/chat/prepare', body)) as ChatPrepared
}

export async function chatCommit(body: {
  conversation_id: string
  assistant_id: string
  model: string
  content: string
  reasoning?: string
  status: 'done' | 'aborted' | 'error'
  usage?: { prompt_tokens: number; completion_tokens: number }
  citations?: unknown
}): Promise<void> {
  await http.post('/chat/commit', body)
}

/* ============ 管理后台 ============ */

export async function listAdminUsers(): Promise<AdminUser[]> {
  if (USE_MOCK) return mockApi.listAdminUsers()
  return (await http.get('/admin/users')) as AdminUser[]
}

export async function setUserStatus(id: string, status: 'active' | 'disabled'): Promise<void> {
  if (USE_MOCK) return mockApi.setUserStatus(id, status)
  await http.patch(`/admin/users/${id}`, { status })
}

export async function getUsageStats(): Promise<UsagePoint[]> {
  if (USE_MOCK) return mockApi.getUsageStats()
  return (await http.get('/admin/stats/usage')) as UsagePoint[]
}

export async function getModelDist(): Promise<ModelDist[]> {
  if (USE_MOCK) return mockApi.getModelDist()
  return (await http.get('/admin/stats/models')) as ModelDist[]
}

export { delay }
