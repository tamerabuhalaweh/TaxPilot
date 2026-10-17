"""REC-DATA-02 human-confirmed mapping-approval contracts (pure, default-deny).

Mapping approval is an INDEPENDENT artifact: registration (REC-DATA-01) and source
release (REC-DATA-03) do not approve a mapping, and an AI suggestion is never
approval. This module owns the *policy boundary* only: no database, HTTP, file,
network, or financial contents.

Design invariants (issue #63):

- **Master default-deny.** ``ApprovalContext.approval_enabled`` defaults to
  ``False``, so :func:`evaluate_mapping_approval` returns
  ``MAPPING_APPROVAL_NOT_ENABLED`` unconditionally.
- **Trusted inputs only.** The header fingerprint is always SERVER-DERIVED from
  trusted source headers via ``fingerprint_headers``; a caller can never supply a
  fingerprint, a boolean, or a role label that forges approval. Absent trusted
  headers (the current state — extraction/read is blocked) refuses with
  ``SOURCE_HEADERS_UNAVAILABLE``.
- **Approval = latest human decision.** An explicit APPROVED review decision by a
  verified reviewer is required; a proposal is only a proposal, and a later
  REJECTED/SUPERSEDED decision wins.
- **Staleness is derived, never rewritten.** A change to the dataset version,
  header shape, mapping/normalization/schema version, or engagement revision
  makes any prior approval stale.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from app.normalization.contracts import ConfirmedMapping
from app.normalization.mapping import fingerprint_headers, validate_mapping

KNOWN_SCHEMA_VERSIONS = ("mapping-v1",)

# Review-decision outcomes (append-only; revocation is a NEW decision row).
DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"
DECISION_SUPERSEDED = "SUPERSEDED"
KNOWN_DECISIONS = (DECISION_APPROVED, DECISION_REJECTED, DECISION_SUPERSEDED)

# Approval outcomes / refusal reasons (first failure wins).
APPROVED = "APPROVED"
MAPPING_APPROVAL_NOT_ENABLED = "MAPPING_APPROVAL_NOT_ENABLED"
SOURCE_HEADERS_UNAVAILABLE = "SOURCE_HEADERS_UNAVAILABLE"
MISSING_PROPOSAL = "MISSING_PROPOSAL"
UNCONFIRMED_PROPOSAL = "UNCONFIRMED_PROPOSAL"
UNKNOWN_SCHEMA_VERSION = "UNKNOWN_SCHEMA_VERSION"
STALE_DATASET_VERSION = "STALE_DATASET_VERSION"
STALE_HEADER_FINGERPRINT = "STALE_HEADER_FINGERPRINT"
STALE_MAPPING_VERSION = "STALE_MAPPING_VERSION"
STALE_NORMALIZATION_VERSION = "STALE_NORMALIZATION_VERSION"
STALE_SCHEMA_VERSION = "STALE_SCHEMA_VERSION"
STALE_ENGAGEMENT_REVISION = "STALE_ENGAGEMENT_REVISION"
INVALID_MAPPING = "INVALID_MAPPING"
MISSING_APPROVAL = "MISSING_APPROVAL"
MAPPING_REJECTED = "MAPPING_REJECTED"
MAPPING_SUPERSEDED = "MAPPING_SUPERSEDED"
UNTRUSTED_REVIEWER = "UNTRUSTED_REVIEWER"


@dataclass(frozen=True)
class ApprovalCoordinates:
    """Exact context an approval must match (server-derived, never caller-provided).

    ``header_fingerprint`` is intentionally absent: it is derived from trusted
    headers inside :func:`evaluate_mapping_approval`.
    """

    dataset_version_id: str
    engagement_revision: int
    mapping_version: str
    normalization_version: str
    canonical_schema_version: str


@dataclass(frozen=True)
class MappingProposal:
    """Immutable, versioned mapping revision under review (a proposal, never approval)."""

    proposal_id: str
    tenant_id: str
    client_id: str
    engagement_id: str
    dataset_version_id: str
    doc_type: str
    header_fingerprint: str
    field_map: Mapping[str, str]
    mapping_version: str
    normalization_version: str
    canonical_schema_version: str
    engagement_revision: int
    confirmed: bool
    proposed_by: str = ""
    proposed_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.field_map, Mapping):
            raise TypeError(f"field_map must be a mapping, got {type(self.field_map).__name__}")
        object.__setattr__(self, "field_map", MappingProxyType(dict(self.field_map)))


@dataclass(frozen=True)
class MappingDecision:
    """One append-only review decision (approve/reject/supersede) by a reviewer."""

    decision_id: str
    tenant_id: str
    proposal_id: str
    decision: str
    reviewer_id: str = ""
    decided_at: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ApprovalOutcome:
    """Derived outcome (``approved`` iff ``APPROVED``); never a compliance claim."""

    approved: bool
    reason: str
    issues: tuple[str, ...] = field(default_factory=tuple)


def proposal_fingerprint(
    *,
    dataset_version_id: str,
    doc_type: str,
    header_fingerprint: str,
    field_map: Mapping[str, str],
    mapping_version: str,
    normalization_version: str,
    canonical_schema_version: str,
) -> str:
    """Stable sha256 identity of one proposal intent (idempotency anchor).

    Canonical JSON over the exact mapping identity; the field map is serialized
    with sorted keys so a reordered map is the same proposal.
    """
    payload = {
        "dataset_version_id": dataset_version_id,
        "doc_type": doc_type,
        "header_fingerprint": header_fingerprint,
        "field_map": {str(k): str(v) for k, v in sorted(field_map.items())},
        "mapping_version": mapping_version,
        "normalization_version": normalization_version,
        "canonical_schema_version": canonical_schema_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def latest_decision(decisions: Sequence[MappingDecision]) -> MappingDecision | None:
    """Latest decision by (decided_at, decision_id); deterministic, no clock use."""
    if not decisions:
        return None
    return max(decisions, key=lambda d: (d.decided_at, d.decision_id))


def staleness_reason(
    proposal: MappingProposal,
    coordinates: ApprovalCoordinates,
    *,
    header_fingerprint: str,
) -> str:
    """First context mismatch that makes ``proposal`` stale, or ``""`` if fresh."""
    if proposal.dataset_version_id != coordinates.dataset_version_id:
        return STALE_DATASET_VERSION
    if proposal.header_fingerprint != header_fingerprint:
        return STALE_HEADER_FINGERPRINT
    if proposal.mapping_version != coordinates.mapping_version:
        return STALE_MAPPING_VERSION
    if proposal.normalization_version != coordinates.normalization_version:
        return STALE_NORMALIZATION_VERSION
    if proposal.canonical_schema_version != coordinates.canonical_schema_version:
        return STALE_SCHEMA_VERSION
    if proposal.engagement_revision != coordinates.engagement_revision:
        return STALE_ENGAGEMENT_REVISION
    return ""


def evaluate_mapping_approval(
    *,
    proposal: MappingProposal | None,
    decisions: Sequence[MappingDecision],
    coordinates: ApprovalCoordinates,
    trusted_headers: Sequence[str] | None,
    approval_enabled: bool = False,
) -> ApprovalOutcome:
    """Default-deny mapping-approval gate (pure; first failure wins).

    The header fingerprint is derived from ``trusted_headers``; when they are
    unavailable (no trusted source-header attestation yet), approval is refused.
    """
    if not approval_enabled:
        return ApprovalOutcome(False, MAPPING_APPROVAL_NOT_ENABLED)
    if trusted_headers is None:
        return ApprovalOutcome(False, SOURCE_HEADERS_UNAVAILABLE)
    headers = tuple(trusted_headers)
    fingerprint = fingerprint_headers(headers)
    if coordinates.canonical_schema_version not in KNOWN_SCHEMA_VERSIONS:
        return ApprovalOutcome(False, UNKNOWN_SCHEMA_VERSION)
    if proposal is None:
        return ApprovalOutcome(False, MISSING_PROPOSAL)
    if not proposal.confirmed:
        return ApprovalOutcome(False, UNCONFIRMED_PROPOSAL)
    stale = staleness_reason(proposal, coordinates, header_fingerprint=fingerprint)
    if stale:
        return ApprovalOutcome(False, stale)
    report = validate_mapping(
        headers,
        ConfirmedMapping(
            field_map=dict(proposal.field_map),
            confirmed=True,
            mapping_version=proposal.mapping_version,
        ),
        proposal.doc_type,
    )
    if not report.ok:
        return ApprovalOutcome(False, INVALID_MAPPING, tuple(i.code for i in report.issues))
    decision = latest_decision(decisions)
    if decision is None:
        return ApprovalOutcome(False, MISSING_APPROVAL)
    if decision.decision == DECISION_REJECTED:
        return ApprovalOutcome(False, MAPPING_REJECTED)
    if decision.decision == DECISION_SUPERSEDED:
        return ApprovalOutcome(False, MAPPING_SUPERSEDED)
    if decision.decision != DECISION_APPROVED:
        return ApprovalOutcome(False, MISSING_APPROVAL)
    if not decision.reviewer_id:
        return ApprovalOutcome(False, UNTRUSTED_REVIEWER)
    return ApprovalOutcome(True, APPROVED)
