"""Engagement foundation + reconciliation-run boundary (REC-SLICE-03).

Authenticated tenant/client-scoped engagements (SRS EP-03 FR-WRK-004/005)
with attributed history, and a default-deny reconciliation execution boundary:
run requests evaluate dataset eligibility from server-side reads and are
recorded as BLOCKED with stable machine-readable reasons until approved
source conditions exist. No worker wiring, no dataset persistence, no
financial contents in requests, responses, or logs.

Durable-job enqueue is deliberately unwired here: DurableJobs.claim() is not
operation-scoped, so a queued `rec.reconcile` job could be picked up by an
unrelated worker. Wiring execution requires operation-scoped claiming under
separate review (fencing/lease machinery untouched in this slice).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..errors import AppError
from ..recon.eligibility import (
    ENGAGEMENT_NOT_ACTIVE,
    EligibilitySnapshot,
    evaluate,
)
from ..recon.execution import (
    DEFAULT_RULES_VERSION,
    OPERATION,
    RunDescriptor,
    payload_hash,
    source_set_fingerprint,
)
from ..recon.findings import PROJECTION_VERSION
from ..schemas.engagement import (
    EngagementEventOut,
    EngagementIn,
    EngagementOut,
    EngagementPatch,
    ReconRunIn,
    ReconRunOut,
)
from ..sprint1_auth import (
    WRITE,
    CurrentUser,
    correlation_of,
    open_store,
    require_roles,
    require_tenant,
    tenant_of,
)
from .demo_recon import router as demo_recon_router

router = APIRouter(tags=["engagements"])
# REC-UI-01: the restricted synthetic-demo boundary rides on this router (main.py
# is owned by an open PR and left untouched). See routers/demo_recon.py.
router.include_router(demo_recon_router)

_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"ACTIVE", "ARCHIVED"},
    "ACTIVE": {"CLOSED", "ARCHIVED"},
    "CLOSED": {"ARCHIVED"},
    "ARCHIVED": set(),
}

_BLOCKED_DETAILS = {
    "UNCONFIRMED_JURISDICTION": "Engagement has no confirmed tax context for this client.",
    "MISSING_DATASET_VERSION": "Dataset versions are not backed by a persisted version registry.",
    "UNAPPROVED_MAPPING": "No approved field mapping is recorded for these dataset versions.",
    "SOURCE_NOT_RELEASED": "Source documents have not completed quarantine release gates.",
    "UNSUPPORTED_JOFO_PROFILE": "No approved supported JoFotara profile is recorded.",
}


def _uuid_or_404(value: str | None, message: str) -> str:
    try:
        assert value is not None
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError, AssertionError):
        raise AppError("NOT_FOUND", message) from None


def _engagement_out(row: dict) -> EngagementOut:
    return EngagementOut(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        review_type=row["review_type"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        status=row["status"],
        assignee_user_id=str(row["assignee_user_id"]) if row.get("assignee_user_id") else None,
        tax_context_id=str(row["tax_context_id"]) if row.get("tax_context_id") else None,
        revision=row["revision"],
        created_at=row["created_at"],
    )


def _run_out(row: dict) -> ReconRunOut:
    return ReconRunOut(
        id=str(row["id"]),
        engagement_id=str(row["engagement_id"]),
        operation=row["operation"],
        idempotency_key=row["idempotency_key"],
        payload_hash=row["payload_hash"],
        sales_dataset_version_id=row["sales_dataset_version_id"],
        jofo_dataset_version_id=row["jofo_dataset_version_id"],
        source_set_fingerprint=row["source_set_fingerprint"],
        rules_version=row["rules_version"],
        projection_version=row["projection_version"],
        period_start=row.get("period_start"),
        period_end=row.get("period_end"),
        jurisdiction_code=row.get("jurisdiction_code"),
        status=row["status"],
        blocked_reason=row["blocked_reason"],
        blocked_detail=row.get("blocked_detail"),
        created_at=row["created_at"],
    )


def _blocked_response(row: dict) -> JSONResponse:
    """Refused execution answers 409 with the recorded run (stable replay)."""
    return JSONResponse(status_code=409, content=_run_out(row).model_dump(mode="json"))


def _verified_assignee(store, tenant_id: str, assignee: str | None) -> str | None:
    """Assignee must be an active member of the same tenant.

    Assignment records a reference only: it never changes membership, role,
    or privileges (SRS FR-WRK-007 gating without privilege expansion).
    """
    if assignee is None:
        return None
    user_id = _uuid_or_404(assignee, "Assignee must be an active member of the tenant.")
    membership = store.get_membership(tenant_id, user_id)
    if membership is None or membership.get("status") != "active":
        raise AppError("VALIDATION_ERROR", "Assignee must be an active member of the tenant.")
    return user_id


def _verified_context(store, tenant_id: str, client_id: str, context: str | None) -> str | None:
    """Tax-context reference must exist and belong to the same tenant+client.

    Confirmation semantics are owned by the jurisdiction slice; this slice
    only verifies the reference (never confirms, never rewrites).
    """
    if context is None:
        return None
    context_id = _uuid_or_404(context, "Tax context not found.")
    row = store.get_tax_context(context_id, tenant_id)
    if row is None:
        raise AppError("VALIDATION_ERROR", "Tax context not found.")
    if str(row["client_id"]) != client_id:
        raise AppError("VALIDATION_ERROR", "Tax context belongs to a different client.")
    return context_id


@router.post("/engagements", response_model=EngagementOut, status_code=201)
def create_engagement(
    body: EngagementIn, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> EngagementOut:
    tenant_id = tenant_of(user)
    client_id = _uuid_or_404(body.client_id, "Client not found.")
    review_type = body.review_type.strip()
    if not review_type:
        raise AppError("VALIDATION_ERROR", "review_type must be non-blank.")
    if body.period_start > body.period_end:
        raise AppError("VALIDATION_ERROR", "period_start must not be after period_end.")
    store, conn, _ = open_store(request)
    try:
        client = store.get_client(client_id, tenant_id)
        if client is None:
            raise AppError("NOT_FOUND", "Client not found.")
        assignee = _verified_assignee(store, tenant_id, body.assignee_user_id)
        context_id = _verified_context(store, tenant_id, client_id, body.tax_context_id)
        duplicate = store.find_engagement_duplicate(
            tenant_id, client_id, body.period_start, body.period_end, review_type
        )
        if duplicate is not None:
            raise AppError(
                "STATE_CONFLICT",
                "Duplicate engagement for this client, period, and review type.",
                {"existing_engagement_id": str(duplicate["id"])},
            )
        row = store.create_engagement(
            tenant_id,
            client_id,
            review_type,
            body.period_start,
            body.period_end,
            assignee,
            context_id,
            user.user_id,
        )
        store.add_engagement_event(tenant_id, str(row["id"]), user.user_id, "created", None, "DRAFT")
        store.audit(
            "engagement.created",
            tenant_id,
            user.user_id,
            f"engagement:{row['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _engagement_out(row)


@router.get("/engagements", response_model=list[EngagementOut])
def list_engagements(
    request: Request,
    client_id: str | None = None,
    status: str | None = None,
    user: CurrentUser = Depends(require_tenant),
) -> list[EngagementOut]:
    tenant_id = tenant_of(user)
    if client_id is not None:
        client_id = _uuid_or_404(client_id, "Client not found.")
    if status is not None and status not in _TRANSITIONS:
        raise AppError("VALIDATION_ERROR", "status must be DRAFT, ACTIVE, CLOSED, or ARCHIVED.")
    store, conn, _ = open_store(request)
    try:
        return [_engagement_out(e) for e in store.list_engagements(tenant_id, client_id, status)]
    finally:
        conn.close()


@router.get("/engagements/{engagement_id}", response_model=EngagementOut)
def get_engagement(
    engagement_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> EngagementOut:
    store, conn, _ = open_store(request)
    try:
        row = store.get_engagement(_uuid_or_404(engagement_id, "Engagement not found."), tenant_of(user))
        if row is None:
            raise AppError("NOT_FOUND", "Engagement not found.")
        return _engagement_out(row)
    finally:
        conn.close()


@router.get("/engagements/{engagement_id}/history", response_model=list[EngagementEventOut])
def engagement_history(
    engagement_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> list[EngagementEventOut]:
    store, conn, _ = open_store(request)
    try:
        eid = _uuid_or_404(engagement_id, "Engagement not found.")
        if store.get_engagement(eid, tenant_of(user)) is None:
            raise AppError("NOT_FOUND", "Engagement not found.")
        return [
            EngagementEventOut(
                id=str(e["id"]),
                action=e["action"],
                actor_id=str(e["actor_id"]) if e.get("actor_id") else None,
                prior_status=e.get("prior_status"),
                new_status=e.get("new_status"),
                created_at=e["created_at"],
            )
            for e in store.list_engagement_events(eid, tenant_of(user))
        ]
    finally:
        conn.close()


@router.patch("/engagements/{engagement_id}", response_model=EngagementOut)
def patch_engagement(
    engagement_id: str,
    body: EngagementPatch,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> EngagementOut:
    store, conn, _ = open_store(request)
    try:
        eid = _uuid_or_404(engagement_id, "Engagement not found.")
        row = store.get_engagement(eid, tenant_of(user))
        if row is None:
            raise AppError("NOT_FOUND", "Engagement not found.")
        current = row["status"]
        if current == "ARCHIVED":
            raise AppError("STATE_CONFLICT", "Archived engagements are immutable.")
        fields: dict[str, object] = {}
        if body.status is not None and body.status != current:
            if body.status not in _TRANSITIONS[current]:
                raise AppError(
                    "STATE_CONFLICT",
                    f"Transition {current} -> {body.status} is not allowed.",
                    {"current_status": current, "allowed": sorted(_TRANSITIONS[current])},
                )
            fields["status"] = body.status
        assignee_present = "assignee_user_id" in body.model_fields_set
        if assignee_present:
            fields["assignee_user_id"] = _verified_assignee(store, tenant_of(user), body.assignee_user_id)
        if not fields:
            return _engagement_out(row)
        updated = store.update_engagement(eid, tenant_of(user), current, row["revision"], **fields)
        if updated is None:
            # Lost a concurrent race: another writer moved status/revision
            # first. Fail closed with a stable 409; no events written.
            fresh = store.get_engagement(eid, tenant_of(user))
            if fresh is None:  # pragma: no cover - engagements are never deleted
                raise AppError("NOT_FOUND", "Engagement not found.")
            raise AppError(
                "STATE_CONFLICT",
                "Engagement changed concurrently; reload and retry.",
                {
                    "reason": "CONCURRENT_MODIFICATION",
                    "current_status": fresh["status"],
                    "current_revision": fresh["revision"],
                },
            )
        if "status" in fields:
            store.add_engagement_event(
                tenant_of(user), eid, user.user_id, "status_changed", current, body.status
            )
            store.audit(
                "engagement.status_changed",
                tenant_of(user),
                user.user_id,
                f"engagement:{eid}",
                correlation_of(request),
            )
        if assignee_present:
            store.add_engagement_event(tenant_of(user), eid, user.user_id, "assignee_changed", None, None)
            store.audit(
                "engagement.assignee_changed",
                tenant_of(user),
                user.user_id,
                f"engagement:{eid}",
                correlation_of(request),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _engagement_out(updated)


@router.post("/engagements/{engagement_id}/recon-runs")
def request_recon_run(
    engagement_id: str,
    body: ReconRunIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> JSONResponse:
    """Evaluate eligibility and record the request as BLOCKED (default-deny).

    Real execution stays refused: no dataset-version registry, mapping
    approvals, release gates, or approved JoFotara profiles exist in persisted
    trusted form yet, so the eligible branch is unreachable and enqueue stays
    unwired (see module docstring). Retries with an identical identity replay
    stably; the same key with different inputs conflicts.
    """
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        eid = _uuid_or_404(engagement_id, "Engagement not found.")
        engagement = store.get_engagement(eid, tenant_id)
        if engagement is None:
            raise AppError("NOT_FOUND", "Engagement not found.")
        if engagement["status"] != "ACTIVE":
            raise AppError(
                "STATE_CONFLICT",
                "Engagement must be ACTIVE to request reconciliation.",
                {"reason": ENGAGEMENT_NOT_ACTIVE, "status": engagement["status"]},
            )
        jurisdiction_code: str | None = None
        jurisdiction_confirmed = False
        if engagement.get("tax_context_id"):
            context = store.get_tax_context(str(engagement["tax_context_id"]), tenant_id)
            if (
                context is not None
                and str(context["client_id"]) == str(engagement["client_id"])
                and context.get("confirmation_status") == "CONFIRMED"
            ):
                jurisdiction_confirmed = True
                jurisdiction_code = context["jurisdiction_code"]
        decision = evaluate(
            EligibilitySnapshot(
                engagement_active=True,
                jurisdiction_confirmed=jurisdiction_confirmed,
                # No persisted trusted sources yet for versions, mappings,
                # release gates, or JoFotara profiles: gates stay closed.
                sales_version_present=False,
                jofo_version_present=False,
                mapping_approved=False,
                source_released=False,
                jofo_profile_supported=False,
            )
        )
        if decision.eligible:  # pragma: no cover - unreachable until dataset persistence lands
            raise AppError(
                "APPROVAL_BLOCKED",
                "Reconciliation execution is not wired in this slice.",
                {"reason": "EXECUTION_NOT_WIRED"},
            )
        descriptor = RunDescriptor(
            tenant_id=tenant_id,
            client_id=str(engagement["client_id"]),
            engagement_id=eid,
            operation=OPERATION,
            idempotency_key=body.idempotency_key,
            sales_dataset_version_id=body.sales_dataset_version_id.strip(),
            jofo_dataset_version_id=body.jofo_dataset_version_id.strip(),
            rules_version=DEFAULT_RULES_VERSION,
            projection_version=PROJECTION_VERSION,
            period_start=engagement["period_start"],
            period_end=engagement["period_end"],
            jurisdiction_code=jurisdiction_code,
        )
        payload = payload_hash(descriptor)
        store.lock_run_key(tenant_id, eid, OPERATION, body.idempotency_key)
        existing = store.get_runs_by_key(tenant_id, eid, OPERATION, body.idempotency_key)
        match = next((r for r in existing if r["payload_hash"] == payload), None)
        if match is not None:
            store.audit(
                "recon_run.replayed",
                tenant_id,
                user.user_id,
                f"recon-run:{match['id']}",
                correlation_of(request),
            )
            conn.commit()
            return _blocked_response(match)
        if existing:
            conn.rollback()
            raise AppError(
                "STATE_CONFLICT",
                "Idempotency key already used for different run inputs.",
                {"existing_run_id": str(existing[-1]["id"])},
            )
        row = store.create_run(
            tenant_id,
            str(engagement["client_id"]),
            eid,
            OPERATION,
            body.idempotency_key,
            payload,
            descriptor.sales_dataset_version_id,
            descriptor.jofo_dataset_version_id,
            source_set_fingerprint(
                descriptor.sales_dataset_version_id,
                descriptor.jofo_dataset_version_id,
                descriptor.rules_version,
                descriptor.projection_version,
            ),
            descriptor.rules_version,
            descriptor.projection_version,
            descriptor.period_start,
            descriptor.period_end,
            descriptor.jurisdiction_code,
            decision.reason,
            _BLOCKED_DETAILS.get(decision.reason, "Execution preconditions are not satisfied."),
            user.user_id,
        )
        store.audit(
            "recon_run.blocked",
            tenant_id,
            user.user_id,
            f"recon-run:{row['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _blocked_response(row)


@router.get("/engagements/{engagement_id}/recon-runs", response_model=list[ReconRunOut])
def list_recon_runs(
    engagement_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> list[ReconRunOut]:
    store, conn, _ = open_store(request)
    try:
        eid = _uuid_or_404(engagement_id, "Engagement not found.")
        if store.get_engagement(eid, tenant_of(user)) is None:
            raise AppError("NOT_FOUND", "Engagement not found.")
        return [_run_out(r) for r in store.list_runs(eid, tenant_of(user))]
    finally:
        conn.close()
