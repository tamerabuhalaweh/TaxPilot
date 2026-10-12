-- 0004: jurisdiction foundation, Phase 1 (JUR-01 proposal, PO-authorized).
-- EMPTY tables + jurisdiction metadata seeds ONLY. This migration MUST NOT create
-- or infer legal entities, incorporation countries, currencies, obligations,
-- registrations, contexts, or periods from existing clients: there are no
-- authoritative facts to migrate. Existing client rows stay byte-identical apart
-- from the additive candidate key below. Old migrations are never edited.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Candidate key the composite tenant-scoped FKs below must reference.
-- R1 (PR #41 review, HOLD-MERGE fix): VERIFY-ONLY, never drop. An earlier draft
-- used DROP CONSTRAINT ... CASCADE, which would silently remove the dependent
-- FKs this same file creates (legal_entities, tax_obligation_profiles,
-- tax_contexts, tax_registrations) and destroy tenant isolation on rerun. This
-- block ADDS the key only when absent; when present it verifies the exact
-- definition and FAILS CLOSED on any mismatch (refuses to modify or replace).
DO $$
DECLARE
  _conoid OID;
  _contype CHAR;
  _cols TEXT;
BEGIN
  SELECT c.oid INTO _conoid
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE c.conname = 'clients_tenant_id_key'
    AND t.relname = 'clients'
    AND n.nspname = current_schema();
  IF _conoid IS NULL THEN
    ALTER TABLE clients
      ADD CONSTRAINT clients_tenant_id_key UNIQUE (tenant_id, id);
  ELSE
    SELECT c.contype INTO _contype FROM pg_constraint c WHERE c.oid = _conoid;
    SELECT string_agg(a.attname, ',' ORDER BY u.ord) INTO _cols
    FROM pg_constraint c
    JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.attnum
    WHERE c.oid = _conoid;
    IF _contype <> 'u' OR _cols IS DISTINCT FROM 'tenant_id,id' THEN
      RAISE EXCEPTION
        'clients_tenant_id_key exists with unexpected definition (type %, columns %); refusing to modify or replace',
        _contype, _cols;
    END IF;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS jurisdiction_catalog (
  code TEXT PRIMARY KEY,
  name_en TEXT NOT NULL,
  name_ar TEXT NOT NULL,
  availability TEXT NOT NULL,
  release_pack_version TEXT,
  capabilities JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT jurisdiction_availability CHECK (availability IN ('PLANNED','IN_REVIEW','BETA','ACTIVE','RETIRED'))
);
-- JO is catalog-ACTIVE metadata with ZERO executable capabilities. AE/SA are
-- PLANNED with empty manifests. Catalog ACTIVE never implies rule approval.
INSERT INTO jurisdiction_catalog (code, name_en, name_ar, availability, release_pack_version, capabilities)
VALUES
  ('JO', 'Jordan', 'الأردن', 'ACTIVE', '0.1.0',
   '{"pack_version":"0.1.0","tax_types":[],"rules":[],"file_import":[]}'),
  ('AE', 'United Arab Emirates', 'الإمارات العربية المتحدة', 'PLANNED', NULL,
   '{"pack_version":null,"tax_types":[],"rules":[],"file_import":[]}'),
  ('SA', 'Saudi Arabia', 'المملكة العربية السعودية', 'PLANNED', NULL,
   '{"pack_version":null,"tax_types":[],"rules":[],"file_import":[]}')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS legal_entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  legal_name TEXT NOT NULL,
  incorporation_country_code TEXT NOT NULL REFERENCES jurisdiction_catalog(code),
  entity_type TEXT NOT NULL DEFAULT 'COMPANY',
  legal_identifier_ciphertext BYTEA,
  base_currency TEXT NOT NULL,
  fiscal_start TEXT NOT NULL DEFAULT '01-01',
  parent_legal_entity_id UUID,
  status TEXT NOT NULL DEFAULT 'SUGGESTED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT legal_entities_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT legal_entities_tenant_client_key UNIQUE (tenant_id, client_id, id),
  CONSTRAINT legal_entities_tenant_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients (tenant_id, id),
  CONSTRAINT legal_entities_parent_fk
    FOREIGN KEY (tenant_id, parent_legal_entity_id) REFERENCES legal_entities (tenant_id, id),
  CONSTRAINT legal_entities_currency CHECK (base_currency ~ '^[A-Z]{3}$'),
  CONSTRAINT legal_entities_status CHECK (status IN ('SUGGESTED','DRAFT','VERIFIED_ACTIVE','ENDED'))
);
CREATE UNIQUE INDEX IF NOT EXISTS legal_entities_active_name_key
  ON legal_entities (tenant_id, client_id, legal_name) WHERE status <> 'ENDED';
