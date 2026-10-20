"""REC-UI-01 synthetic demo fixtures (static, versioned, deterministic).

These scenarios are wholly invented test data for the accountant-facing
reconciliation walkthrough. They contain no customer records, are never
persisted, and are rebuilt in memory on every call before being handed to the
existing pure REC-005 engine (``app.recon.gl``). The comparison policy is an
explicitly synthetic *declared* manifest (``authority="synthetic-demo-only"``):
it is NOT a production accounting rule, and a positive report built from it is a
conditional pure-domain calculation, not production authority.

Fixture ``synthetic-sales-gl-v1`` yields four distinct engine outcomes for a
small Jordan-flavoured book:

- JOD: the sales-register NET total (3500.000) exceeds the in-scope GL posting
  total (3400.000) by exactly 100.000 -> ``DIFFERENCE``.
- JOD: one credit note linked to invoice INV-1002 -> ``CREDIT_NOTE_LINKED``.
- JOD: one reversal linked to journal J-1 -> ``REVERSAL_NOTED``.
- USD: a duplicated sales invoice contaminates coverage, so the currency is
  reported ``INCONCLUSIVE_COVERAGE`` (``DUPLICATE_SALES``) and never a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.recon.contracts import InvoiceProvenance
from app.recon.gl import (
    BASIS_AGGREGATE_PERIOD,
    CREDIT_POSITIVE,
    MEASURE_NET,
    POLICY_APPROVED,
    GLComparisonPolicy,
    GLEntryProvenance,
    GLLine,
    GLPolicyProvenance,
    SalesRegisterEntry,
)

# Mandatory marker carried on every demo screen and export. The ASCII variant is
# used inside the dependency-free PDF renderer (Latin-1 core fonts only).
SYNTHETIC_LABEL = "SYNTHETIC DEMO DATA — NOT CUSTOMER RECORDS / NOT A TAX FILING"
SYNTHETIC_LABEL_ASCII = "SYNTHETIC DEMO DATA - NOT CUSTOMER RECORDS / NOT A TAX FILING"

DEMO_JURISDICTION = "JO"
DEMO_RULES_VERSION = "1"
SALES_DATASET_ID = "SYNTHETIC-SALES-v1"
GL_DATASET_ID = "SYNTHETIC-GL-v1"
_FIXTURE_ID = "synthetic-sales-gl-v1"
_ISSUER = "Synthetic Trading LLC"
_EXPORTER = "Synthetic Export Co"


@dataclass(frozen=True)
class DemoFixture:
    """One fully-built, deterministic synthetic scenario (no I/O)."""

    fixture_id: str
    title: str
    description: str
    jurisdiction: str
    rules_version: str
    sales_dataset_id: str
    gl_dataset_id: str
    period_start: date
    period_end: date
    policy: GLComparisonPolicy
    sales: tuple[SalesRegisterEntry, ...]
    gl: tuple[GLLine, ...]


def _sales(
    number: str,
    net: str | None,
    *,
    currency: str | None,
    when: date | None,
    row: int,
    issuer: str = _ISSUER,
    credit: bool = False,
    reversal: bool = False,
    ref: str | None = None,
) -> SalesRegisterEntry:
    return SalesRegisterEntry(
        issuer=issuer,
        invoice_number=number,
        net_amount=Decimal(net) if net is not None else None,
        net_raw=net or "",
        tax_amount=None,
        tax_raw="",
        gross_amount=None,
        gross_raw="",
        currency=currency,
        transaction_date=when,
        is_credit_note=credit,
        is_reversal=reversal,
        reference_number=ref,
        provenance=InvoiceProvenance(
            dataset_id=SALES_DATASET_ID,
            source="sales_register",
            row_number=row,
            raw_invoice=number,
        ),
    )


def _gl(
    journal: str,
    line: int,
    account: str,
    *,
    debit: str | None = None,
    credit: str | None = None,
    currency: str | None,
    when: date | None,
    row: int,
    reversal: bool = False,
    ref: str | None = None,
) -> GLLine:
    return GLLine(
        journal_id=journal,
        line_number=line,
        account_code=account,
        transaction_date=when,
        debit=Decimal(debit) if debit is not None else None,
        credit=Decimal(credit) if credit is not None else None,
        debit_raw=debit or "",
        credit_raw=credit or "",
        currency=currency,
        description=f"{journal}-{line}",
        is_reversal=reversal,
        reversal_reference=ref,
        provenance=GLEntryProvenance(
            dataset_id=GL_DATASET_ID,
            source="general_ledger",
            row_number=row,
            raw_reference=f"{journal}-{line}",
        ),
    )


def _build_sales_gl_v1() -> DemoFixture:
    policy = GLComparisonPolicy(
        policy_id="DEMO-GL-POL-1",
        policy_version="1",
        status=POLICY_APPROVED,
        comparison_basis=BASIS_AGGREGATE_PERIOD,
        sales_measure=MEASURE_NET,
        gl_account_scope=("4100",),
        debit_credit_convention=CREDIT_POSITIVE,
        currency_scope=("JOD", "USD"),
        tolerance=Decimal("0"),
        rules_version=DEMO_RULES_VERSION,
        approved_by="synthetic-demo-reviewer",
        approved_at="2026-01-01",
        provenance=GLPolicyProvenance(authority="synthetic-demo-only", reference="REC-UI-01"),
    )
    sales = (
        _sales("INV-1001", "1000.000", currency="JOD", when=date(2026, 3, 1), row=2),
        _sales("INV-1002", "2000.000", currency="JOD", when=date(2026, 3, 5), row=3),
        _sales("INV-1003", "500.000", currency="JOD", when=date(2026, 3, 10), row=4),
        _sales("CN-1", "250.000", currency="JOD", when=date(2026, 3, 20), row=5, credit=True, ref="INV-1002"),
        # A duplicated identity contaminates the USD currency bucket.
        _sales("USD-5001", "500.000", currency="USD", when=date(2026, 3, 1), row=6, issuer=_EXPORTER),
        _sales("USD-5001", "500.000", currency="USD", when=date(2026, 3, 1), row=7, issuer=_EXPORTER),
    )
    gl = (
        _gl("J-1", 1, "4100", credit="1000.000", currency="JOD", when=date(2026, 3, 1), row=2),
        _gl("J-2", 1, "4100", credit="2000.000", currency="JOD", when=date(2026, 3, 5), row=3),
        _gl("J-3", 1, "4100", credit="400.000", currency="JOD", when=date(2026, 3, 10), row=4),
        _gl(
            "J-9",
            1,
            "4100",
            credit="1000.000",
            currency="JOD",
            when=date(2026, 4, 1),
            row=5,
            reversal=True,
            ref="J-1",
        ),
        _gl("J-5", 1, "4100", credit="500.000", currency="USD", when=date(2026, 3, 1), row=6),
    )
    return DemoFixture(
        fixture_id=_FIXTURE_ID,
        title="Sales register vs general ledger (JOD + USD)",
        description=(
            "Synthetic JOD book that reconciles to a 100.000 difference, with a linked credit note "
            "and reversal; a duplicated USD export makes that currency inconclusive."
        ),
        jurisdiction=DEMO_JURISDICTION,
        rules_version=DEMO_RULES_VERSION,
        sales_dataset_id=SALES_DATASET_ID,
        gl_dataset_id=GL_DATASET_ID,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        policy=policy,
        sales=sales,
        gl=gl,
    )


FIXTURES: dict[str, DemoFixture] = {_FIXTURE_ID: _build_sales_gl_v1()}


def get_fixture(fixture_id: str) -> DemoFixture | None:
    """Return the named synthetic fixture, or None (caller fails closed)."""
    return FIXTURES.get(fixture_id)


__all__ = [
    "FIXTURES",
    "SYNTHETIC_LABEL",
    "SYNTHETIC_LABEL_ASCII",
    "DemoFixture",
    "get_fixture",
]
