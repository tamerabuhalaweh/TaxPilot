"""REC-005 GL contract invariants + default-deny policy validation (pure/mocked).

Synthetic fixtures only (never customer data). Verifies the immutable input
contracts fail closed on malformed values and that a comparison is refused
(with typed reasons) unless an APPROVED, complete policy is supplied.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.recon.contracts import InvoiceProvenance
from app.recon.gl import (
    BASIS_AGGREGATE_PERIOD,
    BASIS_INVOICE_REFERENCE,
    CREDIT_POSITIVE,
    DEBIT_POSITIVE,
    DEFAULT_GL_POLICY_REGISTRY,
    MEASURE_GROSS,
    MEASURE_NET,
    MEASURE_TAX,
    NO_APPROVED_POLICY,
    POLICY_APPROVED,
    POLICY_DRAFT,
    POLICY_MISSING_ACCOUNT_SCOPE,
    POLICY_MISSING_CONVENTION,
    POLICY_MISSING_CURRENCY_SCOPE,
    POLICY_MISSING_PROVENANCE,
    POLICY_MISSING_SALES_MEASURE,
    POLICY_NOT_APPROVED,
    POLICY_UNSUPPORTED_BASIS,
    GLComparisonPolicy,
    GLEntryProvenance,
    GLLine,
    GLPolicyProvenance,
    GLPolicyRegistry,
    SalesRegisterEntry,
    validate_policy,
)


def approved_policy(**kw) -> GLComparisonPolicy:
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


# -- GL line invariants --------------------------------------------------------


def test_gl_line_rejects_non_genuine_line_number() -> None:
    with pytest.raises(TypeError):
        GLLine(
            journal_id="J1",
            line_number=True,
            account_code="4000",
            transaction_date=date(2026, 3, 1),
            debit=None,
            credit=Decimal("1"),
            debit_raw="",
            credit_raw="1",
            currency="JOD",
        )
    with pytest.raises(ValueError):
        GLLine(
            journal_id="J1",
            line_number=0,
            account_code="4000",
            transaction_date=date(2026, 3, 1),
            debit=None,
            credit=Decimal("1"),
            debit_raw="",
            credit_raw="1",
            currency="JOD",
        )


def test_gl_line_rejects_float_and_nonfinite() -> None:
    with pytest.raises(TypeError):
        GLLine(
            journal_id="J1",
            line_number=1,
            account_code="4000",
            transaction_date=None,
            debit=1.5,  # type: ignore[arg-type]
            credit=None,
            debit_raw="1.5",
            credit_raw="",
            currency="JOD",
        )
    with pytest.raises(ValueError):
        GLLine(
            journal_id="J1",
            line_number=1,
            account_code="4000",
            transaction_date=None,
            debit=Decimal("NaN"),
            credit=None,
            debit_raw="NaN",
            credit_raw="",
            currency="JOD",
        )


def test_gl_line_normalizes_currency_and_preserves_account_zeros() -> None:
    line = GLLine(
        journal_id="J1",
        line_number=1,
        account_code="0004000",
        transaction_date=None,
        debit=None,
        credit=Decimal("10"),
        debit_raw="",
        credit_raw="10",
        currency=" jod ",
    )
    assert line.currency == "JOD"
    assert line.account_code == "0004000"


def test_gl_provenance_requires_positive_int_row() -> None:
    ok = GLEntryProvenance(dataset_id="SYN-GL", source="general_ledger", row_number=2, raw_reference="J1-1")
    assert ok.row_number == 2
    with pytest.raises(TypeError):
        GLEntryProvenance(dataset_id="SYN-GL", source="general_ledger", row_number=2.0, raw_reference="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GLEntryProvenance(dataset_id="SYN-GL", source="general_ledger", row_number=-1, raw_reference="x")


# -- sales entry invariants ----------------------------------------------------


def test_sales_entry_measure_selection() -> None:
    entry = SalesRegisterEntry(
        issuer="Example Trading LLC",
        invoice_number="INV-1",
        net_amount=Decimal("100"),
        net_raw="100",
        tax_amount=Decimal("16"),
        tax_raw="16",
        gross_amount=Decimal("116"),
        gross_raw="116",
        currency="JOD",
        transaction_date=date(2026, 3, 1),
        provenance=InvoiceProvenance(
            dataset_id="SYN-SALES", source="sales_register", row_number=2, raw_invoice="INV-1"
        ),
    )
    assert entry.measure(MEASURE_NET) == (Decimal("100"), "100")
    assert entry.measure(MEASURE_TAX)[0] == Decimal("16")
    assert entry.measure(MEASURE_GROSS)[0] == Decimal("116")
    with pytest.raises(ValueError):
        entry.measure("BOGUS")


def test_sales_entry_rejects_float_amount() -> None:
    with pytest.raises(TypeError):
        SalesRegisterEntry(
            issuer="X",
            invoice_number="1",
            net_amount=1.5,  # type: ignore[arg-type]
            net_raw="1.5",
            tax_amount=None,
            tax_raw="",
            gross_amount=None,
            gross_raw="",
            currency="JOD",
            transaction_date=None,
        )


# -- policy structural + default-deny validation -------------------------------


def test_policy_rejects_float_tolerance_and_negative() -> None:
    with pytest.raises(TypeError):
        approved_policy(tolerance=0.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        approved_policy(tolerance=Decimal("-1"))


def test_approved_policy_requires_every_dimension() -> None:
    assert validate_policy(approved_policy()).approved is True

    def reasons(**kw) -> tuple[str, ...]:
        return validate_policy(approved_policy(**kw)).reasons

    assert reasons(status=POLICY_DRAFT) == (POLICY_NOT_APPROVED,)
    assert POLICY_MISSING_PROVENANCE in reasons(provenance=None)
    assert POLICY_MISSING_PROVENANCE in reasons(approved_by="")
    assert POLICY_UNSUPPORTED_BASIS in reasons(comparison_basis=BASIS_INVOICE_REFERENCE)
    assert POLICY_MISSING_ACCOUNT_SCOPE in reasons(gl_account_scope=())
    assert POLICY_MISSING_CURRENCY_SCOPE in reasons(currency_scope=())
    assert POLICY_MISSING_SALES_MEASURE in reasons(sales_measure="BOGUS")
    assert POLICY_MISSING_CONVENTION in reasons(debit_credit_convention="BOGUS")


def test_default_registry_is_empty_and_ambiguous_lookup_fails_closed() -> None:
    assert DEFAULT_GL_POLICY_REGISTRY.policies == ()
    assert (
        DEFAULT_GL_POLICY_REGISTRY.find(
            comparison_basis=BASIS_AGGREGATE_PERIOD, sales_measure=MEASURE_NET, currency="JOD"
        )
        is None
    )
    # Two declared policies matching the same request are ambiguous -> None.
    registry = GLPolicyRegistry((approved_policy(policy_id="A"), approved_policy(policy_id="B")))
    assert (
        registry.find(comparison_basis=BASIS_AGGREGATE_PERIOD, sales_measure=MEASURE_NET, currency="JOD")
        is None
    )


def test_debit_positive_convention_is_declared_not_assumed() -> None:
    policy = approved_policy(debit_credit_convention=DEBIT_POSITIVE, gl_account_scope=("1000",))
    assert policy.debit_credit_convention == DEBIT_POSITIVE


def test_no_approved_policy_constant_is_stable() -> None:
    assert NO_APPROVED_POLICY == "NO_APPROVED_POLICY"