CREATE INDEX IF NOT EXISTS legal_entities_tenant_client_idx
  ON legal_entities (tenant_id, client_id);

CREATE TABLE IF NOT EXISTS tax_obligation_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  legal_entity_id UUID NOT NULL,
  jurisdiction_code TEXT NOT NULL REFERENCES jurisdiction_catalog(code),
  tax_type_code TEXT NOT NULL,
  regime_code TEXT,
  valid_from DATE NOT NULL,
  valid_to DATE,
  registration_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  verified_by UUID,
  verified_at TIMESTAMPTZ,
  source_ref TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  CONSTRAINT obligation_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT obligation_tenant_client_key UNIQUE (tenant_id, client_id, id),
  -- Same-client enforcement: the entity must belong to the obligation's client,
  -- not merely to the same tenant (multi-client tenants would otherwise mix).
  CONSTRAINT obligation_entity_fk
    FOREIGN KEY (tenant_id, client_id, legal_entity_id)
    REFERENCES legal_entities (tenant_id, client_id, id),
  CONSTRAINT obligation_dates CHECK (valid_to IS NULL OR valid_from <= valid_to),
  CONSTRAINT obligation_reg_status CHECK (registration_status IN
    ('UNKNOWN','NOT_REGISTERED','PENDING','REGISTERED','ENDED'))
);
CREATE INDEX IF NOT EXISTS obligation_tenant_entity_idx
  ON tax_obligation_profiles (tenant_id, legal_entity_id, jurisdiction_code);

CREATE TABLE IF NOT EXISTS tax_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  obligation_profile_id UUID NOT NULL,
  authority_code TEXT NOT NULL,
  registration_kind TEXT NOT NULL,
  number_ciphertext BYTEA,
  number_nonce BYTEA,
  number_last4 TEXT,
  key_id TEXT,
  alg_version TEXT NOT NULL DEFAULT 'aes-256-gcm-v1',
  starts_on DATE,
  ends_on DATE,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  version INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT registration_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT registration_obligation_fk
    FOREIGN KEY (tenant_id, obligation_profile_id) REFERENCES tax_obligation_profiles (tenant_id, id),
  -- Ciphertext model (Master §6): R3 (PR #41 review, HOLD-MERGE fix) enforces
  -- complete BIDIRECTIONAL co-presence. Ciphertext and nonce arrive and leave
  -- together (nonce exactly 12 bytes); key metadata and partial identifiers
  -- must never exist without the encrypted identifier they describe, and an
  -- identifier must always travel with its key id. NULL ciphertext allowed
  -- ONLY where collection is deliberately disabled (fail-closed at the API;
  -- identifier collection stays disabled until PR-B implements encryption).
  CONSTRAINT registration_crypto_shape CHECK (
    (number_ciphertext IS NULL AND number_nonce IS NULL)
    OR (number_ciphertext IS NOT NULL AND number_nonce IS NOT NULL
        AND octet_length(number_nonce) = 12)
  ),
  CONSTRAINT registration_key_co_presence CHECK (
    (key_id IS NULL) = (number_ciphertext IS NULL)
  ),
  CONSTRAINT registration_last4_requires_ciphertext CHECK (
    number_last4 IS NULL OR number_ciphertext IS NOT NULL
  )
);
CREATE INDEX IF NOT EXISTS registration_tenant_obligation_idx
  ON tax_registrations (tenant_id, obligation_profile_id);

CREATE TABLE IF NOT EXISTS tax_contexts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  client_id UUID NOT NULL,
  subject_kind TEXT NOT NULL DEFAULT 'LEGAL_ENTITY',
  subject_entity_id UUID,
  subject_group_id UUID,
  obligation_profile_id UUID,
  jurisdiction_code TEXT NOT NULL REFERENCES jurisdiction_catalog(code),
  tax_type_code TEXT NOT NULL,
  regime_code TEXT,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  profile_version INTEGER,
  context_revision INTEGER NOT NULL DEFAULT 1,
  pack_version TEXT,
  confirmation_status TEXT NOT NULL DEFAULT 'DRAFT',
  context_hash TEXT,
  snapshot JSONB,
  confirmed_by UUID,
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT context_tenant_key UNIQUE (tenant_id, id),
  CONSTRAINT context_tenant_hash_key UNIQUE (tenant_id, context_hash),
  CONSTRAINT context_client_fk
    FOREIGN KEY (tenant_id, client_id) REFERENCES clients (tenant_id, id),
  CONSTRAINT context_entity_fk
    FOREIGN KEY (tenant_id, client_id, subject_entity_id)
    REFERENCES legal_entities (tenant_id, client_id, id),
  -- Phase 1 accepts entity subjects only; the nullable group column plus this
  -- CHECK widen in Phase 2 (never a permanently non-null entity FK blocking groups).
  CONSTRAINT context_subject CHECK (
    (subject_kind = 'LEGAL_ENTITY' AND subject_entity_id IS NOT NULL AND subject_group_id IS NULL)
  ),
  -- Same-client obligation binding (plus PR-B app validation that the obligation
  -- belongs to the context's subject, jurisdiction, and period).
  CONSTRAINT context_obligation_fk
    FOREIGN KEY (tenant_id, client_id, obligation_profile_id)
    REFERENCES tax_obligation_profiles (tenant_id, client_id, id),
  CONSTRAINT context_period CHECK (period_start <= period_end),
  CONSTRAINT context_confirmation CHECK (confirmation_status IN ('DRAFT','NEEDS_CONFIRMATION','CONFIRMED'))
);
CREATE INDEX IF NOT EXISTS context_tenant_client_idx
  ON tax_contexts (tenant_id, client_id, jurisdiction_code, period_start);

