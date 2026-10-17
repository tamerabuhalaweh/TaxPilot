"""Human-confirmed mapping-approval routes (REC-DATA-02).

Read-only scoped evidence plus default-deny mutation routes. Mapping approval is
independent of registration and release: no trusted source-header attestation
exists yet (extraction/read is blocked), so the server cannot derive the exact
header fingerprint an approval must bind. Proposal submission therefore refuses
with a stable 409 ``SOURCE_HEADERS_UNAVAILABLE`` and decision submission with
``MAPPING_APPROVAL_NOT_ENABLED``; neither persists anything, and a caller can
never supply a fingerprint, boolean, or role label that forges approval.

Read routes expose mapping metadata and explicit maps only: never trusted source
headers, bytes, storage keys, or financial contents.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from ..errors import AppError
from ..mapping.approval import (
    KNOWN_DECISIONS,
    KNOWN_SCHEMA_VERSIONS,
    ApprovalCoordinates,
    MappingDecision,
    MappingProposal,
    evaluate_mapping_approval,
)
from ..schemas.mapping import (
    MappingApprovalOut,
    MappingDecisionIn,
    MappingDecisionOut,
    MappingProposalIn,
    MappingProposalOut,
)
from ..sprint1_auth import (
    DECIDE,
    WRITE,
    CurrentUser,
    correlation_of,
    open_store,
    require_roles,
    require_tenant,
    tenant_of,
)

router = APIRouter(tags=["mappings"])

#: Master default-deny. Approval cannot be enabled until trusted source-header
#: attestation (and the REC-DATA-03 release/scanner decisions) exist.
APPROVAL_ENABLED = False


def _uuid_or_404(value: str | None, message: str) -> str:
    try:
        assert value is not None
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError, AssertionError):
        raise AppError("NOT_FOUND", message) from None


def _proposal_out(row: dict) -> MappingProposalOut:
    return MappingProposalOut(
        id=str(row["id"]),
        engagement_id=str(row["engagement_id"]),
        client_id=str(row["client_id"]),
        dataset_version_id=str(row["dataset_version_id"]),
        doc_type=row["doc_type"],
        header_fingerprint=row["header_fingerprint"],
        field_map=dict(row["field_map"] or {}),
        mapping_version=row["mapping_version"],
        normalization_version=row["normalization_version"],
        canonical_schema_version=row["canonical_schema_version"],
        proposed_by=str(row["proposed_by"]) if row.get("proposed_by") else None,
        proposed_at=row["proposed_at"],
    )


def _decision_out(row: dict) -> MappingDecisionOut:
    return MappingDecisionOut(
        id=str(row["id"]),
        proposal_id=str(row["proposal_id"]),
        dataset_version_id=str(row["dataset_version_id"]),
        decision=row["decision"],
        reviewer_id=str(row["reviewer_id"]) if row.get("reviewer_id") else None,
        reason=row.get("reason"),
        decided_at=row["decided_at"],
    )


def _require_engagement(store, tenant_id: str, engagement_id: str) -> dict:
    eid = _uuid_or_404(engagement_id, "Engagement not found.")
    engagement = store.get_engagement(eid, tenant_id)
    if engagement is None:
        raise AppError("NOT_FOUND", "Engagement not found.")
    return engagement


def _require_version_for_client(store, tenant_id: str, version_id: str, client_id: str) -> dict:
    vid = _uuid_or_404(version_id, "Dataset version not found.")
    version = store.get_dataset_version(vid, tenant_id)
    if version is None or str(version["client_id"]) != client_id:
        # No oracle: out-of-scope and missing versions are indistinguishable.
        raise AppError("NOT_FOUND", "Dataset version not found.")
    return version


@router.get("/engagements/{engagement_id}/mapping-proposals", response_model=list[MappingProposalOut])
def list_mapping_proposals(
    engagement_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> list[MappingProposalOut]:
    store, conn, _ = open_store(request)
    try:
        tenant_id = tenant_of(user)
        engagement = _require_engagement(store, tenant_id, engagement_id)
        rows = store.list_mapping_proposals(tenant_id, str(engagement["id"]))
        return [_proposal_out(r) for r in rows]
    finally:
        conn.close()


@router.get(
    "/engagements/{engagement_id}/mapping-proposals/{proposal_id}/decisions",
    response_model=list[MappingDecisionOut],
)
def list_mapping_decisions(
    engagement_id: str,
    proposal_id: str,
    request: Request,
    user: CurrentUser = Depends(require_tenant),
) -> list[MappingDecisionOut]:
    store, conn, _ = open_store(request)
    try:
        tenant_id = tenant_of(user)
        engagement = _require_engagement(store, tenant_id, engagement_id)
        pid = _uuid_or_404(proposal_id, "Mapping proposal not found.")
        proposal = store.get_mapping_proposal(pid, tenant_id)
        if proposal is None or str(proposal["engagement_id"]) != str(engagement["id"]):
            raise AppError("NOT_FOUND", "Mapping proposal not found.")
        return [_decision_out(r) for r in store.list_mapping_decisions(tenant_id, pid)]
    finally:
        conn.close()


@router.get(
    "/engagements/{engagement_id}/dataset-versions/{version_id}/mapping-approval",
    response_model=MappingApprovalOut,
)
def get_mapping_approval(
    engagement_id: str,
    version_id: str,
    request: Request,
    user: CurrentUser = Depends(require_tenant),
) -> MappingApprovalOut:
    """Derived approval status for one (engagement, dataset version).

    Default-deny: with no trusted source headers and approval disabled, this
    returns ``MAPPING_APPROVAL_NOT_ENABLED`` rather than inventing approval.
    """
    store, conn, _ = open_store(request)
    try:
        tenant_id = tenant_of(user)
        engagement = _require_engagement(store, tenant_id, engagement_id)
        version = _require_version_for_client(store, tenant_id, version_id, str(engagement["client_id"]))
        vid = str(version["id"])
        proposals = [
            p
            for p in store.list_mapping_proposals(tenant_id, str(engagement["id"]))
            if str(p["dataset_version_id"]) == vid
        ]
        proposal_row = proposals[-1] if proposals else None
        decisions: list[MappingDecision] = []
        proposal_model: MappingProposal | None = None
        if proposal_row is not None:
            decision_rows = store.list_mapping_decisions(tenant_id, str(proposal_row["id"]))
            decisions = [
                MappingDecision(
                    decision_id=str(d["id"]),
                    tenant_id=tenant_id,
                    proposal_id=str(d["proposal_id"]),
                    decision=d["decision"],
                    reviewer_id=str(d["reviewer_id"]) if d.get("reviewer_id") else "",
                    decided_at=d["decided_at"].isoformat() if d.get("decided_at") else "",
                    reason=d.get("reason") or "",
                )
                for d in decision_rows
            ]
            proposal_model = MappingProposal(
                proposal_id=str(proposal_row["id"]),
                tenant_id=tenant_id,
                client_id=str(proposal_row["client_id"]),
                engagement_id=str(proposal_row["engagement_id"]),
                dataset_version_id=str(proposal_row["dataset_version_id"]),
                doc_type=proposal_row["doc_type"],
                header_fingerprint=proposal_row["header_fingerprint"],
                field_map=dict(proposal_row["field_map"] or {}),
                mapping_version=proposal_row["mapping_version"],
                normalization_version=proposal_row["normalization_version"],
                canonical_schema_version=proposal_row["canonical_schema_version"],
                engagement_revision=proposal_row["engagement_revision"],
                confirmed=True,
            )
        coordinates = ApprovalCoordinates(
            dataset_version_id=vid,
            engagement_revision=engagement["revision"],
            mapping_version=version.get("mapping_revision") or "",
            normalization_version=version.get("normalization_version") or "",
            canonical_schema_version=KNOWN_SCHEMA_VERSIONS[-1],
        )
        outcome = evaluate_mapping_approval(
            proposal=proposal_model,
            decisions=decisions,
            coordinates=coordinates,
            trusted_headers=None,
            approval_enabled=APPROVAL_ENABLED,
        )
        return MappingApprovalOut(
            dataset_version_id=vid,
            approved=outcome.approved,
            reason=outcome.reason,
            issues=list(outcome.issues),
        )
    finally:
        conn.close()


@router.post("/engagements/{engagement_id}/mapping-proposals", status_code=201)
def submit_mapping_proposal(
    engagement_id: str,
    body: MappingProposalIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
):
    """Default-deny submission: refuses 409 and persists nothing.

    The server must derive the header fingerprint from trusted source headers;
    no such attestation exists yet, so no proposal row is fabricated. Callers
    cannot supply a fingerprint, boolean, or role label (schema forbids extras).
    """
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        engagement = _require_engagement(store, tenant_id, engagement_id)
        _require_version_for_client(store, tenant_id, body.dataset_version_id, str(engagement["client_id"]))
        if not body.field_map:
            raise AppError("VALIDATION_ERROR", "field_map must be a non-empty explicit map.")
        for name, value in (
            ("mapping_version", body.mapping_version),
            ("normalization_version", body.normalization_version),
            ("canonical_schema_version", body.canonical_schema_version),
        ):
            if not value.strip():
                raise AppError("VALIDATION_ERROR", f"{name} must be non-blank.")
        store.audit(
            "mapping_proposal.refused",
            tenant_id,
            user.user_id,
            f"engagement:{engagement['id']}",
            correlation_of(request),
        )
        conn.commit()
        raise AppError(
            "SOURCE_HEADERS_UNAVAILABLE",
            "Mapping proposals require server-verified trusted source headers, which are not available.",
        )
    except Exception:
        if conn.in_transaction():
            conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/engagements/{engagement_id}/mapping-proposals/{proposal_id}/decisions", status_code=201)
def submit_mapping_decision(
    engagement_id: str,
    proposal_id: str,
    body: MappingDecisionIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*DECIDE)),
):
    """Default-deny decision: refuses 409 and persists nothing.

    Approval requires trusted evidence and an approved release path; neither
    exists, so no decision row is fabricated. The reviewer is the authenticated
    caller (never a caller-supplied role label).
    """
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        engagement = _require_engagement(store, tenant_id, engagement_id)
        if body.decision not in KNOWN_DECISIONS:
            raise AppError("VALIDATION_ERROR", "decision must be APPROVED, REJECTED, or SUPERSEDED.")
        pid = _uuid_or_404(proposal_id, "Mapping proposal not found.")
        proposal = store.get_mapping_proposal(pid, tenant_id)
        if proposal is None or str(proposal["engagement_id"]) != str(engagement["id"]):
            raise AppError("NOT_FOUND", "Mapping proposal not found.")
        store.audit(
            "mapping_decision.refused",
            tenant_id,
            user.user_id,
            f"mapping-proposal:{pid}",
            correlation_of(request),
        )
        conn.commit()
        raise AppError(
            "MAPPING_APPROVAL_NOT_ENABLED",
            "Mapping approval is not enabled: no trusted source-header attestation exists yet.",
        )
    except Exception:
        if conn.in_transaction():
            conn.rollback()
        raise
    finally:
        conn.close()
