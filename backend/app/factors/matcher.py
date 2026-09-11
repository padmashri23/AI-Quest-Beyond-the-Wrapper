"""Deterministic emission-factor matching.

Resolution order for (activity_type, region, year):
  1. exact region, latest year <= requested year (or latest overall if none)
  2. region fallback: eGRID subregion -> US; any country -> its table family default
  3. global fallback: a row tagged GLOBAL
  4. none -> caller must flag the line, never guess

No fuzzy string matching on activity_type: the classifier must emit a canonical key
from ACTIVITY_TYPES, so the "retrieval" step here is an exact dictionary lookup.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..schemas import FactorMatch, FactorRow

_TABLE_DIR = Path(__file__).parent / "tables"

EGRID_SUBREGIONS = {"CAMX", "ERCT", "NYUP", "RFCW", "SRSO", "NWPP", "NYCW", "NYLI", "NEWE", "RFCE", "RFCM", "SRMW", "SRMV", "SRTV", "SRVC", "MROE", "MROW", "SPNO", "SPSO", "AZNM", "RMPA", "AKGD", "AKMS", "HIMS", "HIOA", "PRMS"}

# Countries whose default factor family is DEFRA (GB) when no country-specific row exists.
_DEFRA_FAMILY = {"GB", "UK", "IE"}

# Human-readable catalogue of activity keys the classifier may emit.
ACTIVITY_TYPES: dict[str, dict] = {
    "electricity_grid": {"scope": 2, "label": "Purchased electricity (grid)", "units": ["kWh", "MWh"]},
    "electricity_transmission_losses": {"scope": 3, "cat": 3, "label": "T&D losses on purchased electricity", "units": ["kWh"]},
    "natural_gas_stationary": {"scope": 1, "label": "Natural gas, stationary combustion", "units": ["kWh", "therm", "mmBtu", "scf_natural_gas", "ccf"]},
    "diesel_stationary": {"scope": 1, "label": "Diesel, stationary (generators)", "units": ["litre", "us_gallon"]},
    "diesel_mobile": {"scope": 1, "label": "Diesel, owned fleet", "units": ["litre", "us_gallon"]},
    "petrol_mobile": {"scope": 1, "label": "Petrol/gasoline, owned fleet", "units": ["litre", "us_gallon"]},
    "propane_stationary": {"scope": 1, "label": "LPG / propane, stationary", "units": ["litre", "us_gallon"]},
    "air_travel_short_haul": {"scope": 3, "cat": 6, "label": "Air travel, short haul", "units": ["passenger_km", "passenger_mile"]},
    "air_travel_medium_haul": {"scope": 3, "cat": 6, "label": "Air travel, medium haul", "units": ["passenger_km", "passenger_mile"]},
    "air_travel_long_haul": {"scope": 3, "cat": 6, "label": "Air travel, long haul", "units": ["passenger_km", "passenger_mile"]},
    "air_travel_domestic": {"scope": 3, "cat": 6, "label": "Air travel, domestic", "units": ["passenger_km", "passenger_mile"]},
    "rail_travel": {"scope": 3, "cat": 6, "label": "Rail travel", "units": ["passenger_km", "passenger_mile"]},
    "car_travel": {"scope": 3, "cat": 6, "label": "Hire car / employee car travel", "units": ["km", "mile"]},
    "hotel_stay": {"scope": 3, "cat": 6, "label": "Hotel stays", "units": ["room_night"]},
    "road_freight": {"scope": 3, "cat": 4, "label": "Upstream road freight", "units": ["tonne_km", "ton_mile"]},
    "rail_freight": {"scope": 3, "cat": 4, "label": "Upstream rail freight", "units": ["tonne_km", "ton_mile"]},
    "sea_freight": {"scope": 3, "cat": 4, "label": "Upstream sea freight", "units": ["tonne_km"]},
    "air_freight": {"scope": 3, "cat": 4, "label": "Upstream air freight", "units": ["tonne_km", "ton_mile"]},
    "water_supply": {"scope": 3, "cat": 1, "label": "Water supply", "units": ["m3"]},
    "water_treatment": {"scope": 3, "cat": 5, "label": "Water treatment", "units": ["m3"]},
    "waste_landfill_mixed": {"scope": 3, "cat": 5, "label": "Waste to landfill, mixed", "units": ["tonne", "kg", "short_ton"]},
    "waste_recycled_mixed": {"scope": 3, "cat": 5, "label": "Waste recycled, mixed", "units": ["tonne", "kg"]},
    "spend_office_supplies": {"scope": 3, "cat": 1, "label": "Purchased goods: office supplies (spend-based)", "units": ["usd"]},
    "spend_it_equipment": {"scope": 3, "cat": 2, "label": "Capital goods: IT equipment (spend-based)", "units": ["usd"]},
    "spend_professional_services": {"scope": 3, "cat": 1, "label": "Purchased services: professional (spend-based)", "units": ["usd"]},
    "spend_steel_products": {"scope": 3, "cat": 1, "label": "Purchased goods: steel (spend-based)", "units": ["usd"]},
    "not_an_emission_source": {"scope": None, "label": "Not an emission source (rent, payroll, tax, insurance...)", "units": []},
}


class FactorLibrary:
    def __init__(self, table_dir: Path = _TABLE_DIR):
        self.tables: list[dict] = []
        self.rows: list[FactorRow] = []
        for p in sorted(table_dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            self.tables.append({k: v for k, v in data.items() if k != "rows"})
            for r in data["rows"]:
                r = dict(r)
                r["value"] = Decimal(r["value"])
                if r.get("components"):
                    r["components"] = {g: Decimal(v) for g, v in r["components"].items()}
                self.rows.append(FactorRow(**r))
        self._index: dict[tuple[str, str], list[FactorRow]] = {}
        for row in self.rows:
            self._index.setdefault((row.activity_type, row.region), []).append(row)
        for lst in self._index.values():
            lst.sort(key=lambda r: r.year, reverse=True)

    # ------------------------------------------------------------------
    def _lookup(self, activity: str, region: str, year: Optional[int]) -> tuple[Optional[FactorRow], str]:
        rows = self._index.get((activity, region))
        if not rows:
            return None, "none"
        if year is None:
            return rows[0], "exact"
        for r in rows:  # newest first
            if r.year <= year:
                return r, "exact" if r.year == year or r is rows[0] else "year_fallback"
        # all rows newer than requested year: use oldest available and flag
        return rows[-1], "year_fallback"

    def match(self, activity_type: Optional[str], region: Optional[str], year: Optional[int] = None) -> FactorMatch:
        req = {"activity_type": activity_type, "region": region, "year": year}
        if not activity_type or activity_type not in ACTIVITY_TYPES:
            return FactorMatch(matched=False, requested=req, reason=f"Unknown or missing activity_type '{activity_type}'")
        if activity_type == "not_an_emission_source":
            return FactorMatch(matched=False, requested=req, reason="Line is not an emission source")

        region_n = (region or "").strip().upper() or "GLOBAL"
        if region_n == "UK":
            region_n = "GB"

        chain: list[tuple[str, str]] = [(region_n, "exact")]
        if region_n in EGRID_SUBREGIONS:
            chain.append(("US", "region_fallback"))
        if region_n in _DEFRA_FAMILY and region_n != "GB":
            chain.append(("GB", "region_fallback"))
        chain.append(("GLOBAL", "global_fallback"))

        for reg, quality in chain:
            row, q = self._lookup(activity_type, reg, year)
            if row:
                final_q = quality if quality != "exact" else q
                reason = f"{row.factor_id} from {row.source} ({row.table_ref})"
                if final_q != "exact":
                    reason = f"{final_q}: requested region={region_n} year={year}; used {row.region} {row.year}. " + reason
                return FactorMatch(matched=True, factor=row, match_quality=final_q, requested=req, reason=reason)

        return FactorMatch(
            matched=False, requested=req, match_quality="none",
            reason=f"No factor for activity_type={activity_type} in region {region_n} or any fallback. Line flagged; no estimate produced.",
        )

    def list_rows(self) -> list[FactorRow]:
        return list(self.rows)


_LIB: Optional[FactorLibrary] = None


def library() -> FactorLibrary:
    global _LIB
    if _LIB is None:
        _LIB = FactorLibrary()
    return _LIB
