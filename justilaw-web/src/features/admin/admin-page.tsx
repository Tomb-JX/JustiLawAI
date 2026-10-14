import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Bot, ShieldCheck, Users } from 'lucide-react'
import { toast } from 'sonner'
import { getModelDist, getUsageStats, listAdminUsers, listAgents, setUserStatus, updateAgent } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

function UsersTab() {
  const qc = useQueryClient()
  const { data: users, isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: listAdminUsers })
  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'active' | 'disabled' }) => setUserStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success('用户状态已更新')
    },
  })

  if (isLoading) return <PageLoading />

  return (
    <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
            <th className="px-4 py-2.5 font-medium">用户</th>
            <th className="px-4 py-2.5 font-medium">角色</th>
            <th className="px-4 py-2.5 font-medium">智能体数</th>
            <th className="px-4 py-2.5 font-medium">注册时间</th>
            <th className="px-4 py-2.5 font-medium">状态</th>
            <th className="px-4 py-2.5 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {users?.map((u) => (
            <tr key={u.id} className="border-b last:border-0">
              <td className="px-4 py-3">
                <div className="font-medium">{u.nickname}</div>
                <div className="text-xs text-muted-foreground">@{u.username}</div>
              </td>
              <td className="px-4 py-3">
                <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                  {u.role === 'admin' ? '管理员' : '用户'}
                </Badge>
              </td>
              <td className="px-4 py-3 text-muted-foreground">{u.agent_count}</td>
              <td className="px-4 py-3 text-muted-foreground">
                {new Date(u.created_at).toLocaleDateString()}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`rounded-md px-2 py-0.5 text-xs font-medium ${
                    u.status === 'active' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600'
                  }`}
                >
                  {u.status === 'active' ? '正常' : '已禁用'}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={u.role === 'admin'}
                  onClick={() =>
                    statusMut.mutate({ id: u.id, status: u.status === 'active' ? 'disabled' : 'active' })
                  }
                >
                  {u.status === 'active' ? '禁用' : '启用'}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReviewTab() {
  const qc = useQueryClient()
  const { data: agents, isLoading } = useQuery({ queryKey: ['agents'], queryFn: listAgents })
  const pending = (agents ?? []).filter((a) => a.status !== 'published')

  const reviewMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'published' | 'offline' }) => updateAgent(id, { status }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success(vars.status === 'published' ? '已通过审核并发布' : '已驳回下架')
    },
  })

  if (isLoading) return <PageLoading />

  return (
    <div className="space-y-2">
      {pending.length === 0 ? (
        <div className="flex flex-col items-center py-14 text-center">
          <ShieldCheck className="h-10 w-10 text-muted-foreground/30" />
          <p className="mt-3 text-sm text-muted-foreground">暂无待审核的智能体</p>
        </div>
      ) : (
        pending.map((a) => (
          <div key={a.id} className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-sm">
            <Bot className="h-5 w-5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{a.name}</div>
              <div className="truncate text-xs text-muted-foreground">{a.description}</div>
            </div>
            <Badge variant="outline">{a.status === 'draft' ? '草稿' : '已下架'}</Badge>
            <div className="flex gap-2">
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={() => reviewMut.mutate({ id: a.id, status: 'published' })}
              >
                通过
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={() => reviewMut.mutate({ id: a.id, status: 'offline' })}
              >
                驳回
              </Button>
            </div>
          </div>
        ))
      )}
    </div>
  )
}

function StatsTab() {
  const { data: usage } = useQuery({ queryKey: ['usage-stats'], queryFn: getUsageStats })
  const { data: dist } = useQuery({ queryKey: ['model-dist'], queryFn: getModelDist })

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="rounded-2xl border bg-card p-4 shadow-sm lg:col-span-3">
        <div className="mb-3 text-sm font-medium">近 14 日调用量</div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={usage}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
              <ChartTooltip
                contentStyle={{
                  background: 'hsl(var(--popover))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line type="monotone" dataKey="calls" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} name="调用量" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="rounded-2xl border bg-card p-4 shadow-sm lg:col-span-2">
        <div className="mb-3 text-sm font-medium">模型调用分布</div>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={dist} layout="vertical">
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="name"
                width={110}
                tick={{ fontSize: 11 }}
                stroke="hsl(var(--muted-foreground))"
              />
              <ChartTooltip
                contentStyle={{
                  background: 'hsl(var(--popover))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Bar dataKey="value" fill="hsl(var(--primary))" radius={[0, 6, 6, 0]} barSize={18} name="调用次数" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

export default function AdminPage() {
  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="text-xl font-bold">管理后台</h1>
        <p className="mt-1 text-sm text-muted-foreground">用户管理、智能体审核与平台用量统计</p>

        <Tabs defaultValue="users" className="mt-6">
          <TabsList>
            <TabsTrigger value="users" className="gap-1">
              <Users className="h-3.5 w-3.5" />
              用户管理
            </TabsTrigger>
            <TabsTrigger value="review" className="gap-1">
              <Bot className="h-3.5 w-3.5" />
              智能体审核
            </TabsTrigger>
            <TabsTrigger value="stats" className="gap-1">
              <ShieldCheck className="h-3.5 w-3.5" />
              用量统计
            </TabsTrigger>
          </TabsList>
          <TabsContent value="users">
            <UsersTab />
          </TabsContent>
          <TabsContent value="review">
            <ReviewTab />
          </TabsContent>
          <TabsContent value="stats">
            <StatsTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
