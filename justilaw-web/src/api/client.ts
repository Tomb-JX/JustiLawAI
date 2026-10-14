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

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 30_000,
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
