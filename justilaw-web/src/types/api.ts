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
  /** 用户反馈：点赞 / 点踩 / 未反馈 */
  feedback?: 'up' | 'down' | null
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
  /** 建库时绑定的嵌入模型（平台模型 ID），更换需重建索引 */
  embed_model?: string
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

/** GET /providers/{pid}/remote-models 条目：能力标签由服务端读模型服务返回字段自动识别 */
export interface RemoteModel {
  id: string
  capabilities: string[]
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
  /** 自动发现供应商（Ollama）最近一次连接结果；未检测过为 null */
  status?: { reachable: boolean; version: string | null; error: string | null } | null
}

/** GET /health：登录前即可调用，前端据此判断单机模式与是否需要模型连接向导 */
export interface Health {
  status: 'up' | 'degraded'
  auth_enabled: boolean
  setup_required: boolean
  ollama: { enabled: boolean; reachable: boolean | null; version: string | null; base_url: string | null }
  default_chat_model: string | null
  default_embed_model: string | null
  warnings: string[]
}

/** Ollama 地址探测结果（服务端 /providers/ollama/detect 与浏览器直连检测共用） */
export interface OllamaProbe {
  base_url: string
  reachable: boolean
  version: string | null
  models: string[]
  error: string | null
}

/** POST /chat/prepare：浏览器直连本机模型前，由服务端组装好的上下文 */
export interface ChatPrepared {
  assistant_id: string
  llm_messages: { role: 'system' | 'user' | 'assistant'; content: string }[]
  citations: Citation[] | null
  rag_error: string | null
}

export interface ModelSettings {
  default_chat_model: string | null
  default_embed_model: string | null
}

export interface Prompt {
  id: string
  name: string
  content: string
  category: string
  starred: boolean
  /** 创建者（种子提示词无此字段）；删除/编辑仅创建者或管理员可操作 */
  created_by?: string
}

// ---------- 管理后台 ----------

export interface AdminUser {
  id: string
  /** Logto 用户 sub；与前端当前用户的 id 同源，用于识别「自己」这一行 */
  logto_id?: string
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

/* ============ 裁量建议（赌博类治安处罚，引擎第一版） ============ */

export interface AmountRange {
  min: number
  max: number | null // null = 无上界（"以上"开口写法）
}

/** 与后端 norm_layer.Facts 同名；未填 = 未知（不是"否"） */
export interface DiscretionFacts {
  behavior_date: string
  decision_date?: string
  region?: string
  behavior_type: string
  age?: number
  first_offense?: boolean
  surrendered?: boolean
  truthful_statement?: boolean
  admits_and_accepts?: boolean
  minor_circumstance?: string
  personal_stake?: AmountRange
  onsite_stake_total?: AmountRange
  commission?: AmountRange
  participant_count?: number
  method?: string
  gambling_form?: string
  venue_type?: string
  civil_servant?: boolean
  minors_involved?: boolean
  profit_purpose?: boolean
  times?: number
}

export interface DiscretionMeta {
  behavior_types: string[]
  methods: string[]
  gambling_forms: string[]
  venue_types: string[]
  minor_levels: string[]
  provinces: { code: string; name: string }[]
  laws: { id: string; title: string }[]
}

export interface PenaltyOption {
  detention: [number, number] | null
  fine: [number, number] | null
  via: string
  basis: string[]
  kind: string
}

export interface DiscretionDecision {
  penalty_type: string | null
  route: 'rule_single' | 'rule_candidates' | 'model_fallback' | 'undetermined'
  candidates: string[]
  quantities: Record<string, [number, number][]>
  notes: string[]
  assessment: {
    law_id: string
    temporal_note: string
    tiers: Record<string, { options: PenaltyOption[]; detention_executable: boolean | null; not_executed_reason: string | null }>
    directions: { effect: string; trigger: string; basis: string }[]
    referral: { item: string; threshold: number | null; status: string; basis?: string }[]
    stake_threshold: {
      status?: string
      reason?: string
      bands: string[]
      band_penalty: string[]
      measures_used: string[]
      basis: string | null
      law_alignment?: string | null
      unknown_conditions: string[]
      notes: string[]
    }
    needs_review: string[]
  }
}
