"""REC-SLICE-02 golden scenarios: ReconciliationReport -> review findings.

Synthetic Jordan-flavored fixtures only (never customer data): JO jurisdiction,
JOD 3dp amounts, English/Arabic issuers, exact-Decimal deltas. Tests build real
reports through reconcile() and project them, so findings stay faithful to the
merged engine.
"""

from datetime import date
from decimal import Decimal

import pytest

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
    MatchOutcome,
    ReconcileRequest,
    ReconciliationReport,
    project,
    reconcile,
)

ISSUER_EN = "Example Trading LLC"
ISSUER_AR = "شركة المثال للتجارة"
PERIOD = (date(2026, 1, 1), date(2026, 12, 31))

BANNED_LANGUAGE = (
    "fraud",
    "fraudulent",
    "violation",
    "suspicious",
    "evasion",
    "evade",
    "penalty",
    "non-compliant",
    "noncompliant",
    "illegal",
    "fake",
    "falsif",
    "manipulat",
)


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


def test_exact_match_is_informational_not_discrepancy() -> None:
    report = reconcile(
        (sales_inv("INV-0001", "15000.000"),),
        (jofo_inv("INV-0001", "15000.000"),),
        req(),
    )
    projected = project(report)
    (item,) = projected.findings
    assert item.outcome_kind == EXACT_MATCH
    assert item.review_required is False
    assert item.category == "INFORMATIONAL"
    assert item.severity == "LOW"
    assert item.rule == "JO/REC-003/1"
    assert {e.role for e in item.evidence} == {"sales", "jofo"}
    assert all(e.dataset_id for e in item.evidence)
    assert projected.summary["total"] == 1
    assert projected.summary["review_required"] == 0
    assert projected.summary["informational"] == 1


def test_unmatched_sales_is_high_discrepancy() -> None:
    report = reconcile((sales_inv("INV-0007", "250.750"),), (), req())
    projected = project(report)
    (item,) = projected.findings
    assert item.outcome_kind == UNMATCHED_SALES
    assert item.review_required is True
    assert (item.category, item.severity) == ("RECONCILIATION_DIFFERENCE", "HIGH")
    assert "250.750" in item.difference and "JOD" in item.difference


def test_unmatched_jofo_arabic_issuer_is_high_discrepancy() -> None:
    report = reconcile(
        (), (jofo_inv("INV-0008", "99.990", issuer=ISSUER_AR),), req()
    )
    projected = project(report)
    (item,) = projected.findings
    assert item.outcome_kind == UNMATCHED_JOFOTARA
    assert item.review_required is True
    assert (item.category, item.severity) == ("RECONCILIATION_DIFFERENCE", "HIGH")
    assert ISSUER_AR in item.title  # identifiers flow through verbatim


def test_amount_mismatch_carries_exact_decimal_delta() -> None:
    report = reconcile(
        (sales_inv("INV-0002", "1000.500"),),
        (jofo_inv("INV-0002", "1000.000"),),
        req(),
    )
    projected = project(report)
    (item,) = projected.findings
    assert item.outcome_kind == AMOUNT_MISMATCH
    assert item.review_required is True
    assert (item.category, item.severity) == ("RECONCILIATION_DIFFERENCE", "HIGH")
    assert item.delta == "0.500"
    assert item.delta_currency == "JOD"
    assert "0.500 JOD" in item.difference


def test_duplicate_is_review_candidate_never_violation() -> None:
    report = reconcile(
        (sales_inv("INV-0005", "10.000", row=2), sales_inv("INV-0005", "10.000", row=3)),
        (),
        req(),
    )
    assert [o.kind for o in report.outcomes] == [DUPLICATE_SALES]
    projected = project(report)
    (item,) = projected.findings
    assert item.review_required is True
    assert (item.category, item.severity) == ("REVIEW_CANDIDATE", "MEDIUM")
    assert len(item.evidence) == 2
    assert {e.row_number for e in item.evidence} == {2, 3}


def test_insufficient_data_is_review_required_quality() -> None:
    report = reconcile((sales_inv("", "10.000"),), (), req())
    assert [o.kind for o in report.outcomes] == [INSUFFICIENT_DATA]
    projected = project(report)
    (item,) = projected.findings
    assert item.review_required is True
    assert (item.category, item.severity) == ("DATA_QUALITY", "MEDIUM")
    assert "MISSING_INVOICE_NUMBER" in item.difference


def test_currency_mismatch_computes_no_delta() -> None:
    report = reconcile(
        (sales_inv("INV-0009", "100.000", currency="JOD"),),
        (jofo_inv("INV-0009", "100.000", currency="USD"),),
        req(),
    )
    assert [o.kind for o in report.outcomes] == [AMBIGUOUS]
    projected = project(report)
    (item,) = projected.findings
    assert item.review_required is True
    assert item.category == "REVIEW_CANDIDATE"
    assert item.delta is None
    assert "JOD" in item.difference and "USD" in item.difference


