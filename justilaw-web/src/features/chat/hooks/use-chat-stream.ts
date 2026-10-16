import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { streamChatCompletion, type ChatEventName } from '@/api/sse'
import { isLocalModel, useLocalOllamaStore } from '@/features/models/local-ollama'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { nowISO } from '@/api/client'
import { uid } from '@/lib/utils'
import type { ChatCompletionRequest, Citation, Message, MessageCard, ModelInfo } from '@/types/api'
import { streamLocalChatCompletion } from './local-chat'

/** 每个会话独立的中断控制器（非响应式，不放入 store） */
const controllers = new Map<string, AbortController>()

export type SendMode = 'new' | 'regenerate'

/**
 * 对话流式核心 Hook：
 * 乐观追加用户消息 → 建立流式草稿（rAF 批量 flush）→
 * 结束/中断后以服务端落库结果刷新列表（统一数据源，避免双写去重）
 */
export function useChatStream(conversationId: string | undefined, agentId?: string) {
  const qc = useQueryClient()
  // 窄 selector 订阅：流式落盘只触发真正依赖该草稿的组件，不再全量重渲染本组件树
  const model = useSettingsStore((s) => s.model)
  const params = useSettingsStore((s) => s.params)
  const thinking = useSettingsStore((s) => s.thinking)
  const ragEnabled = useSettingsStore((s) => s.ragEnabled)
  const ragDatasetId = useSettingsStore((s) => s.ragDatasetId)

  const isStreaming = useChatStore((s) => (conversationId ? !!s.drafts[conversationId] : false))

  const stop = useCallback(() => {
    if (conversationId) controllers.get(conversationId)?.abort()
  }, [conversationId])

  const send = useCallback(
    async (content: string, mode: SendMode = 'new', attachments?: { file_id: string; filename: string }[]) => {
      if (!conversationId) return
      const cid = conversationId

      // 会话级串行：正在生成时忽略新请求
      if (controllers.has(cid)) {
        toast.warning('正在生成中，请先停止或等待完成')
        return
      }

      if (mode === 'new') {
        const userMsg: Message = {
          id: uid('m'),
          conversation_id: cid,
          role: 'user',
          content_type: 'markdown',
          content,
          attachments: attachments?.map((a) => ({ ...a, size: 0 })),
          status: 'done',
          created_at: nowISO(),
        }
        qc.setQueryData<Message[]>(['messages', cid], (old) => [...(old ?? []), userMsg])
      } else {
        // 重新生成：丢弃末尾的助手消息后重发
        qc.setQueryData<Message[]>(['messages', cid], (old) => {
          const list = [...(old ?? [])]
          while (list.length && list[list.length - 1].role === 'assistant') list.pop()
          return list
        })
      }

      const draftId = uid('m')
      useChatStore.getState().setDraft(cid, { id: draftId, content: '', status: 'streaming' })

      const ctrl = new AbortController()
      controllers.set(cid, ctrl)

      // rAF 批量 flush：避免逐 token 触发重渲染
      let buffer = ''
      let raf = 0
      const flush = () => {
        raf = 0
        if (buffer) {
          useChatStore.getState().appendContent(cid, buffer)
          buffer = ''
        }
      }
      const schedule = () => {
        if (!raf) raf = requestAnimationFrame(flush)
      }

      const history = (qc.getQueryData<Message[]>(['messages', cid]) ?? [])
        .filter((m) => m.role !== 'system')
        .map((m) => ({ role: m.role, content: m.content }))

      const req: ChatCompletionRequest = {
        conversation_id: cid,
        agent_id: agentId || undefined,
        // 未选择时交给服务端用平台默认对话模型
        model: model || '',
        messages: history,
        stream: true,
        params,
        thinking,
        attachments: attachments?.map((a) => ({ file_id: a.file_id, filename: a.filename })),
        retrieval: ragEnabled && ragDatasetId ? { dataset_ids: [ragDatasetId], top_k: 5 } : undefined,
      }

      try {
        const onEvent = (name: ChatEventName, data: Record<string, unknown>) => {
          if (name === 'message') {
            buffer += String(data.delta ?? '')
            schedule()
          } else if (name === 'reasoning') {
            flush()
            const cur = useChatStore.getState().drafts[cid]?.reasoning ?? ''
            useChatStore.getState().patchDraft(cid, { reasoning: cur + String(data.delta ?? '') })
          } else if (name === 'citations') {
            flush()
            useChatStore.getState().patchDraft(cid, { citations: data.items as Citation[] })
          } else if (name === 'card') {
            flush()
            useChatStore.getState().patchDraft(cid, {
              card: {
                card_type: data.card_type as 'prediction' | 'case_list' | 'risk_list' | 'document',
                payload: data.payload as MessageCard['payload'],
              },
            })
          } else if (name === 'tool_call' && data.status === 'failed') {
            toast.warning(String(data.message ?? '工具调用失败'))
          } else if (name === 'error') {
            throw new Error(String(data.message ?? '生成失败'))
          }
        }
        if (isLocalModel(req.model)) {
          // 本机模型：浏览器直连用户电脑上的 Ollama 推理
          const { baseUrl } = useLocalOllamaStore.getState()
          const info = qc.getQueryData<ModelInfo[]>(['local-models', baseUrl])?.find((m) => m.id === req.model)
          await streamLocalChatCompletion(
            req,
            { supportsThinking: !!info?.capabilities?.includes('thinking') },
            onEvent,
            ctrl.signal,
          )
        } else {
          await streamChatCompletion(req, onEvent, ctrl.signal)
        }
      } catch (e) {
        const aborted = ctrl.signal.aborted || (e as Error)?.name === 'AbortError'
        flush()
        useChatStore.getState().patchDraft(cid, { status: aborted ? 'aborted' : 'error' })
        if (!aborted) toast.error((e as Error)?.message ?? '生成失败，请重试')
      } finally {
        if (raf) cancelAnimationFrame(raf)
        flush()
      }

      if (ctrl.signal.aborted) useChatStore.getState().patchDraft(cid, { status: 'aborted' })

      // 服务端/Mock 已在流中落库，统一刷新保持单一数据源
      await qc.invalidateQueries({ queryKey: ['messages', cid] })
      qc.invalidateQueries({ queryKey: ['conversations'] })
      useChatStore.getState().clearDraft(cid)
      controllers.delete(cid)
    },
    [conversationId, agentId, model, params, thinking, ragEnabled, ragDatasetId, qc],
  )

  const regenerate = useCallback(async () => {
    if (!conversationId) return
    const list = qc.getQueryData<Message[]>(['messages', conversationId]) ?? []
    const lastUser = [...list].reverse().find((m) => m.role === 'user')
    if (lastUser) {
      // 附件随原用户消息一并重发，否则重新生成的回答会丢失附件上下文
      await send(
        lastUser.content,
        'regenerate',
        lastUser.attachments?.map((a) => ({ file_id: a.file_id, filename: a.filename })),
      )
    }
  }, [conversationId, qc, send])

  /** 编辑用户消息并重发：截断该消息之后的历史，以新内容重新请求 */
  const editAndResend = useCallback(
    async (messageId: string, newContent: string) => {
      if (!conversationId) return
      const list = qc.getQueryData<Message[]>(['messages', conversationId]) ?? []
      const idx = list.findIndex((m) => m.id === messageId)
      if (idx < 0) return
      const attachments = list[idx].attachments?.map((a) => ({ file_id: a.file_id, filename: a.filename }))
      qc.setQueryData<Message[]>(['messages', conversationId], list.slice(0, idx))
      await send(newContent, 'new', attachments)
    },
    [conversationId, qc, send],
  )

  return { send, stop, regenerate, editAndResend, isStreaming }
}
