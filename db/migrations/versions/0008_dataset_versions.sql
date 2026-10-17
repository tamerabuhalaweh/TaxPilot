-- 0008: client-scoped immutable dataset-version registry (REC-DATA-01, PO-approved).
-- A dataset version is a CLIENT artifact: the durable, immutable identity of one
-- source document intake normalized for a declared document type. This migration
-- creates metadata + lineage ONLY: never raw file bytes, storage secrets, or
-- financial contents.
--
-- Registration is NOT approval and NOT release. Those are separately owned future
-- evidence transitions (REC-DATA-02 mapping approval, REC-DATA-03 source release)
-- and MUST NOT become mutable columns on these immutable rows. The registry is not
-- an eligibility certificate: an authenticated POST refuses (SOURCE_NOT_RELEASED)
-- until trusted release evidence exists, so no row is fabricated from the API yet.
--
-- Two hashes stay strictly distinct and are never substituted:
--   source_content_sha256  = trusted hash of the raw upload (from document_intakes)
--   dataset_fingerprint    = normalized content identity computed only later, after
--                            authorized reading + validation + approved mapping; it
--                            is NULL until then, and an absent fingerprint blocks
--                            any derived eligibility.
-- No worker wiring: nothing here enables background financial processing.
-- Old migrations are never edited.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS dataset_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  source_intake_id UUID NOT NULL,
  doc_type TEXT NOT NULL,
  declared_format TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  parent_version_id UUID,
  source_content_sha256 TEXT NOT NULL,
  parser_version TEXT,
  normalization_version TEXT,
  mapping_revision TEXT,
  dataset_fingerprint TEXT,
  registration_fingerprint TEXT NOT NULL,
  registered_by UUID REFERENCES users(id),
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Scope + source lineage: a version binds its client and source intake only
  -- inside its own tenant, never a bare global id.
  CONSTRAINT dataset_versions_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id) ON DELETE RESTRICT,
  CONSTRAINT dataset_versions_source_intake_fk
    FOREIGN KEY (tenant_id, client_id, source_intake_id)
    REFERENCES document_intakes (tenant_id, client_id, id) ON DELETE RESTRICT,
  -- Lineage-grade scope key so parent references never cross tenant/client.
  CONSTRAINT dataset_versions_tenant_client_key UNIQUE (tenant_id, client_id, id),
  CONSTRAINT dataset_versions_parent_fk
    FOREIGN KEY (tenant_id, client_id, parent_version_id)
    REFERENCES dataset_versions (tenant_id, client_id, id) ON DELETE RESTRICT,
  -- One registered version per (source intake, document type): re-registering the
  -- exact same identity converges; a different identity for the same scope is a
  -- hard conflict (fail closed, never overwrite).
  CONSTRAINT dataset_versions_source_uidx UNIQUE (tenant_id, client_id, source_intake_id, doc_type),
  -- Monotonic version lineage per client + document type.
  CONSTRAINT dataset_versions_lineage_uidx UNIQUE (tenant_id, client_id, doc_type, version),
  CONSTRAINT dataset_versions_doc_type CHECK
    (doc_type IN ('sales_register', 'general_ledger', 'jofotara_export')),
  CONSTRAINT dataset_versions_declared_format CHECK (declared_format IN ('csv', 'xlsx')),
  CONSTRAINT dataset_versions_version CHECK (version >= 1),
  CONSTRAINT dataset_versions_source_sha CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
  CONSTRAINT dataset_versions_dataset_fp CHECK
    (dataset_fingerprint IS NULL OR dataset_fingerprint ~ '^[0-9a-f]{64}$'),
  CONSTRAINT dataset_versions_registration_fp CHECK (registration_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS dataset_versions_client_idx
  ON dataset_versions (tenant_id, client_id, doc_type, version);

-- Registration evidence is immutable audit history: no update path exists, and
-- no delete path exists (retention is a later decision). Approval and release
-- are separate records with their own owners; they must never be bolted on here
-- as mutable columns.
CREATE OR REPLACE FUNCTION dataset_versions_immutable_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'dataset_versions rows are immutable registration evidence (no updates, no deletes)';
END;
$$;

DROP TRIGGER IF EXISTS dataset_versions_no_mutation ON dataset_versions;
CREATE TRIGGER dataset_versions_no_mutation
BEFORE UPDATE ON dataset_versions
FOR EACH ROW EXECUTE FUNCTION dataset_versions_immutable_guard();

DROP TRIGGER IF EXISTS dataset_versions_no_delete ON dataset_versions;
CREATE TRIGGER dataset_versions_no_delete
BEFORE DELETE ON dataset_versions
FOR EACH ROW EXECUTE FUNCTION dataset_versions_immutable_guard();
