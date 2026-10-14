"""Recon contract tests: invariants, determinism, tolerance, adapter (synthetic)."""

from datetime import date
from decimal import Decimal

import pytest

from app.normalization import NormalizedField, NormalizedRow, SourceLocation
from app.recon import (
    CanonicalInvoice,
    InvoiceProvenance,
    ReconcileRequest,
    reconcile,
    rule_for,
    sales_invoices_from_normalized,
)


def prov(row: int = 2) -> InvoiceProvenance:
    return InvoiceProvenance(dataset_id="SYN", source="sales_register", row_number=row, raw_invoice="INV-1")


def inv(number: str = "INV-1", amount: str | None = "10.000", **kw) -> CanonicalInvoice:
    return CanonicalInvoice(
        issuer=kw.get("issuer", "Example Trading LLC"),
        number=number,
        amount=Decimal(amount) if amount is not None else None,
        amount_raw=amount or "",
        currency=kw.get("currency", "JOD"),
        transaction_date=kw.get("date", date(2026, 3, 15)),
        provenance=prov(kw.get("row", 2)),
    )


def req(**kw) -> ReconcileRequest:
    base: dict = {
        "tenant_id": "tenant-syn-1",
        "sales_dataset_id": "SYN-SALES",
        "jofo_dataset_id": "SYN-JOFO",
        "jurisdiction": "JO",
    }
    base.update(kw)
    return ReconcileRequest(**base)


def test_float_and_int_amounts_rejected() -> None:
    with pytest.raises(TypeError):
        CanonicalInvoice(
            issuer="A",
            number="1",
            amount=0.1,
            amount_raw="0.1",  # type: ignore[arg-type]
            currency="JOD",
            transaction_date=None,
            provenance=prov(),
        )
    with pytest.raises(TypeError):
        CanonicalInvoice(
            issuer="A",
            number="1",
            amount=100,
            amount_raw="100",  # type: ignore[arg-type]
            currency="JOD",
            transaction_date=None,
            provenance=prov(),
        )
    with pytest.raises(ValueError):
        CanonicalInvoice(
            issuer="A",
            number="1",
            amount=Decimal("NaN"),
            amount_raw="NaN",
            currency="JOD",
            transaction_date=None,
            provenance=prov(),
        )
    with pytest.raises(ValueError):
        CanonicalInvoice(
            issuer="A",
            number="1",
            amount=Decimal("1"),
            amount_raw="1",
            currency="JODD",
            transaction_date=None,
            provenance=prov(),
        )


def test_currency_normalized_and_key_rules() -> None:
    row = inv(currency="jod")
    assert row.currency == "JOD"
    assert inv("  INV-001 ").key() == inv("INV-001").key()  # surrounding space ignored
    assert inv("INV-001").key() != inv("inv-001").key()  # case significant: never guessed
    assert inv("000123").key() != inv("123").key()  # leading zeros significant
    assert inv("INV-1", issuer="  شركة المثال  ").key()[0] == "شركة المثال"


def test_rule_references() -> None:
    assert rule_for("UNMATCHED_SALES", "JO", "1") == "JO/REC-001/1"
    assert rule_for("UNMATCHED_JOFOTARA", "JO", "1") == "JO/REC-002/1"
    assert rule_for("AMOUNT_MISMATCH", "JO", "1") == "JO/REC-003/1"
    assert rule_for("DUPLICATE_SALES", "JO", "1") == "JO/REC-004/1"
    assert rule_for("CREDIT_NOTE_LINKED", "JO", "1") == "JO/NOTE/1"


def test_request_validation() -> None:
    with pytest.raises(ValueError):
        req(tenant_id="  ")
    with pytest.raises(TypeError):
        req(tolerance=0.01)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        req(tolerance=Decimal("-0.01"))


