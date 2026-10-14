import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, GitBranch, Pencil, Play, Trash2, Workflow as WorkflowIcon } from 'lucide-react'
import { toast } from 'sonner'
import { createWorkflow, deleteWorkflow, listWorkflows } from '@/api'
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
import { cn } from '@/lib/utils'

const TEMPLATES = [
  { id: undefined, name: '空白工作流', desc: '从「开始 → 回复」最小结构开始', icon: Pencil },
  { id: 'w_1001', name: '案情分析流水线', desc: '要素抽取 → 法条/类案检索 → 综合分析', icon: GitBranch },
  { id: 'w_1002', name: '判决预测（CAIL）', desc: '调用 CAIL 模型 API + 法条核对', icon: Database },
  { id: 'w_1003', name: '合同风险扫描', desc: '逐块审查 → 风险聚合 → 报告输出', icon: WorkflowIcon },
]

export default function WorkflowsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState<string | undefined>(undefined)

  const { data: workflows, isLoading } = useQuery({ queryKey: ['workflows'], queryFn: listWorkflows })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['workflows'] })

  const createMut = useMutation({
    mutationFn: () => createWorkflow({ name: name.trim(), from_workflow_id: templateId }),
    onSuccess: (wf) => {
      invalidate()
      toast.success('工作流已创建')
      setOpen(false)
      setName('')
      navigate(`/workflows/${wf.id}/edit`)
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteWorkflow,
    onSuccess: () => {
      invalidate()
      toast.success('工作流已删除')
    },
  })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">工作流</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              可视化编排法律 AI 流程：LLM 推理、知识检索、条件分支、HTTP 调用
            </p>
          </div>
          <Button size="sm" className="gap-1" onClick={() => setOpen(true)}>
            <Play className="h-3.5 w-3.5" />
            新建工作流
          </Button>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {workflows?.map((w) => (
              <div
                key={w.id}
                onClick={() => navigate(`/workflows/${w.id}/edit`)}
                className="group cursor-pointer rounded-2xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                    <WorkflowIcon className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-semibold">{w.name}</span>
                      <Badge variant={w.status === 'published' ? 'default' : 'outline'}>
                        {w.status === 'published' ? '已发布' : '草稿'}
                      </Badge>
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {w.dsl.nodes.length} 个节点 · {w.dsl.edges.length} 条连线 · 更新于{' '}
                      {new Date(w.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (confirm(`确认删除工作流「${w.name}」？`)) deleteMut.mutate(w.id)
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
                <p className="mt-2.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                  {w.description}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>新建工作流</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="工作流名称，如：民间借贷要素提取"
            />
            <div className="grid grid-cols-2 gap-2">
              {TEMPLATES.map((t) => (
                <button
                  key={t.name}
                  onClick={() => setTemplateId(t.id)}
                  className={cn(
                    'flex items-start gap-2.5 rounded-xl border p-3 text-left transition-colors',
                    templateId === t.id ? 'border-primary bg-primary/5' : 'hover:bg-accent',
                  )}
                >
                  <t.icon className={cn('mt-0.5 h-4 w-4 shrink-0', templateId === t.id ? 'text-primary' : 'text-muted-foreground')} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{t.name}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">{t.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button disabled={!name.trim() || createMut.isPending} onClick={() => createMut.mutate()}>
              创建并编辑
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
