import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Activity, Brain, Cpu, Plug, Server } from 'lucide-react'
import { toast } from 'sonner'
import { listModels, pingModel } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { OllamaSetupDialog, SETUP_LABELS, useSetupTargets, type SetupTarget } from './ollama-setup'

const CAP_LABELS: Record<string, string> = {
  completion: '对话',
  vision: '视觉',
  tools: '工具',
  thinking: '思维链',
  embedding: '嵌入',
}

export default function ModelsPage() {
  const { data: models, isLoading } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const setupTargets = useSetupTargets()
  const [setupTarget, setSetupTarget] = useState<SetupTarget>()

  const pingMut = useMutation({
    mutationFn: pingModel,
    onSuccess: ({ latency_ms }) => toast.success(`连通正常，延迟 ${latency_ms}ms`),
    onError: () => toast.error('连通失败'),
  })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">模型管理</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              可用模型清单（来自各供应商注册表）；对话页顶部可切换
            </p>
          </div>
          <Link
            to="/providers"
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-input bg-background px-3 text-xs font-medium shadow-sm transition-colors hover:bg-accent"
          >
            <Server className="h-3.5 w-3.5" />
            模型服务配置
          </Link>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : !models?.length ? (
          <div className="mt-6 flex flex-col items-center rounded-2xl border border-dashed px-6 py-10 text-center">
            <Plug className="h-8 w-8 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium">还没有可用模型</p>
            <p className="mt-1 max-w-sm text-xs text-muted-foreground">
              {setupTargets[0] === 'browser'
                ? '可以连接你电脑上的 Ollama，模型在本机运行；服务器模型由管理员配置。'
                : '检测 Ollama 并一键下载推荐模型，或在「模型服务配置」接入 OpenAI 兼容 API。'}
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {setupTargets.map((t, i) => (
                <Button
                  key={t}
                  size="sm"
                  variant={i === 0 ? 'default' : 'outline'}
                  className="gap-1.5"
                  onClick={() => setSetupTarget(t)}
                >
                  <Plug className="h-3.5 w-3.5" />
                  {setupTargets.length === 1 && t === 'server' ? '连接模型' : SETUP_LABELS[t].replace('…', '')}
                </Button>
              ))}
            </div>
            <OllamaSetupDialog
              open={!!setupTarget}
              onOpenChange={(v) => !v && setSetupTarget(undefined)}
              target={setupTarget ?? 'browser'}
            />
          </div>
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {models?.map((m) => (
                <div key={m.id} className="rounded-2xl border bg-card p-4 shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                      <Cpu className="h-5 w-5 text-primary" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold">{m.name}</div>
                      <div className="mt-0.5 truncate text-xs text-muted-foreground">
                        {m.provider_name ?? m.provider}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1 text-xs"
                      onClick={() => pingMut.mutate(m.id)}
                    >
                      <Activity className="h-3 w-3" />
                      测试
                    </Button>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {(m.capabilities ?? []).map((c) => (
                      <Badge key={c} variant="secondary">
                        {CAP_LABELS[c] ?? c}
                      </Badge>
                    ))}
                    <Badge variant="outline">temp {m.default_params.temperature}</Badge>
                    <Badge variant="outline">max_tokens {m.default_params.max_tokens}</Badge>
                  </div>
                </div>
              ))}
          </div>
        )}

        <div className="mt-6 rounded-2xl border border-dashed p-4 text-xs leading-relaxed text-muted-foreground">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-foreground">
            <Brain className="h-3.5 w-3.5" />
            模型能力标签
          </div>
          对话 / 视觉 / 工具 / 思维链 / 嵌入。带「思维链」的模型可在对话参数面板开启深度思考；
          「嵌入」模型用于知识库向量化，默认嵌入模型可在「模型服务」页设置。
        </div>
      </div>
    </div>
  )
}
