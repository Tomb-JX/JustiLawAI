export type HistoryItem = { id: string; kind: 'extract' | 'review' | 'assess'; mode: 'calculator' | 'public' | 'review'; createdAt: string; status: 'running' | 'succeeded' | 'failed' }
const KEY = 'justilaw.discretion.runs.v1'

export function readHistory(): HistoryItem[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(value) ? value.filter((x): x is HistoryItem => !!x && typeof x.id === 'string' && typeof x.kind === 'string').slice(0, 50) : []
  } catch { return [] }
}

export function saveHistory(item: HistoryItem): HistoryItem[] {
  const next = [item, ...readHistory().filter(x => x.id !== item.id)].slice(0, 50)
  localStorage.setItem(KEY, JSON.stringify(next))
  return next
}

export function updateHistory(id: string, status: HistoryItem['status']): HistoryItem[] {
  const next = readHistory().map(x => x.id === id ? { ...x, status } : x)
  localStorage.setItem(KEY, JSON.stringify(next))
  return next
}
