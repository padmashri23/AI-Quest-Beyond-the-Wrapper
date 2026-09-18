import type { RunPayload } from "../api";
import { ACTIVITY_LABELS } from "../api";
import { number, type Workspace } from "../workspace";
import { EntryTable } from "./WorkspaceUI";
import type { LedgerEntry } from "../api";

export default function Overview({
  run,
  workspace,
  navigate,
  select,
}: {
  run: RunPayload;
  workspace: Workspace;
  navigate: (name: string) => void;
  select: (entry: LedgerEntry) => void;
}) {
  const t = run.summary.totals;
  const sources = Object.entries(t.by_activity)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 4);
  const max = Math.max(...sources.map(([, v]) => Number(v)), 1);
  const checks = workspace.readiness;
  return (
    <>
      <section className="kpi-band">
        {[
          ["Total footprint", t.total_location_based],
          ["Scope 1", t.scope1],
          ["Scope 2", t.scope2_location],
          ["Scope 3", t.scope3],
        ].map(([label, value]) => (
          <div className="kpi" key={label}>
            <div className="kpi-label">{label}</div>
            <div className="metric">{number(value)}</div>
            <small>tCO₂e</small>
          </div>
        ))}
      </section>
      <div className="overview-grid">
        <section className="panel emissions">
          <div className="panel-head">
            <h2>Emissions by source</h2>
            <span className="muted">tCO₂e</span>
          </div>
          <div className="activity-bars">
            {sources.map(([key, value], i) => (
              <div className="activity-bar" key={key}>
                <span title={ACTIVITY_LABELS[key] || key}>
                  {ACTIVITY_LABELS[key] || key.replaceAll("_", " ")}
                </span>
                <div className="bar-track">
                  <div
                    className={`bar-fill scope-${i < 2 ? 1 : 2}`}
                    style={{ width: `${(Number(value) / max) * 100}%` }}
                  />
                </div>
                <strong>{number(value)}</strong>
              </div>
            ))}
          </div>
          <p className="chart-caption">
            Largest sources · location-based inventory ·{" "}
            {run.summary.reporting_period}
          </p>
        </section>
        <section className="readiness-panel">
          <h3>
            {checks.approved
              ? "Reviewed & approved"
              : checks.ready_for_approval
                ? "Ready for sign-off"
                : "Ready for review"}
          </h3>
          <div className="readiness-body">
            <div className="gap-number">
              {checks.blockers.length}
              <span>open readiness checks</span>
            </div>
            <ul className="readiness-list">
              <li>
                <span className="check-circle done">✓</span>
                <div>
                  <strong>Source documents captured</strong>
                  <small>
                    {workspace.documents.length} retained evidence files
                  </small>
                </div>
              </li>
              <li>
                <span
                  className={`check-circle ${checks.sections_complete === checks.sections_total ? "done" : ""}`}
                />
                <div>
                  <strong>Disclosure preparation</strong>
                  <small>
                    {checks.sections_complete} of {checks.sections_total}{" "}
                    sections
                  </small>
                </div>
              </li>
              <li>
                <span
                  className={`check-circle ${checks.approved ? "done" : ""}`}
                />
                <div>
                  <strong>Reviewer approval</strong>
                  <small>
                    {checks.approved
                      ? "Current version approved"
                      : "Independent sign-off pending"}
                  </small>
                </div>
              </li>
            </ul>
          </div>
          <button
            className="btn primary"
            onClick={() => navigate("Review queue")}
          >
            Open review queue →
          </button>
        </section>
      </div>
      <EntryTable entries={run.entries} select={select} compact />
      <div className="footnote">
        <span>
          {run.summary.org_name} · Revision {run.summary.revision} ·{" "}
          {t.lines_calculated}/{t.lines_total} activities calculated
        </span>
        <span>
          {run.summary.agent_mode === "lyzr"
            ? "Lyzr-assisted classification"
            : "Deterministic fallback mode"}{" "}
          · Decimal calculation tools
        </span>
      </div>
    </>
  );
}
