import { useCallback } from 'react'
import { useLogto, type IdTokenClaims } from '@logto/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { syncProfile } from '@/api'
import { signInRedirectUri, signOutRedirectUri } from './logto-config'

const RETURN_TO_KEY = 'justilaw-auth-return-to'
const DEFAULT_RETURN_TO = '/chat'

/**
 * 登录跳转会离开 SPA，回跳目标只能暂存在 sessionStorage。
 * 每次登录都覆盖写入（无目标则清除），因此读取时无需删除，StrictMode 重复渲染也安全。
 */
function saveReturnTo(path?: string) {
  try {
    if (path) sessionStorage.setItem(RETURN_TO_KEY, path)
    else sessionStorage.removeItem(RETURN_TO_KEY)
  } catch {
    // 隐私模式等场景不可写，回跳退化为默认页
  }
}

/** 读取回跳目标；只接受站内相对路径，防止开放重定向 */
export function readReturnTo(): string {
  let path: string | null = null
  try {
    path = sessionStorage.getItem(RETURN_TO_KEY)
  } catch {
    // 同上
  }
  if (!path || !path.startsWith('/') || path.startsWith('//')) return DEFAULT_RETURN_TO
  return path
}

export interface SignInOptions {
  /** 登录后回到的站内路径 */
  returnTo?: string
  /** 直接打开 Logto 注册页 */
  register?: boolean
}

/** 跳转 Logto 托管登录页（登录 / 注册 / 找回密码均由 Logto 提供） */
export function useSignIn() {
  const { signIn } = useLogto()
  return useCallback(
    ({ returnTo, register }: SignInOptions = {}) => {
      saveReturnTo(returnTo)
      return signIn({
        redirectUri: signInRedirectUri(),
        firstScreen: register ? 'register' : undefined,
      })
    },
    [signIn],
  )
}

/** 退出登录：清空本地缓存的服务端数据，避免下一位用户看到上一位用户的会话 */
export function useSignOut() {
  const { signOut } = useLogto()
  const queryClient = useQueryClient()
  return useCallback(async () => {
    queryClient.clear()
    await signOut(signOutRedirectUri())
  }, [queryClient, signOut])
}

export interface CurrentUser {
  id: string
  name: string
  email?: string
  avatar?: string
  roles: string[]
  isAdmin: boolean
}

function toCurrentUser(claims: IdTokenClaims): CurrentUser {
  const roles = Array.isArray(claims.roles) ? (claims.roles as string[]) : []
  return {
    id: claims.sub,
    name: claims.name || claims.username || claims.email || '未命名用户',
    email: claims.email ?? undefined,
    avatar: claims.picture ?? undefined,
    roles,
    isAdmin: roles.includes('admin'),
  }
}

/** 当前登录用户（来自 ID Token claims，本地解析）；每次会话顺带把资料同步到后端一次 */
export function useCurrentUser() {
  const { isAuthenticated, getIdTokenClaims } = useLogto()
  return useQuery({
    queryKey: ['auth', 'current-user'],
    queryFn: async () => {
      const claims = await getIdTokenClaims()
      if (!claims) return null
      const user = toCurrentUser(claims)
      // 同步失败不影响登录态，只是后台用户列表里显示默认昵称
      void syncProfile({ nickname: user.name, email: user.email, avatar: user.avatar }).catch(() => undefined)
      return user
    },
    enabled: isAuthenticated,
    staleTime: Infinity,
  })
}
