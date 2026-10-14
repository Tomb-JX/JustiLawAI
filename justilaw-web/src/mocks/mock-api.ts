/**
 * 内置 Mock API：按 docs/02-design/api-contract.md 契约实现，
 * 内存态数据（刷新重置）。后端就绪后 VITE_USE_MOCK=false 即整体下线。
 */
import { delay, nowISO } from '@/api/client'
import { uid } from '@/lib/utils'
import {
  agents,
  chunks,
  conversations,
  datasets,
  documents,
  messages,
  models,
  prompts,
} from './data'
import type {
  Agent,
  Chunk,
  Conversation,
  Dataset,
  Document,
  DocumentStatus,
  ModelInfo,
  Message,
  Prompt,
} from '@/types/api'

function sortConversations(list: Conversation[]): Conversation[] {
  return [...list].sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      b.last_message_at.localeCompare(a.last_message_at),
  )
}

const sleep = () => delay(120 + Math.random() * 260)

export const mockApi = {
  /* ---- 会话 ---- */
  async listConversations(): Promise<Conversation[]> {
    await sleep()
    return sortConversations(conversations)
  },

  async createConversation(body: { title?: string; agent_id?: string }): Promise<Conversation> {
    await delay(80)
    const conv: Conversation = {
      id: uid('c'),
      title: body.title?.slice(0, 30) || '新对话',
      agent_id: body.agent_id,
      pinned: false,
      last_message_at: nowISO(),
      created_at: nowISO(),
    }
    conversations.unshift(conv)
    messages[conv.id] = []
    return conv
  },

  async updateConversation(id: string, patch: { title?: string; pinned?: boolean }): Promise<Conversation> {
    await delay(60)
    const conv = conversations.find((c) => c.id === id)
    if (!conv) throw new Error('会话不存在')
    Object.assign(conv, patch)
    return conv
  },

  async deleteConversation(id: string): Promise<void> {
    await delay(60)
    const idx = conversations.findIndex((c) => c.id === id)
    if (idx >= 0) conversations.splice(idx, 1)
    delete messages[id]
  },

  async listMessages(conversationId: string): Promise<Message[]> {
    await sleep()
    return [...(messages[conversationId] ?? [])]
  },

  /* ---- 智能体 ---- */
  async listAgents(): Promise<Agent[]> {
    await sleep()
    return [...agents]
  },

  async getAgent(id: string): Promise<Agent> {
    await sleep()
    const agent = agents.find((a) => a.id === id)
    if (!agent) throw new Error('智能体不存在')
    return agent
  },

  /* ---- 知识库 ---- */
  async listDatasets(): Promise<Dataset[]> {
    await sleep()
    return [...datasets]
  },

  async getDataset(id: string): Promise<Dataset> {
    await sleep()
    const ds = datasets.find((d) => d.id === id)
    if (!ds) throw new Error('知识库不存在')
    return ds
  },

  async listDocuments(datasetId: string): Promise<Document[]> {
    await sleep()
    return documents.filter((d) => d.dataset_id === datasetId)
  },

  async uploadDocument(datasetId: string, filename: string, size: number): Promise<Document> {
    await delay(200)
    const doc: Document = {
      id: uid('doc'),
      dataset_id: datasetId,
      filename,
      size,
      status: 'parsing',
      chunk_count: 0,
      created_at: nowISO(),
    }
    documents.unshift(doc)
    const ds = datasets.find((d) => d.id === datasetId)
    if (ds) ds.doc_count += 1
    // 模拟解析完成（前端轮询可见状态流转）
    setTimeout(() => {
      doc.status = 'completed'
      doc.chunk_count = 40 + Math.floor(Math.random() * 200)
    }, 3500)
    return doc
  },

  async listChunks(documentId: string): Promise<Chunk[]> {
    await sleep()
    return chunks.filter((c) => c.document_id === documentId)
  },

  async hitTesting(
    datasetId: string,
    query: string,
    topK = 5,
  ): Promise<{ items: { chunk: Chunk; score: number }[] }> {
    await delay(500 + Math.random() * 400)
    const pool = chunks.filter((c) =>
      documents.some((d) => d.id === c.document_id && d.dataset_id === datasetId),
    )
    // 模拟语义匹配：命中"赌博/赌"关键词的片段排前
    const scored = pool.map((chunk, i) => {
      const keywordHit = /赌|拘留|罚款|刑法|治安/.test(query) && /赌|拘留|罚款/.test(chunk.content)
      const score = Math.max(0.35, (keywordHit ? 0.92 : 0.62) - i * 0.04 - Math.random() * 0.05)
      return { chunk, score: Number(score.toFixed(2)) }
    })
    scored.sort((a, b) => b.score - a.score)
    return { items: scored.slice(0, topK) }
  },

  /* ---- 模型 / 提示词 ---- */
  async listModels(): Promise<ModelInfo[]> {
    await sleep()
    return [...models]
  },

  async pingModel(_id: string): Promise<{ latency_ms: number }> {
    await delay(300)
    return { latency_ms: 40 + Math.floor(Math.random() * 160) }
  },

  async listPrompts(): Promise<Prompt[]> {
    await sleep()
    return [...prompts]
  },

  async createPrompt(body: { name: string; content: string; category?: string }): Promise<Prompt> {
    await delay(80)
    const prompt: Prompt = {
      id: uid('p'),
      name: body.name,
      content: body.content,
      category: body.category ?? '常用',
      starred: false,
    }
    prompts.unshift(prompt)
    return prompt
  },

  async deletePrompt(id: string): Promise<void> {
    await delay(60)
    const idx = prompts.findIndex((p) => p.id === id)
    if (idx >= 0) prompts.splice(idx, 1)
  },
}

export type { DocumentStatus }
