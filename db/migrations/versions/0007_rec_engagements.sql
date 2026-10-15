-- 0007: engagement foundation + reconciliation-run boundary (REC-SLICE-03).
-- Tenant is the security boundary; every row carries tenant_id and all
-- cross-table references bind the full (tenant, ...) scope, never a bare id.
-- Engagements reference clients with ON DELETE RESTRICT so client archive or
-- deletion can never destroy engagement audit history. Engagement transitions
-- are recorded in engagement_events (actor + time + prior/new), rows are never
-- deleted. recon_runs rows are IMMUTABLE (trigger-guarded): execution requests
-- are recorded with a stable blocked reason while real dataset versions,
-- mapping approvals, release gates, and supported JoFotara profiles have no
-- persisted trusted source yet. No worker wiring: nothing here enables
-- background financial processing. Old migrations are never edited.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS engagements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  review_type TEXT NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  assignee_user_id UUID REFERENCES users(id),
  -- No FK: tax_contexts is owned by the jurisdiction slice (PR #47 direction);
  -- the API verifies same-tenant + same-client + confirmation server-side.
  tax_context_id UUID,
  created_by UUID REFERENCES users(id),
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT engagements_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id) ON DELETE RESTRICT,
  -- Lineage-grade scope key so run records below bind (tenant, engagement).
  CONSTRAINT engagements_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT engagements_status CHECK (status IN ('DRAFT', 'ACTIVE', 'CLOSED', 'ARCHIVED')),
  CONSTRAINT engagements_period CHECK (period_start <= period_end),
  CONSTRAINT engagements_review_type CHECK (char_length(review_type) BETWEEN 1 AND 64),
  -- Duplicate same-period engagement for one client/type converges instead of
  -- double-booking the review period (SRS FR-WRK-004 duplicate warning).
  CONSTRAINT engagements_period_uidx UNIQUE (tenant_id, client_id, period_start, period_end, review_type)
);

CREATE INDEX IF NOT EXISTS engagements_tenant_client_idx
  ON engagements (tenant_id, client_id);

CREATE TABLE IF NOT EXISTS engagement_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  engagement_id UUID NOT NULL REFERENCES engagements(id) ON DELETE RESTRICT,
  actor_id UUID REFERENCES users(id),
  action TEXT NOT NULL,
  prior_status TEXT,
  new_status TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT engagement_events_action CHECK (action IN ('created', 'status_changed', 'assignee_changed'))
);

CREATE INDEX IF NOT EXISTS engagement_events_engagement_idx
  ON engagement_events (engagement_id, created_at);

CREATE TABLE IF NOT EXISTS recon_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  engagement_id UUID NOT NULL,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  sales_dataset_version_id TEXT NOT NULL,
  jofo_dataset_version_id TEXT NOT NULL,
  source_set_fingerprint TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  projection_version TEXT NOT NULL,
  period_start DATE,
  period_end DATE,
  jurisdiction_code TEXT,
  status TEXT NOT NULL,
  blocked_reason TEXT NOT NULL,
  blocked_detail TEXT,
  requested_by UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT recon_runs_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id) ON DELETE RESTRICT,
  CONSTRAINT recon_runs_tenant_engagement_fk
    FOREIGN KEY (tenant_id, engagement_id) REFERENCES engagements(tenant_id, id) ON DELETE RESTRICT,
  -- Execution stays refused until approved source conditions exist; execution
  -- statuses arrive with the worker slice, never by editing this migration.
  CONSTRAINT recon_runs_status CHECK (status IN ('BLOCKED')),
  CONSTRAINT recon_runs_reason CHECK (char_length(blocked_reason) BETWEEN 1 AND 64),
  -- Tenant+engagement+operation-scoped idempotency: same key in another scope
  -- is independent; same key with a different payload conflicts, never merges.
  CONSTRAINT recon_runs_idem_uidx UNIQUE (tenant_id, engagement_id, operation, idempotency_key)
);

CREATE INDEX IF NOT EXISTS recon_runs_engagement_idx
  ON recon_runs (tenant_id, engagement_id, created_at);

-- Run records are append-only evidence: no update path exists, and no delete
-- path exists (retention is a later decision, as with document_intakes).
CREATE OR REPLACE FUNCTION recon_runs_immutable_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'recon_runs rows are immutable audit evidence (no updates, no deletes)';
END;
$$;

DROP TRIGGER IF EXISTS recon_runs_no_mutation ON recon_runs;
CREATE TRIGGER recon_runs_no_mutation
BEFORE UPDATE ON recon_runs
FOR EACH ROW EXECUTE FUNCTION recon_runs_immutable_guard();

DROP TRIGGER IF EXISTS recon_runs_no_delete ON recon_runs;
CREATE TRIGGER recon_runs_no_delete
BEFORE DELETE ON recon_runs
FOR EACH ROW EXECUTE FUNCTION recon_runs_immutable_guard();
