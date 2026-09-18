import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import type { RunPayload } from "../api";
import {
  number,
  request,
  send,
  type Catalog,
  type Regulations,
  type User,
  type Workspace,
} from "../workspace";
import { Evidence, Field } from "./WorkspaceUI";
const ReportView = lazy(() => import("./ReportView"));
const AgentLog = lazy(() => import("./AgentLog"));
type Props = {
  run: RunPayload;
  workspace: Workspace;
  user: User;
  reload: () => Promise<void>;
};
const data = (e: FormEvent<HTMLFormElement>) => {
  e.preventDefault();
  return new FormData(e.currentTarget);
};
export function DisclosurePanel({ run, workspace, user, reload }: Props) {
  const [specs, setSpecs] = useState<Regulations>({ sections: [] });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  useEffect(() => {
    request<Regulations>("/regulations")
      .then(setSpecs)
      .catch((e) => setError(e.message));
  }, []);
  const base = `/runs/${run.summary.run_id}`;
  const editable = ["admin", "analyst"].includes(user.role);
  async function save(e: FormEvent<HTMLFormElement>, id: string) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(
        `${base}/sections/${id}`,
        {
          text: f.get("text"),
          evidence_ids: [f.get("evidence")],
          expected_content_sha256: workspace.readiness.content_sha256,
        },
        "PUT",
      );
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function approve(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`${base}/approve`, {
        content_sha256: workspace.readiness.content_sha256,
        statement: f.get("statement"),
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="notice">
        <strong>Disclosure preparation, not automatic filing.</strong>
        <p>{workspace.profile.notice}</p>
      </div>
      <div className="section-heading">
        <h2>Build your evidence-backed dossier</h2>
        <span>
          {workspace.readiness.sections_complete} /{" "}
          {workspace.readiness.sections_total} sections
        </span>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="disclosure-list">
        {specs.sections.map((spec) => {
          const saved = workspace.sections.find((s) => s.id === spec.id);
          return (
            <details key={spec.id} className="panel">
              <summary>
                <span className={`status-dot ${saved ? "done" : ""}`} />
                <strong>{spec.title}</strong>
                <span className="muted">
                  {saved ? "Evidence attached" : "Needs preparation"}
                </span>
                <span>+</span>
              </summary>
              <form onSubmit={(e) => save(e, spec.id)}>
                <p className="muted">{spec.guidance}</p>
                <Field label="Disclosure and methodology">
                  <textarea
                    name="text"
                    defaultValue={saved?.text || ""}
                    required
                    minLength={40}
                    rows={5}
                    disabled={!editable}
                  />
                </Field>
                <Evidence documents={workspace.documents} />
                <button className="btn primary" disabled={!editable || busy}>
                  Save section
                </button>
                {saved && (
                  <small className="muted">
                    {" "}
                    Last prepared by {saved.author}
                  </small>
                )}
              </form>
            </details>
          );
        })}
      </div>
      <section className="panel approval">
        <h2>Independent sign-off</h2>
        <p>
          Changes to activities, evidence, disclosures or electricity
          instruments invalidate the previous approval. A preparer cannot
          approve their own dossier.
        </p>
        <form onSubmit={approve}>
          <Field label="Reviewer attestation">
            <textarea
              name="statement"
              minLength={30}
              required
              placeholder="Record the scope of your review, evidence examined and any limitations."
            />
          </Field>
          <div className="actions">
            <button
              className="btn primary"
              disabled={
                busy ||
                !workspace.readiness.ready_for_approval ||
                !["admin", "reviewer"].includes(user.role)
              }
            >
              Approve reviewed version
            </button>
            {workspace.readiness.approved ? (
              <a className="btn" href={`/api${base}/export`}>
                Download approved dossier ↓
              </a>
            ) : (
              <button className="btn" disabled>
                Export locked
              </button>
            )}
            <button
              className="btn quiet"
              type="button"
              onClick={() => setPreview(!preview)}
            >
              {preview ? "Hide" : "View"} draft report
            </button>
          </div>
        </form>
      </section>
      {preview && (
        <Suspense fallback={<p>Loading report…</p>}>
          <ReportView run={run.summary} canDraft={editable} />
        </Suspense>
      )}
    </>
  );
}
export function EvidencePanel({ run, workspace, user, reload }: Props) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function upload(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    try {
      await request(`/runs/${run.summary.run_id}/evidence`, {
        method: "POST",
        body: f,
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel evidence-panel">
      <div className="panel-head">
        <h2>Evidence vault</h2>
        <span className="count">{workspace.documents.length} documents</span>
      </div>
      <p>
        Original sources are retained encrypted, with SHA-256 fingerprints.
        Access is recorded in the audit trail.
      </p>
      <form onSubmit={upload} className="actions">
        <Field label="Add supporting evidence (up to 20 MB)">
          <input name="file" type="file" required />
        </Field>
        <button className="btn" disabled={busy || user.role === "auditor"}>
          {busy ? "Uploading…" : "Attach evidence"}
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="evidence-list">
        {workspace.documents.map((d) => (
          <a
            key={d.document_id}
            href={`/api/runs/${run.summary.run_id}/evidence/${d.document_id}`}
          >
            <strong>{d.filename} ↗</strong>
            <small>{d.sha256}</small>
          </a>
        ))}
      </div>
    </section>
  );
}
export function ScenarioPanel({ run, workspace, user, reload }: Props) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function simulate(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`/runs/${run.summary.run_id}/scenarios`, {
        name: f.get("name"),
        currency: f.get("currency"),
        years: Number(f.get("years")),
        discount_percent: f.get("discount"),
        assumptions: f.get("assumptions"),
        levers: [
          {
            name: f.get("name"),
            activity_type: f.get("activity"),
            reduction_percent: f.get("reduction"),
            investment: f.get("investment"),
            annual_savings: f.get("savings"),
          },
        ],
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="notice">
        Model a reduction before you commit. These are assumption-based
        projections, never deductions from your reported inventory.
      </div>
      <div className="split">
        <section className="panel padded">
          <h2>Explore a reduction lever</h2>
          <form onSubmit={simulate}>
            <Field label="Plan name">
              <input
                name="name"
                placeholder="Electrify the delivery fleet"
                required
                minLength={3}
              />
            </Field>
            <Field label="Baseline activity">
              <select name="activity">
                {Object.entries(run.summary.totals.by_activity).map(
                  ([k, v]) => (
                    <option key={k} value={k}>
                      {k.replaceAll("_", " ")} · {number(v)} tCO₂e
                    </option>
                  ),
                )}
              </select>
            </Field>
            <div className="form-grid">
              <Field label="Reduction (%)">
                <input
                  name="reduction"
                  type="number"
                  min="0.01"
                  max="100"
                  step="any"
                  required
                />
              </Field>
              <Field label="Currency">
                <input
                  name="currency"
                  defaultValue="USD"
                  pattern="[A-Z]{3}"
                  required
                />
              </Field>
              <Field label="Initial investment">
                <input
                  name="investment"
                  type="number"
                  min="0"
                  step="any"
                  required
                />
              </Field>
              <Field label="Annual cost savings">
                <input
                  name="savings"
                  type="number"
                  min="0"
                  step="any"
                  required
                />
              </Field>
              <Field label="Time horizon (years)">
                <input
                  name="years"
                  type="number"
                  min="1"
                  max="50"
                  defaultValue="5"
                  required
                />
              </Field>
              <Field label="Discount rate (%)">
                <input
                  name="discount"
                  type="number"
                  min="0"
                  max="100"
                  step="any"
                  defaultValue="5"
                  required
                />
              </Field>
            </div>
            <Field label="Assumptions & limitations">
              <textarea name="assumptions" required minLength={20} />
            </Field>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button
              className="btn primary"
              disabled={busy || !["admin", "analyst"].includes(user.role)}
            >
              {busy ? "Calculating…" : "Calculate scenario →"}
            </button>
          </form>
        </section>
        <div className="plans">
          {workspace.scenarios.length === 0 && (
            <div className="empty panel">
              Your saved scenarios will appear here, with avoided emissions, ROI
              and payback.
            </div>
          )}
          {workspace.scenarios.toReversed().map((s) => (
            <article className="panel padded" key={s.id}>
              <span className="badge green">
                Projection · revision {s.baseline_revision}
              </span>
              <h2>{s.name}</h2>
              <div className="big-number">
                {number(s.avoided_t)} <small>tCO₂e / year</small>
              </div>
              {s.levers.map((l, i) => (
                <div className="scenario-metrics" key={i}>
                  <div>
                    <small>ROI</small>
                    <strong>{number(l.roi_percent)}%</strong>
                  </div>
                  <div>
                    <small>Net present value</small>
                    <strong>
                      {s.currency} {number(l.npv)}
                    </strong>
                  </div>
                  <div>
                    <small>Payback</small>
                    <strong>{number(l.payback_years)} years</strong>
                  </div>
                </div>
              ))}
              {s.baseline_revision !== run.summary.revision && (
                <p className="amber-text">
                  Baseline changed; create a new scenario.
                </p>
              )}
            </article>
          ))}
        </div>
      </div>
    </>
  );
}
export function SupplierPanel({ run, workspace, user, reload }: Props) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function approve(
    e: FormEvent<HTMLFormElement>,
    id: string,
    hash: string,
  ) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`/runs/${run.summary.run_id}/suppliers/${id}/approve`, {
        content_sha256: hash,
        statement: f.get("approval"),
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function create(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`/runs/${run.summary.run_id}/suppliers`, {
        supplier: f.get("supplier"),
        contact_email: f.get("email"),
        due_date: f.get("due"),
        line_ids: f.getAll("lines"),
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function receive(e: FormEvent<HTMLFormElement>, id: string) {
    const f = data(e);
    setBusy(true);
    try {
      await send(`/runs/${run.summary.run_id}/suppliers/${id}/response`, {
        evidence_ids: [f.get("evidence")],
        notes: f.get("notes"),
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="notice">
        Email delivery is disabled. Review the recipient and message, then have
        an administrator or reviewer approve the exact draft before downloading
        it. Approval does not send an email.
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="split">
        <section className="panel padded">
          <h2>Request missing evidence</h2>
          <form onSubmit={create}>
            <Field label="Supplier name">
              <input name="supplier" required minLength={2} />
            </Field>
            <Field label="Contact email">
              <input name="email" type="email" required />
            </Field>
            <Field label="Response due">
              <input name="due" type="date" required />
            </Field>
            <Field label="Related activity (Ctrl / ⌘ to select more)">
              <select name="lines" multiple size={6} required>
                {run.entries.map((e) => (
                  <option key={e.item.line_id} value={e.item.line_id}>
                    {e.item.description}
                  </option>
                ))}
              </select>
            </Field>
            <button
              className="btn primary"
              disabled={busy || !["admin", "analyst"].includes(user.role)}
            >
              Prepare request draft →
            </button>
          </form>
        </section>
        <div className="plans">
          {!workspace.suppliers.length && (
            <div className="panel empty">
              No supplier requests yet. Start with activities missing quantities
              or source evidence.
            </div>
          )}
          {workspace.suppliers.toReversed().map((s) => (
            <article className="panel padded" key={s.id}>
              <span className="badge amber">{s.status}</span>
              <h2>{s.supplier}</h2>
              <p className="muted">
                To {s.contact_email} · Due {s.due_date}
              </p>
              <p>{s.subject}</p>
              <p className="muted">{s.delivery_status}</p>
              {s.approved ? (
                <>
                  <p className="badge">Approved by {s.approved_by}</p>
                  <a
                    className="btn"
                    href={`/api/runs/${run.summary.run_id}/suppliers/${s.id}/draft`}
                  >
                    Download approved draft ↓
                  </a>
                </>
              ) : (
                <p className="badge amber">
                  Awaiting approval · Download locked
                </p>
              )}
              <details>
                <summary>View draft & record response</summary>
                <pre className="draft-email">{s.body}</pre>
                {!s.approved && (
                  <form onSubmit={(e) => approve(e, s.id, s.content_sha256)}>
                    <Field label="Approval statement">
                      <textarea
                        name="approval"
                        required
                        minLength={20}
                        placeholder="Confirm you reviewed the recipient, message and information being shared."
                      />
                    </Field>
                    <button
                      className="btn primary"
                      disabled={
                        busy || !["admin", "reviewer"].includes(user.role)
                      }
                    >
                      Approve draft (does not send)
                    </button>
                  </form>
                )}
                <form onSubmit={(e) => receive(e, s.id)}>
                  <Evidence documents={workspace.documents} />
                  <Field label="Response assessment">
                    <textarea name="notes" required minLength={20} />
                  </Field>
                  <button
                    className="btn"
                    disabled={busy || !["admin", "analyst"].includes(user.role)}
                  >
                    Record response
                  </button>
                </form>
              </details>
            </article>
          ))}
        </div>
      </div>
    </>
  );
}
export function MarketPanel({ run, workspace, user, reload }: Props) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function revoke(e: FormEvent<HTMLFormElement>, id: string) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`/runs/${run.summary.run_id}/instruments/${id}/revoke`, {
        rationale: f.get("rationale"),
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send(`/runs/${run.summary.run_id}/instruments`, {
        line_id: f.get("line"),
        quantity_kwh: f.get("quantity"),
        factor_kg_per_kwh: f.get("factor"),
        instrument_type: f.get("type"),
        serial_number: f.get("serial"),
        period: f.get("period"),
        region: f.get("region"),
        evidence_ids: [f.get("evidence")],
        quality_statement: f.get("quality"),
        retired: f.get("retired") === "on",
      });
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel padded">
      <h2>Market-based Scope 2</h2>
      <p className="muted">
        Allocate source-backed contractual instruments or a residual mix.
        Uncovered electricity is not treated as zero.
      </p>
      <p>
        <strong>
          {workspace.readiness.market.complete
            ? `${number(workspace.readiness.market.scope2_market_t)} tCO₂e`
            : `${workspace.readiness.market.gaps.length} electricity lines need complete coverage`}
        </strong>
      </p>
      <details>
        <summary>Add an electricity instrument</summary>
        <form onSubmit={save}>
          <div className="form-grid">
            <Field label="Electricity activity">
              <select name="line" required>
                {run.entries
                  .filter(
                    (e) =>
                      e.classification.activity_type === "electricity_grid" &&
                      e.status === "calculated",
                  )
                  .map((e) => (
                    <option key={e.item.line_id} value={e.item.line_id}>
                      {e.item.description} · {e.item.quantity} {e.item.unit} ·{" "}
                      {e.item.region}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Instrument type">
              <select name="type">
                <option value="contract">Contractual instrument</option>
                <option value="residual_mix">Documented residual mix</option>
              </select>
            </Field>
            <Field label="Unique certificate / reference">
              <input name="serial" required minLength={3} />
            </Field>
            <Field label="Allocated kWh">
              <input
                name="quantity"
                type="number"
                min="0.001"
                step="any"
                required
              />
            </Field>
            <Field label="Factor (kgCO₂e / kWh)">
              <input name="factor" type="number" min="0" step="any" required />
            </Field>
            <Field label="Region">
              <input name="region" required />
            </Field>
            <Field label="Period">
              <input
                name="period"
                defaultValue={run.summary.reporting_period}
                pattern="FY20[0-9]{2}"
                required
              />
            </Field>
            <Evidence documents={workspace.documents} />
          </div>
          <Field label="GHG Protocol quality criteria and factor source">
            <textarea name="quality" required minLength={40} />
          </Field>
          <label className="checkbox">
            <input name="retired" type="checkbox" /> Retirement / cancellation
            evidence attached (required for contracts)
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button
            className="btn primary"
            disabled={busy || !["admin", "analyst"].includes(user.role)}
          >
            Allocate instrument
          </button>
        </form>
      </details>
      {workspace.instruments.map((i) => (
        <details key={i.id}>
          <summary>
            {i.serial_number} · {number(i.quantity_kwh)} kWh ×{" "}
            {i.factor_kg_per_kwh} kgCO₂e/kWh{" "}
            {i.status === "revoked" ? "· Revoked" : ""}
          </summary>
          {i.status !== "revoked" && (
            <form onSubmit={(e) => revoke(e, i.id)}>
              <Field label="Reason for revocation">
                <textarea name="rationale" required minLength={20} />
              </Field>
              <button
                className="btn"
                disabled={busy || !["admin", "analyst"].includes(user.role)}
              >
                Revoke allocation with audit record
              </button>
            </form>
          )}
        </details>
      ))}
    </section>
  );
}
export function FactorPanel({ catalog }: { catalog: Catalog | null }) {
  const [query, setQuery] = useState("");
  const [verified, setVerified] = useState(true);
  const rows =
    catalog?.rows.filter(
      (f) =>
        (!verified || f.verified) &&
        `${f.activity_type} ${f.region} ${f.year} ${f.table_ref}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ) || [];
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Official-source factor catalogue</h2>
        <input
          className="search"
          aria-label="Search factors"
          placeholder="Activity, country, year…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="actions padded">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={verified}
            onChange={(e) => setVerified(e.target.checked)}
          />
          Source-verified imports only
        </label>
        <span className="muted">
          {rows.length.toLocaleString()} matching rows · showing first 100
        </span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Activity & official reference</th>
              <th>Region / year</th>
              <th>kgCO₂e / unit</th>
              <th>Provenance</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((f) => (
              <tr key={f.factor_id}>
                <td>
                  <strong>{f.activity_type.replaceAll("_", " ")}</strong>
                  <small>{f.table_ref}</small>
                </td>
                <td>
                  {f.region} · {f.year}
                </td>
                <td>
                  {f.value} / {f.unit}
                </td>
                <td>
                  {f.url && (
                    <a href={f.url} target="_blank" rel="noreferrer">
                      {f.source} ↗
                    </a>
                  )}
                  <small>
                    {f.verified
                      ? f.source_row
                      : "Unverified legacy transcription"}
                  </small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!catalog && <p className="empty">Loading factor catalogue…</p>}
    </section>
  );
}
export function AuditPanel({ run, workspace }: Props) {
  const [events, setEvents] = useState<
    {
      id: number;
      created_at: string;
      actor: string;
      action: string;
      event_hash: string;
    }[]
  >([]);
  const [error, setError] = useState("");
  useEffect(() => {
    request<{ events: typeof events }>(`/runs/${run.summary.run_id}/audit`)
      .then((r) => setEvents(r.events))
      .catch((e) => setError(e.message));
  }, [run.summary.run_id, workspace.readiness.content_sha256]);
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>Decisions leave a trail.</h2>
          <span
            className={`badge ${workspace.readiness.integrity.valid ? "green" : "amber"}`}
          >
            {workspace.readiness.integrity.valid
              ? "Integrity verified"
              : "Integrity failure"}
          </span>
        </div>
        <p className="padded muted">
          Append-only revisions and HMAC-signed events. Retain checkpoints
          independently: this is tamper-evident, not protection against an
          administrator holding both database and signing keys.
        </p>
        {error && <p className="error">{error}</p>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Event fingerprint</th>
              </tr>
            </thead>
            <tbody>
              {events.toReversed().map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td>{e.action}</td>
                  <td>{e.actor}</td>
                  <td>
                    <code title={e.event_hash}>
                      {e.event_hash.slice(0, 18)}…
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Suspense fallback={<p>Loading agent governance log…</p>}>
        <AgentLog runId={run.summary.run_id} />
      </Suspense>
    </>
  );
}
export function TeamPanel() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => request<User[]>("/auth/users").then(setUsers);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  async function create(e: FormEvent<HTMLFormElement>) {
    const f = data(e);
    setBusy(true);
    setError("");
    try {
      await send("/auth/users", Object.fromEntries(f));
      await load();
      e.currentTarget?.reset();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="split">
      <section className="panel padded">
        <h2>Invite a workspace member</h2>
        <p className="muted">
          Create a separate reviewer for independent sign-off. Share the initial
          password through a secure channel.
        </p>
        <form onSubmit={create}>
          <Field label="Username">
            <input name="username" required minLength={3} />
          </Field>
          <Field label="Display name">
            <input name="display_name" required />
          </Field>
          <Field label="Initial password">
            <input
              name="password"
              type="password"
              minLength={12}
              required
              autoComplete="new-password"
            />
          </Field>
          <Field label="Role">
            <select name="role">
              <option value="analyst">Analyst — prepare inventories</option>
              <option value="reviewer">Reviewer — review and approve</option>
              <option value="auditor">Auditor — read only</option>
              <option value="admin">Administrator</option>
            </select>
          </Field>
          {error && <p className="error">{error}</p>}
          <button className="btn primary" disabled={busy}>
            Create member
          </button>
        </form>
      </section>
      <section className="panel padded">
        <h2>Workspace members</h2>
        {users.map((u) => (
          <div className="member" key={u.username}>
            <span className="avatar">{u.display_name.slice(0, 1)}</span>
            <div>
              <strong>{u.display_name}</strong>
              <small>{u.username}</small>
            </div>
            <span className="badge green">{u.role}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