def test_tolerance_boundary_explicit() -> None:
    sales = (inv("INV-1", "100.005"),)
    jofo = (inv("INV-1", "100.000"),)
    strict = reconcile(sales, jofo, req())
    assert strict.outcomes[0].kind == "AMOUNT_MISMATCH"
    allowed = reconcile(sales, jofo, req(tolerance=Decimal("0.01")))
    assert allowed.outcomes[0].kind == "EXACT_MATCH"
    assert "WITHIN_TOLERANCE" in allowed.outcomes[0].flags
    assert allowed.tolerance == Decimal("0.01")


def test_empty_inputs_stable_report() -> None:
    first = reconcile((), (), req())
    second = reconcile((), (), req())
    assert first.outcomes == () and first.counts == {}
    assert first.fingerprint == second.fingerprint and len(first.fingerprint) == 64
    assert (first.sales_total, first.jofo_total) == (0, 0)


def test_input_types_rejected() -> None:
    with pytest.raises(TypeError):
        reconcile([inv()], (inv(),), req())  # type: ignore[list-item]
    with pytest.raises(TypeError):
        reconcile((inv(),), (inv(),), "request")  # type: ignore[arg-type]


def _norm_row(
    row_number: int, number: str, amount: str, currency: str = "JOD", status: str = "VALID"
) -> NormalizedRow:
    loc = SourceLocation(
        doc_id="SYN", content_hash="h", worksheet="Sheet1", row_number=row_number, column_index=0, header="H"
    )
    return NormalizedRow(
        row_number=row_number,
        status=status,
        fields=(
            NormalizedField(
                canonical="invoice_number",
                raw=number,
                normalized=number,
                currency=None,
                location=loc,
                issues=(),
            ),
            NormalizedField(
                canonical="transaction_date",
                raw="05/01/2026",
                normalized=date(2026, 1, 5),
                currency=None,
                location=loc,
                issues=(),
            ),
            NormalizedField(
                canonical="net_amount",
                raw=amount,
                normalized=Decimal(amount),
                currency=currency,
                location=loc,
                issues=(),
            ),
            NormalizedField(
                canonical="currency",
                raw=currency,
                normalized=currency,
                currency=currency,
                location=loc,
                issues=(),
            ),
        ),
    )


def test_sales_adapter_valid_and_failed_rows() -> None:
    rows = (
        _norm_row(2, "000123", "1234.500"),
        _norm_row(3, "INV-9", "10.000", status="FAILED"),
    )
    invoices, skipped = sales_invoices_from_normalized(rows, dataset_id="SYN-S", issuer="Example Trading LLC")
    assert len(invoices) == 1 and len(skipped) == 1
    assert invoices[0].number == "000123" and invoices[0].amount == Decimal("1234.500")
    assert invoices[0].issuer == "Example Trading LLC"
    assert invoices[0].provenance.row_number == 2
    assert skipped[0].row_number == 3


def test_sales_adapter_rejects_bad_arguments() -> None:
    with pytest.raises(ValueError):
        sales_invoices_from_normalized((), dataset_id=" ", issuer="X")
    with pytest.raises(ValueError):
        sales_invoices_from_normalized((), dataset_id="S", issuer=" ")
    with pytest.raises(TypeError):
        sales_invoices_from_normalized(("nope",), dataset_id="S", issuer="X")  # type: ignore[tuple-item]


def test_adapter_end_to_end_exact_match() -> None:
    invoices, skipped = sales_invoices_from_normalized(
        (_norm_row(2, "INV-0001", "15000.000"),), dataset_id="SYN-S", issuer="Example Trading LLC"
    )
    assert skipped == ()
    jofo = (
        CanonicalInvoice(
            issuer="Example Trading LLC",
            number="INV-0001",
            amount=Decimal("15000.000"),
            amount_raw="15000.000",
            currency="JOD",
            transaction_date=date(2026, 1, 6),
            provenance=InvoiceProvenance(
                dataset_id="SYN-J", source="jofotara_export", row_number=2, raw_invoice="INV-0001"
            ),
        ),
    )
    report = reconcile(invoices, jofo, req())
    assert [o.kind for o in report.outcomes] == ["EXACT_MATCH"]