def test_verified_credit_link_is_informational() -> None:
    report = reconcile(
        (
            sales_inv("INV-0003", "250.750"),
            sales_inv("CN-0001", "250.750", credit=True, reference_number="INV-0003"),
        ),
        (),
        req(),
    )
    kinds = [o.kind for o in report.outcomes]
    assert CREDIT_NOTE_LINKED in kinds
    projected = project(report)
    linked = next(i for i in projected.findings if i.outcome_kind == CREDIT_NOTE_LINKED)
    assert linked.review_required is False
    assert linked.category == "INFORMATIONAL"
    assert "not netted" in linked.difference


def test_unverified_credit_is_informational() -> None:
    report = reconcile(
        (sales_inv("CN-0002", "5.000", credit=True),),
        (),
        req(),
    )
    assert [o.kind for o in report.outcomes] == [CREDIT_NOTE_UNVERIFIED]
    (item,) = project(report).findings
    assert item.review_required is False
    assert item.category == "INFORMATIONAL"


def test_out_of_period_flags_are_preserved() -> None:
    report = reconcile(
        (sales_inv("INV-0010", "20.000", date=date(2025, 12, 20)),),
        (jofo_inv("INV-0010", "20.000", date=date(2025, 12, 21)),),
        req(),
    )
    assert [o.kind for o in report.outcomes] == [EXACT_MATCH]
    (item,) = project(report).findings
    assert "PERIOD_OUTSIDE" in item.flags
    assert item.review_required is False  # amounts reconcile; flag is context


def _mixed_report() -> ReconciliationReport:
    """One report exercising every outcome kind of the engine contract."""
    sales = (
        sales_inv("INV-0001", "15000.000", row=2),
        sales_inv("INV-0002", "1000.500", row=3),
        sales_inv("INV-0003", "250.750", row=4),
        sales_inv("INV-0005", "10.000", row=5),
        sales_inv("INV-0005", "10.000", row=6),
        sales_inv("INV-0007", "100.000", currency="JOD", row=7),
        sales_inv("INV-0008", None, row=8),
        sales_inv("CN-0001", "250.750", row=9, credit=True, reference_number="INV-0003"),
        sales_inv("CN-0002", "5.000", row=10, credit=True),
        sales_inv("RV-0001", "99.990", row=11, issuer=ISSUER_AR, reversal=True, reference_number="INV-0004"),
        sales_inv("RV-0002", "7.000", row=12, reversal=True, reference_number="INV-9999"),
        sales_inv("", "10.000", row=13),
    )
    jofo = (
        jofo_inv("INV-0001", "15000.000", row=2),
        jofo_inv("INV-0002", "1000.000", row=3),
        jofo_inv("INV-0004", "99.990", issuer=ISSUER_AR, row=4),
        jofo_inv("INV-0006", "30.000", row=5),
        jofo_inv("INV-0006", "30.000", row=6),
        jofo_inv("INV-0007", "100.000", currency="USD", row=7),
        jofo_inv("INV-0008", "40.000", row=8),
    )
    return reconcile(sales, jofo, req())


def test_every_outcome_kind_maps_to_policy() -> None:
    report = _mixed_report()
    assert {
        EXACT_MATCH,
        AMOUNT_MISMATCH,
        UNMATCHED_SALES,
        UNMATCHED_JOFOTARA,
        DUPLICATE_SALES,
        DUPLICATE_JOFOTARA,
        AMBIGUOUS,
        CREDIT_NOTE_LINKED,
        CREDIT_NOTE_UNVERIFIED,
        REVERSAL_NOTED,
        REVERSAL_UNVERIFIED,
        INSUFFICIENT_DATA,
    } <= set(report.counts)
    projected = project(report)
    assert len(projected.findings) == len(report.outcomes)
    expected = {
        AMOUNT_MISMATCH: ("RECONCILIATION_DIFFERENCE", "HIGH", True),
        UNMATCHED_SALES: ("RECONCILIATION_DIFFERENCE", "HIGH", True),
        UNMATCHED_JOFOTARA: ("RECONCILIATION_DIFFERENCE", "HIGH", True),
        DUPLICATE_SALES: ("REVIEW_CANDIDATE", "MEDIUM", True),
        DUPLICATE_JOFOTARA: ("REVIEW_CANDIDATE", "MEDIUM", True),
        AMBIGUOUS: ("REVIEW_CANDIDATE", "MEDIUM", True),
        INSUFFICIENT_DATA: ("DATA_QUALITY", "MEDIUM", True),
        EXACT_MATCH: ("INFORMATIONAL", "LOW", False),
        CREDIT_NOTE_LINKED: ("INFORMATIONAL", "LOW", False),
        CREDIT_NOTE_UNVERIFIED: ("INFORMATIONAL", "LOW", False),
        REVERSAL_NOTED: ("INFORMATIONAL", "LOW", False),
        REVERSAL_UNVERIFIED: ("INFORMATIONAL", "LOW", False),
    }
    for outcome, item in zip(report.outcomes, projected.findings, strict=True):
        assert (item.category, item.severity, item.review_required) == expected[outcome.kind]
        assert item.rule == outcome.rule


