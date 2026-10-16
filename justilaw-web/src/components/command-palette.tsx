import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Command } from 'cmdk'
import {
  Bot,
  Cpu,
  Library,
  MessagesSquare,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import { listAgents, listConversations, listDatasets } from '@/api'
import { useCurrentUser } from '@/features/auth/use-auth'

/** 全局命令面板（Ctrl/Cmd + K）：搜会话 / 智能体 / 知识库，或直接跳转 */
export function CommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const { data: user } = useCurrentUser()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const { data: conversations } = useQuery({
    queryKey: ['conversations'],
    queryFn: listConversations,
    enabled: open,
  })
  const { data: agents } = useQuery({ queryKey: ['agents'], queryFn: listAgents, enabled: open })
  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets, enabled: open })

  const go = (path: string) => {
    setOpen(false)
    navigate(path)
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="全局命令面板"
      className="fixed left-1/2 top-24 z-50 w-full max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border bg-popover shadow-2xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
      overlayClassName="fixed inset-0 z-50 bg-black/50"
    >
      <div className="flex items-center gap-2 border-b px-4">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
        <Command.Input
          placeholder="搜索会话、智能体、知识库，或输入页面名跳转…"
          className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        <kbd className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">ESC</kbd>
      </div>
      <Command.List className="scrollbar-thin max-h-80 overflow-y-auto p-2">
        <Command.Empty className="py-8 text-center text-sm text-muted-foreground">
          没有匹配结果
        </Command.Empty>

        <Command.Group heading="跳转" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
          {[
            { path: '/chat', label: '对话中心', icon: MessagesSquare },
            { path: '/agents', label: '智能体', icon: Bot },
            { path: '/datasets', label: '知识库', icon: Library },
            { path: '/prompts', label: '提示词库', icon: Sparkles },
            { path: '/models', label: '模型管理', icon: Cpu },
            { path: '/providers', label: '模型服务', icon: Server },
            { path: '/workflows', label: '工作流', icon: WorkflowIcon },
            ...(user?.isAdmin ? [{ path: '/admin', label: '管理后台', icon: ShieldCheck }] : []),
          ].map(({ path, label, icon: Icon }) => (
            <Command.Item
              key={path}
              value={`跳转 ${label}`}
              onSelect={() => go(path)}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors data-[selected=true]:bg-accent"
            >
              <Icon className="h-4 w-4 text-muted-foreground" />
              {label}
            </Command.Item>
          ))}
        </Command.Group>

        {conversations && conversations.length > 0 && (
          <Command.Group heading="最近会话" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
            {conversations.slice(0, 5).map((c) => (
              <Command.Item
                key={c.id}
                value={`会话 ${c.title}`}
                onSelect={() => go(`/chat/${c.id}`)}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors data-[selected=true]:bg-accent"
              >
                <MessagesSquare className="h-4 w-4 text-muted-foreground" />
                <span className="truncate">{c.title}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {agents && agents.length > 0 && (
          <Command.Group heading="智能体" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
            {agents.slice(0, 6).map((a) => (
              <Command.Item
                key={a.id}
                value={`智能体 ${a.name} ${a.category}`}
                onSelect={() => go(`/agents/${a.id}`)}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors data-[selected=true]:bg-accent"
              >
                <Bot className="h-4 w-4 text-muted-foreground" />
                <span className="truncate">{a.name}</span>
                <span className="ml-auto text-xs text-muted-foreground">{a.category}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {datasets && datasets.length > 0 && (
          <Command.Group heading="知识库" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground">
            {datasets.map((d) => (
              <Command.Item
                key={d.id}
                value={`知识库 ${d.name}`}
                onSelect={() => go(`/datasets/${d.id}`)}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors data-[selected=true]:bg-accent"
              >
                <Library className="h-4 w-4 text-muted-foreground" />
                <span className="truncate">{d.name}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  )
}
