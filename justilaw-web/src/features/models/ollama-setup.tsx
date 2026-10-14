/**
 * 模型连接向导：三步把 Ollama 接进来——检测 → 下载推荐模型 → 完成。
 *
 * - target="server"：服务端连接的 Ollama（单机部署时就是用户本机）。经后端检测 / 拉取，需要管理员
 * - target="browser"：浏览器直连用户电脑上的 Ollama（公网站点）。检测 / 拉取都由浏览器直接完成
 */
import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Download, ExternalLink, Loader2, MonitorSmartphone, RefreshCw, Server } from 'lucide-react'
import { toast } from 'sonner'
import { detectOllama, listProviders, updateProvider } from '@/api'
import { streamPullModel } from '@/api/sse'
import { Button, buttonVariants } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useAuthMode } from '@/features/auth/auth-mode'
import { useCurrentUser } from '@/features/auth/use-auth'
import { useSettingsStore } from '@/stores/settings'
import {
  DEFAULT_LOCAL_URL,
  LOCAL_PREFIX,
  detectOs,
  downloadText,
  makeAllowScript,
  probeLocal,
  pullLocalModel,
  useLocalOllamaStore,
  type LocalStatus,
  type PullProgress,
} from './local-ollama'

export type SetupTarget = 'server' | 'browser'

/** 向导目标：单机部署或管理员 → 配置服务端 Ollama；公网普通用户 → 浏览器直连自己电脑上的 Ollama */
export function useSetupTarget(): SetupTarget {
  const authMode = useAuthMode()
  const { data: user } = useCurrentUser()
  return authMode === 'local' || user?.isAdmin ? 'server' : 'browser'
}

interface Recommended {
  name: string
  kind: 'chat' | 'embedding'
  title: string
  size: string
  hint: string
}

/** 推荐模型清单：对话模型必需；嵌入模型只在服务端需要（知识库入库与检索在服务端完成） */
const RECOMMENDED: Recommended[] = [
  { name: 'qwen3.5:9b', kind: 'chat', title: '对话模型 Qwen3.5 9B', size: '约 6.6 GB', hint: '建议 8 GB 以上显存，或 16 GB 内存' },
  { name: 'bge-m3', kind: 'embedding', title: '嵌入模型 BGE-M3', size: '约 1.2 GB', hint: '知识库检索需要' },
]

const OLLAMA_DOWNLOAD = 'https://ollama.com/download'

const sameModel = (a: string, b: string) => a.replace(/:latest$/, '') === b.replace(/:latest$/, '')

function Steps({ step }: { step: number }) {
  const labels = ['检测 Ollama', '准备模型', '完成']
  return (
    <ol className="flex items-center gap-2 text-xs">
      {labels.map((l, i) => (
        <li key={l} className="flex items-center gap-2">
          <span
            className={cn(
              'flex h-5 w-5 items-center justify-center rounded-full border text-[10px]',
              i < step && 'border-primary bg-primary text-primary-foreground',
              i === step && 'border-primary text-primary',
              i > step && 'text-muted-foreground',
            )}
          >
            {i < step ? <Check className="h-3 w-3" /> : i + 1}
          </span>
          <span className={i === step ? 'font-medium' : 'text-muted-foreground'}>{l}</span>
          {i < labels.length - 1 && <span className="h-px w-6 bg-border" />}
        </li>
      ))}
    </ol>
  )
}

function ProgressBar({ p }: { p?: PullProgress }) {
  const pct = p?.total ? Math.min(100, Math.round(((p.completed ?? 0) / p.total) * 100)) : undefined
  return (
    <div className="space-y-1">
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full bg-primary transition-all', pct === undefined && 'w-1/3 animate-pulse')}
          style={pct !== undefined ? { width: `${pct}%` } : undefined}
        />
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span className="truncate">{p?.status ?? '准备中…'}</span>
        {pct !== undefined && <span>{pct}%</span>}
      </div>
    </div>
  )
}

