# SEC-SOURCE-01 — Trusted source storage, malware scanning and release-evidence architecture

Status: **PROPOSED / decision-first — nothing approved.** This document does not
authorize any provider, region, credential, scanner, retention period,
separation-of-duties policy, or release path. Staging and production keep
refusing intake (`storage_readiness()` → 503) and registration keeps refusing
with `SOURCE_NOT_RELEASED` (default-deny). All BLOCKED decisions in §9 stay
**BLOCKED**; where this document names a candidate it is a *PROPOSED option for
comparison*, not an approved decision.

Authoritative issue: **#69**. Baseline: `main` @
`2ac80c54bf77f4fd0a5d22d88f4edd06e899c3c4` (PR #68 merged; post-merge CI
`39116460297`, 7/7 success). Normative spec:
`docs/product/TAXPILOT_MASTER_SRS.md`. Authoritative companions (do not
duplicate): `docs/architecture/EP04C_SECURITY_ARCHITECTURE.md` (design),
`docs/engineering/EP04C_EXECUTION_PLAN.md` (build order),
`docs/product/EP04C_DECISION_REGISTER.md` (stack options),
`docs/product/REC-DATA-03-boundary.md` (pure default-deny release contracts).
Implementation plan: `docs/engineering/SEC-SOURCE-01-IMPLEMENTATION-PLAN.md`.
All provider/region/version/pricing facts were verified October 2026 and **must
be re-verified at decision time**; the migration numbering quoted in the two
older EP-04C docs is stale (§3).

## 1. Objective and why this is decision-first

No trustworthy customer-file processing is permitted before security decisions.
This slice delivers the design, the trusted contracts, and a bounded,
decision-gated plan so implementation (SEC-SOURCE-02+) is unambiguous about
authentication, object identity, trusted verdicts, fail-closed availability,
tenant isolation, regional/legal approvals and lifecycle — while every undecided
item explicitly blocks implementation.

## 2. Grounded current-state audit (post EP-04C1)

Verified against baseline `2ac80c5` (not the stale `main@6c33a7c` in the older
EP-04C docs):

| Area | Status | Grounding |
|---|---|---|
| AuthN/Z, tenancy, RBAC, CSRF | IMPLEMENTED | `apps/api/app/sprint1_auth.py`, `routers/auth.py`, `workspace.py` |
| Intake upload (25 MiB stream cap, type/ext/signature checks) | IMPLEMENTED (dev/test) | `apps/api/app/routers/intakes.py`; `middleware.py` route-scoped upload bypass |
| Private quarantine (opaque keys, O_EXCL `0600`, owner-only dirs, symlink refusal, no read/list/download) | IMPLEMENTED (local dev/test) | `apps/api/app/quarantine.py` (`storage_readiness()` → 503 for staging/prod) |
| Intake metadata immutability + lineage isolation + `DELETE` refusal | IMPLEMENTED | `db/migrations/versions/0005_document_intakes.sql`; `store.py` |
| Durable PG jobs + transactional outbox (EP-04C1) | **IMPLEMENTED** | `db/migrations/versions/0006_extraction_jobs.sql`; `apps/api/app/jobs/`, `worker/` |
| Dataset-version registry (REC-DATA-01) | IMPLEMENTED | `db/migrations/versions/0008_dataset_versions.sql`; `apps/api/app/datasets/registry.py` |
| Mapping approvals (REC-DATA-02) | IMPLEMENTED | `db/migrations/versions/0009_mapping_approvals.sql`; `apps/api/app/mapping/` |
| Durable release policy + trusted-evidence contracts (REC-DATA-03, pure, default-deny) | IMPLEMENTED | `apps/api/app/release/policy.py`; `apps/api/tests/test_release_policy_contracts.py` |
| Exact finance core; bounded extraction; mapping/normalization | IMPLEMENTED | `apps/api/app/finance/money.py`, `extraction/`, `normalization/` |
| Worker queue (fenced leases, Lua CAS, heartbeats, auto-recovery) | PARTIAL (dev-only) | `apps/api/worker/`; production refused until EP-04C1 approval gate |
| BFF allowlist proxy | PARTIAL (JSON/auth only) | `apps/web/lib/proxy.ts`, `apps/web/app/api/v1/[...path]/route.ts` |
| CI security gates | IMPLEMENTED | `.github/workflows/ci.yml` (7 jobs); `.github/scripts/security_gate.py` (fail-closed, no exceptions granted) |
| **Malware scanning + verdict evidence** | **NOT STARTED** | no scanner, no verdict records, no persisted release |
| **Private object storage / KMS / region pin** | **NOT STARTED** | `LocalQuarantine` only; `config.storage_backend` may only be `"local"` |
| **Retention / deletion / backups / legal holds** | **BLOCKED** | `DELETE` trigger refuses erasure; DEC-02 open |
| **Production deployment topology** | **NOT STARTED** | `docker-compose.yml` dev-only; prod path forbidden |

