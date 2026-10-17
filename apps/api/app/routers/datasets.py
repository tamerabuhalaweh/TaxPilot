"""Client-scoped dataset-version registry routes (REC-DATA-01).

Authenticated, tenant/client-scoped registry of immutable dataset versions.
Registration is default-deny: it is NOT approval and NOT release, and until
trusted source-release evidence exists (REC-DATA-03) the POST refuses with a
stable 409 ``SOURCE_NOT_RELEASED`` and persists nothing (no fabricated rows).
Read routes expose registration metadata only: never bytes, storage keys, or
financial contents.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from ..datasets.registry import (
    KNOWN_DOCUMENT_TYPES,
    UNSUPPORTED_DOCUMENT_TYPE,
    UNSUPPORTED_FORMAT,
    evaluate_registration,
)
from ..errors import AppError
from ..schemas.dataset import DatasetVersionIn, DatasetVersionOut
from ..sprint1_auth import (
    WRITE,
    CurrentUser,
    correlation_of,
    open_store,
    require_roles,
    require_tenant,
    tenant_of,
)

router = APIRouter(tags=["datasets"])


def _dataset_out(row: dict) -> DatasetVersionOut:
    return DatasetVersionOut(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        source_intake_id=str(row["source_intake_id"]),
        doc_type=row["doc_type"],
        declared_format=row["declared_format"],
        version=row["version"],
        parent_version_id=str(row["parent_version_id"]) if row.get("parent_version_id") else None,
        source_content_sha256=row["source_content_sha256"],
        parser_version=row.get("parser_version"),
        normalization_version=row.get("normalization_version"),
        mapping_revision=row.get("mapping_revision"),
        dataset_fingerprint=row.get("dataset_fingerprint"),
        registered_by=str(row["registered_by"]) if row.get("registered_by") else None,
        registered_at=row["registered_at"],
    )


def _uuid_or_404(value: str, message: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise AppError("NOT_FOUND", message) from None


@router.post("/clients/{client_id}/dataset-versions", response_model=DatasetVersionOut, status_code=201)
def register_dataset_version(
    client_id: str,
    body: DatasetVersionIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> DatasetVersionOut:
    tenant_id = tenant_of(user)
    cid = _uuid_or_404(client_id, "Client not found.")
    doc_type = body.doc_type.strip()
    if doc_type not in KNOWN_DOCUMENT_TYPES:
        raise AppError("VALIDATION_ERROR", "Unsupported document type.")
    store, conn, _ = open_store(request)
    try:
        client = store.get_client(cid, tenant_id)
        if client is None:
            raise AppError("NOT_FOUND", "Client not found.")
        intake_id = _uuid_or_404(body.source_intake_id, "Source intake not found.")
        intake = store.get_intake(intake_id, tenant_id)
        if intake is None or str(intake["client_id"]) != cid:
            # No oracle: out-of-scope and missing sources are indistinguishable.
            raise AppError("NOT_FOUND", "Source intake not found.")
        decision = evaluate_registration(
            doc_type=doc_type,
            declared_format=str(intake["declared_type"]),
            source_status=intake["status"],
            # No trusted release evidence exists yet (REC-DATA-03): default-deny.
            source_released=False,
        )
        if not decision.allowed:
            store.audit(
                "dataset_version.registration_refused",
                tenant_id,
                user.user_id,
                f"client:{cid}",
                correlation_of(request),
            )
            conn.commit()
            if decision.reason in (UNSUPPORTED_DOCUMENT_TYPE, UNSUPPORTED_FORMAT):
                raise AppError("VALIDATION_ERROR", "Unsupported source format for a dataset version.")
            raise AppError(
                "SOURCE_NOT_RELEASED",
                "Dataset version registration requires trusted source-release evidence.",
                {"doc_type": doc_type, "source_status": intake["status"]},
            )
        # Unreachable while release evidence is absent: registration stays
        # default-deny (no fabricated rows). The write path lands with REC-DATA-03.
        raise AppError("SOURCE_NOT_RELEASED", "Dataset version registration is not enabled.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/clients/{client_id}/dataset-versions", response_model=list[DatasetVersionOut])
def list_dataset_versions(
    client_id: str,
    request: Request,
    doc_type: str | None = None,
    user: CurrentUser = Depends(require_tenant),
) -> list[DatasetVersionOut]:
    store, conn, _ = open_store(request)
    try:
        tenant_id = tenant_of(user)
        cid = _uuid_or_404(client_id, "Client not found.")
        if store.get_client(cid, tenant_id) is None:
            raise AppError("NOT_FOUND", "Client not found.")
        return [_dataset_out(r) for r in store.list_dataset_versions(tenant_id, cid, doc_type)]
    finally:
        conn.close()


@router.get("/dataset-versions/{version_id}", response_model=DatasetVersionOut)
def get_dataset_version(
    version_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> DatasetVersionOut:
    store, conn, _ = open_store(request)
    try:
        row = store.get_dataset_version(
            _uuid_or_404(version_id, "Dataset version not found."), tenant_of(user)
        )
        if row is None:
            raise AppError("NOT_FOUND", "Dataset version not found.")
        return _dataset_out(row)
    finally:
        conn.close()
