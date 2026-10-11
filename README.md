# TaxPilot Jordan

AI-assisted tax reconciliation and financial review platform for Jordanian accounting firms.

**Authoritative spec:** [`docs/product/TAXPILOT_MASTER_SRS.md`](docs/product/TAXPILOT_MASTER_SRS.md) (v2.0 unified draft — single normative baseline, pending PO approval via PR #38).

**History:** SRS v1.1 file + v1.1a jurisdiction amendment + architecture corrections retained as traceability (see §0.1 of the unified master; conflicting implementation details in them are bannered SUPERSEDED). Superseded SRS v1.0 `.docx` under `docs/product/superseded/`. PRs #15/#32/#33 will be CLOSED AS SUPERSEDED by PR #38 after approval — never merged individually. Do not build scope from superseded documents alone.

**Tax Intelligence:** one shared EP-16 system ([#17](https://github.com/tamerabuhalaweh/TaxPilot/issues/17)); broad research/RAG capabilities are P1, staged separately from the deterministic MVP. No JoFotara import/rules or AE/SA tax execution exists yet — Jordan-first reconciliation MVP first.

## Product promise
Sign in → Select/create client → Start tax review → Upload Sales Register + JoFotara Export + GL → Confirm mappings → Run reconciliation (REC-001..005) → Investigate → Record decisions → Bilingual PDF/XLSX report.

- Reconciliation-first, accountant-focused. Deterministic engine calculates; AI assists; accountants decide.
- File-based JoFotara import in MVP. No government API integration, no portal credentials.
- Arabic/English + RTL. Light-mode-first, one primary action per screen.
- Strict tenant isolation, versioned rules, evidence traceability, expert-gated tax conclusions.

## Repo map (as built on `main`: Sprint 0 PR #34 + Sprint 1 PR #37 merged)
- `docs/product/` — unified Master SRS v2.0 draft + v1.1/v1.1a history + ERD/OpenAPI proposals/UX/test-plan/roadmap (bannered where superseded) + `verify_traceability.py` + ADRs (001/002 unresolved, 003 conditional)
- `docs/architecture/` — review-correction records (provenance, non-normative)
- `docs/sprints/` — sprint implementation notes; `docs/engineering/BLOCKERS.md` — visible blocker register
- `apps/api/` — FastAPI 0.143 + SQLAlchemy 2.0 (`/api/v1/health`, `/ready` with 503 semantics, error envelope, correlation IDs, env config + production guards, redacted JSON logs, bcrypt auth, tenant RBAC, CSRF, body caps) + `worker/` (fenced-lease Redis queue: atomic Lua CAS, heartbeats, auto-recovery; worker-crash-only durability; production gate) + `tests/`
- `apps/web/` — Next.js 16.4.0 + React 19.3.0 + strict TS + EN/AR + RTL + design tokens + typed same-origin API client + route-handler BFF proxy (fixed host, header allowlist, bounded streaming reads) + signed-in dashboard slice (no mock data)
- `db/migrations/` — versioned SQL (`0001` ledger, `0002` auth/tenancy/clients, `0003` CSRF) + idempotent `db/migrate.py` runner
- `docker/` — api/web Dockerfiles (runtime image omits dev dependencies); `docker-compose.yml` — postgres 16, redis 7 (single-node, dev-only durability), minio, api, worker, web
- `.github/workflows/ci.yml` — backend, integration (postgres+redis services, REQUIRE_SERVICES=1), frontend (`npm ci`), browser (Playwright + wire tests), security (fail-closed gate)

## Local development
Prerequisites: Docker + Compose, Python 3.12, Node 22.

```powershell
# 1. Start services (postgres, redis, minio)
docker compose up -d postgres redis minio

# 2. Backend (from repo root)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt
$env:DATABASE_URL = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
$env:REDIS_URL = "redis://localhost:6379/0"
python db/migrate.py
$env:PYTHONPATH = "apps/api"
python -m uvicorn app.main:app --app-dir apps/api --port 8000
# health: GET http://localhost:8000/api/v1/health

# 3. Worker (second shell, same venv; noop/echo kinds only)
$env:PYTHONPATH = "apps/api"
python -m worker.runner  # refuses production without durability approval (#35)

# 4. Frontend (third shell)
cd apps/web; npm ci; npm run dev
# open http://localhost:3000 (server-side API_INTERNAL_URL selects the backend;
# default http://127.0.0.1:8000 — use 127.0.0.1, not localhost, Node may try ::1)
```

## Status
`main` holds Sprint 0 + Sprint 1 (auth, tenancy, RBAC, CSRF, clients, audit). No tax/reconciliation/JUR domain code — JUR-01/02 stay blocked until the unified SRS is approved. See `docs/engineering/BLOCKERS.md` and Issues EP-01..EP-17. Synthetic data only; production gates (#35, #36, B-11, residency, repo privacy) remain open.
