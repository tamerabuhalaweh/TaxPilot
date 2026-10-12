# Vercel preview + staging — setup, contracts, walkthrough

**Scope:** visual UI review and connected staging validation. No production deployment, no customer data, no financial processing. PR #39 (JUR plan) untouched.

## 1. Vercel project setup (Product Owner actions — require dashboard/admin access)

The agent cannot perform these; they need a Vercel account owner:

1. **Upgrade from Hobby to a commercial plan** (Standard or higher) BEFORE any deployment carrying real-looking auth flows. Hobby preview URLs rely on obscurity alone; Deployment Protection (Vercel Authentication / password / SSO) requires a paid plan.
2. **Install the Vercel GitHub App** on `tamerabuhalaweh/TaxPilot` (Vercel dashboard → Add GitHub account → select repository). This posts preview URLs + commit SHA + deployment status to every frontend PR and preserves the six GitHub Actions checks (Vercel does not replace CI).
3. **Import project:** framework preset Next.js, **Root Directory = `apps/web`**, Node.js `22.x` (pinned in `apps/web/package.json` engines), build command default (`npm run build`), output default (`.next`). No `vercel.json` is committed on purpose — dashboard settings are the single source of truth for the monorepo root.
4. **Environment variables** (Vercel dashboard → Project → Settings → Environment Variables; never in git):
   - Preview scope: `NEXT_PUBLIC_PREVIEW_MODE=demo` (visual walkthrough, no backend needed).
   - Preview scope (connected staging, once §3 exists): `NEXT_PUBLIC_PREVIEW_MODE=connected` (or unset), `API_INTERNAL_URL=https://<staging-api-host>` (server-side only, never `NEXT_PUBLIC_`).
   - Production scope: **do not deploy production until** Deployment Protection is on, the staging backend of §3 is approved, and secrets are set (no values in this repo).
5. **Enable Deployment Protection** on Preview (and later Production) deployments so nothing is publicly reachable without authentication.

## 2. Preview modes (build-time contract, `apps/web/lib/preview.ts`)

| Mode | Flag | Backend needed | Auth | Data |
|---|---|---|---|---|
| `demo` (default for Vercel Preview) | `NEXT_PUBLIC_PREVIEW_MODE=demo` | No | Disabled with notice; Explore-demo entry | Synthetic fixtures, persistent demo banner, preview-only/coming-soon states only. No financial processing simulated. |
| `connected` (default; local + staging) | unset or `connected` | Yes (`API_INTERNAL_URL`) | Real login/register/sessions/CSRF | Real API data only. |

Because `NEXT_PUBLIC_*` bakes in at build time, switching modes requires a rebuild/redeploy — Vercel does this automatically per environment scope above.

## 3. Connected staging proposal (decision required, nothing provisioned)

Assumed constraint: FastAPI is NOT publicly reachable today. Recommended arrangement (cheap, separated from production which does not exist yet):

- **API + worker:** one Flynn/Render/Fly-style container host running the existing `docker/api.Dockerfile` image (API service) plus a second process entry for `worker.runner`. Alternative single-host Docker Compose on a small VPS (simplest, ~$6–12/mo): reuse `docker-compose.yml` minus minio exposure.
- **PostgreSQL:** managed instance (e.g. Neon/Supabase/Render Postgres) with encrypted backups on; app connects via `DATABASE_URL`.
- **Redis:** managed instance (e.g. Upstash/Render Key-Value) via `REDIS_URL`.
- **Staging env (all server-side, never committed):** `ENVIRONMENT=staging`, `DATABASE_URL`, `REDIS_URL`, `API_INTERNAL_URL` (on Vercel), `CORS_ALLOWED_ORIGINS=https://<staging-web-host>`, `AUTH_EXPOSE_TOKENS` unset (forced off outside development), `JOBS_DURABILITY_APPROVED` unset (queue stays dev-grade).
- **TLS:** terminate at host/proxy (HTTPS only); `Secure` cookies automatic outside development.
- **Seeded synthetic access:** `python apps/api/scripts/seed_staging.py` (this repo) creates one synthetic firm, two verified users (owner + accountant), and two synthetic clients; random passwords are printed ONCE to the operator console and must be rotated after first login. No real names, no customer data, no committed credentials. Run exclusively against the staging database URL.
- **Isolation:** separate database, separate Redis DB/index, separate domain; no production counterpart exists — do not reuse any production secret if one is ever created.

## 4. What is functional vs preview-only (Sprint 1 + UI milestone state)

Functional (connected mode, tested): register/verify/login/logout, sessions + CSRF, tenant switch, invitations, RBAC, client list/create/detail-read, health/readiness, rate limits, audit trail.
Preview-only (honest markers, no backend): review list/detail content, document upload/mapping/reconciliation/findings/reports tabs, New Review run action, dashboard review statistics (demo fixtures), reports/settings pages, AE/SA anything.
Never simulated: reconciliation outcomes, financial figures as results, tax conclusions, government integration.

## 5. Walkthrough for the Product Owner (demo preview URL)

1. Open the preview URL → Dashboard shows the demo banner, firm overview, client table, and review list (all synthetic).
2. Use English / العربية toggle (top right of every page) — layout flips to RTL, strings translate, invoice-style identifiers keep logical direction.
3. Clients → search filters the table → Open → client workspace with Profile/Reviews/Documents/Findings/Reports tabs (preview-only states).
4. Reviews → New Review → pick client + period + review type → three source cards (Sales Register, JoFotara Excel Export, General Ledger) → Start Review is disabled with an honest coming-soon note.
5. Reports / Settings → preview-only markers.
6. Login page in demo shows auth-disabled notice (no accounts exist in demo; no verification codes anywhere).
7. Resize to 390px width — grids collapse, tables scroll horizontally with visible content.

## 6. Verification evidence expected on the PR

- Six GitHub Actions checks green at the PR head (Vercel deployment statuses appear additionally once the GitHub App is installed).
- Playwright suite green (auth journey + proxy wire tests run against connected local stack in CI).
- Screenshots below (`docs/sprints/ui-milestone-1/`, demo build, JPEG): dashboard/clients/new-review EN+AR, desktop (1280) + mobile (390).
  - `dashboard-en-desktop.jpg`, `dashboard-en-mobile.jpg`, `dashboard-ar-desktop.jpg`
  - `clients-en-desktop.jpg`, `clients-ar-mobile.jpg`, `client-detail-en-desktop.jpg`
  - `new-review-en-desktop.jpg`, `new-review-ar-desktop.jpg`, `login-en-desktop.jpg`
