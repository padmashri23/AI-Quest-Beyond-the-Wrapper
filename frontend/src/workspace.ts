import type { FactorRow } from "./api";

export interface User {
  username: string;
  display_name: string;
  role: string;
  csrf: string;
}
export interface Document {
  document_id: string;
  filename: string;
  sha256: string;
}
export interface Section {
  id: string;
  text: string;
  evidence_ids: string[];
  author: string;
}
export interface Profile {
  title: string;
  version: string;
  notice: string;
  sources: string[];
  status: string;
}
export interface Workspace {
  documents: Document[];
  sections: Section[];
  profile: Profile;
  readiness: {
    blockers: string[];
    content_sha256: string;
    ready_for_approval: boolean;
    approved: boolean;
    revision: number;
    sections_complete: number;
    sections_total: number;
    integrity: { valid: boolean; events: number; head: string };
    market: {
      complete: boolean;
      scope2_market_t: string | null;
      gaps: { line_id: string; unallocated_kwh: string }[];
    };
  };
  scenarios: {
    id: string;
    name: string;
    currency: string;
    baseline_revision: number;
    avoided_t: string;
    levers: {
      name: string;
      roi_percent: string | null;
      npv: string;
      avoided_t_per_year: string;
      payback_years: string | null;
    }[];
  }[];
  suppliers: {
    id: string;
    supplier: string;
    status: string;
    due_date: string;
    body: string;
    contact_email: string;
    subject: string;
    content_sha256: string;
    approved: boolean;
    approved_by: string | null;
    delivery_status: string;
  }[];
  instruments: {
    id: string;
    status?: string;
    line_id: string;
    serial_number: string;
    quantity_kwh: string;
    factor_kg_per_kwh: string;
  }[];
  reviews: {
    id: string;
    actor: string;
    rationale: string;
    entry_sha256: string;
  }[];
}
export interface Catalog {
  rows: FactorRow[];
  activity_types: Record<string, { label: string; scope: number | null }>;
}
export interface Regulations {
  sections: { id: string; title: string; guidance: string }[];
}
let csrf = "";
export function session(user: User | null) {
  csrf = user?.csrf || "";
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : JSON.stringify(error.detail),
    );
  }
  return response.json() as Promise<T>;
}
export const send = <T>(path: string, body: unknown, method = "POST") =>
  request<T>(path, { method, body: JSON.stringify(body) });
export const number = (
  value: string | number | null | undefined,
  digits = 2,
) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