**Do not confuse the clean synthetic *pure* evaluator with an active scan.**
`release/policy.py` evaluates in-memory facts; it stores nothing and scans
nothing. No production storage or scanning capability exists (§5).

### 2.1 Environment-specific behavior

- **development / test:** local quarantine on disk; intake allowed.
- **staging / production:** `storage_readiness()` returns not-ready with an
  explicit reason → intake responds **503**; no object store, region,
  encryption, or scanning exists, so there is no release path.
- Master gate: `DEFAULT_RELEASE_POLICY.approved is False` ⇒ `evaluate_release`
  returns `RELEASE_NOT_ENABLED` **unconditionally**, before any other fact.

## 3. Migration-numbering correction (stale upstream)

`EP04C_SECURITY_ARCHITECTURE.md` §4 and `EP04C_EXECUTION_PLAN.md` §1 still say
**0006 = EP-04C1** and **0007 = EP-04C4**. Those numbers are taken by shipped
migrations: `0006_extraction_jobs.sql`, `0007_rec_engagements.sql`,
`0008_dataset_versions.sql`, `0009_mapping_approvals.sql`. **Existing
`0001`–`0009` must never be edited. The next free number is `0010`; any
SEC-SOURCE-02 PR must re-check `main` + open PRs at kickoff and claim the then-free
number.** `0010` is a *proposed future* number only — **not a reservation**.

## 4. Trust boundaries and no-bypass state machine

Boundaries (from `EP04C_SECURITY_ARCHITECTURE.md` §2): browser↔BFF, BFF↔API,
API↔PostgreSQL (tenant is the row boundary), API↔quarantine (opaque keys,
write/delete-only), **scanner↔quarantine (read-only lease on one object; writes
verdicts, never bytes)**, workers↔jobs/store (fenced), provider↔KMS/backups
(least-privilege IAM).

```
upload → QUARANTINED (0005, frozen; only → REJECTED in place; DELETE refused)
  └─▶ scan_verdicts (append-only)                    # migration 0010 PROPOSED
        provider identity + trusted origin (SigV4/queue/control-plane) +
        verbatim verdict + whole-object SHA-256 + exact object version
        (versionId/eTag) + plan/policy version + event id + scanned_at +
        engine/signature version ONLY if supplied (else `not exposed by vendor`)
  └─▶ release_authorizations (append-only)           # migration 0010 PROPOSED
        verdict_id + authorizer (trusted policy identity) + scope=extract +
        issued_at + expires_at (+ approvals when SoD required) + revoked flag
  └─▶ gated extraction (worker requires a live, unexpired release whose verdict
        hash+version match the stored object BEFORE any read; re-checked at
        job start) → future normalization + human approval → eligible job
```

Rules (enforced by the pure evaluator today; persisted later): rejection and
revocation **never** silently enable access; unscanned bytes are never parsed,
downloaded, or promoted (SRS FR-FILE-007); `TIMEOUT`/`UNSUPPORTED`/`ACCESS_DENIED`/
`FAILED`/unknown/outage never mean clean; a hash/object-version mismatch fails
closed; re-scan required on policy/engine change; raw webhook JSON and
self-reported object tags never authorize release; the raw source SHA is **not**
the normalized `dataset_fingerprint`.

