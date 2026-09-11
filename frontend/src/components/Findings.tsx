import type { Finding } from '../api'

export default function Findings({ findings, onShowLines }: { findings: Finding[]; onShowLines?: (ids: string[]) => void }) {
  if (!findings.length) return <div className="empty">No control findings. All lines calculated with cited factors.</div>
  const order = { block: 0, warn: 1, info: 2 }
  const sorted = [...findings].sort((a, b) => order[a.severity] - order[b.severity])
  return (
    <div>
      {sorted.map((f) => (
        <div className="finding" key={f.check_id + f.title}>
          <span className={`sev ${f.severity}`}>{f.severity === 'block' ? 'Blocks' : f.severity === 'warn' ? 'Warn' : 'Info'}</span>
          <div>
            <div className="t">{f.title} <span className="id">{f.check_id}</span></div>
            <div className="d">{f.detail}</div>
          </div>
          {f.line_ids.length > 0 && onShowLines ? (
            <button className="btn small" onClick={() => onShowLines(f.line_ids)}>{f.line_ids.length} line{f.line_ids.length === 1 ? '' : 's'}</button>
          ) : <span />}
        </div>
      ))}
    </div>
  )
}
