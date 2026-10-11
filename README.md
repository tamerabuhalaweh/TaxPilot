# TaxPilot Jordan

AI-assisted tax reconciliation and financial review platform for Jordanian accounting firms.

**Authoritative spec:** [`docs/product/TAXPILOT_MASTER_SRS_V1.1.md`](docs/product/TAXPILOT_MASTER_SRS_V1.1.md) (SRS v1.1, reconciliation-first baseline — pending PO approval via PR).

**Superseded:** SRS v1.0 `.docx` retained under `docs/product/superseded/` for change history. Do not build new scope from v1.0 alone.

## Product promise (v1.1)
Sign in → Select/create client → Start tax review → Upload Sales Register + JoFotara Export + GL → Confirm mappings → Run reconciliation (REC-001..005) → Investigate → Record decisions → Bilingual PDF/XLSX report.

- Reconciliation-first, accountant-focused. Deterministic engine calculates; AI assists; accountants decide.
- File-based JoFotara import in MVP. No government API integration, no portal credentials.
- Arabic/English + RTL. Light-mode-first, one primary action per screen.
- Strict tenant isolation, versioned rules, evidence traceability, expert-gated tax conclusions.

## Repo map
- `docs/product/` — SRS v1.1 (PR #15, pending approval), jurisdiction amendment (PR #32) + review corrections (PR #33), UX flows, golden-test plans
- `docs/architecture/` — ADRs and review-correction records
- `docs/sprints/` — sprint implementation notes; `docs/engineering/BLOCKERS.md` — visible blocker register
- `apps/api/` — FastAPI (`/api/v1/health`, `/ready`, error envelope, correlation IDs, env config, redacted JSON logs) + `worker/` (job queue: Redis with honest memory fallback) + `tests/`
- `apps/web/` — Next.js 14 + strict TS + EN/AR + RTL + design tokens + typed API client (dashboard stub, no mock data)
- `db/migrations/` — versioned SQL + `db/migrate.py` runner
- `docker/` — api/web Dockerfiles; `docker-compose.yml` — postgres, redis, minio, api, worker, web
- `.github/workflows/ci.yml` — backend, integration (services), frontend, security checks

## Local development (Sprint 0 foundation)
Prerequisites: Docker + Compose, Python 3.12, Node 22.

```powershell
# 1. Start services (postgres, redis, minio)
docker compose up -d postgres redis minio

# 2. Backend (from repo root)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt
$env:DATABASE_URL = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
python db/migrate.py
uvicorn app.main:app --app-dir apps/api --port 8000
# health: GET http://localhost:8000/api/v1/health

# 3. Worker (second shell, same venv)
python -m worker.runner  # cwd apps/api; noop/echo kinds only in Sprint 0

# 4. Frontend (third shell)
cd apps/web; npm install; npm run dev
# open http://localhost:3000 (set NEXT_PUBLIC_API_BASE to reach the API)
```

## Status
Sprint 0 foundation on `feature/sprint-00-foundation` (PR pending). No tax/reconciliation/JUR domain code yet — those need PO approval of PR #15 + #32/#33. See GitHub Issues EP-01..EP-17 and `docs/engineering/BLOCKERS.md`.
