"""Unit tests for the greenwashing / data-integrity checks and the PII redaction layer.

Each GW check is exercised with a minimal hand-built ledger so the trigger condition is
explicit; the pipeline tests cover how they combine over real sample data.
"""
from decimal import Decimal

import pytest

from app.guardrails.greenwashing import mark_cross_file_duplicates, run_checks
from app.guardrails.pii import hash_vendor, redact_text, strip_sensitive_fields
from app.schemas import Calculation, Classification, FactorMatch, FactorRow, LedgerEntry, LineItem, ScopeTotals


def entry(line_id, *, activity="electricity_grid", scope=2, cat=None, qty="100", unit="kWh", t="0.02",
          status="calculated", source="a.csv", ref="row 1", sha=None, region="GB", period="FY2025", date=None,
          spend=None, method="rule", confidence="0.95", data_quality="measured", scope2_method="location",
          matched=True) -> LedgerEntry:
    item = LineItem(line_id=line_id, source_file=source, source_ref=ref, source_sha256=sha, description=activity,
                    region=region, period=period, date=date, spend=Decimal(spend) if spend else None)
    classification = Classification(scope=scope, scope3_category=cat, activity_type=activity, method=method, confidence=Decimal(confidence))
    factor = FactorRow(factor_id="F", activity_type=activity, scope=scope, region=region, year=2025, value=Decimal("0.2"),
                       unit=unit, source="s", table_ref="t", scope2_method=scope2_method) if matched else None
    match = FactorMatch(matched=matched, factor=factor, match_quality="exact" if matched else "none")
    calculation = None
    if status not in ("unclassified", "unmatched_factor", "no_quantity"):
        calculation = Calculation(quantity_input=Decimal(qty), unit_input=unit, quantity_converted=Decimal(qty), unit_converted=unit,
                                  factor_value=Decimal("0.2"), factor_unit=f"kg CO2e/{unit}", kg_co2e=Decimal(t) * 1000,
                                  t_co2e=Decimal(t), formula="synthetic")
    return LedgerEntry(item=item, classification=classification, factor_match=match, calculation=calculation,
                       status=status, data_quality=data_quality)


def one(findings, check_id):
    hits = [f for f in findings if f.check_id == check_id]
    assert len(hits) <= 1, f"{check_id} reported more than once"
    return hits[0] if hits else None


def test_empty_ledger_has_no_findings():
    assert run_checks([], ScopeTotals()) == []


def test_gw01_figure_without_factor_citation_blocks():
    finding = one(run_checks([entry("a", matched=False)], ScopeTotals()), "GW01")
    assert finding and finding.severity == "block" and finding.line_ids == ["a"]


def test_gw02_mixed_scope2_methods_block_but_a_single_method_does_not():
    mixed = [entry("a", scope2_method="location"), entry("b", scope2_method="market", qty="50")]
    assert one(run_checks(mixed, ScopeTotals()), "GW02").severity == "block"
    assert one(run_checks(mixed[:1], ScopeTotals()), "GW02") is None


def test_gw03_climate_claims_need_offset_evidence():
    ledger = [entry("a")]
    blocked = one(run_checks(ledger, ScopeTotals(), narrative="We are proud to be carbon neutral and Net-Zero."), "GW03")
    assert blocked and blocked.severity == "block" and "carbon neutral" in blocked.detail and "net-zero" in blocked.detail
    assert one(run_checks(ledger, ScopeTotals(), narrative="We are carbon neutral.", offsets_t=Decimal("5")), "GW03") is None
    assert one(run_checks(ledger, ScopeTotals(), narrative="Emissions are reported below."), "GW03") is None


def test_gw04_flags_implausible_year_on_year_drops_only():
    totals = ScopeTotals(scope1=Decimal("50"), scope2_location=Decimal("80"), scope3=Decimal("10"))
    prior = {"scope1": "100", "scope2_location": "100", "scope3": "0"}
    findings = run_checks([entry("a")], totals, prior_totals=prior)
    drops = [f for f in findings if f.check_id == "GW04"]
    assert len(drops) == 1 and drops[0].severity == "warn" and "Scope 1 fell 50%" in drops[0].title
    assert "Prior 100" in drops[0].detail


def test_gw05_scope3_spend_without_emissions_is_a_data_gap():
    gap = [entry("a", activity="spend_office_supplies", scope=3, cat=1, spend="1000", status="unclassified")]
    finding = one(run_checks(gap, ScopeTotals()), "GW05")
    assert finding and finding.severity == "warn" and finding.line_ids == ["a"] and "[1]" in finding.detail
    covered = gap + [entry("b", activity="spend_office_supplies", scope=3, cat=1, unit="usd", t="0.5")]
    assert one(run_checks(covered, ScopeTotals()), "GW05") is None


