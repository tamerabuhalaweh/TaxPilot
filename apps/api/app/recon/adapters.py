"""Adapters from approved normalized rows into matchable invoices.

Only the sales side has an approved normalized contract today: every sales
register row carries the seller implicitly (the register IS the client's own
invoices), so the caller supplies the selling client's issuer identity
explicitly and each VALID/WARNING row becomes one CanonicalInvoice. FAILED
rows are reported back as skipped (never coerced, never silently dropped).

There is deliberately NO JoFotara adapter: no approved JoFotara mapping
profile exists, and inventing one would fabricate the very contract EP-15
must approve. JoFotara inputs for this slice are explicit synthetic fixtures
(see tests), each carrying its own issuer identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.normalization import NormalizedRow
from app.recon.contracts import SALES_SOURCE, CanonicalInvoice, InvoiceProvenance


@dataclass(frozen=True)
class SkippedRow:
    """A normalized row that could not become an invoice (with reasons)."""

    dataset_id: str
    row_number: int
    status: str
    reason_codes: tuple[str, ...]


def _field(row: NormalizedRow, canonical: str) -> object:
    for candidate in row.fields:
        if candidate.canonical == canonical:
            return candidate.normalized
    return None


def sales_invoices_from_normalized(
    rows: tuple[NormalizedRow, ...], *, dataset_id: str, issuer: str
) -> tuple[tuple[CanonicalInvoice, ...], tuple[SkippedRow, ...]]:
    """Convert READY sales rows into CanonicalInvoices (pure function)."""
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("dataset_id must be a non-blank string")
    if not isinstance(issuer, str) or not issuer.strip():
        raise ValueError("issuer must be a non-blank string (the selling client)")
    invoices: list[CanonicalInvoice] = []
    skipped: list[SkippedRow] = []
    for row in rows:
        if not isinstance(row, NormalizedRow):
            raise TypeError(f"rows must be NormalizedRow, got {type(row).__name__}")
        if row.status == "FAILED":
            skipped.append(
                SkippedRow(
                    dataset_id=dataset_id,
                    row_number=row.row_number,
                    status=row.status,
                    reason_codes=tuple(issue.code for f in row.fields for issue in f.issues)
                    + tuple(issue.code for issue in row.row_issues)
                    or ("ROW_FAILED",),
                )
            )
            continue
        number = _field(row, "invoice_number")
        amount = _field(row, "net_amount")
        currency = _field(row, "currency")
        when = _field(row, "transaction_date")
        invoices.append(
            CanonicalInvoice(
                issuer=issuer,
                number=number if isinstance(number, str) else "",
                amount=amount if isinstance(amount, Decimal) else None,
                amount_raw=next((f.raw for f in row.fields if f.canonical == "net_amount"), ""),
                currency=currency if isinstance(currency, str) else None,
                transaction_date=when if isinstance(when, date) else None,
                provenance=InvoiceProvenance(
                    dataset_id=dataset_id,
                    source=SALES_SOURCE,
                    row_number=row.row_number,
                    raw_invoice=number if isinstance(number, str) else "",
                ),
            )
        )
    return tuple(invoices), tuple(skipped)
