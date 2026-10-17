-- 0009: human-confirmed versioned mapping proposals + append-only approval evidence
-- (REC-DATA-02). Mapping approval is an INDEPENDENT artifact from dataset
-- registration (0008) and source release (REC-DATA-03): approval derives from the
-- latest valid review decision bound to the exact dataset version, engagement
-- revision, header fingerprint and normalization/schema versions, and is never a
-- mutable boolean bolted onto another table. This migration creates metadata +
-- explicit maps + review decisions ONLY: never raw file bytes, storage secrets,
-- trusted source headers, or financial contents.
--
-- Trust boundary: a proposal carries the human-authored explicit field map, but
-- its header_fingerprint is the SERVER-DERIVED fingerprint of trusted source
-- headers. No trusted source-header attestation exists yet (extraction/read is
-- blocked), so the authenticated submission/confirmation routes stay default-deny
-- and no row is fabricated from the API. These tables are the append-only
-- evidence the future trusted writer will use; they do not enable any release or
-- reconciliation execution. Old migrations are never edited.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS mapping_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  engagement_id UUID NOT NULL,
  dataset_version_id UUID NOT NULL,
  doc_type TEXT NOT NULL,
  header_fingerprint TEXT NOT NULL,
  field_map JSONB NOT NULL,
  mapping_version TEXT NOT NULL,
  normalization_version TEXT NOT NULL,
  canonical_schema_version TEXT NOT NULL,
  engagement_revision INTEGER NOT NULL,
  proposal_fingerprint TEXT NOT NULL,
  proposed_by UUID REFERENCES users(id),
  proposed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Scope + lineage: a proposal binds its client, its engagement (whose client
  -- must match), and its dataset version (which must belong to the same client),
  -- all inside one tenant — never a bare global id.
  CONSTRAINT mapping_proposals_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id) ON DELETE RESTRICT,
  CONSTRAINT mapping_proposals_engagement_fk
    FOREIGN KEY (tenant_id, engagement_id, client_id)
    REFERENCES engagements(tenant_id, id, client_id) ON DELETE RESTRICT,
  CONSTRAINT mapping_proposals_dataset_fk
    FOREIGN KEY (tenant_id, client_id, dataset_version_id)
    REFERENCES dataset_versions(tenant_id, client_id, id) ON DELETE RESTRICT,
  -- Lineage-grade scope keys so decisions below bind the full proposal scope.
  CONSTRAINT mapping_proposals_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT mapping_proposals_scope_key UNIQUE
    (tenant_id, id, client_id, dataset_version_id, engagement_id),
  CONSTRAINT mapping_proposals_doc_type CHECK
    (doc_type IN ('sales_register', 'general_ledger', 'jofotara_export')),
  CONSTRAINT mapping_proposals_header_fp CHECK (header_fingerprint ~ '^[0-9a-f]{64}$'),
  CONSTRAINT mapping_proposals_proposal_fp CHECK (proposal_fingerprint ~ '^[0-9a-f]{64}$'),
  -- An explicit, non-empty canonical-field -> source-header object: no inference,
  -- no empty map, no scalar/array payloads.
  CONSTRAINT mapping_proposals_field_map CHECK
    (jsonb_typeof(field_map) = 'object' AND field_map <> '{}'::jsonb),
  CONSTRAINT mapping_proposals_mapping_version CHECK
    (char_length(mapping_version) BETWEEN 1 AND 64),
  CONSTRAINT mapping_proposals_normalization_version CHECK
    (char_length(normalization_version) BETWEEN 1 AND 64),
  CONSTRAINT mapping_proposals_schema_version CHECK
    (char_length(canonical_schema_version) BETWEEN 1 AND 64),
  CONSTRAINT mapping_proposals_engagement_revision CHECK (engagement_revision >= 1),
  -- Tenant+engagement+dataset-version-scoped idempotency: replaying the same
  -- proposal identity converges; the same (proposal, dataset version) with a
  -- different fingerprint conflicts, never overwrites.
  CONSTRAINT mapping_proposals_idem_uidx UNIQUE
    (tenant_id, engagement_id, dataset_version_id, proposal_fingerprint)
);

