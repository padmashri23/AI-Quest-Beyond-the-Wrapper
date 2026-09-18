import { useState, type FormEvent } from "react";
import type { LedgerEntry, RunPayload } from "../api";
import { send, type Catalog, type Workspace } from "../workspace";
import { Evidence, Field, Modal } from "./WorkspaceUI";

export default function ReviewEditor({
  entry,
  run,
  workspace,
  catalog,
  close,
  saved,
  canEdit,
}: {
  entry: LedgerEntry;
  run: RunPayload;
  workspace: Workspace;
  catalog: Catalog | null;
  close: () => void;
  saved: () => Promise<void>;
  canEdit: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activity, setActivity] = useState(
    entry.classification.activity_type || "",
  );
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const f = new FormData(event.currentTarget);
    try {
      await send(
        `/runs/${run.summary.run_id}/entries/${encodeURIComponent(entry.item.line_id)}/review`,
        {
          expected_revision: run.summary.revision,
          activity_type: activity,
          quantity: f.get("quantity") || null,
          unit: f.get("unit") || null,
          region: f.get("region") || null,
          period: f.get("period"),
          decision: f.get("decision"),
          rationale: f.get("rationale"),
          evidence_ids: [f.get("evidence")],
          factor_id: f.get("factor") || null,
          scope3_category: f.get("category") ? Number(f.get("category")) : null,
        },
      );
      await saved();
      close();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const factor = entry.factor_match.factor;
  return (
    <Modal title="Activity & evidence" close={close}>
      <p className="lead">{entry.item.description}</p>
      <div className="source-block">
        <strong>{entry.item.source_file}</strong>
        <small>{entry.item.source_ref}</small>
        {entry.item.document_id && (
          <a
            href={`/api/runs/${run.summary.run_id}/evidence/${entry.item.document_id}`}
          >
            Download original source ↗
          </a>
        )}
      </div>
      <div className="formula">
        <small>DETERMINISTIC CALCULATION</small>
        <p>
          {entry.calculation?.formula ||
            "A verified calculation is not yet available."}
        </p>
      </div>
      {factor && (
        <p className="muted">
          {factor.source} · {factor.year} ·{" "}
          {factor.verified
            ? "Source-verified import"
            : "Legacy transcription — not verified"}
          <br />
          {factor.table_ref}
          <br />
          {factor.source_row}
        </p>
      )}
      <p className="muted">
        Classification: {entry.classification.reason}
        <br />
        Factor selection: {entry.factor_match.reason}
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={!canEdit || busy}>
          <div className="form-grid">
            <Field label="Activity type">
              <input
                list="review-activities"
                value={activity}
                onChange={(e) => setActivity(e.target.value)}
                required
              />
              <datalist id="review-activities">
                {Object.entries(catalog?.activity_types || {}).map(
                  ([key, value]) => (
                    <option key={key} value={key}>
                      {value.label}
                    </option>
                  ),
                )}
              </datalist>
            </Field>
            <Field label="Decision">
              <select name="decision" defaultValue="calculate">
                <option value="calculate">Correct & recalculate</option>
                <option value="confirm">Confirm existing calculation</option>
                <option value="exclude">Exclude with evidence</option>
              </select>
            </Field>
            <Field label="Quantity">
              <input
                name="quantity"
                defaultValue={entry.item.quantity || ""}
                inputMode="decimal"
              />
            </Field>
            <Field label="Unit">
              <input name="unit" defaultValue={entry.item.unit || ""} />
            </Field>
            <Field label="Region">
              <input name="region" defaultValue={entry.item.region || ""} />
            </Field>
            <Field label="Reporting period">
              <input
                name="period"
                pattern="FY20[0-9]{2}"
                defaultValue={entry.item.period || run.summary.reporting_period}
                required
              />
            </Field>
            <Field label="Scope 3 category (if applicable)">
              <input
                name="category"
                type="number"
                min="1"
                max="15"
                defaultValue={entry.classification.scope3_category || ""}
              />
            </Field>
            <Field label="Factor selection">
              <select name="factor">
                <option value="">Deterministic matching</option>
                {catalog?.rows
                  .filter((f) => f.activity_type === activity)
                  .map((f) => (
                    <option key={f.factor_id} value={f.factor_id}>
                      {f.region} · {f.year} · {f.value} / {f.unit} ·{" "}
                      {f.factor_id}
                    </option>
                  ))}
              </select>
            </Field>
          </div>
          <Field label="Decision rationale">
            <textarea
              name="rationale"
              minLength={20}
              required
              placeholder="Explain the boundary, methodology and reason for this decision."
            />
          </Field>
          <Evidence documents={workspace.documents} />
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <button className="btn primary" disabled={busy}>
            {busy ? "Saving revision…" : "Save reviewed revision"}
          </button>
        </fieldset>
        {!canEdit && <p className="muted">Your role has read-only access.</p>}
      </form>
    </Modal>
  );
}
