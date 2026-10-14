import { useMutation, useQuery } from '@tanstack/react-query'
import { Activity, Cpu } from 'lucide-react'
import { toast } from 'sonner'
import { listModels, pingModel } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'

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
        <h1 className="text-xl font-bold">模型管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          后端提供的可用模型清单；对话页顶部可切换，参数可按模型重置
        </p>

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
                    <div className="font-semibold">{m.name}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{m.provider}</div>
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
                <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">{m.description}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge variant="secondary">temp {m.default_params.temperature}</Badge>
                  <Badge variant="secondary">top_p {m.default_params.top_p}</Badge>
                  <Badge variant="secondary">max_tokens {m.default_params.max_tokens}</Badge>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
