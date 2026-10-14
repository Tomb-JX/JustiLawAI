import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // vendor 分包：只拆依赖方向单一（业务 → 库）的组，独立长缓存。
        // 注意：不要把 axios/zustand/@tanstack 等与业务高频交织的库单独成组——
        // 实测会造成模块初始化顺序问题导致白屏（2026-10-14 教训）。
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@logto') || id.includes('oidc-client')) return 'logto'
          if (
            id.includes('react-dom') ||
            id.includes('/react@') ||
            id.includes('scheduler') ||
            id.includes('react-router')
          ) {
            return 'react-vendor'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    // 后端联调时启用代理（Mock 模式下不生效）；JUSTILAW_API 可改代理目标，如并行跑多个后端时
    proxy: {
      '/api': {
        target: process.env.JUSTILAW_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
