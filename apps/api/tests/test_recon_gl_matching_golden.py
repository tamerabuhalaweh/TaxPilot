"""REC-005 golden scenarios: deterministic Sales Register <-> GL comparison.

Synthetic Jordan-flavored fixtures only (never customer data): JOD 3dp amounts,
leading-zero accounts, credit notes, reversals, multi-currency, periods. The
approved policy used here is an explicitly synthetic test double
(``authority="synthetic-test-only"``) — it is NOT a production accounting rule.
"""

from datetime import date
from decimal import Decimal

from app.recon.contracts import InvoiceProvenance
from app.recon.gl import (
    BASIS_AGGREGATE_PERIOD,
    BASIS_INVOICE_REFERENCE,
    CREDIT_NOTE_LINKED,
    CREDIT_NOTE_UNVERIFIED,
    CREDIT_POSITIVE,
    CURRENCY_NOT_IN_SCOPE,
    DIFFERENCE,
    DUPLICATE_GL,
    DUPLICATE_SALES,
    INVALID_DEBIT_CREDIT_PAIR,
    MEASURE_GROSS,
    MEASURE_NET,
    MISSING_GL,
    MISSING_SALES,
    MISSING_VALUE,
    NO_APPROVED_POLICY,
    PERIOD_OUTSIDE,
    PERIOD_UNKNOWN,
    POLICY_APPROVED,
    RECONCILED,
    REVERSAL_NOTED,
    REVERSAL_UNVERIFIED,
    GLComparisonPolicy,
    GLComparisonRequest,
    GLEntryProvenance,
    GLLine,
    GLPolicyProvenance,
    SalesRegisterEntry,
    compare_sales_to_gl,
)

ISSUER = "Example Trading LLC"
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


def sales_entry(
    number: str,
    net: str | None = None,
    *,
    tax: str | None = None,
    gross: str | None = None,
    currency: str = "JOD",
    when: date | None = date(2026, 3, 15),
    row: int = 2,
    credit: bool = False,
    reversal: bool = False,
    ref: str | None = None,
) -> SalesRegisterEntry:
    return SalesRegisterEntry(
        issuer=ISSUER,
        invoice_number=number,
        net_amount=Decimal(net) if net is not None else None,
        net_raw=net or "",
        tax_amount=Decimal(tax) if tax is not None else None,
        tax_raw=tax or "",
        gross_amount=Decimal(gross) if gross is not None else None,
        gross_raw=gross or "",
        currency=currency,
        transaction_date=when,
        is_credit_note=credit,
        is_reversal=reversal,
        reference_number=ref,
        provenance=InvoiceProvenance(
            dataset_id="SYN-SALES", source="sales_register", row_number=row, raw_invoice=number
        ),
    )


def gl_line(
    journal: str,
    number: int,
    account: str,
    *,
    debit: str | None = None,
    credit: str | None = None,
    currency: str | None = "JOD",
    when: date | None = date(2026, 3, 20),
    row: int = 2,
    reversal: bool = False,
    ref: str | None = None,
) -> GLLine:
    return GLLine(
        journal_id=journal,
        line_number=number,
        account_code=account,
        transaction_date=when,
        debit=Decimal(debit) if debit is not None else None,
        credit=Decimal(credit) if credit is not None else None,
        debit_raw=debit or "",
        credit_raw=credit or "",
        currency=currency,
        description=f"{journal}-{number}",
        is_reversal=reversal,
        reversal_reference=ref,
        provenance=GLEntryProvenance(
            dataset_id="SYN-GL",
            source="general_ledger",
            row_number=row,
            raw_reference=f"{journal}-{number}",
        ),
    )


def request(policy_value: GLComparisonPolicy | None, **kw) -> GLComparisonRequest:
    base: dict = {
        "tenant_id": "tenant-syn-1",
        "client_id": "client-syn-1",
        "sales_dataset_id": "SYN-SALES",
        "gl_dataset_id": "SYN-GL",
        "jurisdiction": "JO",
        "rules_version": "1",
        "policy": policy_value,
        "period_start": PERIOD[0],
        "period_end": PERIOD[1],
    }
    base.update(kw)
    return GLComparisonRequest(**base)


def kinds(report) -> list:  # type: ignore[no-untyped-def]
    return [o.kind for o in report.outcomes]


# -- default-deny --------------------------------------------------------------


def test_no_policy_blocks_without_output() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100"),), (gl_line("J1", 1, "4000", credit="100"),), request(None)
    )
    assert report.blocked is True
    assert report.block_reasons == (NO_APPROVED_POLICY,)
    assert report.outcomes == ()


