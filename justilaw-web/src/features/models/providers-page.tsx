import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Brain,
  Cpu,
  Eye,
  Globe,
  HardDrive,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  addProvider,
  addProviderModel,
  deleteProvider,
  fetchProviderRemoteModels,
  getModelSettings,
  listModels,
  listProviders,
  pingProvider,
  refreshProvider,
  removeProviderModel,
  setModelSettings,
  updateProvider,
} from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { PageLoading } from '@/components/common/misc'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { ModelInfo, ModelProvider } from '@/types/api'

const CAP_LABELS: Record<string, string> = {
  completion: '对话',
  vision: '视觉',
  tools: '工具',
  thinking: '思维链',
  embedding: '嵌入',
}

/** 供应商类型说明（对齐主流智能体平台的"模型供应商"体系） */
const TYPE_META = {
  ollama: { label: 'Ollama 本地', icon: HardDrive, desc: '本地推理，模型自动发现' },
  openai_compat: { label: 'OpenAI 兼容 API', icon: Globe, desc: '自定义 base_url + api_key' },
}

function ProviderCard({ provider }: { provider: ModelProvider }) {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['providers'] })
    qc.invalidateQueries({ queryKey: ['models'] })
  }
  const [addOpen, setAddOpen] = useState(false)
  const [modelName, setModelName] = useState('')
  const [caps, setCaps] = useState<string[]>(['completion'])
  const [remoteModels, setRemoteModels] = useState<string[] | null>(null)

  // 从远端 API 拉取模型名列表（只列不存），点选填入输入框，仍可手动输入
  const fetchMut = useMutation({
    mutationFn: () => fetchProviderRemoteModels(provider.id),
    onSuccess: (models) => {
      setRemoteModels(models)
      if (models.length > 0) toast.success(`拉取到 ${models.length} 个模型，点击选择即可`)
    },
    onError: (e) => toast.error(`拉取失败：${(e as Error).message}，可手动输入模型名`),
  })

  const pingMut = useMutation({
    mutationFn: () => pingProvider(provider.id),
    onSuccess: ({ latency_ms }) => toast.success(`连通正常，延迟 ${latency_ms}ms`),
    onError: (e) => toast.error(`连通失败：${(e as Error).message}`),
  })

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => updateProvider(provider.id, { enabled }),
    onSuccess: invalidate,
  })

  const deleteMut = useMutation({
    mutationFn: () => deleteProvider(provider.id),
    onSuccess: () => {
      invalidate()
      toast.success('供应商已删除')
    },
  })

  const addModelMut = useMutation({
    mutationFn: () => addProviderModel(provider.id, { name: modelName.trim(), capabilities: caps }),
    onSuccess: () => {
      invalidate()
      toast.success('模型已添加')
      setAddOpen(false)
      setModelName('')
    },
  })

  const removeModelMut = useMutation({
    mutationFn: (modelId: string) => removeProviderModel(provider.id, modelId),
    onSuccess: invalidate,
  })

  const refreshMut = useMutation({
    mutationFn: () => refreshProvider(provider.id),
    onSuccess: (p) => {
      invalidate()
      toast.success(`已同步 ${p.models.length} 个模型`)
    },
    onError: (e) => toast.error(`同步失败：${(e as Error).message}`),
  })

  const meta = TYPE_META[provider.type] ?? TYPE_META.openai_compat
  const Icon = meta.icon

  return (
    <div className="rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{provider.name}</span>
            <Badge variant="secondary">{meta.label}</Badge>
            <span className={`text-xs ${provider.enabled ? 'text-emerald-600' : 'text-muted-foreground'}`}>
              {provider.enabled ? '已启用' : '已停用'}
            </span>
          </div>
          <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{provider.base_url}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {provider.models.length} 个模型 · {meta.desc}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {provider.type === 'ollama' && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1 text-xs"
              onClick={() => refreshMut.mutate()}
              disabled={refreshMut.isPending}
            >
              <RefreshCw className={`h-3 w-3 ${refreshMut.isPending ? 'animate-spin' : ''}`} />
              同步模型
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 text-xs"
            onClick={() => pingMut.mutate()}
            disabled={pingMut.isPending}
          >
            {pingMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Activity className="h-3 w-3" />}
            测试
          </Button>
          <Switch checked={provider.enabled} onCheckedChange={(v) => toggleMut.mutate(v)} />
        </div>
      </div>

      {/* 模型列表 */}
      <div className="mt-3 space-y-1.5">
        {provider.models.map((m) => (
          <div key={m.id} className="flex items-center gap-2 rounded-lg bg-muted/40 px-3 py-1.5 text-xs">
            <Cpu className="h-3 w-3 shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate font-medium">{m.name}</span>
            <div className="flex shrink-0 gap-1">
              {(m.capabilities ?? []).slice(0, 4).map((c) => (
                <Badge key={c} variant="outline" className="px-1.5 py-0 text-[10px]">
                  {CAP_LABELS[c] ?? c}
                </Badge>
              ))}
            </div>
            {provider.type === 'openai_compat' && (
              <button
                className="text-muted-foreground hover:text-destructive"
                onClick={() => removeModelMut.mutate(m.id)}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
      </div>

      {provider.type === 'openai_compat' && (
        <div className="mt-3 flex items-center justify-between border-t pt-3">
          <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={() => setAddOpen(true)}>
            <Plus className="h-3 w-3" />
            添加模型
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 text-xs text-destructive"
            onClick={() => {
              if (confirm(`确认删除供应商「${provider.name}」及其模型配置？`)) deleteMut.mutate()
            }}
          >
            <Trash2 className="h-3 w-3" />
            删除供应商
          </Button>
        </div>
      )}

      {/* 添加模型对话框 */}
      <Dialog open={addOpen} onOpenChange={(v) => { setAddOpen(v); if (!v) { setRemoteModels(null); setModelName('') } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>向「{provider.name}」添加模型</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="模型名（与 API 一致，如 glm-4-plus / deepseek-chat）"
              />
              <Button
                variant="outline"
                className="shrink-0 gap-1 text-xs"
                onClick={() => fetchMut.mutate()}
                disabled={fetchMut.isPending}
              >
                <RefreshCw className={`h-3 w-3 ${fetchMut.isPending ? 'animate-spin' : ''}`} />
                {fetchMut.isPending ? '拉取中' : '拉取列表'}
              </Button>
            </div>
            {remoteModels && (
              <div className="max-h-40 overflow-y-auto rounded-lg border">
                {remoteModels.length === 0 ? (
                  <p className="p-3 text-xs text-muted-foreground">API 返回的模型列表为空</p>
                ) : (
                  remoteModels.map((m) => (
                    <button
                      key={m}
                      onClick={() => setModelName(m)}
                      className={`flex w-full items-center justify-between px-3 py-2 text-left font-mono text-xs transition-colors hover:bg-accent ${
                        modelName === m ? 'bg-accent text-primary' : ''
                      }`}
                    >
                      <span className="truncate">{m}</span>
                      {provider.models.some((x) => x.name === m) && (
                        <span className="ml-2 shrink-0 text-[11px] text-muted-foreground">已添加</span>
                      )}
                    </button>
                  ))
                )}
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">能力标签</label>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(CAP_LABELS).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setCaps((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]))}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      caps.includes(k)
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:bg-accent'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>
              取消
            </Button>
            <Button disabled={!modelName.trim() || addModelMut.isPending} onClick={() => addModelMut.mutate()}>
              添加
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const hasCap = (m: ModelInfo, cap: string) => (m.capabilities ?? ['completion']).includes(cap)

/** 默认模型：对话未选模型时、知识库新建时使用 */
function DefaultModelsCard() {
  const qc = useQueryClient()
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const { data: settings } = useQuery({ queryKey: ['model-settings'], queryFn: getModelSettings })
  const saveMut = useMutation({
    mutationFn: setModelSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['model-settings'] })
      toast.success('默认模型已更新')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const rows = [
    { key: 'default_chat_model' as const, label: '默认对话模型', cap: 'completion', hint: '对话、工作流 LLM 节点未指定模型时使用' },
    { key: 'default_embed_model' as const, label: '默认嵌入模型', cap: 'embedding', hint: '新建知识库时绑定；已有知识库更换需重建索引' },
  ]

  return (
    <div className="mt-6 rounded-2xl border bg-card p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Brain className="h-4 w-4 text-primary" />
        默认模型
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {rows.map((r) => {
          const options = models?.filter((m) => hasCap(m, r.cap)) ?? []
          return (
            <div key={r.key} className="space-y-1.5">
              <label className="text-xs font-medium">{r.label}</label>
              <Select
                value={settings?.[r.key] ?? ''}
                onValueChange={(v) => saveMut.mutate({ [r.key]: v })}
                disabled={!options.length}
              >
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder={options.length ? '选择模型' : '暂无可用模型'} />
                </SelectTrigger>
                <SelectContent>
                  {options.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name} · {m.provider_name ?? m.provider}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-muted-foreground">{r.hint}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function ProvidersPage() {
  const { data: providers, isLoading } = useQuery({ queryKey: ['providers'], queryFn: listProviders })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [apiKey, setApiKey] = useState('')

  const createMut = useMutation({
    mutationFn: () => addProvider({ name: name.trim(), base_url: baseUrl.trim(), api_key: apiKey.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] })
      qc.invalidateQueries({ queryKey: ['models'] })
      toast.success('供应商已添加，可继续添加模型')
      setOpen(false)
      setName('')
      setApiKey('')
    },
  })
  const qc = useQueryClient()

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">模型服务</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              管理模型供应商：本地 Ollama 自动发现；自定义 OpenAI 兼容 API（base_url + api_key）
            </p>
          </div>
          <Button size="sm" className="gap-1" onClick={() => setOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            接入自定义 API
          </Button>
        </div>

        <DefaultModelsCard />

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 grid gap-4">
            {providers?.map((p) => <ProviderCard key={p.id} provider={p} />)}
          </div>
        )}

        <div className="mt-6 rounded-2xl border border-dashed p-4 text-xs leading-relaxed text-muted-foreground">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground">
            <Eye className="h-3.5 w-3.5" />
            说明
          </div>
          自定义 API 需为 OpenAI 兼容接口（<code className="rounded bg-muted px-1">/chat/completions</code> 与{' '}
          <code className="rounded bg-muted px-1">/embeddings</code>），支持 GLM / DeepSeek / 通义 / Moonshot
          等开放平台；对话与嵌入能力按模型能力标签路由。api_key 仅保存在本地服务端，不会下发给浏览器。
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>接入自定义 API</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">名称</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：智谱 GLM" />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Base URL</label>
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://open.bigmodel.cn/api/paas/v4" />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">API Key（可选）</label>
              <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button disabled={!name.trim() || !baseUrl.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
              <Server className="mr-1 h-3.5 w-3.5" />
              保存并测试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
