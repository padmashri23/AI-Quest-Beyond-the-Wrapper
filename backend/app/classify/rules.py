"""Rule-based Scope 1/2/3 pre-classifier.

Runs before any agent call. Rules are ordered; the first hit wins. Each rule carries an
id so the lineage record can cite which rule labelled the line. Anything the rules do
not cover is left "unclassified" for the Lyzr classifier agent (only that residue is
sent to the model, which is what keeps token spend and latency low).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from ..calc.units import dimension_of, normalise_unit
from ..schemas import Classification, LineItem

# (rule_id, regex on description+vendor+gl_code, activity_type, required unit dimension or None)
_RULES: list[tuple[str, re.Pattern, str, Optional[str]]] = [
    ("R00_R410A", re.compile(r"\bR[- ]?410A\b", re.I), "refrigerant_r410a", "mass"),
    # NB: kWh/MWh are deliberately NOT electricity keywords; UK gas is billed in kWh too.
    ("R02_NATGAS", re.compile(r"\b(natural gas|gas supply|gas statement|therms?|mmbtu|ccf|scf|boiler gas|heating gas|gas bill|calorific)\b", re.I), "natural_gas_stationary", "energy"),
    ("R01_ELEC", re.compile(r"\b(electricity|electric|power supply|grid supply|utility power|edf|eon|octopus|pg&e|pacific gas|con ?edison|duke energy|oncor|txu)\b", re.I), "electricity_grid", "energy"),
    ("R03_DIESEL_GEN", re.compile(r"\b(generator|genset|backup diesel|standby diesel|red diesel|gas ?oil)\b", re.I), "diesel_stationary", "volume"),
    ("R04_DIESEL_FLEET", re.compile(r"\b(diesel|derv|fuel card|fleet fuel|hgv fuel|truck fuel)\b", re.I), "diesel_mobile", "volume"),
    ("R05_PETROL", re.compile(r"\b(petrol|gasoline|unleaded|ulp)\b", re.I), "petrol_mobile", "volume"),
    ("R06_LPG", re.compile(r"\b(propane|lpg|forklift gas|butane)\b", re.I), "propane_stationary", "volume"),
    # freight before travel so "rail freight" / "air freight" never resolve to passenger travel
    ("R14_SEA_FREIGHT", re.compile(r"\b(sea freight|ocean freight|container ship|maersk|msc |cma cgm|hapag|shipping line|port to port)\b", re.I), "sea_freight", "freight"),
    ("R15_AIR_FREIGHT", re.compile(r"\b(air freight|air cargo|airfreight|express air)\b", re.I), "air_freight", "freight"),
    ("R16_RAIL_FREIGHT", re.compile(r"\b(rail freight|intermodal rail|freight train)\b", re.I), "rail_freight", "freight"),
    ("R17_ROAD_FREIGHT", re.compile(r"\b(freight|haulage|trucking|carrier|ltl|ftl|dhl freight|xpo|schneider|jb hunt|pallet delivery|inbound logistics)\b", re.I), "road_freight", "freight"),
    ("R07_AIR_LONG", re.compile(r"\b(long[- ]?haul|international flight|intercontinental|transatlantic)\b", re.I), "air_travel_long_haul", "travel"),
    ("R08_AIR_SHORT", re.compile(r"\b(short[- ]?haul|regional flight|shuttle flight)\b", re.I), "air_travel_short_haul", "travel"),
    ("R09_AIR_DOM", re.compile(r"\b(domestic flight)\b", re.I), "air_travel_domestic", "travel"),
    ("R10_AIR_GENERIC", re.compile(r"\b(flight|airfare|airline|british airways|united airlines|delta|lufthansa|ryanair|easyjet|american airlines|indigo)\b", re.I), "air_travel_medium_haul", "travel"),
    ("R11_RAIL", re.compile(r"\b(rail|train|amtrak|eurostar|lner|avanti|gwr|national rail|trainline)\b", re.I), "rail_travel", None),
    ("R12_HOTEL", re.compile(r"\b(hotel|lodging|accommodation|marriott|hilton|premier inn|travelodge|ibis|hyatt|room[- ]?night)\b", re.I), "hotel_stay", "accommodation"),
    ("R13_CAR", re.compile(r"\b(mileage|hire car|rental car|car rental|hertz|avis|enterprise rent|uber|taxi|grey fleet|employee car)\b", re.I), "car_travel", None),
    ("R18_WATER_SUPPLY", re.compile(r"\b(water supply|water bill|thames water|severn trent|anglian water|water usage|potable water)\b", re.I), "water_supply", "water"),
    ("R19_WATER_TREAT", re.compile(r"\b(wastewater|sewerage|effluent|water treatment|trade effluent)\b", re.I), "water_treatment", "water"),
    ("R20_WASTE_RECYCLED", re.compile(r"\b(recycl)", re.I), "waste_recycled_mixed", None),
    ("R21_WASTE_LANDFILL", re.compile(r"\b(landfill|general waste|skip hire|waste collection|waste disposal|biffa|veolia|suez|waste management)\b", re.I), "waste_landfill_mixed", None),
    ("R22_TD_LOSSES", re.compile(r"\b(t&d losses|transmission loss|distribution loss)\b", re.I), "electricity_transmission_losses", "energy"),
    # spend-based residual categories (unit must be spend)
    ("R30_SPEND_STEEL", re.compile(r"\b(steel|rebar|sheet metal|coil|ferro)\b", re.I), "spend_steel_products", "spend"),
    ("R31_SPEND_IT", re.compile(r"\b(laptop|server|monitor|workstation|dell|lenovo|hp inc|apple|computer|it hardware)\b", re.I), "spend_it_equipment", "spend"),
    ("R32_SPEND_OFFICE", re.compile(r"\b(stationery|office supplies|paper|toner|staples|viking direct|lyreco)\b", re.I), "spend_office_supplies", "spend"),
    ("R33_SPEND_SERVICES", re.compile(r"\b(consult|advisory|legal|audit fee|accounting fee|professional services|deloitte|kpmg|pwc|ey )\b", re.I), "spend_professional_services", "spend"),
    # explicit non-emission lines
    ("R90_NOT_SOURCE", re.compile(r"\b(rent|lease payment|payroll|salary|salaries|wages|tax|vat|insurance|bank charge|interest|loan|dividend|depreciation|subscription|software licen[cs]e|saas|donation)\b", re.I), "not_an_emission_source", None),
]

_GL_HINTS: dict[str, str] = {
    "6100": "electricity_grid", "6110": "natural_gas_stationary", "6120": "water_supply",
    "6200": "diesel_mobile", "6210": "petrol_mobile",
    "6300": "air_travel_medium_haul", "6310": "hotel_stay", "6320": "rail_travel", "6330": "car_travel",
    "5100": "road_freight", "5110": "sea_freight", "5120": "air_freight",
    "6400": "waste_landfill_mixed", "6410": "waste_recycled_mixed",
    "7000": "not_an_emission_source", "7100": "not_an_emission_source",
}


def _dimension_ok(item: LineItem, required: Optional[str]) -> bool:
    if required is None:
        return True
    if item.unit is None:
        return required == "spend" and item.spend is not None
    if required == "spend":
        return dimension_of(item.unit) == "spend" or normalise_unit(item.unit) is None and item.spend is not None
    return dimension_of(item.unit) == required


def classify_by_rules(item: LineItem) -> Classification:
    text = " ".join(filter(None, [item.description, item.vendor, item.raw_text or ""]))

    # GL code hint first: it is the most structured signal an ERP gives us.
    if item.gl_code:
        code = item.gl_code.strip()[:4]
        hint = _GL_HINTS.get(code)
        if hint:
            return _finish(hint, "rule", Decimal("0.90"), f"GL code {item.gl_code} maps to {hint}", f"GL_{code}")

    for rule_id, pat, activity, dim in _RULES:
        if pat.search(text):
            if not _dimension_ok(item, dim):
                # Keyword matched but the unit is the wrong dimension: leave to the agent with a hint.
                return Classification(
                    method="unclassified", confidence=Decimal("0.3"), activity_type=None,
                    reason=f"Rule {rule_id} matched keyword but unit '{item.unit}' is not {dim}; needs review", rule_id=rule_id,
                )
            conf = Decimal("0.95") if rule_id.startswith("R0") or rule_id.startswith("R1") else Decimal("0.80")
            return _finish(activity, "rule", conf, f"Rule {rule_id} matched '{pat.pattern[:40]}...'", rule_id)

    return Classification(method="unclassified", confidence=Decimal("0"), reason="No rule matched; sent to classifier agent")


def _finish(activity: str, method: str, conf: Decimal, reason: str, rule_id: str) -> Classification:
    from ..factors.matcher import ACTIVITY_TYPES

    meta = ACTIVITY_TYPES[activity]
    return Classification(
        scope=meta["scope"], scope3_category=meta.get("cat"), activity_type=activity,
        method=method, confidence=conf, reason=reason, rule_id=rule_id,
    )


def apply_agent_label(activity: Optional[str], confidence: Decimal, reason: str) -> Classification:
    """Build a Classification from a validated agent response. Unknown keys are rejected."""
    from ..factors.matcher import ACTIVITY_TYPES

    if not activity or activity not in ACTIVITY_TYPES:
        return Classification(method="unclassified", confidence=Decimal("0"), reason=f"Agent returned unknown activity_type '{activity}'; rejected")
    meta = ACTIVITY_TYPES[activity]
    return Classification(
        scope=meta["scope"], scope3_category=meta.get("cat"), activity_type=activity,
        method="agent", confidence=confidence, reason=reason,
    )
