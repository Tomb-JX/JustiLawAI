import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Bot,
  ChevronRight,
  Flame,
  MessagesSquare,
  Pencil,
  Send,
  Trash2,
  Undo2,
} from 'lucide-react'
import { toast } from 'sonner'
import { deleteAgent, getAgent, listDatasets, updateAgent } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'

export default function AgentDetailPage() {
  const { agentId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: agent, isLoading } = useQuery({
    queryKey: ['agents', agentId],
    queryFn: () => getAgent(agentId!),
    enabled: !!agentId,
  })
  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['agents'] })

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'published' | 'offline' | 'draft' }) =>
      updateAgent(id, { status }),
    onSuccess: (_d, vars) => {
      invalidate()
      toast.success(vars.status === 'published' ? '已发布到广场' : vars.status === 'offline' ? '已下架' : '已转为草稿')
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteAgent,
    onSuccess: () => {
      invalidate()
      toast.success('智能体已删除')
      navigate('/agents')
    },
  })

  if (isLoading) return <PageLoading />
  if (!agent)
    return <div className="p-10 text-center text-sm text-muted-foreground">智能体不存在</div>

  const isMine = agent.created_by === 'u_me'
  const linkedDatasets = (datasets ?? []).filter((d) => agent.dataset_ids.includes(d.id))

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <Link
          to="/agents"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          返回广场
        </Link>

        <div className="mt-5 flex items-start gap-4">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-primary/10">
            <Bot className="h-8 w-8 text-primary" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">{agent.name}</h1>
              <Badge variant="secondary">{agent.category}</Badge>
              {agent.status !== 'published' && <Badge variant="outline">草稿</Badge>}
            </div>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{agent.description}</p>
            <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <Flame className="h-3 w-3" />
                已被使用 {agent.usage_count} 次
              </span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {isMine && (
              <>
                <Button variant="outline" size="sm" className="gap-1" onClick={() => navigate('/agents/create')}>
                  <Pencil className="h-3.5 w-3.5" />
                  编辑
                </Button>
                {agent.status !== 'published' ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1"
                    onClick={() => statusMut.mutate({ id: agent.id, status: 'published' })}
                  >
                    <Send className="h-3.5 w-3.5" />
                    发布到广场
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1"
                    onClick={() => statusMut.mutate({ id: agent.id, status: 'offline' })}
                  >
                    <Undo2 className="h-3.5 w-3.5" />
                    下架
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1 text-destructive"
                  onClick={() => {
                    if (confirm(`确认删除智能体「${agent.name}」？`)) deleteMut.mutate(agent.id)
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </>
            )}
            <Button className="gap-1.5" onClick={() => navigate(`/chat?agentId=${agent.id}`)}>
              <MessagesSquare className="h-4 w-4" />
              开始对话
            </Button>
          </div>
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border bg-card p-4">
            <h2 className="text-sm font-semibold">系统提示词</h2>
            <p className="mt-2 rounded-lg bg-muted/60 p-3 font-mono text-xs leading-relaxed text-muted-foreground">
              {agent.system_prompt}
            </p>
          </div>
          <div className="rounded-2xl border bg-card p-4">
            <h2 className="text-sm font-semibold">挂载知识库</h2>
            <div className="mt-2 space-y-1.5">
              {linkedDatasets.length > 0 ? (
                linkedDatasets.map((d) => (
                  <Link
                    key={d.id}
                    to={`/datasets/${d.id}`}
                    className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors hover:bg-accent"
                  >
                    {d.name}
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                  </Link>
                ))
              ) : (
                <p className="text-xs text-muted-foreground">未挂载知识库</p>
              )}
            </div>
          </div>
        </div>

        {agent.suggested_questions && agent.suggested_questions.length > 0 && (
          <div className="mt-4 rounded-2xl border bg-card p-4">
            <h2 className="text-sm font-semibold">试试这样问</h2>
            <div className="mt-2.5 space-y-1.5">
              {agent.suggested_questions.map((q) => (
                <button
                  key={q}
                  onClick={() => navigate(`/chat?agentId=${agent.id}`)}
                  className="block w-full rounded-lg px-3 py-2 text-left text-sm text-foreground/85 transition-colors hover:bg-accent"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
