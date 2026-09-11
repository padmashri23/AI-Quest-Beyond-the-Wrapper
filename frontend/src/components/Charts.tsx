import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ACTIVITY_LABELS, fmtT, SCOPE3_NAMES, type LedgerEntry, type ScopeTotals } from '../api'

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim()

function scopeColor(s: number | null) {
  if (s === 1) return css('--scope1')
  if (s === 2) return css('--scope2')
  if (s === 3) return css('--scope3')
  return css('--muted')
}

function Tip({ active, payload, label, unit = 'tCO₂e' }: { active?: boolean; payload?: { value: number; payload: Record<string, unknown> }[]; label?: string; unit?: string }) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="tip">
      <b>{(p.payload.full as string) || label}</b>
      <span className="num">{fmtT(p.value, 3)} {unit}</span>
      {p.payload.lines !== undefined && <div className="muted">{String(p.payload.lines)} lines</div>}
    </div>
  )
}

export function ScopeChart({ t }: { t: ScopeTotals }) {
  const data = [
    { name: 'Scope 1', full: 'Scope 1 · direct', v: Number(t.scope1), scope: 1 },
    { name: 'Scope 2', full: 'Scope 2 · location-based', v: Number(t.scope2_location), scope: 2 },
    { name: 'Scope 3', full: 'Scope 3 · value chain', v: Number(t.scope3), scope: 3 },
  ]
  return (
    <div className="card">
      <h3>Emissions by scope</h3>
      <div style={{ height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="35%">
            <CartesianGrid vertical={false} stroke={css('--grid')} />
            <XAxis dataKey="name" tick={{ fill: css('--muted'), fontSize: 12 }} axisLine={{ stroke: css('--rule') }} tickLine={false} />
            <YAxis tick={{ fill: css('--muted'), fontSize: 11 }} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => fmtT(v, 0)} />
            <Tooltip content={<Tip />} cursor={{ fill: css('--surface-2') }} />
            <Bar dataKey="v" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {data.map((d) => <Cell key={d.name} fill={scopeColor(d.scope)} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="legend">
        <span style={{ '--c': css('--scope1') } as React.CSSProperties}>Scope 1 {fmtT(t.scope1)}</span>
        <span style={{ '--c': css('--scope2') } as React.CSSProperties}>Scope 2 {fmtT(t.scope2_location)}</span>
        <span style={{ '--c': css('--scope3') } as React.CSSProperties}>Scope 3 {fmtT(t.scope3)}</span>
      </div>
    </div>
  )
}

export function ActivityChart({ t, entries }: { t: ScopeTotals; entries: LedgerEntry[] }) {
  const scopeOf: Record<string, number | null> = {}
  const linesOf: Record<string, number> = {}
  entries.forEach((e) => {
    const a = e.classification.activity_type
    if (a && e.status === 'calculated') {
      scopeOf[a] = e.classification.scope
      linesOf[a] = (linesOf[a] || 0) + 1
    }
  })
  const data = Object.entries(t.by_activity)
    .map(([k, v]) => ({ name: ACTIVITY_LABELS[k] || k, full: ACTIVITY_LABELS[k] || k, v: Number(v), scope: scopeOf[k] ?? null, lines: linesOf[k] || 0 }))
    .sort((a, b) => b.v - a.v)
    .slice(0, 12)
  const h = Math.max(160, data.length * 26 + 30)
  return (
    <div className="card">
      <h3>Top activities</h3>
      <div style={{ height: h }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, left: 8, bottom: 0 }} barCategoryGap="30%">
            <CartesianGrid horizontal={false} stroke={css('--grid')} />
            <XAxis type="number" tick={{ fill: css('--muted'), fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => fmtT(v, 0)} />
            <YAxis type="category" dataKey="name" width={150} tick={{ fill: css('--ink-2'), fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip />} cursor={{ fill: css('--surface-2') }} />
            <Bar dataKey="v" radius={[0, 4, 4, 0]} isAnimationActive={false} label={{ position: 'right', fill: css('--ink-2'), fontSize: 11, formatter: (v: unknown) => fmtT(v as number, 1) }}>
              {data.map((d) => <Cell key={d.name} fill={scopeColor(d.scope)} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="cap">Bar colour is the scope of the activity. Spend-based estimates carry lower data quality and are flagged in findings.</div>
    </div>
  )
}

export function Scope3Chart({ t }: { t: ScopeTotals }) {
  const data = Object.entries(t.scope3_by_category)
    .map(([k, v]) => ({ name: `Cat. ${k}`, full: `Category ${k} · ${SCOPE3_NAMES[k] || 'Other'}`, v: Number(v) }))
    .sort((a, b) => Number(a.name.slice(5)) - Number(b.name.slice(5)))
  if (!data.length) return null
  return (
    <div className="card">
      <h3>Scope 3 by GHG Protocol category</h3>
      <div style={{ height: 200 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="35%">
            <CartesianGrid vertical={false} stroke={css('--grid')} />
            <XAxis dataKey="name" tick={{ fill: css('--muted'), fontSize: 12 }} axisLine={{ stroke: css('--rule') }} tickLine={false} />
            <YAxis tick={{ fill: css('--muted'), fontSize: 11 }} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => fmtT(v, 0)} />
            <Tooltip content={<Tip />} cursor={{ fill: css('--surface-2') }} />
            <Bar dataKey="v" fill={css('--scope3')} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="cap">{data.map((d) => d.full.replace('Category ', 'Cat. ')).join(' · ')}</div>
    </div>
  )
}
