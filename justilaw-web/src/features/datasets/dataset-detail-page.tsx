import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileSearch, FileText, Library, Loader2, Search, Upload } from 'lucide-react'
import { toast } from 'sonner'
import {
  getDataset,
  hitTesting,
  listDocuments,
  uploadDocument,
} from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { formatBytes } from '@/lib/utils'
import type { DocumentStatus } from '@/types/api'

const statusBadge: Record<DocumentStatus, { label: string; cls: string }> = {
  queued: { label: '排队中', cls: 'bg-secondary text-secondary-foreground' },
  parsing: { label: '解析中', cls: 'bg-amber-500/10 text-amber-600 animate-pulse' },
  completed: { label: '已完成', cls: 'bg-emerald-500/10 text-emerald-600' },
  failed: { label: '失败', cls: 'bg-destructive/10 text-destructive' },
}

function DocumentTab({ datasetId }: { datasetId: string }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: documents, isLoading } = useQuery({
    queryKey: ['documents', datasetId],
    queryFn: () => listDocuments(datasetId),
    // 有解析中的文档时轮询
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === 'parsing' || d.status === 'queued') ? 1500 : false,
  })

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadDocument(datasetId, file.name, file.size),
    onSuccess: () => {
      toast.success('已上传，解析中…')
      qc.invalidateQueries({ queryKey: ['documents', datasetId] })
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
      <p className="mt-1.5 text-[11px] text-muted-foreground">支持 PDF / DOCX / TXT / MD，单文件 ≤ 20MB</p>

      <div className="mt-4 space-y-2">
        {isLoading ? (
          <PageLoading />
        ) : (
          documents?.map((doc) => {
            const s = statusBadge[doc.status]
            return (
              <div
                key={doc.id}
                className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-sm"
              >
                <FileText className="h-4.5 w-4.5 h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{doc.filename}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {formatBytes(doc.size)} · {doc.chunk_count} 个分段 ·{' '}
                    {new Date(doc.created_at).toLocaleDateString()}
                  </div>
                </div>
                <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${s.cls}`}>{s.label}</span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

interface HitResult {
  chunk: { id: string; content: string; index: number; document_id: string }
  score: number
}

function HitTestingTab({ datasetId }: { datasetId: string }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HitResult[] | null>(null)

  const mut = useMutation({
    mutationFn: () => hitTesting(datasetId, query.trim(), 5),
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
        <Button
          className="gap-1.5"
          disabled={!query.trim() || mut.isPending}
          onClick={() => mut.mutate()}
        >
          {mut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          命中测试
        </Button>
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
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border bg-card p-4 text-sm">
                <div className="mb-2 font-medium">分段设置</div>
                <div className="space-y-1 text-muted-foreground">
                  <div>分段最大长度：{dataset.chunk_config.max_length} 字符</div>
                  <div>分段重叠：{dataset.chunk_config.overlap} 字符</div>
                </div>
              </div>
              <div className="rounded-xl border bg-card p-4 text-sm">
                <div className="mb-2 font-medium">检索设置</div>
                <div className="space-y-1 text-muted-foreground">
                  <div>Top-K：{dataset.retrieval_config.top_k}</div>
                  <div>相似度阈值：{dataset.retrieval_config.score_threshold}</div>
                </div>
              </div>
            </div>
            <Badge variant="outline" className="mt-3">
              分段与检索参数修改将于 M3 联调后端时开放
            </Badge>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
