import { create } from 'zustand'
import type { Citation, MessageCard } from '@/types/api'

export interface DraftMessage {
  id: string
  content: string
  reasoning?: string
  citations?: Citation[]
  card?: MessageCard
  status: 'streaming' | 'error' | 'aborted'
}

/** 输入框预填（用于推荐问题、智能体开场引导自动发送） */
export interface Prefill {
  text: string
  autoSend: boolean
  nonce: number
}

interface ChatState {
  /** 流式草稿，按会话 ID 隔离：切换会话不丢正在生成的内容 */
  drafts: Record<string, DraftMessage | undefined>
  /** 输入框预填指令 */
  prefill?: Prefill
  setDraft: (conversationId: string, draft: DraftMessage) => void
  patchDraft: (conversationId: string, patch: Partial<DraftMessage>) => void
  appendContent: (conversationId: string, delta: string) => void
  clearDraft: (conversationId: string) => void
  setPrefill: (text: string, autoSend?: boolean) => void
  consumePrefill: () => void
}

export const useChatStore = create<ChatState>()((set) => ({
  drafts: {},
  prefill: undefined,

  setDraft: (conversationId, draft) =>
    set((s) => ({ drafts: { ...s.drafts, [conversationId]: draft } })),

  patchDraft: (conversationId, patch) =>
    set((s) => {
      const draft = s.drafts[conversationId]
      if (!draft) return s
      return { drafts: { ...s.drafts, [conversationId]: { ...draft, ...patch } } }
    }),

  appendContent: (conversationId, delta) =>
    set((s) => {
      const draft = s.drafts[conversationId]
      if (!draft) return s
      return { drafts: { ...s.drafts, [conversationId]: { ...draft, content: draft.content + delta } } }
    }),

  clearDraft: (conversationId) =>
    set((s) => ({ drafts: { ...s.drafts, [conversationId]: undefined } })),

  setPrefill: (text, autoSend = false) =>
    set({ prefill: { text, autoSend, nonce: Date.now() } }),

  consumePrefill: () => set({ prefill: undefined }),
}))
