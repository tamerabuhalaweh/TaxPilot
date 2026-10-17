"""REC-005 findings projection golden tests (pure).

Projects Sales<->GL outcomes into review items; verifies categories/severities,
evidence projection across both roles, fail-closed behaviour, and the
default-deny blocked item. Synthetic fixtures only.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.recon.contracts import InvoiceProvenance
from app.recon.gl import (
    BASIS_AGGREGATE_PERIOD,
    COVERAGE_INVALID_DEBIT_CREDIT_PAIR,
    CREDIT_POSITIVE,
    INCONCLUSIVE_COVERAGE,
    MEASURE_NET,
    POLICY_APPROVED,
    GLComparisonPolicy,
    GLComparisonRequest,
    GLEntryProvenance,
    GLLine,
    GLPolicyProvenance,
    SalesRegisterEntry,
    compare_sales_to_gl,
    project_gl,
)
from app.recon.gl.findings import (
    CATEGORY_CONTRACT,
    CATEGORY_DIFFERENCE,
    CATEGORY_INFO,
    CATEGORY_QUALITY,
    SEVERITY_HIGH,
    SEVERITY_LOW,
)

PERIOD = (date(2026, 1, 1), date(2026, 12, 31))


def policy(**kw) -> GLComparisonPolicy:
    base: dict = {
        "policy_id": "SYN-GL-POL-1",
        "policy_version": "1",
        "status": POLICY_APPROVED,
        "comparison_basis": BASIS_AGGREGATE_PERIOD,
        "sales_measure": MEASURE_NET,
        "gl_account_scope": ("4000", "4001"),
        "debit_credit_convention": CREDIT_POSITIVE,
        "currency_scope": ("JOD",),
        "tolerance": Decimal("0"),
        "rules_version": "1",
        "approved_by": "synthetic-test-reviewer",
        "approved_at": "2026-01-01",
        "provenance": GLPolicyProvenance(authority="synthetic-test-only", reference="SYN-GL-1"),
    }
    base.update(kw)
    return GLComparisonPolicy(**base)


def sales_entry(number: str, net: str, *, row: int = 2) -> SalesRegisterEntry:
    return SalesRegisterEntry(
        issuer="Example Trading LLC",
        invoice_number=number,
        net_amount=Decimal(net),
        net_raw=net,
        tax_amount=None,
        tax_raw="",
        gross_amount=None,
        gross_raw="",
        currency="JOD",
        transaction_date=date(2026, 3, 15),
        provenance=InvoiceProvenance(
            dataset_id="SYN-SALES", source="sales_register", row_number=row, raw_invoice=number
        ),
    )


def gl_line(journal: str, credit: str, *, row: int = 2) -> GLLine:
    return GLLine(
        journal_id=journal,
        line_number=1,
        account_code="4000",
        transaction_date=date(2026, 3, 20),
        debit=None,
        credit=Decimal(credit),
        debit_raw="",
        credit_raw=credit,
        currency="JOD",
        provenance=GLEntryProvenance(
            dataset_id="SYN-GL", source="general_ledger", row_number=row, raw_reference=f"{journal}-1"
        ),
    )


def request(policy_value: GLComparisonPolicy | None) -> GLComparisonRequest:
    return GLComparisonRequest(
        tenant_id="t1",
        client_id="c1",
        sales_dataset_id="SYN-SALES",
        gl_dataset_id="SYN-GL",
        jurisdiction="JO",
        rules_version="1",
        policy=policy_value,
        period_start=PERIOD[0],
        period_end=PERIOD[1],
    )


def test_difference_projects_high_review_item_with_evidence() -> None:
    report = compare_sales_to_gl((sales_entry("1", "150"),), (gl_line("J1", "140"),), request(policy()))
    projected = project_gl(report)
    assert projected.blocked is False
    (item,) = projected.findings
    assert item.category == CATEGORY_DIFFERENCE
    assert item.severity == SEVERITY_HIGH and item.review_required is True
    assert item.outcome_kind == "DIFFERENCE"
    assert item.rule == "JO/REC-005/1"
    assert item.delta == "10"
    roles = sorted(ref.role for ref in item.evidence)
    assert roles == ["gl", "sales"]
    assert item.sales[0] is not None and item.sales[0].amount == "150"
    assert projected.summary["review_required"] == 1


def test_reconciled_projects_informational_item() -> None:
    report = compare_sales_to_gl((sales_entry("1", "150"),), (gl_line("J1", "150"),), request(policy()))
    projected = project_gl(report)
    (item,) = projected.findings
    assert item.category == CATEGORY_INFO
    assert item.severity == SEVERITY_LOW
    assert item.review_required is False and item.review_state is None
    assert projected.summary["informational"] == 1


def test_blocked_report_projects_single_contract_item() -> None:
    report = compare_sales_to_gl((), (), request(None))
    projected = project_gl(report)
    assert projected.blocked is True
    (item,) = projected.findings
    assert item.category == CATEGORY_CONTRACT
    assert item.review_required is True
    assert item.outcome_kind == "BLOCKED"
    assert projected.summary["blocked"] is True
    assert projected.summary["block_reasons"] == ["NO_APPROVED_POLICY"]


def test_missing_provenance_fails_closed() -> None:
    entry = SalesRegisterEntry(
        issuer="X",
        invoice_number="1",
        net_amount=Decimal("100"),
        net_raw="100",
        tax_amount=None,
        tax_raw="",
        gross_amount=None,
        gross_raw="",
        currency="JOD",
        transaction_date=date(2026, 3, 15),
        provenance=None,
    )
    report = compare_sales_to_gl((entry,), (gl_line("J1", "100"),), request(policy()))
    with pytest.raises(ValueError):
        project_gl(report)


def test_projection_fingerprint_is_stable() -> None:
    report = compare_sales_to_gl((sales_entry("1", "150"),), (gl_line("J1", "150"),), request(policy()))
    assert project_gl(report).fingerprint == project_gl(report).fingerprint


def test_unknown_outcome_kind_fails_closed() -> None:
    from dataclasses import replace

    from app.recon.gl.contracts import GLOutcome

    report = compare_sales_to_gl((sales_entry("1", "150"),), (gl_line("J1", "150"),), request(policy()))
    poisoned = replace(report, outcomes=(GLOutcome(kind="BOGUS", rule="JO/REC-005/1"),))
    with pytest.raises(ValueError):
        project_gl(poisoned)


def test_inconclusive_coverage_projects_data_quality_item() -> None:
    invalid = GLLine(
        journal_id="J2",
        line_number=1,
        account_code="4000",
        transaction_date=date(2026, 3, 20),
        debit=Decimal("100"),
        credit=Decimal("100"),
        debit_raw="100",
        credit_raw="100",
        currency="JOD",
        provenance=GLEntryProvenance(
            dataset_id="SYN-GL", source="general_ledger", row_number=3, raw_reference="J2-1"
        ),
    )
    report = compare_sales_to_gl(
        (sales_entry("1", "150"),), (gl_line("J1", "150"), invalid), request(policy())
    )
    projected = project_gl(report)
    assert projected.inconclusive is True
    assert COVERAGE_INVALID_DEBIT_CREDIT_PAIR in projected.inconclusive_reasons
    assert projected.summary["inconclusive"] is True
    assert "RECONCILED" not in [f.outcome_kind for f in projected.findings]
    inconclusive = [f for f in projected.findings if f.outcome_kind == INCONCLUSIVE_COVERAGE]
    assert inconclusive and inconclusive[0].category == CATEGORY_QUALITY
    assert inconclusive[0].review_required is True
