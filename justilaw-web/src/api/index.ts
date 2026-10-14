import { USE_MOCK, delay, http } from './client'
import { mockApi } from '@/mocks/mock-api'
import type { Agent, Chunk, Conversation, Dataset, Document, ModelInfo, Message, Prompt } from '@/types/api'

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

/* ============ 智能体 ============ */

export async function listAgents(): Promise<Agent[]> {
  if (USE_MOCK) return mockApi.listAgents()
  return (await http.get('/agents')) as Agent[]
}

export async function getAgent(id: string): Promise<Agent> {
  if (USE_MOCK) return mockApi.getAgent(id)
  return (await http.get(`/agents/${id}`)) as Agent
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

export async function listDocuments(datasetId: string): Promise<Document[]> {
  if (USE_MOCK) return mockApi.listDocuments(datasetId)
  return (await http.get(`/datasets/${datasetId}/documents`)) as Document[]
}

export async function uploadDocument(datasetId: string, filename: string, size: number): Promise<Document> {
  if (USE_MOCK) return mockApi.uploadDocument(datasetId, filename, size)
  const form = new FormData()
  form.append('file', new Blob([filename]), filename)
  return (await http.post(`/datasets/${datasetId}/documents`, form)) as Document
}

export async function listChunks(documentId: string): Promise<Chunk[]> {
  if (USE_MOCK) return mockApi.listChunks(documentId)
  return (await http.get(`/documents/${documentId}/chunks`)) as Chunk[]
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

/* ============ 模型 / 提示词 ============ */

export async function listModels(): Promise<ModelInfo[]> {
  if (USE_MOCK) return mockApi.listModels()
  return (await http.get('/models')) as ModelInfo[]
}

export async function pingModel(id: string): Promise<{ latency_ms: number }> {
  if (USE_MOCK) return mockApi.pingModel(id)
  return (await http.post(`/models/${id}/ping`)) as { latency_ms: number }
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

export { delay }
