import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Bot, Check, Library, MessagesSquare, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import { createAgent, listDatasets } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const CATEGORIES = ['法律咨询', '司法辅助', '合同文书', '检索分析', '其他']

interface Draft {
  name: string
  category: string
  description: string
  system_prompt: string
  opening_statement: string
  suggested_questions: string[]
  dataset_ids: string[]
}

const STEPS = ['基本信息', '人设与提示词', '知识库挂载', '完成']

export default function CreateAgentPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<Draft>({
    name: '',
    category: '法律咨询',
    description: '',
    system_prompt:
      '你是专业的法律智能助手。回答需引用具体法条，语言通俗，结尾给出行动建议，并声明"以上内容由 AI 生成，不构成法律意见"。',
    opening_statement: '',
    suggested_questions: [],
    dataset_ids: [],
  })
  const [newQuestion, setNewQuestion] = useState('')

  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))

  const createMut = useMutation({
    mutationFn: () => createAgent(draft),
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('智能体已创建，可在详情页发布')
      navigate(`/agents/${agent.id}`)
    },
  })

  const stepValid =
    (step === 0 && draft.name.trim()) ||
    step === 1 ||
    step === 2 ||
    step === 3

  const addQuestion = () => {
    const q = newQuestion.trim()
    if (q && !draft.suggested_questions.includes(q)) {
      set({ suggested_questions: [...draft.suggested_questions, q] })
    }
    setNewQuestion('')
  }

  const toggleDataset = (id: string) =>
    set({
      dataset_ids: draft.dataset_ids.includes(id)
        ? draft.dataset_ids.filter((x) => x !== id)
        : [...draft.dataset_ids, id],
    })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate('/agents')}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回列表
          </button>
        </div>
        <h1 className="mt-3 text-xl font-bold">创建智能体</h1>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
          {/* 左：分步表单 */}
          <div className="rounded-2xl border bg-card p-5 shadow-sm">
            {/* 步骤指示 */}
            <div className="mb-5 flex items-center gap-2">
              {STEPS.map((s, i) => (
                <div key={s} className="flex items-center gap-2">
                  <button
                    onClick={() => i < step && setStep(i)}
                    className={cn(
                      'flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium',
                      i === step
                        ? 'bg-primary text-primary-foreground'
                        : i < step
                          ? 'bg-primary/15 text-primary'
                          : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {i < step ? <Check className="h-3 w-3" /> : i + 1}
                  </button>
                  <span className={cn('text-xs', i === step ? 'font-medium text-foreground' : 'text-muted-foreground')}>
                    {s}
                  </span>
                  {i < STEPS.length - 1 && <div className="h-px w-6 bg-border" />}
                </div>
              ))}
            </div>

            {step === 0 && (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">名称 *</label>
                  <Input
                    value={draft.name}
                    onChange={(e) => set({ name: e.target.value })}
                    placeholder="如：婚姻家事咨询助手"
                    className="bg-background"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">分类</label>
                  <div className="flex flex-wrap gap-1.5">
                    {CATEGORIES.map((c) => (
                      <button
                        key={c}
                        onClick={() => set({ category: c })}
                        className={cn(
                          'rounded-full border px-3 py-1 text-xs transition-colors',
                          draft.category === c
                            ? 'border-primary bg-primary text-primary-foreground'
                            : 'text-muted-foreground hover:bg-accent',
                        )}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">简介</label>
                  <Textarea
                    value={draft.description}
                    onChange={(e) => set({ description: e.target.value })}
                    placeholder="一句话描述智能体的用途"
                    className="min-h-[64px] bg-background"
                  />
                </div>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">系统提示词（人设与规则）</label>
                  <Textarea
                    value={draft.system_prompt}
                    onChange={(e) => set({ system_prompt: e.target.value })}
                    className="min-h-[120px] bg-background font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">开场白</label>
                  <Textarea
                    value={draft.opening_statement}
                    onChange={(e) => set({ opening_statement: e.target.value })}
                    placeholder="用户进入对话时看到的第一句话"
                    className="min-h-[60px] bg-background"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-sm font-medium">推荐问题</label>
                  <div className="flex gap-2">
                    <Input
                      value={newQuestion}
                      onChange={(e) => setNewQuestion(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addQuestion()}
                      placeholder="输入推荐问题后回车添加"
                      className="bg-background"
                    />
                    <Button variant="outline" size="icon" onClick={addQuestion}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {draft.suggested_questions.map((q) => (
                      <Badge key={q} variant="secondary" className="gap-1 pr-1">
                        <span className="max-w-[260px] truncate">{q}</span>
                        <button
                          onClick={() =>
                            set({ suggested_questions: draft.suggested_questions.filter((x) => x !== q) })
                          }
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  挂载知识库后，智能体对话将自动检索所选库并引用来源
                </p>
                {datasets?.map((d) => {
                  const on = draft.dataset_ids.includes(d.id)
                  return (
                    <button
                      key={d.id}
                      onClick={() => toggleDataset(d.id)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors',
                        on ? 'border-primary bg-primary/5' : 'hover:bg-accent',
                      )}
                    >
                      <Library className={cn('h-4 w-4', on ? 'text-primary' : 'text-muted-foreground')} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{d.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {d.doc_count} 个文档
                        </div>
                      </div>
                      {on && <Check className="h-4 w-4 text-primary" />}
                    </button>
                  )
                })}
              </div>
            )}

            {step === 3 && (
              <div className="py-6 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                  <Bot className="h-7 w-7 text-primary" />
                </div>
                <h2 className="mt-3 text-lg font-semibold">「{draft.name || '未命名智能体'}」准备就绪</h2>
                <p className="mx-auto mt-1.5 max-w-sm text-sm text-muted-foreground">
                  将以草稿状态创建，你可以在详情页继续编辑并发布到广场
                </p>
                <Button
                  className="mt-5 gap-1.5"
                  disabled={!draft.name.trim() || createMut.isPending}
                  onClick={() => createMut.mutate()}
                >
                  <Check className="h-4 w-4" />
                  创建智能体
                </Button>
              </div>
            )}

            {/* 步骤按钮 */}
            {step < 3 && (
              <div className="mt-6 flex justify-between border-t pt-4">
                <Button variant="ghost" size="sm" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
                  上一步
                </Button>
                <Button size="sm" disabled={!stepValid} onClick={() => setStep((s) => s + 1)}>
                  下一步
                </Button>
              </div>
            )}
          </div>

          {/* 右：实时预览 */}
          <div className="space-y-3">
            <div className="rounded-2xl border bg-card p-4 shadow-sm">
              <div className="text-xs font-medium text-muted-foreground">实时预览</div>
              <div className="mt-3 flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                  <Bot className="h-5 w-5 text-primary" />
                </div>
                <div className="min-w-0">
                  <div className="font-semibold">{draft.name || '未命名智能体'}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{draft.category}</span>
                    <Badge variant="outline" className="text-[10px]">
                      草稿
                    </Badge>
                  </div>
                </div>
              </div>
              <p className="mt-2.5 min-h-[32px] text-xs leading-relaxed text-muted-foreground">
                {draft.description || '暂无简介'}
              </p>
            </div>

            <div className="rounded-2xl border bg-card p-4 shadow-sm">
              <div className="text-xs font-medium text-muted-foreground">开场白预览</div>
              <div className="mt-3 flex items-start gap-2">
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary">
                  <Bot className="h-3.5 w-3.5 text-primary-foreground" />
                </div>
                <p className="rounded-2xl rounded-tl-sm bg-muted px-3 py-2 text-xs leading-relaxed">
                  {draft.opening_statement || '（未设置开场白）'}
                </p>
              </div>
              {draft.suggested_questions.length > 0 && (
                <div className="mt-3 space-y-1.5 pl-8">
                  {draft.suggested_questions.slice(0, 3).map((q) => (
                    <div key={q} className="rounded-lg border px-3 py-1.5 text-xs text-muted-foreground">
                      {q}
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 flex items-center gap-1 border-t pt-3 text-[11px] text-muted-foreground">
                <MessagesSquare className="h-3 w-3" />
                创建后可在详情页点击「开始对话」进行调试
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
