import { lazy, Suspense, useEffect, type FormEvent } from "react";
import { useShallow } from "zustand/react/shallow";
import { NAV, useStore } from "./store";
import {
  EntryTable,
  Field,
  Icon,
  Login,
  Modal,
} from "./components/WorkspaceUI";
import Overview from "./components/Overview";
const ReviewEditor = lazy(() => import("./components/ReviewEditor"));
const Panels = () => import("./components/CompliancePanels");
const DisclosurePanel = lazy(() =>
  Panels().then((m) => ({ default: m.DisclosurePanel })),
);
const EvidencePanel = lazy(() =>
  Panels().then((m) => ({ default: m.EvidencePanel })),
);
const ScenarioPanel = lazy(() =>
  Panels().then((m) => ({ default: m.ScenarioPanel })),
);
const SupplierPanel = lazy(() =>
  Panels().then((m) => ({ default: m.SupplierPanel })),
);
const MarketPanel = lazy(() =>
  Panels().then((m) => ({ default: m.MarketPanel })),
);
const FactorPanel = lazy(() =>
  Panels().then((m) => ({ default: m.FactorPanel })),
);
const AuditPanel = lazy(() =>
  Panels().then((m) => ({ default: m.AuditPanel })),
);
const TeamPanel = lazy(() => Panels().then((m) => ({ default: m.TeamPanel })));
const descriptions: Record<string, string> = {
  "Activity ledger": "Every activity, connected to its source and calculation.",
  "Review queue":
    "Close data gaps. Record the judgement behind every decision.",
  Disclosures: "A considered disclosure starts with traceable evidence.",
  "Reduction plans": "Turn your inventory into an informed next step.",
  Suppliers: "Bring missing Scope 3 evidence into the conversation.",
  "Factor library":
    "Official sources. Explicit versions. Reproducible calculations.",
  "Audit trail": "Follow the evidence from source document to sign-off.",
  Team: "The right access. Independent accountability.",
};
export default function App() {
  const {
    user,
    checking,
    loadingInventory,
    runs,
    run,
    workspace,
    catalog,
    page,
    error,
    busy,
    upload,
    selected,
    menu,
  } = useStore(
    useShallow((s) => ({
      user: s.user,
      checking: s.checking,
      loadingInventory: s.loadingInventory,
      runs: s.runs,
      run: s.run,
      workspace: s.workspace,
      catalog: s.catalog,
      page: s.page,
      error: s.error,
      busy: s.busy,
      upload: s.upload,
      selected: s.selected,
      menu: s.menu,
    })),
  );
  const {
    bootstrap,
    signIn,
    loadInventories,
    open,
    reload,
    importFiles,
    demo,
    logout,
    navigate,
    setError,
    toggleMenu,
    showUpload,
    select,
  } = useStore(
    useShallow((s) => ({
      bootstrap: s.bootstrap,
      signIn: s.signIn,
      loadInventories: s.loadInventories,
      open: s.open,
      reload: s.reload,
      importFiles: s.importFiles,
      demo: s.demo,
      logout: s.logout,
      navigate: s.navigate,
      setError: s.setError,
      toggleMenu: s.toggleMenu,
      showUpload: s.showUpload,
      select: s.select,
    })),
  );
  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);
  useEffect(() => {
    if (user) void loadInventories();
  }, [user, loadInventories]);
  function submitImport(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void importFiles(new FormData(e.currentTarget));
  }
  if (checking)
    return (
      <div className="boot">
        <Icon />
        <p>Opening your workspace…</p>
      </div>
    );
  if (!user) return <Login onLogin={signIn} />;
  const canEdit = ["admin", "analyst"].includes(user.role);
  // Only rendered inside the run/workspace non-null branch below.
  const panelProps = { run: run!, workspace: workspace!, user, reload };
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menu ? "mobile-open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("Overview");
          }}
        >
          <Icon /> Carbon Copilot
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          {NAV.map((name) => (
            <button
              key={name}
              className={page === name ? "active" : ""}
              onClick={() => navigate(name)}
            >
              <Icon name={name} />
              <span>{name}</span>
              {name === "Review queue" && workspace && (
                <span className="nav-count">
                  {workspace.readiness.blockers.length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="workspace-note">
            <span className="live-dot" /> Evidence-led accounting
            <small>Human-reviewed. Tool-calculated.</small>
          </div>
          {user.role === "admin" && (
            <button className="team-link" onClick={() => navigate("Team")}>
              Manage workspace members ↗
            </button>
          )}
          <div className="user">
            <span className="avatar">
              {user.display_name.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{user.display_name}</strong>
              <small>{user.role}</small>
            </div>
            <button
              onClick={() => void logout()}
              title="Sign out"
              aria-label="Sign out"
            >
              ↪
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button menu-toggle"
            onClick={toggleMenu}
            aria-label="Toggle navigation"
          >
            ☰
          </button>
          <div className="breadcrumb">
            Workspace <span>/</span> <strong>{page}</strong>
          </div>
          <div className="actions">
            <select
              aria-label="Select inventory"
              value={run?.summary.run_id || ""}
              onChange={(e) => void open(e.target.value)}
            >
              <option value="" disabled>
                Select an inventory
              </option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.reporting_period} · {r.org_name} · {r.run_id.slice(-6)}
                </option>
              ))}
            </select>
            {canEdit && (
              <button className="btn primary" onClick={() => showUpload(true)}>
                ＋ <span>Import activity</span>
              </button>
            )}
          </div>
        </header>
        <main className="content" aria-busy={busy}>
          <div className="page-heading">
            <div>
              <h1>
                {page === "Overview"
                  ? "Your footprint, in focus."
                  : page === "Team"
                    ? "Your workspace team."
                    : page}
              </h1>
              <p>
                {page === "Overview"
                  ? "A clear view of emissions. An evidence trail behind every number."
                  : descriptions[page]}
              </p>
            </div>
            {run && (
              <span
                className={`inventory-state ${workspace?.readiness.approved ? "green" : ""}`}
              >
                <span className="status-dot" />
                {workspace?.readiness.approved
                  ? "Reviewed dossier"
                  : "Draft inventory"}
              </span>
            )}
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
              <button className="text-button" onClick={() => setError("")}>
                Dismiss
              </button>
            </div>
          )}
          {busy && (
            <div className="loading-line" role="status">
              Updating workspace…
            </div>
          )}
          <Suspense
            key={run?.summary.run_id || "empty"}
            fallback={<div className="empty">Loading workspace tools…</div>}
          >
            {page === "Team" && user.role === "admin" ? (
              <TeamPanel />
            ) : page === "Factor library" ? (
              <FactorPanel catalog={catalog} />
            ) : loadingInventory ? (
              <div className="empty" role="status">
                Loading your inventories…
              </div>
            ) : !run || !workspace ? (
              <section className="welcome panel">
                <Icon />
                <h2>Your evidence trail starts here.</h2>
                <p>
                  Import utility bills, ERP spreadsheets or travel logs to
                  create a traceable emissions inventory.
                </p>
                {canEdit && (
                  <div className="actions">
                    <button
                      className="btn primary"
                      onClick={() => showUpload(true)}
                    >
                      Import your first activity
                    </button>
                    <button
                      className="btn"
                      disabled={busy}
                      onClick={() => void demo()}
                    >
                      Explore sample inventory
                    </button>
                  </div>
                )}
                <small>
                  CSV · Excel · PDF with optional OCR · Source documents
                  retained encrypted
                </small>
              </section>
            ) : (
              <>
                {page === "Overview" && (
                  <Overview
                    run={run}
                    workspace={workspace}
                    navigate={navigate}
                    select={select}
                  />
                )}
                {page === "Activity ledger" && (
                  <>
                    <EntryTable entries={run.entries} select={select} />
                    <EvidencePanel {...panelProps} />
                  </>
                )}
                {page === "Review queue" && (
                  <>
                    <section className="panel padded">
                      <div className="panel-head">
                        <h2>Items requiring attention</h2>
                        <span className="count">
                          {workspace.readiness.blockers.length}
                        </span>
                      </div>
                      {workspace.readiness.blockers.length ? (
                        <ul className="blockers">
                          {workspace.readiness.blockers.map((b, i) => (
                            <li key={i}>
                              <span className="status-dot" />
                              {b}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p>
                          Preparation checks are clear. Open Disclosures for
                          independent sign-off.
                        </p>
                      )}
                      <button
                        className="btn"
                        onClick={() => navigate("Disclosures")}
                      >
                        Prepare disclosure sections →
                      </button>
                    </section>
                    <EntryTable entries={run.entries} select={select} />
                    <MarketPanel {...panelProps} />
                  </>
                )}
                {page === "Disclosures" && (
                  <>
                    <DisclosurePanel {...panelProps} />
                    <EvidencePanel {...panelProps} />
                  </>
                )}
                {page === "Reduction plans" && (
                  <ScenarioPanel {...panelProps} />
                )}
                {page === "Suppliers" && <SupplierPanel {...panelProps} />}
                {page === "Audit trail" && <AuditPanel {...panelProps} />}
              </>
            )}
          </Suspense>
          <footer>
            Carbon Copilot{" "}
            <span>
              Disclosure preparation platform · Legal applicability and
              assurance require professional review.
            </span>
          </footer>
        </main>
      </div>
      {upload && (
        <Modal
          title="Import activity"
          close={() => {
            if (!busy) showUpload(false);
          }}
        >
          <p className="muted">
            Create a separate inventory for each reporting period. Original
            documents are retained as encrypted audit evidence.
          </p>
          <form onSubmit={submitImport}>
            <Field label="Organization">
              <input
                name="org_name"
                required
                maxLength={200}
                placeholder="Your organization"
              />
            </Field>
            <div className="form-grid">
              <Field label="Disclosure framework">
                <select name="jurisdiction">
                  <option value="CSRD">CSRD / ESRS preparation</option>
                  <option value="SEC">
                    SEC climate — stayed-rule reference
                  </option>
                </select>
              </Field>
              <Field label="Default region (optional)">
                <input name="default_region" placeholder="GB, US, CAMX…" />
              </Field>
            </div>
            <label className="drop-zone">
              <span>＋</span>
              <strong>Choose activity files</strong>
              <small>
                CSV, XLSX, XLS or PDF · 20 MB per file · 50 MB total
              </small>
              <input
                name="files"
                type="file"
                accept=".csv,.xlsx,.xls,.pdf"
                multiple
                required
              />
            </label>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button className="btn primary" disabled={busy}>
              {busy ? "Ingesting & calculating…" : "Create inventory →"}
            </button>
            <p className="muted small">
              Rules run first. Unresolved redacted activity data may be sent to
              your configured Lyzr agent.
            </p>
          </form>
        </Modal>
      )}
      {selected && run && workspace && (
        <Suspense fallback={null}>
          <ReviewEditor
            entry={selected}
            run={run}
            workspace={workspace}
            catalog={catalog}
            close={() => select(null)}
            saved={reload}
            canEdit={user.role !== "auditor"}
          />
        </Suspense>
      )}
    </div>
  );
}
