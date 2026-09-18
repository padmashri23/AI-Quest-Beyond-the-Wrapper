"""Pydantic models shared across ingestion, classification, calculation and reporting.

Every numeric that ends up in a disclosure is a Decimal serialised as a string so the
JSON round-trip never introduces binary floating point error.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    """One normalised activity row from any source document, after PII redaction."""

    line_id: str
    source_file: str
    source_ref: str = Field(description="Row number, page number or invoice line that produced this item")
    date: Optional[str] = None
    period: Optional[str] = Field(default=None, description="Fiscal year label derived from date, e.g. FY2025")
    vendor: Optional[str] = None
    description: str
    gl_code: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    region: Optional[str] = Field(default=None, description="ISO country code or eGRID subregion, e.g. US, GB, CAMX")
    spend: Optional[Decimal] = Field(default=None, description="Monetary amount. Never sent to a model.")
    currency: Optional[str] = None
    raw_text: Optional[str] = Field(default=None, description="Redacted raw text of the source row/line")
    redactions: list[str] = Field(default_factory=list, description="Kinds of PII removed from this row")
    source_sha256: Optional[str] = None
    document_id: Optional[str] = None


class Classification(BaseModel):
    scope: Optional[Literal[1, 2, 3]] = None
    scope3_category: Optional[int] = Field(default=None, description="GHG Protocol Scope 3 category 1-15")
    activity_type: Optional[str] = Field(default=None, description="Key into the factor tables, e.g. electricity_grid")
    method: Literal["rule", "agent", "unclassified", "reviewer"] = "unclassified"
    confidence: Decimal = Decimal("0")
    reason: str = ""
    rule_id: Optional[str] = None


class FactorRow(BaseModel):
    factor_id: str
    activity_type: str
    scope: Literal[1, 2, 3]
    scope3_category: Optional[int] = None
    region: str = Field(description="ISO country, eGRID subregion, or GLOBAL")
    year: int
    value: Decimal = Field(description="kg CO2e per denominator unit (already GWP-weighted if components given)")
    unit: str = Field(description="Denominator unit, e.g. kWh, litre, tonne_km")
    components: Optional[dict[str, Decimal]] = Field(default=None, description="Per-gas kg per unit, e.g. {CO2:..., CH4:..., N2O:...}")
    gwp_set: Optional[str] = Field(default=None, description="GWP set used to fold components into CO2e, e.g. AR5-100")
    method: Literal["activity", "spend"] = "activity"
    scope2_method: Optional[Literal["location", "market"]] = None
    source: str
    table_ref: str
    url: Optional[str] = None
    notes: Optional[str] = None
    verified: bool = False
    source_sha256: Optional[str] = None
    source_row: Optional[str] = None


class FactorMatch(BaseModel):
    matched: bool
    factor: Optional[FactorRow] = None
    match_quality: Literal["exact", "region_fallback", "year_fallback", "global_fallback", "none"] = "none"
    requested: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ConversionStep(BaseModel):
    from_unit: str
    to_unit: str
    factor: Decimal
    source: str


class Calculation(BaseModel):
    quantity_input: Decimal
    unit_input: str
    conversion: Optional[ConversionStep] = None
    quantity_converted: Decimal
    unit_converted: str
    factor_value: Decimal
    factor_unit: str
    kg_co2e: Decimal
    t_co2e: Decimal
    gas_breakdown: Optional[dict[str, Decimal]] = None
    formula: str
    rounding: str = "kg to 6 dp, tonnes to 6 dp, ROUND_HALF_EVEN"
    engine: str = "python.decimal (60-digit local context)"


class LedgerEntry(BaseModel):
    """A fully-traced line: source -> classification -> factor -> calculation."""

    item: LineItem
    classification: Classification
    factor_match: FactorMatch
    calculation: Optional[Calculation] = None
    status: Literal["calculated", "unmatched_factor", "unclassified", "no_quantity", "unit_error", "excluded", "duplicate"] = "unclassified"
    duplicate_of: Optional[str] = Field(default=None, description="line_id of the earlier line this one duplicates (cross-file)")
    data_quality: Literal["measured", "estimated_spend", "unknown"] = "unknown"


class Finding(BaseModel):
    check_id: str
    severity: Literal["block", "warn", "info"]
    title: str
    detail: str
    line_ids: list[str] = Field(default_factory=list)


class AgentLogEntry(BaseModel):
    ts: str
    agent: str
    mode: Literal["lyzr", "fallback"]
    step: str
    input_summary: str
    output_summary: str
    tokens_estimate: Optional[int] = None
    latency_ms: Optional[int] = None


class ScopeTotals(BaseModel):
    scope1: Decimal = Decimal("0")
    scope2_location: Decimal = Decimal("0")
    scope2_market: Decimal = Decimal("0")
    scope3: Decimal = Decimal("0")
    scope3_by_category: dict[str, Decimal] = Field(default_factory=dict)
    by_activity: dict[str, Decimal] = Field(default_factory=dict)
    total_location_based: Decimal = Decimal("0")
    lines_total: int = 0
    lines_calculated: int = 0
    lines_unmatched: int = 0
    lines_unclassified: int = 0
    lines_no_quantity: int = 0
    lines_excluded: int = 0
    lines_unit_error: int = 0
    lines_duplicate: int = 0
    spend_based_t: Decimal = Decimal("0")


class RunSummary(BaseModel):
    run_id: str
    created_at: str
    org_name: str
    reporting_period: str
    jurisdiction: str
    source_files: list[str]
    totals: ScopeTotals
    findings: list[Finding]
    report_allowed: bool
    agent_mode: Literal["lyzr", "fallback"]
    revision: int = 1
    created_by: str = "system"
    prior_totals: Optional[dict[str, str]] = None
