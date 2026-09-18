import { useEffect, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api, type RunSummary } from "../api";
import { send } from "../workspace";

export default function ReportView({
  run,
  canDraft = false,
}: {
  run: RunSummary;
  canDraft?: boolean;
}) {
  const [jur, setJur] = useState(run.jurisdiction);
  const [md, setMd] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async (regenerate = false) => {
    setBusy(true);
    setErr(null);
    try {
      if (regenerate)
        await send(`/runs/${run.run_id}/draft-narrative`, {
          jurisdiction: jur,
          expected_revision: run.revision,
        });
      setMd(await api.reportMarkdown(run.run_id, jur));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    let active = true;
    api
      .reportMarkdown(run.run_id, jur)
      .then((text) => {
        if (active) {
          setMd(text);
          setErr(null);
        }
      })
      .catch((e) => {
        if (active) setErr(e.message);
      });
    return () => {
      active = false;
    };
  }, [run.run_id, run.revision, jur]);

  const html = md
    ? DOMPurify.sanitize(marked.parse(md, { async: false }) as string)
    : "";

  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 14 }}>
        <label className="field">
          Framework
          <select
            id="report-jurisdiction"
            value={jur}
            onChange={(e) => setJur(e.target.value)}
          >
            <option value="CSRD">CSRD / ESRS E1</option>
            <option value="SEC">SEC Reg S-K Item 1504</option>
          </select>
        </label>
        <button
          className="btn"
          onClick={() => load(true)}
          disabled={busy || !canDraft}
        >
          Regenerate narrative
        </button>
        <a
          className="btn"
          href={api.reportUrl(run.run_id, jur)}
          target="_blank"
          rel="noreferrer"
        >
          Open raw markdown
        </a>
        <span className="muted" style={{ marginLeft: "auto" }}>
          Draft preview only. Narrative source and governance log are recorded
          in the report.
        </span>
      </div>
      {!run.report_allowed && (
        <div className="banner block">
          Report blocked: blocking findings are open. The draft below is for
          remediation only.
        </div>
      )}
      {err && <div className="error">{err}</div>}
      {busy && !md ? (
        <div className="empty">Drafting…</div>
      ) : (
        <div className="report" dangerouslySetInnerHTML={{ __html: html }} />
      )}
    </div>
  );
}