def test_accountant_facing_completeness_and_language() -> None:
    projected = project(_mixed_report())
    for item in projected.findings:
        for text in (
            item.title,
            item.what,
            item.compared,
            item.difference,
            item.why,
            item.guidance,
        ):
            assert text.strip()
            lowered = text.casefold()
            assert not any(word in lowered for word in BANNED_LANGUAGE), text
        assert item.evidence
        assert item.rule.startswith("JO/")
        assert item.finding_id
    assert len({item.finding_id for item in projected.findings}) == len(projected.findings)


def test_evidence_is_traceable_to_source_rows() -> None:
    report = _mixed_report()
    projected = project(report)
    source_rows = {
        (r.provenance.dataset_id, r.provenance.source, r.provenance.row_number)
        for outcome in report.outcomes
        for r in (*outcome.sales, *outcome.jofo)
        if r.provenance
    }
    evidence_rows = {
        (e.dataset_id, e.source, e.row_number)
        for item in projected.findings
        for e in item.evidence
    }
    assert evidence_rows == source_rows


def test_projection_is_permutation_stable() -> None:
    sales = (
        sales_inv("INV-0001", "15000.000", row=2),
        sales_inv("INV-0002", "1000.500", row=3),
        sales_inv("INV-0003", "250.750", row=4),
    )
    jofo = (jofo_inv("INV-0001", "15000.000", row=2), jofo_inv("INV-0002", "1000.000", row=3))
    first = project(reconcile(sales, jofo, req()))
    second = project(reconcile(tuple(reversed(sales)), tuple(reversed(jofo)), req()))
    assert first.fingerprint == second.fingerprint
    assert [i.finding_id for i in first.findings] == [i.finding_id for i in second.findings]


def test_dataset_versions_flow_into_projection_identity() -> None:
    sales = (sales_inv("INV-0001", "15000.000"),)
    jofo = (jofo_inv("INV-0001", "15000.000"),)
    base = project(reconcile(sales, jofo, req()))
    rerun = project(
        reconcile(sales, jofo, req(sales_dataset_id="SYN-SALES-v2", jofo_dataset_id="SYN-JOFO-v2"))
    )
    assert base.recon_fingerprint != rerun.recon_fingerprint
    assert base.fingerprint != rerun.fingerprint
    assert rerun.sales_dataset_id == "SYN-SALES-v2"
    assert rerun.jofo_dataset_id == "SYN-JOFO-v2"
    assert base.tenant_id == "tenant-syn-1"


def test_empty_report_projects_to_empty_findings() -> None:
    projected = project(reconcile((), (), req()))
    assert projected.findings == ()
    assert projected.summary["total"] == 0
    assert len(projected.fingerprint) == 64
    assert project(reconcile((), (), req())).fingerprint == projected.fingerprint


def test_jo_arabic_end_to_end_keeps_exact_amounts() -> None:
    report = reconcile(
        (sales_inv("INV-0100", "1234.567", issuer=ISSUER_AR),),
        (jofo_inv("INV-0100", "1234.500", issuer=ISSUER_AR),),
        req(),
    )
    (item,) = project(report).findings
    assert item.outcome_kind == AMOUNT_MISMATCH
    assert item.delta == "0.067"
    assert ISSUER_AR in item.what


def test_non_report_input_is_rejected() -> None:
    with pytest.raises(TypeError):
        project("not-a-report")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        project(None)  # type: ignore[arg-type]


def test_unknown_outcome_kind_fails_closed() -> None:
    outcome = MatchOutcome(kind="SOMETHING_NEW", rule="JO/REC-001/1")
    report = ReconciliationReport(
        tenant_id="tenant-syn-1",
        sales_dataset_id="SYN-SALES",
        jofo_dataset_id="SYN-JOFO",
        jurisdiction="JO",
        rules_version="1",
        tolerance=Decimal("0"),
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        outcomes=(outcome,),
        counts={"SOMETHING_NEW": 1},
        sales_total=0,
        jofo_total=0,
        fingerprint="0" * 64,
    )
    with pytest.raises(ValueError, match="unmapped outcome kind"):
        project(report)
