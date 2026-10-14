import { useEffect, useRef } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Gavel, Library, MessagesSquare, ScrollText, FileSearch } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { createConversation, getAgent } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useChatStore } from '@/stores/chat'
import { ChatHeader } from './components/chat-header'
import { ChatInput } from './components/chat-input'
import { MessageItem } from './components/message-item'
import { SessionSidebar } from './components/session-sidebar'
import { useChatStream } from './hooks/use-chat-stream'
import type { Agent, Message } from '@/types/api'

/* ---------- 空状态（未选会话） ---------- */

function ChatWelcome({ agent, agentId }: { agent?: Agent; agentId?: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const setPrefill = useChatStore((s) => s.setPrefill)

  const createMut = useMutation({
    mutationFn: (title: string) => createConversation({ title, agent_id: agentId }),
    onSuccess: invalidate,
  })
  function invalidate() {
    qc.invalidateQueries({ queryKey: ['conversations'] })
  }

  const startWith = async (question: string) => {
    try {
      const conv = await createMut.mutateAsync(question.slice(0, 24))
      setPrefill(question, true)
      navigate(`/chat/${conv.id}${agentId ? `?agentId=${agentId}` : ''}`)
    } catch {
      toast.error('创建会话失败')
    }
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 pb-24">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
        <MessagesSquare className="h-7 w-7 text-primary" />
      </div>
      <h2 className="mt-4 text-lg font-semibold">
        {agent ? agent.name : '有什么法律问题可以帮你？'}
      </h2>
      <p className="mt-1.5 max-w-md text-center text-sm text-muted-foreground">
        {agent?.opening_statement ?? '从左侧新建对话，或从下方内置法律智能体开始'}
      </p>

      {agent?.suggested_questions && agent.suggested_questions.length > 0 ? (
        <div className="mt-6 grid w-full max-w-xl gap-2">
          {agent.suggested_questions.map((q) => (
            <button
              key={q}
              onClick={() => startWith(q)}
              className="rounded-xl border bg-card px-4 py-2.5 text-left text-sm text-foreground/90 shadow-sm transition-colors hover:border-primary/40 hover:bg-accent"
            >
              {q}
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {[
            { id: 'a_1001', name: '法律咨询助手', icon: MessagesSquare },
            { id: 'a_1002', name: '判决预测', icon: Gavel },
            { id: 'a_1003', name: '类案检索', icon: FileSearch },
            { id: 'a_1004', name: '法条解释', icon: ScrollText },
            { id: 'a_1006', name: '知识库问答', icon: Library },
          ].map(({ id, name, icon: Icon }) => (
            <Button
              key={id}
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => navigate(`/chat?agentId=${id}`)}
            >
              <Icon className="h-3.5 w-3.5" />
              {name}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------- 会话视图 ---------- */

function ConversationView({
  conversationId,
  agent,
}: {
  conversationId: string
  agent?: Agent
}) {
  const { send, stop, regenerate, isStreaming } = useChatStream(conversationId, agent?.id)
  const { data: messages, isLoading } = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => import('@/api').then((m) => m.listMessages(conversationId)),
    staleTime: Infinity,
  })
  const draft = useChatStore((s) => s.drafts[conversationId])
  const prefill = useChatStore((s) => s.prefill)
  const consumePrefill = useChatStore((s) => s.consumePrefill)
  const sentForRef = useRef(0)

  // 自动发送的预填（推荐问题 → 建会话后立即提问）
  useEffect(() => {
    if (prefill?.autoSend && sentForRef.current !== prefill.nonce) {
      sentForRef.current = prefill.nonce
      const text = prefill.text
      consumePrefill()
      void send(text)
    }
  }, [prefill, consumePrefill, send])

  const viewportRef = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const onScroll = () => {
    const el = viewportRef.current
    if (!el) return
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140
  }
  useEffect(() => {
    if (stick.current) viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight })
  }, [messages?.length, draft?.content, draft?.status])

  const list = messages ?? []
  const lastAssistantIdx = draft ? -1 : list.length - 1

  return (
    <>
      <div
        ref={viewportRef}
        onScroll={onScroll}
        className="scrollbar-thin flex-1 overflow-y-auto px-4 py-6"
      >
        <div className="mx-auto max-w-3xl space-y-5">
          {isLoading ? (
            <div className="space-y-3">
              <Skeleton className="ml-auto h-10 w-1/2" />
              <Skeleton className="h-24 w-3/4" />
            </div>
          ) : (
            <>
              {list.map((m, i) => (
                <MessageItem
                  key={m.id}
                  message={m}
                  isLastAssistant={i === lastAssistantIdx && m.role === 'assistant'}
                  onRegenerate={regenerate}
                />
              ))}
              {draft && (
                <MessageItem
                  message={{ ...draft, role: 'assistant' as const }}
                  streaming={draft.status === 'streaming'}
                />
              )}
              {draft?.status === 'error' && (
                <p className="text-center text-xs text-destructive">生成失败，请重试</p>
              )}
              {draft?.status === 'aborted' && (
                <p className="text-center text-xs text-muted-foreground">已停止生成</p>
              )}
            </>
          )}
        </div>
      </div>
      <ChatInput onSend={(t) => void send(t)} onStop={stop} streaming={isStreaming} />
    </>
  )
}

/* ---------- 页面 ---------- */

export default function ChatPage() {
  const { conversationId } = useParams()
  const [searchParams] = useSearchParams()
  const agentId = searchParams.get('agentId') ?? undefined

  const { data: agent } = useQuery({
    queryKey: ['agents', agentId],
    queryFn: () => getAgent(agentId!),
    enabled: !!agentId,
  })

  return (
    <div className="flex h-full">
      <SessionSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader conversationId={conversationId} agent={agent} />
        {conversationId ? (
          <ConversationView key={conversationId} conversationId={conversationId} agent={agent} />
        ) : (
          <ChatWelcome agent={agent} agentId={agentId} />
        )}
      </div>
    </div>
  )
}
