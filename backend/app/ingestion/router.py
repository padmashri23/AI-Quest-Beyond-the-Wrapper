"""Dispatch a file to the right parser by extension."""
from __future__ import annotations

from ..schemas import LineItem
from .pdf_bills import parse_pdf
from .tabular import parse_tabular

SUPPORTED = (".csv", ".xlsx", ".xls", ".pdf")


def ingest_file(filename: str, content: bytes) -> list[LineItem]:
    low = filename.lower()
    if low.endswith(".pdf"):
        return parse_pdf(filename, content)
    if low.endswith((".csv", ".xlsx", ".xls")):
        return parse_tabular(filename, content)
    raise ValueError(f"Unsupported file type: {filename}. Supported: {', '.join(SUPPORTED)}")
