# EP-04C Execution Plan (PROPOSED — no code authorized yet)

> Companion to `docs/architecture/EP04C_SECURITY_ARCHITECTURE.md` (design) and
> `docs/product/EP04C_DECISION_REGISTER.md` (PO/legal/cloud approvals). All PRs
> below are PROPOSED; each needs its own PO GO + GPT-6 review. Production stays
> forbidden until every gate in §6 passes.

## 0. Grounded starting point (exact `main@6c33a7c`)

Shipped and tested: auth/tenancy/RBAC/CSRF, exact finance (`app/finance`),
bounded extraction (`app/extraction`), mapping/normalization (`app/normalization`),
authenticated intake + local quarantine + immutable intake metadata + idempotency
(`app/routers/intakes.py`, `app/quarantine.py`, migration 0005), dev-only fenced
queue (`apps/api/worker/`), BFF allowlist proxy (1 MiB JSON path), fail-closed CI.
Missing: everything in §2 — durable jobs, upload-capable proxy, approved store/
KMS/region, scanner + release evidence, retention mechanics.

## 1. Build order (dependency-ordered, non-overlapping)

Canonical migration numbering (mirrored in the security architecture doc):
**0006 = EP-04C1 durable jobs/outbox; 0007 = EP-04C4 scan verdicts/release.**
Neither file exists until its PR is approved — and every PR kickoff must
recheck numbering and main HEAD so no worker ever creates a competing 0006.

### EP-04C1 — Durable PostgreSQL jobs + recovery (#35)
Scope: `extraction_jobs` table + migration 0006 (states, attempts, fencing
owner/expiry, idempotency key, payload hash, terminal error; CHECKs; tenant
indexes); claim/heartbeat/settle DAO with single-statement atomicity (same Lua
discipline as `worker/jobs.py`, now in SQL); Redis wakeups-only (ID lists, loss
= delay); sweeper (stale requeue, max-attempts dead-letter); outbox rows for
scan→release→extract handoffs; `/ready` + depth/age metrics; runbook.
Files: `db/migrations/versions/0006_extraction_jobs.sql` + CHECKSUMS,
`apps/api/app/jobs/` (new), `worker/` runner reuse, `tests/integration/test_ep04c1_jobs.py`.
No provider/region/legal decisions required — **recommended first coding PR**.
Estimate: 4–6 focused days.
Tests: kill claimant mid-run → recovery; slow heartbeat prevents theft; stale
finish rejected; concurrent recovery single-claim; two crashes → terminal;
Redis restart loses nothing (jobs in PG); duplicate delivery idempotent at
effects boundary; tenant-scoped idempotency (no cross-tenant coupling).
Rollback: migration additive; runner refuses prod until `#35` closes (keep gate).
Gate to close #35: all above + metrics/alerts + PO/security review.

### EP-04C2 — Secure BFF streaming + proxy hardening (#36)
Scope: 25 MiB upload path in `apps/web/lib/proxy.ts` + route handler (bounded
streaming, per-route caps, deadline ladder auth-vs-upload, cancellation,
correlation passthrough), edge spray-limit policy (config, off by default),
negative wire tests (chunked oversize, slow streams, forged headers, CSRF).
Files: `apps/web/lib/proxy.ts`, route handler, `apps/web/e2e/proxy-upload.spec.ts`.
No provider decisions required.
Estimate: 3–4 days.
Tests: 2 MiB JSON still 413; 25 MiB upload streams without buffering; missing
length capped; `x-forwarded-*` ignored; CSRF/origin enforced; cancellation
propagates; timeouts differentiated.
Rollback: revert to 1 MiB-only proxy (uploads stay API-only).

### EP-04C3 — Approved object-store adapter + encryption controls
Scope (only after storage/region/KMS decisions): S3-compatible adapter behind
the `quarantine.py` interface (put/get-lease/delete/exists, multipart for
>100 MB later), SSE-KMS envelope keys, key rotation schedule, private bucket
policy (Block Public Access, TLS-only, region-pinned endpoint), tenant-scoped
IAM roles, versioning + backup replication, staging drill.
Files: `apps/api/app/objectstore/` (new), config + migration for key metadata
as needed, `tests/integration/test_ep04c3_store.py` (real bucket in CI sandbox).
Estimate: 4–6 days + provider provisioning.
Tests: cross-tenant GetObject denied; public ACL blocked; wrong-region endpoint
refused; rotation keeps decrypting old backups; outage → 503 without data loss.
Rollback: readiness gate flips back to local-only; uploads 503 in prod.

