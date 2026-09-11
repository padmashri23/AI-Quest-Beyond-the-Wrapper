import { useEffect } from 'react'
import { ACTIVITY_LABELS, fmtT, SCOPE3_NAMES, STATUS_LABELS, type LedgerEntry } from '../api'

export default function LineageDrawer({ entry, onClose }: { entry: LedgerEntry; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const { item, classification: c, factor_match: fm, calculation: calc } = entry
  const f = fm.factor

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label="Lineage">
        <header>
          <div>
            <div className="eyebrow">Audit lineage</div>
            <h2 className="mono" style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 15 }}>{item.line_id}</h2>
            <span className={`status ${entry.status}`}>{STATUS_LABELS[entry.status]}</span>
            {entry.status === 'duplicate' && <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>duplicate of {entry.duplicate_of}</span>}
          </div>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <div className="step">
          <div className="k">1 · Source document</div>
          <div className="t">{item.source_file} · {item.source_ref}</div>
          <div className="kv">
            <span className="k">Date</span><span className="v">{item.date || '—'} {item.period && <span className="muted">({item.period})</span>}</span>
            <span className="k">Vendor</span><span className="v">{item.vendor || '—'}</span>
            <span className="k">Description</span><span className="v">{item.description}</span>
            <span className="k">GL code</span><span className="v">{item.gl_code || '—'}</span>
            <span className="k">Quantity</span><span className="v num">{item.quantity ? `${item.quantity} ${item.unit}` : '—'}</span>
            <span className="k">Region</span><span className="v">{item.region || '—'}</span>
            <span className="k">Spend</span><span className="v num">{item.spend ? `${fmtT(item.spend)} ${item.currency || ''}` : '—'} <span className="muted">(ledger only, never sent to an agent)</span></span>
          </div>
          {item.raw_text && <div className="formula">{item.raw_text}</div>}
          {item.redactions.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {item.redactions.map((r) => <span className="redact" key={r}>{r.replace('_', ' ')} redacted</span>)}
            </div>
          )}
        </div>

        <div className={`step ${c.activity_type ? '' : 'dim'}`}>
          <div className="k">2 · Classification</div>
          <div className="t">
            {c.activity_type ? (ACTIVITY_LABELS[c.activity_type] || c.activity_type) : 'Unclassified'}
            {c.scope && <span className={`scopetag s${c.scope}`} style={{ marginLeft: 8 }}>{c.scope}</span>}
            {c.scope3_category && <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>Cat. {c.scope3_category} · {SCOPE3_NAMES[String(c.scope3_category)] || ''}</span>}
          </div>
          <div className="kv">
            <span className="k">Method</span><span className="v">{c.method === 'rule' ? `Rule engine · ${c.rule_id}` : c.method === 'agent' ? 'Lyzr Scope Classifier agent' : 'None (needs review)'}</span>
            <span className="k">Confidence</span><span className="v num">{Number(c.confidence).toFixed(2)}</span>
            <span className="k">Reason</span><span className="v">{c.reason}</span>
          </div>
        </div>

        <div className={`step ${f ? '' : 'dim'}`}>
          <div className="k">3 · Emission factor</div>
          {f ? (
            <>
              <div className="t">{f.factor_id} <span className="muted" style={{ fontWeight: 400 }}>· {fm.match_quality.replace('_', ' ')}</span></div>
              <div className="kv">
                <span className="k">Value</span><span className="v num">{f.value} kg CO₂e / {f.unit}</span>
                <span className="k">Source</span><span className="v">{f.source}</span>
                <span className="k">Table ref</span><span className="v">{f.table_ref}</span>
                <span className="k">Region · year</span><span className="v">{f.region} · {f.year}</span>
                {f.components && <><span className="k">Per gas</span><span className="v num">{Object.entries(f.components).map(([g, v]) => `${g} ${v}`).join(' · ')} kg/{f.unit} · {f.gwp_set}</span></>}
                {f.method === 'spend' && <><span className="k">Method</span><span className="v">Spend-based (EEIO) — lower data quality</span></>}
                {f.notes && <><span className="k">Notes</span><span className="v">{f.notes}</span></>}
              </div>
              {fm.match_quality !== 'exact' && <div className="banner warn" style={{ marginTop: 8, marginBottom: 0 }}>{fm.reason}</div>}
            </>
          ) : (
            <div className="t" style={{ fontWeight: 400 }}>{fm.reason || 'No factor lookup performed.'}</div>
          )}
        </div>

        <div className={`step ${calc ? '' : 'dim'}`} style={{ paddingBottom: 0 }}>
          <div className="k">4 · Deterministic calculation</div>
          {calc ? (
            <>
              <div className="t num">{calc.t_co2e} tCO₂e <span className="muted" style={{ fontWeight: 400 }}>({calc.kg_co2e} kg)</span></div>
              <div className="kv">
                <span className="k">Input</span><span className="v num">{calc.quantity_input} {calc.unit_input}</span>
                {calc.conversion && <><span className="k">Conversion</span><span className="v num">× {calc.conversion.factor} → {calc.quantity_converted} {calc.unit_converted}<div className="muted" style={{ fontSize: 11 }}>{calc.conversion.source}</div></span></>}
                <span className="k">Factor</span><span className="v num">{calc.factor_value} {calc.factor_unit}</span>
                {calc.gas_breakdown && <><span className="k">By gas</span><span className="v num">{Object.entries(calc.gas_breakdown).map(([g, v]) => `${g} ${v} kg`).join(' · ')}</span></>}
                <span className="k">Rounding</span><span className="v">{calc.rounding}</span>
                <span className="k">Engine</span><span className="v">{calc.engine}</span>
              </div>
              <div className="formula">{calc.formula}</div>
            </>
          ) : (
            <div className="t" style={{ fontWeight: 400 }}>No figure produced. This line is listed as a data gap in the report, never estimated.</div>
          )}
        </div>
      </aside>
    </>
  )
}
