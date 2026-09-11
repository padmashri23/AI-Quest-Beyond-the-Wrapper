import { useEffect, useState } from 'react'
import { marked } from 'marked'
import { api, type RunSummary } from '../api'

export default function ReportView({ run }: { run: RunSummary }) {
  const [jur, setJur] = useState(run.jurisdiction)
  const [md, setMd] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = async (regenerate = false) => {
    setBusy(true)
    setErr(null)
    try {
      setMd(await api.reportMarkdown(run.run_id, jur, regenerate))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void load() }, [run.run_id, jur]) // eslint-disable-line react-hooks/exhaustive-deps

  const html = md ? (marked.parse(md, { async: false }) as string) : ''

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 14 }}>
        <label className="field">
          Framework
          <select id="report-jurisdiction" value={jur} onChange={(e) => setJur(e.target.value)}>
            <option value="CSRD">CSRD / ESRS E1</option>
            <option value="SEC">SEC Reg S-K Item 1504</option>
          </select>
        </label>
        <button className="btn" onClick={() => load(true)} disabled={busy}>Regenerate narrative</button>
        <a className="btn" href={api.reportUrl(run.run_id, jur)} target="_blank" rel="noreferrer">Open raw markdown</a>
        <span className="muted" style={{ marginLeft: 'auto' }}>
          Narrative by {run.agent_mode === 'lyzr' ? 'Lyzr Disclosure Writer (number-locked)' : 'deterministic template (no Lyzr key)'}
        </span>
      </div>
      {!run.report_allowed && <div className="banner block">Report blocked: blocking findings are open. The draft below is for remediation only.</div>}
      {err && <div className="error">{err}</div>}
      {busy && !md ? <div className="empty">Drafting…</div> : <div className="report" dangerouslySetInnerHTML={{ __html: html }} />}
    </div>
  )
}
