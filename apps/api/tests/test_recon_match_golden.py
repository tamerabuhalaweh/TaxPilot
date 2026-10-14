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
    CREDIT_NOTE_UNVERIFIED,
    DUPLICATE_JOFOTARA,
    DUPLICATE_SALES,
    EXACT_MATCH,
    INSUFFICIENT_DATA,
    REVERSAL_NOTED,
    REVERSAL_UNVERIFIED,
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
        reference_number=kw.get("reference_number"),
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
        reference_number=kw.get("reference_number"),
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
    assert kinds(report) == [DUPLICATE_SALES, AMBIGUOUS]
    assert len(report.outcomes[0].sales) == 2
    ambiguous = next(o for o in report.outcomes if o.kind == AMBIGUOUS)
    assert "DUPLICATE_COUNTERPART" in ambiguous.rationale
    assert len(ambiguous.sales) == 2 and len(ambiguous.jofo) == 1
    assert "fraud" not in str(report.outcomes[0].rationale).lower()


def test_duplicate_jofotara_keys_listed_not_matched() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (jofo_inv("INV-001", "100.000", row=2), jofo_inv("INV-001", "200.000", row=3)),
        req(),
    )
    assert kinds(report) == [DUPLICATE_JOFOTARA, AMBIGUOUS]
    ambiguous = next(o for o in report.outcomes if o.kind == AMBIGUOUS)
    assert "DUPLICATE_COUNTERPART" in ambiguous.rationale
    assert len(ambiguous.sales) == 1 and len(ambiguous.jofo) == 2


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


def test_verified_credit_note_links_without_netting() -> None:
    # The credit note carries an explicit original-document reference naming a
    # unique invoice: the link is verified evidence, and nothing is netted.
    report = reconcile(
        (
            sales_inv("INV-001", "100.000"),
            sales_inv("CN-555", "100.000", credit=True, reference_number="INV-001", row=5),
        ),
        (jofo_inv("INV-009", "10.000"),),
        req(),
    )
    assert kinds(report) == [UNMATCHED_SALES, UNMATCHED_JOFOTARA, CREDIT_NOTE_LINKED]
    linked = next(o for o in report.outcomes if o.kind == CREDIT_NOTE_LINKED)
    assert linked.delta is None
    assert "CREDIT_NOTE_PRESERVED" in linked.rationale
    assert "REFERENCE_VERIFIED" in linked.flags
    assert sorted(r.number for r in linked.sales) == ["CN-555", "INV-001"]


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
    assert CREDIT_NOTE_LINKED not in kinds(report)  # clustered rows are not linked
    assert CREDIT_NOTE_UNVERIFIED not in kinds(report)


def test_unverified_credit_note_preserved_without_assertion() -> None:
    # A credit note whose reference cannot be verified is preserved as
    # relationship-unverified: visible for review, never claimed as linked.
    report = reconcile(
        (sales_inv("INV-001", "100.000"), sales_inv("CN-001", "20.000", credit=True, row=3)),
        (jofo_inv("INV-001", "100.000"),),
        req(),
    )
    assert CREDIT_NOTE_UNVERIFIED in kinds(report)
    unverified = next(o for o in report.outcomes if o.kind == CREDIT_NOTE_UNVERIFIED)
    assert unverified.delta is None  # never netted into an amount
    assert "CREDIT_NOTE_PRESERVED" in unverified.rationale
    assert "NO_REFERENCE" in unverified.flags
    assert CREDIT_NOTE_LINKED not in kinds(report)


def test_reversal_noted_with_verified_reference() -> None:
    report = reconcile(
        (sales_inv("INV-009", "10.000"),),
        (
            jofo_inv("INV-001", "100.000"),
            jofo_inv("RV-777", "100.000", reversal=True, reference_number="INV-001", row=6),
        ),
        req(),
    )
    assert REVERSAL_NOTED in kinds(report)
    noted = next(o for o in report.outcomes if o.kind == REVERSAL_NOTED)
    assert "REFERENCE_VERIFIED" in noted.flags
    assert sorted(r.number for r in noted.jofo) == ["INV-001", "RV-777"]


def test_reversal_without_reference_unverified() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (jofo_inv("INV-001", "100.000"), jofo_inv("INV-001-R", "100.000", reversal=True, row=6)),
        req(),
    )
    assert REVERSAL_UNVERIFIED in kinds(report)
    assert REVERSAL_NOTED not in kinds(report)


