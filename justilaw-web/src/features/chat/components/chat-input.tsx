import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CornerDownLeft, Square, Sparkles } from 'lucide-react'
import { listPrompts } from '@/api'
import { Button } from '@/components/ui/button'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { useChatStore } from '@/stores/chat'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  onSend: (text: string) => void
  onStop: () => void
  streaming: boolean
}

export function ChatInput({ onSend, onStop, streaming }: ChatInputProps) {
  const [value, setValue] = useState('')
  const [promptOpen, setPromptOpen] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)
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
    if (!text || streaming) return
    onSend(text)
    setValue('')
    requestAnimationFrame(resize)
  }

  const choosePrompt = (content: string) => {
    setValue(content)
    setPromptOpen(false)
    taRef.current?.focus()
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
    <div className="shrink-0 px-4 pb-4">
      <div className="mx-auto max-w-3xl">
        <Popover open={promptOpen && matched.length > 0} onOpenChange={setPromptOpen}>
          <PopoverAnchor asChild>
            <div className="rounded-2xl border bg-card p-2.5 shadow-sm focus-within:ring-2 focus-within:ring-ring">
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
                <span className="hidden text-[11px] text-muted-foreground sm:inline">
                  AI 生成内容仅供参考，不构成法律意见
                </span>
                {streaming ? (
                  <Button size="sm" variant="secondary" className="gap-1.5" onClick={onStop}>
                    <Square className="h-3.5 w-3.5 fill-current" />
                    停止生成
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    className={cn('h-8 w-8 rounded-lg', !value.trim() && 'opacity-40')}
                    disabled={!value.trim()}
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
            className="w-96 max-h-64 overflow-y-auto p-1.5"
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
