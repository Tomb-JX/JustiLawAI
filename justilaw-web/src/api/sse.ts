import { fetchEventSource } from '@microsoft/fetch-event-source'
import { USE_MOCK, getAuthHeaders, http, notifyUnauthorized } from './client'
import { mockChatStream } from '@/mocks/chat-stream'
import type { ChatCompletionRequest } from '@/types/api'

export type ChatEventName =
  | 'message'
  | 'reasoning'
  | 'citations'
  | 'tool_call'
  | 'workflow'
  | 'card'
  | 'done'
  | 'error'

/**
 * 对话补全（SSE 流式）。
 * Mock 模式：由本地模拟器逐事件推送（含中断支持）；
 * 真实模式：POST /chat/completions，按契约事件流分发。
 */
export async function streamChatCompletion(
  body: ChatCompletionRequest,
  onEvent: (name: ChatEventName, data: Record<string, unknown>) => void,
  signal: AbortSignal,
): Promise<void> {
  if (USE_MOCK) {
    return mockChatStream(body, onEvent, signal)
  }

  const url = `${http.defaults.baseURL}/chat/completions`
  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await getAuthHeaders()) },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true, // 页面切后台不中断生成
    async onopen(res) {
      if (res.status === 401) notifyUnauthorized()
      if (!res.ok) throw new Error(`SSE 连接失败：HTTP ${res.status}`)
    },
    onmessage(ev) {
      if (!ev.data) return
      try {
        onEvent((ev.event || 'message') as ChatEventName, JSON.parse(ev.data))
      } catch {
        // 非 JSON 数据忽略
      }
    },
    // 抛错以终止（默认行为是无限重连）
    onerror(err) {
      throw err
    },
  })
}
