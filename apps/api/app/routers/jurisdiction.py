"""LegalEntity + TaxContext + masked-registration + catalog routes (JUR PR-B).

Conventions (from routers/workspace.py):
- Tenant reads/writes are tenant-scoped; cross-tenant object access is 404.
- Mutations require WRITE roles (owner/admin/accountant/reviewer) + CSRF.
- Every mutation commits with its audit event in one transaction, else rolls back.
- DB constraints stay authoritative: IntegrityError maps to 409/422, never 500.

Scope boundaries (Master SRS + JUR-IMPLEMENTATION-PLAN, Jordan-first):
- Context jurisdiction: JO only (AE/SA PLANNED are non-executable; PR-C unlocks).
- Tax type: ACCOUNTING_ONLY only (statutory codes UNDECIDED pending DEC-04/10).
- pack_version / regime_code: PR-B accepts neither (NULL-only; packs/regimes
  arrive with PR-C). No invented obligations, registrations, or contexts.
- Plaintext identifiers are never collected: any identifier input → 403
  FEATURE_DISABLED (audited), never persisted, never logged.
- Confirm is a two-write atomic transaction compatible with the PR-A freeze
  trigger: (1) freeze snapshot+hash while NEEDS_CONFIRMATION, (2) flip to
  CONFIRMED carrying actor/time only. New revisions are new rows.
"""

import re
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError

