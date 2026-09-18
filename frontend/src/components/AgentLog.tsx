import { useEffect, useState } from 'react'
import { api, type AgentLogEntry } from '../api'

export default function AgentLog({ runId }: { runId: string }) {
  const [rows, setRows] = useState<AgentLogEntry[]>([])
  useEffect(() => { api.agentLog(runId).then(setRows).catch(() => setRows([])) }, [runId])
  const tokens = rows.reduce((a, r) => a + (r.tokens_estimate || 0), 0)
  const latency = rows.reduce((a, r) => a + (r.latency_ms || 0), 0)
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Governance log (AIMS)</h3>
        <span className="muted" style={{ marginLeft: 'auto' }}>{rows.length} events · ~{tokens.toLocaleString()} tokens · {latency} ms agent latency</span>
      </div>
      <p className="cap" style={{ marginTop: 0 }}>Every handoff between the rule engine, Lyzr agents and the deterministic tools. Numbers never originate in an agent step; labels and narrative are validated before use.</p>
      <div className="table-scroll">
        <table className="ledger">
          <thead><tr><th>Time</th><th>Actor</th><th>Mode</th><th>Step</th><th>Input</th><th>Output</th><th style={{ textAlign: 'right' }}>Tokens</th><th style={{ textAlign: 'right' }}>ms</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono">{r.ts.replace('T', ' ').replace('+00:00', 'Z')}</td>
                <td>{r.agent}</td>
                <td><span className={`pill ${r.mode}`}>{r.mode}</span></td>
                <td>{r.step}</td>
                <td>{r.input_summary}</td>
                <td>{r.output_summary}</td>
                <td className="num">{r.tokens_estimate ?? '—'}</td>
                <td className="num">{r.latency_ms ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
