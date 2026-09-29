import { describe, expect, it } from "vitest";
import {
  ACTIVITY_LABELS,
  SCOPE3_NAMES,
  STATUS_LABELS,
  api,
  fmtT,
} from "../api";
import { failure, mockFetch } from "./fixtures";

describe("fmtT", () => {
  it("handles empty, numeric and non-numeric input", () => {
    expect(fmtT(null)).toBe("—");
    expect(fmtT(undefined)).toBe("—");
    expect(fmtT("")).toBe("—");
    expect(fmtT("n/a")).toBe("n/a");
    expect(fmtT(1)).toBe(
      (1).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    );
    expect(fmtT("2.25", 1)).toBe(
      (2.25).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    );
  });
});

describe("labels", () => {
  it("cover every ledger status and the common activities", () => {
    expect(Object.keys(STATUS_LABELS).sort()).toEqual([
      "calculated",
      "duplicate",
      "excluded",
      "no_quantity",
      "unclassified",
      "unit_error",
      "unmatched_factor",
    ]);
    expect(SCOPE3_NAMES["6"]).toBe("Business travel");
    expect(ACTIVITY_LABELS.electricity_grid).toBe("Grid electricity");
  });
});

describe("api client", () => {
  it("builds upload form data and report urls", async () => {
    const fetchMock = mockFetch({ "POST /runs": { summary: {}, entries: [] } });
    const file = new File(["a,b"], "a.csv", { type: "text/csv" });
    await api.upload([file], "Acme", "CSRD", "GB");
    const body = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(body.get("org_name")).toBe("Acme");
    expect(body.get("jurisdiction")).toBe("CSRD");
    expect(body.get("default_region")).toBe("GB");
    expect(body.getAll("files")).toHaveLength(1);
    expect(api.reportUrl("r1", "SEC")).toBe("/api/runs/r1/report?jurisdiction=SEC&format=md");
  });

  it("omits the region when none is given", async () => {
    const fetchMock = mockFetch({ "POST /runs": { summary: {}, entries: [] } });
    await api.upload([], "Acme", "SEC", "");
    const body = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(body.has("default_region")).toBe(false);
  });

  it("throws the detail message on failure", async () => {
    mockFetch({ "GET /runs/r1": failure("run not found", 404) });
    await expect(api.getRun("r1")).rejects.toThrow("run not found");
  });

  it("returns markdown text for reports and raises on failure", async () => {
    mockFetch({
      "GET /runs/r1/report?jurisdiction=SEC&format=md": new Response("# Report", { status: 200 }),
      "GET /runs/r2/report?jurisdiction=SEC&format=md&regenerate=true": new Response("nope", { status: 405 }),
    });
    await expect(api.reportMarkdown("r1", "SEC")).resolves.toBe("# Report");
    await expect(api.reportMarkdown("r2", "SEC", true)).rejects.toThrow("nope");
  });

  it("reads health and the run list", async () => {
    const health = { ok: true, agent_mode: "fallback" };
    mockFetch({ "GET /health": health, "GET /runs": [] });
    await expect(api.health()).resolves.toEqual(health);
    await expect(api.listRuns()).resolves.toEqual([]);
  });
});
