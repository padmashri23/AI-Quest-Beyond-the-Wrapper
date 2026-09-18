"""Dispatch a file to the right parser by extension."""
from __future__ import annotations
import io
import zipfile

from ..schemas import LineItem
from .pdf_bills import parse_pdf
from .tabular import parse_tabular

SUPPORTED = (".csv", ".xlsx", ".xls", ".pdf")


def ingest_file(filename: str, content: bytes) -> list[LineItem]:
    low = filename.lower()
    if low.endswith(".pdf"):
        return parse_pdf(filename, content)
    if low.endswith((".csv", ".xlsx", ".xls")):
        if low.endswith('.xlsx'):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if len(archive.infolist())>5000 or sum(i.file_size for i in archive.infolist())>100*1024*1024:
                        raise ValueError('Workbook expanded content exceeds ingestion limits')
            except zipfile.BadZipFile as exc:
                raise ValueError('Invalid XLSX container') from exc
        return parse_tabular(filename, content)
    raise ValueError(f"Unsupported file type: {filename}. Supported: {', '.join(SUPPORTED)}")
