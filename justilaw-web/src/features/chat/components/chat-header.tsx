import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eraser, Library, RotateCcw, SlidersHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { clearMessages, getDataset, getModelSettings, listConversations, listDatasets, listModels } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSettingsStore } from '@/stores/settings'
import type { Agent } from '@/types/api'

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
}: {
  conversationId?: string
  agent?: Agent
}) {
  const qc = useQueryClient()
  const { data: conversations } = useQuery({ queryKey: ['conversations'], queryFn: listConversations })
  const { data: allModels } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const { data: modelSettings } = useQuery({ queryKey: ['model-settings'], queryFn: getModelSettings })
  // 嵌入模型不能用于对话
  const models = allModels?.filter((m) => (m.capabilities ?? ['completion']).includes('completion'))
  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  const { model, setModel, params, setParams, resetParams, thinking, setThinking, ragEnabled, ragDatasetId, setRag } =
    useSettingsStore()

  // 未选择或已失效（模型被删除/停用）时，回退到平台默认对话模型
  useEffect(() => {
    if (!models?.length || models.some((m) => m.id === model)) return
    const fallback = models.find((m) => m.id === modelSettings?.default_chat_model) ?? models[0]
    setModel(fallback.id)
  }, [models, model, modelSettings, setModel])

  const currentModel = models?.find((m) => m.id === model)
  const conversation = conversations?.find((c) => c.id === conversationId)
  const title = agent?.name ?? conversation?.title ?? 'JustiLawAI'

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b bg-card/50 px-4">
      <div className="flex min-w-0 items-center gap-2">
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

        {/* 模型选择 */}
        <Select value={model} onValueChange={setModel}>
          <SelectTrigger className="w-36 text-xs">
            <SelectValue placeholder="选择模型" />
          </SelectTrigger>
          <SelectContent>
            {models?.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </header>
  )
}
