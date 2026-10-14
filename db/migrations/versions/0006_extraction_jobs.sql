-- 0006: PG-authoritative durable processing jobs + transactional outbox (EP-04C1).
-- PostgreSQL is the durable source of truth; Redis carries wakeups only and may
-- be lost without losing committed jobs. This migration creates metadata +
-- bounded reference payloads ONLY: never raw file bytes, storage secrets, or
-- financial contents. No worker activation: jobs_durability_approved stays false
-- and production processing remains refused until #35 closes. Old migrations
-- are never edited.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS extraction_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'QUEUED',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  lease_owner TEXT NOT NULL DEFAULT '',
  fencing_token TEXT NOT NULL DEFAULT '',
  lease_expires_at TIMESTAMPTZ,
  not_before TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT,
  last_error_class TEXT,
  terminal_error TEXT,
  terminal_error_class TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT extraction_jobs_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients(tenant_id, id),
  CONSTRAINT extraction_jobs_status CHECK
    (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD')),
  CONSTRAINT extraction_jobs_attempts CHECK (attempts >= 0),
  CONSTRAINT extraction_jobs_max_attempts CHECK (max_attempts >= 1),
  CONSTRAINT extraction_jobs_payload_size CHECK (octet_length(payload::text) <= 65536)
);

-- Tenant-scoped idempotency: the same key in another tenant is an independent
-- job (no cross-tenant coupling); the same key + different payload conflicts.
CREATE UNIQUE INDEX IF NOT EXISTS extraction_jobs_idem_uidx
  ON extraction_jobs (tenant_id, idempotency_key);
-- Claim/sweep scan: eligible queued rows oldest-first; concurrent claimants
-- serialize on FOR UPDATE SKIP LOCKED, never double-claim.
CREATE INDEX IF NOT EXISTS extraction_jobs_claim_idx
  ON extraction_jobs (status, not_before, created_at, id);
CREATE INDEX IF NOT EXISTS extraction_jobs_lease_idx
  ON extraction_jobs (status, lease_expires_at);

CREATE TABLE IF NOT EXISTS job_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  job_id UUID NOT NULL REFERENCES extraction_jobs(id),
  event_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'PENDING',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT job_outbox_status CHECK (status IN ('PENDING', 'PUBLISHED', 'FAILED')),
  CONSTRAINT job_outbox_attempts CHECK (attempts >= 0),
  CONSTRAINT job_outbox_max_attempts CHECK (max_attempts >= 1),
  CONSTRAINT job_outbox_payload_size CHECK (octet_length(payload::text) <= 65536)
);

-- Retried publishes of the same logical event converge on one row per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS job_outbox_event_uidx
  ON job_outbox (tenant_id, event_key);
CREATE INDEX IF NOT EXISTS job_outbox_claim_idx
  ON job_outbox (status, next_attempt_at, created_at, id);
