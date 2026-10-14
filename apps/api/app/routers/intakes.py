"""Client-intake quarantine routes (EP-04B). Authenticated intake only.

Quarantined bytes are stored opaquely and NEVER parsed, downloaded, or
promoted here: responses carry metadata (no storage keys, no file contents),
every state-changing call is tenant-scoped + RBAC + CSRF enforced, and
staging/production refuse intake without an approved store/scan gate.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..deps import settings_singleton
from ..errors import AppError
from ..quarantine import LocalQuarantine, StorageUnavailable, new_storage_key, storage_readiness
from ..schemas.intake import IntakeOut, QuarantineState
from ..sprint1_auth import (
    WRITE,
    CurrentUser,
    correlation_of,
    open_store,
    require_roles,
    require_tenant,
    tenant_of,
)

router = APIRouter(tags=["intakes"])

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CSV_TYPES = {"text/csv"}
_XLSX_TYPES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"
_FILENAME_MAX = 255


def _intake_out(row: dict) -> IntakeOut:
    return IntakeOut(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        version=row["version"],
        parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
        duplicate_of=str(row["duplicate_of"]) if row.get("duplicate_of") else None,
        filename=row["filename"],
        declared_type=row["declared_type"],
        content_type=row.get("content_type"),
        byte_count=row["byte_count"],
        sha256=row["content_sha256"],
        quarantine=QuarantineState(status=row["status"]),
        reason=row.get("reason"),
        uploaded_by=str(row["uploaded_by"]) if row.get("uploaded_by") else None,
        created_at=row["created_at"],
    )


def _replay_response(row: dict) -> JSONResponse:
    """Idempotent replay answers 200 with the existing record (not a second 201)."""
    return JSONResponse(status_code=200, content=_intake_out(row).model_dump(mode="json"))


def _uuid_or_404(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise AppError("NOT_FOUND", "Client not found.") from None


def _params(request: Request) -> tuple[str, str, bool]:
    query = request.query_params
    declared = (query.get("declared_type") or "").strip().lower()
    if declared not in ("csv", "xlsx"):
        raise AppError("VALIDATION_ERROR", "declared_type must be 'csv' or 'xlsx'.")
    filename = query.get("filename") or ""
    if not filename.strip():
        raise AppError("VALIDATION_ERROR", "filename is required.")
    if len(filename) > _FILENAME_MAX or "\x00" in filename:
        raise AppError("VALIDATION_ERROR", "filename is too long or contains NUL.")
    lowered = filename.lower()
    if declared == "csv" and not lowered.endswith(".csv"):
        raise AppError("VALIDATION_ERROR", "filename extension conflicts with declared csv type.")
    if declared == "xlsx" and not lowered.endswith(".xlsx"):
        raise AppError("VALIDATION_ERROR", "filename extension conflicts with declared xlsx type.")
    new_version_raw = (query.get("new_version") or "false").strip().lower()
    if new_version_raw not in ("true", "false"):
        raise AppError("VALIDATION_ERROR", "new_version must be 'true' or 'false'.")
    return declared, filename, new_version_raw == "true"


def _content_type(request: Request, declared: str) -> str:
    raw = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    allowed = _CSV_TYPES if declared == "csv" else _XLSX_TYPES
    if raw not in allowed:
        raise AppError("VALIDATION_ERROR", "content type is not allowlisted for the declared file type.")
    return raw


def _idempotency_key(request: Request) -> str:
    key = (request.headers.get("idempotency-key") or "").strip()
    if not _IDEMPOTENCY_RE.match(key):
        raise AppError("VALIDATION_ERROR", "Idempotency-Key header (1-128 of A-Za-z0-9_-) is required.")
    return key


async def _read_bounded(request: Request, cap: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            raise AppError("PAYLOAD_TOO_LARGE", "Upload exceeds the allowed size.")
    if not body:
        raise AppError("VALIDATION_ERROR", "Upload body is empty.")
    return bytes(body)


def _check_signature(data: bytes, declared: str) -> None:
    if declared == "xlsx":
        if data[:4] != _ZIP_MAGIC:
            raise AppError("VALIDATION_ERROR", "Declared xlsx content lacks the ZIP/OOXML signature.")
    else:
        if data[:4] == _ZIP_MAGIC or data[:8] == _OLE_MAGIC:
            raise AppError("VALIDATION_ERROR", "Declared csv content carries a non-CSV signature.")


@router.post("/clients/{client_id}/document-intakes", response_model=IntakeOut, status_code=201)
async def upload_intake(
    client_id: str, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> IntakeOut | JSONResponse:
    settings = settings_singleton()
    ready, reason = storage_readiness(
        settings.environment, settings.storage_backend, settings.quarantine_root
    )
    if not ready:
        raise AppError("STORAGE_UNAVAILABLE", reason)
    assert settings.quarantine_root is not None
    declared, filename, want_new_version = _params(request)
    content_type = _content_type(request, declared)
    key = _idempotency_key(request)
    tenant_id = tenant_of(user)
    store, conn, _ = open_store(request)
    try:
        client = store.get_client(_uuid_or_404(client_id), tenant_id)
        if client is None:
            raise AppError("NOT_FOUND", "Client not found.")
        try:
            data = await _read_bounded(request, settings.upload_max_bytes)
            _check_signature(data, declared)
        except AppError:
            # Post-scope validation failure: audited rejection, nothing stored.
            store.audit(
                "document_intake.rejected",
                tenant_id,
                user.user_id,
                f"client:{client['id']}",
                correlation_of(request),
            )
            conn.commit()
            raise
        sha = hashlib.sha256(data).hexdigest()
        store.lock_intake_key(tenant_id, str(client["id"]), key)
        existing = store.get_intakes_by_key(tenant_id, str(client["id"]), key, for_update=True)
        match = next((r for r in existing if r["content_sha256"] == sha), None)
        if match is not None:
            store.audit(
                "document_intake.duplicate",
                tenant_id,
                user.user_id,
                f"intake:{match['id']}",
                correlation_of(request),
            )
            conn.commit()
            return _replay_response(match)
        if existing:
            if not want_new_version:
                conn.rollback()
                raise AppError(
                    "STATE_CONFLICT",
                    "Idempotency key already used for different content.",
                    {"intake_id": str(existing[-1]["id"]), "version": existing[-1]["version"]},
                )
            version = max(r["version"] for r in existing) + 1
            parent_id: str | None = str(existing[-1]["id"])
        else:
            version = 1
            parent_id = None
        duplicates = store.find_intakes_by_sha(tenant_id, str(client["id"]), sha)
        duplicate_of = str(duplicates[0]["id"]) if duplicates else None
        storage_key = new_storage_key(tenant_id, sha)
        quarantine = LocalQuarantine(settings.quarantine_root)
        try:
            quarantine.put(storage_key, data)
        except StorageUnavailable as exc:
            conn.rollback()
            raise AppError("STORAGE_UNAVAILABLE", str(exc)) from exc
        except OSError as exc:
            conn.rollback()
            raise AppError("STORAGE_UNAVAILABLE", "Quarantine write failed.") from exc
        try:
            row = store.create_intake(
                tenant_id,
                str(client["id"]),
                key,
                version,
                parent_id,
                duplicate_of,
                storage_key,
                sha,
                len(data),
                filename,
                declared,
                content_type,
                user.user_id,
            )
            store.audit(
                "document_intake.versioned" if parent_id else "document_intake.received",
                tenant_id,
                user.user_id,
                f"intake:{row['id']}",
                correlation_of(request),
            )
            if duplicate_of:
                store.audit(
                    "document_intake.duplicate",
                    tenant_id,
                    user.user_id,
                    f"intake:{row['id']}",
                    correlation_of(request),
                )
            conn.commit()
        except IntegrityError:
            # Lost a concurrent race for this key: drop our orphan blob, then
            # serve the winner (same content) or report the conflict.
            conn.rollback()
            quarantine.delete(storage_key)
            leader = store.get_intakes_by_key(tenant_id, str(client["id"]), key)
            same = next((r for r in leader if r["content_sha256"] == sha), None)
            if same is not None:
                return _replay_response(same)
            raise AppError("STATE_CONFLICT", "Concurrent upload won this idempotency key.") from None
        except Exception:
            conn.rollback()
            quarantine.delete(storage_key)
            raise
        return _intake_out(row)
    finally:
        conn.close()


@router.get("/clients/{client_id}/document-intakes", response_model=list[IntakeOut])
def list_intakes(
    client_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> list[IntakeOut]:
    store, conn, _ = open_store(request)
    try:
        tenant_id = tenant_of(user)
        client = store.get_client(_uuid_or_404(client_id), tenant_id)
        if client is None:
            raise AppError("NOT_FOUND", "Client not found.")
        return [_intake_out(r) for r in store.list_intakes(str(client["id"]), tenant_id)]
    finally:
        conn.close()


@router.get("/document-intakes/{intake_id}", response_model=IntakeOut)
def get_intake(intake_id: str, request: Request, user: CurrentUser = Depends(require_tenant)) -> IntakeOut:
    store, conn, _ = open_store(request)
    try:
        row = store.get_intake(_uuid_or_404(intake_id), tenant_of(user))
        if row is None:
            raise AppError("NOT_FOUND", "Document intake not found.")
        return _intake_out(row)
    finally:
        conn.close()