-- Confirmed-context freeze guard (REJECTED alternative: dynamic per-row REVOKE).
-- R2 (PR #41 review, HOLD-MERGE fix): CONFIRMED rows reject ALL updates in
-- place; new revisions are INSERTs. Identity and attribution (id, tenant_id,
-- client_id, subject, obligation, created_at, confirmed_by/at) are frozen from
-- birth: pre-confirmation edits may change only working fields, and the sole
-- privileged transition is DRAFT/NEEDS_CONFIRMATION -> CONFIRMED carrying the
-- confirmation actor/time. Operational status lives in future run tables.
CREATE OR REPLACE FUNCTION tax_context_freeze_guard() RETURNS trigger AS $$
BEGIN
  -- Rule 1: a CONFIRMED row is fully immutable, including no-op writes.
  IF OLD.confirmation_status = 'CONFIRMED' THEN
    RAISE EXCEPTION 'tax_context % is CONFIRMED and immutable; create a new revision row instead (42890)', OLD.id;
  END IF;
  -- Rule 2: the confirmation transition may set status + actor/time only.
  IF NEW.confirmation_status = 'CONFIRMED' AND OLD.confirmation_status <> 'CONFIRMED' THEN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.client_id IS DISTINCT FROM OLD.client_id
       OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
       OR NEW.subject_entity_id IS DISTINCT FROM OLD.subject_entity_id
       OR NEW.subject_group_id IS DISTINCT FROM OLD.subject_group_id
       OR NEW.jurisdiction_code IS DISTINCT FROM OLD.jurisdiction_code
       OR NEW.tax_type_code IS DISTINCT FROM OLD.tax_type_code
       OR NEW.regime_code IS DISTINCT FROM OLD.regime_code
       OR NEW.obligation_profile_id IS DISTINCT FROM OLD.obligation_profile_id
       OR NEW.profile_version IS DISTINCT FROM OLD.profile_version
       OR NEW.period_start IS DISTINCT FROM OLD.period_start
       OR NEW.period_end IS DISTINCT FROM OLD.period_end
       OR NEW.pack_version IS DISTINCT FROM OLD.pack_version
       OR NEW.snapshot IS DISTINCT FROM OLD.snapshot
       OR NEW.context_hash IS DISTINCT FROM OLD.context_hash
       OR NEW.context_revision IS DISTINCT FROM OLD.context_revision
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
      RAISE EXCEPTION 'tax_context % confirmation must not alter identity or content; create a new revision row instead (immutable, 42891)', OLD.id;
    END IF;
    RETURN NEW;
  END IF;
  -- Rule 3: pre-confirmation edits freeze identity and attribution only; working
  -- fields (periods, snapshot, status steps below CONFIRMED, ...) stay editable.
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.client_id IS DISTINCT FROM OLD.client_id
     OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
     OR NEW.subject_entity_id IS DISTINCT FROM OLD.subject_entity_id
     OR NEW.subject_group_id IS DISTINCT FROM OLD.subject_group_id
     OR NEW.jurisdiction_code IS DISTINCT FROM OLD.jurisdiction_code
     OR NEW.obligation_profile_id IS DISTINCT FROM OLD.obligation_profile_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
     OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at THEN
    RAISE EXCEPTION 'tax_context % identity and attribution are immutable (42892)', OLD.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tax_context_freeze ON tax_contexts;
CREATE TRIGGER tax_context_freeze
  BEFORE UPDATE ON tax_contexts
  FOR EACH ROW EXECUTE FUNCTION tax_context_freeze_guard();

-- Ledger hash column for tamper-evident migrations (see db/migrate.py). Additive;
-- 0001 is never edited.
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS sha256 TEXT;


