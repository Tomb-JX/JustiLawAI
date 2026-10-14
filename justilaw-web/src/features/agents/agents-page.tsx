import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bot, Flame, MessagesSquare, Search } from 'lucide-react'
import { listAgents } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageLoading } from '@/components/common/misc'
import { cn } from '@/lib/utils'

export default function AgentsPage() {
  const navigate = useNavigate()
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState('全部')

  const { data: agents, isLoading } = useQuery({ queryKey: ['agents'], queryFn: listAgents })

  const categories = useMemo(
    () => ['全部', ...Array.from(new Set((agents ?? []).map((a) => a.category)))],
    [agents],
  )

  const filtered = (agents ?? []).filter(
    (a) =>
      (category === '全部' || a.category === category) &&
      (!keyword || a.name.includes(keyword) || a.description.includes(keyword)),
  )

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold">智能体广场</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              内置法律智能体，点击进入对话；创建自定义智能体将于 M4 交付
            </p>
          </div>
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索智能体…"
              className="bg-background pl-8"
            />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {categories.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs transition-colors',
                category === c
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent',
              )}
            >
              {c}
            </button>
          ))}
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((a) => (
              <div
                key={a.id}
                onClick={() => navigate(`/agents/${a.id}`)}
                className="group flex cursor-pointer flex-col rounded-2xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                    <Bot className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-semibold">{a.name}</span>
                      {a.status !== 'published' && (
                        <Badge variant="outline" className="text-[10px]">
                          草稿
                        </Badge>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                      <span>{a.category}</span>
                      <span className="flex items-center gap-0.5">
                        <Flame className="h-3 w-3" />
                        {a.usage_count}
                      </span>
                    </div>
                  </div>
                </div>
                <p className="mt-2.5 line-clamp-2 flex-1 text-xs leading-relaxed text-muted-foreground">
                  {a.description}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <Badge variant="secondary" className="text-[10px]">
                    {a.scope === 'public' ? '公开' : a.scope === 'org' ? '组织' : '私有'}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 gap-1 text-xs text-primary"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/chat?agentId=${a.id}`)
                    }}
                  >
                    <MessagesSquare className="h-3 w-3" />
                    开始对话
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
