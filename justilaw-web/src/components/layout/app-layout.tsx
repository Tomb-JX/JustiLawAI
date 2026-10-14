import { NavLink, Outlet } from 'react-router-dom'
import {
  Bot,
  Cpu,
  Library,
  MessagesSquare,
  Moon,
  Scale,
  Server,
  ShieldCheck,
  Sparkles,
  Sun,
  Workflow,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CommandPalette } from '@/components/command-palette'
import { UserMenu } from '@/features/auth/user-menu'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/chat', label: '对话', icon: MessagesSquare },
  { to: '/agents', label: '智能体', icon: Bot },
  { to: '/datasets', label: '知识库', icon: Library },
  { to: '/prompts', label: '提示词', icon: Sparkles },
  { to: '/models', label: '模型', icon: Cpu },
  { to: '/providers', label: '模型服务', icon: Server },
  { to: '/workflows', label: '工作流', icon: Workflow },
  { to: '/admin', label: '管理后台', icon: ShieldCheck },
]

export function AppLayout() {
  const { theme, toggle } = useTheme()

  return (
    <div className="flex h-screen overflow-hidden">
      {/* 左侧主导航 */}
      <aside className="hidden w-56 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary">
            <Scale className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight">JustiLawAI</div>
            <div className="text-[11px] text-muted-foreground">法律智能体工作平台</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-accent font-medium text-primary'
                    : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-2 border-t p-3">
          <Button variant="ghost" size="sm" className="w-full justify-start gap-3" onClick={toggle}>
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {theme === 'dark' ? '浅色模式' : '深色模式'}
          </Button>
          <UserMenu />
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>

      <CommandPalette />
    </div>
  )
}
