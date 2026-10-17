"""REC-005 comparison-policy validation (default-deny, pure).

A run may proceed only when its governing :class:`GLComparisonPolicy` is an
APPROVED manifest whose every required dimension is present *and* grounded in a
supported comparison level. Anything else yields typed block reasons and the
engine refuses (see ``gl.matching``). This module performs no authorization: it
only checks the declared manifest for internal completeness, exactly like the
normalization/JoFotara "declared is not verified" contracts.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.recon.gl.contracts import (
    CONVENTIONS,
    POLICY_APPROVED,
    POLICY_MISSING_ACCOUNT_SCOPE,
    POLICY_MISSING_BASIS,
    POLICY_MISSING_CONVENTION,
    POLICY_MISSING_CURRENCY_SCOPE,
    POLICY_MISSING_PROVENANCE,
    POLICY_MISSING_SALES_MEASURE,
    POLICY_NOT_APPROVED,
    POLICY_UNSUPPORTED_BASIS,
    SALES_MEASURES,
    SUPPORTED_BASES,
    GLComparisonPolicy,
)


@dataclass(frozen=True)
class PolicyDecision:
    """Result of policy validation (approved iff ``reasons`` is empty)."""

    approved: bool
    reasons: tuple[str, ...]


def validate_policy(policy: GLComparisonPolicy) -> PolicyDecision:
    """Validate a declared policy for completeness and grounded basis.

    Reasons are emitted in a stable order; the first is the most fundamental
    (status before provenance before dimensions). An APPROVED policy additionally
    requires an approver and declared provenance.
    """
    if not isinstance(policy, GLComparisonPolicy):
        raise TypeError(f"policy must be GLComparisonPolicy, got {type(policy).__name__}")
    reasons: list[str] = []
    if policy.status != POLICY_APPROVED:
        reasons.append(POLICY_NOT_APPROVED)
    elif not policy.approved_by.strip() or policy.provenance is None:
        reasons.append(POLICY_MISSING_PROVENANCE)
    if not policy.comparison_basis:
        reasons.append(POLICY_MISSING_BASIS)
    elif policy.comparison_basis not in SUPPORTED_BASES:
        reasons.append(POLICY_UNSUPPORTED_BASIS)
    if not policy.gl_account_scope:
        reasons.append(POLICY_MISSING_ACCOUNT_SCOPE)
    if not policy.currency_scope:
        reasons.append(POLICY_MISSING_CURRENCY_SCOPE)
    if policy.sales_measure not in SALES_MEASURES:
        reasons.append(POLICY_MISSING_SALES_MEASURE)
    if policy.debit_credit_convention not in CONVENTIONS:
        reasons.append(POLICY_MISSING_CONVENTION)
    reasons = list(dict.fromkeys(reasons))
    return PolicyDecision(approved=not reasons, reasons=tuple(reasons))
