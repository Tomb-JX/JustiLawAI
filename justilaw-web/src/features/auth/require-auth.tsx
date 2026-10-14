import { useEffect, useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useLogto } from '@logto/react'
import { setAccessTokenGetter, setUnauthorizedHandler } from '@/api/client'
import { PageLoading } from '@/components/common/misc'
import { API_RESOURCE } from './logto-config'
import { useSignIn } from './use-auth'

/** 路由守卫：未登录跳 /login，并把 Logto token 注入 api 层 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, getAccessToken } = useLogto()
  const signIn = useSignIn()
  const location = useLocation()
  const returnTo = `${location.pathname}${location.search}`

  // 401 处理器只读最新路径，避免每次路由变化都重新注册
  const returnToRef = useRef(returnTo)
  returnToRef.current = returnTo
  const reauthingRef = useRef(false)

  useEffect(() => {
    if (!isAuthenticated) return
    // 未配置 API Resource 时拿不到面向后端的 JWT，宁可不带也不误传 ID Token
    setAccessTokenGetter(API_RESOURCE ? () => getAccessToken(API_RESOURCE) : undefined)
    setUnauthorizedHandler(() => {
      // 并发请求同时 401 时只发起一次重新登录
      if (reauthingRef.current) return
      reauthingRef.current = true
      void signIn({ returnTo: returnToRef.current })
    })
    return () => {
      setAccessTokenGetter(undefined)
      setUnauthorizedHandler(undefined)
    }
  }, [isAuthenticated, getAccessToken, signIn])

  // Logto 在取 token 等异步操作期间也会置 isLoading，已登录时不能因此卸载整个应用
  if (!isAuthenticated) {
    if (isLoading) return <div className="h-screen"><PageLoading /></div>
    return <Navigate to="/login" state={{ returnTo }} replace />
  }

  return children
}
