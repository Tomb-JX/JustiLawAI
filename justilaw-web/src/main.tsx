import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { LogtoProvider } from '@logto/react'
import { Toaster, toast } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { router } from '@/router'
import { logtoConfig } from '@/features/auth/logto-config'
import { applyTheme, getInitialTheme } from '@/hooks/useTheme'
import '@/styles/globals.css'

applyTheme(getInitialTheme())

// 部署更新后，长存活页面的内存模块图会去加载新 hash 的懒加载 chunk（404/错配导致整树崩溃）。
// 监听 Vite 预加载失败事件自动整页刷新拿一致版本；sessionStorage 标记防止刷新循环。
window.addEventListener('vite:preloadError', () => {
  const KEY = 'justilaw-reloaded-on-preload-error'
  try {
    if (!sessionStorage.getItem(KEY)) {
      sessionStorage.setItem(KEY, '1')
      location.reload()
    } else {
      sessionStorage.removeItem(KEY)
    }
  } catch {
    // 隐私模式下 sessionStorage 不可用时放弃自愈，等待用户手动刷新
  }
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
    // 全局兜底：所有写操作失败必有提示（未单独写 onError 的 mutation 不再静默）
    mutations: {
      onError: (e) => toast.error((e as Error).message || '操作失败'),
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LogtoProvider config={logtoConfig}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
          <Toaster richColors position="top-center" />
        </TooltipProvider>
      </QueryClientProvider>
    </LogtoProvider>
  </React.StrictMode>,
)
