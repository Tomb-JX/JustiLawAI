import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Sparkles, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createPrompt, deletePrompt, listPrompts } from '@/api'
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
import { Textarea } from '@/components/ui/textarea'

export default function PromptsPage() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')

  const { data: prompts, isLoading } = useQuery({ queryKey: ['prompts'], queryFn: listPrompts })

  const createMut = useMutation({
    mutationFn: () => createPrompt({ name: name.trim(), content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prompts'] })
      toast.success('提示词已创建')
      setOpen(false)
      setName('')
      setContent('')
    },
  })

  const deleteMut = useMutation({
    mutationFn: deletePrompt,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['prompts'] })
      toast.success('已删除')
    },
  })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">提示词库</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              对话输入框中输入 <code className="rounded bg-muted px-1">/</code> 可快速插入模板
            </p>
          </div>
          <Button size="sm" className="gap-1" onClick={() => setOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            新建
          </Button>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 space-y-2.5">
            {prompts?.map((p) => (
              <div key={p.id} className="group rounded-xl border bg-card p-4 shadow-sm">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary" />
                    <span className="text-sm font-semibold">{p.name}</span>
                    <Badge variant="secondary">{p.category}</Badge>
                    {p.starred && <Badge variant="outline">常用</Badge>}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100"
                    onClick={() => deleteMut.mutate(p.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
                <pre className="mt-2 whitespace-pre-wrap font-sans text-xs leading-relaxed text-muted-foreground">
                  {p.content}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建提示词</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="名称，如：案情分析" />
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="模板内容，可用 {{变量}} 占位"
              className="min-h-[110px]"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button disabled={!name.trim() || !content.trim()} onClick={() => createMut.mutate()}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
