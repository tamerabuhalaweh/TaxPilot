"""Request schemas: auth, members, clients. Monetary/decimal work arrives Sprint 3+."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["owner", "admin", "accountant", "reviewer", "viewer"]


class RegisterIn(BaseModel):
    email: str
    password: str
    firm_name: str = Field(min_length=1, max_length=200)


class RegisterOut(BaseModel):
    user_id: str
    tenant_id: str
    email_verified: bool = False
    verification_token: str | None = None  # dev-only; never present in production


class VerifyIn(BaseModel):
    token: str


class LoginIn(BaseModel):
    email: str
    password: str


class MembershipOut(BaseModel):
    tenant_id: str
    tenant_name: str | None = None
    role: str


class LoginOut(BaseModel):
    user_id: str
    email: str
    active_tenant_id: str | None = None
    memberships: list[MembershipOut] = []


class SwitchTenantIn(BaseModel):
    tenant_id: str


class InviteIn(BaseModel):
    email: str
    role: Role


class InviteOut(BaseModel):
    invitation_id: str
    email: str
    role: str
    expires_at: datetime
    token: str | None = None  # dev-only; never present in production


class AcceptInviteIn(BaseModel):
    token: str


class MemberPatch(BaseModel):
    role: Role | None = None
    status: Literal["active", "deactivated"] | None = None


class MemberOut(BaseModel):
    membership_id: str
    user_id: str
    email: str | None = None
    role: str
    status: str


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_ref: str | None = Field(default=None, max_length=200)
    sector: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    external_ref: str | None = Field(default=None, max_length=200)
    sector: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None


class ClientOut(BaseModel):
    id: str
    name: str
    external_ref: str | None = None
    sector: str | None = None
    contact: str | None = None
    status: str


class AuditOut(BaseModel):
    id: str
    action: str
    actor_id: str | None = None
    resource: str | None = None
    request_id: str | None = None
    created_at: datetime
