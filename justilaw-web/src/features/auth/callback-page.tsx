import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useHandleSignInCallback } from '@logto/react'
import { buttonVariants } from '@/components/ui/button'
import { PageLoading } from '@/components/common/misc'
import { readReturnTo } from './use-auth'

export default function CallbackPage() {
  const [searchParams] = useSearchParams()
  const isSignInRedirect = searchParams.has('code') || searchParams.has('error')
  const { isLoading, isAuthenticated, error } = useHandleSignInCallback()

  if (error) {
    return (
      <div className="flex h-screen flex-col items-center justify-center px-4 text-center">
        <p className="text-sm font-medium">登录失败</p>
        <p className="mt-1.5 text-xs text-muted-foreground">{error.message}</p>
        <Link to="/login" replace className={`${buttonVariants({ variant: 'outline' })} mt-5`}>
          重新登录
        </Link>
      </div>
    )
  }

  if (!isLoading && isAuthenticated) return <Navigate to={readReturnTo()} replace />
  // 直接访问 /callback（非登录回跳）时不会触发回调。必须先判断 URL 参数：
  // Logto 初始化完成到处理回调之间有一帧 isLoading=false，此时跳走会丢掉授权码
  if (!isLoading && !isSignInRedirect) return <Navigate to="/login" replace />

  return (
    <div className="h-screen">
      <PageLoading />
    </div>
  )
}
