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
    COVERAGE_CURRENCY_OUT_OF_SCOPE,
    COVERAGE_INVALID_DEBIT_CREDIT_PAIR,
    COVERAGE_MISSING_CURRENCY,
    COVERAGE_MISSING_MEASURE,
    COVERAGE_PERIOD_UNKNOWN,
    CREDIT_NOTE_LINKED,
    CREDIT_NOTE_UNVERIFIED,
    CREDIT_POSITIVE,
    CURRENCY_NOT_IN_SCOPE,
    DIFFERENCE,
    DUPLICATE_GL,
    DUPLICATE_SALES,
    INCONCLUSIVE_COVERAGE,
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
    currency: str | None = "JOD",
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
    # F1: the invalid line contaminates JOD coverage, so the matched pair can
    # never yield an affirmative reconciliation despite equal valid totals.
    assert RECONCILED not in kinds(report)
    assert INCONCLUSIVE_COVERAGE in kinds(report)
    assert report.inconclusive is True
    assert COVERAGE_INVALID_DEBIT_CREDIT_PAIR in report.inconclusive_reasons


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
    assert kinds(report).count(CURRENCY_NOT_IN_SCOPE) == 2
    # F1: a currency outside the approved scope means the run's coverage cannot
    # be established; the comparison is explicitly inconclusive, never conclusive.
    assert INCONCLUSIVE_COVERAGE in kinds(report)
    assert RECONCILED not in kinds(report) and DIFFERENCE not in kinds(report)
    assert COVERAGE_CURRENCY_OUT_OF_SCOPE in report.inconclusive_reasons


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
    # PERIOD_OUTSIDE is a legitimate in-period exclusion (no contamination);
    # PERIOD_UNKNOWN contaminates because the period cannot be established.
    assert set(kinds(report)) == {PERIOD_OUTSIDE, PERIOD_UNKNOWN, INCONCLUSIVE_COVERAGE}
    assert COVERAGE_PERIOD_UNKNOWN in report.inconclusive_reasons
    assert COVERAGE_MISSING_CURRENCY not in report.inconclusive_reasons


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


# -- F1: completeness / contamination ------------------------------------------


def _matched_pair() -> tuple[tuple, tuple]:
    return (sales_entry("1", "100", row=2),), (gl_line("J1", 1, "4000", credit="100", row=2),)


def test_valid_pair_with_unresolved_gl_record_cannot_reconcile() -> None:
    sales, gl = _matched_pair()
    report = compare_sales_to_gl(
        sales,
        gl + (gl_line("J2", 1, "4000", debit="100", credit="100", row=3),),
        request(policy()),
    )
    assert RECONCILED not in kinds(report) and DIFFERENCE not in kinds(report)
    assert INCONCLUSIVE_COVERAGE in kinds(report)
    assert report.inconclusive is True
    jod = [o for o in report.outcomes if o.kind == INCONCLUSIVE_COVERAGE and o.currency == "JOD"]
    assert jod  # the affected currency is explicitly reported inconclusive


def test_each_contamination_scenario_blocks_conclusive_verdict() -> None:
    cases = (
        ("gl_invalid_pair", (), (gl_line("J2", 1, "4000", debit="100", credit="100", row=3),)),
        ("gl_missing_amount", (), (gl_line("J2", 1, "4000", row=3),)),
        ("gl_missing_currency", (), (gl_line("J2", 1, "4000", credit="100", currency=None, row=3),)),
        ("gl_period_unknown", (), (gl_line("J2", 1, "4000", credit="100", when=None, row=3),)),
        ("gl_duplicate", (), (gl_line("J1", 1, "4000", credit="100", row=3),)),
        (
            "gl_reversal_unverified",
            (),
            (gl_line("J9", 1, "4000", debit="100", reversal=True, ref="GHOST", row=3),),
        ),
        ("gl_out_of_scope_currency", (), (gl_line("J2", 1, "4000", credit="100", currency="USD", row=3),)),
        ("sales_missing_measure", (sales_entry("2", net=None, gross="100", row=3),), ()),
        ("sales_missing_currency", (sales_entry("2", "100", currency=None, row=3),), ()),
        ("sales_period_unknown", (sales_entry("2", "100", when=None, row=3),), ()),
        ("sales_duplicate", (sales_entry("1", "100", row=3),), ()),
        ("sales_note_unverified", (sales_entry("C1", "100", credit=True, ref="NOPE", row=3),), ()),
        ("sales_out_of_scope_currency", (sales_entry("2", "100", currency="USD", row=3),), ()),
    )
    for label, extra_sales, extra_gl in cases:
        sales, gl = _matched_pair()
        report = compare_sales_to_gl(sales + extra_sales, gl + extra_gl, request(policy()))
        assert RECONCILED not in kinds(report), f"{label}: false RECONCILED"
        assert DIFFERENCE not in kinds(report), f"{label}: false DIFFERENCE"
        assert INCONCLUSIVE_COVERAGE in kinds(report), f"{label}: not inconclusive"
        assert report.inconclusive is True, f"{label}: report not flagged inconclusive"


