import { useCallback, useEffect, useState } from 'react'
import { api, type Health, type LedgerEntry, type RunPayload, type RunSummary } from './api'
import UploadPanel from './components/UploadPanel'
import KpiTiles from './components/KpiTiles'
import { ActivityChart, Scope3Chart, ScopeChart } from './components/Charts'
import Findings from './components/Findings'
import Ledger from './components/Ledger'
import LineageDrawer from './components/LineageDrawer'
import ReportView from './components/ReportView'
import AgentLog from './components/AgentLog'

type Tab = 'overview' | 'ledger' | 'findings' | 'report' | 'log'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [current, setCurrent] = useState<RunPayload | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jurisdiction, setJurisdiction] = useState('CSRD')
  const [selected, setSelected] = useState<string | null>(null)
  const [filterIds, setFilterIds] = useState<string[] | null>(null)

  const refreshRuns = useCallback(async () => {
    const list = await api.listRuns()
    setRuns(list)
    return list
  }, [])

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    refreshRuns().then((list) => { if (list.length) api.getRun(list[0].run_id).then(setCurrent).catch(() => {}) }).catch((e) => setError(String(e)))
  }, [refreshRuns])

  const finish = async (p: RunPayload) => {
    setCurrent(p)
    setSelected(null)
    setFilterIds(null)
    setTab('overview')
    await refreshRuns()
  }

  const runDemo = async () => {
    setBusy(true); setError(null)
    try { await finish(await api.demo(jurisdiction)) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const upload = async (files: File[], org: string, region: string) => {
    setBusy(true); setError(null)
    try { await finish(await api.upload(files, org, jurisdiction, region)) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const pick = async (id: string) => {
    if (!id) return
    setBusy(true)
    try { setCurrent(await api.getRun(id)); setSelected(null); setFilterIds(null) } finally { setBusy(false) }
  }

  const entries: LedgerEntry[] = current?.entries ?? []
  const summary = current?.summary
  const selectedEntry = entries.find((e) => e.item.line_id === selected) || null
  const blocking = summary?.findings.filter((f) => f.severity === 'block').length ?? 0
  const warns = summary?.findings.filter((f) => f.severity === 'warn').length ?? 0

  return (
    <>
      <div className="topbar">
        <div className="brand">
          <h1>Carbon Copilot</h1>
          <span className="sub">ESG &amp; GHG accounting · CSRD / SEC</span>
        </div>
        <div className="spacer" />
        {health && (
          <span className={`pill dot ${health.agent_mode}`} title={health.lyzr_configured ? 'Lyzr Agent API configured' : 'Set LYZR_API_KEY and agent IDs to enable agents'}>
            {health.agent_mode === 'lyzr' ? 'Lyzr agents live' : 'Rules-only fallback'}
          </span>
        )}
        {health && <span className="muted" style={{ fontSize: 12 }}>{health.factor_rows} factors · {health.factor_tables.join(', ')}</span>}
        <select id="run-picker" value={summary?.run_id || ''} onChange={(e) => pick(e.target.value)} aria-label="Select run">
          {!summary && <option value="">No run yet</option>}
          {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.org_name} · {r.reporting_period} · {r.jurisdiction} · {r.run_id.slice(0, 15)}</option>)}
        </select>
      </div>

      <div className="page">
        {error && <div className="banner block">{error}</div>}
        {!health && <div className="banner warn">Backend not reachable. Start it with <code>uvicorn app.main:app --reload</code> in backend/ or <code>docker compose up</code>.</div>}

        <div className="tabs" role="tablist">
          {([['overview', 'Overview'], ['ledger', 'Ledger'], ['findings', 'Findings'], ['report', 'Disclosure'], ['log', 'Governance log']] as [Tab, string][]).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)} disabled={!summary && k !== 'overview'}>
              {label}
              {k === 'ledger' && summary && <span className="count">{entries.length}</span>}
              {k === 'findings' && summary && <span className="count">{summary.findings.length}</span>}
            </button>
          ))}
        </div>

        {tab === 'overview' && (
          <div className="grid">
            <UploadPanel busy={busy} jurisdiction={jurisdiction} onJurisdiction={setJurisdiction} onRunDemo={runDemo} onUpload={upload} />
            {summary ? (
              <>
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <div>
                    <h2>{summary.org_name} · {summary.reporting_period}</h2>
                    <div className="muted" style={{ fontSize: 12 }}>{summary.source_files.join(' · ')} · run {summary.run_id} · {summary.agent_mode === 'lyzr' ? 'Lyzr agents' : 'rules-only fallback'}</div>
                  </div>
                  {blocking > 0
                    ? <span className="sev block">{blocking} blocking finding{blocking === 1 ? '' : 's'} · report blocked</span>
                    : <span className="pill lyzr">Report allowed · {warns} warning{warns === 1 ? '' : 's'} to disclose</span>}
                </div>
                <KpiTiles t={summary.totals} />
                <div className="grid cols-2">
                  <ScopeChart t={summary.totals} />
                  <Scope3Chart t={summary.totals} />
                </div>
                <ActivityChart t={summary.totals} entries={entries} />
                <div className="card">
                  <h3>Control findings</h3>
                  <Findings findings={summary.findings} onShowLines={(ids) => { setFilterIds(ids); setTab('ledger') }} />
                </div>
              </>
            ) : (
              <div className="empty">Run the bundled sample or upload your own files to see the dashboard.</div>
            )}
          </div>
        )}

        {tab === 'ledger' && summary && (
          <Ledger entries={entries} selected={selected} onSelect={setSelected} filterIds={filterIds} onClearFilter={() => setFilterIds(null)} />
        )}

        {tab === 'findings' && summary && (
          <div className="card">
            <h3>Greenwashing and data-integrity checks</h3>
            <p className="cap" style={{ marginTop: 0 }}>Deterministic checks over the ledger. Blocking findings stop disclosure generation; warnings are printed into the report's governance log.</p>
            <Findings findings={summary.findings} onShowLines={(ids) => { setFilterIds(ids); setTab('ledger') }} />
          </div>
        )}

        {tab === 'report' && summary && <ReportView run={summary} />}
        {tab === 'log' && summary && <AgentLog runId={summary.run_id} />}
      </div>

      {selectedEntry && <LineageDrawer entry={selectedEntry} onClose={() => setSelected(null)} />}
    </>
  )
}
