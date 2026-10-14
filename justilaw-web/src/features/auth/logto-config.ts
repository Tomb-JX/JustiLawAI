import { UserScope, type LogtoConfig } from '@logto/react'

/**
 * 后端 API 在 Logto 中注册的 API Resource 标识（如 https://api.justilaw.ai）。
 * 配置后前端才能换取面向后端的 JWT access token；未配置时请求不携带 Authorization。
 */
export const API_RESOURCE: string | undefined = import.meta.env.VITE_LOGTO_RESOURCE || undefined

export const logtoConfig: LogtoConfig = {
  endpoint: import.meta.env.VITE_LOGTO_ENDPOINT,
  appId: import.meta.env.VITE_LOGTO_APP_ID,
  // Roles 用于前端区分管理员入口（最终权限以后端校验为准）
  scopes: [UserScope.Email, UserScope.Roles],
  resources: API_RESOURCE ? [API_RESOURCE] : [],
}

export const CALLBACK_PATH = '/callback'

/** 须与 Logto Console 中登记的 Redirect URI 完全一致 */
export const signInRedirectUri = () => `${window.location.origin}${CALLBACK_PATH}`

/** 须与 Logto Console 中登记的 Post sign-out redirect URI 完全一致 */
export const signOutRedirectUri = () => `${window.location.origin}/`
