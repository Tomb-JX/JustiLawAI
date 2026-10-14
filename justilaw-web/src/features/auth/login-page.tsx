import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useLogto } from '@logto/react'
import { Loader2, LogIn, Scale, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { useSignIn } from './use-auth'

export default function LoginPage() {
  const { isAuthenticated, isLoading, error } = useLogto()
  const signIn = useSignIn()
  const location = useLocation()
  const returnTo = (location.state as { returnTo?: string } | null)?.returnTo
  const [pending, setPending] = useState<'login' | 'register'>()

  if (isAuthenticated) return <Navigate to={returnTo ?? '/chat'} replace />
  if (isLoading && !pending) return <div className="h-screen"><PageLoading /></div>

  const start = (mode: 'login' | 'register') => {
    setPending(mode)
    void signIn({ returnTo, register: mode === 'register' })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm rounded-2xl border bg-card p-8 shadow-sm">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary">
            <Scale className="h-6 w-6 text-primary-foreground" />
          </div>
          <h1 className="mt-4 text-xl font-bold tracking-tight">登录 JustiLawAI</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">法律智能体工作平台</p>
        </div>

        <div className="mt-8 space-y-3">
          <Button className="w-full" size="lg" disabled={!!pending} onClick={() => start('login')}>
            {pending === 'login' ? <Loader2 className="animate-spin" /> : <LogIn />}
            登录
          </Button>
          <Button
            className="w-full"
            size="lg"
            variant="outline"
            disabled={!!pending}
            onClick={() => start('register')}
          >
            {pending === 'register' ? <Loader2 className="animate-spin" /> : <UserPlus />}
            注册新账号
          </Button>
        </div>

        {error && (
          <p className="mt-4 text-center text-xs text-destructive">登录服务异常：{error.message}</p>
        )}

        <p className="mt-6 text-center text-xs text-muted-foreground">
          账号由 Logto 统一认证，将跳转至安全登录页
        </p>
      </div>
    </div>
  )
}
