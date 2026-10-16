import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  Check,
  Gavel,
  MessagesSquare,
  ScrollText,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { createConversation, deleteMessage, getAgent, listAgents, setMessageFeedback } from '@/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { SpotlightCard } from '@/components/common/effects'
import { OllamaSetup, useSetupTargets, type SetupTarget } from '@/features/models/ollama-setup'
import { useChatModels } from '@/features/models/use-chat-models'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/stores/chat'
import { ChatHeader } from './components/chat-header'
import { ChatInput } from './components/chat-input'
import { MessageItem } from './components/message-item'
import { SessionSidebar } from './components/session-sidebar'
import { useChatStream } from './hooks/use-chat-stream'
import type { Agent, Message } from '@/types/api'

/* ---------- 空状态（未选会话） ---------- */

const CATEGORY_ICONS: Record<string, typeof Bot> = {
  法律咨询: MessagesSquare,
  司法辅助: Gavel,
  合同文书: ScrollText,
}

function ChatWelcome({ agent, agentId }: { agent?: Agent; agentId?: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const setPrefill = useChatStore((s) => s.setPrefill)
  // 快捷入口取已发布的智能体，而不是写死 ID（Mock 与真实后端的 ID 不同）
  const { data: agents } = useQuery({ queryKey: ['agents'], queryFn: listAgents, enabled: !agent })
  const quickAgents = (agents ?? []).filter((a) => a.status === 'published').slice(0, 6)
  // 还没有任何可用模型：欢迎区直接换成模型连接向导，首次使用不用找设置页
  const { models, isLoading: modelsLoading } = useChatModels()
  const setupTargets = useSetupTargets()
  const [pickedTarget, setPickedTarget] = useState<SetupTarget>()
  const setupTarget = pickedTarget && setupTargets.includes(pickedTarget) ? pickedTarget : setupTargets[0]
  const needsSetup = !modelsLoading && models.length === 0

  const createMut = useMutation({
    mutationFn: (title: string) => createConversation({ title, agent_id: agentId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
  })

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
    <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-6 pb-24">
      {/* Aurora 极光装饰层 */}
      <div className="aurora" aria-hidden />
      <div className="relative z-10 flex flex-col items-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 shadow-lg shadow-primary/10">
        <MessagesSquare className="h-7 w-7 text-primary" />
      </div>
      <h2 className="mt-4 text-lg font-semibold">
        {agent ? agent.name : '有什么法律问题可以帮你？'}
      </h2>
      <p className="mt-1.5 max-w-md text-center text-sm text-muted-foreground">
        {agent?.opening_statement ?? '从左侧新建对话，或从下方内置法律智能体开始'}
      </p>

      {needsSetup ? (
        <div className="glass mt-6 w-full max-w-lg rounded-2xl p-5 text-left shadow-sm">
          <div className="mb-1 text-sm font-semibold">
            {setupTarget === 'browser' ? '先连接你电脑上的 Ollama 模型' : '先连接一个模型'}
          </div>
          <p className="mb-4 text-xs text-muted-foreground">
            {setupTarget === 'browser'
              ? '模型运行在你自己的电脑上，免费且对话内容不经过第三方模型服务。'
              : '检测本机 Ollama 并下载推荐模型，完成后即可开始对话。'}
          </p>
          {setupTargets.length > 1 && (
            <button
              className="mb-3 text-xs text-primary hover:underline"
              onClick={() => setPickedTarget(setupTarget === 'server' ? 'browser' : 'server')}
            >
              {setupTarget === 'server' ? '改为使用我电脑上的 Ollama →' : '改为配置服务器上的 Ollama →'}
            </button>
          )}
          <OllamaSetup key={setupTarget} target={setupTarget} />
        </div>
      ) : agent?.suggested_questions && agent.suggested_questions.length > 0 ? (
        <div className="mt-6 grid w-full max-w-xl gap-2">
          {agent.suggested_questions.map((q, i) => (
            <button
              key={q}
              onClick={() => void startWith(q)}
              style={{ '--stagger-delay': `${i * 60}ms` } as React.CSSProperties}
              className="stagger-item rounded-xl border bg-card px-4 py-2.5 text-left text-sm text-foreground/90 shadow-sm transition-colors hover:border-primary/40 hover:bg-accent"
            >
              {q}
            </button>
          ))}
        </div>
      ) : (
        /* Bento 快捷入口：首个智能体大卡（2 列跨行），其余小卡 */
        <div className="mt-6 grid w-full max-w-xl grid-cols-2 gap-2.5 sm:grid-cols-3">
          {quickAgents.map((a, i) => {
            const Icon = CATEGORY_ICONS[a.category] ?? Bot
            return (
              <SpotlightCard
                key={a.id}
                onClick={() => navigate(`/chat?agentId=${a.id}`, { viewTransition: true })}
                style={{ '--stagger-delay': `${i * 50}ms` } as React.CSSProperties}
                className={cn(
                  'stagger-item flex cursor-pointer flex-col gap-2 rounded-xl border bg-card p-3 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md',
                  i === 0 && 'col-span-2 sm:row-span-2 sm:p-4',
                )}
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <div className={cn('truncate font-medium', i === 0 ? 'text-sm' : 'text-xs')}>
                    {a.name}
                  </div>
                  <p
                    className={cn(
                      'mt-0.5 text-muted-foreground',
                      i === 0 ? 'line-clamp-3 text-xs leading-relaxed' : 'line-clamp-1 text-[11px]',
                    )}
                  >
                    {a.description}
                  </p>
                </div>
              </SpotlightCard>
            )
          })}
        </div>
      )}
      </div>
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
  const qc = useQueryClient()
  const { send, stop, regenerate, editAndResend, isStreaming } = useChatStream(conversationId, agent?.id)
  const { data: messages, isLoading } = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => import('@/api').then((m) => m.listMessages(conversationId)),
    staleTime: Infinity,
  })
  const draft = useChatStore((s) => s.drafts[conversationId])
  const prefill = useChatStore((s) => s.prefill)
  const consumePrefill = useChatStore((s) => s.consumePrefill)
  const sentForRef = useRef(0)
  const [editing, setEditing] = useState<{ id: string; content: string } | null>(null)

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

  // 消息反馈（点赞/点踩落库）：乐观更新，失败后以服务端为准回滚
  const feedbackMut = useMutation({
    mutationFn: ({ msg, rating }: { msg: Message; rating: 'up' | 'down' | null }) =>
      setMessageFeedback(conversationId, msg.id, rating),
    onMutate: ({ msg, rating }) => {
      qc.setQueryData<Message[]>(['messages', conversationId], (old) =>
        (old ?? []).map((m) => (m.id === msg.id ? { ...m, feedback: rating } : m)),
      )
    },
    onError: () => qc.invalidateQueries({ queryKey: ['messages', conversationId] }),
  })

  // 删除单条消息：乐观移除，成功后刷新会话列表（last_message_at 可能变化）
  const deleteMut = useMutation({
    mutationFn: (msg: Message) => deleteMessage(conversationId, msg.id),
    onMutate: (msg) => {
      qc.setQueryData<Message[]>(['messages', conversationId], (old) =>
        (old ?? []).filter((m) => m.id !== msg.id),
      )
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations'] }),
    onError: () => qc.invalidateQueries({ queryKey: ['messages', conversationId] }),
  })

  const list = messages ?? []
  const lastAssistantIdx = draft ? -1 : list.length - 1

  const confirmEdit = async () => {
    if (!editing) return
    const content = editing.content.trim()
    const id = editing.id
    setEditing(null)
    if (content) await editAndResend(id, content)
  }

  // 稳定引用：内联箭头函数会让所有用户消息的 memo 失效（每帧全量重渲染）
  const startEdit = useCallback(
    (msg: Message) => setEditing({ id: msg.id, content: msg.content }),
    [],
  )

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
              <div className="ml-auto h-10 w-1/2 skeleton-shimmer rounded-lg" />
              <div className="h-24 w-3/4 skeleton-shimmer rounded-lg" />
            </div>
          ) : (
            <>
              {list.map((m: Message, i: number) => (
                <div key={m.id}>
                  <MessageItem
                    message={m}
                    isLastAssistant={i === lastAssistantIdx && m.role === 'assistant'}
                    onRegenerate={regenerate}
                    onEdit={m.role === 'user' ? startEdit : undefined}
                    onFeedback={m.role === 'assistant' ? (rating) => feedbackMut.mutate({ msg: m, rating }) : undefined}
                    onDelete={() => deleteMut.mutate(m)}
                  />
                  {editing?.id === m.id && (
                    <div className="ml-auto mt-2 w-[82%] rounded-xl border bg-card p-2.5 shadow-sm">
                      <Textarea
                        autoFocus
                        value={editing.content}
                        onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                        className="min-h-[72px] resize-none border-0 shadow-none focus-visible:ring-0"
                      />
                      <div className="flex justify-end gap-2 pt-1.5">
                        <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                          取消
                        </Button>
                        <Button size="sm" className="gap-1" onClick={() => void confirmEdit()}>
                          <Check className="h-3.5 w-3.5" />
                          保存并重发
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
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
      <ChatInput onSend={(t, atts) => void send(t, 'new', atts)} onStop={stop} streaming={isStreaming} />
    </>
  )
}

/* ---------- 页面 ---------- */

export default function ChatPage() {
  const { conversationId } = useParams()
  const [searchParams] = useSearchParams()
  const agentId = searchParams.get('agentId') ?? undefined
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const { data: agent } = useQuery({
    queryKey: ['agents', agentId],
    queryFn: () => getAgent(agentId!),
    enabled: !!agentId,
  })

  // 切换会话后自动收起移动端侧栏
  useEffect(() => {
    setSidebarOpen(false)
  }, [conversationId])

  return (
    <div className="relative flex h-full">
      <SessionSidebar
        className={cn(
          'max-lg:absolute max-lg:inset-y-0 max-lg:left-0 max-lg:z-40 max-lg:shadow-2xl',
          sidebarOpen ? 'max-lg:flex' : 'max-lg:hidden',
        )}
      />
      {sidebarOpen && (
        <div
          className="absolute inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <ChatHeader conversationId={conversationId} agent={agent} onOpenSidebar={() => setSidebarOpen(true)} />
        {conversationId ? (
          <ConversationView key={conversationId} conversationId={conversationId} agent={agent} />
        ) : (
          <ChatWelcome agent={agent} agentId={agentId} />
        )}
      </div>
    </div>
  )
}
