"""End-to-end run: ingest -> redact -> classify -> match -> calculate -> check -> ledger."""
from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from .agent_bridge import Orchestrator
from .calc.engine import calculate
from .calc.units import normalise_unit
from .classify.rules import apply_agent_label, classify_by_rules
from .factors.matcher import ACTIVITY_TYPES, library
from .guardrails.greenwashing import mark_cross_file_duplicates, run_checks
from .guardrails.pii import hash_vendor
from .ingestion.router import ingest_file
from .ledger import db
from .schemas import AgentLogEntry, FactorMatch, LedgerEntry, LineItem, RunSummary, ScopeTotals


def _year_of(period: Optional[str]) -> Optional[int]:
    if not period:
        return None
    m = re.search(r"(20\d{2})", period)
    return int(m.group(1)) if m else None


def _agent_payload(item: LineItem) -> dict:
    return {
        "line_id": item.line_id,
        "description": item.description,
        "vendor_token": hash_vendor(item.vendor),
        "gl_code": item.gl_code,
        "quantity": str(item.quantity) if item.quantity is not None else None,
        "unit": item.unit,
        "region": item.region,
    }


class Pipeline:
    def __init__(self, orchestrator: Optional[Orchestrator] = None):
        self.orch = orchestrator or Orchestrator(allowed_activity_types=set(ACTIVITY_TYPES))
        self.lib = library()

    # ------------------------------------------------------------------
    def run(self, files: list[tuple[str, bytes]], org_name: str, jurisdiction: str = "CSRD", prior_totals: Optional[dict] = None, default_region: Optional[str] = None) -> tuple[RunSummary, list[LedgerEntry], list[AgentLogEntry]]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.orch.log.clear()

        # 1. ingest (parsers redact as they go)
        items: list[LineItem] = []
        for name, content in files:
            items.extend(ingest_file(name, content))
        if default_region:
            for it in items:
                it.region = it.region or default_region
        self.orch._log("ingestion", "ingest", f"{len(files)} files", f"{len(items)} line items; PII redacted on {sum(1 for i in items if i.redactions)} lines", mode="fallback")

        # 2. classify: rules first, agent for the residue
        entries: list[LedgerEntry] = []
        residue: list[LineItem] = []
        for it in items:
            cls = classify_by_rules(it)
            entries.append(LedgerEntry(item=it, classification=cls, factor_match=FactorMatch(matched=False)))
            if cls.method == "unclassified":
                residue.append(it)
        self.orch._log("rule_engine", "classify", f"{len(items)} lines", f"{len(items) - len(residue)} labelled by rules, {len(residue)} residual", mode="fallback")

        if residue:
            labels = self.orch.classify([_agent_payload(it) for it in residue])
            for e in entries:
                lab = labels.get(e.item.line_id)
                if lab:
                    e.classification = apply_agent_label(lab["activity_type"], lab["confidence"], lab["reason"])

        # 3 + 4. match and calculate
        for e in entries:
            self._resolve(e)
        ndup = mark_cross_file_duplicates(entries)
        if ndup:
            self.orch._log("guardrails", "dedupe", f"{len(entries)} entries", f"{ndup} cross-file duplicates excluded from totals", mode="fallback")

        totals = self._totals(entries)
        findings = run_checks(entries, totals, prior_totals=prior_totals)
        self.orch._log("guardrails", "greenwashing_checks", f"{len(entries)} entries", f"{len(findings)} findings ({sum(1 for f in findings if f.severity == 'block')} blocking)", mode="fallback")

        period = Counter(i.period for i in items if i.period).most_common(1)
        summary = RunSummary(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            org_name=org_name,
            reporting_period=period[0][0] if period else f"FY{datetime.now().year}",
            jurisdiction=jurisdiction,
            source_files=[n for n, _ in files],
            totals=totals,
            findings=findings,
            report_allowed=not any(f.severity == "block" for f in findings),
            agent_mode=self.orch.mode,  # type: ignore[arg-type]
        )
        log = [AgentLogEntry(**l.as_dict()) for l in self.orch.log]
        db.save_run(summary, entries, log)
        return summary, entries, log

    # ------------------------------------------------------------------
    def _resolve(self, e: LedgerEntry) -> None:
        cls = e.classification
        it = e.item
        if cls.activity_type is None:
            e.status = "unclassified"
            return
        if cls.activity_type == "not_an_emission_source":
            e.status = "excluded"
            e.factor_match = FactorMatch(matched=False, reason="Not an emission source")
            return

        qty, unit = it.quantity, it.unit
        if cls.activity_type.startswith("spend_"):
            if it.spend is None:
                e.status = "no_quantity"
                e.factor_match = FactorMatch(matched=False, reason="Spend-based activity but no spend value on the line")
                return
            if it.currency and it.currency.upper() != "USD":
                e.status = "unmatched_factor"
                e.factor_match = FactorMatch(matched=False, reason=f"Spend-based factor is per 2022 USD; line is in {it.currency}. Currency conversion is out of scope, no estimate produced.")
                return
            qty, unit = it.spend, "usd"
            e.data_quality = "estimated_spend"
        else:
            if qty is None or unit is None or normalise_unit(unit) is None:
                e.status = "no_quantity"
                e.factor_match = FactorMatch(matched=False, reason=f"No usable quantity/unit (quantity={qty}, unit={unit})")
                return
            e.data_quality = "measured"

        e.factor_match = self.lib.match(cls.activity_type, it.region, _year_of(it.period))
        if not e.factor_match.matched or not e.factor_match.factor:
            e.status = "unmatched_factor"
            return
        try:
            e.calculation = calculate(qty, unit, e.factor_match.factor)
            e.status = "calculated"
        except ValueError as exc:
            e.status = "unit_error"
            e.factor_match.reason += f" | calculation refused: {exc}"

    # ------------------------------------------------------------------
    @staticmethod
    def _totals(entries: list[LedgerEntry]) -> ScopeTotals:
        t = ScopeTotals(lines_total=len(entries))
        cat: dict[str, Decimal] = defaultdict(Decimal)
        act: dict[str, Decimal] = defaultdict(Decimal)
        for e in entries:
            if e.status == "calculated" and e.calculation:
                t.lines_calculated += 1
                v = e.calculation.t_co2e
                s = e.classification.scope
                if s == 1:
                    t.scope1 += v
                elif s == 2:
                    if e.factor_match.factor and e.factor_match.factor.scope2_method == "market":
                        t.scope2_market += v
                    else:
                        t.scope2_location += v
                elif s == 3:
                    t.scope3 += v
                    cat[str(e.classification.scope3_category or 0)] += v
                act[e.classification.activity_type or "unknown"] += v
                if e.data_quality == "estimated_spend":
                    t.spend_based_t += v
            elif e.status == "unmatched_factor":
                t.lines_unmatched += 1
            elif e.status == "unclassified":
                t.lines_unclassified += 1
            elif e.status == "no_quantity":
                t.lines_no_quantity += 1
            elif e.status == "excluded":
                t.lines_excluded += 1
            elif e.status == "unit_error":
                t.lines_unit_error += 1
            elif e.status == "duplicate":
                t.lines_duplicate += 1
        t.scope3_by_category = dict(cat)
        t.by_activity = dict(act)
        t.total_location_based = t.scope1 + t.scope2_location + t.scope3
        return t
