"""Greenwashing and data-integrity checks over the computed ledger.

Every check is deterministic. "block" findings stop disclosure generation; "warn"
findings are printed into the report's governance log so an auditor sees them.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from decimal import Decimal
from typing import Optional

from ..schemas import Finding, LedgerEntry, ScopeTotals

_CLAIM_WORDS = re.compile(r"\b(carbon[- ]neutral|net[- ]zero|climate[- ]positive|offset|100% renewable|zero[- ]emission|carbon[- ]negative)\b", re.I)


def mark_cross_file_duplicates(entries: list[LedgerEntry]) -> int:
    """Flag a calculated line as duplicate when an earlier line from a DIFFERENT file has the
    same activity, converted quantity, region and period. Returns the number flagged."""
    seen: dict[tuple, LedgerEntry] = {}
    n = 0
    for e in entries:
        if e.status != "calculated" or not e.calculation:
            continue
        k = (e.classification.activity_type, str(e.calculation.quantity_converted), (e.item.region or "").upper(), e.item.period)
        prev = seen.get(k)
        if prev and prev.item.source_file != e.item.source_file:
            e.status = "duplicate"
            e.duplicate_of = prev.item.line_id
            n += 1
        elif not prev:
            seen[k] = e
    return n


def run_checks(entries: list[LedgerEntry], totals: ScopeTotals, prior_totals: Optional[dict] = None, narrative: Optional[str] = None, offsets_t: Decimal = Decimal("0")) -> list[Finding]:
    findings: list[Finding] = []

    # GW01: figure without a factor citation (should be impossible; proves the invariant)
    bad = [e.item.line_id for e in entries if e.calculation and (not e.factor_match.matched or not e.factor_match.factor)]
    if bad:
        findings.append(Finding(check_id="GW01", severity="block", title="tCO2e without factor citation", detail="Lines carry a computed figure but no factor row reference.", line_ids=bad))

    # GW02: Scope 2 method mixing
    methods = {e.factor_match.factor.scope2_method for e in entries if e.calculation and e.factor_match.factor and e.factor_match.factor.scope == 2}
    if len(methods - {None}) > 1:
        findings.append(Finding(check_id="GW02", severity="block", title="Scope 2 location/market methods mixed", detail=f"Scope 2 lines use methods {sorted(m for m in methods if m)}; a single total must not blend them."))

    # GW03: unbacked claim in narrative
    if narrative:
        hits = sorted({m.group(0).lower() for m in _CLAIM_WORDS.finditer(narrative)})
        if hits and offsets_t <= 0:
            findings.append(Finding(check_id="GW03", severity="block", title="Unbacked climate claim in narrative", detail=f"Narrative uses {hits} but the ledger holds no verified offset or renewable-instrument entries."))

    # GW04: implausible year-on-year drop
    if prior_totals:
        for key, label in (("scope1", "Scope 1"), ("scope2_location", "Scope 2 (location)"), ("scope3", "Scope 3")):
            prev = Decimal(str(prior_totals.get(key, "0")))
            cur = getattr(totals, key)
            if prev > 0 and cur >= 0:
                change = (cur - prev) / prev
                if change < Decimal("-0.30"):
                    findings.append(Finding(check_id="GW04", severity="warn", title=f"{label} fell {abs(change) * 100:.0f}% year-on-year", detail=f"Prior {prev} tCO2e, current {cur} tCO2e. Verify activity data completeness before reporting a reduction."))

    # GW05: Scope 3 categories with spend but no emissions
    cat_spend: dict[int, Decimal] = defaultdict(Decimal)
    cat_emis: dict[int, Decimal] = defaultdict(Decimal)
    for e in entries:
        c = e.classification.scope3_category
        if c is None:
            continue
        if e.item.spend:
            cat_spend[c] += e.item.spend
        if e.calculation:
            cat_emis[c] += e.calculation.t_co2e
    missing = [c for c, s in cat_spend.items() if s > 0 and cat_emis.get(c, Decimal("0")) == 0]
    if missing:
        findings.append(Finding(check_id="GW05", severity="warn", title="Scope 3 categories with spend but zero emissions", detail=f"Categories {sorted(missing)} show ERP spend but no calculated emissions. Likely missing activity data or unmatched factors.", line_ids=[e.item.line_id for e in entries if e.classification.scope3_category in missing and not e.calculation]))

    # GW06: unit outliers within energy/fuel activities (kWh/MWh, litre/gallon mix-ups)
    by_act: dict[str, list[LedgerEntry]] = defaultdict(list)
    for e in entries:
        act = e.classification.activity_type or ""
        if e.calculation and (act.startswith("electricity") or act.endswith("_stationary") or act.endswith("_mobile")):
            by_act[f"{act}/{e.calculation.unit_converted}"].append(e)  # compare like units only
    outliers: list[str] = []
    for act, lst in by_act.items():
        if len(lst) < 4:
            continue
        vals = [float(x.calculation.quantity_converted) for x in lst]
        med = statistics.median(vals)
        mad = statistics.median([abs(v - med) for v in vals]) or 1e-9
        for x, v in zip(lst, vals):
            if abs(v - med) / (1.4826 * mad) > 8:
                outliers.append(x.item.line_id)
    if outliers:
        findings.append(Finding(check_id="GW06", severity="warn", title="Quantity outliers suggest unit mix-up", detail="Converted energy/fuel quantities sit far outside their activity's median (robust z > 8). Check for kWh vs MWh or litre vs gallon errors.", line_ids=outliers))

    # GW11: cross-source duplicates removed from totals (utility PDF vs ERP export)
    dups = [e for e in entries if e.status == "duplicate"]
    if dups:
        findings.append(Finding(check_id="GW11", severity="warn", title="Same consumption present in two source documents", detail="Identical activity, quantity, region and period found in different files (e.g. a utility bill and the ERP posting of that bill). Counted once; the later line is excluded and linked to the original.", line_ids=[e.item.line_id for e in dups]))

    # GW12: identical rows inside one file (may be legitimate, e.g. two travellers on one flight)
    seen: dict[tuple, str] = {}
    same_file: list[str] = []
    for e in entries:
        if not e.calculation:
            continue
        k = (e.item.source_file, e.classification.activity_type, str(e.calculation.quantity_converted), e.item.region, e.item.date)
        if k in seen:
            same_file.append(e.item.line_id)
        else:
            seen[k] = e.item.line_id
    if same_file:
        findings.append(Finding(check_id="GW12", severity="info", title="Identical rows within one file", detail="Rows with the same activity, quantity, region and date in the same file. Kept in totals; confirm they are distinct events.", line_ids=same_file))

    # GW07: unmatched / unclassified lines
    unmatched = [e.item.line_id for e in entries if e.status == "unmatched_factor"]
    if unmatched:
        findings.append(Finding(check_id="GW07", severity="warn", title="Lines with no official factor", detail="No EPA/DEFRA factor exists for these lines in the requested region. They are excluded from totals and listed as a data gap; no estimate was fabricated.", line_ids=unmatched))
    uncl = [e.item.line_id for e in entries if e.status == "unclassified"]
    if uncl:
        findings.append(Finding(check_id="GW08", severity="warn", title="Lines the classifier could not label", detail="No rule matched and no validated agent label was received (agent not configured, declined, or returned an out-of-list label). Manual review required.", line_ids=uncl))

    # GW09: spend-based share
    spend_t = sum((e.calculation.t_co2e for e in entries if e.calculation and e.data_quality == "estimated_spend"), Decimal("0"))
    if totals.total_location_based > 0 and spend_t / totals.total_location_based > Decimal("0.5"):
        findings.append(Finding(check_id="GW09", severity="info", title="Over half of the footprint is spend-based", detail=f"{spend_t} of {totals.total_location_based} tCO2e comes from EEIO spend factors. Disclose data-quality limitations under ESRS E1-6 / SEC Item 1505."))

    # GW10: low-confidence agent labels
    low = [e.item.line_id for e in entries if e.classification.method == "agent" and e.classification.confidence < Decimal("0.7")]
    if low:
        findings.append(Finding(check_id="GW10", severity="warn", title="Low-confidence agent classifications", detail="Classifier agent confidence below 0.70. These lines are included but flagged for human sign-off.", line_ids=low))

    return findings
