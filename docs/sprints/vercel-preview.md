# Vercel preview + staging — setup, contracts, walkthrough

**Scope:** visual UI review and connected staging validation. No production deployment, no customer data, no financial processing. PR #39 (JUR plan) untouched.

## 0. Verified Vercel state (2026-10-12, agent-checked)

- Project **`tax-pilot`** exists with **Root Directory `apps/web`**; GitHub integration posts deployment statuses + preview comments to PRs (verified on PR #40).
- Production domain `tax-pilot-five.vercel.app` serves `main` with NO environment variables: it shows the connected-mode UI with backend-unreachable states. That is expected (no backend is hosted) — it is not the visual preview.
- The PR preview deployment for `feature/ui-preview-milestone` completed successfully AND serves Vercel's login wall to anonymous visitors: **Deployment Protection is ON**.
- Still required (dashboard actions, §1): commercial plan decision, `NEXT_PUBLIC_PREVIEW_MODE=demo` on the **Preview** environment, then redeploy the PR branch.

## 1. Vercel project setup (Product Owner actions — require dashboard/admin access)

The agent cannot perform these; they need a Vercel account owner:

1. **Upgrade from Hobby to Pro before any commercial use.** Vercel Authentication can protect all deployments, including production, on every plan — but Hobby is non-commercial per the Vercel plans documentation, so commercial TaxPilot deployment should use Pro. Do not publish anything sensitive before the plan and protection are in place.
2. **Install the Vercel GitHub App** on `tamerabuhalaweh/TaxPilot` ✅ DONE (deployment statuses + preview comments appear on PRs; Actions checks preserved).
3. **Import project** ✅ DONE except Node version: framework Next.js, **Root Directory = `apps/web`**. **Set Project → Settings → General → Node.js Version to `22.x`** to match the `engines` pin in `apps/web/package.json` (the project currently shows `24.x`; CI tests `22.x`, so align to avoid build/runtime drift). No `vercel.json` is committed on purpose — dashboard settings are the single source of truth for the monorepo root.
4. **Environment variables** (Vercel dashboard → Project → Settings → Environment Variables; never in git) — OPEN, blocks the visual preview:
   - Preview scope: `NEXT_PUBLIC_PREVIEW_MODE=demo` (visual walkthrough, no backend needed). Do NOT set `API_INTERNAL_URL` for the visual-only demo.
   - Preview scope (connected staging, once §3 exists): `NEXT_PUBLIC_PREVIEW_MODE=connected` (or unset), `API_INTERNAL_URL=https://<staging-api-host>` (server-side only, never `NEXT_PUBLIC_`).
   - Production scope: **do not deploy production until** Deployment Protection is on, the staging backend of §3 is approved, and secrets are set (no values in this repo).
   - After saving, **Redeploy** the PR branch (Deployments → ⋯ → Redeploy): env vars bake in at build time and do not retro-apply. Any fresh push also redeploys.
5. **Deployment Protection** (Vercel Authentication) ✅ VERIFIED ON for the PR preview (anonymous visitors receive Vercel's login wall). Keep it on for Preview and future Production; re-verify in a logged-out private window after any project change.

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
- **Seeded synthetic access:** `python apps/api/scripts/seed_staging.py` (this repo) creates one synthetic firm, two verified users (owner + accountant), and two synthetic clients. It runs ONLY with `ENVIRONMENT=staging`, refuses reruns once seeded accounts exist, and writes random passwords ONLY to the file named by `SEED_OUT_FILE` (created 0600) — never to stdout, since providers retain logs. Rotate after first login. No real names, no customer data, no committed credentials. Run exclusively against the staging database URL.
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

- All GitHub Actions jobs green at the PR head (backend, docs, frontend, integration, browser, browser-demo, security; Vercel deployment statuses appear additionally once the GitHub App is installed).
- Playwright suite green (auth journey + proxy wire tests run against connected local stack in CI).
- Screenshots below (`docs/sprints/ui-milestone-1/`, demo build, JPEG): dashboard/clients/new-review EN+AR, desktop (1280) + mobile (390).
  - `dashboard-en-desktop.jpg`, `dashboard-en-mobile.jpg`, `dashboard-ar-desktop.jpg`
  - `clients-en-desktop.jpg`, `clients-ar-mobile.jpg`, `client-detail-en-desktop.jpg`
  - `new-review-en-desktop.jpg`, `new-review-ar-desktop.jpg`, `login-en-desktop.jpg`