from ..errors import AppError
from ..schemas.jurisdiction import (
    ConfirmationStatusFilter,
    EntityStatus,
    JurisdictionOut,
    LegalEntityIn,
    LegalEntityOut,
    LegalEntityPatch,
    RegistrationIn,
    RegistrationOut,
    TaxContextIn,
    TaxContextOut,
    TaxContextPatch,
)
from ..snapshot import (
    ACCOUNTING_ONLY_DISCLAIMER,
    build_snapshot,
    snapshot_hash,
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
from ..store import utcnow

router = APIRouter(tags=["jurisdiction"])

CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
FISCAL_START_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
CONFIRMABLE_SCOPE = "ACCOUNTING_ONLY"
CONFIRMABLE_JURISDICTION = "JO"

# Fields a context PATCH may never touch (trigger-frozen identity/scope).
_CONTEXT_FROZEN_HINT = (
    "client_id, subject_entity_id, obligation_profile_id, jurisdiction_code, "
    "tax_type_code are immutable after creation; revise instead"
)


def _entity_out(e: dict) -> LegalEntityOut:
    return LegalEntityOut(
        id=str(e["id"]),
        client_id=str(e["client_id"]),
        legal_name=e["legal_name"],
        incorporation_country_code=e["incorporation_country_code"],
        entity_type=e["entity_type"],
        base_currency=e["base_currency"],
        fiscal_start=e["fiscal_start"],
        parent_legal_entity_id=str(e["parent_legal_entity_id"]) if e.get("parent_legal_entity_id") else None,
        status=e["status"],
        created_at=e["created_at"],
    )


def _context_out(c: dict) -> TaxContextOut:
    return TaxContextOut(
        id=str(c["id"]),
        client_id=str(c["client_id"]),
        subject_kind=c["subject_kind"],
        subject_entity_id=str(c["subject_entity_id"]) if c.get("subject_entity_id") else None,
        obligation_profile_id=str(c["obligation_profile_id"]) if c.get("obligation_profile_id") else None,
        profile_version=c.get("profile_version"),
        jurisdiction_code=c["jurisdiction_code"],
        tax_type_code=c["tax_type_code"],
        regime_code=c.get("regime_code"),
        period_start=c["period_start"],
        period_end=c["period_end"],
        context_revision=c["context_revision"],
        pack_version=c.get("pack_version"),
        confirmation_status=c["confirmation_status"],
        context_hash=c.get("context_hash"),
        snapshot=c.get("snapshot"),
        confirmed_by=str(c["confirmed_by"]) if c.get("confirmed_by") else None,
        confirmed_at=c.get("confirmed_at"),
        created_at=c["created_at"],
        accounting_only_disclaimer=ACCOUNTING_ONLY_DISCLAIMER
        if c["tax_type_code"] == CONFIRMABLE_SCOPE
        else None,
    )


def _registration_out(r: dict) -> RegistrationOut:
    return RegistrationOut(
        id=str(r["id"]),
        obligation_profile_id=str(r["obligation_profile_id"]),
        authority_code=r["authority_code"],
        registration_kind=r["registration_kind"],
        number_last4=r.get("number_last4"),
        status=r["status"],
        starts_on=r.get("starts_on"),
        ends_on=r.get("ends_on"),
    )


def _require_client(store, tenant_id: str, client_id: str) -> dict:  # type: ignore[no-untyped-def]
    client = store.get_client(client_id, tenant_id)
    if client is None:
        raise AppError("NOT_FOUND", "Client not found.")
    return client


def _require_entity(store, tenant_id: str, client_id: str, entity_id: str) -> dict:  # type: ignore[no-untyped-def]
    entity = store.get_legal_entity(entity_id, tenant_id)
    if entity is None or str(entity["client_id"]) != client_id:
        # Same-client binding: an entity of another client is invisible here.
        raise AppError("NOT_FOUND", "Legal entity not found for this client.")
    return entity


def _require_catalog(store, code: str) -> dict:  # type: ignore[no-untyped-def]
    for row in store.list_jurisdictions():
        if row["code"] == code.upper():
            return row
    raise AppError("VALIDATION_ERROR", f"Unknown jurisdiction code: {code}.")


def _validate_obligation(store, tenant_id: str, client_id: str, ctx: dict, obligation_id: str) -> dict:  # type: ignore[no-untyped-def]
    """PR-B same-client/entity/jurisdiction/period match for an optional obligation."""
    obligation = store.get_obligation(obligation_id, tenant_id)
    if obligation is None or str(obligation["client_id"]) != client_id:
        raise AppError("NOT_FOUND", "Obligation profile not found for this client.")
    if str(obligation["legal_entity_id"]) != str(ctx["subject_entity_id"]):
        raise AppError("VALIDATION_ERROR", "Obligation belongs to a different legal entity.")
    if str(obligation["jurisdiction_code"]).upper() != str(ctx["jurisdiction_code"]).upper():
        raise AppError("VALIDATION_ERROR", "Obligation jurisdiction does not match the context.")
    valid_from = obligation["valid_from"]
    valid_to = obligation.get("valid_to")
    if valid_from > ctx["period_start"] or (valid_to is not None and ctx["period_end"] > valid_to):
        raise AppError("VALIDATION_ERROR", "Context period falls outside the obligation validity window.")
    # registration_status is deliberately NOT gated: UNKNOWN tolerates confirm
    # and never means NOT_REGISTERED (plan §5).
    return obligation


def _validate_ready(store, tenant_id: str, ctx: dict) -> dict | None:  # type: ignore[no-untyped-def]
    """Revalidate a context against LIVE rows before request/confirm.

    Returns the bound obligation (or None). Raises 404/422 with stable codes.
    """
    _require_client(store, tenant_id, str(ctx["client_id"]))
    entity = _require_entity(store, tenant_id, str(ctx["client_id"]), str(ctx["subject_entity_id"]))
    if entity["status"] == "ENDED":
        raise AppError("VALIDATION_ERROR", "Subject legal entity is ENDED.")
    if str(ctx["jurisdiction_code"]).upper() != CONFIRMABLE_JURISDICTION:
        raise AppError("JURISDICTION_NOT_SUPPORTED", "Only JO contexts confirm in PR-B.")
    if str(ctx["tax_type_code"]).upper() != CONFIRMABLE_SCOPE:
        raise AppError("VALIDATION_ERROR", "Only ACCOUNTING_ONLY contexts confirm in PR-B.")
    if ctx["period_start"] > ctx["period_end"]:
        raise AppError("VALIDATION_ERROR", "period_start must not be after period_end.")
    obligation = None
    if ctx.get("obligation_profile_id"):
        obligation = _validate_obligation(
            store, tenant_id, str(ctx["client_id"]), ctx, str(ctx["obligation_profile_id"])
        )
    return obligation


def _map_integrity(exc: IntegrityError) -> AppError:
    diag = getattr(exc.orig, "diag", None)
    constraint = str(getattr(diag, "constraint_name", "") or "") if diag is not None else ""
    sqlstate = str(getattr(exc.orig, "sqlstate", "") or "")
    message = str(exc.orig)
    if sqlstate == "23505" or "already exists" in message or "duplicate" in message.lower():
        return AppError("STATE_CONFLICT", f"Conflicting value ({constraint or 'unique constraint'}).")
    if (
        sqlstate in ("23503", "23514")
        or "foreign key" in message.lower()
        or "check constraint" in message.lower()
    ):
        return AppError("VALIDATION_ERROR", "Referenced record does not exist or value violates a rule.")
    return AppError("VALIDATION_ERROR", "Invalid reference or value.")


# -- catalog ---------------------------------------------------------------
@router.get("/jurisdictions", response_model=list[JurisdictionOut])
def list_jurisdictions(
    request: Request, user: CurrentUser = Depends(require_tenant)
) -> list[JurisdictionOut]:
    """Read-only availability contract (PR-B §6): metadata only, zero executables."""
    store, conn, _ = open_store(request)
    try:
        return [
            JurisdictionOut(
                code=r["code"],
                name_en=r["name_en"],
                name_ar=r["name_ar"],
                availability=r["availability"],
                release_pack_version=r.get("release_pack_version"),
                capabilities=r["capabilities"],
            )
            for r in store.list_jurisdictions()
        ]
    finally:
        conn.close()


# -- legal entities ----------------------------------------------------------
@router.post("/legal-entities", response_model=LegalEntityOut, status_code=201)
def create_legal_entity(
    body: LegalEntityIn, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> LegalEntityOut:
    store, conn, _ = open_store(request)
    try:
        if body.legal_identifier is not None:
            # Fail closed WITHOUT echoing the value (never logged, never stored).
            store.audit(
                "legalentity.identifier_rejected",
                tenant_of(user),
                user.user_id,
                f"client:{body.client_id}",
                correlation_of(request),
            )
            conn.commit()
            raise AppError(
                "FEATURE_DISABLED",
                "Legal-identifier collection is disabled until encrypted key "
                "management lands; plaintext identifiers are never accepted.",
            )
        name = body.legal_name.strip()
        if not name:
            raise AppError("VALIDATION_ERROR", "legal_name is required.")
        country = body.incorporation_country_code.strip().upper()
        currency = body.base_currency.strip().upper()
        if not CURRENCY_RE.match(currency):
            raise AppError("VALIDATION_ERROR", "base_currency must be a 3-letter ISO code (e.g. JOD).")
        if not FISCAL_START_RE.match(body.fiscal_start.strip()):
            raise AppError("VALIDATION_ERROR", "fiscal_start must be MM-DD.")
        entity_type = (body.entity_type or "COMPANY").strip().upper() or "COMPANY"
        _require_client(store, tenant_of(user), body.client_id)
        _require_catalog(store, country)
        parent_id = None
        if body.parent_legal_entity_id:
            parent = store.get_legal_entity(body.parent_legal_entity_id, tenant_of(user))
            if parent is None:
                raise AppError("NOT_FOUND", "Parent legal entity not found.")
            parent_id = str(parent["id"])
        try:
            entity = store.create_legal_entity(
                tenant_of(user),
                body.client_id,
                name,
                country,
                currency,
                entity_type=entity_type,
                fiscal_start=body.fiscal_start.strip(),
                parent_legal_entity_id=parent_id,
            )
        except IntegrityError as exc:
            raise _map_integrity(exc) from exc
        store.audit(
            "legalentity.created",
            tenant_of(user),
            user.user_id,
            f"legal-entity:{entity['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return _entity_out(entity)


@router.get("/legal-entities", response_model=list[LegalEntityOut])
def list_legal_entities(
    request: Request,
    client_id: str | None = None,
    status: EntityStatus | None = None,
    user: CurrentUser = Depends(require_tenant),
) -> list[LegalEntityOut]:
    store, conn, _ = open_store(request)
    try:
        if client_id is not None:
            _require_client(store, tenant_of(user), client_id)
        return [_entity_out(e) for e in store.list_legal_entities(tenant_of(user), client_id, status)]
    finally:
        conn.close()


@router.get("/legal-entities/{entity_id}", response_model=LegalEntityOut)
def get_legal_entity(
    entity_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> LegalEntityOut:
    store, conn, _ = open_store(request)
    try:
        entity = store.get_legal_entity(entity_id, tenant_of(user))
        if entity is None:
            raise AppError("NOT_FOUND", "Legal entity not found.")
        return _entity_out(entity)
    finally:
        conn.close()


@router.patch("/legal-entities/{entity_id}", response_model=LegalEntityOut)
def patch_legal_entity(
    entity_id: str,
    body: LegalEntityPatch,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> LegalEntityOut:
    store, conn, _ = open_store(request)
    try:
        if body.legal_identifier is not None:
            store.audit(
                "legalentity.identifier_rejected",
                tenant_of(user),
                user.user_id,
                f"legal-entity:{entity_id}",
                correlation_of(request),
            )
            conn.commit()
            raise AppError(
                "FEATURE_DISABLED",
                "Legal-identifier collection is disabled until encrypted key "
                "management lands; plaintext identifiers are never accepted.",
            )
        if body.tenant_id is not None or body.client_id is not None:
            raise AppError("VALIDATION_ERROR", "tenant_id/client_id are immutable; revise via a new entity.")
        existing = store.get_legal_entity(entity_id, tenant_of(user))
        if existing is None:
            raise AppError("NOT_FOUND", "Legal entity not found.")
        fields: dict = {}
        if body.legal_name is not None:
            name = body.legal_name.strip()
            if not name:
                raise AppError("VALIDATION_ERROR", "legal_name is required.")
            fields["legal_name"] = name
        if body.incorporation_country_code is not None:
            country = body.incorporation_country_code.strip().upper()
            _require_catalog(store, country)
            fields["incorporation_country_code"] = country
        if body.base_currency is not None:
            currency = body.base_currency.strip().upper()
            if not CURRENCY_RE.match(currency):
                raise AppError("VALIDATION_ERROR", "base_currency must be a 3-letter ISO code.")
            fields["base_currency"] = currency
        if body.entity_type is not None:
            entity_type = body.entity_type.strip().upper()
            if not entity_type:
                raise AppError("VALIDATION_ERROR", "entity_type is required.")
            fields["entity_type"] = entity_type
        if body.fiscal_start is not None:
            if not FISCAL_START_RE.match(body.fiscal_start.strip()):
                raise AppError("VALIDATION_ERROR", "fiscal_start must be MM-DD.")
            fields["fiscal_start"] = body.fiscal_start.strip()
        if body.clear_parent:
            fields["parent_legal_entity_id"] = None
        elif body.parent_legal_entity_id is not None:
            parent = store.get_legal_entity(body.parent_legal_entity_id, tenant_of(user))
            if parent is None:
                raise AppError("NOT_FOUND", "Parent legal entity not found.")
            if str(parent["id"]) == entity_id:
                raise AppError("VALIDATION_ERROR", "An entity cannot parent itself.")
            fields["parent_legal_entity_id"] = str(parent["id"])
        if body.status is not None:
            if existing["status"] == "ENDED" and body.status != "ENDED":
                raise AppError("VALIDATION_ERROR", "ENDED is terminal; revise via a new entity.")
            fields["status"] = body.status
        if not fields:
            return _entity_out(existing)
        try:
            updated = store.update_legal_entity(entity_id, tenant_of(user), **fields)
        except IntegrityError as exc:
            raise _map_integrity(exc) from exc
        assert updated is not None
        store.audit(
            "legalentity.updated",
            tenant_of(user),
            user.user_id,
            f"legal-entity:{entity_id}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _entity_out(updated)


# -- tax contexts ------------------------------------------------------------
def _validate_context_scope(body_jurisdiction: str, body_tax_type: str) -> tuple[str, str]:
    jurisdiction = body_jurisdiction.strip().upper()
    tax_type = body_tax_type.strip().upper()
    if jurisdiction != CONFIRMABLE_JURISDICTION:
        raise AppError(
            "JURISDICTION_NOT_SUPPORTED",
            f"Only {CONFIRMABLE_JURISDICTION} contexts are supported in PR-B.",
        )
    if tax_type != CONFIRMABLE_SCOPE:
        raise AppError(
            "VALIDATION_ERROR",
            f"Only {CONFIRMABLE_SCOPE} tax_type_code is supported in PR-B.",
        )
    return jurisdiction, tax_type


def _validate_period(start: date, end: date) -> None:
    if start > end:
        raise AppError("VALIDATION_ERROR", "period_start must not be after period_end.")


@router.post("/tax-contexts", response_model=TaxContextOut, status_code=201)
def create_tax_context(
    body: TaxContextIn, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> TaxContextOut:
    jurisdiction, tax_type = _validate_context_scope(body.jurisdiction_code, body.tax_type_code)
    _validate_period(body.period_start, body.period_end)
    store, conn, _ = open_store(request)
    try:
        _require_client(store, tenant_of(user), body.client_id)
        _require_entity(store, tenant_of(user), body.client_id, body.subject_entity_id)
        obligation_id = None
        profile_version = None
        if body.obligation_profile_id:
            pseudo = {
                "subject_entity_id": body.subject_entity_id,
                "jurisdiction_code": jurisdiction,
                "period_start": body.period_start,
                "period_end": body.period_end,
            }
            obligation = _validate_obligation(
                store, tenant_of(user), body.client_id, pseudo, body.obligation_profile_id
            )
            obligation_id = str(obligation["id"])
            profile_version = obligation["version"]
        try:
            ctx = store.create_tax_context(
                tenant_of(user),
                body.client_id,
                body.subject_entity_id,
                jurisdiction,
                tax_type,
                body.period_start,
                body.period_end,
                obligation_profile_id=obligation_id,
            )
        except IntegrityError as exc:
            raise _map_integrity(exc) from exc
        if profile_version is not None:
            pinned = store.update_tax_context(
                str(ctx["id"]), tenant_of(user), profile_version=profile_version
            )
            if pinned is None:  # defensive: just inserted, cannot vanish mid-transaction
                raise AppError("STATE_CONFLICT", "Context vanished; retry.")
            ctx = pinned
        store.audit(
            "taxcontext.created",
            tenant_of(user),
            user.user_id,
            f"tax-context:{ctx['id']}",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _context_out(ctx)


@router.get("/tax-contexts", response_model=list[TaxContextOut])
def list_tax_contexts(
    request: Request,
    client_id: str | None = None,
    status: ConfirmationStatusFilter | None = None,
    user: CurrentUser = Depends(require_tenant),
) -> list[TaxContextOut]:
    store, conn, _ = open_store(request)
    try:
        if client_id is not None:
            _require_client(store, tenant_of(user), client_id)
        if status is not None and status not in ("DRAFT", "NEEDS_CONFIRMATION", "CONFIRMED", "all"):
            raise AppError("VALIDATION_ERROR", "Invalid confirmation status filter.")
        return [_context_out(c) for c in store.list_tax_contexts(tenant_of(user), client_id, status)]
    finally:
        conn.close()


@router.get("/tax-contexts/{context_id}", response_model=TaxContextOut)
def get_tax_context(
    context_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> TaxContextOut:
    store, conn, _ = open_store(request)
    try:
        ctx = store.get_tax_context(context_id, tenant_of(user))
        if ctx is None:
            raise AppError("NOT_FOUND", "Tax context not found.")
        return _context_out(ctx)
    finally:
        conn.close()


@router.patch("/tax-contexts/{context_id}", response_model=TaxContextOut)
def patch_tax_context(
    context_id: str,
    body: TaxContextPatch,
    request: Request,
    user: CurrentUser = Depends(require_roles(*WRITE)),
) -> TaxContextOut:
    store, conn, _ = open_store(request)
    try:
        # Row lock: a concurrent confirmation serializes here; re-read decides.
        ctx = store.get_tax_context_for_update(context_id, tenant_of(user))
        if ctx is None:
            raise AppError("NOT_FOUND", "Tax context not found.")
        if ctx["confirmation_status"] == "CONFIRMED":
            raise AppError(
                "STATE_CONFLICT",
                "Confirmed contexts are immutable; create a new revision instead.",
            )
        fields: dict = {}
        if body.period_start is not None:
            fields["period_start"] = body.period_start
        if body.period_end is not None:
            fields["period_end"] = body.period_end
        for frozen, label in (
            (body.client_id, "client_id"),
            (body.subject_entity_id, "subject_entity_id"),
            (body.obligation_profile_id, "obligation_profile_id"),
            (body.jurisdiction_code, "jurisdiction_code"),
            (body.tax_type_code, "tax_type_code"),
        ):
            if frozen is not None:
                raise AppError(
                    "VALIDATION_ERROR", f"{label} is immutable after creation; {_CONTEXT_FROZEN_HINT}."
                )
        if fields:
            start = fields.get("period_start", ctx["period_start"])
            end = fields.get("period_end", ctx["period_end"])
            _validate_period(start, end)
            updated = store.update_tax_context(context_id, tenant_of(user), **fields)
            assert updated is not None
            ctx = updated
            store.audit(
                "taxcontext.updated",
                tenant_of(user),
                user.user_id,
                f"tax-context:{context_id}",
                correlation_of(request),
            )
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return _context_out(ctx)


@router.post("/tax-contexts/{context_id}/request-confirmation", response_model=TaxContextOut)
def request_confirmation(
    context_id: str, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> TaxContextOut:
    store, conn, _ = open_store(request)
    try:
        ctx = store.get_tax_context_for_update(context_id, tenant_of(user))
        if ctx is None:
            raise AppError("NOT_FOUND", "Tax context not found.")
        if ctx["confirmation_status"] == "CONFIRMED":
            raise AppError("STATE_CONFLICT", "Context is already confirmed.")
        if ctx["confirmation_status"] == "NEEDS_CONFIRMATION":
            conn.rollback()
            return _context_out(ctx)  # idempotent replay
        _validate_ready(store, tenant_of(user), ctx)
        updated = store.update_tax_context(
            context_id, tenant_of(user), expect_status="DRAFT", confirmation_status="NEEDS_CONFIRMATION"
        )
        if updated is None:
            # Lost a race with a concurrent transition: re-read decides.
            current = store.get_tax_context(context_id, tenant_of(user))
            assert current is not None
            if current["confirmation_status"] == "NEEDS_CONFIRMATION":
                conn.rollback()
                return _context_out(current)
            raise AppError("STATE_CONFLICT", "Context changed concurrently; re-read and retry.")
        store.audit(
            "taxcontext.confirmation_requested",
            tenant_of(user),
            user.user_id,
            f"tax-context:{context_id}",
            correlation_of(request),
        )
        conn.commit()
        ctx = updated
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return _context_out(ctx)


@router.post("/tax-contexts/{context_id}/confirm", response_model=TaxContextOut)
def confirm_tax_context(
    context_id: str, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> TaxContextOut:
    """Atomic confirmation compatible with the PR-A freeze trigger.

    One transaction holding the row lock: (1) revalidate the LIVE row,
    (2) freeze snapshot+hash while NEEDS_CONFIRMATION (trigger Rule 3 permits
    these columns), (3) flip to CONFIRMED carrying actor/time only (Rule 2),
    (4) audit. Either all of it commits or nothing does.
    """
    store, conn, _ = open_store(request)
    try:
        ctx = store.get_tax_context_for_update(context_id, tenant_of(user))
        if ctx is None:
            raise AppError("NOT_FOUND", "Tax context not found.")
        if ctx["confirmation_status"] == "CONFIRMED":
            # Idempotent replay for the confirming actor; a different actor
            # attempting to "confirm" a frozen row gets a conflict, never a rewrite.
            conn.rollback()
            if str(ctx.get("confirmed_by")) == user.user_id:
                return _context_out(ctx)
            raise AppError("STATE_CONFLICT", "Context is already confirmed by another user.")
        if ctx["confirmation_status"] != "NEEDS_CONFIRMATION":
            raise AppError(
                "STATE_CONFLICT",
                "Only contexts awaiting confirmation can be confirmed; request confirmation first.",
            )
        obligation = _validate_ready(store, tenant_of(user), ctx)
        now = utcnow()
        profile_version = obligation["version"] if obligation else None
        snapshot = build_snapshot(
            tenant_id=tenant_of(user),
            client_id=str(ctx["client_id"]),
            subject_kind=str(ctx["subject_kind"]),
            subject_entity_id=str(ctx["subject_entity_id"]),
            jurisdiction_code=str(ctx["jurisdiction_code"]),
            tax_type_code=str(ctx["tax_type_code"]),
            regime_code=None,
            obligation_profile_id=str(ctx["obligation_profile_id"])
            if ctx.get("obligation_profile_id")
            else None,
            profile_version=profile_version,
            period_start=ctx["period_start"],
            period_end=ctx["period_end"],
            context_revision=int(ctx["context_revision"]),
            pack_version=None,
            confirmation_status="CONFIRMED",
            confirmed_by=user.user_id,
            confirmed_at=now,
            created_at=ctx["created_at"],
        )
        digest = snapshot_hash(snapshot)
        frozen = store.update_tax_context(
            context_id,
            tenant_of(user),
            expect_status="NEEDS_CONFIRMATION",
            snapshot=snapshot,
            context_hash=digest,
            profile_version=profile_version,
        )
        if frozen is None:
            current = store.get_tax_context(context_id, tenant_of(user))
            assert current is not None
            if (
                current["confirmation_status"] == "CONFIRMED"
                and str(current.get("confirmed_by")) == user.user_id
            ):
                conn.rollback()
                return _context_out(current)
            raise AppError("STATE_CONFLICT", "Context changed concurrently; re-read and retry.")
        confirmed = store.update_tax_context(
            context_id,
            tenant_of(user),
            expect_status="NEEDS_CONFIRMATION",
            confirmation_status="CONFIRMED",
            confirmed_by=user.user_id,
            confirmed_at=now,
        )
        if confirmed is None:  # defensive: lock held, cannot lose here barring trigger reject
            raise AppError("STATE_CONFLICT", "Context changed concurrently; re-read and retry.")
        store.audit(
            "taxcontext.confirmed",
            tenant_of(user),
            user.user_id,
            f"tax-context:{context_id}",
            correlation_of(request),
        )
        conn.commit()
        ctx = confirmed
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return _context_out(ctx)


@router.post("/tax-contexts/{context_id}/revise", response_model=TaxContextOut, status_code=201)
def revise_tax_context(
    context_id: str, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> TaxContextOut:
    """Supersession: copy a CONFIRMED row into a new DRAFT revision.

    The old row is never touched (trigger would reject it anyway); the new row
    carries revision+1 and empty confirmation artifacts (hash recomputed at its
    own confirmation, so the tenant-scoped hash unique can never collide).
    """
    store, conn, _ = open_store(request)
    try:
        ctx = store.get_tax_context_for_update(context_id, tenant_of(user))
        if ctx is None:
            raise AppError("NOT_FOUND", "Tax context not found.")
        if ctx["confirmation_status"] != "CONFIRMED":
            raise AppError("STATE_CONFLICT", "Only confirmed contexts are revised; edit drafts in place.")
        new_revision = int(ctx["context_revision"]) + 1
        nxt = store.create_tax_context(
            tenant_of(user),
            str(ctx["client_id"]),
            str(ctx["subject_entity_id"]),
            str(ctx["jurisdiction_code"]),
            str(ctx["tax_type_code"]),
            ctx["period_start"],
            ctx["period_end"],
            obligation_profile_id=str(ctx["obligation_profile_id"])
            if ctx.get("obligation_profile_id")
            else None,
        )
        revised = store.update_tax_context(str(nxt["id"]), tenant_of(user), context_revision=new_revision)
        if revised is None:  # defensive: just inserted, cannot vanish mid-transaction
            raise AppError("STATE_CONFLICT", "Revision target vanished; retry.")
        nxt = revised
        if nxt.get("obligation_profile_id"):
            obligation = store.get_obligation(str(nxt["obligation_profile_id"]), tenant_of(user))
            if obligation is not None:
                repinned = store.update_tax_context(
                    str(nxt["id"]), tenant_of(user), profile_version=obligation["version"]
                )
                if repinned is None:
                    raise AppError("STATE_CONFLICT", "Revision target vanished; retry.")
                nxt = repinned
        store.audit(
            "taxcontext.revised",
            tenant_of(user),
            user.user_id,
            f"tax-context:{nxt['id']}",
            correlation_of(request),
        )
        conn.commit()
        ctx = nxt
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    out = _context_out(ctx)
    return out


# -- registrations: fail-closed writes, masked reads ---------------------------
@router.post("/tax-registrations", status_code=403)
def create_tax_registration(
    body: RegistrationIn | None, request: Request, user: CurrentUser = Depends(require_roles(*WRITE))
) -> dict:
    """PR-B collects NO registration identifiers: every create attempt is
    rejected with 403 FEATURE_DISABLED (audited), nothing is persisted."""
    store, conn, _ = open_store(request)
    try:
        store.audit(
            "registration.create_rejected",
            tenant_of(user),
            user.user_id,
            "tax-registration:new",
            correlation_of(request),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    raise AppError(
        "FEATURE_DISABLED",
        "Registration identifier collection is disabled until encrypted key "
        "management lands; no registration was created.",
    )


@router.get("/tax-registrations", response_model=list[RegistrationOut])
def list_tax_registrations(
    request: Request,
    obligation_profile_id: str | None = None,
    user: CurrentUser = Depends(require_tenant),
) -> list[RegistrationOut]:
    store, conn, _ = open_store(request)
    try:
        if obligation_profile_id is not None:
            obligation = store.get_obligation(obligation_profile_id, tenant_of(user))
            if obligation is None:
                raise AppError("NOT_FOUND", "Obligation profile not found.")
        return [
            _registration_out(r)
            for r in store.list_registrations_masked(tenant_of(user), obligation_profile_id)
        ]
    finally:
        conn.close()


@router.get("/tax-registrations/{registration_id}", response_model=RegistrationOut)
def get_tax_registration(
    registration_id: str, request: Request, user: CurrentUser = Depends(require_tenant)
) -> RegistrationOut:
    store, conn, _ = open_store(request)
    try:
        registration = store.get_registration_masked(registration_id, tenant_of(user))
        if registration is None:
            raise AppError("NOT_FOUND", "Tax registration not found.")
        return _registration_out(registration)
    finally:
        conn.close()
