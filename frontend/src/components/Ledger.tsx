import { useMemo, useState } from 'react'
import { ACTIVITY_LABELS, fmtT, STATUS_LABELS, type LedgerEntry, type Status } from '../api'

interface Props {
  entries: LedgerEntry[]
  selected: string | null
  onSelect: (id: string) => void
  filterIds: string[] | null
  onClearFilter: () => void
}

export default function Ledger({ entries, selected, onSelect, filterIds, onClearFilter }: Props) {
  const [status, setStatus] = useState<'all' | Status>('all')
  const [scope, setScope] = useState<'all' | '1' | '2' | '3'>('all')
  const [q, setQ] = useState('')

  const rows = useMemo(() => {
    const ql = q.toLowerCase()
    return entries.filter((e) => {
      if (filterIds && !filterIds.includes(e.item.line_id)) return false
      if (status !== 'all' && e.status !== status) return false
      if (scope !== 'all' && String(e.classification.scope) !== scope) return false
      if (ql && !`${e.item.description} ${e.item.vendor} ${e.item.source_file} ${e.classification.activity_type}`.toLowerCase().includes(ql)) return false
      return true
    })
  }, [entries, status, scope, q, filterIds])

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <input id="ledger-search" type="text" placeholder="Search description, vendor, file…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
        <select id="ledger-status" value={status} onChange={(e) => setStatus(e.target.value as 'all' | Status)}>
          <option value="all">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select id="ledger-scope" value={scope} onChange={(e) => setScope(e.target.value as 'all' | '1' | '2' | '3')}>
          <option value="all">All scopes</option>
          <option value="1">Scope 1</option>
          <option value="2">Scope 2</option>
          <option value="3">Scope 3</option>
        </select>
        {filterIds && <button className="btn small" onClick={onClearFilter}>Clear finding filter ({filterIds.length})</button>}
        <span className="muted" style={{ marginLeft: 'auto' }}>{rows.length} of {entries.length} lines</span>
      </div>
      <div className="tablewrap">
        <table className="ledger">
          <thead>
            <tr>
              <th>Line</th>
              <th>Source</th>
              <th>Description</th>
              <th>Scope</th>
              <th>Activity</th>
              <th style={{ textAlign: 'right' }}>Quantity</th>
              <th>Factor</th>
              <th style={{ textAlign: 'right' }}>tCO₂e</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => {
              const s = e.classification.scope
              return (
                <tr key={e.item.line_id} className={`clickable ${selected === e.item.line_id ? 'selected' : ''}`} onClick={() => onSelect(e.item.line_id)}>
                  <td className="mono">{e.item.line_id}</td>
                  <td><div>{e.item.source_file}</div><div className="muted" style={{ fontSize: 11 }}>{e.item.source_ref}</div></td>
                  <td>{e.item.description}{e.item.vendor && <div className="muted" style={{ fontSize: 11 }}>{e.item.vendor}</div>}</td>
                  <td><span className={`scopetag ${s ? 's' + s : 'none'}`}>{s ?? '–'}</span></td>
                  <td>
                    {e.classification.activity_type ? ACTIVITY_LABELS[e.classification.activity_type] || e.classification.activity_type : <span className="muted">unlabelled</span>}
                    <div className="method">{e.classification.method === 'rule' ? `rule ${e.classification.rule_id}` : e.classification.method === 'agent' ? `Lyzr agent · ${Number(e.classification.confidence).toFixed(2)}` : 'unclassified'}</div>
                  </td>
                  <td className="num">{e.item.quantity ? `${fmtT(e.item.quantity, 2)} ${e.item.unit}` : e.item.spend && e.classification.activity_type?.startsWith('spend_') ? `${fmtT(e.item.spend, 0)} ${e.item.currency}` : '—'}</td>
                  <td className="mono" style={{ fontSize: 11.5 }}>{e.factor_match.factor?.factor_id || <span className="muted">—</span>}</td>
                  <td className="num">{e.calculation ? fmtT(e.calculation.t_co2e, 4) : '—'}</td>
                  <td><span className={`status ${e.status}`}>{STATUS_LABELS[e.status]}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="empty">No lines match.</div>}
      </div>
    </div>
  )
}
