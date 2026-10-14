import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { MessageSquarePlus, MoreHorizontal, Pencil, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { createConversation, deleteConversation, listConversations, updateConversation } from '@/api'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/types/api'

function groupConversations(list: Conversation[]) {
  const now = dayjs()
  const pinned = list.filter((c) => c.pinned)
  const rest = list.filter((c) => !c.pinned)
  const today: Conversation[] = []
  const week: Conversation[] = []
  const earlier: Conversation[] = []
  for (const c of rest) {
    const d = dayjs(c.last_message_at)
    if (d.isSame(now, 'day')) today.push(c)
    else if (d.isAfter(now.subtract(7, 'day'))) week.push(c)
    else earlier.push(c)
  }
  return [
    { label: '置顶', items: pinned },
    { label: '今天', items: today },
    { label: '7 天内', items: week },
    { label: '更早', items: earlier },
  ].filter((g) => g.items.length > 0)
}

export function SessionSidebar() {
  const navigate = useNavigate()
  const { conversationId } = useParams()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const { data: conversations, isLoading } = useQuery({
    queryKey: ['conversations'],
    queryFn: listConversations,
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['conversations'] })

  const createMut = useMutation({
    mutationFn: () => createConversation({ title: '新对话' }),
    onSuccess: (conv) => {
      invalidate()
      navigate(`/chat/${conv.id}`)
    },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { title?: string; pinned?: boolean } }) =>
      updateConversation(id, patch),
    onSuccess: invalidate,
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: (_d, id) => {
      invalidate()
      if (id === conversationId) navigate('/chat')
      toast.success('会话已删除')
    },
  })

  const groups = useMemo(() => {
    const kw = search.trim().toLowerCase()
    const filtered = (conversations ?? []).filter((c) => !kw || c.title.toLowerCase().includes(kw))
    return groupConversations(filtered)
  }, [conversations, search])

  const commitRename = (id: string) => {
    const title = renameValue.trim()
    if (title) updateMut.mutate({ id, patch: { title } })
    setRenamingId(null)
  }

  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r bg-card lg:flex">
      <div className="space-y-2.5 p-3">
        <Button className="w-full justify-start gap-2" onClick={() => createMut.mutate()}>
          <MessageSquarePlus className="h-4 w-4" />
          新建对话
        </Button>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索会话…"
            className="h-8 bg-background pl-8"
          />
        </div>
      </div>

      <div className="scrollbar-thin flex-1 space-y-3 overflow-y-auto px-3 pb-3">
        {isLoading &&
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}

        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-1.5 pb-1 pt-1 text-[11px] font-medium text-muted-foreground">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((conv) => {
                const active = conv.id === conversationId
                if (renamingId === conv.id) {
                  return (
                    <Input
                      key={conv.id}
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => commitRename(conv.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename(conv.id)
                        if (e.key === 'Escape') setRenamingId(null)
                      }}
                      className="h-8"
                    />
                  )
                }
                return (
                  <div
                    key={conv.id}
                    onClick={() => navigate(`/chat/${conv.id}`)}
                    className={cn(
                      'group flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm transition-colors',
                      active
                        ? 'bg-accent font-medium text-primary'
                        : 'text-foreground/80 hover:bg-accent/60',
                    )}
                  >
                    {conv.pinned && <Pin className="h-3 w-3 shrink-0 text-primary" />}
                    <span className="min-w-0 flex-1 truncate">{conv.title}</span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                        <button
                          className={cn(
                            'rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100',
                            active && 'opacity-100',
                          )}
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-36">
                        <DropdownMenuItem
                          onClick={(e) => {
                            e.stopPropagation()
                            updateMut.mutate({ id: conv.id, patch: { pinned: !conv.pinned } })
                          }}
                        >
                          {conv.pinned ? <PinOff /> : <Pin />}
                          {conv.pinned ? '取消置顶' : '置顶'}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={(e) => {
                            e.stopPropagation()
                            setRenameValue(conv.title)
                            setRenamingId(conv.id)
                          }}
                        >
                          <Pencil />
                          重命名
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation()
                            deleteMut.mutate(conv.id)
                          }}
                        >
                          <Trash2 />
                          删除
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )
              })}
            </div>
          </div>
        ))}

        {!isLoading && groups.length === 0 && (
          <p className="px-2 py-8 text-center text-xs text-muted-foreground">
            {search ? '没有匹配的会话' : '暂无会话，点击上方新建'}
          </p>
        )}
      </div>
    </aside>
  )
}