def test_missing_amount_preserves_presence_both_directions() -> None:
    # F1: a sales invoice with a missing amount still EXISTS. Its JoFotara
    # counterpart must read as a comparison problem, never as absent.
    report = reconcile(
        (sales_inv("INV-001", None),),
        (jofo_inv("INV-001", "10.000"),),
        req(),
    )
    assert kinds(report) == [AMBIGUOUS]
    outcome = report.outcomes[0]
    assert "COMPARISON_INSUFFICIENT" in outcome.rationale
    assert "MISSING_AMOUNT" in outcome.rationale
    assert UNMATCHED_JOFOTARA not in kinds(report)
    reverse = reconcile(
        (sales_inv("INV-001", "10.000"),),
        (jofo_inv("INV-001", None),),
        req(),
    )
    assert kinds(reverse) == [AMBIGUOUS]
    assert "COMPARISON_INSUFFICIENT" in reverse.outcomes[0].rationale
    assert UNMATCHED_SALES not in kinds(reverse)


def test_missing_currency_preserves_presence_both_directions() -> None:
    report = reconcile(
        (sales_inv("INV-001", "10.000", currency=None),),
        (jofo_inv("INV-001", "10.000"),),
        req(),
    )
    assert kinds(report) == [AMBIGUOUS]
    assert "MISSING_CURRENCY" in report.outcomes[0].rationale
    reverse = reconcile(
        (sales_inv("INV-001", "10.000"),),
        (jofo_inv("INV-001", "10.000", currency=None),),
        req(),
    )
    assert kinds(reverse) == [AMBIGUOUS]
    assert "MISSING_CURRENCY" in reverse.outcomes[0].rationale


def test_missing_key_is_insufficient_never_zero() -> None:
    report = reconcile(
        (
            sales_inv("", "10.000", row=3),
            sales_inv("INV-003", "10.000", currency=None, row=4),
        ),
        (jofo_inv("INV-003", "10.000"),),
        req(),
    )
    by_kind = kinds(report)
    assert by_kind.count(INSUFFICIENT_DATA) == 1  # blank key cannot be placed
    assert by_kind.count(AMBIGUOUS) == 1  # key present, comparison impossible
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


def test_duplicate_with_incomplete_member_and_counterpart() -> None:
    # F2 mixed: a duplicate sales cluster (one member amount-less) plus a
    # JoFotara counterpart. No false unmatched, no silent zero-fill.
    report = reconcile(
        (
            sales_inv("INV-001", None, row=2),
            sales_inv("INV-001", "100.000", row=3),
        ),
        (jofo_inv("INV-001", "100.000"),),
        req(),
    )
    assert kinds(report) == [DUPLICATE_SALES, AMBIGUOUS]
    assert UNMATCHED_SALES not in kinds(report) and UNMATCHED_JOFOTARA not in kinds(report)


def test_duplicate_clusters_on_both_sides_link_ambiguously() -> None:
    report = reconcile(
        (
            sales_inv("INV-001", "100.000", row=2),
            sales_inv("INV-001", "100.000", row=3),
        ),
        (
            jofo_inv("INV-001", "100.000", row=2),
            jofo_inv("INV-001", "100.000", row=4),
        ),
        req(),
    )
    assert kinds(report) == [DUPLICATE_SALES, DUPLICATE_JOFOTARA, AMBIGUOUS]
    ambiguous = next(o for o in report.outcomes if o.kind == AMBIGUOUS)
    assert len(ambiguous.sales) == 2 and len(ambiguous.jofo) == 2


def test_fingerprint_stable_under_duplicate_permutation() -> None:
    # F3: equal-key duplicates with distinct provenance must hash identically
    # regardless of input order.
    sales = (
        sales_inv("INV-001", "100.000", row=2),
        sales_inv("INV-001", "100.000", row=9),
        sales_inv("INV-002", "50.000", row=3),
    )
    jofo = (jofo_inv("INV-001", "100.000", row=4), jofo_inv("INV-002", "50.000", row=5))
    first = reconcile(sales, jofo, req())
    second = reconcile(tuple(reversed(sales)), tuple(reversed(jofo)), req())
    assert first.fingerprint == second.fingerprint
    assert [o.kind for o in first.outcomes] == [o.kind for o in second.outcomes]


