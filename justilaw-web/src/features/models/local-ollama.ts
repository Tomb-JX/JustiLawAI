/**
 * 浏览器直连用户本机 Ollama（模式 A）：推理请求从用户浏览器直接发到 http://127.0.0.1:11434，
 * 跑在用户自己的电脑上；服务端只负责组装上下文（/chat/prepare）与落库（/chat/commit）。
 *
 * 前提：Ollama 允许本站跨域（OLLAMA_ORIGINS）。Ollama 默认只放行 localhost 等本机来源，
 * 所以单机部署（127.0.0.1:8000）无需配置，公网站点需要用户运行一次 makeAllowScript 生成的脚本。
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ModelInfo, OllamaProbe } from '@/types/api'

export const LOCAL_PREFIX = 'local/'
export const DEFAULT_LOCAL_URL = 'http://127.0.0.1:11434'

/** 本机模型设置：每个用户各自浏览器里的便利设置，只存 localStorage */
interface LocalOllamaState {
  enabled: boolean
  baseUrl: string
  setEnabled: (v: boolean) => void
  setBaseUrl: (v: string) => void
}

export const useLocalOllamaStore = create<LocalOllamaState>()(
  persist(
    (set) => ({
      enabled: false,
      baseUrl: DEFAULT_LOCAL_URL,
      setEnabled: (enabled) => set({ enabled }),
      setBaseUrl: (baseUrl) => set({ baseUrl: baseUrl.trim().replace(/\/+$/, '') || DEFAULT_LOCAL_URL }),
    }),
    { name: 'justilaw-local-ollama' },
  ),
)

export const isLocalModel = (id: string | undefined) => !!id?.startsWith(LOCAL_PREFIX)

/** 本机检测结果：running = 已连通；blocked = 在运行但未放行本站跨域；offline = 未运行 */
export type LocalStatus = 'running' | 'blocked' | 'offline'

interface OllamaTag {
  name: string
  capabilities?: string[]
  details?: { family?: string }
}

async function fetchJson<T>(url: string, init?: RequestInit, timeoutMs = 3000): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: init?.signal ?? ctrl.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export async function probeLocal(baseUrl: string): Promise<OllamaProbe & { status: LocalStatus }> {
  const base = { base_url: baseUrl, version: null, models: [] as string[], error: null }
  try {
    const { version } = await fetchJson<{ version: string }>(`${baseUrl}/api/version`)
    const { models } = await fetchJson<{ models: OllamaTag[] }>(`${baseUrl}/api/tags`)
    return { ...base, reachable: true, version, models: models.map((m) => m.name), status: 'running' }
  } catch {
    // 跨域被拦时 fetch 也只报 TypeError；用 no-cors 再探一次：能拿到不透明响应说明服务在运行
    try {
      await fetch(`${baseUrl}/api/version`, { mode: 'no-cors' })
      return { ...base, reachable: false, error: 'Ollama 正在运行，但还没有允许本网站访问', status: 'blocked' }
    } catch {
      return { ...base, reachable: false, error: '没有检测到 Ollama（未安装或未启动）', status: 'offline' }
    }
  }
}

/** 本机模型列表，转换成平台 ModelInfo（ID 带 local/ 前缀，嵌入模型不参与对话） */
export async function listLocalModels(baseUrl: string): Promise<ModelInfo[]> {
  const { models } = await fetchJson<{ models: OllamaTag[] }>(`${baseUrl}/api/tags`)
  return models.map((t) => {
    const name = t.name.toLowerCase()
    const caps =
      t.capabilities ??
      ((t.details?.family ?? '').includes('bert') || name.includes('embed') || name.startsWith('bge')
        ? ['embedding']
        : ['completion'])
    return {
      id: `${LOCAL_PREFIX}${t.name}`,
      name: t.name,
      provider: 'local',
      provider_name: '本机 Ollama',
      provider_type: 'ollama',
      capabilities: caps,
      default_params: { temperature: 0.7, top_p: 0.9, max_tokens: 2048 },
    }
  })
}

export interface PullProgress {
  status: string
  completed?: number
  total?: number
}

