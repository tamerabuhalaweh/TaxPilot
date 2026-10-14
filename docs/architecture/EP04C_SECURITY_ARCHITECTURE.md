# EP-04C Production Ingestion Security Architecture (PROPOSED — not approved)

> Status: **PROPOSED design for GPT-6 review + PO approval. Nothing here authorizes
> providers, regions, credentials, scanning, downloads, extraction jobs, or production
> activation.** Normative baseline remains `docs/product/TAXPILOT_MASTER_SRS.md` v2.0;
> this document is non-normative on any conflict. All provider/region/version facts
> were verified October 2026 and must be re-verified at decision time.

Target pipeline:

```
upload → QUARANTINED → scan verdicts (append-only) → SCAN_CLEAN release
  → durable extraction job → validated dataset → confirmed mapping
  → normalization → READY_FOR_CHECKS
```

Every arrow is an authenticated, audited, tenant-isolated transition. Unscanned
bytes are never parsed, downloaded, or promoted.

## 1. Current-state audit (exact `main@6c33a7c`)

| Area | Status | Evidence |
|---|---|---|
| AuthN/Z, tenancy, RBAC, CSRF | IMPLEMENTED | `apps/api/app/sprint1_auth.py` (`require_roles(*WRITE)`, session-bound CSRF + exact-origin check, per-email Redis limiter); `apps/api/app/routers/auth.py`, `workspace.py` |
| Client intake upload (raw bytes, 25 MiB stream cap, signature/type/extension checks) | IMPLEMENTED (dev/test only) | `apps/api/app/routers/intakes.py`; bypass of JSON body cap is route-scoped in `apps/api/app/middleware.py` (`UPLOAD_BYPASS_SUFFIX`) |
| Private quarantine (opaque keys, O_EXCL 0600, owner-only dirs, symlink refusal) | IMPLEMENTED (local dev/test) | `apps/api/app/quarantine.py`; staging/production refuse via `storage_readiness()` → 503 |
| Intake metadata + lineage isolation + immutability trigger + DELETE refusal | IMPLEMENTED | `db/migrations/versions/0005_document_intakes.sql`; `apps/api/app/store.py` (`document_intakes`, advisory-lock helper) |
| Idempotency / versions / SHA dedup / concurrency | IMPLEMENTED (metadata only) | `routers/intakes.py` (advisory xact lock per key, IntegrityError loser path, fresh-conn commit verification) |
| Audit trail (no contents/keys) | IMPLEMENTED | `store.audit()`; `document_intake.received/duplicate/rejected/versioned` |
| Exact finance core | IMPLEMENTED | `apps/api/app/finance/money.py` (PR #43) |
| CSV/XLSX extraction (bounded, fail-closed typed cells) | IMPLEMENTED (must not run on unscanned files) | `apps/api/app/extraction/` (PR #49) |
| Mapping + normalization | IMPLEMENTED | `apps/api/app/normalization/` (PR #45) |
| Worker queue (fenced leases, Lua CAS, heartbeats, auto-recovery) | PARTIAL (dev-only) | `apps/api/worker/jobs.py`, `runner.py`; worker-crash-only durability; prod refused without `jobs_durability_approved` (#35 OPEN) |
| BFF proxy (allowlist, 1 MiB/10 MiB caps, 10 s timeout, no open proxy) | PARTIAL (JSON/auth only) | `apps/web/lib/proxy.ts`, `apps/web/app/api/v1/[...path]/route.ts`; 25 MiB uploads 413 at BFF — upload journey is API-only (#36 partly open) |
| CI security gates | IMPLEMENTED | `.github/workflows/ci.yml` (7 jobs) + `.github/scripts/security_gate.py` (fail-closed, signed time-bounded exceptions; none granted) |
| Malware scanning / release evidence | NOT STARTED | No scanner, no verdict records, no release path |
| Durable PG jobs / outbox | NOT STARTED | Redis-only queue; no job tables, no PG source of truth |
| Private object storage / KMS / region | NOT STARTED | Local disk only; no provider approved |
| Retention / deletion policy | BLOCKED | DELETE trigger refuses erasure; DEC-02 open; no periods chosen |
| Engagement workflow / review docs | NOT STARTED | Intake is client-bound staging, not an approved review document |
| Production deployment topology | NOT STARTED | `docker-compose.yml` is dev-only; `docker/api.Dockerfile` runs as root, no caps/TLS |

## 2. Trust boundaries

1. **Browser ↔ BFF** (same-origin; session cookie + CSRF; BFF never sees backend secrets).
2. **BFF ↔ API** (server-side fixed host; allowlisted headers only; no `x-forwarded-*` trust).
3. **API ↔ PostgreSQL** (tenant is the boundary: every row carries `tenant_id`; cross-tenant reads are 404).
4. **API ↔ quarantine store** (opaque keys; write/delete-only; no listing/download).
5. **Scanner ↔ quarantine** (read-only lease on one object; writes verdicts only, never file bytes).
6. **Workers ↔ jobs + store** (fenced claims; idempotent handlers; no cross-tenant coupling).
7. **Provider account ↔ KMS/backups** (least-privilege IAM; keys never in repo/env dumps).

## 3. Threat model (attacker-controlled input first)

| Threat | Implemented mitigation | Remaining gap → EP-04C PR |
|---|---|---|
| Malicious upload (malware, polyglot, bomb) | 25 MiB stream cap, ZIP/XML/formula guards in `extraction/`; quarantine never parses | No scanner yet → C4; BFF 25 MiB path → C2 |
| Zip/XML/entity-expansion bombs | Declared + verified decompression caps, entity-declaration refusal | Scanner-side re-validation → C4 |
| Forged scan-clean verdict | N/A (no scanner) | Append-only verdicts + hash binding + TBAC-style denial → C4 |
| Unauthorized release / confused deputy | N/A | Release requires verdict + hash + policy row; worker IAM least-privilege → C3/C4 |
| Tenant IDOR (metadata, blobs, jobs, links) | Tenant-scoped queries, composite FKs, opaque keys, 404 oracle-free | Extend to jobs/verdicts/links; signed-URL scope tests → C1/C2/C4 |
| Queue loss / claim theft / stale overwrite | Fenced per-attempt tokens, Lua CAS, heartbeats, auto-recovery | PG source of truth + wakeups; Redis-loss survival → C1 |
| Duplicate financial side effects | Advisory-locked idempotency keys (metadata) | Job-level idempotency at effects boundary; no exactly-once claim → C1 |
| Commit-ack ambiguity (DB vs blob) | Fresh-connection verification, preserve-on-uncertain | Outbox + reconciliation sweeper → C1 |
| Object-store public ACL / SSRF / key leak | No remote store; keys never in responses/logs | Private buckets, block-public-access, endpoint pinning → C3 |
| Path/link attacks, traversal filenames | Opaque keys, symlink refusal, neutralized metadata | Same controls on provider SDK paths → C3 |
| Logging/PII leaks | Redacted JSON logs, coordinates-only errors, content-free audit | Scanner verdict logs review → C4 |
| Key/credential compromise | No cloud secrets exist yet | KMS + rotation + secret manager → C3 |
| Partial DB/object writes | Blob-first + cleanup; fresh-conn verification | Transactional outbox → C1 |
| Oversized proxy streams / slow clients | BFF 1 MiB + discard cap; backend per-route caps | 25 MiB BFF path, timeouts, cancellation, edge throttling → C2 |
| Region transfer / residency violation | Nothing leaves dev; staging/prod refuse | Region pin + transfer basis + counsel (DEC-03) → decisions |
| Deletion / backup loss / legal hold | DELETE trigger refuses erasure | Tombstones, holds, backup expiry, restore drills (no periods without DEC-02) → C5 |

Detection + verification owner for every row above: backend integration tests (tenant-scoped negatives), CI security job, staging drills (C5), and PO/security sign-off gates in `EP04C_EXECUTION_PLAN.md`.

## 4. No-bypass state machine

Intake rows stay append-only under migration 0005 (only `QUARANTINED → REJECTED`
is permitted in place; `REJECTED` is terminal; `DELETE` is refused). Scan and
release state therefore lives in **new append-only records**, never as a
mutable `CLEAN` flag on the intake:

```
document_intakes.status = QUARANTINED          (frozen; EP-04B, migration 0005)
  └─▶ scan_verdicts (append-only, migration 0006 PROPOSED):
      intake_id + content_sha256 + scanner_id + engine_version + verdict
      {CLEAN, INFECTED, UNSUPPORTED, SCAN_FAILED, EXPIRED} + scanned_at + policy_version
     CHECK: verdict row is worthless unless content_sha256 == intake content_sha256.
  └─▶ release_authorizations (append-only, migration 0006 PROPOSED):
      intake_id + verdict_id + authorizer (policy, not a person) + scope
      (extract-only) + expires_at. Workers require a live, unexpired release
      whose verdict hash matches the object hash before ANY read.
```

Rules: timeout/unavailable/unsupported verdicts NEVER mean clean; a hash
mismatch between object, verdict, and release fails closed; re-scan is required
on scanner-version or policy change (old verdicts expire); extraction reads
only via short-lived, tenant-scoped, single-object grants issued after release
verification — never via opaque internal keys and never presigned quarantine URLs.

## 5. Storage architecture (PROPOSED)

- Private bucket(s), immutable versioning ON, Block Public Access ON (account +
  bucket), default SSE with customer-managed KMS keys (per-tenant data keys
  envelope-encrypted; rotation scheduled, old key versions retained for backups).
- Key layout keeps the EP-04B scheme (`tenant/shard/random`), generated
  server-side; tenant prefix is a namespace, never an authorization proof.
- TLS 1.2+ in transit; SDK endpoint pinned to the approved region (no path-style
  fallback to other regions); VPC endpoint / private networking where the
  provider supports it.
- Lifecycle: quarantine prefix (expire unreleased objects per DEC-02 once set) vs
  released prefix; replication/versioned backups in the approved region(s) only.
- Reads: no public ACL ever; worker reads via least-privilege role scoped to the
  release; any human-facing fetch is a ≤15-minute, single-object, tenant-checked
  grant (FR-FILE-010) — designed in C4, enabled only after decisions.

## 6. Jobs architecture (PROPOSED; detail in execution plan)

PostgreSQL as the durable source of truth, Redis as wakeups-only:

- `extraction_jobs` table (tenant, intake, idempotency key, payload hash,
  state, attempts, lease owner/expiry, terminal error) with CHECK-constrained
  states and advisory-locked claim; Redis list carries only job IDs as wakeups.
- Claim = single atomic `UPDATE ... WHERE state=QUEUED AND lease expired`
  returning the row (fencing token per attempt, as today); heartbeats renew;
  sweeper requeues below max attempts, dead-letters above; Redis loss only
  delays wakeups (sweeper re-discovers), never loses jobs.
- Handlers idempotent at the effects boundary (intake-key + payload-hash
  dedup); at-least-once delivery, never exactly-once claims.
- Transactional outbox for scan-requested → scan-complete → release → extract
  handoffs so DB/object split-brain reconciles via sweeper, not hope.
- Metrics: queue depth, claim age, stale recoveries, attempt exhaustion, scan
  latency, orphan-blob sweeps; alerts before paid pilots.

## 7. Proxy/BFF architecture (what exists vs gaps)

Implemented (`apps/web/lib/proxy.ts`, route handler): fixed backend host, header
allowlist (incl. `Idempotency-Key`, `X-CSRF-Token`), 1 MiB request / 10 MiB
response caps, 16 MiB discard cap, 10 s timeout, 502 without backend detail,
multi-`set-cookie` forwarding, demo-mode auth fail-closed, wire tests.
Gaps (→ C2): no 25 MiB upload path (413 by design today — upload stays API-only
until C2 lands + is tested), no request deadline differentiation (auth vs
upload), no cancellation propagation accounting, no edge spray limiting
(backend per-email limiter is authoritative; platform edge is a DEC-03-adjacent
ops decision), no upload progress/resume contract (FR-FILE-008 stays partial).

## 8. Retention/deletion mechanics (no periods chosen — DEC-02 open)

DELETE trigger stays enforced. Future mechanics (C5): tombstone rows (metadata
sans bytes), legal-hold flags blocking sweeps, per-class erasure manifests
(originals → derived → keys/backups → audit minimization), backup-expiry proof,
restore drills for RPO ≤24 h / RTO ≤8 h. No day counts, no compliance claims
without PO/legal sign-off.

## 9. Explicit non-goals

No provider credentials/regions activated, no scanner deployed, no downloads,
no extraction jobs, no tax rules, no JoFotara schemas, no frontend upload UI,
no retention periods, no compliance attestations.
