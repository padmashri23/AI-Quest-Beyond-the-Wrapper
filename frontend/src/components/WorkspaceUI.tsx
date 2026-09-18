import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type FormEvent,
} from "react";
import type { LedgerEntry } from "../api";
import {
  number,
  request,
  send,
  session,
  type Document,
  type User,
} from "../workspace";

export function Icon({ name = "leaf" }: { name?: string }) {
  const paths: Record<string, ReactNode> = {
    leaf: (
      <>
        <path d="M20 3C8 2 3 7 4 14c1 7 11 7 14 0 2-4 2-8 2-11Z" />
        <path d="M3 22 15 9M8 17v-6m0 6h6" />
      </>
    ),
    Overview: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    "Activity ledger": (
      <>
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <path d="M8 8h8M8 12h8M8 16h5" />
      </>
    ),
    "Review queue": (
      <>
        <path d="m9 12 2 2 4-5" />
        <circle cx="12" cy="12" r="9" />
      </>
    ),
    Disclosures: (
      <>
        <path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h8" />
      </>
    ),
    "Reduction plans": (
      <>
        <path d="M4 4v16h17M7 15l5-5 4 3 5-7M17 6h4v4" />
      </>
    ),
    Suppliers: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3 21v-3a6 6 0 0 1 12 0v3M17 5a3 3 0 0 1 0 6m1 4a5 5 0 0 1 3 5" />
      </>
    ),
    "Factor library": (
      <>
        <path d="M4 5h6v14H4zM13 5h6v14h-6zM4 9h6M13 9h6" />
      </>
    ),
    "Audit trail": (
      <>
        <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6" />
      </>
    ),
  };
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths["Suppliers"]}
    </svg>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  return (
    <dialog ref={dialog} onCancel={close} className="modal">
      <div className="panel-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close dialog"
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Evidence({ documents }: { documents: Document[] }) {
  return (
    <Field label="Supporting evidence">
      <select name="evidence" required>
        <option value="">Select a retained document</option>
        {documents.map((d) => (
          <option key={d.document_id} value={d.document_id}>
            {d.filename}
          </option>
        ))}
      </select>
    </Field>
  );
}
export function EntryTable({
  entries,
  select,
  compact = false,
}: {
  entries: LedgerEntry[];
  select: (e: LedgerEntry) => void;
  compact?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const filtered = entries.filter((e) =>
    `${e.item.description} ${e.item.source_file} ${e.status}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  const [limit, setLimit] = useState(30);
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          {compact ? "Recent activity" : "Activity ledger"}{" "}
          <span className="count">{entries.length}</span>
        </h2>
        {!compact && (
          <input
            aria-label="Search activities"
            className="search"
            placeholder="Search activity or source…"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setLimit(30);
            }}
          />
        )}
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Activity / source</th>
              <th>Scope</th>
              <th>
                Emissions <small>tCO₂e</small>
              </th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, compact ? 5 : limit).map((e) => (
              <tr key={e.item.line_id}>
                <td>
                  <strong>{e.item.description || "Untitled activity"}</strong>
                  <small>
                    {e.item.source_file} · {e.item.source_ref}
                  </small>
                </td>
                <td>
                  {e.classification.scope
                    ? `Scope ${e.classification.scope}`
                    : "Unclassified"}
                </td>
                <td className="numeric">{number(e.calculation?.t_co2e)}</td>
                <td>
                  <span
                    className={`badge ${e.status === "calculated" ? "green" : "amber"}`}
                  >
                    {e.status.replaceAll("_", " ")}
                  </span>
                </td>
                <td>
                  <button
                    className="text-button"
                    onClick={() => select(e)}
                    aria-label={`Review ${e.item.description}`}
                  >
                    View ↗
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!filtered.length && (
        <div className="empty">No activities match your search.</div>
      )}
      {!compact && filtered.length > limit && (
        <button className="btn quiet" onClick={() => setLimit(limit + 30)}>
          Show more activities
        </button>
      )}
    </section>
  );
}
export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [initialized, setInitialized] = useState<boolean | null>(null);
  const [local, setLocal] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    request<{ initialized: boolean; local_setup_allowed: boolean }>(
      "/auth/status",
    )
      .then((s) => {
        setInitialized(s.initialized);
        setLocal(s.local_setup_allowed);
      })
      .catch((e) => setError(e.message));
  }, []);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (!initialized) await send("/auth/setup", data);
      const user = await send<User>("/auth/login", data);
      session(user);
      onLogin(user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <aside>
        <div className="brand">
          <Icon /> Carbon Copilot
        </div>
        <div>
          <h1>
            Clarity for your
            <br />
            carbon accounts.
          </h1>
          <p>
            From source evidence to a reviewed disclosure.
            <br />
            Every activity. Every factor. Every decision.
          </p>
        </div>
        <small>Deterministic accounting · Human accountability</small>
      </aside>
      <main>
        <form onSubmit={submit}>
          <Icon />
          <h1>
            {initialized === false ? "Create your workspace." : "Welcome back."}
          </h1>
          <p className="muted">
            {initialized === false
              ? "Set up the first administrator for this local workspace."
              : "Sign in to your sustainability workspace."}
          </p>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {initialized === false && !local ? (
            <p>
              Use the administrator CLI to provision this production workspace.
            </p>
          ) : (
            <>
              <Field label="Username">
                <input
                  name="username"
                  autoComplete="username"
                  required
                  minLength={3}
                />
              </Field>
              {initialized === false && (
                <Field label="Display name">
                  <input name="display_name" required />
                </Field>
              )}
              <Field label="Password">
                <input
                  name="password"
                  type="password"
                  autoComplete={
                    initialized ? "current-password" : "new-password"
                  }
                  minLength={12}
                  required
                />
              </Field>
              <small className="muted">
                At least 12 characters. Sessions expire after 8 hours.
              </small>
              <button
                className="btn primary"
                disabled={busy || initialized === null}
              >
                {busy
                  ? "Connecting…"
                  : initialized
                    ? "Sign in →"
                    : "Create workspace →"}
              </button>
            </>
          )}
        </form>
      </main>
    </div>
  );
}
