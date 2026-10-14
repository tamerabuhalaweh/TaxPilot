-- 0005: client-intake quarantine metadata (EP-04B, PO-authorized).
-- Immutable intake records + version lineage ONLY. This migration MUST NOT create
-- engagements, tax contexts, extraction results, or job state machines: none of
-- those workflows exist yet. No backfill: there are no authoritative facts to
-- migrate. Old migrations are never edited. Files stay QUARANTINED ( unscanned
-- bytes are never parsed, downloaded, or promoted) until a future scan gate.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS document_intakes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  idempotency_key TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  parent_id UUID REFERENCES document_intakes(id),
  duplicate_of UUID,
  storage_key TEXT NOT NULL UNIQUE,
  content_sha256 TEXT NOT NULL,
  byte_count INTEGER NOT NULL,
  filename TEXT NOT NULL,
  declared_type TEXT NOT NULL,
  content_type TEXT,
  status TEXT NOT NULL DEFAULT 'QUARANTINED',
  reason TEXT,
  uploaded_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT document_intakes_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id),
  CONSTRAINT document_intakes_version CHECK (version >= 1),
  CONSTRAINT document_intakes_bytes CHECK (byte_count >= 0),
  CONSTRAINT document_intakes_type CHECK (declared_type IN ('csv', 'xlsx')),
  CONSTRAINT document_intakes_status CHECK (status IN ('QUARANTINED', 'REJECTED'))
);

CREATE UNIQUE INDEX IF NOT EXISTS document_intakes_key_version_uidx
  ON document_intakes (tenant_id, client_id, idempotency_key, version);
CREATE INDEX IF NOT EXISTS document_intakes_client_idx
  ON document_intakes (tenant_id, client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS document_intakes_sha_idx
  ON document_intakes (tenant_id, client_id, content_sha256);
