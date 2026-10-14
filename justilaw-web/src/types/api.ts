/**
 * API 契约类型定义（与 docs/02-design/api-contract.md 保持一致）
 * 字段命名遵循契约约定：snake_case
 */

export interface User {
  id: string
  username: string
  nickname: string
  avatar?: string
  role: 'user' | 'admin'
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  agent_id?: string
  pinned: boolean
  last_message_at: string
  created_at: string
}

export interface Citation {
  index: number
  source: string
  snippet: string
  score: number
  doc_id?: string
  chunk_id?: string
}

export interface Attachment {
  file_id: string
  filename: string
  size: number
}

// ---------- 结构化输出卡片 ----------

export interface PredictionPayload {
  crime: string
  confidence: number
  punishment: {
    type: string
    detention_days?: [number, number]
    fine?: [number, number]
  }
  basis: string[]
  note?: string
}

export interface CaseItem {
  case_no: string
  court: string
  summary: string
  result: string
  score: number
}

export interface RiskItem {
  clause: string
  position: string
  level: 'high' | 'medium' | 'low'
  suggestion: string
}

export interface DocumentPayload {
  title: string
  doc_type: string
  content: string
}

export type MessageCard = {
  card_type: 'prediction' | 'case_list' | 'risk_list' | 'document'
  payload: PredictionPayload | CaseItem[] | RiskItem[] | DocumentPayload | Record<string, unknown>
}

export type MessageStatus = 'streaming' | 'done' | 'error' | 'aborted'

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content_type: 'markdown' | 'card'
  content: string
  card?: MessageCard
  citations?: Citation[]
  reasoning?: string
  attachments?: Attachment[]
  status: MessageStatus
  usage?: { prompt_tokens: number; completion_tokens: number }
  created_at: string
}

export interface Agent {
  id: string
  name: string
  avatar?: string
  category: string
  description: string
  system_prompt: string
  opening_statement?: string
  suggested_questions?: string[]
  tool_ids: string[]
  dataset_ids: string[]
  scope: 'private' | 'org' | 'public'
  status: 'draft' | 'published' | 'offline'
  usage_count: number
  created_by: string
  created_at: string
}

export interface WorkflowNode {
  id: string
  /** 画布渲染节点类型，固定为 'workflow'；语义类型在 data.nodeType */
  type: 'workflow'
  position: { x: number; y: number }
  data: {
    nodeType: 'start' | 'llm' | 'retrieval' | 'branch' | 'http' | 'template' | 'aggregate' | 'reply'
    name: string
    config: Record<string, unknown>
  }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
}

export interface Workflow {
  id: string
  name: string
  description: string
  dsl: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }
  status: 'draft' | 'published'
  created_at: string
}

export interface Dataset {
  id: string
  name: string
  description?: string
  chunk_config: { max_length: number; overlap: number }
  retrieval_config: { top_k: number; score_threshold: number }
  doc_count: number
  created_at: string
}

export type DocumentStatus = 'queued' | 'parsing' | 'completed' | 'failed'

export interface Document {
  id: string
  dataset_id: string
  filename: string
  size: number
  status: DocumentStatus
  error?: string
  chunk_count: number
  created_at: string
}

export interface Chunk {
  id: string
  document_id: string
  index: number
  content: string
  enabled: boolean
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
  provider_name?: string
  provider_type?: string
  capabilities?: string[]
  description?: string
  default_params: { temperature: number; top_p: number; max_tokens: number }
}

/** 模型供应商（自定义 API 配置，对齐主流智能体平台） */
export interface ModelProvider {
  id: string
  name: string
  type: 'ollama' | 'openai_compat'
  base_url: string
  api_key: string
  enabled: boolean
  models: {
    id: string
    name: string
    capabilities: string[]
    default_params: { temperature: number; top_p: number; max_tokens: number }
  }[]
}

export interface Prompt {
  id: string
  name: string
  content: string
  category: string
  starred: boolean
}

// ---------- 管理后台 ----------

export interface AdminUser {
  id: string
  username: string
  nickname: string
  role: 'user' | 'admin'
  status: 'active' | 'disabled'
  agent_count: number
  created_at: string
}

export interface UsagePoint {
  date: string
  calls: number
}

export interface ModelDist {
  name: string
  value: number
}

// ---------- 对话补全请求 ----------

export interface ChatCompletionRequest {
  conversation_id: string
  agent_id?: string
  model: string
  messages: { role: 'user' | 'assistant' | 'system'; content: string }[]
  stream: true
  params: { temperature: number; top_p: number; max_tokens: number }
  thinking?: boolean
  retrieval?: { dataset_ids: string[]; top_k: number }
  attachments?: { file_id: string; filename: string }[]
}
