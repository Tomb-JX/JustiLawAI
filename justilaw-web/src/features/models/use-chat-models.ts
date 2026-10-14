import { useQuery } from '@tanstack/react-query'
import { listModels } from '@/api'
import type { ModelInfo } from '@/types/api'
import { listLocalModels, useLocalOllamaStore } from './local-ollama'

const canChat = (m: ModelInfo) => (m.capabilities ?? ['completion']).includes('completion')

/** 本机 Ollama 的模型（浏览器直连，未启用时不请求） */
export function useLocalModels() {
  const enabled = useLocalOllamaStore((s) => s.enabled)
  const baseUrl = useLocalOllamaStore((s) => s.baseUrl)
  return useQuery({
    queryKey: ['local-models', baseUrl],
    queryFn: () => listLocalModels(baseUrl),
    enabled,
    retry: false,
    staleTime: 30_000,
  })
}

/** 可用于对话的全部模型：服务端模型 + 本机 Ollama 模型（local/ 前缀） */
export function useChatModels() {
  const server = useQuery({ queryKey: ['models'], queryFn: listModels })
  const local = useLocalModels()
  const localEnabled = useLocalOllamaStore((s) => s.enabled)
  const serverModels = server.data?.filter(canChat) ?? []
  const localModels = localEnabled ? (local.data?.filter(canChat) ?? []) : []
  return {
    serverModels,
    localModels,
    models: [...serverModels, ...localModels],
    isLoading: server.isLoading || (localEnabled && local.isLoading),
    localError: localEnabled && local.isError ? (local.error as Error) : null,
    /** 本机已连通但还没有可对话的模型（比如只装了嵌入模型） */
    localEmpty: localEnabled && local.isSuccess && localModels.length === 0,
  }
}
