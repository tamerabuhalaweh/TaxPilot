# P0 staging candidate (preparation only, nothing provisioned)

Status: **draft for approval; technical hold lifted only after independent review.**
This document defines the smallest secure connected synthetic demo we can stand
up for the founder and first firms. It contains no credentials or secret values,
and no deployment commands have been run. Do not purchase, provision, invite, or
deploy from this document until the Product Owner approves the exact
configuration and cost in §2 and GPT-6 reviews the corrected candidate. Resource
provisioning needs a separate, explicit approval after that review.

Candidate commit: `dfd6d60fbad0fb26111c8993d80e353313195dfb` (the PR #79 merge).
The guardrails, edge gate, and hosted-demo invariant in
`docs/engineering/HOSTED_DEMO_SECURITY.md` are the source of truth; this document
only fixes the resource shape and the order of operations.

## 1. Smallest defensible topology

| Layer | Provider | Shape | Why this is the minimum |
| --- | --- | --- | --- |
| Web | Vercel, existing `taxpilot-demo` project under Tamer Team | Preview scope only; Root Directory `apps/web`; Node `22.x`; Vercel Authentication on | already integrated; no new vendor or production deployment |
| API | Render Web Service (Docker) | one Starter instance, always-on, `docker/api.Dockerfile` | BFF timeout is 10s; a cold start makes the connected demo look broken |
| Database | Render PostgreSQL | one Basic 256 MB instance | isolated synthetic data; no shared local/staging DB |
| Queue/cache | Render Key Value | one Starter instance | API readiness and queue use Redis; no worker process |
| Worker | none | do not deploy | the synthetic demo runs the restricted path in-process; no background jobs are required |
| Object storage | none | do not deploy | uploads stay disabled and fail closed |
| DNS | none | use provider hostnames | no custom domain or certificate work in P0 |

No production resources, no production secrets, no production domain. P0 is a
protected connected synthetic demo, not a launch.

## 2. Exact configuration and cost to approve

All amounts are planning estimates, not quotes or incurred charges. They exclude
taxes, exchange-rate movement, overages, paid backups, additional seats, custom
domains, and provider price changes. Do not purchase or provision until the
Product Owner approves this exact shape.

| Resource | Exact configuration | Estimated incremental cost |
| --- | --- | --- |
| Render Web Service | name `taxpilot-demo-api`; Dockerfile `docker/api.Dockerfile`; context repository root; region Frankfurt; plan Starter; one instance; auto-deploy off; health check `/api/v1/health` | ~$7/month |
| Render PostgreSQL | name `taxpilot-demo-db`; region Frankfurt; PostgreSQL 16; plan Basic 256 MB; one instance; provider-default backups; no paid point-in-time recovery | ~$6/month |
| Render Key Value | name `taxpilot-demo-kv`; region Frankfurt; plan Starter; one instance; no public access beyond the API service | ~$10/month |
| Render subtotal | one API, one database, one Key Value instance | **~$23/month, estimates only** |
| Vercel | existing `taxpilot-demo` project under Tamer Team; Preview scope only; no production changes; no added seats | **$0 incremental while the existing Pro Trial is active** |
| Possible future Vercel subscription | only if the existing Pro Trial expires or is deliberately converted; list price is approximately $20/month | **separate future approval required** |
| Possible total after trial conversion | Render subtotal plus a paid Vercel subscription | **~$43/month, estimate only** |

The existing Vercel Pro Trial is **not** part of the new Render charge. Trial
expiration, conversion, seat changes, or any new Vercel subscription requires a
separate Product Owner decision; none is authorized by this document.

Capacity and backup assumptions:

- The single Starter API instance is sized for a founder/first-firm synthetic
  walkthrough, not load testing, production traffic, or high availability.
- The Basic 256 MB PostgreSQL plan and its provider-default backups are the only
  database durability assumed here. There is no paid point-in-time recovery,
  cross-region replica, or off-provider backup. Synthetic data may be recreated
  and reseeded if the instance is lost.
- Key Value is a single Starter instance with no high-availability guarantee.
- If the provider no longer offers these plans or prices, stop and return for
  approval rather than silently changing the resource shape.

**Approval requested:** provision one Render API Starter, one Render PostgreSQL
Basic 256 MB, and one Render Key Value Starter in Frankfurt for an estimated
~$23/month plus taxes; accept provider-default backup durability; accept that the
Vercel Pro Trial may expire and that any Vercel subscription conversion is a
separate future approval.

## 3. Identity, access, and protected environment

1. **Current Vercel destination.** Deployment metadata and the Product Owner's
   view identify the transferred project as:
   - project name: `taxpilot-demo`
   - team: **Tamer Team** / `tamer-team-cd02eeda`
   - project ID reported by Vercel: `prj_5ZxbiW9xZB63HbgLPcRpPTg6uvsV`
   - team ID reported by Vercel: `team_nIpi2Y66eFZ1HzQ7iCLr4byJ`
   - Root Directory: `apps/web`
   - current deployment state observed: Ready, frontend-only

   The historical personal-project name/ID or the older `tax-pilot` /
   `team_ip8tPEADGJu5JfdC4GFHyNuS` setup notes are not the current target. Treat
   them as superseded notes, not as an unresolved ownership mismatch.

2. **What is still unverified.** The transfer and a Ready frontend deployment do
   **not** prove connector, API, or environment correctness. Until an operator
   with Tamer Team access independently checks them, the following remain
   unverified:
   - project settings and GitHub connector permissions;
   - Preview environment variables and their scopes;
   - Deployment Protection configuration;
   - whether Preview is currently in `demo` or `connected` mode;
   - Node version and build/runtime settings;
   - the same-team access path needed to configure the connected environment.

   The protected candidate environment is the **Preview scope of this project
   under Tamer Team**, not Production. Anonymous access to the current preview
   already returns a Vercel SSO challenge, but that observation alone is not API
   or connector validation.

3. **Access method.** The Product Owner runs `vercel login` locally, or supplies a
   short-lived project-scoped `VERCEL_TOKEN` only as a local environment
   variable. The token is never pasted into chat, committed, or logged.

4. **Exact source commit.** Record the PR head to deploy. This document does not
   authorize a later head or a different branch.

5. **Review gate.** GPT-6 reviews this corrected document, then the Product Owner
   merges it and gives separate explicit approval for the budget and protected
   candidate provisioning.

## 4. Rollout order (PO or operator with provider access)

The order below is mandatory. The public-facing API must never serve traffic
against an unmigrated or unseeded schema. Stop on any unexpected result and
revoke rather than improvise.

1. **Approval gate.** Confirm the exact §2 configuration, the ~$23/month Render
   estimate, the Vercel Pro Trial risk, and the synthetic-only scope. Nothing
   below is authorized before this gate.

2. **Create database and Key Value first.** Confirm the Render account and
   approved billing, then create `taxpilot-demo-db` and `taxpilot-demo-kv` in
   Frankfurt with the exact plans above. Store connection strings only in the
   provider's secret store or a local password manager. Do not expose them in
   logs, chat, or git.

3. **Create the API service without live traffic.** Create
   `taxpilot-demo-api` from the exact candidate commit with auto-deploy off,
   health check `/api/v1/health`, and the hosted-demo environment from
   `docs/engineering/HOSTED_DEMO_SECURITY.md`.    Configure the pre-deploy command
   or a one-off job for migration before the first live instance. If the
   provider starts the service on creation, suspend the service immediately and
   resume it only after migration and seed succeed. Do not connect Vercel until
   then. Generate `API_EDGE_SECRET` out-of-band and store the same value in both
   providers.

4. **Migrate before first start.** Run `python db/migrate.py` against the demo
   database as a one-off Render Job using the API image, or as the API service's
   pre-deploy command if the provider guarantees it completes before any live
   instance receives traffic. A deploy that can serve requests while migrations
   are still running is a failed gate. Do not proceed until migration reports
   success. Do not send the API any user traffic before this succeeds.

5. **Seed synthetic access before first start.** Run
   `apps/api/scripts/seed_staging.py` as a one-off job against the same demo
   database with `ENVIRONMENT=staging` and `SEED_OUT_FILE` pointing at an
   ACL-restricted local file. The seed creates one synthetic firm, synthetic
   users, and synthetic clients; it must refuse reruns once accounts exist.
   Never print passwords to provider logs. Rotate the generated passwords after
   the first login. Start live API traffic only after the seed job reports
   success.

6. **Start the API and verify the boundary.** Start the API only after migration
   and seed succeed. Verify `/api/v1/health` returns `ok`; verify every other API
   route without `X-TaxPilot-Edge` returns 403; verify a client-supplied edge
   header is dropped by the BFF. Do not configure the frontend yet if any check
   fails.

7. **Configure Vercel Preview, not Production.** In the verified `taxpilot-demo`
   project under Tamer Team, Preview scope only, set
   `API_INTERNAL_URL=https://<render-demo-api-host>`,
   `API_EDGE_SECRET=<same generated value>`, and
   `NEXT_PUBLIC_PREVIEW_MODE` unset or `connected`. Do not set any
   `NEXT_PUBLIC_` secret. Leave `CORS_ALLOWED_ORIGINS` unset or set it to the
   exact preview origin; never `*`. Production scope remains untouched.

8. **Deploy the frontend candidate and verify protection.** Deploy the recorded
   candidate commit to Preview. Confirm Vercel Authentication is on, and verify
   in a logged-out private window that anonymous access is blocked. Keep
   protection on for the lifetime of the demo.

9. **First-traffic acceptance, operator only.** Using the seeded synthetic
   account, verify login/logout/CSRF, the automated tenant-isolation suite, the
   synthetic run, findings, PDF/XLSX exports bound to the displayed run, Arabic
   RTL, mobile layout, the persistent synthetic banner, session expiry, and
   revocation. If a second synthetic tenant is created for a manual check, it
   must not be able to read or mutate the first tenant. Record results in the P0
   handoff file, not in git. Only after this gate may the founder personally use
   the protected HTTPS URL.

10. **Invitation gate.** No firm or customer invitation is allowed by this
    document, even after founder acceptance. First-firm access requires a
    separate Product Owner approval.

## 5. Pre-invite verification

Run every check before the PO or a firm is invited:

- `GET /api/v1/health` is public and returns `ok`.
- Every other API route without `X-TaxPilot-Edge` returns 403.
- The BFF adds the edge header server-side and drops a client-supplied copy.
- Registration returns 403; login, logout, and CSRF work.
- The tenant-isolation suite passes; if a second synthetic tenant/user is
  created for a manual check, it cannot read or mutate the first tenant's
  clients or reviews.
- Uploads fail closed; no real-data path is reachable.
- The synthetic run, findings, and PDF/XLSX exports match the displayed run.
- Arabic/RTL, mobile layout, and the persistent synthetic banner render.
- Anonymous access to the preview URL is blocked by Vercel Authentication.
- The 24-hour session expiry and revocation steps are understood.
- Migration and seed completed before the API accepted the first request.

Record the results in the P0 handoff file, not in git.

## 6. Revocation

Remove Vercel access, delete the preview deployment, rotate or delete the edge
secret, delete the Render API/PostgreSQL/Key Value resources, and let sessions
expire. There is no app-level password-rotation endpoint. If the trial expires or
billing approval is withdrawn, revoke access and delete resources rather than
assuming they remain available. Revocation is part of the candidate, not a
follow-up.

## 7. Explicitly out of scope

- Production Vercel deployment, production API, production database, or any
  production secret.
- Real customer records, uploads, filings, or financial processing.
- Custom domains, TLS/HSTS work, WAF, DDoS protection, or email delivery.
- Background workers, object storage, paid point-in-time recovery, backups beyond
  the provider default, or multi-region failover.
- Any change to source-release gates, financial math, or migrations beyond
  running the existing migration script.
