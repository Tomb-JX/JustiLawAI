import { LogOut } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { useCurrentUser, useSignOut } from './use-auth'

/** 侧栏底部的当前用户卡片 + 账户菜单 */
export function UserMenu() {
  const { data: user, isLoading } = useCurrentUser()
  const signOut = useSignOut()

  if (isLoading || !user) {
    return <Skeleton className="h-11 w-full rounded-lg" />
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-2.5 rounded-lg bg-muted/60 px-3 py-2 text-left transition-colors hover:bg-muted">
          {user.avatar ? (
            <img src={user.avatar} alt="" className="h-7 w-7 shrink-0 rounded-full object-cover" />
          ) : (
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
              {user.name.slice(0, 1).toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">{user.name}</div>
            <div className="truncate text-[10px] text-muted-foreground">
              {user.isAdmin ? '管理员' : '普通用户'}
            </div>
          </div>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-[var(--radix-dropdown-menu-trigger-width)]">
        <DropdownMenuLabel className="truncate text-xs font-normal text-muted-foreground">
          {user.email ?? user.name}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut />
          退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