def test_fingerprint_stable_under_ambiguous_permutation() -> None:
    sales = (
        sales_inv("INV-001", "100.000", currency="JOD", row=2),
        sales_inv("INV-002", "200.000", row=3),
    )
    jofo = (
        jofo_inv("INV-002", "200.000", row=5),
        jofo_inv("INV-001", "100.000", currency="USD", row=4),
    )
    first = reconcile(sales, jofo, req())
    assert [o.kind for o in first.outcomes] == [AMBIGUOUS, EXACT_MATCH]
    second = reconcile(tuple(reversed(sales)), tuple(reversed(jofo)), req())
    assert first.fingerprint == second.fingerprint


def test_fingerprint_stable_under_issuer_case_permutation() -> None:
    # F3a: rows identical except raw issuer case tie in the normalized key but
    # serialize differently — the raw issuer tie-breaker keeps order total.
    sales = (
        sales_inv("INV-001", "100.000", issuer="Acme", row=2),
        sales_inv("INV-001", "100.000", issuer="ACME", row=2),
    )
    jofo = (jofo_inv("INV-009", "10.000"),)
    first = reconcile(sales, jofo, req())
    assert [o.kind for o in first.outcomes] == [DUPLICATE_SALES, UNMATCHED_JOFOTARA]
    second = reconcile(tuple(reversed(sales)), tuple(reversed(jofo)), req())
    assert [o.kind for o in second.outcomes] == [DUPLICATE_SALES, UNMATCHED_JOFOTARA]
    assert first.fingerprint == second.fingerprint


def test_fingerprint_stable_under_number_whitespace_permutation() -> None:
    # F3a: "INV-001" vs "INV-001 " share a key but not a serialization.
    sales = (
        sales_inv("INV-001", "100.000", row=4),
        sales_inv("INV-001 ", "100.000", row=4),
    )
    jofo = (jofo_inv("INV-009", "10.000"),)
    first = reconcile(sales, jofo, req())
    assert [o.kind for o in first.outcomes] == [DUPLICATE_SALES, UNMATCHED_JOFOTARA]
    assert first.fingerprint == reconcile(tuple(reversed(sales)), jofo, req()).fingerprint


def test_fingerprint_stable_under_reference_permutation() -> None:
    # F3a: same-key credits differing only in reference must order identically.
    sales = (sales_inv("INV-001", "100.000"),)
    credits = (
        jofo_inv("CN-A", "10.000", credit=True, reference_number="INV-404", row=5),
        jofo_inv("CN-A", "10.000", credit=True, reference_number="INV-405", row=5),
    )
    jofo = (jofo_inv("INV-001", "100.000"),) + credits
    first = reconcile(sales, jofo, req())
    assert [o.kind for o in first.outcomes] == [DUPLICATE_JOFOTARA, EXACT_MATCH]
    assert first.fingerprint == reconcile(sales, tuple(reversed(jofo)), req()).fingerprint


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
    assert report.counts["CREDIT_NOTE_UNVERIFIED"] == 1  # CN-0009 states no reference
    assert report.sales_total == 4 and report.jofo_total == 3
    assert len(report.fingerprint) == 64


def test_unresolvable_reference_stays_unverified() -> None:
    report = reconcile(
        (sales_inv("INV-001", "100.000"),),
        (
            jofo_inv("INV-001", "100.000"),
            jofo_inv(
                "CN-002",
                "30.000",
                credit=True,
                reference_number="INV-404",
                row=5,
            ),
        ),
        req(),
    )
    assert kinds(report) == [EXACT_MATCH, CREDIT_NOTE_UNVERIFIED]
    unverified = next(o for o in report.outcomes if o.kind == CREDIT_NOTE_UNVERIFIED)
    assert "REFERENCE_UNRESOLVED" in unverified.flags
    assert CREDIT_NOTE_LINKED not in kinds(report)


def test_reference_matching_multiple_targets_stays_unverified() -> None:
    # A credit referencing a duplicated invoice number cannot pick a target.
    report = reconcile(
        (
            sales_inv("INV-001", "100.000", row=2),
            sales_inv("INV-001", "100.000", row=3),
            sales_inv("CN-003", "50.000", credit=True, reference_number="INV-001", row=4),
        ),
        (jofo_inv("INV-009", "10.000"),),
        req(),
    )
    assert DUPLICATE_SALES in kinds(report)
    assert CREDIT_NOTE_UNVERIFIED in kinds(report)
    unverified = next(o for o in report.outcomes if o.kind == CREDIT_NOTE_UNVERIFIED)
    assert "AMBIGUOUS_TARGET" in unverified.flags
    assert CREDIT_NOTE_LINKED not in kinds(report)
