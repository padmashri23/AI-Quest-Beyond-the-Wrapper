"""PII and commercial-sensitivity redaction.

Runs on every row BEFORE anything is handed to a Lyzr agent. Two layers:

1. Structured: spend / unit price / account fields are dropped from the agent payload
   entirely (they stay in the ledger for the audit trail, never in a prompt).
2. Unstructured: free text is scrubbed with regexes for emails, phone numbers, card and
   account numbers, IBANs, national IDs, street addresses and currency amounts.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("phone", re.compile(r"(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)\d{3,4}[ -]?\d{3,4}\b")),
    ("account_number", re.compile(r"\b(?:acct|account|a/c|customer|meter|policy)\s*(?:no\.?|number|#|id)?\s*[:#]?\s*[A-Z0-9-]{6,}\b", re.I)),
    ("currency_amount", re.compile(r"(?:[$£€]|USD|GBP|EUR|INR)\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|GBP|EUR|INR)\b")),
    ("street_address", re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way)\b\.?")),
    ("ssn_nino", re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b")),
]

SENSITIVE_FIELDS = {
    "spend", "currency", "unit_price", "amount", "total", "price", "cost", "invoice_total", "net amount", "line total", "value",
    "account", "account_number", "meter_id", "contact", "email", "phone", "address",
    "traveller", "traveler", "employee", "employee name", "name", "passenger name", "driver", "requester",
}


def redact_text(text: str | None) -> tuple[str | None, list[str]]:
    if not text:
        return text, []
    found: list[str] = []
    out = text
    for kind, pat in _PATTERNS:
        if pat.search(out):
            found.append(kind)
            out = pat.sub(f"[{kind.upper()}]", out)
    return out, found


def strip_sensitive_fields(row: dict) -> dict:
    """Return a copy of a raw row with commercially sensitive keys removed."""
    return {k: v for k, v in row.items() if k.strip().lower() not in SENSITIVE_FIELDS}


def hash_vendor(vendor: str | None) -> str | None:
    """Stable, non-reversible vendor token so agents can group by supplier without seeing the name."""
    if not vendor:
        return None
    import hashlib

    return "VENDOR_" + hashlib.sha256(vendor.strip().lower().encode()).hexdigest()[:8].upper()
