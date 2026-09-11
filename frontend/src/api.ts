// Typed client for the Carbon Copilot backend. All tCO2e values are decimal strings.

export type Scope = 1 | 2 | 3 | null

export interface LineItem {
  line_id: string
  source_file: string
  source_ref: string
  date: string | null
  period: string | null
  vendor: string | null
  description: string
  gl_code: string | null
  quantity: string | null
  unit: string | null
  region: string | null
  spend: string | null
  currency: string | null
  raw_text: string | null
  redactions: string[]
}

export interface Classification {
  scope: Scope
  scope3_category: number | null
  activity_type: string | null
  method: 'rule' | 'agent' | 'unclassified'
  confidence: string
  reason: string
  rule_id: string | null
}

export interface FactorRow {
  factor_id: string
  activity_type: string
  scope: 1 | 2 | 3
  scope3_category: number | null
  region: string
  year: number
  value: string
  unit: string
  components: Record<string, string> | null
  gwp_set: string | null
  method: 'activity' | 'spend'
  scope2_method: 'location' | 'market' | null
  source: string
  table_ref: string
  url: string | null
  notes: string | null
}

export interface FactorMatch {
  matched: boolean
  factor: FactorRow | null
  match_quality: 'exact' | 'region_fallback' | 'year_fallback' | 'global_fallback' | 'none'
  requested: Record<string, unknown>
  reason: string
}

export interface Calculation {
  quantity_input: string
  unit_input: string
  conversion: { from_unit: string; to_unit: string; factor: string; source: string } | null
  quantity_converted: string
  unit_converted: string
  factor_value: string
  factor_unit: string
  kg_co2e: string
  t_co2e: string
  gas_breakdown: Record<string, string> | null
  formula: string
  rounding: string
  engine: string
}

export type Status = 'calculated' | 'unmatched_factor' | 'unclassified' | 'no_quantity' | 'unit_error' | 'excluded' | 'duplicate'

export interface LedgerEntry {
  item: LineItem
  classification: Classification
  factor_match: FactorMatch
  calculation: Calculation | null
  status: Status
  data_quality: 'measured' | 'estimated_spend' | 'unknown'
  duplicate_of: string | null
}

export interface Finding {
  check_id: string
  severity: 'block' | 'warn' | 'info'
  title: string
  detail: string
  line_ids: string[]
}

export interface ScopeTotals {
  scope1: string
  scope2_location: string
  scope2_market: string
  scope3: string
  scope3_by_category: Record<string, string>
  by_activity: Record<string, string>
  total_location_based: string
  lines_total: number
  lines_calculated: number
  lines_unmatched: number
  lines_unclassified: number
  lines_no_quantity: number
  lines_excluded: number
  lines_unit_error: number
  lines_duplicate: number
  spend_based_t: string
}

export interface RunSummary {
  run_id: string
  created_at: string
  org_name: string
  reporting_period: string
  jurisdiction: string
  source_files: string[]
  totals: ScopeTotals
  findings: Finding[]
  report_allowed: boolean
  agent_mode: 'lyzr' | 'fallback'
}

export interface AgentLogEntry {
  ts: string
  agent: string
  mode: 'lyzr' | 'fallback'
  step: string
  input_summary: string
  output_summary: string
  tokens_estimate: number | null
  latency_ms: number | null
}

export interface RunPayload {
  summary: RunSummary
  entries: LedgerEntry[]
}

export interface Health {
  ok: boolean
  agent_mode: 'lyzr' | 'fallback'
  lyzr_configured: boolean
  classifier_agent: boolean
  writer_agent: boolean
  factor_tables: string[]
  factor_rows: number
}

const BASE = import.meta.env.VITE_API_BASE || ''

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch(`${BASE}/api/health`).then((r) => j<Health>(r)),
  listRuns: () => fetch(`${BASE}/api/runs`).then((r) => j<RunSummary[]>(r)),
  getRun: (id: string) => fetch(`${BASE}/api/runs/${id}`).then((r) => j<RunPayload>(r)),
  demo: (jurisdiction: string) => fetch(`${BASE}/api/demo?jurisdiction=${jurisdiction}`, { method: 'POST' }).then((r) => j<RunPayload>(r)),
  upload: (files: File[], orgName: string, jurisdiction: string, defaultRegion: string) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    fd.append('org_name', orgName)
    fd.append('jurisdiction', jurisdiction)
    if (defaultRegion) fd.append('default_region', defaultRegion)
    return fetch(`${BASE}/api/runs`, { method: 'POST', body: fd }).then((r) => j<RunPayload>(r))
  },
  agentLog: (id: string) => fetch(`${BASE}/api/runs/${id}/agent-log`).then((r) => j<AgentLogEntry[]>(r)),
  reportMarkdown: (id: string, jurisdiction: string, regenerate = false) =>
    fetch(`${BASE}/api/runs/${id}/report?jurisdiction=${jurisdiction}&format=md${regenerate ? '&regenerate=true' : ''}`).then(async (r) => {
      if (!r.ok) throw new Error(await r.text())
      return r.text()
    }),
  reportUrl: (id: string, jurisdiction: string) => `${BASE}/api/runs/${id}/report?jurisdiction=${jurisdiction}&format=md`,
  deleteRun: (id: string) => fetch(`${BASE}/api/runs/${id}`, { method: 'DELETE' }).then((r) => j<{ ok: boolean }>(r)),
}

export const fmtT = (v: string | number | null | undefined, dp = 2) => {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

export const SCOPE3_NAMES: Record<string, string> = {
  '1': 'Purchased goods & services',
  '2': 'Capital goods',
  '3': 'Fuel & energy related',
  '4': 'Upstream transport',
  '5': 'Waste in operations',
  '6': 'Business travel',
  '7': 'Employee commuting',
}

export const ACTIVITY_LABELS: Record<string, string> = {
  electricity_grid: 'Grid electricity',
  electricity_transmission_losses: 'T&D losses',
  natural_gas_stationary: 'Natural gas',
  diesel_stationary: 'Diesel (generators)',
  diesel_mobile: 'Diesel (fleet)',
  petrol_mobile: 'Petrol (fleet)',
  propane_stationary: 'LPG / propane',
  air_travel_short_haul: 'Air, short haul',
  air_travel_medium_haul: 'Air, medium haul',
  air_travel_long_haul: 'Air, long haul',
  air_travel_domestic: 'Air, domestic',
  rail_travel: 'Rail travel',
  car_travel: 'Car travel',
  hotel_stay: 'Hotel stays',
  road_freight: 'Road freight',
  rail_freight: 'Rail freight',
  sea_freight: 'Sea freight',
  air_freight: 'Air freight',
  water_supply: 'Water supply',
  water_treatment: 'Water treatment',
  waste_landfill_mixed: 'Waste to landfill',
  waste_recycled_mixed: 'Waste recycled',
  spend_office_supplies: 'Office supplies (spend)',
  spend_it_equipment: 'IT equipment (spend)',
  spend_professional_services: 'Professional services (spend)',
  spend_steel_products: 'Steel (spend)',
  not_an_emission_source: 'Not an emission source',
}

export const STATUS_LABELS: Record<Status, string> = {
  calculated: 'Calculated',
  unmatched_factor: 'No factor',
  unclassified: 'Needs review',
  no_quantity: 'No quantity',
  unit_error: 'Unit error',
  excluded: 'Excluded',
  duplicate: 'Duplicate',
}
