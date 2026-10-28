import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, FileSearch, Gavel, Users } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { assess, getRun, getSettings, listRuns, submit } from './service'
import { ManualFacts } from './manual-facts'
import { readHistory, saveHistory, updateHistory, type HistoryItem } from './history'
import type { Assessment, AssessInput, Element, Extraction, ParseResult, Run, Submission } from './types'

type Mode = 'calculator' | 'public' | 'review'
const modes: { key: Mode; title: string; icon: typeof Gavel; desc: string }[] = [
  { key: 'calculator', title: '执法裁量', icon: Gavel, desc: '核实要素，计算成文结论并对照拟处罚' },
  { key: 'public', title: '结果预期', icon: Users, desc: '根据已知事实查看可能范围与待确认条件' },
  { key: 'review', title: '决定书审查', icon: FileSearch, desc: '对已作出的处罚逐层检查偏离' },
]
const fieldLabels: Record<string, string> = { behavior_date: '行为日期', decision_date: '决定日期', region: '地区代码', behavior_type: '行为类型', personal_stake: '个人赌资', onsite_stake_total: '现场赌资', commission: '抽头获利', participant_count: '参赌人数', method: '赌博方式', gambling_form: '组织形式', venue_type: '场所', civil_servant: '国家工作人员', minors_involved: '涉及未成年人', profit_purpose: '营利目的', times: '次数' }
const levelLabels: Record<string, string> = { legal_space: '法定空间', written_band: '省级基准', amount_reference: '数额参照', practice: '实务参照' }
const format = (v: unknown) => typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v ?? '未知')
const detailLabels: Record<string, string> = { type: '种类', status: '状态', route: '计算路径', law_id: '适用法律', temporal_note: '时间效力', result: '结论', value: '取值', measure: '判断指标', thresholds: '档位门槛', computation: '计算过程', band_text: '档位条款', reason: '原因', note: '说明', unknown_conditions: '待核实条件', candidates: '候选结论', source: '数据来源', scope: '适用范围', n_events: '样本事件数', ref: '出处', text: '原文', verified: '已核验' }

function DetailValue({ value }: { value: unknown }) {
  if (value == null) return <span className="text-muted-foreground">未提供</span>
  if (typeof value === 'boolean') return <span>{value ? '是' : '否'}</span>
  if (typeof value !== 'object') return <span className="break-words">{String(value)}</span>
  if (Array.isArray(value)) return <div className="space-y-1">{value.length ? value.map((item, i) => <div key={i} className="rounded-md bg-muted/40 px-2 py-1.5"><DetailValue value={item} /></div>) : <span className="text-muted-foreground">无</span>}</div>
  return <dl className="space-y-1.5">{Object.entries(value).map(([key, item]) => <div key={key} className="grid gap-1 border-b border-border/50 py-1 last:border-0 sm:grid-cols-[7rem_minmax(0,1fr)]"><dt className="text-muted-foreground">{detailLabels[key] ?? key}</dt><dd><DetailValue value={item} /></dd></div>)}</dl>
}

function EvidenceView({ text, element }: { text: string; element: Element }) {
  const evidence = element.evidence?.[0]
  if (!evidence) return <span className="text-xs text-muted-foreground">无原文证据</span>
  const [start, end] = evidence.span ?? []
  const valid = typeof start === 'number' && typeof end === 'number' && start >= 0 && end <= text.length && text.slice(start, end) === evidence.quote
  return <div className="space-y-1 text-xs">
    <div className="text-muted-foreground">第 {evidence.sentence ?? '—'} 句 · {valid ? '已定位到原文' : '原文位置待核实'}</div>
    <div className="rounded-md bg-muted p-2 leading-relaxed">{valid ? <>{text.slice(Math.max(0, start! - 25), start)}<mark className="bg-amber-200 dark:bg-amber-800">{text.slice(start, end)}</mark>{text.slice(end, Math.min(text.length, end! + 25))}</> : evidence.quote}</div>
  </div>
}

