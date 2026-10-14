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
  | 'progress'

type EventHandler = (name: ChatEventName, data: Record<string, unknown>) => void

/** POST 一个 SSE 接口并按事件名分发；onEvent 抛出的异常会终止整个流。 */
async function postSSE(path: string, body: unknown, onEvent: EventHandler, signal: AbortSignal): Promise<void> {
  await fetchEventSource(`${http.defaults.baseURL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await getAuthHeaders()) },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true, // 页面切后台不中断生成
    async onopen(res) {
      if (res.ok) return
      if (res.status === 401) notifyUnauthorized()
      // 非 2xx 时后端返回 { code, message } 错误包
      const detail = await res
        .json()
        .then((j: { message?: string }) => j.message)
        .catch(() => undefined)
      throw new Error(detail ?? `SSE 连接失败：HTTP ${res.status}`)
    },
    onmessage(ev) {
      if (!ev.data) return
      let data: Record<string, unknown>
      try {
        data = JSON.parse(ev.data)
      } catch {
        return // 非 JSON 数据忽略
      }
      // 不能放进上面的 try：error 事件需要抛出以终止流
      onEvent((ev.event || 'message') as ChatEventName, data)
    },
    // 抛错以终止（默认行为是无限重连）
    onerror(err) {
      throw err
    },
  })
}

/**
 * 对话补全（SSE 流式）。
 * Mock 模式：由本地模拟器逐事件推送（含中断支持）；
 * 真实模式：POST /chat/completions，按契约事件流分发。
 */
export async function streamChatCompletion(
  body: ChatCompletionRequest,
  onEvent: EventHandler,
  signal: AbortSignal,
): Promise<void> {
  if (USE_MOCK) {
    return mockChatStream(body, onEvent, signal)
  }
  await postSSE('/chat/completions', body, onEvent, signal)
}

/** 让服务端的 Ollama 下载模型：progress {status, completed?, total?} → done {model} | error */
export async function streamPullModel(
  providerId: string,
  model: string,
  onEvent: EventHandler,
  signal: AbortSignal,
): Promise<void> {
  if (USE_MOCK) {
    for (let i = 1; i <= 5; i++) {
      if (signal.aborted) return
      await new Promise((r) => setTimeout(r, 300))
      onEvent('progress', { status: 'pulling', completed: i * 20, total: 100 })
    }
    onEvent('done', { model: `${providerId}/${model}` })
    return
  }
  await postSSE(`/providers/${providerId}/pull`, { model }, onEvent, signal)
}

/** 工作流试运行（真实模式）：workflow 事件逐节点回报，message 为最终结果。 */
export async function streamWorkflowRun(
  workflowId: string,
  body: { inputs: Record<string, string>; dsl?: unknown },
  onEvent: EventHandler,
  signal: AbortSignal,
): Promise<void> {
  await postSSE(`/workflows/${workflowId}/run`, body, onEvent, signal)
}
