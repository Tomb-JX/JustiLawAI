import { USE_MOCK, http } from '@/api/client'
import type { Assessment, AssessInput, Run, Settings, Submission } from './types'
import settingsFixture from '@/mocks/fixtures/discretion/settings.json'
import runningFixture from '@/mocks/fixtures/discretion/run-running.json'
import extractFixture from '@/mocks/fixtures/discretion/run-extract-succeeded.json'
import reviewFixture from '@/mocks/fixtures/discretion/run-review-succeeded.json'
import assessFixture from '@/mocks/fixtures/discretion/assess-jiangsu-fine.json'
import parseFixture from '@/mocks/fixtures/discretion/run-parse-succeeded.json'
import failedFixture from '@/mocks/fixtures/discretion/run-review-failed-missing-date.json'

const data = <T,>(fixture: { data: unknown }) => structuredClone(fixture.data) as T
const mockRuns = new Map<string, { kind: string; polls: number; fail: boolean }>()
const mockAssessments = new Map<string, Assessment>()
let mockSettings: Settings | undefined

export async function getSettings(): Promise<Settings> {
  return USE_MOCK ? structuredClone(mockSettings ?? data<Settings>(settingsFixture)) : await http.get('/discretion/settings')
}
export async function putSettings(models: Partial<Settings['models']>): Promise<Settings> {
  if (USE_MOCK) {
    const result = await getSettings()
    result.models = { ...result.models, ...models }
    mockSettings = result
    return result
  }
  return await http.put('/discretion/settings', { models })
}
export async function submit(kind: 'parse' | 'extract' | 'review', body: Record<string, unknown>): Promise<Submission> {
  if (!USE_MOCK) return await http.post(`/discretion/${kind}`, body)
  const run_id = `dr_mock_${Date.now()}`
  mockRuns.set(run_id, { kind, polls: 0, fail: kind === 'review' && !body.behavior_date && !!body.text })
  return { run_id, kind, status: 'running', poll: `/api/v1/discretion/runs/${run_id}`, poll_interval_ms: 2000 }
}
export async function getRun(id: string): Promise<Run> {
  if (!USE_MOCK) return await http.get(`/discretion/runs/${encodeURIComponent(id)}`)
  const item = mockRuns.get(id)
  const assessment = mockAssessments.get(id)
  if (assessment) return { run_id: id, kind: 'assess', status: 'succeeded', result: assessment as Run['result'], error: null, partial: null }
  if (!item) throw new Error('运行记录不存在')
  if (item.polls++ === 0) return { ...data<Run>(runningFixture), run_id: id, kind: item.kind }
  const fixture = item.fail ? failedFixture : item.kind === 'review' ? reviewFixture : item.kind === 'parse' ? parseFixture : extractFixture
  return { ...data<Run>(fixture), run_id: id, kind: item.kind }
}
export async function listRuns(): Promise<{ run_id: string; kind: string; status: 'running' | 'succeeded' | 'failed'; created_at: string; summary?: string | null }[]> {
  if (USE_MOCK) return []
  return await http.get('/discretion/runs', { params: { limit: 50 } })
}
export async function assess(body: AssessInput): Promise<Assessment> {
  if (!USE_MOCK) return await http.post('/discretion/assess', body)
  const result = data<Assessment>(assessFixture)
  result.run_id = `dr_mock_${Date.now()}`
  mockAssessments.set(result.run_id, result)
  return result
}
