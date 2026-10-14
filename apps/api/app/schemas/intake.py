"""Client-intake quarantine schemas. Metadata only: no bytes, no storage keys."""

from datetime import datetime

from pydantic import BaseModel


class QuarantineState(BaseModel):
    status: str  # QUARANTINED (never READY/CLEAN here: unscanned, unusable)
    downloadable: bool = False
    extractable: bool = False
    note: str = (
        "Unscanned file in private quarantine: not parsed, not downloaded, "
        "not promoted. Release requires an approved scan gate (EP-04C)."
    )


class IntakeOut(BaseModel):
    id: str
    client_id: str
    version: int
    parent_id: str | None = None
    duplicate_of: str | None = None
    filename: str
    declared_type: str
    content_type: str | None = None
    byte_count: int
    sha256: str
    quarantine: QuarantineState
    reason: str | None = None
    uploaded_by: str | None = None
    created_at: datetime
