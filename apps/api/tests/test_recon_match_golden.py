"""REC-001..004 golden scenarios: deterministic sales↔JoFotara matching.

Synthetic Jordan-flavored fixtures only (never customer data): English/Arabic
issuers, JOD 3dp amounts, leading-zero identifiers, credit notes.
"""

from datetime import date
from decimal import Decimal

from app.recon import (
    AMBIGUOUS,
    AMOUNT_MISMATCH,
    CREDIT_NOTE_LINKED,
    DUPLICATE_JOFOTARA,
    DUPLICATE_SALES,
    EXACT_MATCH,
    INSUFFICIENT_DATA,
    REVERSAL_NOTED,
    UNMATCHED_JOFOTARA,
    UNMATCHED_SALES,
    CanonicalInvoice,
    InvoiceProvenance,
    ReconcileRequest,
    reconcile,
)

ISSUER_EN = "Example Trading LLC"
ISSUER_AR = "شركة المثال للتجارة"
PERIOD = (date(2026, 1, 1), date(2026, 12, 31))


def prov(dataset: str, source: str, row: int, raw: str) -> InvoiceProvenance:
    return InvoiceProvenance(dataset_id=dataset, source=source, row_number=row, raw_invoice=raw)


def sales_inv(
    number: str, amount: str | None, issuer: str = ISSUER_EN, row: int = 2, **kw
) -> CanonicalInvoice:
    return CanonicalInvoice(
        issuer=issuer,
        number=number,
        amount=Decimal(amount) if amount is not None else None,
        amount_raw=amount or "",
        currency=kw.get("currency", "JOD"),
        transaction_date=kw.get("date", date(2026, 3, 15)),
        is_credit_note=kw.get("credit", False),
        is_reversal=kw.get("reversal", False),
        provenance=prov("SYN-SALES", "sales_register", row, number),
    )


def jofo_inv(
    number: str, amount: str | None, issuer: str = ISSUER_EN, row: int = 2, **kw
) -> CanonicalInvoice:
    return CanonicalInvoice(
        issuer=issuer,
        number=number,
        amount=Decimal(amount) if amount is not None else None,
        amount_raw=amount or "",
        currency=kw.get("currency", "JOD"),
        transaction_date=kw.get("date", date(2026, 3, 16)),
        is_credit_note=kw.get("credit", False),
        is_reversal=kw.get("reversal", False),
        provenance=prov("SYN-JOFO", "jofotara_export", row, number),
    )


def req(**kw) -> ReconcileRequest:
    base: dict = {
        "tenant_id": "tenant-syn-1",
        "sales_dataset_id": "SYN-SALES",
        "jofo_dataset_id": "SYN-JOFO",
        "jurisdiction": "JO",
        "period_start": PERIOD[0],
        "period_end": PERIOD[1],
    }
    base.update(kw)
    return ReconcileRequest(**base)


def kinds(report) -> list:  # type: ignore[no-untyped-def]
    return [o.kind for o in report.outcomes]


def test_exact_match_identical_invoice_amount_currency() -> None:
    report = reconcile((sales_inv("INV-0001", "15000.000"),), (jofo_inv("INV-0001", "15000.000"),), req())
    assert kinds(report) == [EXACT_MATCH]
    outcome = report.outcomes[0]
    assert outcome.rule == "JO/REC-003/1" and outcome.delta == Decimal("0") and outcome.currency == "JOD"


def test_exact_match_arabic_issuer() -> None:
    report = reconcile(
        (sales_inv("000123", "450.000", issuer=ISSUER_AR),),
        (jofo_inv("000123", "450.000", issuer=ISSUER_AR),),
        req(),
    )
    assert kinds(report) == [EXACT_MATCH]


def test_unmatched_both_directions() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"), sales_inv("INV-002", "200.000")),
        (jofo_inv("INV-002", "200.000"), jofo_inv("INV-009", "50.000")),
        req(),
    )
    by_kind = kinds(report)
    assert by_kind.count(UNMATCHED_SALES) == 1 and by_kind.count(UNMATCHED_JOFOTARA) == 1
    assert by_kind.count(EXACT_MATCH) == 1
    unmatched = next(o for o in report.outcomes if o.kind == UNMATCHED_SALES)
    assert unmatched.rule == "JO/REC-001/1" and unmatched.sales[0].number == "INV-001"
    assert unmatched.jofo == () and unmatched.delta is None


def test_amount_mismatch_exact_decimal_difference() -> None:
    report = reconcile((sales_inv("INV-001", "15000.000"),), (jofo_inv("INV-001", "14550.000"),), req())
    assert kinds(report) == [AMOUNT_MISMATCH]
    outcome = report.outcomes[0]
    assert outcome.delta == Decimal("450.000") and outcome.rule == "JO/REC-003/1"


