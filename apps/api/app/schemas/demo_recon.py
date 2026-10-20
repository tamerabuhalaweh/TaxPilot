"""Request/response schemas for the REC-UI-01 synthetic demo boundary.

Amounts are exact Decimals serialized as strings and are always explicitly
labelled: every payload states ``synthetic=True`` and repeats the mandatory
marker in ``label``. No customer data, no uploaded content, no persistence.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DemoFixtureOut(BaseModel):
    fixture_id: str
    title: str
    description: str
    jurisdiction: str
    rules_version: str
    period_start: date
    period_end: date
    sales_dataset_id: str
    gl_dataset_id: str
    account_scope: list[str]
    currency_scope: list[str]


class DemoReconRunIn(BaseModel):
    fixture_id: str = Field(min_length=1, max_length=64)


class DemoMoney(BaseModel):
    amount: str
    currency: str


class DemoEvidence(BaseModel):
    dataset_id: str
    source: str
    row_number: int
    raw_reference: str
    role: Literal["sales", "gl"]


class DemoFinding(BaseModel):
    finding_id: str
    category: str
    severity: str
    review_state: str | None = None
    review_required: bool
    rule: str
    outcome_kind: str
    title: str
    what: str
    compared: str
    difference: str
    why: str
    guidance: str
    sales: list[DemoMoney]
    gl: list[DemoMoney]
    delta: str | None = None
    delta_currency: str | None = None
    evidence: list[DemoEvidence]
    rationale: list[str]
    flags: list[str]


class DemoCurrencyResult(BaseModel):
    currency: str
    outcome: Literal["DIFFERENCE", "INCONCLUSIVE_COVERAGE"]
    sales_total: str | None = None
    gl_total: str | None = None
    delta: str | None = None


class DemoCoverage(BaseModel):
    complete: bool
    currencies: list[str]
    reasons: list[str]
    explanations: list[str]


class DemoConclusion(BaseModel):
    """Presentation-only result summary; never a new calculation or verdict."""

    status: Literal["BLOCKED", "REVIEW_REQUIRED", "NO_REVIEW_ITEMS"]
    headline: str
    detail: str
    caution: str
    currency_results: list[DemoCurrencyResult]
    coverage: DemoCoverage


class DemoReconRunOut(BaseModel):
    synthetic: bool = True
    label: str
    fixture_id: str
    fixture_title: str
    jurisdiction: str
    rules_version: str
    period_start: date
    period_end: date
    policy_id: str | None = None
    policy_version: str | None = None
    comparison_basis: str | None = None
    sales_measure: str | None = None
    gl_account_scope: list[str]
    debit_credit_convention: str | None = None
    currency_scope: list[str]
    tolerance: str | None = None
    blocked: bool
    block_reasons: list[str]
    inconclusive: bool
    inconclusive_reasons: list[str]
    recon_fingerprint: str
    findings_fingerprint: str
    summary: dict[str, Any]
    findings: list[DemoFinding]
    conclusion: DemoConclusion
