"""Mapping-approval schemas (REC-DATA-02).

Metadata + explicit maps + review decisions only: never trusted source headers,
server-derived fingerprints, bytes, or financial contents. Proposals carry the
human-authored explicit field map; the header fingerprint and all approval
state are server-derived and can never be supplied by a caller (``extra`` is
forbidden so a forged ``header_fingerprint``/``confirmed``/role label is a hard
422, not silently ignored).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MappingProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: str
    doc_type: str
    field_map: dict[str, str] = Field(default_factory=dict)
    mapping_version: str
    normalization_version: str
    canonical_schema_version: str


class MappingDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    reason: str | None = None
    idempotency_key: str


class MappingProposalOut(BaseModel):
    id: str
    engagement_id: str
    client_id: str
    dataset_version_id: str
    doc_type: str
    header_fingerprint: str
    field_map: dict[str, str]
    mapping_version: str
    normalization_version: str
    canonical_schema_version: str
    proposed_by: str | None = None
    proposed_at: datetime


class MappingDecisionOut(BaseModel):
    id: str
    proposal_id: str
    dataset_version_id: str
    decision: str
    reviewer_id: str | None = None
    reason: str | None = None
    decided_at: datetime


class MappingApprovalOut(BaseModel):
    dataset_version_id: str
    approved: bool
    reason: str
    issues: list[str] = Field(default_factory=list)
