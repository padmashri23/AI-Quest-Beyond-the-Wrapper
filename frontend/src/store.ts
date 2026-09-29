/**
 * Shell state for the dashboard, managed with Zustand.
 *
 * Everything the application frame needs to know (who is signed in, which
 * inventories exist, which one is open, which page is showing, whether a
 * request is in flight) lives here. Components subscribe to the slices they
 * render with `useStore(selector)` and call the actions below; the actions are
 * the only code that fetches shell-level data, so loading, error handling and
 * race protection are written once. Form-local state (draft text, a filter
 * box) stays inside the component that owns it.
 */
import { create } from "zustand";
import type { LedgerEntry, RunPayload, RunSummary } from "./api";
import {
  request,
  session,
  type Catalog,
  type User,
  type Workspace,
} from "./workspace";

export const NAV = [
  "Overview",
  "Activity ledger",
  "Review queue",
  "Disclosures",
  "Reduction plans",
  "Suppliers",
  "Factor library",
  "Audit trail",
] as const;

export interface ShellState {
  /** Signed-in user, or null when the login screen should show. */
  user: User | null;
  /** True until the initial session check has finished. */
  checking: boolean;
  /** True while the inventory list and factor catalogue are loading. */
  loadingInventory: boolean;
  runs: RunSummary[];
  run: RunPayload | null;
  workspace: Workspace | null;
  catalog: Catalog | null;
  page: string;
  error: string;
  /** True while a request that changes the visible inventory is in flight. */
  busy: boolean;
  upload: boolean;
  selected: LedgerEntry | null;
  menu: boolean;
}

export interface ShellActions {
  /** Restore an existing cookie session, if any. Always clears `checking`. */
  bootstrap: () => Promise<void>;
  signIn: (user: User) => void;
  /** Load the inventory list and factor catalogue, then open the newest run. */
  loadInventories: () => Promise<void>;
  /** Open one inventory. A stale response never overwrites a newer selection. */
  open: (runId: string) => Promise<void>;
  /** Re-fetch the open inventory and the list after a panel saved something. */
  reload: () => Promise<void>;
  importFiles: (form: FormData) => Promise<void>;
  demo: () => Promise<void>;
  logout: () => Promise<void>;
  navigate: (page: string) => void;
  setError: (message: string) => void;
  toggleMenu: () => void;
  showUpload: (open: boolean) => void;
  select: (entry: LedgerEntry | null) => void;
  /** Forget every inventory and the user; used after sign-out. */
  reset: () => void;
}

export const initialState: ShellState = {
  user: null,
  checking: true,
  loadingInventory: true,
  runs: [],
  run: null,
  workspace: null,
  catalog: null,
  page: "Overview",
  error: "",
  busy: false,
  upload: false,
  selected: null,
  menu: false,
};

const describe = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

export const useStore = create<ShellState & ShellActions>()((set, get) => {
  // Monotonic ticket: only the most recent open() may write its result.
  let ticket = 0;
  const currentUser = () => get().user?.username ?? null;

  return {
    ...initialState,

    async bootstrap() {
      try {
        const user = await request<User>("/auth/me");
        session(user);
        set({ user });
      } catch {
        // No valid session: the login screen is shown.
      } finally {
        set({ checking: false });
      }
    },

    signIn(user) {
      session(user);
      set({ user, checking: false });
    },

    async loadInventories() {
      const owner = currentUser();
      set({ loadingInventory: true, error: "" });
      try {
        const [runs, catalog] = await Promise.all([
          request<RunSummary[]>("/runs"),
          request<Catalog>("/factors"),
        ]);
        if (currentUser() !== owner) return; // signed out while loading
        set({ runs, catalog });
        if (runs[0]) await get().open(runs[0].run_id);
      } catch (error) {
        if (currentUser() === owner) set({ error: describe(error) });
      } finally {
        if (currentUser() === owner) set({ loadingInventory: false });
      }
    },

    async open(runId) {
      const mine = ++ticket;
      set({ busy: true, error: "" });
      try {
        const [run, workspace] = await Promise.all([
          request<RunPayload>(`/runs/${runId}`),
          request<Workspace>(`/runs/${runId}/workspace`),
        ]);
        if (mine === ticket) set({ run, workspace });
      } catch (error) {
        if (mine === ticket) set({ error: describe(error) });
      } finally {
        if (mine === ticket) set({ busy: false });
      }
    },

    async reload() {
      const { run, open } = get();
      if (run) await open(run.summary.run_id);
      set({ runs: await request<RunSummary[]>("/runs") });
    },

    async importFiles(form) {
      set({ busy: true, error: "" });
      try {
        const created = await request<RunPayload>("/runs", {
          method: "POST",
          body: form,
        });
        set({ runs: await request<RunSummary[]>("/runs") });
        await get().open(created.summary.run_id);
        set({ upload: false, page: "Overview" });
      } catch (error) {
        set({ error: describe(error) });
      } finally {
        set({ busy: false });
      }
    },

    async demo() {
      set({ busy: true, error: "" });
      try {
        const created = await request<RunPayload>("/demo", { method: "POST" });
        set({ runs: await request<RunSummary[]>("/runs") });
        await get().open(created.summary.run_id);
      } catch (error) {
        set({ error: describe(error) });
      } finally {
        set({ busy: false });
      }
    },

    async logout() {
      try {
        await request("/auth/logout", { method: "POST" });
        session(null);
        get().reset();
      } catch (error) {
        set({ error: describe(error) });
      }
    },

    navigate(page) {
      set({ page, menu: false });
    },
    setError(error) {
      set({ error });
    },
    toggleMenu() {
      set((state) => ({ menu: !state.menu }));
    },
    showUpload(upload) {
      set({ upload });
    },
    select(selected) {
      set({ selected });
    },
    reset() {
      ticket += 1; // invalidate any open() still in flight
      set({ ...initialState, checking: false });
    },
  };
});
