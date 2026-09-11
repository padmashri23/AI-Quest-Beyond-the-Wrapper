"""Utility-bill PDF ingestion.

Extracts text with pdfplumber and pulls consumption lines with unit-aware regexes.
This is deliberately conservative: a bill line becomes a LineItem only when a number
and a recognised unit sit on the same line. Everything else is kept (redacted) as
context for the classifier agent but never turns into a quantity.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal
from typing import Optional

import pdfplumber

from ..guardrails.pii import redact_text
from ..schemas import LineItem

_QTY_LINE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z /&()-]{2,60}?)\s*[:\-]?\s*(?P<qty>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>kWh|MWh|therms?|mmBtu|MMBtu|ccf|scf|litres?|liters?|L\b|gallons?|gal\b|m3|m³|tonnes?|kg)\b",
    re.I,
)
_DATE = re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4})")
_REGION_HINTS = {
    "GB": re.compile(r"\b(United Kingdom|UK|England|Scotland|Wales|Ltd|plc|Ofgem)\b"),
    "US": re.compile(r"\b(USA|United States|Inc\.|LLC|[A-Z]{2} \d{5})\b"),
    "DE": re.compile(r"\b(GmbH|Deutschland|Germany)\b"),
    "IN": re.compile(r"\b(India|Pvt\.? Ltd|Bengaluru|Chennai|Mumbai)\b"),
}
_EGRID = re.compile(r"\b(CAMX|ERCT|NYUP|RFCW|SRSO|NWPP)\b")

_SKIP_LABELS = re.compile(r"\b(rate|price|charge|tariff|standing|vat|amount)\b|[£$€]", re.I)


def parse_pdf(filename: str, content: bytes) -> list[LineItem]:
    items: list[LineItem] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            region = _guess_region(text)
            date = _first_date(text)
            vendor = _guess_vendor(text)
            kind = _doc_kind(text)
            page_items: list[LineItem] = []
            for lno, line in enumerate(text.splitlines(), start=1):
                m = _QTY_LINE.search(line)
                if not m:
                    continue
                label = m.group("label").strip()
                if _SKIP_LABELS.search(label) or _SKIP_LABELS.search(line[: m.start("qty")]):
                    continue
                qty = Decimal(m.group("qty").replace(",", ""))
                unit = m.group("unit")
                red_line, kinds = redact_text(line)
                red_vendor, k2 = redact_text(vendor)
                page_items.append(
                    LineItem(
                        line_id=f"{_slug(filename)}-p{pno}-l{lno}",
                        source_file=filename,
                        source_ref=f"page {pno}, line {lno}",
                        date=date,
                        period=f"FY{date[-4:]}" if date and date[-4:].isdigit() else None,
                        vendor=red_vendor,
                        description=f"{label} ({kind})",
                        quantity=qty,
                        unit=unit,
                        region=region,
                        raw_text=red_line,
                        redactions=sorted(set(kinds + k2)),
                    )
                )
            items.extend(_prefer_reportable(page_items, kind))
    return items


def _guess_region(text: str) -> Optional[str]:
    eg = _EGRID.search(text)
    if eg:
        return eg.group(1)
    for code, pat in _REGION_HINTS.items():
        if pat.search(text):
            return code
    return None


def _first_date(text: str) -> Optional[str]:
    m = _DATE.search(text)
    return m.group(1) if m else None


def _guess_vendor(text: str) -> Optional[str]:
    for line in text.splitlines()[:6]:
        s = line.strip()
        if 3 < len(s) < 60 and not re.search(r"\d{3,}", s) and not s.lower().startswith(("invoice", "bill", "statement", "account")):
            return s
    return None


def _doc_kind(text: str) -> str:
    t = text.lower()
    # Strong signals only: a supplier called "Pacific Gas and Electric" must not turn an electric statement into a gas bill.
    if re.search(r"gas statement|gas bill|natural gas|therms?\b|calorific|gas supply|\bm3 corrected", t):
        return "gas bill"
    if re.search(r"electric", t):
        return "electricity bill"
    if "water" in t:
        return "water bill"
    return "utility bill"


def _prefer_reportable(items: list[LineItem], kind: str) -> list[LineItem]:
    """A bill often lists peak, off-peak and total: keep only the total so the site is
    counted once. A gas bill lists corrected volume (m3) and energy (kWh): keep the kWh
    line, since the energy factor is the official one and the CV is bill-specific."""
    totals = [i for i in items if re.search(r"\btotal\b", i.description, re.I)]
    if totals:
        return totals
    if kind == "gas bill":
        energy = [i for i in items if (i.unit or "").lower() in {"kwh", "mwh", "therm", "therms", "mmbtu"}]
        if energy:
            return energy
    return items


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.rsplit(".", 1)[0].lower()).strip("-")[:24]
