"""Dataset-version registry schemas (REC-DATA-01).

Registration metadata only: no bytes, no storage keys, no financial contents.
``source_content_sha256`` (raw upload identity) and ``dataset_fingerprint``
(normalized identity, absent until authorization) stay distinct.
"""

from datetime import datetime

from pydantic import BaseModel


class DatasetVersionIn(BaseModel):
    source_intake_id: str
    doc_type: str
    parser_version: str | None = None
    normalization_version: str | None = None


class DatasetVersionOut(BaseModel):
    id: str
    client_id: str
    source_intake_id: str
    doc_type: str
    declared_format: str
    version: int
    parent_version_id: str | None = None
    source_content_sha256: str
    parser_version: str | None = None
    normalization_version: str | None = None
    mapping_revision: str | None = None
    dataset_fingerprint: str | None = None
    registered_by: str | None = None
    registered_at: datetime
