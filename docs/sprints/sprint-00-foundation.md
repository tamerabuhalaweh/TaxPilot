# Sprint 0 — foundation implementation notes (EP-01 #1)

Branch: `feature/sprint-00-foundation`. Scope: reproducible dev foundation only. No tax logic, no reconciliation, no JUR contracts (those need PO approval of PR #32/#33 corrections).

## What was built
- `apps/api` — FastAPI + `/api/v1/health` + `/api/v1/ready`, correlation-ID middleware, error envelope `{error:{code,message,details,request_id}}`, pydantic-settings config (env-only secrets), JSON logging with redaction, SQLAlchemy engine helpers, DI boundaries (`app/deps.py`).
- `apps/api/worker` — job model (id/status/attempts/retry/idempotency/error/correlation), Redis backend with honest in-memory fallback, `process_one` claim→handle→finish with requeue-then-fail, `runner.py` loop (supports `noop`/`echo` only).
- `db/` — versioned SQL migrations + `migrate.py` runner (transactional, idempotent, `schema_migrations` ledger). `0001` creates the ledger itself.
- `apps/web` — Next.js 14 + TS strict + app router + layout + design tokens + EN/AR dictionaries with RTL + Button/StatusPill/EmptyState/Alert + typed API client + dashboard page (backend status, one primary action, no mock reviews) + vitest i18n test.
- `docker-compose.yml` — postgres:16, redis:7-alpine, minio, api, worker, web. `.env.example` documents local vars (no secrets committed).
- `.github/workflows/ci.yml` — backend (ruff lint+format, mypy, pytest, migration file validation), integration (postgres+redis services: migrate + integration tests + API health), frontend (typecheck, vitest, build), security (pip-audit, npm audit — non-blocking reporters for now).

## Deliberately deferred (with reason)
- `packages/contracts|shared`, `workers/ingestion|reconciliation|reports`, `rules/jordan`, `infrastructure/`, `tests/e2e`: no purpose yet without domain contracts (Sprint 1+). Worker logic lives in `apps/api/worker` until the approved queue topology exists. Git does not track empty dirs; creating them would be decoration.
- Alembic: the 30-line `migrate.py` runner is the migration framework (reviewable, dependency-free, tested). Revisit if migrations outgrow versioned SQL.
- Deployment: CI builds + validates; no prod deploy target yet (no hosting decision — blocker).

## Run it
See README “Local development”. Test evidence for this PR is recorded in Task 3 outputs (no fabricated results).
