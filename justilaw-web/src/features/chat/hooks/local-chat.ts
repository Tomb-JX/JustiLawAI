import { chatCommit, chatPrepare } from '@/api'
import type { ChatEventName } from '@/api/sse'
import { LOCAL_PREFIX, streamLocalChat, useLocalOllamaStore } from '@/features/models/local-ollama'
import type { ChatCompletionRequest } from '@/types/api'

type EventHandler = (name: ChatEventName, data: Record<string, unknown>) => void

/**
 * 本机模型对话（浏览器直连 Ollama）：与 streamChatCompletion 同一套事件回调，调用方无需区分。
 * prepare（服务端组装上下文）→ 浏览器流式推理 → commit（无论完成、中止还是出错都落库）。
 */
export async function streamLocalChatCompletion(
  req: ChatCompletionRequest,
  opts: { supportsThinking: boolean },
  onEvent: EventHandler,
  signal: AbortSignal,
): Promise<void> {
  const prep = await chatPrepare(req)
  if (prep.rag_error) onEvent('tool_call', { name: 'knowledge_retrieval', status: 'failed', message: prep.rag_error })
  if (prep.citations) onEvent('citations', { items: prep.citations })

  const { baseUrl } = useLocalOllamaStore.getState()
  let content = ''
  let reasoning = ''
  let usage: { prompt_tokens: number; completion_tokens: number } | undefined
  let status: 'done' | 'aborted' | 'error' = 'done'
  let failure = ''
  try {
    for await (const d of streamLocalChat(
      baseUrl,
      req.model.slice(LOCAL_PREFIX.length),
      prep.llm_messages,
      req.params,
      opts.supportsThinking ? !!req.thinking : undefined,
      signal,
    )) {
      if (d.usage) usage = d.usage
      if (d.thinking) {
        reasoning += d.thinking
        onEvent('reasoning', { delta: d.thinking })
      }
      if (d.text) {
        content += d.text
        onEvent('message', { delta: d.text })
      }
    }
  } catch (e) {
    status = signal.aborted ? 'aborted' : 'error'
    const err =
      !signal.aborted && e instanceof TypeError
        ? new Error('无法连接你电脑上的 Ollama：请确认 Ollama 已打开，或在模型下拉中重新连接本机模型')
        : (e as Error)
    failure = err.message
    throw err
  } finally {
    // 中止/出错也要落库已生成的部分，与服务端推理的行为一致
    await chatCommit({
      conversation_id: req.conversation_id,
      assistant_id: prep.assistant_id,
      model: req.model,
      // 失败且没有任何输出时把原因写进消息，刷新后也能看到为什么没有回答
      content: content || (status === 'error' ? `（生成失败：${failure}）` : ''),
      reasoning: reasoning || undefined,
      status,
      usage,
      citations: prep.citations ?? undefined,
    }).catch(() => undefined)
  }
}
