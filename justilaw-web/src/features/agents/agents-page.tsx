import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bot, Flame, MessagesSquare, Plus, Search } from 'lucide-react'
import { listAgents } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SpotlightCard } from '@/components/common/effects'
import { PageLoading } from '@/components/common/misc'
import { isMine, useCurrentUser } from '@/features/auth/use-auth'
import { cn } from '@/lib/utils'

export default function AgentsPage() {
  const navigate = useNavigate()
  const [scope, setScope] = useState<'market' | 'mine'>('market')
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState('全部')

  const { data: agents, isLoading } = useQuery({ queryKey: ['agents'], queryFn: listAgents })
  const { data: user } = useCurrentUser()

  const categories = useMemo(
    () => ['全部', ...Array.from(new Set((agents ?? []).map((a) => a.category)))],
    [agents],
  )

  const filtered = (agents ?? []).filter((a) => {
    if (scope === 'market' && (a.status !== 'published' || a.scope !== 'public')) return false
    if (scope === 'mine' && !isMine(a.created_by, user?.id)) return false
    return (
      (category === '全部' || a.category === category) &&
      (!keyword || a.name.includes(keyword) || a.description.includes(keyword))
    )
  })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold">智能体</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              使用内置法律智能体，或创建你自己的智能体
            </p>
          </div>
          <Button size="sm" className="gap-1" onClick={() => navigate('/agents/create')}>
            <Plus className="h-3.5 w-3.5" />
            创建智能体
          </Button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          {/* 范围切换 */}
          <div className="inline-flex h-8 items-center rounded-lg bg-muted p-0.5 text-muted-foreground">
            {(
              [
                ['market', '广场'],
                ['mine', '我的'],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                onClick={() => setScope(v)}
                className={cn(
                  'h-7 rounded-md px-3 text-xs font-medium transition-all',
                  scope === v && 'bg-background text-foreground shadow',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          {/* 分类 */}
          <div className="flex flex-wrap gap-1.5">
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
          <div className="relative ml-auto w-56">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索智能体…"
              className="bg-background pl-8"
            />
          </div>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : filtered.length === 0 ? (
          <div className="mt-16 flex flex-col items-center text-center">
            <Bot className="h-10 w-10 text-muted-foreground/40" />
            <p className="mt-3 text-sm text-muted-foreground">
              {scope === 'mine' ? '你还没有创建智能体，点击右上角"创建智能体"开始' : '没有符合条件的智能体'}
            </p>
          </div>
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((a, i) => (
              <SpotlightCard
                key={a.id}
                onClick={() => navigate(`/agents/${a.id}`, { viewTransition: true })}
                style={{ '--stagger-delay': `${Math.min(i, 8) * 45}ms` } as React.CSSProperties}
                className="stagger-item group flex cursor-pointer flex-col rounded-2xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
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
              </SpotlightCard>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
