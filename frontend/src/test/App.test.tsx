import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../App";
import { failure, mockFetch, run, summary, user, workspace } from "./fixtures";

const catalog = { rows: [], activity_types: {} };

describe("App", () => {
  it("shows the login screen when there is no session", async () => {
    mockFetch({
      "GET /auth/me": failure("Sign in to your workspace", 401),
      "GET /auth/status": { initialized: true, local_setup_allowed: true },
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Welcome back." })).toBeInTheDocument();
  });

  it("loads the newest inventory into the overview and navigates between pages", async () => {
    const current = summary({ run_id: "run-1", org_name: "Acme Ltd" });
    mockFetch({
      "GET /auth/me": user,
      "GET /runs": [current],
      "GET /factors": catalog,
      "GET /runs/run-1": run({ summary: current }),
      "GET /runs/run-1/workspace": workspace(),
    });
    render(<App />);
    expect(await screen.findByText("Your footprint, in focus.")).toBeInTheDocument();
    expect(await screen.findByText("Total footprint")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Select inventory" })).toHaveValue("run-1");
    expect(screen.getByText("Draft inventory")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review queue/ })).toHaveTextContent("1");
    expect(screen.getByText("Ana Lyst")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Review queue/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Review queue" })).toBeInTheDocument();
    // Page panels are lazy-loaded behind Suspense, so wait for the queue to render.
    expect(await screen.findByText("1 line needs classification")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Prepare disclosure sections/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Disclosures" })).toBeInTheDocument();
  });

  it("offers the import and sample actions when there are no inventories", async () => {
    mockFetch({ "GET /auth/me": user, "GET /runs": [], "GET /factors": catalog });
    render(<App />);
    expect(await screen.findByText("Your evidence trail starts here.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explore sample inventory" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Import your first activity" }));
    expect(screen.getByRole("heading", { name: "Import activity" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("heading", { name: "Import activity" })).toBeNull();
  });

  it("hides import actions from auditors and surfaces load errors", async () => {
    mockFetch({
      "GET /auth/me": { ...user, role: "auditor" },
      "GET /runs": failure("Ledger unavailable", 503),
      "GET /factors": catalog,
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ledger unavailable");
    expect(screen.queryByRole("button", { name: /Import/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
