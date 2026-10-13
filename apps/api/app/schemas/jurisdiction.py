"""Request/response schemas: LegalEntity, TaxContext, registrations (masked), catalog.

Conventions follow schemas/sprint1.py. Sensitive identifier PLAINTEXT is never a
stored field: `legal_identifier` exists on write schemas ONLY as a fail-closed
tripwire (any provided value → 403 FEATURE_DISABLED, never persisted/logged).
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EntityStatus = Literal["SUGGESTED", "DRAFT", "VERIFIED_ACTIVE", "ENDED"]
ContextStatus = Literal["DRAFT", "NEEDS_CONFIRMATION", "CONFIRMED"]
ConfirmationStatusFilter = Literal["DRAFT", "NEEDS_CONFIRMATION", "CONFIRMED", "all"]


class LegalEntityIn(BaseModel):
    client_id: str
    legal_name: str = Field(min_length=1, max_length=300)
    incorporation_country_code: str = Field(min_length=2, max_length=3)
    base_currency: str = Field(min_length=3, max_length=3)
    entity_type: str = Field(default="COMPANY", max_length=60)
    fiscal_start: str = Field(default="01-01", max_length=5)
    parent_legal_entity_id: str | None = None
    # Fail-closed tripwire: plaintext identifiers are not collected in PR-B.
    legal_identifier: str | None = None


class LegalEntityPatch(BaseModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=300)
    incorporation_country_code: str | None = Field(default=None, min_length=2, max_length=3)
    base_currency: str | None = Field(default=None, min_length=3, max_length=3)
    entity_type: str | None = Field(default=None, max_length=60)
    fiscal_start: str | None = Field(default=None, max_length=5)
    parent_legal_entity_id: str | None = None
    clear_parent: bool = False
    status: EntityStatus | None = None
    legal_identifier: str | None = None
    # Identity is path-bound; body-supplied identity rejects loudly (never ignored).
    tenant_id: str | None = None
    client_id: str | None = None


class LegalEntityOut(BaseModel):
    id: str
    client_id: str
    legal_name: str
    incorporation_country_code: str
    entity_type: str
    base_currency: str
    fiscal_start: str
    parent_legal_entity_id: str | None = None
    status: str
    created_at: datetime


class TaxContextIn(BaseModel):
    client_id: str
    subject_entity_id: str
    obligation_profile_id: str | None = None
    jurisdiction_code: str = Field(min_length=2, max_length=3)
    tax_type_code: str = Field(min_length=1, max_length=60)
    period_start: date
    period_end: date
    regime_code: str | None = Field(default=None, max_length=60)
    pack_version: str | None = Field(default=None, max_length=60)


class TaxContextPatch(BaseModel):
    # Only working fields are patchable. Frozen identity/scope bindings are
    # DECLARED so attempts reject loudly with 422 instead of being ignored.
    period_start: date | None = None
    period_end: date | None = None
    client_id: str | None = None
    subject_entity_id: str | None = None
    obligation_profile_id: str | None = None
    jurisdiction_code: str | None = None
    tax_type_code: str | None = None


class TaxContextOut(BaseModel):
    id: str
    client_id: str
    subject_kind: str
    subject_entity_id: str | None = None
    obligation_profile_id: str | None = None
    profile_version: int | None = None
    jurisdiction_code: str
    tax_type_code: str
    regime_code: str | None = None
    period_start: date
    period_end: date
    context_revision: int
    pack_version: str | None = None
    confirmation_status: str
    context_hash: str | None = None
    snapshot: dict[str, Any] | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    accounting_only_disclaimer: str | None = None


class RegistrationIn(BaseModel):
    # Accepted only to reject loudly: identifier collection is disabled in PR-B.
    obligation_profile_id: str | None = None
    authority_code: str | None = None
    registration_kind: str | None = None
    number_ciphertext: str | None = None
    number_nonce: str | None = None
    number_last4: str | None = None
    key_id: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class RegistrationOut(BaseModel):
    # Masked read shape: ciphertext, nonce, and key metadata are NEVER selected.
    id: str
    obligation_profile_id: str
    authority_code: str
    registration_kind: str
    number_last4: str | None = None
    status: str
    starts_on: date | None = None
    ends_on: date | None = None


class JurisdictionOut(BaseModel):
    code: str
    name_en: str
    name_ar: str
    availability: str
    release_pack_version: str | None = None
    capabilities: dict[str, Any]
