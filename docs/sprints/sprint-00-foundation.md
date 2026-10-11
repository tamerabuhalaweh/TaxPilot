# Sprint 0 — foundation implementation notes (EP-01 #1)

Branch: `feature/sprint-00-foundation`. Scope: reproducible dev foundation only. No tax logic, no reconciliation, no JUR contracts (those need PO approval of PR #15 + #32/#33).

## What was built
- `apps/api` — FastAPI + `/api/v1/health` (liveness) + `/api/v1/ready` (per-request bounded probes; 503 with per-check flags when a required dependency is down; no DSN leaks), validated/coerced correlation IDs, error envelope `{error:{code,message,details,request_id}}`, explicit CORS allowlist (no wildcard, no credentials), pydantic-settings config with production guards (dev defaults + memory queue refused in prod), JSON logging with redaction, SQLAlchemy engine helpers (bounded connect timeout), DI boundaries (`app/deps.py`), lifespan startup/shutdown with engine disposal.
- `apps/api/worker` — real shared Redis queue: Lua-atomic enqueue (idempotency-checked) and claim (no double-claim across workers), bounded retries, terminal FAILED with retained inspectable error, `recover_stale` for crashed-worker recovery. Guarantees documented in code: durable-on-ack, at-least-once, never exactly-once; handlers must be idempotent. `MemoryBackend` kept for unit tests + explicit local/dev only. Runner supports `noop`/`echo` only.
- `db/` — versioned SQL migrations + `migrate.py` runner (transactional, idempotent, name/duplicate validation, failed versions record nothing, loud connectivity errors). `0001` creates the ledger itself.
- `apps/web` — Next.js 16.4.0 + React 19.3.0 (upgraded from 14.2/18.3 to remediate 20+ framework advisories; typecheck/tests/build/dev re-verified) + strict TS + EN/AR + RTL + design tokens + 4 components + typed same-origin API client + route-handler proxy (`app/api/v1/[...path]`, runtime `API_INTERNAL_URL`, 10s timeout, 502 mapping without backend detail) + dashboard (backend status, one primary action) + honest `/reviews/new` placeholder (no inert buttons) + vitest i18n tests + Playwright journey spec (4 tests).
- `docker-compose.yml` — postgres:16, redis:7-alpine, minio, api, worker, web. `.env.example` documents local vars (127.0.0.1 notes for Node→uvicorn; no secrets committed).
- `.github/workflows/ci.yml` — backend (ruff lint+format incl. scripts, mypy, pytest, migration file validation), integration (postgres+redis services, REQUIRE_SERVICES=1: migrate + cross-process queue + migration tests + API health — failures fail, never skip), frontend (`npm ci`, typecheck, vitest, build), browser (API + production web + Playwright), security (pip-audit + npm audit through `security_gate.py` with expiring-exceptions file; fails on non-exempt pip findings / npm high+critical).
- `.github/security-exceptions.json` — empty (no exceptions granted); `.github/scripts/security_gate.py` — threshold gate with negative-control verified.

## Review corrections (PR #34 review, CHANGES REQUIRED → addressed)
- P0-A real queue: RedisBackend rewritten (was memory-backed); cross-process tests (separate OS processes) for echo, duplicates, 2-worker concurrency (attempts sum exact), crash recovery, retry exhaustion, loud Redis-down; production memory fallback refused.
- P0-B security: upgraded Next 14.2.35→16.4.0 + React 19 (20+ GHSA incl. RCE/SSRF remediated; prod audit 0 vulns); pip starlette advisories fixed via fastapi 0.143.0; CI masking removed; gate fails on non-exempt findings (verified with synthetic critical); `npm ci` in CI + Dockerfile (same lockfile graph).
- P0-C readiness: per-request probes, 503 semantics, bounded timeouts, startup no longer gates on deps, down/recovery tests, no-DSN-leak test.
- P0-D tests: all `or True` removed; discovery/order/first-apply/rerun-noop/bad-name/duplicate/failed-SQL-clean/unreachable-raises all real; REQUIRE_SERVICES=1 makes service absence fail (CI sets it; local skips documented).
- P0-E journey: same-origin route-handler proxy (runtime env; destination host never from request input) + explicit CORS allowlist; `/reviews/new` honest placeholder; Playwright 4-test journey green against production build.

## Deliberately deferred (with reason)
- `packages/contracts|shared`, `workers/ingestion|reconciliation|reports`, `rules/jordan`, `infrastructure/`, `tests/e2e`: no purpose yet without domain contracts (Sprint 1+). Worker logic lives in `apps/api/worker` until the approved queue topology exists.
- Alembic: the `migrate.py` runner is the migration framework (reviewable, dependency-free, tested).
- Deployment: CI builds + validates; no prod deploy target yet (no hosting decision — blocker).
- postcss pair: remediated via the Next 16 upgrade (no exception needed).

## Run it
See README “Local development”. Test evidence for this PR is recorded in Task 3 outputs (no fabricated results).