## 5. Missing production storage and scanning capabilities

Not present at baseline: an approved private object store with immutable
versioning and KMS; a scanner and trusted verdict ingestion; append-only
verdict/release tables; object-version binding; retention/deletion/backup
lifecycle; region pinning; production IAM/secret management; pre-production
security review. Until these exist behind approved decisions, the default-deny
boundary in §7 is the whole security posture.

## 6. Decision areas (PROPOSED options — none approved)

Options and trade-offs are detailed in `EP04C_DECISION_REGISTER.md`; this section
is the SEC-SOURCE-01 contract view and adds DEC-06.

### 6.1 DEC-S1 — private object storage, encryption, KMS, versioning, IAM
- Requirements: private, versioned bucket(s); **immutable per-object version
  ID**; whole-object SHA-256 recorded server-side; Block Public Access (account +
  bucket); SSE with customer-managed KMS keys (per-tenant data keys, envelope);
  scheduled rotation with old key versions retained so backups stay decryptable;
  region-pinned SDK endpoint (no path-style cross-region fallback);
  least-privilege, per-role IAM (uploader / scanner read-lease / worker /
  sweeper); no public ACL; no long-lived credentials in the image or env dumps.
- Hazards to design out: presigned-URL scope escape, SSRF via endpoint config,
  key-in-logs, cross-region drift.
- Candidates (PROPOSED): Stack A AWS `me-south-1`; Stack B AWS `eu-central-1`;
  Stack C S3-compatible independent store. None approved.

### 6.2 DEC-S2 — scanner selection, trusted verdict provenance, outages, malicious-file protection
- Provenance **must** be authenticated at a trusted boundary — SigV4-authenticated
  SQS/EventBridge poll or control-plane status read — **never** caller/submitted
  JSON or object tags alone.
- Provider-aware evidence: leading managed scanner (GuardDuty Malware Protection
  for S3) publishes **no** engine/signature version; record `not exposed by
  vendor` rather than fabricate one (ClamAV exposes CVD versions).
- Verdict semantics: clean / infected / `UNSUPPORTED` / `ACCESS_DENIED` /
  `FAILED` / timeout / outage — only an explicitly clean verdict of the exact
  object version may ever release; all others fail closed.
- Freshness/TTL, re-scan and revocation: verdicts expire under a policy TTL and
  are invalidated on policy/engine change; revocation is append-only.
- Malicious-workbook defences (defence-in-depth beyond the scanner): bounded
  decompression (zip/XML/entity bombs), formula/external-link neutralization, no
  macro execution, size caps, resource caps; these already partly exist in
  `extraction/` and must not run before release.
- Candidates (PROPOSED): managed GuardDuty / self-hosted ClamAV / evaluated SaaS.

### 6.3 DEC-02 — retention, deletion, backups, legal holds
- No durations are invented. `DELETE` remains refused on intake rows until a
  tombstone/hold flow is authorized.
- Future mechanics: quarantine-prefix expiry for unreleased objects; released
  lifecycle; tombstones (metadata sans bytes); legal-hold flags that block
  sweeps; per-class erasure manifests (originals → derived → keys/backups →
  audit minimization); backup-expiry proof; restore drills. SRS pilot default
  (retain while active + contractual interval; soft-delete immediately
  inaccessible; minimal tombstones) is **context, not an approved period**.

### 6.4 DEC-03 — hosting region, residency and transfers
- Jordan-first geography. Distinguish **legal requirement** from **assumption**
  and seek a Jordan-qualified legal determination (PDPL Law 24/2023). Every
  candidate is cross-border (Bahrain/EU ≠ Jordan) and needs a documented
  transfer basis + subprocessor DPAs. Related: SRS DEC-12 (residency ADR).
- Multi-country future: one deployment per residency zone, tenant→zone pinning,
  separate bucket + KMS key + region per zone, no cross-zone replication unless
  approved — preserves Jordan-first residency while keeping rollout a config
  change.

