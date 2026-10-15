"""Request/response schemas: engagements + reconciliation runs (REC-SLICE-03).

Financial amounts never appear here: run requests reference dataset version
IDs only, and refusal details carry stable codes, never source contents.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

EngagementStatus = Literal["DRAFT", "ACTIVE", "CLOSED", "ARCHIVED"]


class EngagementIn(BaseModel):
    client_id: str
    review_type: str = Field(min_length=1, max_length=64)
    period_start: date
    period_end: date
    assignee_user_id: str | None = None
    tax_context_id: str | None = None


class EngagementOut(BaseModel):
    id: str
    client_id: str
    review_type: str
    period_start: date
    period_end: date
    status: str
    assignee_user_id: str | None = None
    tax_context_id: str | None = None
    revision: int
    created_at: datetime


class EngagementPatch(BaseModel):
    status: EngagementStatus | None = None
    assignee_user_id: str | None = None  # explicit null clears the assignment


class EngagementEventOut(BaseModel):
    id: str
    action: str
    actor_id: str | None = None
    prior_status: str | None = None
    new_status: str | None = None
    created_at: datetime


class ReconRunIn(BaseModel):
    sales_dataset_version_id: str = Field(min_length=1, max_length=128)
    jofo_dataset_version_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ReconRunOut(BaseModel):
    id: str
    engagement_id: str
    operation: str
    idempotency_key: str
    payload_hash: str
    sales_dataset_version_id: str
    jofo_dataset_version_id: str
    source_set_fingerprint: str
    rules_version: str
    projection_version: str
    period_start: date | None = None
    period_end: date | None = None
    jurisdiction_code: str | None = None
    status: str
    blocked_reason: str
    blocked_detail: str | None = None
    created_at: datetime