def test_out_of_period_records_do_not_contaminate() -> None:
    sales, gl = _matched_pair()
    report = compare_sales_to_gl(
        sales,
        gl + (gl_line("J2", 1, "4000", credit="100", when=date(2027, 1, 5), row=3),),
        request(policy()),
    )
    # Legitimate in-period filter: the out-of-period row is excluded but does
    # not make coverage uncertain, so the matched pair still reconciles.
    assert PERIOD_OUTSIDE in kinds(report)
    assert RECONCILED in kinds(report)
    assert report.inconclusive is False
    assert report.inconclusive_reasons == ()


def test_missing_currency_makes_whole_comparison_inconclusive() -> None:
    sales, gl = _matched_pair()
    report = compare_sales_to_gl(
        sales,
        gl + (gl_line("J2", 1, "4000", credit="100", currency=None, row=3),),
        request(policy()),
    )
    assert RECONCILED not in kinds(report)
    assert any(o.kind == INCONCLUSIVE_COVERAGE and o.currency == "JOD" for o in report.outcomes)
    assert COVERAGE_MISSING_CURRENCY in report.inconclusive_reasons


def test_only_global_contamination_yields_single_inconclusive_outcome() -> None:
    report = compare_sales_to_gl(
        (), (gl_line("J1", 1, "4000", credit="100", currency=None),), request(policy())
    )
    # The diagnostic for the unassignable row is preserved, and the run is
    # flagged inconclusive with a currency-less outcome (no currency bucket).
    assert kinds(report) == [MISSING_VALUE, INCONCLUSIVE_COVERAGE]
    assert report.outcomes[-1].currency is None
    assert report.inconclusive is True
    assert COVERAGE_MISSING_CURRENCY in report.inconclusive_reasons


def test_contamination_scenarios_together_union_of_reasons() -> None:
    sales = (sales_entry("1", "100", row=2), sales_entry("2", net=None, gross="100", row=3))
    gl = (
        gl_line("J1", 1, "4000", credit="100", row=2),
        gl_line("J2", 1, "4000", debit="1", credit="1", row=3),
        gl_line("J3", 1, "4000", credit="100", when=None, row=4),
    )
    report = compare_sales_to_gl(sales, gl, request(policy()))
    assert INCONCLUSIVE_COVERAGE in kinds(report)
    assert RECONCILED not in kinds(report)
    assert {
        COVERAGE_MISSING_MEASURE,
        COVERAGE_INVALID_DEBIT_CREDIT_PAIR,
        COVERAGE_PERIOD_UNKNOWN,
    } <= set(report.inconclusive_reasons)


def test_inconclusive_fingerprint_is_permutation_stable() -> None:
    sales, gl = _matched_pair()
    gl = gl + (gl_line("J2", 1, "4000", debit="100", credit="100", row=3),)
    forward = compare_sales_to_gl(sales, gl, request(policy()))
    reversed_ = compare_sales_to_gl(tuple(reversed(sales)), tuple(reversed(gl)), request(policy()))
    assert forward.inconclusive is True
    assert forward.fingerprint == reversed_.fingerprint


# -- F3: reversal / credit-note link verification ------------------------------