### 6.5 DEC-R1 — production security readiness (GO checklist)
Secrets management; least-privilege IAM; signed-event authenticity; audit
retention; tenant-boundary negatives; KMS + rotation; abuse/rate limits; SIEM
alerting; adversarial end-to-end red-team; backup restore test; operational
on-call and runbooks. All must pass in staging before any production GO.

### 6.6 DEC-06 — release authority and separation of duties (SoD)
- Release is authorized by a **trusted policy identity**, not a person acting
  ad hoc; the authority set and the policy/version it enforces are a decision.
- Whether source release requires **two-person approval** (`require_two_person`)
  is **undecided** — the pure evaluator already models `INCOMPLETE_APPROVALS`,
  but perpetual or single-authorizer release is **not** silently adopted.
- SoD must reconcile with REC-DATA-02 approval roles (distinct, server-verified
  reviewers) so one actor cannot both alter mapping approval and release source
  bytes. SRS `DEC-06` = blocker/SoD (pre-approval-impl).

## 7. Preserving the default-deny boundary (unchanged)

- `config.storage_backend` accepts only `"local"`; `storage_readiness()` refuses
  staging/production with an explicit reason.
- `DEFAULT_RELEASE_POLICY.approved is False` ⇒ `RELEASE_NOT_ENABLED`
  short-circuits everything; `source_released(...)` is `False` everywhere.
- `evaluate_registration` refuses with `SOURCE_NOT_RELEASED`; derived-run
  eligibility refuses; release alone is never sufficient (needs REC-DATA-02
  approval + normalized fingerprint).
- Missing object store / scanner / trust boundary ⇒ 503 and no release path.
  SEC-SOURCE-02 must add evidence behind the approved policy, never around it.

## 8. Trusted evidence contract (binding, append-only, replay)

1. **Exact source SHA-256 + object-version binding.** Every verdict binds the
   server-computed whole-object SHA-256 **and** the exact provider object
   `versionId`/eTag. Release re-verifies both; extraction re-checks at job start
   (`INTEGRITY_MISMATCH` on swap).
2. **Append-only scan/release evidence.** New tables only (proposed `0010`):
   immutable rows with `BEFORE UPDATE/DELETE` refusal triggers, composite
   `(tenant_id, client_id, source_intake_id)` FKs, `NOT NULL` SHA-256 CHECKs,
   explicit provider/policy/event columns. **No mutable `CLEAN` flag on
   `document_intakes`.**
3. **Trusted provenance.** Insertion only via the authenticated boundary; the
   in-memory `transport_verified` flag is boundary-only (client-constructed
   evidence is refused as `UNVERIFIED_EVIDENCE`).
4. **Replay control.** Event IDs are deduplicated; the same verdict delivered
   twice is a single effect; a stale/superseded arrival does not override a
   newer state.
5. **Expiration.** A finite policy TTL; `max_evidence_age_seconds=None` means no
   evidence is fresh (default-closed); malformed/non-finite timestamps fail
   closed (REC-DATA-03 F1).
6. **Revocation.** Append-only revocation record / supersede generation; never
   mutate historical evidence (`RELEASE_REVOKED`).
7. **Trusted source binding.** Evidence binds an immutable tenant/client/intake
   plus object identity (REC-DATA-03 F2), so identical bytes across tenants never
   confuse.

## 9. Unresolved decisions and approval owners