def test_duplicate_sales_keys_never_matched() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000", row=2), sales_inv("INV-001", "100.000", row=3)),
        (jofo_inv("INV-001", "100.000"),),
        req(),
    )
    assert kinds(report) == [DUPLICATE_SALES, UNMATCHED_JOFOTARA]
    assert len(report.outcomes[0].sales) == 2
    assert "fraud" not in str(report.outcomes[0].rationale).lower()


def test_duplicate_jofotara_keys_listed_not_matched() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (jofo_inv("INV-001", "100.000", row=2), jofo_inv("INV-001", "200.000", row=3)),
        req(),
    )
    assert kinds(report) == [DUPLICATE_JOFOTARA, UNMATCHED_SALES]


def test_currency_mismatch_is_ambiguous_without_delta() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000", currency="JOD"),),
        (jofo_inv("INV-001", "100.000", currency="USD"),),
        req(),
    )
    assert kinds(report) == [AMBIGUOUS]
    outcome = report.outcomes[0]
    assert outcome.delta is None and outcome.currency is None
    assert "CURRENCY_MISMATCH" in outcome.rationale


def test_credit_note_overlap_is_ambiguous_and_linked() -> None:
    # JoFotara holds the invoice AND its credit note: the invoice still matches
    # exactly, but the overlap needs human confirmation (nothing auto-netted).
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (jofo_inv("INV-001", "100.000"), jofo_inv("INV-001", "100.000", credit=True, row=5)),
        req(),
    )
    assert kinds(report) == [EXACT_MATCH, AMBIGUOUS, CREDIT_NOTE_LINKED]
    ambiguous = next(o for o in report.outcomes if o.kind == AMBIGUOUS)
    assert "CREDIT_NOTE_OVERLAP" in ambiguous.rationale
    assert "REVIEW_ISSUER_AND_CREDIT" in ambiguous.flags


def test_two_credit_notes_same_key_cluster_as_duplicates() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (
            jofo_inv("INV-001", "100.000"),
            jofo_inv("INV-001", "40.000", credit=True, row=5),
            jofo_inv("INV-001", "60.000", credit=True, row=6),
        ),
        req(),
    )
    assert kinds(report) == [DUPLICATE_JOFOTARA, EXACT_MATCH]
    assert len(next(o for o in report.outcomes if o.kind == DUPLICATE_JOFOTARA).jofo) == 2


def test_standalone_credit_note_linked_not_netted() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"), sales_inv("CN-001", "20.000", credit=True, row=3)),
        (jofo_inv("INV-001", "100.000"),),
        req(),
    )
    assert CREDIT_NOTE_LINKED in kinds(report)
    linked = next(o for o in report.outcomes if o.kind == CREDIT_NOTE_LINKED)
    assert linked.delta is None  # never netted into an amount
    assert "CREDIT_NOTE_PRESERVED" in linked.rationale


def test_reversal_noted_with_lineage() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (jofo_inv("INV-001", "100.000"), jofo_inv("INV-001-R", "100.000", reversal=True, row=6)),
        req(),
    )
    assert REVERSAL_NOTED in kinds(report)
    noted = next(o for o in report.outcomes if o.kind == REVERSAL_NOTED)
    assert noted.jofo[0].provenance is not None
    assert noted.jofo[0].provenance.row_number == 6


def test_missing_values_are_insufficient_never_zero() -> None:
    report = reconcile(
        (
            sales_inv("INV-001", None),
            sales_inv("", "10.000", row=3),
            sales_inv("INV-003", "10.000", currency=None, row=4),
        ),
        (jofo_inv("INV-001", "10.000"),),
        req(),
    )
    insufficient = [o for o in report.outcomes if o.kind == INSUFFICIENT_DATA]
    assert len(insufficient) == 3
    assert any("MISSING_AMOUNT" in o.rationale for o in insufficient)
    assert not any(o.kind == EXACT_MATCH for o in report.outcomes)


def test_leading_zeros_significant() -> None:
    report = reconcile((sales_inv("000123", "10.000"),), (jofo_inv("123", "10.000"),), req())
    assert kinds(report) == [UNMATCHED_SALES, UNMATCHED_JOFOTARA]
    same = reconcile((sales_inv("000123", "10.000"),), (jofo_inv("000123", "10.000"),), req())
    assert kinds(same) == [EXACT_MATCH]


def test_mixed_currencies_never_combined() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000", currency="JOD"), sales_inv("INV-002", "100.000", currency="USD")),
        (
            jofo_inv("INV-001", "100.000", currency="USD"),
            jofo_inv("INV-002", "100.000", currency="JOD"),
        ),
        req(),
    )
    assert kinds(report) == [AMBIGUOUS, AMBIGUOUS]
    assert all(o.delta is None for o in report.outcomes)


