import { useRef, useState } from 'react'

interface Props {
  busy: boolean
  jurisdiction: string
  onJurisdiction: (j: string) => void
  onRunDemo: () => void
  onUpload: (files: File[], orgName: string, defaultRegion: string) => void
}

export default function UploadPanel({ busy, jurisdiction, onJurisdiction, onRunDemo, onUpload }: Props) {
  const [files, setFiles] = useState<File[]>([])
  const [org, setOrg] = useState('Demo Manufacturing Ltd')
  const [region, setRegion] = useState('')
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const add = (list: FileList | null) => {
    if (!list) return
    const ok = Array.from(list).filter((f) => /\.(csv|xlsx|xls|pdf)$/i.test(f.name))
    setFiles((prev) => [...prev, ...ok.filter((f) => !prev.some((p) => p.name === f.name))])
  }

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0 }}>New run</h3>
        <button className="btn primary" onClick={onRunDemo} disabled={busy} id="btn-demo">
          {busy ? 'Running…' : 'Run bundled sample dataset'}
        </button>
      </div>
      <p className="cap" style={{ marginTop: 6 }}>
        Upload ERP exports (CSV / Excel), utility bill PDFs, travel or freight logs. Prices, account numbers and names are redacted before any agent sees a line.
      </p>
      <div
        className={`drop ${over ? 'over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files) }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      >
        Drop files here or click to browse
        <input ref={inputRef} id="file-input" type="file" multiple accept=".csv,.xlsx,.xls,.pdf" onChange={(e) => add(e.target.files)} />
      </div>
      {files.length > 0 && (
        <div className="files">
          {files.map((f) => (
            <span className="chip" key={f.name}>
              {f.name}
              <button aria-label={`remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x !== f))}>×</button>
            </span>
          ))}
        </div>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <label className="field">
          Organisation
          <input id="org-name" type="text" value={org} onChange={(e) => setOrg(e.target.value)} style={{ width: 220 }} />
        </label>
        <label className="field">
          Framework
          <select id="jurisdiction" value={jurisdiction} onChange={(e) => onJurisdiction(e.target.value)}>
            <option value="CSRD">CSRD / ESRS E1</option>
            <option value="SEC">SEC Reg S-K</option>
          </select>
        </label>
        <label className="field">
          Default region (if missing)
          <select id="default-region" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">None</option>
            <option value="US">US (national grid)</option>
            <option value="GB">GB</option>
            <option value="DE">DE</option>
            <option value="IN">IN</option>
            <option value="FR">FR</option>
            <option value="CAMX">CAMX (California)</option>
            <option value="ERCT">ERCT (Texas)</option>
          </select>
        </label>
        <div className="spacer" style={{ flex: 1 }} />
        <button className="btn" disabled={busy || files.length === 0} onClick={() => onUpload(files, org, region)} id="btn-upload">
          Run on {files.length || 'selected'} file{files.length === 1 ? '' : 's'}
        </button>
      </div>
    </div>
  )
}
