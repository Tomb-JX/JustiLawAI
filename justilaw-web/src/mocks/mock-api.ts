/**
 * 内置 Mock API：按 docs/02-design/api-contract.md 契约实现，
 * 内存态数据（刷新重置）。后端就绪后 VITE_USE_MOCK=false 即整体下线。
 */
import { delay, nowISO } from '@/api/client'
import { uid } from '@/lib/utils'
import {
  adminUsers,
  agents,
  chunks,
  conversations,
  datasets,
  documents,
  messages,
  modelDist,
  models,
  prompts,
  usageStats,
  workflows,
} from './data'
import type {
  AdminUser,
  Agent,
  Chunk,
  Conversation,
  Dataset,
  Document,
  DocumentStatus,
  ModelDist,
  ModelInfo,
  ModelProvider,
  ModelSettings,
  Message,
  Prompt,
  UsagePoint,
  Workflow,
} from '@/types/api'

function sortConversations(list: Conversation[]): Conversation[] {
  return [...list].sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      b.last_message_at.localeCompare(a.last_message_at),
  )
}

/* 供应商 / 默认模型（内存态） */
const mockProviders: ModelProvider[] = [
  {
    id: 'justilaw',
    name: 'JustiLawAI（演示）',
    type: 'openai_compat',
    base_url: 'https://api.justilaw.ai/v1',
    api_key: '',
    enabled: true,
    models: models.map((m) => ({
      id: m.id,
      name: m.name,
      capabilities: m.capabilities ?? ['completion'],
      default_params: m.default_params,
    })),
  },
]
const mockModelSettings: ModelSettings = { default_chat_model: models[0]?.id ?? null, default_embed_model: null }

const sleep = () => delay(120 + Math.random() * 260)

/** 无预置分段的文档按需生成分段（模拟切片结果） */
const SAMPLE_TEXTS = [
  '第十条 治安管理处罚的种类分为：（一）警告；（二）罚款；（三）行政拘留；（四）吊销公安机关发放的许可证。对违反治安管理的外国人，可以附加适用限期出境或者驱逐出境。',
  '第十九条 违反治安管理有下列情形之一的，减轻处罚或者不予处罚：（一）情节特别轻微的；（二）主动消除或者减轻违法后果，并取得被侵害人谅解的；（三）出于他人胁迫或者诱骗的。',
  '第七十条 以营利为目的，为赌博提供条件的，或者参与赌博赌资较大的，处五日以下拘留或者五百元以下罚款；情节严重的，处十日以上十五日以下拘留，并处五百元以上三千元以下罚款。',
  '第七十二条 明知是赌博赃物而窝藏、转移或者代为销售的，依照有关规定处罚。参与赌博且赌资巨大、多次参与赌博经处罚不改的，从重处罚。',
  '（典型案例）李某在经营棋牌室期间，以每桌抽取 50 元的方式渔利，累计 3.8 万元。公安机关认定其构成为赌博提供条件，情节严重，处行政拘留十二日，并处罚款 2000 元。',
  '（典型案例）张某利用微信群组织"接龙押注"式赌博，参赌人员 40 余人，赌资流水 20 余万元，人民法院以开设赌场罪判处有期徒刑十个月，并处罚金 2 万元。',
]

function ensureChunks(documentId: string): Chunk[] {
  const own = chunks.filter((c) => c.document_id === documentId)
  if (own.length > 0) return own
  for (let i = 0; i < 6; i++) {
    chunks.push({
      id: uid('ch'),
      document_id: documentId,
      index: i + 1,
      enabled: true,
      content: SAMPLE_TEXTS[i % SAMPLE_TEXTS.length],
    })
  }
  return chunks.filter((c) => c.document_id === documentId)
}

