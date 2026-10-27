import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Gavel, Info } from 'lucide-react'
import { decideDiscretion, getDiscretionMeta } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { AmountRange, DiscretionDecision, DiscretionFacts, PenaltyOption } from '@/types/api'

/** 下拉里的"未知"：Radix Select 不允许空字符串作选项值 */
const UNKNOWN = '_'

const ROUTE_LABEL: Record<DiscretionDecision['route'], string> = {
  rule_single: '省级裁量基准直接确定',
  rule_candidates: '省级基准候选内按文本模型选择',
  model_fallback: '无省级分档，文本模型统计参考',
  undetermined: '未能确定处罚种类',
}

const QUANTITY_LABEL: Record<string, string> = { fine: '罚款（元）', detention_days: '拘留（日）' }

const CONDITION_LABEL: Record<string, string> = {
  personal_stake: '个人赌资',
  onsite_stake_total: '现场赌资合计',
  commission: '获利 / 抽头',
  times: '次数',
  civil_servant: '是否国家工作人员',
  venue_public: '是否公共场所',
  venue_public_for_profit: '是否在公共场所营利',
  method_online: '是否网络赌博',
  minors_involved: '是否涉及未成年人',
  prior_within_year: '一年内是否受过处罚',
}

/** "500" → 500–500；"300-500" → 区间；"1000以上" / "1000+" → 无上界 */
function parseAmount(s: string): AmountRange | undefined | null {
  const t = s.replace(/[,，元\s]/g, '')
  if (!t) return undefined
  let m = t.match(/^(\d+(?:\.\d+)?)$/)
  if (m) return { min: +m[1], max: +m[1] }
  m = t.match(/^(\d+(?:\.\d+)?)[-~–至到](\d+(?:\.\d+)?)$/)
  if (m && +m[1] <= +m[2]) return { min: +m[1], max: +m[2] }
  m = t.match(/^(\d+(?:\.\d+)?)(?:\+|以上)$/)
  if (m) return { min: +m[1], max: null }
  return null
}

const range = (r: [number, number] | null, unit: string) =>
  r ? (r[0] === r[1] ? `${r[0]}${unit}` : `${r[0]}–${r[1]}${unit}`) : null

function optionText(o: PenaltyOption) {
  if (o.kind === '不予处罚') return '不予处罚'
  return [range(o.detention, '日拘留'), range(o.fine, '元罚款')].filter(Boolean).join(' 并处 ')
}

type Form = Record<string, string>

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground/80">{hint}</span>}
    </label>
  )
}

