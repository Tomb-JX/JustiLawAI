import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, FileText, Library } from 'lucide-react'
import { listDatasets } from '@/api'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'

export default function DatasetsPage() {
  const navigate = useNavigate()
  const { data: datasets, isLoading } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="text-xl font-bold">知识库</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          管理法律语料（RAG 检索源）；对话中开启"知识库"开关即可引用
        </p>

        {isLoading ? (
          <PageLoading />
        ) : (
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {datasets?.map((d) => (
              <div
                key={d.id}
                className="rounded-2xl border bg-card p-4 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
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
    </div>
  )
}