export const mockApi = {
  async getHealth() {
    await delay(50)
    return {
      status: 'up' as const,
      auth_enabled: true,
      setup_required: false,
      ollama: { enabled: true, reachable: true, version: 'mock', base_url: null },
      default_chat_model: mockModelSettings.default_chat_model,
      default_embed_model: mockModelSettings.default_embed_model,
      warnings: [],
    }
  },

  async detectOllama(baseUrl?: string) {
    await delay(300)
    return {
      base_url: baseUrl || 'http://127.0.0.1:11434',
      reachable: true,
      version: 'mock',
      models: ['qwen3.5:9b', 'bge-m3:latest'],
      error: null,
    }
  },

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

  async clearMessages(conversationId: string): Promise<void> {
    await delay(60)
    messages[conversationId] = []
  },

  async deleteMessage(conversationId: string, messageId: string): Promise<void> {
    await delay(60)
    const list = messages[conversationId]
    if (list) messages[conversationId] = list.filter((m) => m.id !== messageId)
  },

  async setMessageFeedback(conversationId: string, messageId: string, rating: 'up' | 'down' | null): Promise<void> {
    await delay(60)
    const m = (messages[conversationId] ?? []).find((x) => x.id === messageId)
    if (!m) throw new Error('消息不存在')
    if (rating) m.feedback = rating
    else m.feedback = null
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

  async createAgent(body: Partial<Agent>): Promise<Agent> {
    await delay(150)
    const agent: Agent = {
      ...body,
      id: uid('a'),
      name: body.name ?? '未命名智能体',
      category: body.category ?? '法律咨询',
      description: body.description ?? '',
      system_prompt: body.system_prompt ?? '你是法律智能助手。',
      opening_statement: body.opening_statement,
      suggested_questions: body.suggested_questions ?? [],
      tool_ids: body.tool_ids ?? [],
      dataset_ids: body.dataset_ids ?? [],
      scope: body.scope ?? 'private',
      status: 'draft',
      usage_count: 0,
      // mock 内存库拿不到登录态：以 u_me 标记「本人创建」，配合 isMine() 判定归属
      created_by: 'u_me',
      created_at: nowISO(),
    }
    agents.unshift(agent)
    return agent
  },

  async updateAgent(id: string, patch: Partial<Agent>): Promise<Agent> {
    await delay(100)
    const agent = agents.find((a) => a.id === id)
    if (!agent) throw new Error('智能体不存在')
    Object.assign(agent, patch)
    return agent
  },

  async deleteAgent(id: string): Promise<void> {
    await delay(80)
    const idx = agents.findIndex((a) => a.id === id)
    if (idx >= 0) agents.splice(idx, 1)
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

  async createDataset(body: Partial<Dataset>): Promise<Dataset> {
    await delay(150)
    const ds: Dataset = {
      id: uid('d'),
      name: body.name ?? '未命名知识库',
      description: body.description,
      chunk_config: body.chunk_config ?? { max_length: 500, overlap: 50 },
      retrieval_config: body.retrieval_config ?? { top_k: 5, score_threshold: 0.6 },
      doc_count: 0,
      created_at: nowISO(),
    }
    datasets.unshift(ds)
    return ds
  },

  async updateDataset(id: string, patch: Partial<Dataset>): Promise<Dataset> {
    await delay(100)
    const ds = datasets.find((d) => d.id === id)
    if (!ds) throw new Error('知识库不存在')
    Object.assign(ds, patch)
    return ds
  },

  async deleteDataset(id: string): Promise<void> {
    await delay(80)
    const idx = datasets.findIndex((d) => d.id === id)
    if (idx >= 0) datasets.splice(idx, 1)
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

  async deleteDocument(documentId: string): Promise<void> {
    await delay(80)
    const idx = documents.findIndex((d) => d.id === documentId)
    if (idx >= 0) {
      const ds = datasets.find((d) => d.id === documents[idx].dataset_id)
      if (ds) ds.doc_count = Math.max(0, ds.doc_count - 1)
      documents.splice(idx, 1)
    }
  },

  async listChunks(documentId: string): Promise<Chunk[]> {
    await sleep()
    return [...ensureChunks(documentId)]
  },

  async updateChunk(chunkId: string, patch: { enabled?: boolean; content?: string }): Promise<Chunk> {
    await delay(60)
    const chunk = chunks.find((c) => c.id === chunkId)
    if (!chunk) throw new Error('分段不存在')
    Object.assign(chunk, patch)
    return chunk
  },

  async hitTesting(
    datasetId: string,
    query: string,
    topK = 5,
  ): Promise<{ items: { chunk: Chunk; score: number }[] }> {
    await delay(500 + Math.random() * 400)
    const docs = documents.filter((d) => d.dataset_id === datasetId)
    docs.forEach((d) => ensureChunks(d.id))
    const pool = chunks.filter((c) => docs.some((d) => d.id === c.document_id && d.status === 'completed'))
    // 模拟语义匹配：命中"赌博/赌"关键词的片段排前
    const scored = pool.map((chunk, i) => {
      const keywordHit = /赌|拘留|罚款|刑法|治安/.test(query) && /赌|拘留|罚款/.test(chunk.content)
      const score = Math.max(0.35, (keywordHit ? 0.92 : 0.62) - i * 0.04 - Math.random() * 0.05)
      return { chunk, score: Number(score.toFixed(2)) }
    })
    scored.sort((a, b) => b.score - a.score)
    return { items: scored.slice(0, topK) }
  },

  /* ---- 工作流 ---- */
  async listWorkflows(): Promise<Workflow[]> {
    await sleep()
    return [...workflows]
  },

  async getWorkflow(id: string): Promise<Workflow> {
    await sleep()
    const wf = workflows.find((w) => w.id === id)
    if (!wf) throw new Error('工作流不存在')
    return wf
  },

  async createWorkflow(body: { name: string; description?: string; from_workflow_id?: string }): Promise<Workflow> {
    await delay(120)
    const source = body.from_workflow_id ? workflows.find((w) => w.id === body.from_workflow_id) : undefined
    const wf: Workflow = {
      id: uid('w'),
      name: body.name,
      description: body.description ?? source?.description ?? '',
      status: 'draft',
      created_at: nowISO(),
      dsl: source
        ? JSON.parse(JSON.stringify(source.dsl))
        : {
            nodes: [
              { id: 'nd_1', type: 'workflow' as const, position: { x: 0, y: 200 }, data: { nodeType: 'start' as const, name: '开始', config: { vars: [{ name: 'query', label: '输入' }] } } },
              { id: 'nd_2', type: 'workflow' as const, position: { x: 240, y: 200 }, data: { nodeType: 'reply' as const, name: '直接回复', config: {} } },
            ],
            edges: [{ id: uid('e'), source: 'nd_1', target: 'nd_2' }],
          },
    }
    workflows.unshift(wf)
    return wf
  },

  async updateWorkflow(id: string, patch: Partial<Workflow>): Promise<Workflow> {
    await delay(120)
    const wf = workflows.find((w) => w.id === id)
    if (!wf) throw new Error('工作流不存在')
    Object.assign(wf, patch)
    return wf
  },

  async deleteWorkflow(id: string): Promise<void> {
    await delay(80)
    const idx = workflows.findIndex((w) => w.id === id)
    if (idx >= 0) workflows.splice(idx, 1)
  },

  /* ---- 模型 / 提示词 / 文件 ---- */
  async listModels(): Promise<ModelInfo[]> {
    await sleep()
    return [...models]
  },

  async pingModel(_id: string): Promise<{ latency_ms: number }> {
    await delay(300)
    return { latency_ms: 40 + Math.floor(Math.random() * 160) }
  },

  async getModelSettings(): Promise<ModelSettings> {
    await delay(60)
    return { ...mockModelSettings }
  },

  async setModelSettings(patch: Partial<ModelSettings>): Promise<ModelSettings> {
    await delay(80)
    Object.assign(mockModelSettings, patch)
    return { ...mockModelSettings }
  },

  async listProviders(): Promise<ModelProvider[]> {
    await sleep()
    return mockProviders.map((p) => ({ ...p, models: [...p.models] }))
  },

  async addProvider(body: { name: string; base_url: string; api_key?: string }): Promise<ModelProvider> {
    await delay(120)
    const p: ModelProvider = {
      id: uid('custom'),
      name: body.name,
      type: 'openai_compat',
      base_url: body.base_url.replace(/\/+$/, ''),
      api_key: body.api_key ? `********${body.api_key.slice(-4)}` : '',
      enabled: true,
      models: [],
    }
    mockProviders.push(p)
    return p
  },

  async updateProvider(id: string, patch: Partial<ModelProvider>): Promise<ModelProvider> {
    await delay(80)
    const p = mockProviders.find((x) => x.id === id)
    if (!p) throw new Error('供应商不存在')
    Object.assign(p, patch)
    return p
  },

  async deleteProvider(id: string): Promise<void> {
    await delay(80)
    const idx = mockProviders.findIndex((p) => p.id === id)
    if (idx >= 0) mockProviders.splice(idx, 1)
  },

  async refreshProvider(id: string): Promise<ModelProvider> {
    await delay(200)
    const p = mockProviders.find((x) => x.id === id)
    if (!p) throw new Error('供应商不存在')
    return p
  },

  async fetchRemoteModels(id: string): Promise<string[]> {
    await delay(300)
    const p = mockProviders.find((x) => x.id === id)
    if (!p) throw new Error('供应商不存在')
    return ['glm-4-plus', 'glm-4-air', 'glm-4-flash', 'embedding-3']
  },

  async addProviderModel(
    providerId: string,
    model: { id?: string; name: string; capabilities?: string[] },
  ): Promise<ModelInfo> {
    await delay(80)
    const p = mockProviders.find((x) => x.id === providerId)
    if (!p) throw new Error('供应商不存在')
    const entry = {
      id: `${providerId}/${model.id ?? model.name}`,
      name: model.name,
      capabilities: model.capabilities ?? ['completion'],
      default_params: { temperature: 0.7, top_p: 0.9, max_tokens: 2048 },
    }
    p.models = [...p.models.filter((m) => m.id !== entry.id), entry]
    return { ...entry, provider: p.id, provider_name: p.name }
  },

  async removeProviderModel(providerId: string, modelId: string): Promise<void> {
    await delay(80)
    const p = mockProviders.find((x) => x.id === providerId)
    if (p) p.models = p.models.filter((m) => m.id !== modelId)
  },

  async reindexDataset(datasetId: string, embedModel?: string): Promise<{ chunk_count: number; embed_model: string }> {
    await delay(800)
    const ds = datasets.find((d) => d.id === datasetId)
    if (ds && embedModel) ds.embed_model = embedModel
    return { chunk_count: 0, embed_model: embedModel ?? ds?.embed_model ?? '' }
  },

  async uploadFile(filename: string, size: number): Promise<{ file_id: string; filename: string; size: number }> {
    await delay(400 + Math.random() * 600)
    return { file_id: uid('f'), filename, size }
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

  /* ---- 管理后台 ---- */
  async listAdminUsers(): Promise<AdminUser[]> {
    await sleep()
    return [...adminUsers]
  },

  async setUserStatus(id: string, status: 'active' | 'disabled'): Promise<void> {
    await delay(80)
    const u = adminUsers.find((x) => x.id === id)
    if (u) u.status = status
  },

  async setUserRole(id: string, role: 'user' | 'admin'): Promise<void> {
    await delay(80)
    const u = adminUsers.find((x) => x.id === id)
    if (u) u.role = role
  },

  async getUsageStats(): Promise<UsagePoint[]> {
    await sleep()
    return [...usageStats]
  },

  async getModelDist(): Promise<ModelDist[]> {
    await sleep()
    return [...modelDist]
  },
}

export type { DocumentStatus }
