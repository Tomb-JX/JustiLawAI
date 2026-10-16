import { useEffect, useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useLogto } from '@logto/react'
import { setAccessTokenGetter, setUnauthorizedHandler } from '@/api/client'
import { PageLoading } from '@/components/common/misc'
import { useAuthMode } from './auth-mode'
import { API_RESOURCE } from './logto-config'
import { useCurrentUser, useSignIn } from './use-auth'

/** 路由守卫：未登录跳 /login，并把 Logto token 注入 api 层；单机模式直接放行 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const authMode = useAuthMode()
  const { isAuthenticated, isLoading, getAccessToken, getIdToken } = useLogto()
  const signIn = useSignIn()
  const location = useLocation()
  const returnTo = `${location.pathname}${location.search}`

  // 401 处理器只读最新路径，避免每次路由变化都重新注册
  const returnToRef = useRef(returnTo)
  returnToRef.current = returnTo
  const reauthingRef = useRef(false)

  useEffect(() => {
    if (!isAuthenticated) return
    // 未配置 API Resource（Logto 免费版）时拿不到面向后端的 JWT，退而直传 ID Token：
    // 后端按 aud=appId 用 JWKS 验签，等效保护（见后端 auth.py 的 idtoken 模式说明）
    setAccessTokenGetter(
      API_RESOURCE ? () => getAccessToken(API_RESOURCE) : async () => (await getIdToken()) ?? undefined,
    )
    setUnauthorizedHandler(() => {
      // 并发请求同时 401 时只发起一次重新登录
      if (reauthingRef.current) return
      reauthingRef.current = true
      void signIn({ returnTo: returnToRef.current })
      // signIn（proxy 包装）失败会被静默吞掉，跳转也可能被浏览器拦截；
      // 5s 后放行重试，避免 token 过期后鉴权恢复永久卡死（所有请求静默 401）
      setTimeout(() => {
        reauthingRef.current = false
      }, 5000)
    })
    return () => {
      setAccessTokenGetter(undefined)
      setUnauthorizedHandler(undefined)
    }
  }, [isAuthenticated, getAccessToken, getIdToken, signIn])

  if (authMode === 'loading') return <div className="h-screen"><PageLoading /></div>
  if (authMode === 'local') return children

  // Logto 在取 token 等异步操作期间也会置 isLoading，已登录时不能因此卸载整个应用
  if (!isAuthenticated) {
    if (isLoading) return <div className="h-screen"><PageLoading /></div>
    return <Navigate to="/login" state={{ returnTo }} replace />
  }

  return children
}

/** 管理员路由守卫：普通用户访问 /admin 时重定向回对话页（单机模式固定管理员） */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const authMode = useAuthMode()
  const { data: user, isLoading } = useCurrentUser()

  if (authMode === 'loading' || (authMode !== 'local' && isLoading)) {
    return <div className="h-screen"><PageLoading /></div>
  }
  if (!user?.isAdmin) return <Navigate to="/chat" replace />
  return children
}
