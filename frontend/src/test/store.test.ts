import { describe, expect, it } from "vitest";
import { useStore } from "../store";
import {
  entry,
  failure,
  mockFetch,
  run,
  summary,
  user,
  workspace,
} from "./fixtures";

const state = () => useStore.getState();
const catalog = { rows: [], activity_types: {} };

describe("bootstrap", () => {
  it("restores the session when /auth/me succeeds", async () => {
    mockFetch({ "GET /auth/me": user });
    await state().bootstrap();
    expect(state().user).toEqual(user);
    expect(state().checking).toBe(false);
  });

  it("shows the login screen when there is no session", async () => {
    mockFetch({ "GET /auth/me": failure("Sign in to your workspace", 401) });
    await state().bootstrap();
    expect(state().user).toBeNull();
    expect(state().checking).toBe(false);
    expect(state().error).toBe("");
  });
});

describe("inventories", () => {
  it("loads runs and the catalogue then opens the newest inventory", async () => {
    const first = summary({ run_id: "run-1" });
    const second = summary({ run_id: "run-2" });
    mockFetch({
      "GET /runs": [first, second],
      "GET /factors": catalog,
      "GET /runs/run-1": run({ summary: first }),
      "GET /runs/run-1/workspace": workspace(),
    });
    state().signIn(user);
    await state().loadInventories();
    expect(state().runs).toHaveLength(2);
    expect(state().catalog).toEqual(catalog);
    expect(state().run?.summary.run_id).toBe("run-1");
    expect(state().workspace?.readiness.approved).toBe(false);
    expect(state().loadingInventory).toBe(false);
    expect(state().busy).toBe(false);
  });

  it("records the error and stops loading when the API fails", async () => {
    mockFetch({
      "GET /runs": failure("Ledger unavailable", 503),
      "GET /factors": catalog,
    });
    state().signIn(user);
    await state().loadInventories();
    expect(state().error).toBe("Ledger unavailable");
    expect(state().loadingInventory).toBe(false);
    expect(state().runs).toEqual([]);
  });

  it("ignores inventory responses that arrive after the user signed out", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    mockFetch({
      "GET /runs": async () => {
        await gate;
        return [summary()];
      },
      "GET /factors": catalog,
      "POST /auth/logout": { ok: true },
    });
    state().signIn(user);
    const loading = state().loadInventories();
    await state().logout();
    release();
    await loading;
    expect(state().user).toBeNull();
    expect(state().runs).toEqual([]);
    expect(state().error).toBe("");
  });

  it("keeps only the most recently opened inventory when responses race", async () => {
    let releaseSlow!: () => void;
    const slow = new Promise<void>((resolve) => (releaseSlow = resolve));
    mockFetch({
      "GET /runs/slow": async () => {
        await slow;
        return run({ summary: summary({ run_id: "slow" }) });
      },
      "GET /runs/slow/workspace": async () => {
        await slow;
        return workspace();
      },
      "GET /runs/fast": run({ summary: summary({ run_id: "fast" }) }),
      "GET /runs/fast/workspace": workspace(),
    });
    const stale = state().open("slow");
    const fresh = state().open("fast");
    await fresh;
    expect(state().run?.summary.run_id).toBe("fast");
    releaseSlow();
    await stale;
    expect(state().run?.summary.run_id).toBe("fast");
    expect(state().busy).toBe(false);
  });

  it("reports a failed open and clears the busy flag", async () => {
    mockFetch({
      "GET /runs/x": failure("run not found", 404),
      "GET /runs/x/workspace": workspace(),
    });
    await state().open("x");
    expect(state().error).toBe("run not found");
    expect(state().busy).toBe(false);
    expect(state().run).toBeNull();
  });
});

describe("mutations", () => {
  it("imports files, refreshes the list, opens the new run and returns to the overview", async () => {
    const created = summary({ run_id: "new" });
    const fetchMock = mockFetch({
      "POST /runs": run({ summary: created }),
      "GET /runs": [created],
      "GET /runs/new": run({ summary: created }),
      "GET /runs/new/workspace": workspace(),
    });
    useStore.setState({ upload: true, page: "Suppliers" });
    const form = new FormData();
    form.append("org_name", "Acme");
    await state().importFiles(form);
    expect(state().upload).toBe(false);
    expect(state().page).toBe("Overview");
    expect(state().run?.summary.run_id).toBe("new");
    expect(state().runs).toEqual([created]);
    expect(state().busy).toBe(false);
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[1]?.body).toBe(form);
  });

  it("surfaces an import failure and keeps the dialog open", async () => {
    mockFetch({
      "POST /runs": failure("Use CSV, Excel or PDF activity files", 422),
    });
    useStore.setState({ upload: true });
    await state().importFiles(new FormData());
    expect(state().error).toBe("Use CSV, Excel or PDF activity files");
    expect(state().upload).toBe(true);
    expect(state().busy).toBe(false);
  });

  it("runs the sample inventory", async () => {
    const created = summary({ run_id: "demo" });
    mockFetch({
      "POST /demo": run({ summary: created }),
      "GET /runs": [created],
      "GET /runs/demo": run({ summary: created }),
      "GET /runs/demo/workspace": workspace(),
    });
    await state().demo();
    expect(state().run?.summary.run_id).toBe("demo");
    expect(state().runs).toEqual([created]);
  });

  it("reload re-opens the current inventory and refreshes the list", async () => {
    const current = summary({ run_id: "run-1", revision: 2 });
    mockFetch({
      "GET /runs": [current],
      "GET /runs/run-1": run({ summary: current }),
      "GET /runs/run-1/workspace": workspace({ approved: true }),
    });
    useStore.setState({ run: run(), workspace: workspace() });
    await state().reload();
    expect(state().run?.summary.revision).toBe(2);
    expect(state().workspace?.readiness.approved).toBe(true);
    expect(state().runs).toEqual([current]);
  });

  it("logout clears the session and every inventory", async () => {
    mockFetch({ "POST /auth/logout": { ok: true } });
    state().signIn(user);
    useStore.setState({
      runs: [summary()],
      run: run(),
      workspace: workspace(),
      page: "Audit trail",
      selected: entry("x"),
    });
    await state().logout();
    expect(state()).toMatchObject({
      user: null,
      runs: [],
      run: null,
      workspace: null,
      catalog: null,
      checking: false,
      page: "Overview",
      selected: null,
    });
  });

  it("a failed logout keeps the session and reports the error", async () => {
    mockFetch({ "POST /auth/logout": failure("Network error", 500) });
    state().signIn(user);
    await state().logout();
    expect(state().user).toEqual(user);
    expect(state().error).toBe("Network error");
  });

  it("navigation closes the mobile menu and small toggles behave", () => {
    state().toggleMenu();
    expect(state().menu).toBe(true);
    state().navigate("Suppliers");
    expect(state()).toMatchObject({ page: "Suppliers", menu: false });
    state().setError("Something failed");
    expect(state().error).toBe("Something failed");
    state().setError("");
    expect(state().error).toBe("");
    state().showUpload(true);
    state().select(entry("e1"));
    expect(state().upload).toBe(true);
    expect(state().selected?.item.line_id).toBe("e1");
  });
});
