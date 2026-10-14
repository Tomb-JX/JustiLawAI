import { BookOpen, Copy, Download, FileText, Gavel, Scale, ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { CaseItem, DocumentPayload, MessageCard, PredictionPayload, RiskItem } from '@/types/api'

/** 结构化输出卡片：法律平台区别于通用 AI 应用的关键呈现形式 */

function PredictionCard({ payload }: { payload: PredictionPayload }) {
  const conf = Math.round(payload.confidence * 100)
  return (
    <div className="mt-3 w-full max-w-lg overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b bg-muted/50 px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Gavel className="h-4 w-4 text-primary" />
          判决预测结果
        </span>
        <Badge variant="outline" className="text-amber-600 border-amber-300 dark:border-amber-800">
          AI 预测 · 仅供参考
        </Badge>
      </div>
      <div className="space-y-4 p-4 text-sm">
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-muted-foreground">预测罪名</span>
            <span className="font-medium text-muted-foreground">置信度 {conf}%</span>
          </div>
          <div className="text-lg font-semibold text-primary">{payload.crime}</div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${conf}%` }}
            />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-2 rounded-lg bg-muted/60 p-3">
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-muted-foreground" />
            <span>{payload.punishment.type}</span>
          </div>
          {payload.punishment.detention_days && (
            <div className="text-muted-foreground">
              刑期/拘留区间：{payload.punishment.detention_days[0]} ~{' '}
              {payload.punishment.detention_days[1]} 个月
            </div>
          )}
          {payload.punishment.fine && (
            <div className="text-muted-foreground">
              罚金区间：¥{payload.punishment.fine[0].toLocaleString()} ~ ¥
              {payload.punishment.fine[1].toLocaleString()}
            </div>
          )}
        </div>
        <div>
          <div className="mb-1.5 text-muted-foreground">依据</div>
          <ul className="space-y-1">
            {payload.basis.map((b) => (
              <li key={b} className="flex items-center gap-2">
                <BookOpen className="h-3.5 w-3.5 shrink-0 text-primary" />
                {b}
              </li>
            ))}
          </ul>
        </div>
        {payload.note && <p className="text-xs leading-relaxed text-muted-foreground">{payload.note}</p>}
      </div>
    </div>
  )
}

function CaseListCard({ items }: { items: CaseItem[] }) {
  return (
    <div className="mt-3 w-full max-w-lg space-y-2">
      {items.map((c) => (
        <div key={c.case_no} className="rounded-xl border bg-card p-3.5 shadow-sm transition-colors hover:border-primary/40">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs text-primary">{c.case_no}</span>
            <span className="shrink-0 text-xs font-medium text-amber-600">
              相似度 {(c.score * 100).toFixed(0)}%
            </span>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed">{c.summary}</p>
          <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{c.court}</span>
            <Badge variant="secondary">{c.result}</Badge>
          </div>
        </div>
      ))}
    </div>
  )
}

const levelMap: Record<RiskItem['level'], { label: string; cls: string }> = {
  high: { label: '高风险', cls: 'bg-red-500/10 text-red-600 border-red-200 dark:border-red-900' },
  medium: { label: '中风险', cls: 'bg-amber-500/10 text-amber-600 border-amber-200 dark:border-amber-900' },
  low: { label: '低风险', cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-200 dark:border-emerald-900' },
}

function RiskListCard({ items }: { items: RiskItem[] }) {
  return (
    <div className="mt-3 w-full max-w-lg space-y-2">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <ShieldAlert className="h-4 w-4 text-amber-600" />
        合同风险清单
      </div>
      {items.map((r, i) => (
        <div key={i} className="rounded-xl border bg-card p-3.5 text-sm shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{r.clause}</span>
            <Badge variant="outline" className={levelMap[r.level].cls}>
              {levelMap[r.level].label}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">位置：{r.position}</p>
          <p className="mt-1.5 leading-relaxed">
            <span className="text-muted-foreground">建议：</span>
            {r.suggestion}
          </p>
        </div>
      ))}
    </div>
  )
}

function DocumentCardView({ payload }: { payload: DocumentPayload }) {
  const copy = async () => {
    await navigator.clipboard.writeText(payload.content)
    toast.success('文书已复制到剪贴板')
  }
  const download = () => {
    const blob = new Blob([payload.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${payload.title}.md`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="mt-3 w-full max-w-lg overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b bg-muted/50 px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <FileText className="h-4 w-4 text-primary" />
          {payload.title}
        </span>
        <Badge variant="secondary">{payload.doc_type}</Badge>
      </div>
      <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap px-4 py-3 font-sans text-sm leading-relaxed">
        {payload.content}
      </pre>
      <div className="flex justify-end gap-2 border-t px-4 py-2.5">
        <Button variant="outline" size="sm" className="gap-1" onClick={copy}>
          <Copy className="h-3.5 w-3.5" />
          复制
        </Button>
        <Button variant="outline" size="sm" className="gap-1" onClick={download}>
          <Download className="h-3.5 w-3.5" />
          下载 .md
        </Button>
      </div>
    </div>
  )
}

export function MessageCardView({ card }: { card: MessageCard }) {
  switch (card.card_type) {
    case 'prediction':
      return <PredictionCard payload={card.payload as PredictionPayload} />
    case 'case_list':
      return <CaseListCard items={card.payload as CaseItem[]} />
    case 'risk_list':
      return <RiskListCard items={card.payload as RiskItem[]} />
    case 'document':
      return <DocumentCardView payload={card.payload as DocumentPayload} />
    default:
      return (
        <div className="mt-3 flex items-center gap-2 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
          <FileText className="h-4 w-4" />
          附件卡片内容
        </div>
      )
  }
}
