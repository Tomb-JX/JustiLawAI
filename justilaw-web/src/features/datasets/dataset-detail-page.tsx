import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileSearch,
  FileText,
  Library,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  deleteDocument,
  getDataset,
  hitTesting,
  listChunks,
  listDocuments,
  reindexDataset,
  updateChunk,
  updateDataset,
  uploadDocument,
} from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageLoading } from '@/components/common/misc'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { EmbedModelSelect } from './embed-model-select'
import { formatBytes } from '@/lib/utils'
import type { DocumentStatus } from '@/types/api'

const statusBadge: Record<DocumentStatus, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'bg-secondary text-secondary-foreground' },
  parsing: { label: '解析中', cls: 'bg-amber-500/10 text-amber-600 animate-pulse' },
  completed: { label: '已完成', cls: 'bg-emerald-500/10 text-emerald-600' },
  failed: { label: '失败', cls: 'bg-destructive/10 text-destructive' },
}

/* ---------- 文档 Tab ---------- */

function DocumentTab({ datasetId }: { datasetId: string }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [activeDoc, setActiveDoc] = useState<string | null>(null)

  const { data: documents, isLoading } = useQuery({
    queryKey: ['documents', datasetId],
    queryFn: () => listDocuments(datasetId),
    // 有解析中的文档时轮询
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === 'parsing' || d.status === 'queued') ? 1500 : false,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['documents', datasetId] })

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadDocument(datasetId, file),
    onSuccess: (doc) => {
      if (doc?.status === 'failed') toast.error(`${doc.filename}：${doc.error ?? '上传失败'}`)
      else toast.success('已上传，解析中…')
      invalidate()
    },
    onError: (e) => toast.error(`上传失败：${(e as Error).message}`),
  })

  const deleteMut = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      toast.success('文档已删除')
      invalidate()
    },
  })

  return (
    <div>
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.txt,.md,.json"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) uploadMut.mutate(f)
          e.target.value = ''
        }}
      />
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={() => fileRef.current?.click()}
        disabled={uploadMut.isPending}
      >
        {uploadMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
        上传文档
      </Button>
      <p className="mt-1.5 text-[11px] text-muted-foreground">支持 PDF / DOCX / TXT / MD，单文件 ≤ 20MB；点击文档名可查看分段</p>

      <div className="mt-4 space-y-2">
        {isLoading ? (
          <PageLoading />
        ) : (
          documents?.map((doc) => {
            const s = statusBadge[doc.status]
            const expanded = activeDoc === doc.id
            return (
              <div key={doc.id} className="rounded-xl border bg-card shadow-sm">
                <div className="flex items-center gap-3 px-4 py-3">
                  <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
                  <button
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setActiveDoc(expanded ? null : doc.id)}
                  >
                    <div className="truncate text-sm font-medium transition-colors hover:text-primary">
                      {doc.filename}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {formatBytes(doc.size)} · {doc.chunk_count || '—'} 个分段 ·{' '}
                      {new Date(doc.created_at).toLocaleDateString()}
                    </div>
                  </button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground hover:text-destructive"
                    onClick={() => {
                      if (confirm(`确认删除文档「${doc.filename}」？`)) deleteMut.mutate(doc.id)
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                  <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>
                </div>
                {expanded && doc.status === 'completed' && (
                  <div className="border-t p-3">
                    <ChunkList documentId={doc.id} />
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

/* ---------- 分段列表（启停） ---------- */

function ChunkList({ documentId }: { documentId: string }) {
  const qc = useQueryClient()
  const { data: chunks, isLoading } = useQuery({
    queryKey: ['chunks', documentId],
    queryFn: () => listChunks(documentId),
  })

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => updateChunk(id, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chunks', documentId] }),
  })

  if (isLoading) return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />

  return (
    <div className="space-y-1.5">
      <div className="px-1 pb-1 text-[11px] text-muted-foreground">
        共 {chunks?.length ?? 0} 个分段；停用的分段不参与检索
      </div>
      {chunks?.map((c) => (
        <div key={c.id} className="flex items-start gap-3 rounded-lg bg-muted/40 px-3 py-2.5">
          <span className="mt-0.5 font-mono text-xs text-muted-foreground">#{c.index}</span>
          <p className={`min-w-0 flex-1 text-xs leading-relaxed ${c.enabled ? '' : 'text-muted-foreground/50 line-clamp-2'}`}>
            {c.content}
          </p>
          <Switch
            checked={c.enabled}
            onCheckedChange={(v) => toggleMut.mutate({ id: c.id, enabled: v })}
          />
        </div>
      ))}
    </div>
  )
}

/* ---------- 命中测试 Tab ---------- */

interface HitResult {
  chunk: { id: string; content: string; index: number; document_id: string }
  score: number
}

function HitTestingTab({ datasetId }: { datasetId: string }) {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [results, setResults] = useState<HitResult[] | null>(null)

  const mut = useMutation({
    mutationFn: () => hitTesting(datasetId, query.trim(), topK),
    onSuccess: (data) => setResults(data.items),
    onError: () => toast.error('检索失败'),
  })

  return (
    <div>
      <div className="flex items-start gap-2">
        <Textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入测试问题，如：组织他人赌博怎么处罚？"
          className="min-h-[72px] bg-background"
        />
        <div className="space-y-2">
          <select
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="h-9 w-full rounded-lg border border-input bg-background px-2 text-xs"
          >
            {[3, 5, 8, 10].map((k) => (
              <option key={k} value={k}>
                top_k {k}
              </option>
            ))}
          </select>
          <Button
            className="w-full gap-1.5"
            disabled={!query.trim() || mut.isPending}
            onClick={() => mut.mutate()}
          >
            {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            测试
          </Button>
        </div>
      </div>

      {results && (
        <div className="mt-4 space-y-2.5">
          <div className="text-xs text-muted-foreground">共命中 {results.length} 个分段（按相似度降序）</div>
          {results.map((r, i) => (
            <div key={r.chunk.id} className="rounded-xl border bg-card p-3.5 shadow-sm">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  #{i + 1} · 分段 {r.chunk.index}
                </span>
                <span className="font-mono text-amber-600">score {r.score.toFixed(2)}</span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed">{r.chunk.content}</p>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-secondary">
                <div className="h-full rounded-full bg-amber-500" style={{ width: `${r.score * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------- 设置 Tab ---------- */

function SettingsTab({ datasetId }: { datasetId: string }) {
  const qc = useQueryClient()
  const { data: dataset } = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => getDataset(datasetId),
  })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [maxLength, setMaxLength] = useState(500)
  const [overlap, setOverlap] = useState(50)
  const [topK, setTopK] = useState(5)
  const [threshold, setThreshold] = useState(0.6)
  const [embedModel, setEmbedModel] = useState<string>()
  const [initialized, setInitialized] = useState(false)

  // 表单初始值随数据填充（仅一次）
  if (dataset && !initialized) {
    setName(dataset.name)
    setDescription(dataset.description ?? '')
    setMaxLength(dataset.chunk_config.max_length)
    setOverlap(dataset.chunk_config.overlap)
    setTopK(dataset.retrieval_config.top_k)
    setThreshold(dataset.retrieval_config.score_threshold)
    setEmbedModel(dataset.embed_model)
    setInitialized(true)
  }

  const saveMut = useMutation({
    mutationFn: () =>
      updateDataset(datasetId, {
        name: name.trim(),
        description: description.trim(),
        chunk_config: { max_length: maxLength, overlap },
        retrieval_config: { top_k: topK, score_threshold: threshold },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['datasets'] })
      toast.success('设置已保存')
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const reindexMut = useMutation({
    mutationFn: () => reindexDataset(datasetId, embedModel),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['datasets'] })
      toast.success(`索引已重建：${r.chunk_count} 个分段`)
    },
    onError: (e) => toast.error((e as Error).message),
  })

  if (!dataset) return null

  return (
    <div className="max-w-xl space-y-4">
      <div className="space-y-1.5">
        <label className="text-sm font-medium">名称</label>
        <Input value={name} onChange={(e) => setName(e.target.value)} className="bg-background" />
      </div>
      <div className="space-y-1.5">
        <label className="text-sm font-medium">描述</label>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} className="min-h-[64px] bg-background" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-sm font-medium">分段最大长度</label>
          <Input
            type="number"
            value={maxLength}
            min={100}
            max={2000}
            onChange={(e) => setMaxLength(Number(e.target.value))}
            className="bg-background"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">分段重叠</label>
          <Input
            type="number"
            value={overlap}
            min={0}
            max={400}
            onChange={(e) => setOverlap(Number(e.target.value))}
            className="bg-background"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">检索 Top-K</label>
          <Input
            type="number"
            value={topK}
            min={1}
            max={20}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="bg-background"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium">相似度阈值</label>
          <Input
            type="number"
            step={0.05}
            value={threshold}
            min={0}
            max={1}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="bg-background"
          />
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">分段参数只对之后上传的文档生效</p>
      <div className="space-y-1.5 rounded-xl border p-3">
        <label className="text-sm font-medium">嵌入模型</label>
        <EmbedModelSelect value={embedModel} onChange={setEmbedModel} />
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] text-muted-foreground">
            当前：{dataset.embed_model ?? '默认嵌入模型'}。更换模型需重建全部向量
          </p>
          <Button
            variant="outline"
            size="sm"
            className="h-7 shrink-0 gap-1 text-xs"
            disabled={reindexMut.isPending}
            onClick={() => {
              if (confirm('将用所选嵌入模型重新向量化全部分段，确认继续？')) reindexMut.mutate()
            }}
          >
            <RefreshCw className={`h-3 w-3 ${reindexMut.isPending ? 'animate-spin' : ''}`} />
            重建索引
          </Button>
        </div>
      </div>
      <Button className="gap-1.5" onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !name.trim()}>
        {saveMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        保存设置
      </Button>
    </div>
  )
}

/* ---------- 页面 ---------- */

export default function DatasetDetailPage() {
  const { datasetId } = useParams()
  const { data: dataset, isLoading } = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => getDataset(datasetId!),
    enabled: !!datasetId,
  })

  if (isLoading) return <PageLoading />
  if (!dataset)
    return <div className="p-10 text-center text-sm text-muted-foreground">知识库不存在</div>

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <Link
          to="/datasets"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          返回知识库
        </Link>

        <div className="mt-4 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <Library className="h-6 w-6 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-bold">{dataset.name}</h1>
            <p className="text-xs text-muted-foreground">{dataset.description}</p>
          </div>
        </div>

        <Tabs defaultValue="documents" className="mt-6">
          <TabsList>
            <TabsTrigger value="documents" className="gap-1">
              <FileText className="h-3.5 w-3.5" />
              文档
            </TabsTrigger>
            <TabsTrigger value="hit" className="gap-1">
              <FileSearch className="h-3.5 w-3.5" />
              命中测试
            </TabsTrigger>
            <TabsTrigger value="settings">设置</TabsTrigger>
          </TabsList>
          <TabsContent value="documents">
            <DocumentTab datasetId={dataset.id} />
          </TabsContent>
          <TabsContent value="hit">
            <HitTestingTab datasetId={dataset.id} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab datasetId={dataset.id} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