def test_period_positions_surfaced_not_dropped() -> None:
    report = reconcile(
        (sales_inv("INV-001", "10.000", date=date(2025, 6, 1)),),
        (jofo_inv("INV-001", "10.000", date=date(2026, 3, 16)),),
        req(),
    )
    assert kinds(report) == [EXACT_MATCH]
    assert "PERIOD_OUTSIDE" in report.outcomes[0].flags


def test_determinism_under_reordered_input() -> None:
    sales = tuple(sales_inv(f"INV-{i:03d}", f"{i * 10}.000", row=i) for i in range(1, 9))
    jofo = tuple(jofo_inv(f"INV-{i:03d}", f"{i * 10}.000", row=i) for i in range(2, 10))
    first = reconcile(sales, jofo, req())
    second = reconcile(tuple(reversed(sales)), tuple(reversed(jofo)), req())
    assert first.fingerprint == second.fingerprint
    assert [(o.kind, o.delta) for o in first.outcomes] == [(o.kind, o.delta) for o in second.outcomes]


def test_evidence_lineage_preserved() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000", row=7),), (jofo_inv("INV-001", "100.000", row=9),), req()
    )
    outcome = report.outcomes[0]
    assert outcome.sales[0].provenance is not None and outcome.jofo[0].provenance is not None
    assert outcome.sales[0].provenance.dataset_id == "SYN-SALES"
    assert outcome.sales[0].provenance.row_number == 7
    assert outcome.jofo[0].provenance.dataset_id == "SYN-JOFO"
    assert outcome.jofo[0].provenance.row_number == 9
    assert outcome.sales[0].provenance.raw_invoice == "INV-001"


def test_tenant_scoping_echoed_in_report_and_fingerprint() -> None:
    sales = (sales_inv("INV-001", "10.000"),)
    jofo = (jofo_inv("INV-001", "10.000"),)
    first = reconcile(sales, jofo, req(tenant_id="tenant-a"))
    second = reconcile(sales, jofo, req(tenant_id="tenant-b"))
    assert first.tenant_id == "tenant-a" and second.tenant_id == "tenant-b"
    assert first.fingerprint != second.fingerprint  # scope is identity-bound


def test_exact_delta_precision_under_hostile_context() -> None:
    import decimal

    big_sales = "12345678901234567890123456789.12345"
    big_jofo = "12345678901234567890123456789.12346"
    with decimal.localcontext() as ctx:
        ctx.prec = 10  # hostile ambient precision; engine stays exact anyway
        report = reconcile((sales_inv("INV-001", big_sales),), (jofo_inv("INV-001", big_jofo),), req())
    assert kinds(report) == [AMOUNT_MISMATCH]
    assert report.outcomes[0].delta == Decimal("-0.00001")


def test_no_fraud_or_violation_language_anywhere() -> None:
    report = reconcile(
        (
            sales_inv("INV-001", "100.000", row=2),
            sales_inv("INV-001", "200.000", row=3),
            sales_inv("INV-002", "50.000", currency="USD"),
        ),
        (jofo_inv("INV-001", "100.000", currency="USD"), jofo_inv("INV-002", "50.000", currency="JOD")),
        req(),
    )
    text = " ".join(
        f"{o.kind} {o.rule} {' '.join(o.rationale)} {' '.join(o.flags)}" for o in report.outcomes
    ).lower()
    for forbidden in ("fraud", "evasion", "violation", "liabilit", "non-compliant", "guilt"):
        assert forbidden not in text


def test_demo_slice_mixed_jordan_workbook() -> None:
    sales = (
        sales_inv("INV-0001", "15000.000", row=2),
        sales_inv("INV-0002", "450.000", row=3),
        sales_inv("000123", "1200.000", issuer=ISSUER_AR, row=4),
        sales_inv("CN-0009", "75.000", credit=True, row=5),
    )
    jofo = (
        jofo_inv("INV-0001", "15000.000", row=2),
        jofo_inv("000123", "1200.000", issuer=ISSUER_AR, row=3),
        jofo_inv("INV-0077", "310.000", row=4),
    )
    report = reconcile(sales, jofo, req())
    assert report.counts["EXACT_MATCH"] == 2
    assert report.counts["UNMATCHED_SALES"] == 1  # INV-0002 (450.000)
    assert report.counts["UNMATCHED_JOFOTARA"] == 1  # INV-0077
    assert report.counts["CREDIT_NOTE_LINKED"] == 1
    assert report.sales_total == 4 and report.jofo_total == 3
    assert len(report.fingerprint) == 64
