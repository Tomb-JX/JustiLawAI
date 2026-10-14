import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Activity, Brain, Cpu, Eye, Server } from 'lucide-react'
import { toast } from 'sonner'
import { listModels, pingModel } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'

const CAP_LABELS: Record<string, string> = {
  completion: '对话',
  vision: '视觉',
  tools: '工具',
  thinking: '思维链',
  embedding: '嵌入',
}

export default function ModelsPage() {
  const { data: models, isLoading } = useQuery({ queryKey: ['models'], queryFn: listModels })

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
