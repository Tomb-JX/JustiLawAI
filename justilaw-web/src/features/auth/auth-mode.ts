import { useQuery } from '@tanstack/react-query'
import { getHealth } from '@/api'

/** 服务状态（登录前即可调用）：单机模式判断、模型连接向导都依赖它 */
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: getHealth, staleTime: 30_000, retry: 1 })
}

/**
 * 鉴权模式（运行时判断，同一份前端构建既能公网部署也能单机使用）：
 * - local：后端未配置 Logto（单机一键部署），免登录，所有请求视为本地管理员
 * - logto：走 Logto 托管登录
 * 后端不可达时按 logto 处理，保持公网部署的默认行为。
 */
export function useAuthMode(): 'loading' | 'local' | 'logto' {
  const { data, isLoading } = useHealth()
  if (isLoading) return 'loading'
  return data && !data.auth_enabled ? 'local' : 'logto'
}
