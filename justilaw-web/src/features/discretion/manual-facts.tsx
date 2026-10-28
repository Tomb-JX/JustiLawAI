import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { AssessInput } from './types'

type Form = Record<string, string>
const fields = [
  { title: '案件基本信息', items: [
    ['behavior_date', '行为日期', 'date'], ['decision_date', '决定日期', 'date'],
    ['region', '地区代码', 'text'], ['behavior_type', '行为类型', 'behavior'],
  ] },
  { title: '赌资与行为', items: [
    ['personal_stake', '个人赌资（元）', 'number'], ['onsite_stake_total', '现场赌资（元）', 'number'],
    ['commission', '抽头获利（元）', 'number'], ['participant_count', '参赌人数', 'number'],
    ['times', '次数', 'number'], ['method', '赌博方式', 'text'],
    ['gambling_form', '组织形式', 'text'], ['venue_type', '场所', 'text'],
  ] },
  { title: '身份与情节', items: [
    ['age', '年龄', 'number'], ['civil_servant', '国家工作人员', 'boolean'],
    ['minors_involved', '涉及未成年人', 'boolean'], ['profit_purpose', '以营利为目的', 'boolean'],
    ['first_offense', '初次违法', 'boolean'], ['surrendered', '主动投案', 'boolean'],
    ['truthful_statement', '如实陈述', 'boolean'], ['admits_and_accepts', '认错认罚', 'boolean'],
  ] },
] as const
const inputClass = 'mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring'

function build(form: Form): AssessInput | string {
  if (!form.behavior_date) return '请填写行为日期'
  if (!form.behavior_type) return '请选择行为类型'
  const input: AssessInput = {}
  for (const group of fields) for (const [key, , kind] of group.items) {
    const value = form[key]
    if (value === undefined || value === '') continue
    if (kind === 'number') {
      const n = Number(value)
      if (!Number.isFinite(n) || n < 0) return `${key} 必须是非负数字`
      input[key] = ['personal_stake', 'onsite_stake_total', 'commission'].includes(key) ? { min: n, max: n } : n
    } else if (kind === 'boolean') input[key] = value === 'true'
    else input[key] = value
  }
  if (form.proposed_type) input.proposed = {
    type: form.proposed_type,
    ...(form.proposed_detention_days && { detention_days: Number(form.proposed_detention_days) }),
    ...(form.proposed_fine && { fine: Number(form.proposed_fine) }),
  }
  return input
}

export function ManualFacts({ busy, onSubmit }: { busy: boolean; onSubmit: (body: AssessInput) => void }) {
  const [form, setForm] = useState<Form>({ behavior_type: '参与赌博' })
  const [error, setError] = useState('')
  const set = (key: string, value: string) => setForm(v => ({ ...v, [key]: value }))
  const submit = () => { const body = build(form); if (typeof body === 'string') setError(body); else { setError(''); onSubmit(body) } }
  return <section className="rounded-xl border bg-card p-4 shadow-sm sm:p-5">
    <div className="flex items-baseline justify-between gap-2"><h2 className="text-sm font-semibold">直接填写要素</h2><span className="text-xs text-muted-foreground">未掌握的事实留空</span></div>
    <div className="mt-4 space-y-5">{fields.map(group => <fieldset key={group.title} className="space-y-3 border-t pt-4 first:border-0 first:pt-0"><legend className="text-xs font-semibold text-muted-foreground">{group.title}</legend><div className="grid gap-x-3 gap-y-3 sm:grid-cols-2">{group.items.map(([key, label, kind]) => <label key={key} className="block text-xs font-medium text-foreground/80">{label}{kind === 'boolean' || kind === 'behavior' ? <select className={inputClass} value={form[key] ?? ''} onChange={e => set(key, e.target.value)}><option value="">{kind === 'boolean' ? '未知' : '请选择'}</option>{kind === 'boolean' ? <><option value="true">是</option><option value="false">否</option></> : <><option value="参与赌博">参与赌博</option><option value="为赌博提供条件">为赌博提供条件</option></>}</select> : <Input className="mt-1 h-9" type={kind === 'date' ? 'date' : kind === 'number' ? 'number' : 'text'} min={kind === 'number' ? 0 : undefined} value={form[key] ?? ''} onChange={e => set(key, e.target.value)} placeholder={key === 'region' ? '如 320000' : undefined} />}</label>)}</div></fieldset>)}</div>
    <details className="mt-5 rounded-lg border bg-muted/30 p-3"><summary className="cursor-pointer text-xs font-medium">对照拟处罚（可选）</summary><div className="mt-3 grid gap-3 sm:grid-cols-3"><label className="text-xs">处罚种类<select className={inputClass} value={form.proposed_type ?? ''} onChange={e => set('proposed_type', e.target.value)}><option value="">不对照</option>{['不予处罚','罚款','拘留','拘留并处罚款'].map(x => <option key={x}>{x}</option>)}</select></label><label className="text-xs">拘留天数<Input className="mt-1 h-9" type="number" min={0} value={form.proposed_detention_days ?? ''} onChange={e => set('proposed_detention_days', e.target.value)} /></label><label className="text-xs">罚款金额<Input className="mt-1 h-9" type="number" min={0} value={form.proposed_fine ?? ''} onChange={e => set('proposed_fine', e.target.value)} /></label></div></details>
    {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
    <Button className="mt-4 w-full" disabled={busy} onClick={submit}>计算裁量结果</Button>
  </section>
}