function Elements({ extraction, text, onConfirm }: { extraction: Extraction; text: string; onConfirm: (input: AssessInput) => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [meta, setMeta] = useState({ behavior_date: extraction.assess_input.behavior_date ?? '', region: extraction.assess_input.region ?? '' })
  const rows = Object.entries(extraction.elements).filter(([, e]) => e.status !== '未提及')
  const confirm = () => {
    const input: AssessInput = { ...extraction.assess_input, ...meta, provenance: { ...extraction.assess_input.provenance } }
    for (const [path, raw] of Object.entries(values)) {
      const e = extraction.elements[path]
      const field = e?.fact_field
      if (!field || raw === '') continue
      const original = extraction.assess_input[field]
      input[field] = typeof original === 'number' ? Number(raw) : typeof original === 'boolean' ? raw === 'true' : original && typeof original === 'object' && 'min' in original ? { min: Number(raw), max: Number(raw) } : raw
      input.provenance![field] = { status: '明确', origin: 'edited', evidence: e.evidence ?? [] }
    }
    if (!input.behavior_date || !input.behavior_type) return toast.error('请补齐行为日期与行为类型')
    onConfirm(input)
  }
  return <section className="space-y-3 rounded-xl border bg-card p-4">
    <h2 className="font-semibold">核实提取要素</h2>
    <p className="text-xs text-muted-foreground">保留未知项；修改会记为人工编辑。被剔除的字段不会自动进入计算。</p>
    {extraction.dropped?.map(d => <div key={d.path} className="rounded border border-amber-300 p-2 text-xs text-amber-700">待核实：{d.path} · {d.reason}</div>)}
    <div className="grid gap-2 sm:grid-cols-2">
      <label className="text-xs">行为日期<Input type="date" value={meta.behavior_date} onChange={e => setMeta(v => ({ ...v, behavior_date: e.target.value }))} /></label>
      <label className="text-xs">地区代码<Input value={meta.region} onChange={e => setMeta(v => ({ ...v, region: e.target.value }))} placeholder="如 320000" /></label>
    </div>
    <div className="max-h-96 space-y-2 overflow-y-auto">
      {rows.map(([path, e]) => <details key={path} className="rounded-lg border p-2 text-sm"><summary className="cursor-pointer">{fieldLabels[e.fact_field ?? ''] ?? path} <Badge variant="outline" className="ml-2">{e.status}</Badge></summary><div className="mt-2 space-y-2"><Input value={values[path] ?? (e.value && typeof e.value === 'object' && 'min' in e.value ? String(e.value.min) : format(e.value))} onChange={ev => setValues(v => ({ ...v, [path]: ev.target.value }))} disabled={!e.fact_field || e.status === '待核实'} /><EvidenceView text={text} element={e} /></div></details>)}
    </div>
    <Button onClick={confirm}>确认要素并计算</Button>
  </section>
}

function Result({ result, mode }: { result: Assessment; mode: Mode }) {
  const { written, practice, deviation, trace } = result
  const band = Array.isArray(written.band) ? written.band.join('、') : format(written.band)
  return <div className="space-y-4">
    <div className="grid gap-3 md:grid-cols-2">
      <section className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">成文结论 · 规范计算</div><div className="mt-2 text-xl font-bold">{written.type ?? '尚不能确定'}</div><p className="mt-2 text-sm text-muted-foreground">{written.candidates?.length > 1 ? `候选：${written.candidates.join('、')}` : `省级档位：${band || '待确认'}`}</p></section>
      <section className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">实务参照 · 历史统计</div>{practice.status === 'reference' ? <><div className="mt-2 text-xl font-bold">{practice.predicted ?? '—'}</div>{Object.entries(practice.distribution ?? {}).map(([k, v]) => <div key={k} className="mt-1 flex items-center gap-2 text-xs"><span className="w-24">{k}</span><div className="h-2 flex-1 rounded bg-muted"><div className="h-2 rounded bg-primary/70" style={{ width: `${v * 100}%` }} /></div><span>{Math.round(v * 100)}%</span></div>)}</> : <p className="mt-2 text-sm text-muted-foreground">{practice.status === 'out_of_scope' ? '超出实务模型适用范围' : '实务参照暂不可用'}{practice.note ? `：${practice.note}` : ''}</p>}</section>
    </div>
    {!!Object.keys(result.amounts ?? {}).length && <section className="rounded-xl border bg-card p-4"><h3 className="text-sm font-semibold">档内数额参照</h3><p className="mt-1 text-xs text-muted-foreground">历史决定中的取值分布，不表示单案确定金额。</p><div className="mt-3 grid gap-4 sm:grid-cols-2">{Object.entries(result.amounts).map(([key, values]) => <div key={key}><div className="mb-2 text-xs font-medium">{key === 'fine' ? '罚款金额（元）' : '拘留天数（日）'}</div>{values.slice(0, 6).map(([value, share]) => <div key={value} className="mb-1 flex items-center gap-2 text-xs"><span className="w-12 text-right tabular-nums">{value}</span><div className="h-2 flex-1 rounded bg-muted"><div className="h-2 rounded bg-primary/70" style={{ width: `${Math.min(100, share * 100)}%` }} /></div><span className="w-9 text-right tabular-nums text-muted-foreground">{Math.round(share * 100)}%</span></div>)}</div>)}</div></section>}
    {deviation?.levels?.length ? <section className="rounded-xl border bg-card p-4"><h3 className="font-semibold">{mode === 'review' ? '实际处罚偏离检查' : '拟处罚偏离检查'}</h3><div className="mt-2 space-y-2">{deviation.levels.map((d, i) => <div key={i} className="flex gap-2 text-sm"><Badge variant={d.ok === false ? 'destructive' : 'outline'}>{levelLabels[d.level] ?? d.level}</Badge><span>{d.ok === false ? '需复核' : d.ok === true ? '范围内' : '仅供参照'} {d.detail}</span></div>)}</div></section> : null}
    {!!result.missing?.length && <section className="rounded-xl border bg-card p-4"><h3 className="font-semibold">{mode === 'public' ? '哪些事实会影响结果' : '待补查要素'}</h3><ul className="mt-2 space-y-2 text-sm">{result.missing.map((m, i) => <li key={i}><b>{m.label ?? fieldLabels[m.field] ?? m.field}</b>：{m.why}{m.effect ? `；${m.effect}` : ''}</li>)}</ul></section>}
    {!!result.needs_review?.length && <div className="rounded-xl border border-amber-300 p-3 text-sm"><AlertTriangle className="mr-2 inline h-4 w-4" />{result.needs_review.join('；')}</div>}
    <section className="rounded-xl border bg-card p-4"><h3 className="text-sm font-semibold">依据与推理记录</h3><div className="mt-3 space-y-2">{trace.steps?.map((s, i) => <details key={`${s.id}-${i}`} className="rounded-lg border bg-background p-3 text-sm"><summary className="cursor-pointer font-medium">{i + 1}. {s.title}</summary><div className="mt-3 space-y-3 border-t pt-3 text-xs leading-relaxed">{(s.reasoning || s.computation) && <p>{s.reasoning ?? s.computation}</p>}{s.result !== undefined && <DetailValue value={s.result} />}{Boolean(s.basis) && <div className="rounded-md border-l-2 border-primary bg-muted/40 p-2"><div className="mb-1 font-medium">依据原文</div><DetailValue value={s.basis} /></div>}</div></details>)}</div><div className="mt-3 text-xs text-muted-foreground">运行编号：{result.run_id}</div><Button variant="outline" size="sm" className="mt-2" onClick={() => { const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `${result.run_id}.json`; a.click(); URL.revokeObjectURL(url) }}>导出完整记录</Button></section>
    <p className="text-xs text-muted-foreground">仅供辅助参考，结论须由人员审核确认。</p>
  </div>
}

export default function WorkbenchPage() {
  const [mode, setMode] = useState<Mode>('calculator')
  const [text, setText] = useState('')
  const [date, setDate] = useState('')
  const [region, setRegion] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>(readHistory)
  const [runId, setRunId] = useState(() => readHistory()[0]?.id ?? '')
  const [startedAt, setStartedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const [run, setRun] = useState<Run | null>(null)
  const [result, setResult] = useState<Assessment | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { data: settings } = useQuery({ queryKey: ['discretion-settings'], queryFn: getSettings })
  const { data: serverRuns } = useQuery({ queryKey: ['discretion-runs'], queryFn: listRuns, staleTime: 15_000 })
  useEffect(() => { if (!serverRuns) return; const local = readHistory(); const merged: HistoryItem[] = serverRuns.map(row => ({ id: row.run_id, kind: row.kind as HistoryItem['kind'], mode: local.find(x => x.id === row.run_id)?.mode ?? (row.kind === 'review' ? 'review' : 'calculator'), createdAt: row.created_at, status: row.status })); setHistory(merged) }, [serverRuns])
  useEffect(() => { if (!runId || run?.status === 'failed' || run?.status === 'succeeded') return; let active = true; const tick = async () => { try { const next = await getRun(runId); if (active) { setRun(next); if (next.status !== 'running') setHistory(updateHistory(runId, next.status)); if (next.status === 'succeeded' && next.result && (next.kind === 'review' || next.kind === 'assess')) setResult(next.result as Assessment) } } catch (e) { if (active) setError((e as Error).message) } }; void tick(); const timer = setInterval(() => void tick(), 2000); return () => { active = false; clearInterval(timer) } }, [runId, run?.status])
  useEffect(() => { if (run?.status !== 'running') return; const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000); return () => clearInterval(timer) }, [run?.status, startedAt])
  const start = async (kind: 'extract' | 'review', body: Record<string, unknown>) => { setBusy(true); setError(''); setResult(null); setRun(null); try { const s: Submission = await submit(kind, body); setHistory(saveHistory({ id: s.run_id, kind, mode, createdAt: new Date().toISOString(), status: 'running' })); setStartedAt(Date.now()); setElapsed(0); setRun({ run_id: s.run_id, kind, status: 'running', result: null, error: null, partial: null }); setRunId(s.run_id) } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const compute = async (input: AssessInput) => { setBusy(true); setError(''); try { const value = await assess(input); setResult(value); setRunId(value.run_id); setHistory(saveHistory({ id: value.run_id, kind: 'assess', mode, createdAt: new Date().toISOString(), status: 'succeeded' })) } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const openRun = (item: HistoryItem) => { setMode(item.mode); setResult(null); setError(''); setRun(null); setRunId(item.id); void getRun(item.id).then(next => { setRun(next); if (next.status === 'succeeded' && next.result && (next.kind === 'assess' || next.kind === 'review')) setResult(next.result as Assessment); if (next.status !== 'running') setHistory(updateHistory(item.id, next.status)) }).catch(e => setError((e as Error).message)) }
  const extraction = run?.status === 'succeeded' && run.kind === 'extract' ? run.result as Extraction : run?.partial?.extraction
  return <div className="h-full overflow-y-auto"><div className="mx-auto max-w-7xl space-y-5 px-4 py-6 sm:px-6">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-xl font-bold">赌博案件裁量工作台</h1><p className="mt-1 text-sm text-muted-foreground">输入事实、核实要素，再查看规范结论与审计依据</p></div><div className="flex w-full max-w-sm gap-2"><Input aria-label="运行编号" placeholder="输入运行编号查询" value={runId} onChange={e => setRunId(e.target.value)} /><Button variant="outline" onClick={() => openRun({ id: runId, kind: 'review', mode, createdAt: new Date().toISOString(), status: 'running' })}>查询</Button></div></div>
    {!!history.length && <section className="rounded-xl border bg-card p-3"><div className="mb-2 text-xs font-semibold text-muted-foreground">最近运行 · 保存在此浏览器，结果从服务端读取</div><div className="flex gap-2 overflow-x-auto pb-1">{history.map(item => <button key={item.id} onClick={() => openRun(item)} className={`min-w-44 rounded-lg border px-3 py-2 text-left text-xs transition-colors hover:border-primary ${runId === item.id ? 'border-primary bg-primary/5' : 'bg-background'}`}><span className="block font-medium">{item.mode === 'review' ? '决定书审查' : item.kind === 'extract' ? '要素抽取' : '裁量计算'}</span><span className="mt-1 block text-muted-foreground">{item.id} · {item.status === 'running' ? '执行中' : item.status === 'failed' ? '失败' : '已完成'}</span></button>)}</div></section>}
    <div className="grid gap-2 sm:grid-cols-3">{modes.map(m => <button key={m.key} onClick={() => { setMode(m.key); setResult(null); setRun(null); setRunId('') }} className={`rounded-xl border p-3 text-left ${mode === m.key ? 'border-primary bg-primary/5' : 'bg-card'}`}><m.icon className="mb-1 h-4 w-4 text-primary" /><b className="text-sm">{m.title}</b><p className="text-xs text-muted-foreground">{m.desc}</p></button>)}</div>
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-muted/30 px-4 py-3 text-xs"><span className="text-muted-foreground">先查看真实结果渲染：使用虚构的江苏麻将案例，由当前后端计算并生成运行记录。</span><Button size="sm" variant="outline" disabled={busy} onClick={() => { setMode('calculator'); void compute({ behavior_date: '2023-07-06', region: '320000', behavior_type: '参与赌博', personal_stake: { min: 600, max: 600 }, method: '麻将', gambling_form: '其他' }) }}>载入示例结果</Button></div>
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(350px,440px)_minmax(0,1fr)]"><div className="space-y-4">
      <section className="space-y-3 rounded-xl border bg-card p-4"><h2 className="font-semibold">{mode === 'review' ? '决定书原文' : mode === 'public' ? '描述已知情况' : '案情或笔录'}</h2><Textarea className="min-h-36" value={text} onChange={e => setText(e.target.value)} placeholder="粘贴原文；计算器也可直接在下方填写要素" /><div className="grid gap-2 sm:grid-cols-2"><label className="text-xs">行为日期<Input type="date" value={date} onChange={e => setDate(e.target.value)} /></label><label className="text-xs">地区代码<Input value={region} onChange={e => setRegion(e.target.value)} placeholder="如 320000" /></label></div>{!settings?.chain.available && <p className="text-xs text-amber-700">抽取链路不可用：{settings?.chain.reason ?? '请联系管理员检查模型槽位'}</p>}<Button disabled={!text.trim() || busy || !settings?.chain.available} onClick={() => void start(mode === 'review' ? 'review' : 'extract', { text, ...(mode !== 'review' && { doc_kind: mode === 'public' ? '叙述' : '笔录' }), ...(region && { region }), ...(date && { behavior_date: date }) })}>{busy ? '提交中…' : mode === 'review' ? '审查决定书' : '提取要素'}</Button></section>
      {mode === 'calculator' && <details className="group rounded-xl border bg-card shadow-sm"><summary className="cursor-pointer px-4 py-3 text-sm font-medium">或直接填写要素 <span className="ml-2 text-xs font-normal text-muted-foreground">无需上传材料</span></summary><div className="border-t"><ManualFacts busy={busy} onSubmit={input => void compute(input)} /></div></details>}
      {extraction && <Elements extraction={extraction} text={text} onConfirm={input => { if (mode === 'review') { const outcome = run?.partial?.parse?.outcome ?? (run?.result as Assessment | null)?.parse?.outcome; if (!outcome?.type) return toast.error('未识别实际处罚，请重新提交决定书'); void start('review', { elements: input, actual: { type: outcome.type, detention_days: outcome.detention_days, fine: outcome.fine } }) } else void compute(input) }} />}
    </div><div className="min-h-72 space-y-4 lg:sticky lg:top-6">{error && <div className="rounded-lg border border-destructive p-3 text-sm text-destructive">{error}</div>}{run?.status === 'running' && <div className="rounded-xl border bg-card p-5 text-sm"><div className="flex items-center gap-2 font-semibold"><span className="h-2 w-2 animate-pulse rounded-full bg-primary" />正在处理{run.kind === 'review' ? '决定书' : run.kind === 'extract' ? '案情要素' : '裁量结果'}</div><p className="mt-2 text-xs text-muted-foreground">已等待 {elapsed} 秒 · 任务编号 {run.run_id}</p><p className="mt-2 text-xs text-muted-foreground">当前阶段：{{ queued: '排队准备', segment: '模型解析与分段', extract: '模型抽取要素', assess: '规范裁量计算', completed: '已完成', failed: '失败' }[run.phase ?? 'queued']}。阶段由服务端实时返回；模型单次调用内部暂无 token 级进度。刷新页面后可从最近运行恢复。</p></div>}{run?.status === 'failed' && <div className="rounded-xl border border-amber-300 p-4 text-sm"><b>任务未完成</b><p>{run.error?.message}</p>{run.partial && <p className="mt-1 text-xs">已完成的解析、抽取或模型回执已保留。可补齐信息后重新提交。</p>}</div>}{result ? <Result result={result} mode={mode} /> : !run && <div className="rounded-xl border border-dashed p-12 text-center text-sm text-muted-foreground">提交材料或填写要素后，在此查看结论与依据</div>}</div></div>
  </div></div>
}