def test_reversal_self_reference_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (gl_line("J5", 1, "4000", debit="100", reversal=True, ref="J5"),),
        request(policy()),
    )
    unverified = [o for o in report.outcomes if o.kind == REVERSAL_UNVERIFIED]
    assert unverified and unverified[0].flags == ("SELF_REFERENCE",)
    assert REVERSAL_NOTED not in kinds(report)


def test_reversal_only_cycle_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("JA", 1, "4000", debit="100", reversal=True, ref="JB", row=2),
            gl_line("JB", 1, "4000", debit="100", reversal=True, ref="JA", row=3),
        ),
        request(policy()),
    )
    unverified = [o for o in report.outcomes if o.kind == REVERSAL_UNVERIFIED]
    assert len(unverified) == 2
    assert all(o.flags == ("REFERENCE_UNQUALIFIED",) for o in unverified)
    assert REVERSAL_NOTED not in kinds(report)


def test_reversal_unresolved_reference_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="GHOST", row=3),
        ),
        request(policy()),
    )
    unverified = [o for o in report.outcomes if o.kind == REVERSAL_UNVERIFIED]
    assert unverified and unverified[0].flags == ("REFERENCE_UNRESOLVED",)


def test_reversal_valid_original_posting_is_verified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    noted = [o for o in report.outcomes if o.kind == REVERSAL_NOTED]
    assert noted and noted[0].flags == ("REFERENCE_VERIFIED",)


def test_reversal_reference_to_out_of_scope_original_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "9999", credit="100", row=2),  # account 9999 not in scope
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    assert REVERSAL_NOTED not in kinds(report)
    assert REVERSAL_UNVERIFIED in kinds(report)


def test_sales_credit_note_self_reference_is_unverified() -> None:
    report = compare_sales_to_gl(
        (sales_entry("C1", "100", credit=True, ref="C1", row=2),),
        (gl_line("J1", 1, "4000", credit="100"),),
        request(policy()),
    )
    unverified = [o for o in report.outcomes if o.kind == CREDIT_NOTE_UNVERIFIED]
    assert unverified and unverified[0].flags == ("SELF_REFERENCE",)
    assert CREDIT_NOTE_LINKED not in kinds(report)


def _assert_reversal_unqualified(report) -> None:
    assert REVERSAL_NOTED not in kinds(report)
    unverified = [o for o in report.outcomes if o.kind == REVERSAL_UNVERIFIED]
    assert unverified and unverified[0].flags == ("REFERENCE_UNQUALIFIED",)


def test_reversal_reference_to_malformed_original_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", debit="100", credit="100", row=2),  # both set
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    _assert_reversal_unqualified(report)


def test_reversal_reference_to_original_without_amount_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", row=2),  # neither debit nor credit
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    _assert_reversal_unqualified(report)


def test_reversal_reference_to_original_without_currency_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", currency=None, row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    _assert_reversal_unqualified(report)


def test_reversal_reference_to_original_with_unknown_period_is_unverified() -> None:
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", when=None, row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    _assert_reversal_unqualified(report)


def test_reversal_reference_to_out_of_period_valid_original_is_verified() -> None:
    # A known-date original outside the window is still a valid qualifying
    # posting (reversals of prior-period documents are legitimate).
    report = compare_sales_to_gl(
        (),
        (
            gl_line("J1", 1, "4000", credit="100", when=date(2027, 1, 5), row=2),
            gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J1", row=3),
        ),
        request(policy()),
    )
    noted = [o for o in report.outcomes if o.kind == REVERSAL_NOTED]
    assert noted and noted[0].flags == ("REFERENCE_VERIFIED",)


def test_reversal_outcomes_are_permutation_stable() -> None:
    rows = (
        gl_line("J1", 1, "4000", credit="100", row=2),
        gl_line("J2", 1, "4000", debit="100", credit="100", row=3),  # malformed original
        gl_line("J8", 1, "4000", debit="100", reversal=True, ref="J1", row=4),
        gl_line("J9", 1, "4000", debit="100", reversal=True, ref="J2", row=5),
    )
    forward = compare_sales_to_gl((), rows, request(policy()))
    reversed_ = compare_sales_to_gl((), tuple(reversed(rows)), request(policy()))
    assert forward.fingerprint == reversed_.fingerprint
    assert kinds(forward) == kinds(reversed_)
