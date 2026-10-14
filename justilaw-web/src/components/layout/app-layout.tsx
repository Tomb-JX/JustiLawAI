import { Suspense, lazy, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  Bot,
  Cpu,
  Library,
  Menu,
  MessagesSquare,
  Moon,
  Scale,
  Server,
  ShieldCheck,
  Sparkles,
  Sun,
  Workflow,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { UserMenu } from '@/features/auth/user-menu'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

// 命令面板体积大（cmdk + api/axios），非首屏必需，按需加载
const CommandPalette = lazy(() =>
  import('@/components/command-palette').then((m) => ({ default: m.CommandPalette })),
)

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

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
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
  )
}

export function AppLayout() {
  const { theme, toggle } = useTheme()
  const [navOpen, setNavOpen] = useState(false)

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* 桌面左侧主导航 */}
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

        <NavList />

        <div className="space-y-2 border-t p-3">
          <Button variant="ghost" size="sm" className="w-full justify-start gap-3" onClick={toggle}>
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {theme === 'dark' ? '浅色模式' : '深色模式'}
          </Button>
          <UserMenu />
        </div>
      </aside>

      {/* 移动端抽屉导航（触屏主导航 + 主题/账号入口） */}
      {navOpen && (
        <div className="absolute inset-0 z-40 bg-black/40 md:hidden" onClick={() => setNavOpen(false)} />
      )}
      <aside
        className={cn(
          'absolute inset-y-0 left-0 z-50 flex w-64 flex-col border-r bg-card transition-transform duration-200 md:hidden',
          navOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex items-center justify-between gap-2.5 px-4 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary">
              <Scale className="h-5 w-5 text-primary-foreground" />
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight">JustiLawAI</div>
              <div className="text-[11px] text-muted-foreground">法律智能体工作平台</div>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setNavOpen(false)}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <NavList onNavigate={() => setNavOpen(false)} />

        <div className="space-y-2 border-t p-3">
          <Button variant="ghost" size="sm" className="w-full justify-start gap-3" onClick={toggle}>
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {theme === 'dark' ? '浅色模式' : '深色模式'}
          </Button>
          <UserMenu />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 移动端顶栏：汉堡菜单 + 品牌名 + 主题切换 */}
        <div className="flex h-11 shrink-0 items-center gap-1 border-b bg-card/50 px-2 md:hidden">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setNavOpen(true)}>
            <Menu className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-1.5">
            <Scale className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold">JustiLawAI</span>
          </div>
          <div className="ml-auto">
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={toggle}>
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        <main className="min-w-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>

      <Suspense fallback={null}>
        <CommandPalette />
      </Suspense>
    </div>
  )
}