def test_draft_policy_blocks() -> None:
    report = compare_sales_to_gl((), (), request(policy(status="DRAFT")))
    assert report.blocked is True and "POLICY_NOT_APPROVED" in report.block_reasons


def test_unsupported_invoice_reference_basis_blocks() -> None:
    report = compare_sales_to_gl((), (), request(policy(comparison_basis=BASIS_INVOICE_REFERENCE)))
    assert report.blocked is True and "POLICY_UNSUPPORTED_BASIS" in report.block_reasons


def test_blocked_fingerprint_is_stable() -> None:
    a = compare_sales_to_gl((), (), request(None))
    b = compare_sales_to_gl((), (), request(None))
    assert a.fingerprint == b.fingerprint


# -- reconciled / difference / tolerance ---------------------------------------


def test_reconciled_identical_totals() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100", row=2), sales_entry("2", "50", row=3)),
        (gl_line("J1", 1, "4000", credit="100", row=2), gl_line("J2", 1, "4001", credit="50", row=3)),
        request(policy()),
    )
    assert kinds(report) == [RECONCILED]
    outcome = report.outcomes[0]
    assert outcome.sales_total == Decimal("150") and outcome.gl_total == Decimal("150")
    assert outcome.delta == Decimal("0")


def test_difference_beyond_tolerance() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "150"),),
        (gl_line("J1", 1, "4000", credit="140"),),
        request(policy()),
    )
    assert kinds(report) == [DIFFERENCE]
    assert report.outcomes[0].delta == Decimal("10")


def test_difference_within_tolerance_is_reconciled() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "150"),),
        (gl_line("J1", 1, "4000", credit="149.99"),),
        request(policy(tolerance=Decimal("0.01"))),
    )
    assert kinds(report) == [RECONCILED]
    assert "WITHIN_TOLERANCE" in report.outcomes[0].flags


# -- coverage / scope ----------------------------------------------------------


def test_missing_gl_and_missing_sales() -> None:
    only_sales = compare_sales_to_gl((sales_entry("1", "100"),), (), request(policy()))
    assert kinds(only_sales) == [MISSING_GL]
    only_gl = compare_sales_to_gl((), (gl_line("J1", 1, "4000", credit="100"),), request(policy()))
    assert kinds(only_gl) == [MISSING_SALES]


def test_out_of_scope_account_is_counted_not_compared() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100"),),
        (
            gl_line("J1", 1, "4000", credit="100"),
            gl_line("J2", 1, "9999", debit="1000"),
        ),
        request(policy()),
    )
    assert report.gl_out_of_scope == 1
    assert kinds(report) == [RECONCILED]


def test_debit_positive_convention_flips_sign() -> None:
    # DEBIT_POSITIVE: an AR debit of 100 equals sales 100 (declared convention).
    report = compare_sales_to_gl(
        (sales_entry("1", "100"),),
        (gl_line("J1", 1, "1000", debit="100"),),
        request(policy(debit_credit_convention="DEBIT_POSITIVE", gl_account_scope=("1000",))),
    )
    assert kinds(report) == [RECONCILED]


# -- malformed / missing values ------------------------------------------------


def test_invalid_debit_credit_pair_is_reported_and_excluded() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100"),),
        (
            gl_line("J1", 1, "4000", debit="100", credit="100"),
            gl_line("J2", 1, "4000", credit="100"),
        ),
        request(policy()),
    )
    assert INVALID_DEBIT_CREDIT_PAIR in kinds(report)
    # The valid line still reconciles against sales; the invalid line never nets.
    assert RECONCILED in kinds(report)


def test_missing_amount_and_currency_are_reported() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000"),  # neither debit nor credit
            gl_line("J2", 1, "4000", credit="100", currency=None),  # missing currency
        ),
        request(policy()),
    )
    missing = [o for o in report.outcomes if o.kind == MISSING_VALUE]
    assert {o.rationale for o in missing} == {("MISSING_AMOUNT",), ("MISSING_CURRENCY",)}


def test_sales_missing_selected_measure() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", net=None, gross="116"),),
        (gl_line("J1", 1, "4000", credit="116"),),
        request(policy()),
    )
    assert [o.kind for o in report.outcomes if o.kind == MISSING_VALUE]
    assert ("MISSING_NET",) in [o.rationale for o in report.outcomes]


