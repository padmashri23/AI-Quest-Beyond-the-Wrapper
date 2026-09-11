"""CSV / Excel ingestion for ERP exports, travel logs and freight logs.

Column names are mapped through a synonym table so the same parser handles SAP,
NetSuite, Concur and hand-made spreadsheets. Quantities are parsed to Decimal from the
original string, never through float.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

import pandas as pd

from ..guardrails.pii import redact_text, strip_sensitive_fields
from ..schemas import LineItem

_SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "posting date", "invoice date", "doc date", "trip date", "period", "transaction date"],
    "vendor": ["vendor", "supplier", "payee", "merchant", "carrier", "provider", "vendor name", "supplier name"],
    "description": ["description", "line description", "item", "memo", "narrative", "text", "details", "route", "expense type"],
    "gl_code": ["gl code", "gl", "account code", "gl account", "cost element", "nominal code", "gl_code"],
    "quantity": ["quantity", "qty", "usage", "consumption", "volume", "distance", "amount consumed", "units consumed", "kwh", "litres", "km", "miles", "nights", "tonne_km", "weight", "quantity_value"],
    "unit": ["unit", "uom", "unit of measure", "units", "measure", "quantity_unit"],
    "region": ["region", "country", "site country", "location", "site", "egrid subregion", "grid region", "country code"],
    "spend": ["amount", "spend", "total", "net amount", "cost", "value", "invoice amount", "line total", "price"],
    "currency": ["currency", "ccy", "cur"],
    "passengers": ["passengers", "pax", "travellers", "travelers"],
    "weight_tonnes": ["weight tonnes", "weight_t", "tonnes", "cargo weight", "payload tonnes", "weight (t)"],
    "distance_km": ["distance km", "distance_km", "km", "leg distance"],
    "mode": ["mode", "travel mode", "transport mode", "service"],
    "travel_class": ["class", "cabin", "cabin class", "vehicle type", "vehicle"],
}


def _map_columns(cols: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    lowered = {c: re.sub(r"[^a-z0-9 _()]", "", str(c).strip().lower()) for c in cols}
    for canon, syns in _SYNONYMS.items():
        for c, low in lowered.items():
            if c in mapping:
                continue
            if low in syns or low.replace("_", " ") in syns:
                mapping[c] = canon
                break
    return mapping


def _dec(v) -> Optional[Decimal]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip().replace(",", "")
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _str(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def _period(date: Optional[str]) -> Optional[str]:
    if not date:
        return None
    m = re.search(r"(20\d{2})", date)
    return f"FY{m.group(1)}" if m else None


def parse_tabular(filename: str, content: bytes) -> list[LineItem]:
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(content), dtype=str)
    else:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    df.columns = [str(c) for c in df.columns]
    mapping = _map_columns(df.columns)
    inv = {v: k for k, v in mapping.items()}

    items: list[LineItem] = []
    for idx, row in df.iterrows():
        raw = {c: _str(row[c]) for c in df.columns}
        get = lambda canon: raw.get(inv[canon]) if canon in inv else None  # noqa: E731

        quantity = _dec(get("quantity"))
        unit = get("unit")

        # Derived quantities for travel / freight logs.
        pax = _dec(get("passengers"))
        dist = _dec(get("distance_km"))
        wt = _dec(get("weight_tonnes"))
        mode_text = " ".join(filter(None, [get("description"), get("mode")])).lower()
        vehicle_mode = bool(re.search(r"\b(car|taxi|hire|rental|uber|van|mileage)\b", mode_text))
        if quantity is None and dist is not None:
            if wt is not None:
                quantity, unit = dist * wt, "tonne_km"
            elif vehicle_mode:
                quantity, unit = dist, "km"  # car factors are per vehicle-km, not passenger-km
            elif pax is not None:
                quantity, unit = dist * pax, "passenger_km"
            else:
                quantity, unit = dist, unit or "km"
        if quantity is None and re.search(r"\b(hotel|nights?|stay)\b", mode_text):
            nm = re.search(r"(\d+)\s*nights?", mode_text)
            if nm:
                quantity, unit = Decimal(nm.group(1)) * (pax or Decimal("1")), "room_night"

        # Unit may be embedded in the quantity column name, e.g. "kWh".
        if unit is None and "quantity" in inv and inv["quantity"].strip().lower() in {"kwh", "litres", "km", "miles", "nights", "tonne_km"}:
            unit = inv["quantity"].strip()

        desc = " ".join(filter(None, [get("description"), get("mode"), get("travel_class")])).strip()
        vendor = get("vendor")
        safe_raw = strip_sensitive_fields(raw)
        raw_line = " | ".join(f"{k}={v}" for k, v in safe_raw.items() if v not in (None, ""))
        red_text, kinds = redact_text(raw_line)
        red_desc, kinds2 = redact_text(desc)
        red_vendor, kinds3 = redact_text(vendor)

        date = get("date")
        items.append(
            LineItem(
                line_id=f"{_slug(filename)}-r{idx + 2}",
                source_file=filename,
                source_ref=f"row {idx + 2}",
                date=date,
                period=_period(date),
                vendor=red_vendor,
                description=red_desc or "(no description)",
                gl_code=get("gl_code"),
                quantity=quantity,
                unit=unit,
                region=get("region"),
                spend=_dec(get("spend")),
                currency=get("currency"),
                raw_text=red_text,
                redactions=sorted(set(kinds + kinds2 + kinds3)),
            )
        )
    return items


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.rsplit(".", 1)[0].lower()).strip("-")[:24]