export function OllamaSetup({ target, onDone }: { target: SetupTarget; onDone?: () => void }) {
  const qc = useQueryClient()
  const local = useLocalOllamaStore()
  const setModel = useSettingsStore((s) => s.setModel)

  const [step, setStep] = useState(0)
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<LocalStatus | 'unknown'>('unknown')
  const [error, setError] = useState<string | null>(null)
  const [url, setUrl] = useState(target === 'browser' ? local.baseUrl : '')
  const [installed, setInstalled] = useState<string[]>([])
  const [pulling, setPulling] = useState<string>()
  const [progress, setProgress] = useState<PullProgress>()
  const abortRef = useRef<AbortController | null>(null)

  const needed = RECOMMENDED.filter((r) => target === 'server' || r.kind === 'chat')
  const hasChat = installed.some((n) => !/embed|bge|m3e|gte/i.test(n))

  const invalidate = () => {
    for (const key of ['models', 'model-settings', 'health', 'providers', 'local-models']) {
      void qc.invalidateQueries({ queryKey: [key] })
    }
  }

  const detect = async (customUrl?: string) => {
    setChecking(true)
    setError(null)
    try {
      if (target === 'browser') {
        const base = (customUrl || url || DEFAULT_LOCAL_URL).replace(/\/+$/, '')
        const res = await probeLocal(base)
        setStatus(res.status)
        if (!res.reachable) return setError(res.error)
        local.setBaseUrl(base)
        local.setEnabled(true)
        setInstalled(res.models)
      } else {
        const res = await detectOllama(customUrl || undefined)
        setStatus(res.reachable ? 'running' : 'offline')
        if (!res.reachable) return setError(res.error)
        // 检测到的地址与当前配置不同（如 Docker 里要用 host.docker.internal）时自动切换
        const builtin = (await listProviders()).find((p) => p.id === 'ollama')
        if (builtin && (builtin.base_url !== res.base_url || !builtin.enabled)) {
          await updateProvider('ollama', { base_url: res.base_url, enabled: true })
        }
        setUrl(res.base_url)
        setInstalled(res.models)
      }
      setStep(1)
      invalidate()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  // 打开即自动检测一次：已经装好 Ollama 的用户无需任何点击就进入下一步
  useEffect(() => {
    void detect()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pull = async (name: string) => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setPulling(name)
    setProgress(undefined)
    try {
      if (target === 'browser') {
        await pullLocalModel(local.baseUrl, name, setProgress, ctrl.signal)
      } else {
        await streamPullModel(
          'ollama',
          name,
          (ev, data) => {
            if (ev === 'progress') setProgress(data as unknown as PullProgress)
            else if (ev === 'error') throw new Error(String(data.message ?? '下载失败'))
          },
          ctrl.signal,
        )
      }
      setInstalled((prev) => [...prev, name])
      toast.success(`${name} 已就绪`)
      invalidate()
    } catch (e) {
      if (!ctrl.signal.aborted) toast.error((e as Error).message)
    } finally {
      setPulling(undefined)
      abortRef.current = null
    }
  }

  const finish = () => {
    const chat = installed.find((n) => sameModel(n, RECOMMENDED[0].name)) ?? installed.find((n) => !/embed|bge/i.test(n))
    if (chat) setModel(target === 'browser' ? `${LOCAL_PREFIX}${chat}` : `ollama/${chat}`)
    invalidate()
    setStep(2)
  }

  const scriptOs = detectOs()

  return (
    <div className="space-y-4">
      <Steps step={step} />

      {step === 0 && (
        <div className="space-y-3">
          {checking ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {target === 'browser' ? '正在检测你电脑上的 Ollama…' : '正在检测 Ollama…'}
            </div>
          ) : status === 'blocked' ? (
            <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
              <p className="font-medium">检测到 Ollama 正在运行，还差一步：允许本网站访问它</p>
              <p className="text-xs text-muted-foreground">
                下载并双击运行下面的小脚本（只做一件事：把本站加入 Ollama 的 OLLAMA_ORIGINS 并重启 Ollama），然后点「重新检测」。
              </p>
              <Button
                size="sm"
                className="gap-1.5"
                onClick={() => {
                  const s = makeAllowScript(scriptOs, window.location.origin)
                  downloadText(s.filename, s.content)
                }}
              >
                <Download className="h-3.5 w-3.5" />
                下载放行脚本（{scriptOs === 'windows' ? 'Windows' : scriptOs === 'mac' ? 'macOS' : 'Linux'}）
              </Button>
              {scriptOs === 'mac' && (
                <p className="text-[11px] text-muted-foreground">首次运行如被拦截：右键脚本 → 打开。</p>
              )}
            </div>
          ) : status === 'offline' ? (
            <div className="space-y-2 rounded-lg border bg-muted/40 p-3 text-sm">
              <p className="font-medium">没有检测到 Ollama</p>
              <p className="text-xs text-muted-foreground">
                {error}。请先安装并打开 Ollama（免费，一路下一步即可），装好后点「重新检测」。
              </p>
              <a
                href={OLLAMA_DOWNLOAD}
                target="_blank"
                rel="noreferrer"
                className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'gap-1.5')}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                下载 Ollama
              </a>
              {target === 'browser' && (
                <p className="text-[11px] text-muted-foreground">
                  已经装好仍检测不到：浏览器可能弹出“访问本地网络设备”的提示，请点允许；Safari 可能不支持，请改用 Chrome / Edge。
                </p>
              )}
            </div>
          ) : (
            error && <p className="text-sm text-destructive">{error}</p>
          )}

          <div className="flex gap-2">
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={target === 'browser' ? DEFAULT_LOCAL_URL : '自动检测（也可填写 Ollama 地址）'}
              className="h-8 text-xs"
            />
            <Button size="sm" className="h-8 shrink-0 gap-1" disabled={checking} onClick={() => void detect(url)}>
              <RefreshCw className={cn('h-3.5 w-3.5', checking && 'animate-spin')} />
              重新检测
            </Button>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            已连接 Ollama{url ? `（${url}）` : ''}。下载推荐模型，或直接使用已有模型。模型只需下载一次。
          </p>
          {needed.map((r) => {
            const ok = installed.some((n) => sameModel(n, r.name))
            return (
              <div key={r.name} className="space-y-2 rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{r.title}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {r.name} · {r.size} · {r.hint}
                    </div>
                  </div>
                  {ok ? (
                    <span className="flex shrink-0 items-center gap-1 text-xs text-emerald-600">
                      <Check className="h-3.5 w-3.5" />
                      已就绪
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 shrink-0 gap-1 text-xs"
                      disabled={!!pulling}
                      onClick={() => void pull(r.name)}
                    >
                      <Download className="h-3 w-3" />
                      下载
                    </Button>
                  )}
                </div>
                {pulling === r.name && <ProgressBar p={progress} />}
              </div>
            )
          })}
          {installed.length > 0 && (
            <p className="text-[11px] text-muted-foreground">已安装：{installed.join('、')}</p>
          )}
          <div className="flex justify-end gap-2">
            {pulling && (
              <Button size="sm" variant="ghost" onClick={() => abortRef.current?.abort()}>
                暂停下载
              </Button>
            )}
            <Button size="sm" disabled={!hasChat || !!pulling} onClick={finish}>
              {hasChat ? '完成' : '至少需要一个对话模型'}
            </Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3 text-sm">
          <p className="flex items-center gap-2 font-medium text-emerald-600">
            <Check className="h-4 w-4" />
            模型已连接，可以开始对话了
          </p>
          <p className="text-xs text-muted-foreground">
            {target === 'browser'
              ? '对话将在你自己的电脑上推理，模型下拉中的「本机」分组即为本机模型。知识库检索仍由服务器完成。'
              : '之后新下载的模型会自动出现在模型列表中。'}
          </p>
          <div className="flex justify-end">
            <Button size="sm" onClick={onDone}>
              开始对话
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 弹窗形式的向导；target 一般取 useSetupTarget() */
export function OllamaSetupDialog({
  open,
  onOpenChange,
  target,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  target: SetupTarget
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {target === 'browser' ? <MonitorSmartphone className="h-4 w-4" /> : <Server className="h-4 w-4" />}
            {target === 'browser' ? '使用我电脑上的 Ollama' : '连接 Ollama 模型'}
          </DialogTitle>
          <DialogDescription>
            {target === 'browser'
              ? '模型在你自己的电脑上运行，对话内容不经过第三方模型服务。'
              : '把本机或服务器上的 Ollama 接入平台，全程三步。'}
          </DialogDescription>
        </DialogHeader>
        {open && <OllamaSetup target={target} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}
