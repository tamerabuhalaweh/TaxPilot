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
  parent_id UUID,
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
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT document_intakes_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id),
  -- R1 lineage isolation: version parents and content-duplicate references can
  -- never cross tenant/client boundaries. The composite target key exists
  -- solely so these references stay scope-bound (never a global id lookup).
  CONSTRAINT document_intakes_tenant_client_key UNIQUE (tenant_id, client_id, id),
  CONSTRAINT document_intakes_parent_fk
    FOREIGN KEY (tenant_id, client_id, parent_id)
    REFERENCES document_intakes (tenant_id, client_id, id),
  CONSTRAINT document_intakes_duplicate_fk
    FOREIGN KEY (tenant_id, client_id, duplicate_of)
    REFERENCES document_intakes (tenant_id, client_id, id),
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

-- R1 immutability: accepted intake metadata cannot be rewritten, and rows are
-- never deleted (no HTTP delete exists; retention DEC-02 is open; any future
-- controlled erasure requires its own reviewed migration). The ONLY authorized
-- update is exactly QUARANTINED -> REJECTED with a nonblank reason supplied
-- atomically (the future scan gate's verdict); after REJECTED even the reason
-- is frozen. No Q->Q or R->R rewrites, no reverts, no other statuses.
CREATE OR REPLACE FUNCTION document_intakes_immutable_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'document_intakes rows are never deleted (retention policy undecided)';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
    OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
    OR NEW.client_id IS DISTINCT FROM OLD.client_id
    OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
    OR NEW.version IS DISTINCT FROM OLD.version
    OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
    OR NEW.duplicate_of IS DISTINCT FROM OLD.duplicate_of
    OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
    OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
    OR NEW.byte_count IS DISTINCT FROM OLD.byte_count
    OR NEW.filename IS DISTINCT FROM OLD.filename
    OR NEW.declared_type IS DISTINCT FROM OLD.declared_type
    OR NEW.content_type IS DISTINCT FROM OLD.content_type
    OR NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'document_intakes accepted metadata is immutable';
  END IF;
  IF OLD.status = 'QUARANTINED' AND NEW.status = 'REJECTED'
    AND NEW.reason IS NOT NULL AND btrim(NEW.reason) <> '' THEN
    NEW.updated_at := now();
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'only QUARANTINED -> REJECTED with a nonblank reason is authorized (got % -> %)',
    OLD.status, NEW.status;
END $$;

DROP TRIGGER IF EXISTS document_intakes_no_mutation ON document_intakes;
CREATE TRIGGER document_intakes_no_mutation
  BEFORE UPDATE ON document_intakes
  FOR EACH ROW EXECUTE FUNCTION document_intakes_immutable_guard();

DROP TRIGGER IF EXISTS document_intakes_no_delete ON document_intakes;
CREATE TRIGGER document_intakes_no_delete
  BEFORE DELETE ON document_intakes
  FOR EACH ROW EXECUTE FUNCTION document_intakes_immutable_guard();
