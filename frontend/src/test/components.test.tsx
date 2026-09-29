import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Overview from "../components/Overview";
import { EntryTable, Login } from "../components/WorkspaceUI";
import { number } from "../workspace";
import { entry, failure, mockFetch, run, user, workspace } from "./fixtures";

const many = Array.from({ length: 35 }, (_, i) =>
  entry(`l${i}`, {
    description: `Activity ${i}`,
    source: i % 2 ? "erp.csv" : "bill.pdf",
  }),
);

describe("EntryTable", () => {
  it("pages long ledgers thirty rows at a time", () => {
    render(<EntryTable entries={many} select={() => {}} />);
    expect(screen.getAllByRole("row")).toHaveLength(31); // header + 30
    fireEvent.click(screen.getByText("Show more activities"));
    expect(screen.getAllByRole("row")).toHaveLength(36);
    expect(screen.queryByText("Show more activities")).toBeNull();
  });

  it("filters by description, source file and status", () => {
    render(<EntryTable entries={many} select={() => {}} />);
    const search = screen.getByLabelText("Search activities");
    fireEvent.change(search, { target: { value: "erp.csv" } });
    expect(screen.getAllByRole("row")).toHaveLength(18); // header + 17 odd rows
    fireEvent.change(search, { target: { value: "CALCULATED" } });
    expect(screen.getAllByRole("row")).toHaveLength(31);
    fireEvent.change(search, { target: { value: "nothing here" } });
    expect(screen.getByText("No activities match your search.")).toBeInTheDocument();
  });

  it("hands the selected entry back and shows five rows when compact", () => {
    const select = vi.fn();
    render(<EntryTable entries={many} select={select} compact />);
    expect(screen.getByRole("heading", { name: /Recent activity/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search activities")).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(6);
    fireEvent.click(screen.getByLabelText("Review Activity 3"));
    expect(select).toHaveBeenCalledWith(many[3]);
  });

  it("labels unclassified lines and untitled activities", () => {
    render(
      <EntryTable
        entries={[entry("u", { description: "", status: "unclassified", scope: null })]}
        select={() => {}}
      />,
    );
    expect(screen.getByText("Untitled activity")).toBeInTheDocument();
    expect(screen.getByText("Unclassified")).toBeInTheDocument();
    expect(screen.getByText("unclassified")).toHaveClass("amber");
  });
});

describe("Overview", () => {
  it("shows scope totals, the largest sources and the review state", () => {
    const navigate = vi.fn();
    render(
      <Overview run={run()} workspace={workspace()} navigate={navigate} select={() => {}} />,
    );
    expect(screen.getByText("Total footprint")).toBeInTheDocument();
    expect(screen.getByText(number("50"))).toBeInTheDocument();
    // Scope 1 appears twice: as a KPI tile and as the natural gas source bar.
    expect(screen.getAllByText(number("12.5"))).toHaveLength(2);
    const bars = screen.getAllByTitle(/.+/);
    expect(bars[0]).toHaveTextContent("Grid electricity");
    expect(screen.getByRole("heading", { name: "Ready for review" })).toBeInTheDocument();
    expect(screen.getByText("2 of 6 sections")).toBeInTheDocument();
    expect(screen.getByText(/Deterministic fallback mode/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Open review queue/ }));
    expect(navigate).toHaveBeenCalledWith("Review queue");
  });

  it("reflects readiness and approval", () => {
    const { rerender } = render(
      <Overview
        run={run()}
        workspace={workspace({ ready_for_approval: true, blockers: [] })}
        navigate={() => {}}
        select={() => {}}
      />,
    );
    expect(screen.getByRole("heading", { name: "Ready for sign-off" })).toBeInTheDocument();
    rerender(
      <Overview
        run={run({ summary: { ...run().summary, agent_mode: "lyzr" } })}
        workspace={workspace({ approved: true, blockers: [] })}
        navigate={() => {}}
        select={() => {}}
      />,
    );
    expect(screen.getByRole("heading", { name: "Reviewed & approved" })).toBeInTheDocument();
    expect(screen.getByText("Current version approved")).toBeInTheDocument();
    expect(screen.getByText(/Lyzr-assisted classification/)).toBeInTheDocument();
  });
});

describe("Login", () => {
  it("creates the workspace on first run and then signs in", async () => {
    const fetchMock = mockFetch({
      "GET /auth/status": { initialized: false, local_setup_allowed: true },
      "POST /auth/setup": { ok: true },
      "POST /auth/login": user,
    });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    expect(
      await screen.findByRole("heading", { name: "Create your workspace." }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "ana" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Ana" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "twelve-character-secret" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Create workspace/ }).closest("form")!);
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(user));
    const posts = fetchMock.mock.calls
      .filter(([, init]) => init?.method === "POST")
      .map(([url]) => String(url));
    expect(posts).toEqual(["/api/auth/setup", "/api/auth/login"]);
  });

  it("signs in to an initialised workspace and surfaces failures", async () => {
    mockFetch({
      "GET /auth/status": { initialized: true, local_setup_allowed: true },
      "POST /auth/login": failure("Invalid credentials", 401),
    });
    const onLogin = vi.fn();
    render(<Login onLogin={onLogin} />);
    expect(await screen.findByRole("heading", { name: "Welcome back." })).toBeInTheDocument();
    expect(screen.queryByLabelText("Display name")).toBeNull();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "ana" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "twelve-character-secret" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Sign in/ }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
    expect(onLogin).not.toHaveBeenCalled();
  });

  it("points production deployments to the administrator CLI", async () => {
    mockFetch({
      "GET /auth/status": { initialized: false, local_setup_allowed: false },
    });
    render(<Login onLogin={() => {}} />);
    expect(await screen.findByText(/administrator CLI/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Username")).toBeNull();
  });
});