### EP-04C4 — Malware scanning + append-only release + gated extraction
Scope (only after scanner decision): `scan_verdicts` + `release_authorizations`
append-only tables (migration 0007 PROPOSED: intake FK, sha + object-version
binding, provider-aware evidence per architecture §4.1 — engine/signature
version recorded only when supplied, else `not exposed by vendor`, never
fabricated); scanner worker (GuardDuty EventBridge consumer OR ClamAV daemon —
per decision); TBAC-style deny-unless-`NO_THREATS_FOUND`; hash re-verification
at release AND at extraction start; re-scan on engine/policy change; audit
`scan.received/verdict/released/expired`.
Files: migration 0007, `apps/api/app/scan/` (new), worker handler, release
checks in C1 job execution path.
Estimate: 5–8 days.
Tests (attacker matrix §3): EICAR-style fixture infected → INFECTED, never
released; forged event (unknown source / failed transport auth) refused;
replayed verdict (same EventBridge event ID delivered twice) single-effect;
swapped object version (verdict for v1 presented against v2 bytes) refused;
UNSUPPORTED/FAILED/TIMEOUT never clean; expired release refused; concurrent
reprocess single-release; revoked policy re-scans.
Rollback: releases stop issuing; quarantine stays closed.

### EP-04C5 — Retention/deletion + operations + release drills
Scope (only after DEC-02 periods + legal authority): tombstone flow, legal-hold
flags, erasure manifest worker (originals → derived → keys → backups), backup
expiry proof, restore drill (RPO ≤24 h / RTO ≤8 h evidence), ops runbooks,
pre-prod security review checklist, paid-pilot onboarding gate.
Estimate: 4–6 days + drill windows.
Tests: hold blocks sweep; manifest completes all classes; backup restore into
sandbox verifies hashes; expired backup absence proven.
Rollback: holds remain; sweeps pause.

## 2. Unblocked-now vs provider-blocked work

Unblocked now (no external decisions): C1 (PG+Redis already in CI), C2 (code +
tests only). Blocked on decisions: C3 (provider/region/KMS), C4 (scanner +
verdict trust), C5 (DEC-02 periods + legal authority + backup targets).

## 3. Attacker-test matrix (all PRs; fail-closed assertions)

| Attack | Expected | Owner PR |
|---|---|---|
| Malicious file (EICAR-style, polyglot, bomb) | Refused/quarantined, never extracted | C4 (intake guards already: EP-04A) |
| Fake scan-clean / forged event / replayed verdict / swapped object version | Refused (single-effect on replay), audited | C4 |
| Missing/untrusted/expired verdict | Refused, no extraction | C4 |
| Swapped object hash post-verdict | Refused at release + at job start | C4 |
| Concurrent reprocess / duplicate delivery | Single effect (idempotency keys) | C1 |
| Cross-tenant IDOR / signed-URL scope escape | 404/deny, no leak | C1/C2/C4 |
| Stale worker completes after reclaim | Rejected (fencing token) | C1 |
| Redis crash/restart mid-flight | Jobs intact (PG), wakeups delayed only | C1 |
| DB commit-ack loss (job row) | Outbox + sweeper reconcile, no double effect | C1 |
| Orphan blob / missing object at job start | Job fails safe, blob swept, audited | C1/C3 |
| Oversized/slow proxy streams | 413/timeout, backend untouched | C2 |
| Key rotation / storage outage | Old backups decrypt; 503 without loss | C3 |
| Retention expiry / legal hold | Sweep or block per manifest; proof | C5 |
| Backup restore | Hash-verified restore in sandbox | C5 |

## 4. CI per PR

Full backend unit + integration on real PG/Redis (disposable DBs, REQUIRE_SERVICES=1
fail-closed), ruff + mypy clean, security gate green, no mock-only claims for
queue/lease/recovery semantics (concurrency + crash tests are mandatory), docs
updated, DRAFT PR + GPT-6 review + PO GO per PR. Production deploy stays forbidden.

## 5. Runbooks (to be exercised in C5 staging drills)

- Stale-recovery storm: identify wedged worker via claim-age metric → drain →
  sweeper requeues; no manual DB edits.
- Storage outage: readiness flips 503; uploads stop; in-flight jobs retry with
  backoff; verify zero partial effects on recovery.
- Scanner outage: verdicts stop; releases expire naturally; nothing auto-promotes.
- Backup restore: restore to sandbox prefix → verify intake hashes + metadata
  counts → promote only on match.
- Key compromise: rotate KMS key; re-encrypt; revoke old IAM; audit.

## 6. Activation gates (ALL required before any production file flows)

1. #35 closed (durable jobs proven) + #36 upload path proven.
2. Storage provider + region + KMS + IAM approved and drilled (C3).
3. Scanner approved with verdict-trust evidence (C4).
4. DEC-02 retention + DEC-03 residency/transfer + counsel sign-off.
5. Pre-prod security review + credentials + runbook drills (C5).
6. Explicit PO production GO. Until then: staging/production refuse.
