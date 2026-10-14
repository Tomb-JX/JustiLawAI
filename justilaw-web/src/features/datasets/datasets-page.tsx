import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, FileText, Library, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createDataset, deleteDataset, listDatasets } from '@/api'
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
import { EmbedModelSelect } from './embed-model-select'

export default function DatasetsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [embedModel, setEmbedModel] = useState<string>()

  const { data: datasets, isLoading } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['datasets'] })

  const createMut = useMutation({
    mutationFn: () =>
      createDataset({ name: name.trim(), description: description.trim(), embed_model: embedModel }),
    onSuccess: () => {
      invalidate()
      toast.success('知识库已创建')
      setOpen(false)
      setName('')
      setDescription('')
      setEmbedModel(undefined)
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const deleteMut = useMutation({
    mutationFn: deleteDataset,
    onSuccess: () => {
      invalidate()
      toast.success('知识库已删除')
    },
  })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">知识库</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              管理法律语料（RAG 检索源）；对话中开启"知识库"开关即可引用
            </p>
          </div>
          <Button size="sm" className="gap-1" onClick={() => setOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            新建知识库
          </Button>
        </div>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {datasets?.map((d) => (
              <div
                key={d.id}
                className="group rounded-2xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10">
                    <Library className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">{d.name}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {d.doc_count} 个文档 · top_k {d.retrieval_config.top_k} · 阈值{' '}
                      {d.retrieval_config.score_threshold}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100 max-lg:opacity-100"
                    onClick={() => {
                      if (confirm(`确认删除知识库「${d.name}」？该操作不可恢复。`)) deleteMut.mutate(d.id)
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
                <p className="mt-2.5 line-clamp-2 min-h-[32px] text-xs leading-relaxed text-muted-foreground">
                  {d.description}
                </p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <FileText className="h-3 w-3" />
                    创建于 {new Date(d.created_at).toLocaleDateString()}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 gap-1 text-xs text-primary"
                    onClick={() => navigate(`/datasets/${d.id}`)}
                  >
                    管理
                    <ChevronRight className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建知识库</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="名称，如：婚姻家事法规库" />
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述（可选）"
              className="min-h-[72px]"
            />
            <div className="space-y-1.5">
              <label className="text-sm font-medium">嵌入模型</label>
              <EmbedModelSelect value={embedModel} onChange={setEmbedModel} />
              <p className="text-[11px] text-muted-foreground">建库后更换需在「设置」中重建索引</p>
            </div>
            <p className="text-xs text-muted-foreground">
              分段与检索参数创建后可在「设置」Tab 中调整
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button disabled={!name.trim()} onClick={() => createMut.mutate()}>
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
