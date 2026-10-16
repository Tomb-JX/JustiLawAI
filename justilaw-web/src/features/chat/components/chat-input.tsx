import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CornerDownLeft, FileText, Loader2, Paperclip, Square, Sparkles, X } from 'lucide-react'
import { toast } from 'sonner'
import { listPrompts, uploadFile } from '@/api'
import { Button } from '@/components/ui/button'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { useChatStore } from '@/stores/chat'
import { cn, formatBytes } from '@/lib/utils'
import type { Attachment } from '@/types/api'

interface ChatInputProps {
  onSend: (text: string, attachments?: { file_id: string; filename: string }[]) => void
  onStop: () => void
  streaming: boolean
}

export function ChatInput({ onSend, onStop, streaming }: ChatInputProps) {
  const [value, setValue] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const { data: prompts } = useQuery({ queryKey: ['prompts'], queryFn: listPrompts })

  const prefill = useChatStore((s) => s.prefill)
  const consumePrefill = useChatStore((s) => s.consumePrefill)

  // 非自动发送的预填（推荐问题点击 → 仅填入输入框）
  useEffect(() => {
    if (prefill && !prefill.autoSend) {
      setValue(prefill.text)
      consumePrefill()
      taRef.current?.focus()
    }
  }, [prefill, consumePrefill])

  // 输入 / 唤起提示词菜单
  const isPromptQuery = value.startsWith('/') && !value.includes('\n')
  useEffect(() => {
    setPromptOpen(isPromptQuery)
  }, [isPromptQuery, value])

  const kw = isPromptQuery ? value.slice(1).toLowerCase() : ''
  const matched = (prompts ?? []).filter(
    (p) => p.name.toLowerCase().includes(kw) || p.content.toLowerCase().includes(kw),
  )

  const resize = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`
  }

  const doSend = () => {
    const text = value.trim()
    if ((!text && attachments.length === 0) || streaming) return
    onSend(
      text || '请分析我上传的文件',
      attachments.map((a) => ({ file_id: a.file_id, filename: a.filename })),
    )
    setValue('')
    setAttachments([])
    requestAnimationFrame(resize)
  }

  const choosePrompt = (content: string) => {
    setValue(content)
    setPromptOpen(false)
    taRef.current?.focus()
  }

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const f of Array.from(files)) {
        const res = await uploadFile(f)
        setAttachments((prev) => [...prev, res])
      }
    } catch (e) {
      toast.error(`附件上传失败：${(e as Error).message}`)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      if (promptOpen && matched.length > 0) choosePrompt(matched[0].content)
      else doSend()
    }
    if (e.key === 'Escape' && promptOpen) setPromptOpen(false)
  }

  return (
    <div className="shrink-0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
      <div className="mx-auto max-w-3xl">
        <Popover open={promptOpen && matched.length > 0} onOpenChange={setPromptOpen}>
          <PopoverAnchor asChild>
            <div
              className={cn(
                'rounded-2xl border bg-card p-2.5 shadow-sm transition-shadow focus-within:ring-2 focus-within:ring-ring',
                streaming && 'flow-border border-transparent',
              )}
            >
              {/* 附件列表 */}
              {(attachments.length > 0 || uploading) && (
                <div className="flex flex-wrap gap-1.5 px-1 pb-2">
                  {attachments.map((a) => (
                    <span
                      key={a.file_id}
                      className="inline-flex items-center gap-1.5 rounded-md border bg-muted/60 px-2 py-1 text-xs"
                    >
                      <FileText className="h-3 w-3 text-primary" />
                      <span className="max-w-[160px] truncate">{a.filename}</span>
                      <span className="text-muted-foreground">{formatBytes(a.size)}</span>
                      <button
                        onClick={() => setAttachments((prev) => prev.filter((x) => x.file_id !== a.file_id))}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                  {uploading && (
                    <span className="inline-flex items-center gap-1.5 rounded-md border bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      解析中…
                    </span>
                  )}
                </div>
              )}

              <Textarea
                ref={taRef}
                value={value}
                onChange={(e) => {
                  setValue(e.target.value)
                  resize()
                }}
                onKeyDown={onKeyDown}
                placeholder="输入法律问题…（Enter 发送，Shift+Enter 换行，输入 / 唤起提示词）"
                className="min-h-[44px] resize-none border-0 px-2 py-1.5 shadow-none focus-visible:ring-0"
                rows={1}
              />
              <div className="flex items-center justify-between px-1 pt-1.5">
                <div className="flex items-center gap-1">
                  <input
                    ref={fileRef}
                    type="file"
                    multiple
                    accept=".pdf,.docx,.txt,.md,.json,.csv"
                    className="hidden"
                    onChange={(e) => void addFiles(e.target.files)}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-muted-foreground"
                    onClick={() => fileRef.current?.click()}
                    disabled={uploading}
                  >
                    <Paperclip className="h-4 w-4" />
                  </Button>
                  <span className="hidden text-[11px] text-muted-foreground sm:inline">
                    AI 生成内容仅供参考，不构成法律意见
                  </span>
                </div>
                {streaming ? (
                  <Button size="sm" variant="secondary" className="gap-1.5" onClick={onStop}>
                    <Square className="h-3.5 w-3.5 fill-current" />
                    停止生成
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    className={cn('h-8 w-8 rounded-lg', !value.trim() && attachments.length === 0 && 'opacity-40')}
                    disabled={!value.trim() && attachments.length === 0}
                    onClick={doSend}
                  >
                    <CornerDownLeft className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          </PopoverAnchor>
          <PopoverContent
            side="top"
            align="start"
            className="w-[min(24rem,calc(100vw-2rem))] max-h-64 overflow-y-auto p-1.5"
            onOpenAutoFocus={(e) => e.preventDefault()}
          >
            <div className="px-2 py-1 text-[11px] text-muted-foreground">提示词模板</div>
            {matched.map((p) => (
              <button
                key={p.id}
                onClick={() => choosePrompt(p.content)}
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
              >
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                <span className="min-w-0">
                  <span className="block font-medium">{p.name}</span>
                  <span className="mt-0.5 line-clamp-1 block text-xs text-muted-foreground">
                    {p.content}
                  </span>
                </span>
              </button>
            ))}
          </PopoverContent>
        </Popover>
      </div>
    </div>
  )
}
