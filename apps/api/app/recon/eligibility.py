"""Dataset eligibility evaluation for reconciliation runs (REC-SLICE-03).

Pure default-deny contract: a run is eligible only when every gate in the
precedence order below is satisfied from persisted trusted data. Caller
supplied IDs or labels are never proof — the API layer assembles the snapshot
from server-side reads, and any gate that cannot be verified from a persisted
trusted source stays False (execution refused with a stable machine-readable
reason). No database, HTTP, or financial contents anywhere here.
"""

from __future__ import annotations

from dataclasses import dataclass

ELIGIBLE = "ELIGIBLE"
ENGAGEMENT_NOT_ACTIVE = "ENGAGEMENT_NOT_ACTIVE"
UNCONFIRMED_JURISDICTION = "UNCONFIRMED_JURISDICTION"
MISSING_DATASET_VERSION = "MISSING_DATASET_VERSION"
UNAPPROVED_MAPPING = "UNAPPROVED_MAPPING"
SOURCE_NOT_RELEASED = "SOURCE_NOT_RELEASED"
UNSUPPORTED_JOFO_PROFILE = "UNSUPPORTED_JOFO_PROFILE"

# Evaluation precedence (first failure wins; engagement-level gates before
# dataset-level gates; dataset identity before approvals before release).
_PRECEDENCE = (
    ENGAGEMENT_NOT_ACTIVE,
    UNCONFIRMED_JURISDICTION,
    MISSING_DATASET_VERSION,
    UNAPPROVED_MAPPING,
    SOURCE_NOT_RELEASED,
    UNSUPPORTED_JOFO_PROFILE,
)


@dataclass(frozen=True)
class EligibilitySnapshot:
    """Server-assembled view of the gates for one run request.

    Each flag must come from persisted trusted data (or stay False when the
    backing store does not exist yet — e.g. no dataset-version registry, no
    mapping-approval store, no release-gate log, no approved JoFotara profile
    catalog on main). Synthetic fixtures never set these True.
    """

    engagement_active: bool = False
    jurisdiction_confirmed: bool = False
    sales_version_present: bool = False
    jofo_version_present: bool = False
    mapping_approved: bool = False
    source_released: bool = False
    jofo_profile_supported: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    """Outcome of evaluate(): eligible iff reason == ELIGIBLE."""

    eligible: bool
    reason: str


def evaluate(snapshot: EligibilitySnapshot) -> EligibilityDecision:
    """Evaluate gates in precedence order (pure function)."""
    if not isinstance(snapshot, EligibilitySnapshot):
        raise TypeError(f"snapshot must be EligibilitySnapshot, got {type(snapshot).__name__}")
    gates = {
        ENGAGEMENT_NOT_ACTIVE: snapshot.engagement_active,
        UNCONFIRMED_JURISDICTION: snapshot.jurisdiction_confirmed,
        MISSING_DATASET_VERSION: snapshot.sales_version_present and snapshot.jofo_version_present,
        UNAPPROVED_MAPPING: snapshot.mapping_approved,
        SOURCE_NOT_RELEASED: snapshot.source_released,
        UNSUPPORTED_JOFO_PROFILE: snapshot.jofo_profile_supported,
    }
    for reason in _PRECEDENCE:
        if not gates[reason]:
            return EligibilityDecision(eligible=False, reason=reason)
    return EligibilityDecision(eligible=True, reason=ELIGIBLE)
