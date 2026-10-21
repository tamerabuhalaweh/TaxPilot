# Hosted synthetic demo security boundary

Status: implementation guardrails only. No hosted API, database, Redis, or connected candidate exists yet.

## Scope

This describes the P0 connected demo for the founder and first firms. It is synthetic-only, staging-only, and must never process real customer records, uploads, filings, or production data.

## Trust boundaries

- **Vercel edge:** The frontend stays behind Vercel Authentication over HTTPS. Only named founder/operator accounts receive project access. This is the outer user gate, not API authorization.
- **BFF:** The browser calls same-origin `/api/v1/*` on the Vercel host. The Next.js route handler forwards server-side to the announced `API_INTERNAL_URL` using HTTPS. The backend origin comes only from server env.
- **API edge gate:** When `API_EDGE_SECRET` is set, every FastAPI route except `GET /api/v1/health` requires `X-TaxPilot-Edge`. The BFF adds the header server-side; client-supplied copies are dropped by the header allowlist. `/health` is also public for the host probe.
- **Application authorization:** Per-firm sessions, CSRF/Origin checks, tenant isolation, and role checks remain the real user authorization boundary. The edge secret is only a shared server-to-server gate.
- **Data:** Dedicated synthetic PostgreSQL and Redis/Key Value resources. No production data, backups beyond the demo window, or shared local database.

`API_EDGE_SECRET` is **not** end-user authentication, a WAF, DDoS protection, or a substitute for Vercel deployment protection. It does not make the frontend connected by itself; the API, PostgreSQL, and Redis must be running and reachable.

## Fail-closed startup invariant

When `TAXPILOT_DEMO_RECON_ENABLED=1` outside local `development`/`test`, startup refuses configuration that is not safe for a hosted demo:

- `ALLOW_PUBLIC_REGISTRATION=false` is required.
- `AUTH_EXPOSE_TOKENS` must be unset or false.
- `API_EDGE_SECRET` is required and must be 64-128 URL-safe characters with reasonable character diversity.
- Production continues to force `demo_recon_enabled=false`, regardless of input.

Local development/test defaults are unchanged: demo mode may be enabled without these hosted settings.

The shape check rejects obvious mistakes; it is not proof of entropy. Operators must generate the secret out-of-band and inject it through provider secrets:

```text
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use the same value on the Render API and Vercel Preview, never a `NEXT_PUBLIC_*` variable. Do not commit, print, or log it. Configuration errors hide input values and the secret is held as `SecretStr`.

## Required hosted names (values are provider secrets)

Render API:

```text
ENVIRONMENT=staging
DATABASE_URL=<isolated demo postgres>
REDIS_URL=<isolated demo key value>
CORS_ALLOWED_ORIGINS=<exact Vercel preview origin>
TAXPILOT_DEMO_RECON_ENABLED=1
ALLOW_PUBLIC_REGISTRATION=false
API_EDGE_SECRET=<generated 64-128 URL-safe chars>
AUTH_EXPOSE_TOKENS unset
```

Vercel Preview only:

```text
API_INTERNAL_URL=https://<render-demo-api>
API_EDGE_SECRET=<same generated value>
NEXT_PUBLIC_PREVIEW_MODE unset or connected
```

Node `22.x` is required for the web build. Production Vercel env and production API/database settings remain untouched.

## Accounts, seeding, and revocation

- Public registration is closed on the hosted API.
- Seed one synthetic firm, one founder/operator account, and two synthetic clients with `apps/api/scripts/seed_staging.py`; create the demo review through the UI.
- Keep generated passwords and review URLs outside the repository in an ACL-restricted local file.
- No developer credentials in the demo, screenshots, logs, or GitHub.
- Revocation: remove Vercel access, delete/disable the preview deployment, rotate/delete the edge secret, delete the demo API/PostgreSQL/Redis resources, and let the 24-hour session expire. There is no app-level password-rotation endpoint.

## Pre-invite checks

- Anonymous access to `/` and `/api/v1/health` on the preview is blocked by Vercel Authentication.
- Direct API access without the edge header returns 403; `/api/v1/health` remains public.
- Registration returns 403; login/logout and CSRF work; tenant isolation is verified.
- Uploads fail closed; no real data or production credentials are reachable.
- PDF/XLSX match the displayed synthetic run; Arabic/RTL and mobile are verified.
- Revocation removes access and invalidates the demo account/session.
- No customer invitation until the protected connected candidate passes these checks and GPT-6/PO approval.
