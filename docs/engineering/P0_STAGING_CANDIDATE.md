# P0 staging candidate (preparation only, nothing provisioned)

Status: **draft for approval.** This document defines the smallest secure connected
synthetic demo we can stand up for the founder and first firms. It contains no
credentials, no resource identifiers, and no deployment commands that have been
run. Do not purchase, provision, invite, or deploy from this document until the
Product Owner approves the cost and Vercel access, and GPT-6 reviews the
candidate.

Candidate commit: `dfd6d60fbad0fb26111c8993d80e353313195dfb` (the PR #79 merge).
The guardrails, edge gate, and hosted-demo invariant in
`docs/engineering/HOSTED_DEMO_SECURITY.md` are the source of truth; this document
only fixes the resource shape and the order of operations.

## 1. Smallest defensible topology

| Layer | Provider | Shape | Why this is the minimum |
| --- | --- | --- | --- |
| Web | Vercel (existing project, Preview scope) | existing Hobby/Pro project, Root Directory `apps/web`, Node `22.x` | already integrated; no new vendor |
| API | Render Web Service (Docker) | Starter, always-on, `docker/api.Dockerfile` | BFF timeout is 10s; a cold start makes the connected demo look broken |
| Database | Render PostgreSQL | Basic 256 MB, dedicated instance | isolated synthetic data; no shared local/staging DB |
| Queue/cache | Render Key Value | Starter, dedicated instance | API readiness and queue use Redis; no worker process |
| Worker | none | do not deploy | the synthetic demo runs the restricted path in-process; no background jobs are required |
| Object storage | none | do not deploy | uploads stay disabled and fail closed |
| DNS | none | use provider hostnames | no custom domain or certificate work in P0 |

No production resources, no production secrets, no production domain. P0 is a
protected connected synthetic demo, not a launch.

## 2. Cost to approve (list prices at time of writing)

| Resource | Plan | Monthly |
| --- | --- | --- |
| Render Web Service | Starter, always-on | ~$7 |
| Render PostgreSQL | Basic 256 MB | ~$6 |
| Render Key Value | Starter | ~$10 |
| Vercel Pro | optional; only if a non-commercial plan is not acceptable for the protected demo | ~$20 |
| Total | with existing Vercel plan | **~$23/month** |
| Total | with Vercel Pro | **~$43/month** |

Taxes, exchange rates, and provider price changes are not included. If the PO
wants a lower number, the only real lever is a short-lived demo window; the API
cannot go to sleep without degrading the connected demo.

## 3. Preconditions (all must be true before provisioning)

1. Product Owner approves the monthly cost and the synthetic-only scope.
2. Vercel identity is reconciled. The PR check reports
   `taxpilot-demo` / `prj_5ZxbiW9xZB63HbgLPcRpPTg6uvsV` under
   `tamer-team-cd02eeda` / `team_nIpi2Y66eFZ1HzQ7iCLr4byJ`, while the setup
   notes name `tax-pilot` / `team_ip8tPEADGJu5JfdC4GFHyNuS`. Configure the
   project that actually owns the preview URL, or fix the notes.
3. Access method is chosen: the PO runs `vercel login` locally, or supplies a
   short-lived project-scoped `VERCEL_TOKEN` only as a local environment variable.
   The token is never pasted into chat, committed, or logged.
4. The exact PR head to deploy is recorded. This document does not authorize a
   later head.
5. GPT-6 has reviewed this candidate and the UI PR that follows it.

## 4. Provisioning order (PO or operator with provider access)

Do these in order. Stop if any step's result differs from the expected value.

1. **Render account and billing.** Confirm the account region closest to Amman
   (Frankfurt) and add the approved payment method.
2. **Render PostgreSQL.** Create one instance: name `taxpilot-demo-db`,
   region Frankfurt, plan Basic 256 MB, PostgreSQL 16. Keep backups at the
   provider default. Record only the internal connection string into a local
   password manager; do not paste it anywhere else.
3. **Render Key Value.** Create one instance: name `taxpilot-demo-kv`, region
   Frankfurt, plan Starter, no public IP allow-list entry beyond the API
   service. Record the connection string locally.
4. **Render Web Service.** Create a Docker web service from
   `tamerabuhalaweh/TaxPilot` at the candidate commit, Dockerfile
   `docker/api.Dockerfile`, context repository root, region Frankfurt, plan
   Starter, health check path `/api/v1/health`, auto-deploy off.
   Add a pre-deploy command only after confirming migrations are safe to run on
   every release (`python /srv/db/migrate.py`), otherwise run migrations once by
   hand and keep auto-deploy off.
5. **Render environment.** Set the hosted-demo variables from
   `docs/engineering/HOSTED_DEMO_SECURITY.md`. Generate the edge secret
   out-of-band with
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store the
   same value in both providers' secret stores. `CORS_ALLOWED_ORIGINS` stays
   unset or set to the exact Vercel preview origin once known; never use `*`.
   Leave `AUTH_EXPOSE_TOKENS` unset.
6. **Vercel Preview environment.** On the resolved project, Preview scope only:
   `API_INTERNAL_URL=https://<render-demo-api-host>`,
   `API_EDGE_SECRET=<same generated value>`, `NEXT_PUBLIC_PREVIEW_MODE` unset or
   `connected`. Do not set any `NEXT_PUBLIC_` secret. Production scope is not
   touched.
7. **Vercel Deployment Protection.** Confirm Vercel Authentication is on for
   Preview and verify it in a logged-out private window. Keep it on for the
   lifetime of the demo.
8. **First deploy.** Deploy the candidate commit, then run migrations against the
   demo database only.
9. **Seed synthetic access.** Run the staging seed script against the demo
   database only, with `ENVIRONMENT=staging` and `SEED_OUT_FILE` pointing at an
   ACL-restricted local file. The script refuses to rerun once accounts exist.
   Rotate the generated passwords after the first login. Keep the file and the
   review URL outside the repository.

## 5. Pre-invite verification

Run every check before the PO or a firm is invited:

- `GET /api/v1/health` is public and returns `ok`.
- Every other API route without `X-TaxPilot-Edge` returns 403.
- The BFF adds the edge header server-side and drops a client-supplied copy.
- Registration returns 403; login, logout, and CSRF work; tenant isolation holds.
- Uploads fail closed; no real data path is reachable.
- The synthetic run, findings, and PDF/XLSX exports match the displayed run.
- Arabic/RTL, mobile layout, and the persistent synthetic banner render.
- Anonymous access to the preview URL is blocked by Vercel Authentication.
- The 24-hour session expiry and revocation steps are understood.

Record the results in the P0 handoff file, not in git.

## 6. Revocation

Remove Vercel access, delete the preview deployment, rotate or delete the edge
secret, delete the Render API/PostgreSQL/Key Value resources, and let sessions
expire. There is no app-level password-rotation endpoint. Revocation is part of
the candidate, not a follow-up.

## 7. Explicitly out of scope

- Production Vercel deployment, production API, production database, or any
  production secret.
- Real customer records, uploads, filings, or financial processing.
- Custom domains, TLS/HSTS work, WAF, DDoS protection, or email delivery.
- Background workers, object storage, backups beyond the provider default, or
  multi-region failover.
- Any change to source-release gates, financial math, or migrations beyond
  running the existing migration script.