CREATE INDEX IF NOT EXISTS mapping_proposals_engagement_idx
  ON mapping_proposals (tenant_id, engagement_id, proposed_at);
CREATE INDEX IF NOT EXISTS mapping_proposals_dataset_idx
  ON mapping_proposals (tenant_id, client_id, dataset_version_id);

CREATE TABLE IF NOT EXISTS mapping_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  engagement_id UUID NOT NULL,
  proposal_id UUID NOT NULL,
  dataset_version_id UUID NOT NULL,
  decision TEXT NOT NULL,
  reviewer_id UUID REFERENCES users(id),
  reason TEXT,
  idempotency_key TEXT NOT NULL,
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- A decision is pinned to the EXACT proposal scope (client + dataset version +
  -- engagement), so its client/engagement can never drift from the proposal it
  -- reviews, and cross-client decisions are impossible.
  CONSTRAINT mapping_decisions_proposal_fk
    FOREIGN KEY (tenant_id, proposal_id, client_id, dataset_version_id, engagement_id)
    REFERENCES mapping_proposals (tenant_id, id, client_id, dataset_version_id, engagement_id)
    ON DELETE RESTRICT,
  CONSTRAINT mapping_decisions_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id) ON DELETE RESTRICT,
  CONSTRAINT mapping_decisions_decision CHECK
    (decision IN ('APPROVED', 'REJECTED', 'SUPERSEDED')),
  CONSTRAINT mapping_decisions_reason CHECK
    (reason IS NULL OR char_length(reason) BETWEEN 1 AND 512),
  -- Tenant+engagement+proposal-scoped idempotency: the same key on another scope
  -- is independent; the same key on this proposal does not double-apply.
  CONSTRAINT mapping_decisions_idem_uidx UNIQUE
    (tenant_id, engagement_id, proposal_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS mapping_decisions_proposal_idx
  ON mapping_decisions (tenant_id, proposal_id, decided_at);

-- Approval evidence is append-only audit history: no update path exists, and no
-- delete path exists (retention is a later decision). Revocation/superseding is a
-- NEW decision row, never a mutation of history; staleness is derived at read
-- time from the exact scope coordinates.
CREATE OR REPLACE FUNCTION mapping_proposals_immutable_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mapping_proposals rows are immutable mapping evidence (no updates, no deletes)';
END;
$$;

DROP TRIGGER IF EXISTS mapping_proposals_no_mutation ON mapping_proposals;
CREATE TRIGGER mapping_proposals_no_mutation
BEFORE UPDATE ON mapping_proposals
FOR EACH ROW EXECUTE FUNCTION mapping_proposals_immutable_guard();

DROP TRIGGER IF EXISTS mapping_proposals_no_delete ON mapping_proposals;
CREATE TRIGGER mapping_proposals_no_delete
BEFORE DELETE ON mapping_proposals
FOR EACH ROW EXECUTE FUNCTION mapping_proposals_immutable_guard();

CREATE OR REPLACE FUNCTION mapping_decisions_immutable_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'mapping_decisions rows are immutable approval evidence (no updates, no deletes)';
END;
$$;

DROP TRIGGER IF EXISTS mapping_decisions_no_mutation ON mapping_decisions;
CREATE TRIGGER mapping_decisions_no_mutation
BEFORE UPDATE ON mapping_decisions
FOR EACH ROW EXECUTE FUNCTION mapping_decisions_immutable_guard();

DROP TRIGGER IF EXISTS mapping_decisions_no_delete ON mapping_decisions;
CREATE TRIGGER mapping_decisions_no_delete
BEFORE DELETE ON mapping_decisions
FOR EACH ROW EXECUTE FUNCTION mapping_decisions_immutable_guard();
