"""Deterministic unit conversion.

All factors are exact Decimals with a documented source. Conversion is only allowed
within a dimension; crossing dimensions (e.g. litres to kWh) is refused so a mis-typed
invoice column can never silently become a plausible number.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..schemas import ConversionStep

# Canonical unit name -> (dimension, factor to the dimension's base unit, source)
# Base units: energy=kWh, volume=litre, mass=kg, distance=km, tonne_km, passenger_km,
# room_night, m3 (water), unit (count), usd (spend)
_UNITS: dict[str, tuple[str, Decimal, str]] = {
    # energy
    "kWh": ("energy", Decimal("1"), "SI"),
    "MWh": ("energy", Decimal("1000"), "SI"),
    "GWh": ("energy", Decimal("1000000"), "SI"),
    "therm": ("energy", Decimal("29.3001"), "EPA GHG Emission Factors Hub 2024, 1 therm = 0.1 mmBtu; 1 mmBtu = 293.001 kWh (EIA)"),
    "mmBtu": ("energy", Decimal("293.001"), "EIA: 1 mmBtu = 293.001 kWh"),
    "MMBtu": ("energy", Decimal("293.001"), "EIA: 1 mmBtu = 293.001 kWh"),
    "scf_natural_gas": ("energy", Decimal("0.303874"), "EPA Hub 2024 Table 1: 1,000 scf natural gas = 1.037 mmBtu; x 293.001 kWh/mmBtu / 1000"),
    "GJ": ("energy", Decimal("277.777777777777777778"), "SI: 1 GJ = 277.78 kWh"),
    # volume
    "litre": ("volume", Decimal("1"), "SI"),
    "L": ("volume", Decimal("1"), "SI"),
    "m3_fuel": ("volume", Decimal("1000"), "SI"),
    "us_gallon": ("volume", Decimal("3.785411784"), "NIST: 1 US gallon = 3.785411784 L (exact)"),
    "gallon": ("volume", Decimal("3.785411784"), "NIST: 1 US gallon = 3.785411784 L (exact)"),
    "uk_gallon": ("volume", Decimal("4.54609"), "UK Weights and Measures Act: 1 imperial gallon = 4.54609 L (exact)"),
    # mass
    "kg": ("mass", Decimal("1"), "SI"),
    "tonne": ("mass", Decimal("1000"), "SI"),
    "t": ("mass", Decimal("1000"), "SI"),
    "lb": ("mass", Decimal("0.45359237"), "NIST: 1 lb = 0.45359237 kg (exact)"),
    "short_ton": ("mass", Decimal("907.18474"), "NIST: 1 short ton = 2000 lb = 907.18474 kg"),
    # distance
    "km": ("distance", Decimal("1"), "SI"),
    "mile": ("distance", Decimal("1.609344"), "NIST: 1 mile = 1.609344 km (exact)"),
    "miles": ("distance", Decimal("1.609344"), "NIST: 1 mile = 1.609344 km (exact)"),
    # freight
    "tonne_km": ("freight", Decimal("1"), "SI"),
    "ton_mile": ("freight", Decimal("1.459972"), "1 short-ton-mile = 0.90718474 t x 1.609344 km = 1.459972 tonne-km"),
    # passenger travel
    "passenger_km": ("travel", Decimal("1"), "SI"),
    "passenger_mile": ("travel", Decimal("1.609344"), "NIST: 1 mile = 1.609344 km (exact)"),
    # water
    "m3": ("water", Decimal("1"), "SI"),
    "kL": ("water", Decimal("1"), "SI"),
    # accommodation
    "room_night": ("accommodation", Decimal("1"), "count"),
    # waste
    "tonne_waste": ("waste", Decimal("1"), "SI"),
    "kg_waste": ("waste", Decimal("0.001"), "SI"),
    # spend
    "usd": ("spend", Decimal("1"), "USD, 2022 price year for USEEIO factors"),
    "USD": ("spend", Decimal("1"), "USD, 2022 price year for USEEIO factors"),
}

_ALIASES = {
    "kwh": "kWh", "mwh": "MWh", "gwh": "GWh", "therms": "therm", "thm": "therm",
    "mmbtu": "mmBtu", "l": "litre", "liter": "litre", "liters": "litre", "litres": "litre", "ltr": "litre",
    "gal": "us_gallon", "gallons": "us_gallon", "us gal": "us_gallon",
    "kgs": "kg", "kilogram": "kg", "kilograms": "kg", "tonnes": "tonne", "metric ton": "tonne", "mt": "tonne",
    "lbs": "lb", "pounds": "lb", "kilometre": "km", "kilometer": "km", "kms": "km", "mi": "mile",
    "tkm": "tonne_km", "tonne-km": "tonne_km", "t.km": "tonne_km", "ton-mile": "ton_mile", "ton_miles": "ton_mile",
    "pkm": "passenger_km", "passenger-km": "passenger_km", "pax_km": "passenger_km", "passenger_kms": "passenger_km",
    "nights": "room_night", "room_nights": "room_night", "room-night": "room_night", "night": "room_night",
    "scf": "scf_natural_gas", "ccf": "ccf", "m³": "m3", "cubic_metre": "m3", "cubic_meter": "m3",
    "$": "usd", "us$": "usd",
}
# ccf (hundred cubic feet) of natural gas = 100 scf
_UNITS["ccf"] = ("energy", Decimal("100") * _UNITS["scf_natural_gas"][1], "1 ccf = 100 scf; see scf_natural_gas")


def normalise_unit(unit: Optional[str]) -> Optional[str]:
    if unit is None:
        return None
    u = unit.strip()
    if u in _UNITS:
        return u
    low = u.lower().replace(" ", "_")
    if low in _ALIASES:
        return _ALIASES[low]
    for k in _UNITS:
        if k.lower() == low:
            return k
    return None


def dimension_of(unit: str) -> Optional[str]:
    u = normalise_unit(unit)
    return _UNITS[u][0] if u else None


def convert(quantity: Decimal, from_unit: str, to_unit: str) -> tuple[Decimal, Optional[ConversionStep]]:
    """Convert quantity between units of the same dimension. Raises ValueError otherwise."""
    f = normalise_unit(from_unit)
    t = normalise_unit(to_unit)
    if f is None:
        raise ValueError(f"Unknown unit '{from_unit}'")
    if t is None:
        raise ValueError(f"Unknown unit '{to_unit}'")
    if f == t:
        return quantity, None
    fd, ff, fs = _UNITS[f]
    td, tf, ts = _UNITS[t]
    if fd != td:
        raise ValueError(f"Cannot convert {from_unit} ({fd}) to {to_unit} ({td}); dimensions differ")
    ratio = ff / tf
    return quantity * ratio, ConversionStep(from_unit=f, to_unit=t, factor=ratio, source=f"{fs}; {ts}")


def known_units() -> dict[str, dict[str, str]]:
    return {k: {"dimension": v[0], "to_base": str(v[1]), "source": v[2]} for k, v in _UNITS.items()}
