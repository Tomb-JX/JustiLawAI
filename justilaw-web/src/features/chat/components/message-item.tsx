import { memo, useDeferredValue, useState } from 'react'
import {
  Bot,
  Brain,
  Check,
  Copy,
  FileText,
  Pencil,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  User,
} from 'lucide-react'
import { toast } from 'sonner'
import { MarkdownRenderer } from '@/components/markdown/MarkdownRenderer'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { MessageCardView } from './cards'
import type { DraftMessage } from '@/stores/chat'
import type { Message } from '@/types/api'

function CitationChips({ items }: { items: NonNullable<Message['citations']> }) {
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      {items.map((c) => (
        <Popover key={c.index}>
          <PopoverTrigger asChild>
            <button className="inline-flex max-w-[240px] items-center gap-1 rounded-md border bg-muted/50 px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
              <span className="font-semibold text-amber-600">[{c.index}]</span>
              <span className="truncate">{c.source}</span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80">
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed">
              {c.snippet}
            </p>
            <div className="mt-2.5 flex items-center justify-between border-t pt-2 text-xs text-muted-foreground">
              <span>{c.source}</span>
              <span>相关度 {(c.score * 100).toFixed(0)}%</span>
            </div>
          </PopoverContent>
        </Popover>
      ))}
    </div>
  )
}

interface MessageItemProps {
  message: Message | (DraftMessage & { role: 'assistant' })
  streaming?: boolean
  isLastAssistant?: boolean
  onRegenerate?: () => void
  onEdit?: (message: Message) => void
}

export const MessageItem = memo(function MessageItem({
  message,
  streaming,
  isLastAssistant,
  onRegenerate,
  onEdit,
}: MessageItemProps) {
  const [copied, setCopied] = useState(false)
  const [showReasoning, setShowReasoning] = useState(false)
  // 流式期间 token 高频落盘：延迟值让 React 可中断重量级 markdown 重解析，输入/滚动保持响应
  const deferredContent = useDeferredValue(message.content)
  const isUser = message.role === 'user'
  const attachments = 'attachments' in message ? message.attachments : undefined

  const copy = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    toast.success('已复制到剪贴板')
    setTimeout(() => setCopied(false), 1500)
  }

  if (isUser) {
    return (
      <div className="group flex justify-end animate-fade-in">
        <div className="flex max-w-[82%] items-start gap-2.5">
          <div className="min-w-0">
            <div className="whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground">
              {message.content}
            </div>
            {attachments && attachments.length > 0 && (
              <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
                {attachments.map((a) => (
                  <span
                    key={a.file_id}
                    className="inline-flex items-center gap-1 rounded-md border bg-muted/50 px-1.5 py-0.5 text-xs text-muted-foreground"
                  >
                    <FileText className="h-3 w-3" />
                    {a.filename}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-1 flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 max-lg:opacity-100">
              <Button variant="ghost" size="icon" className="h-6.5 h-7 w-7" onClick={copy}>
                {copied ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
              </Button>
              {onEdit && (
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onEdit(message)}>
                  <Pencil className="h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary">
            <User className="h-4 w-4 text-secondary-foreground" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="group flex animate-fade-in">
      <div className="flex max-w-[92%] items-start gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary">
          <Bot className="h-4 w-4 text-primary-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          {/* 思维链（推理模型场景） */}
          {'reasoning' in message && message.reasoning && (
            <div className="mb-2">
              <button
                onClick={() => setShowReasoning((v) => !v)}
                className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <Brain className="h-3 w-3" />
                {streaming && !message.content ? '深度思考中…' : `深度思考（点击${showReasoning ? '收起' : '展开'}）`}
              </button>
              {showReasoning && (
                <div className="mt-1.5 rounded-lg border bg-muted/40 p-2.5 text-xs leading-relaxed text-muted-foreground">
                  {message.reasoning}
                </div>
              )}
            </div>
          )}
          <div className={cn(streaming && 'stream-caret')}>
            <MarkdownRenderer content={deferredContent} />
          </div>
          {'card' in message && message.card && <MessageCardView card={message.card} />}
          {'citations' in message && message.citations && message.citations.length > 0 && (
            <CitationChips items={message.citations} />
          )}
          {!streaming && (
            <div className="mt-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 max-lg:opacity-100">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={copy}>
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
              {isLastAssistant && onRegenerate && (
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRegenerate}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => toast.success('已记录反馈，感谢！')}
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => toast.success('已记录反馈，感谢！')}
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
              {'usage' in message && message.usage && (
                <span className="ml-1 text-[11px] text-muted-foreground">
                  {message.usage.prompt_tokens + message.usage.completion_tokens} tokens
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
})
