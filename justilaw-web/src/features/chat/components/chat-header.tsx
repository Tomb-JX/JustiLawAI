import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eraser, Library, PanelLeft, Plug, RotateCcw, SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { clearMessages, getDataset, getModelSettings, listConversations, listDatasets } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { LOCAL_PREFIX, isLocalModel, useLocalOllamaStore } from '@/features/models/local-ollama'
import { OllamaSetupDialog, SETUP_LABELS, useSetupTargets, type SetupTarget } from '@/features/models/ollama-setup'
import { useChatModels } from '@/features/models/use-chat-models'
import { useSettingsStore } from '@/stores/settings'
import type { Agent } from '@/types/api'

/** 模型下拉里的"连接模型"入口（不是真实模型 ID） */
const SETUP_PREFIX = '__setup__:'

function ParamRow({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  format?: (v: number) => string
  onChange: (v: number) => void
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">{format ? format(value) : value}</span>
      </div>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])} />
    </div>
  )
}

export function ChatHeader({
  conversationId,
  agent,
  onOpenSidebar,
}: {
  conversationId?: string
  agent?: Agent
  onOpenSidebar?: () => void
}) {
  const qc = useQueryClient()
  const { data: conversations } = useQuery({ queryKey: ['conversations'], queryFn: listConversations })
  // 服务端模型 + 本机 Ollama 模型（嵌入模型不能用于对话，已过滤）
  const { models, serverModels, localModels, localError, localEmpty, isLoading: modelsLoading } = useChatModels()
  const { data: modelSettings } = useQuery({ queryKey: ['model-settings'], queryFn: getModelSettings })
  const setupTargets = useSetupTargets()
  const [setupTarget, setSetupTarget] = useState<SetupTarget>()
  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  const { model, setModel, params, setParams, resetParams, thinking, setThinking, ragEnabled, ragDatasetId, setRag } =
    useSettingsStore()

  const localEnabled = useLocalOllamaStore((s) => s.enabled)
  // 选中的本机模型暂时不可用（Ollama 没开）：保留选择，不能静默改用服务器模型——
  // 用户选本机模型往往就是不希望对话内容经过服务器上的模型
  const localUnavailable = localEnabled && isLocalModel(model) && !localModels.some((m) => m.id === model)

  // 未选择或已失效（模型被删除/停用）时，回退到平台默认对话模型
  useEffect(() => {
    if (modelsLoading || !models.length || models.some((m) => m.id === model) || localUnavailable) return
    const fallback = models.find((m) => m.id === modelSettings?.default_chat_model) ?? models[0]
    setModel(fallback.id)
  }, [models, modelsLoading, model, modelSettings, setModel, localUnavailable])

  const currentModel = models.find((m) => m.id === model)
  const conversation = conversations?.find((c) => c.id === conversationId)
  const title = agent?.name ?? conversation?.title ?? 'JustiLawAI'

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b bg-card/50 px-2 sm:px-4">
      <div className="flex min-w-0 items-center gap-1 sm:gap-2">
        {onOpenSidebar && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 lg:hidden"
            onClick={onOpenSidebar}
          >
            <PanelLeft className="h-4 w-4" />
          </Button>
        )}
        <h1 className="truncate text-sm font-semibold">{title}</h1>
        {agent && <Badge variant="secondary">智能体</Badge>}
        {currentModel && (
          <span className="hidden truncate text-xs text-muted-foreground sm:inline">
            {currentModel.name}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        {/* 清空上下文 */}
        {conversationId && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground"
                onClick={() => {
                  qc.setQueryData(['messages', conversationId], [])
                  void clearMessages(conversationId)
                  toast.success('上下文已清空，开启全新对话')
                }}
              >
                <Eraser className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>清空上下文</TooltipContent>
          </Tooltip>
        )}

        {/* 知识库检索（RAG）开关 */}
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={ragEnabled ? 'gap-1.5 text-primary' : 'gap-1.5 text-muted-foreground'}
            >
              <Library className="h-4 w-4" />
              <span className="hidden sm:inline">知识库{ragEnabled ? ' · 已开启' : ''}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">知识库检索（RAG）</div>
              <Switch
                checked={ragEnabled}
                onCheckedChange={(v) => setRag(v, ragDatasetId ?? datasets?.[0]?.id)}
              />
            </div>
            <Select
              value={ragDatasetId ?? ''}
              onValueChange={(v) => setRag(true, v)}
              disabled={!ragEnabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择知识库" />
              </SelectTrigger>
              <SelectContent>
                {datasets?.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed text-muted-foreground">
              开启后回答将检索所选知识库，并以 [n] 引用标注来源，可点击查看原文。
            </p>
          </PopoverContent>
        </Popover>

        {/* 模型参数 */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="sm" className="text-muted-foreground">
              <SlidersHorizontal className="h-4 w-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">生成参数</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 text-xs text-muted-foreground"
                onClick={() => currentModel && resetParams(currentModel.default_params)}
              >
                <RotateCcw className="h-3 w-3" />
                重置
              </Button>
            </div>
            <ParamRow
              label="温度 temperature"
              value={params.temperature}
              min={0}
              max={2}
              step={0.1}
              onChange={(v) => setParams({ temperature: v })}
            />
            <ParamRow
              label="核采样 top_p"
              value={params.top_p}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setParams({ top_p: v })}
            />
            <ParamRow
              label="最大生成长度"
              value={params.max_tokens}
              min={256}
              max={8192}
              step={256}
              onChange={(v) => setParams({ max_tokens: v })}
            />
            {currentModel?.capabilities?.includes('thinking') && (
              <div className="flex items-center justify-between border-t pt-3">
                <div>
                  <div className="text-sm font-medium">深度思考</div>
                  <div className="text-xs text-muted-foreground">开启思维链（较慢，答案更严谨）</div>
                </div>
                <Switch checked={thinking} onCheckedChange={setThinking} />
              </div>
            )}
          </PopoverContent>
        </Popover>

        {/* 模型选择：没有任何可用模型时直接给出连接入口 */}
        {!modelsLoading && !models.length ? (
          <Button size="sm" variant="outline" className="gap-1.5 text-xs" onClick={() => setSetupTarget(setupTargets[0])}>
            <Plug className="h-3.5 w-3.5" />
            连接模型
          </Button>
        ) : (
          <Select
            value={model}
            onValueChange={(v) =>
              v.startsWith(SETUP_PREFIX) ? setSetupTarget(v.slice(SETUP_PREFIX.length) as SetupTarget) : setModel(v)
            }
          >
            <SelectTrigger className="w-36 text-xs">
              <SelectValue placeholder="选择模型" />
            </SelectTrigger>
            <SelectContent>
              {serverModels.length > 0 && (
                <SelectGroup>
                  {(localModels.length > 0 || localUnavailable) && (
                    <SelectLabel className="text-[11px]">服务器</SelectLabel>
                  )}
                  {serverModels.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              )}
              {(localModels.length > 0 || localUnavailable) && (
                <SelectGroup>
                  <SelectLabel className="text-[11px]">本机 · Ollama</SelectLabel>
                  {localModels.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))}
                  {localUnavailable && (
                    <SelectItem value={model} className="text-muted-foreground">
                      {model.slice(LOCAL_PREFIX.length)}（未连接）
                    </SelectItem>
                  )}
                </SelectGroup>
              )}
              {localError && (
                <SelectItem value={`${SETUP_PREFIX}browser`} className="text-xs text-destructive">
                  本机 Ollama 未连接，点击重新连接
                </SelectItem>
              )}
              {localEmpty && (
                <SelectItem value={`${SETUP_PREFIX}browser`} className="text-xs text-amber-600">
                  本机 Ollama 还没有对话模型，点击下载
                </SelectItem>
              )}
              <SelectSeparator />
              {setupTargets.map((t) => (
                <SelectItem key={t} value={`${SETUP_PREFIX}${t}`} className="text-xs text-muted-foreground">
                  {setupTargets.length === 1 && t === 'server' ? '连接 / 下载模型…' : SETUP_LABELS[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      <OllamaSetupDialog
        open={!!setupTarget}
        onOpenChange={(v) => !v && setSetupTarget(undefined)}
        target={setupTarget ?? 'browser'}
      />
    </header>
  )
}
