/**
 * Test data builders and a route-based fetch mock.
 *
 * `mockFetch` keys routes as "METHOD /path" (without the /api prefix). A route
 * value may be a plain JSON body, a `Response`, or a function returning either.
 */
import { vi } from "vitest";
import type {
  LedgerEntry,
  RunPayload,
  RunSummary,
  ScopeTotals,
} from "../api";
import type { User, Workspace } from "../workspace";

export const user: User = {
  username: "ana",
  display_name: "Ana Lyst",
  role: "analyst",
  csrf: "csrf-token",
};

export const totals: ScopeTotals = {
  scope1: "12.5",
  scope2_location: "30.25",
  scope2_market: "0",
  scope3: "7.25",
  scope3_by_category: { "6": "7.25" },
  by_activity: {
    electricity_grid: "30.25",
    natural_gas_stationary: "12.5",
    air_travel_long_haul: "7.25",
  },
  total_location_based: "50",
  lines_total: 3,
  lines_calculated: 3,
  lines_unmatched: 0,
  lines_unclassified: 0,
  lines_no_quantity: 0,
  lines_excluded: 0,
  lines_unit_error: 0,
  lines_duplicate: 0,
  spend_based_t: "0",
};

export function entry(
  id: string,
  over: Partial<{
    description: string;
    status: LedgerEntry["status"];
    t: string;
    scope: 1 | 2 | 3 | null;
    source: string;
  }> = {},
): LedgerEntry {
  const status = over.status ?? "calculated";
  return {
    item: {
      document_id: null,
      source_sha256: null,
      line_id: id,
      source_file: over.source ?? "erp.csv",
      source_ref: "row 2",
      date: "2025-03-01",
      period: "FY2025",
      vendor: null,
      description: over.description ?? `Activity ${id}`,
      gl_code: null,
      quantity: "100",
      unit: "kWh",
      region: "GB",
      spend: null,
      currency: null,
      raw_text: null,
      redactions: [],
    },
    classification: {
      scope: over.scope === undefined ? 2 : over.scope,
      scope3_category: null,
      activity_type: "electricity_grid",
      method: "rule",
      confidence: "0.95",
      reason: "Rule R01_ELEC",
      rule_id: "R01_ELEC",
    },
    factor_match: {
      matched: status === "calculated",
      factor: null,
      match_quality: status === "calculated" ? "exact" : "none",
      requested: {},
      reason: "",
    },
    calculation:
      status === "calculated"
        ? {
            quantity_input: "100",
            unit_input: "kWh",
            conversion: null,
            quantity_converted: "100",
            unit_converted: "kWh",
            factor_value: "0.2",
            factor_unit: "kg CO2e/kWh",
            kg_co2e: "20",
            t_co2e: over.t ?? "0.02",
            gas_breakdown: null,
            formula: "100 kWh x 0.2 = 20 kg",
            rounding: "6 dp",
            engine: "decimal",
          }
        : null,
    status,
    data_quality: "measured",
    duplicate_of: null,
  };
}

export function summary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    revision: 1,
    created_by: "ana",
    run_id: "run-1",
    created_at: "2025-04-01T00:00:00Z",
    org_name: "Northbridge Precision",
    reporting_period: "FY2025",
    jurisdiction: "CSRD",
    source_files: ["erp.csv"],
    totals,
    findings: [],
    report_allowed: true,
    agent_mode: "fallback",
    ...over,
  };
}

export function run(over: Partial<RunPayload> = {}): RunPayload {
  return {
    summary: summary(),
    entries: [entry("l1"), entry("l2"), entry("l3", { status: "unclassified" })],
    ...over,
  };
}

export function workspace(
  readiness: Partial<Workspace["readiness"]> = {},
): Workspace {
  return {
    documents: [{ document_id: "d1", filename: "erp.csv", sha256: "abc" }],
    sections: [],
    profile: {
      title: "CSRD",
      version: "2025",
      notice: "",
      sources: [],
      status: "draft",
    },
    readiness: {
      blockers: ["1 line needs classification"],
      content_sha256: "sha",
      ready_for_approval: false,
      approved: false,
      revision: 1,
      sections_complete: 2,
      sections_total: 6,
      integrity: { valid: true, events: 4, head: "h" },
      market: { complete: false, scope2_market_t: null, gaps: [] },
      ...readiness,
    },
    scenarios: [],
    suppliers: [],
    instruments: [],
    reviews: [],
  };
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export const failure = (detail: string, status = 400) =>
  json({ detail }, status);

type Handler = (init?: RequestInit) => unknown;
type Route = unknown | Response | Handler;

export function mockFetch(routes: Record<string, Route>) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const path = String(input).replace(/^\/api/, "");
      const key = `${(init?.method ?? "GET").toUpperCase()} ${path}`;
      if (!(key in routes)) return failure(`no route for ${key}`, 404);
      const route = routes[key];
      const value =
        typeof route === "function" ? await (route as Handler)(init) : route;
      return value instanceof Response ? value : json(value);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
