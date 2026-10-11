-- 0001: schema-migrations ledger (foundation; domain tables arrive Sprint 1+).
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