| ID | Decision | Owner | Precondition / evidence | Blocks |
|---|---|---|---|---|
| DEC-S1 | Object-store provider/bucket, versioning, key rotation, prod IAM owner | PO + Tech Lead | sandbox rotation/outage drill + counsel inputs | store adapter, object-version binding |
| DEC-S2 | Scanner + provider-aware verdict trust, fallback, outage behavior, rescan/TTL | PO + Security | sandbox scan-latency/outage drill | verdict/release tables, gated extraction |
| DEC-03 | Hosting region + cross-border transfer basis (SRS DEC-12) | PO + Tech Lead + Legal | PDPL Law 24/2023 assessment + counsel opinion + DPAs | region pin, any real data |
| DEC-02 | Retention/deletion/backup/hold periods + legal authority (SRS pilot default is context only) | PO + Legal | legal authority + hold process + backup-expiry compatibility | lifecycle/TTL, tombstones |
| DEC-R1 | Pre-prod security review, env credentials, pilot gate | PO + Security | §6.5 checklist + staging drills + sign-off | any production flow |
| DEC-06 | Release authority set + separation of duties (two-person?) | PO + Security | SoD policy reconciled with REC-DATA-02 | `require_two_person` semantics |
| Revocation semantics | What revokes a release + append-only representation | PO + Security + Tech Lead | — | revocation design |
| Release TTL / chronology | Compulsory finite TTL; no future `issued_at`; scan↔auth chronology | PO + Security | — | production policy values |

All above are **BLOCKED**. No AI may mark them APPROVED.

## 10. Verified external facts (dated — re-verify at decision time)

| Fact | Value (verified Oct 2026) | Source | Caveat |
|---|---|---|---|
| GuardDuty Malware Protection for S3 evidence surface | statuses `NO_THREATS_FOUND/THREATS_FOUND/UNSUPPORTED/ACCESS_DENIED/FAILED`; EventBridge at-least-once; carries object `versionId`/`eTag`; **no** engine/signature version | `EP04C_DECISION_REGISTER.md`; AWS monitoring docs | managed-scan pricing/behavior drift |
| Backblaze B2 | $6.95/TB/mo; regions US/EU/CA — **no Middle East**; account region immutable | `EP04C_DECISION_REGISTER.md`; Backblaze pricing page | list-price assumption |
| Wasabi | 16 regions NA/EMEA/APAC; 90-day minimum = early-deletion *billing* charge, not a technical block | `EP04C_DECISION_REGISTER.md`; Wasabi terms/docs | DEC-02 cost compatibility risk |
| Cloudflare R2 | jurisdictions default/eu/us/fedramp(-high) only; location hints best-effort, not guaranteed | `EP04C_DECISION_REGISTER.md`; R2 data-location docs | not viable for ME residency as drawn |
| AWS S3 / GuardDuty scan pricing | **not yet captured** — to be recorded with a dated citation before DEC-S1/S2 | — | open |

No cost figure here is a committed price; all are list-price assumptions for
comparison pending a dated re-verification.

## 11. Residual risks and explicit non-decisions

- Nothing here authorizes a provider, region, credential, scanner, scrape,
  download, retention period, SoD policy, revocation rule, or release TTL.
- Vendor facts are Oct-2026 snapshots and may drift; S3/GuardDuty pricing is not
  yet captured.
- The upstream EP-04C docs still carry stale `0006`/`0007` numbering; this
  document records the correction without editing reference material owned by
  the EP-04C design branch.
- SoD, revocation, and a compulsory release TTL remain undecided and are not
  silently adopted.
- The flaky Redis DB-15 cross-process tests are a separate maintenance issue, out
  of scope here.

## 12. Evidence and references

- Code: `apps/api/app/quarantine.py`, `routers/intakes.py`, `config.py`,
  `release/policy.py`, `datasets/registry.py`, `mapping/`, `jobs/`, `worker/`;
  tests `apps/api/tests/test_release_policy_contracts.py`.
- Migrations `0005`, `0006`, `0007`, `0008`, `0009` (immutability/append-only
  patterns); next free `0010`.
- Docs: `REC-DATA-03-boundary.md`, `EP04C_SECURITY_ARCHITECTURE.md`,
  `EP04C_EXECUTION_PLAN.md`, `EP04C_DECISION_REGISTER.md`,
  `SEC-SOURCE-01-IMPLEMENTATION-PLAN.md`.
- SRS: FR-FILE-003/004/005/006/007/008/009/010; DEC-02/03/06/12/13; AT-001/
  AT-017/AT-020.