function Choice({
  value,
  onChange,
  options,
  unknownLabel = '未知',
}: {
  value?: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  unknownLabel?: string | null
}) {
  return (
    <Select value={value || UNKNOWN} onValueChange={onChange}>
      <SelectTrigger className="h-9 bg-background">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {unknownLabel !== null && <SelectItem value={UNKNOWN}>{unknownLabel}</SelectItem>}
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

const asOptions = (xs: string[] = []) => xs.map((x) => ({ value: x, label: x }))
const YES_NO = [
  { value: 'true', label: '是' },
  { value: 'false', label: '否' },
]

function buildFacts(form: Form): { facts?: DiscretionFacts; error?: string } {
  const pick = (k: string) => (form[k] && form[k] !== UNKNOWN ? form[k] : undefined)
  const bool = (k: string) => (pick(k) === undefined ? undefined : pick(k) === 'true')
  const int = (k: string) => (pick(k) === undefined ? undefined : Number.parseInt(pick(k)!, 10))
  if (!pick('behavior_date')) return { error: '请填写违法行为日期' }
  if (!pick('behavior_type')) return { error: '请选择行为类型' }
  const facts: DiscretionFacts = {
    behavior_date: pick('behavior_date')!,
    decision_date: pick('decision_date'),
    region: pick('region'),
    behavior_type: pick('behavior_type')!,
    age: int('age'),
    first_offense: bool('first_offense'),
    surrendered: bool('surrendered'),
    truthful_statement: bool('truthful_statement'),
    admits_and_accepts: bool('admits_and_accepts'),
    minor_circumstance: pick('minor_circumstance'),
    participant_count: int('participant_count'),
    method: pick('method'),
    gambling_form: pick('gambling_form'),
    venue_type: pick('venue_type'),
    civil_servant: bool('civil_servant'),
    minors_involved: bool('minors_involved'),
    profit_purpose: bool('profit_purpose'),
    times: int('times'),
  }
  for (const [k, label] of [
    ['personal_stake', '个人赌资'],
    ['onsite_stake_total', '现场赌资合计'],
    ['commission', '获利 / 抽头'],
  ] as const) {
    const v = parseAmount(form[k] ?? '')
    if (v === null) return { error: `${label}格式不对：填数字、"300-500" 或 "1000以上"` }
    if (v) facts[k] = v
  }
  return { facts }
}

export default function DiscretionPage() {
  const [form, setForm] = useState<Form>({ behavior_type: '参与赌博' })
  const [formError, setFormError] = useState<string>()
  const set = (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v }))
  const setInput = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => set(k)(e.target.value)

  const { data: meta, error: metaError } = useQuery({ queryKey: ['discretion-meta'], queryFn: getDiscretionMeta })
  const decideMut = useMutation({ mutationFn: decideDiscretion })

  const submit = () => {
    const { facts, error } = buildFacts(form)
    setFormError(error)
    if (facts) decideMut.mutate(facts)
  }

  const provider = form.behavior_type === '为赌博提供条件'

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <Gavel className="h-5 w-5 text-primary" />
          赌博类治安处罚裁量建议
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          填写已查明的案件要素，给出合法处罚空间、省级裁量基准对应的处罚种类与历史数额分布。不确定的项保持"未知"，不要按"否"填。
        </p>
        {metaError && (
          <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            无法连接裁量服务：{(metaError as Error).message}。此功能需要后端（justilaw-api）运行。
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[360px_1fr]">
          <section className="space-y-5 rounded-xl border bg-card p-4 shadow-sm lg:self-start">
            <div className="space-y-3">
              <h2 className="text-sm font-semibold">基本信息</h2>
              <div className="grid grid-cols-2 gap-3">
                <Field label="违法行为日期 *">
                  <Input type="date" value={form.behavior_date ?? ''} onChange={setInput('behavior_date')} />
                </Field>
                <Field label="处罚决定日期">
                  <Input type="date" value={form.decision_date ?? ''} onChange={setInput('decision_date')} />
                </Field>
              </div>
              <Field label="省份" hint="省级裁量基准目前录入河北、江苏；其他省份只给国家法定空间">
                <Choice
                  value={form.region}
                  onChange={set('region')}
                  unknownLabel="其他省份 / 未知"
                  options={(meta?.provinces ?? []).map((p) => ({ value: p.code, label: p.name }))}
                />
              </Field>
              <Field label="行为类型 *">
                <Choice
                  value={form.behavior_type}
                  onChange={set('behavior_type')}
                  unknownLabel={null}
                  options={asOptions(meta?.behavior_types)}
                />
              </Field>
            </div>

            <div className="space-y-3">
              <h2 className="text-sm font-semibold">赌资与方式</h2>
              <div className="grid grid-cols-2 gap-3">
                {provider ? (
                  <Field label="获利 / 抽头（元）">
                    <Input value={form.commission ?? ''} onChange={setInput('commission')} placeholder="如 300" />
                  </Field>
                ) : (
                  <Field label="个人赌资（元）">
                    <Input value={form.personal_stake ?? ''} onChange={setInput('personal_stake')} placeholder="如 700" />
                  </Field>
                )}
                <Field label="现场赌资合计（元）">
                  <Input value={form.onsite_stake_total ?? ''} onChange={setInput('onsite_stake_total')} placeholder="如 3000" />
                </Field>
                <Field label="参赌人数">
                  <Input type="number" min={1} value={form.participant_count ?? ''} onChange={setInput('participant_count')} />
                </Field>
                <Field label={provider ? '提供条件次数' : '赌博次数'}>
                  <Input type="number" min={1} value={form.times ?? ''} onChange={setInput('times')} />
                </Field>
              </div>
              <p className="text-[11px] text-muted-foreground/80">金额可填区间"300-500"或开口"1000以上"</p>
              <Field label="赌博方式">
                <Choice value={form.method} onChange={set('method')} options={asOptions(meta?.methods)} />
              </Field>
              <Field label="组织形式" hint="江苏基准按此区分门槛：聚众、赌场赌博适用较低门槛">
                <Choice value={form.gambling_form} onChange={set('gambling_form')} options={asOptions(meta?.gambling_forms)} />
              </Field>
              <Field label="场所">
                <Choice value={form.venue_type} onChange={set('venue_type')} options={asOptions(meta?.venue_types)} />
              </Field>
            </div>

            <div className="space-y-3">
              <h2 className="text-sm font-semibold">身份与情节</h2>
              <div className="grid grid-cols-2 gap-3">
                <Field label="年龄">
                  <Input type="number" min={0} value={form.age ?? ''} onChange={setInput('age')} />
                </Field>
                {(
                  [
                    ['civil_servant', '国家工作人员'],
                    ['minors_involved', '涉及未成年人'],
                    ['first_offense', '初次违法'],
                    ['surrendered', '主动投案'],
                    ['truthful_statement', '如实陈述'],
                    ['admits_and_accepts', '认错认罚'],
                    ...(provider ? [['profit_purpose', '以营利为目的']] : []),
                  ] as [string, string][]
                ).map(([k, label]) => (
                  <Field key={k} label={label}>
                    <Choice value={form[k]} onChange={set(k)} options={YES_NO} />
                  </Field>
                ))}
              </div>
              <Field label="情节轻微" hint="只填处罚机关认定的情形">
                <Choice
                  value={form.minor_circumstance}
                  onChange={set('minor_circumstance')}
                  unknownLabel="无 / 未知"
                  options={asOptions(meta?.minor_levels)}
                />
              </Field>
            </div>

            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <Button className="w-full" onClick={submit} disabled={decideMut.isPending}>
              {decideMut.isPending ? '计算中…' : '生成裁量建议'}
            </Button>
          </section>

          <section className="min-w-0">
            {decideMut.error && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                {(decideMut.error as Error).message}
              </div>
            )}
            {decideMut.data ? (
              <Result d={decideMut.data} />
            ) : (
              !decideMut.error && (
                <div className="flex h-48 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
                  填写左侧要素后生成建议
                </div>
              )
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </div>
  )
}

function Result({ d }: { d: DiscretionDecision }) {
  const a = d.assessment
  const st = a.stake_threshold
  const notes = [...new Set(d.notes)]
  return (
    <div className="space-y-4">
      <div className="rounded-xl border bg-card p-5 shadow-sm">
        <div className="text-xs text-muted-foreground">建议处罚种类</div>
        <div className="mt-1 text-2xl font-bold">{d.penalty_type ?? '未确定'}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <Badge variant={d.route === 'rule_single' ? 'default' : 'secondary'}>{ROUTE_LABEL[d.route]}</Badge>
          {d.candidates.length > 1 && (
            <span className="text-muted-foreground">
              基准候选：{d.candidates.join(' / ')}（补充下方"待查明"的要素可缩小范围）
            </span>
          )}
        </div>
        {Object.keys(d.quantities).length > 0 && (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {Object.entries(d.quantities).map(([k, values]) => (
              <div key={k}>
                <div className="mb-1.5 text-xs font-medium text-muted-foreground">
                  {QUANTITY_LABEL[k] ?? k} · 历史取值分布
                </div>
                {values.length === 0 ? (
                  <div className="text-xs text-muted-foreground">无落在法定幅度内的历史取值</div>
                ) : (
                  <div className="space-y-1">
                    {values.slice(0, 6).map(([v, share]) => (
                      <div key={v} className="flex items-center gap-2 text-xs">
                        <span className="w-12 shrink-0 text-right tabular-nums">{v}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded bg-muted">
                          <div className="h-full rounded bg-primary/70" style={{ width: `${share * 100}%` }} />
                        </div>
                        <span className="w-10 shrink-0 tabular-nums text-muted-foreground">
                          {Math.round(share * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="mt-4 flex items-start gap-1.5 text-[11px] text-muted-foreground">
          <Info className="mt-px h-3 w-3 shrink-0" />
          这是裁量建议，不是处罚决定。档内数额只给历史分布，不作点预测。
        </p>
      </div>

      <Card title="省级裁量基准">
        {st.bands.length ? (
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap gap-1.5">
              {st.bands.map((b, i) => (
                <Badge key={b} variant="outline">
                  {b}
                  {st.band_penalty[i - (st.bands[0] === '未达起罚标准' ? 1 : 0)] && b !== '未达起罚标准'
                    ? `：${st.band_penalty[i - (st.bands[0] === '未达起罚标准' ? 1 : 0)]}`
                    : ''}
                </Badge>
              ))}
            </div>
            <div className="text-xs text-muted-foreground">
              依据 {st.basis}；采用 {st.measures_used.join('、') || '—'}
              {st.law_alignment && <Badge variant="secondary" className="ml-2">{st.law_alignment}</Badge>}
            </div>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            {st.status}
            {st.reason ? `：${st.reason}` : ''}
          </div>
        )}
        {st.unknown_conditions.length > 0 && (
          <div className="mt-2 text-xs text-muted-foreground">
            待查明：{st.unknown_conditions.map((c) => CONDITION_LABEL[c] ?? c).join('、')}
          </div>
        )}
      </Card>

      <Card title="法定处罚空间">
        <div className="mb-2 text-xs text-muted-foreground">{a.temporal_note}</div>
        <div className="space-y-3">
          {Object.entries(a.tiers).map(([tier, t]) => (
            <div key={tier}>
              <div className="text-xs font-medium">
                {tier}
                {t.detention_executable === false && (
                  <span className="ml-2 text-amber-600 dark:text-amber-400">拘留依法不执行（{t.not_executed_reason}）</span>
                )}
              </div>
              <ul className="mt-1 space-y-0.5 text-sm">
                {t.options.map((o, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                    <span>{optionText(o)}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {o.via} · {o.basis.join('、')}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {a.directions.length > 0 && (
          <div className="mt-3 border-t pt-3 text-sm">
            {a.directions.map((x, i) => (
              <div key={i}>
                <Badge variant="secondary" className="mr-2">
                  {x.effect}
                </Badge>
                {x.trigger}
                <span className="ml-2 text-[11px] text-muted-foreground">{x.basis}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {a.referral.length > 0 && (
        <div className="flex gap-2 rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm">
          <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
          <div>
            可能涉嫌犯罪，需审查是否移送：
            {a.referral.map((r) => `${CONDITION_LABEL[r.item] ?? r.item}${r.threshold ? ` ≥ ${r.threshold}` : ''}（${r.status}）`).join('；')}
          </div>
        </div>
      )}

      {notes.length > 0 && (
        <Card title="提示">
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