def test_gw06_detects_quantity_outliers_within_an_activity():
    ledger = [entry(f"l{i}", qty=q) for i, q in enumerate(["100", "101", "99", "100", "1000000"])]
    finding = one(run_checks(ledger, ScopeTotals()), "GW06")
    assert finding and finding.line_ids == ["l4"] and "unit mix-up" in finding.title
    assert one(run_checks(ledger[:3], ScopeTotals()), "GW06") is None  # fewer than 4 lines: no statistics


def test_gw07_and_gw08_list_unmatched_and_unclassified_lines():
    ledger = [entry("ok"), entry("nf", status="unmatched_factor"), entry("uc", status="unclassified", matched=False)]
    findings = run_checks(ledger, ScopeTotals())
    assert one(findings, "GW07").line_ids == ["nf"] and "no estimate was fabricated" in one(findings, "GW07").detail
    assert one(findings, "GW08").line_ids == ["uc"] and one(findings, "GW08").severity == "warn"


def test_gw09_spend_based_share_over_half_is_disclosed():
    ledger = [entry("s", data_quality="estimated_spend", t="0.6"), entry("m", t="0.4")]
    totals = ScopeTotals(total_location_based=Decimal("1.0"))
    finding = one(run_checks(ledger, totals), "GW09")
    assert finding and finding.severity == "info" and "0.6 of 1.0" in finding.detail
    assert one(run_checks(ledger, ScopeTotals(total_location_based=Decimal("2.0"))), "GW09") is None


def test_gw10_low_confidence_agent_labels_are_flagged_below_070():
    ledger = [entry("low", method="agent", confidence="0.5"), entry("edge", method="agent", confidence="0.7"), entry("rule", confidence="0.5")]
    finding = one(run_checks(ledger, ScopeTotals()), "GW10")
    assert finding and finding.line_ids == ["low"]


def test_gw11_gw12_gw13_duplicate_families_are_distinct():
    ledger = [
        entry("orig", date="2025-01-01"),
        entry("dup", status="duplicate", date="2025-02-01"),
        entry("same_file", date="2025-01-01"),
        entry("other_file", source="b.csv", date="2025-03-01"),
    ]
    findings = run_checks(ledger, ScopeTotals())
    assert one(findings, "GW11").line_ids == ["dup"] and one(findings, "GW11").severity == "warn"
    assert one(findings, "GW12").line_ids == ["same_file"] and one(findings, "GW12").severity == "info"
    cross = one(findings, "GW13")
    assert cross and cross.severity == "warn" and set(cross.line_ids) == {"orig", "same_file", "other_file"}


def test_only_byte_identical_documents_are_auto_deduplicated():
    first = entry("a", sha="deadbeef", source="bill.pdf")
    renamed = entry("b", sha="deadbeef", source="bill (1).pdf")
    different_doc = entry("c", sha="cafebabe", source="other.pdf")
    skipped = entry("d", sha="deadbeef", source="bill (2).pdf", status="unclassified", matched=False)
    assert mark_cross_file_duplicates([first, renamed, different_doc, skipped]) == 1
    assert renamed.status == "duplicate" and renamed.duplicate_of == "a"
    assert first.status == "calculated" and different_doc.status == "calculated" and skipped.status == "unclassified"


# ---------------------------------------------------------------- PII
@pytest.mark.parametrize("text,kind", [
    ("mail me at a.b+c@example.co.uk", "email"),
    ("IBAN GB82WEST12345698765432", "iban"),
    ("card 4111 1111 1111 1111", "card_number"),
    ("call +44 7700 900123", "phone"),
    ("Account no: ABC123456 please", "account_number"),
    ("total $1,234.56", "currency_amount"),
    ("paid 250 EUR", "currency_amount"),
    ("ship to 221 Baker Street", "street_address"),
    ("SSN 123-45-6789", "ssn_nino"),
    ("NINO AB123456C", "ssn_nino"),
])
def test_each_pii_pattern_is_replaced_with_a_typed_placeholder(text, kind):
    redacted, kinds = redact_text(text)
    assert kind in kinds and f"[{kind.upper()}]" in redacted


def test_clean_text_and_empty_values_pass_through():
    assert redact_text(None) == (None, [])
    assert redact_text("") == ("", [])
    assert redact_text("Electricity supply 1000 kWh") == ("Electricity supply 1000 kWh", [])


def test_sensitive_columns_are_dropped_case_and_space_insensitively():
    row = {"Description": "Gas", " Spend ": 100, "Employee Name": "J", "quantity": 5, "CONTACT": "x", "unit": "kWh"}
    assert strip_sensitive_fields(row) == {"Description": "Gas", "quantity": 5, "unit": "kWh"}


def test_vendor_hash_is_stable_normalised_and_non_reversible():
    token = hash_vendor("  British Gas ")
    assert token == hash_vendor("british gas") and token.startswith("VENDOR_") and len(token) == len("VENDOR_") + 8
    assert token != hash_vendor("EDF Energy")
    assert hash_vendor(None) is None and hash_vendor("") is None