/** 浏览器直接让本机 Ollama 下载模型（流式进度，NDJSON） */
export async function pullLocalModel(
  baseUrl: string,
  model: string,
  onProgress: (p: PullProgress) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`${baseUrl}/api/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, stream: true }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`Ollama 返回 HTTP ${res.status}`)
  for await (const j of readNdjson(res.body)) {
    if (j.error) throw new Error(String(j.error))
    onProgress(j as unknown as PullProgress)
  }
}

export interface LocalChatDelta {
  text: string
  thinking: string
  usage?: { prompt_tokens: number; completion_tokens: number }
}

/** 本机 Ollama 流式对话（/api/chat 原生协议），与服务端 gateway.stream_chat 的 ollama 分支对应 */
export async function* streamLocalChat(
  baseUrl: string,
  model: string,
  messages: { role: string; content: string }[],
  params: { temperature: number; top_p: number; max_tokens: number },
  think: boolean | undefined,
  signal: AbortSignal,
): AsyncGenerator<LocalChatDelta> {
  const body: Record<string, unknown> = {
    model,
    messages,
    stream: true,
    options: { temperature: params.temperature, top_p: params.top_p, num_predict: params.max_tokens },
  }
  // 只对支持思维链的模型传 think，不支持的模型传了会报错
  if (think !== undefined) body.think = think
  const res = await fetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '')
    throw new Error(`本机模型调用失败（HTTP ${res.status}）${detail.slice(0, 200)}`)
  }
  for await (const j of readNdjson(res.body)) {
    if (j.error) throw new Error(String(j.error))
    const msg = (j.message ?? {}) as { content?: string; thinking?: string }
    if (msg.content || msg.thinking) yield { text: msg.content ?? '', thinking: msg.thinking ?? '' }
    if (j.done) {
      yield {
        text: '',
        thinking: '',
        usage: {
          prompt_tokens: Number(j.prompt_eval_count ?? 0),
          completion_tokens: Number(j.eval_count ?? 0),
        },
      }
    }
  }
}

async function* readNdjson(stream: ReadableStream<Uint8Array>): AsyncGenerator<Record<string, unknown>> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let nl: number
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim()
        buf = buf.slice(nl + 1)
        if (!line) continue
        try {
          yield JSON.parse(line)
        } catch {
          // 非 JSON 行忽略
        }
      }
    }
    if (buf.trim()) {
      try {
        yield JSON.parse(buf)
      } catch {
        // 同上
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/* ---------- 一键放行脚本：把本站加入 OLLAMA_ORIGINS（保留用户已有的值） ---------- */

export type ScriptOs = 'windows' | 'mac' | 'linux'

export function detectOs(): ScriptOs {
  const ua = navigator.userAgent
  if (/Windows/i.test(ua)) return 'windows'
  if (/Mac OS X|Macintosh/i.test(ua)) return 'mac'
  return 'linux'
}

export function makeAllowScript(os: ScriptOs, origin: string): { filename: string; content: string } {
  if (os === 'windows') {
    // .bat 用 CRLF；PowerShell 负责合并已有值、写用户环境变量、重启 Ollama 托盘程序
    const ps = [
      `$o='${origin}';`,
      `$c=[Environment]::GetEnvironmentVariable('OLLAMA_ORIGINS','User');`,
      `$l=@($c -split ',' | Where-Object { $_ -and $_ -ne $o }) + $o;`,
      `[Environment]::SetEnvironmentVariable('OLLAMA_ORIGINS',($l -join ','),'User');`,
      // 注册表里的新值不会进入当前进程，下面拉起的 Ollama 继承的是本进程环境，要同步设置
      `$env:OLLAMA_ORIGINS=($l -join ',');`,
      // 先记下正在运行的托盘程序路径（Ollama 可能装在自定义目录），找不到再用默认安装位置
      `$exe=(Get-Process 'ollama app' -ErrorAction SilentlyContinue | Select-Object -First 1).Path;`,
      `if (-not $exe) { $exe=Join-Path $env:LOCALAPPDATA 'Programs\\Ollama\\ollama app.exe' };`,
      `Get-Process 'ollama app','ollama' -ErrorAction SilentlyContinue | Stop-Process -Force;`,
      `Start-Sleep 2;`,
      `if (Test-Path $exe) { Start-Process $exe } else { Write-Host '请手动重新打开 Ollama' }`,
    ].join(' ')
    return {
      filename: 'allow-justilaw.bat',
      content: [
        '@echo off',
        'chcp 65001 >nul',
        `echo 正在允许 ${origin} 访问本机 Ollama...`,
        `powershell -NoProfile -ExecutionPolicy Bypass -Command "${ps}"`,
        'echo 完成！Ollama 已重启，请回到网页点击“重新检测”。',
        'pause',
        '',
      ].join('\r\n'),
    }
  }
  if (os === 'mac') {
    return {
      filename: 'allow-justilaw.command',
      content: [
        '#!/bin/bash',
        `ORIGIN='${origin}'`,
        'CUR="$(launchctl getenv OLLAMA_ORIGINS)"',
        'case ",$CUR," in *",$ORIGIN,"*) NEW="$CUR" ;; *) NEW="${CUR:+$CUR,}$ORIGIN" ;; esac',
        'launchctl setenv OLLAMA_ORIGINS "$NEW"',
        'osascript -e \'quit app "Ollama"\' 2>/dev/null; sleep 2; open -a Ollama',
        'echo "完成！请回到网页点击「重新检测」。（重启电脑后需再运行一次）"',
        '',
      ].join('\n'),
    }
  }
  return {
    filename: 'allow-justilaw.sh',
    content: [
      '#!/bin/bash',
      'set -e',
      `ORIGIN='${origin}'`,
      'sudo mkdir -p /etc/systemd/system/ollama.service.d',
      'printf "[Service]\\nEnvironment=\\"OLLAMA_ORIGINS=%s\\"\\n" "$ORIGIN" | sudo tee /etc/systemd/system/ollama.service.d/justilaw.conf >/dev/null',
      'sudo systemctl daemon-reload && sudo systemctl restart ollama',
      'echo "完成！请回到网页点击「重新检测」。"',
      '',
    ].join('\n'),
  }
}

export function downloadText(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: 'application/octet-stream' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