def test_sales_measure_gross_selected_by_policy() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", net="100", gross="116"),),
        (gl_line("J1", 1, "4000", credit="116"),),
        request(policy(sales_measure=MEASURE_GROSS)),
    )
    assert kinds(report) == [RECONCILED]


# -- currency segregation ------------------------------------------------------


def test_currency_not_in_scope_is_refused_never_converted() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100", currency="USD"),),
        (gl_line("J1", 1, "4000", credit="100", currency="USD"),),
        request(policy()),  # scope is JOD only
    )
    assert kinds(report) == [CURRENCY_NOT_IN_SCOPE, CURRENCY_NOT_IN_SCOPE]


def test_multi_currency_buckets_never_combine() -> None:
    report = compare_sales_to_gl(
        (
            sales_entry("1", "100", currency="JOD", row=2),
            sales_entry("2", "50", currency="USD", row=3),
        ),
        (
            gl_line("J1", 1, "4000", credit="100", currency="JOD", row=2),
            gl_line("J2", 1, "4000", credit="40", currency="USD", row=3),
        ),
        request(policy(currency_scope=("JOD", "USD"))),
    )
    by_currency = {o.currency: o.kind for o in report.outcomes}
    assert by_currency == {"JOD": RECONCILED, "USD": DIFFERENCE}


# -- period --------------------------------------------------------------------


def test_period_outside_and_unknown_excluded() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", when=date(2027, 1, 5)),  # outside
            gl_line("J2", 1, "4000", credit="100", when=None),  # unknown date
        ),
        request(policy()),
    )
    assert set(kinds(report)) == {PERIOD_OUTSIDE, PERIOD_UNKNOWN}


# -- duplicates ----------------------------------------------------------------


def test_duplicate_gl_identity_reported_without_verdict() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100"),),
        (
            gl_line("J1", 1, "4000", credit="100", row=2),
            gl_line("J1", 1, "4000", credit="100", row=3),
        ),
        request(policy()),
    )
    assert DUPLICATE_GL in kinds(report)
    assert RECONCILED not in kinds(report) and DIFFERENCE not in kinds(report)


def test_duplicate_sales_key_reported_without_verdict() -> None:
    report = compare_sales_to_gl(
        (sales_entry("1", "100", row=2), sales_entry("1", "100", row=3)),
        (gl_line("J1", 1, "4000", credit="100"),),
        request(policy()),
    )
    assert DUPLICATE_SALES in kinds(report)
    assert RECONCILED not in kinds(report) and DIFFERENCE not in kinds(report)


# -- credit notes and reversals ------------------------------------------------


def test_gl_reversal_linked_and_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
            gl_line("J8", 1, "4000", debit="100", reversal=True, ref="MISSING", row=4),
        ),
        request(policy()),
    )
    assert REVERSAL_NOTED in kinds(report)
    assert REVERSAL_UNVERIFIED in kinds(report)


def test_sales_credit_note_linked_and_unverified() -> None:
    report = compare_sales_to_gl(
        (
            sales_entry("1", "100", row=2),
            sales_entry("C1", "100", credit=True, ref="1", row=3),
            sales_entry("C2", "100", credit=True, ref="NOPE", row=4),
        ),
        (gl_line("J1", 1, "4000", credit="100"),),
        request(policy()),
    )
    assert CREDIT_NOTE_LINKED in kinds(report)
    assert CREDIT_NOTE_UNVERIFIED in kinds(report)


# -- exactness + determinism ---------------------------------------------------


def test_long_decimal_precision_is_exact() -> None:
    big = "1234567890123456789012345.6789"
    report = compare_sales_to_gl(
        (sales_entry("1", big),),
        (gl_line("J1", 1, "4000", credit=big),),
        request(policy()),
    )
    assert kinds(report) == [RECONCILED]
    assert report.outcomes[0].delta == Decimal("0")


def test_permutation_stability_of_fingerprint() -> None:
    sales = (sales_entry("1", "100", row=2), sales_entry("2", "50", row=3))
    gl = (gl_line("J1", 1, "4000", credit="100", row=2), gl_line("J2", 1, "4000", credit="50", row=3))
    forward = compare_sales_to_gl(sales, gl, request(policy()))
    reversed_ = compare_sales_to_gl(tuple(reversed(sales)), tuple(reversed(gl)), request(policy()))
    assert forward.fingerprint == reversed_.fingerprint


def test_zero_tolerance_defaults_and_matching_report_metadata() -> None:
    report = compare_sales_to_gl((), (), request(policy()))
    assert report.blocked is False
    assert report.sales_measure == MEASURE_NET
    assert report.currency_scope == ("JOD",)
