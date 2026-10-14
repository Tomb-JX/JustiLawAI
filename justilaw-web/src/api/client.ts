import axios from 'axios'

/** Mock 开关：VITE_USE_MOCK !== 'false' 时全部接口走内置 Mock */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type AccessTokenGetter = () => Promise<string | undefined>

/** 由鉴权层（React 内的 Logto 上下文）注入，api 层不直接依赖 React */
let accessTokenGetter: AccessTokenGetter | undefined
let unauthorizedHandler: (() => void) | undefined

export function setAccessTokenGetter(getter?: AccessTokenGetter) {
  accessTokenGetter = getter
}

export function setUnauthorizedHandler(handler?: () => void) {
  unauthorizedHandler = handler
}

/** 当前用户的鉴权请求头；SSE 等不走 axios 的请求也需手动带上 */
export async function getAuthHeaders(): Promise<Record<string, string>> {
  if (!accessTokenGetter) return {}
  try {
    // token 过期时 SDK 会向 Logto 云静默刷新，网络不通会永久挂起；
    // 3s 超时兜底：放弃带 token（请求将 401 → 触发重新登录），不能卡死所有请求
    const token = await Promise.race([
      accessTokenGetter(),
      new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 3000)),
    ])
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

export function notifyUnauthorized() {
  unauthorizedHandler?.()
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 30_000,
})

http.interceptors.request.use(async (config) => {
  const headers = await getAuthHeaders()
  for (const [key, value] of Object.entries(headers)) config.headers.set(key, value)
  return config
})

// 统一解包 { code, message, data } 响应包，业务层只拿 data
http.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) throw new ApiError(body.code, body.message ?? '请求失败')
      return body.data
    }
    return body
  },
  (err) => {
    const code = err.response?.data?.code ?? err.response?.status ?? -1
    if (code === 40100 || err.response?.status === 401) notifyUnauthorized()
    const message = err.response?.data?.message ?? '网络异常，请稍后重试'
    return Promise.reject(new ApiError(code, message))
  },
)

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function nowISO(): string {
  return new Date().toISOString()
}
