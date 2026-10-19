# SEC-SOURCE-01 — phased implementation plan (P0–P5, decision-gated)

Status: **PLAN ONLY — no phase may start until its named decisions are approved
and its approval checkpoint signed.** No migration, scanner SDK, production
storage adapter, worker wiring, real-file parsing, credential, or release
endpoint is created by this document. Pairs with
`docs/product/SEC-SOURCE-01-boundary.md`. Authoritative issue: **#69**.

Baseline: `main` @ `2ac80c54bf77f4fd0a5d22d88f4edd06e899c3c4` (PR #68 merged;
post-merge CI `39116460297`, 7/7). Authoritative detail:
`docs/architecture/EP04C_SECURITY_ARCHITECTURE.md`,
`docs/engineering/EP04C_EXECUTION_PLAN.md`, `EP04C_DECISION_REGISTER.md`,
`docs/product/REC-DATA-03-boundary.md`. Where those name `0006`/`0007` for EP-04C
they are **stale** (§0.2).

## 0. Grounded starting point and numbering

### 0.1 Shipped at baseline
Auth/tenancy/RBAC/CSRF; intake upload + local quarantine; intake immutability
(`0005`); durable jobs + outbox (`0006`, EP-04C1); dev-only worker queue; pure
default-deny release contracts (`release/policy.py`, REC-DATA-03); dataset
registry (`0008`); mapping approvals (`0009`); exact finance, extraction,
normalization; fail-closed CI (7 jobs).

### 0.2 Migration rules (non-negotiable)
`0001`–`0009` are frozen and **must never be edited**. **`0010` is only a
proposed future number, not a reservation**; every PR must re-check `main` + open
PRs at kickoff and claim the then-free number. One migration per PR; add its line
to `db/migrations/versions/CHECKSUMS`.

### 0.3 Phase map

| Phase | Goal | Build start gate | Migration | Real data |
|---|---|---|---|---|
| P0 | Architecture + provider/control approvals (build-enabling) | — | none | no |
| P1 | Private object-storage foundation | DEC-S1 (architecture + control) | none (metadata only if needed) | no (synthetic) |
| P2 | Trusted malware scanning | DEC-S2 (architecture + control) | proposed `0010` | no (synthetic) |
| P3 | Release authorization | DEC-S2 + DEC-06 + revocation/TTL | proposed `0010` (or split) | no (synthetic) |
| P4 | Controlled extraction integration | DEC-S2 (sandbox) | none | sandbox only |
| P5 | Security verification + controlled rollout | P1–P4 staging evidence, then DEC-R1 GO + DEC-02 + DEC-03 | proposed `0012` if lifecycle | pilot, gated |

P0 approves the **architecture and the planned security controls** needed to
build each phase (plus the security *test plan*). P1–P4 may be built in a
**sandbox with synthetic files** once their build-enabling decisions are
approved. **DEC-R1 is a P5 GO after staging evidence, not a build precondition.**
No real customer document is read or processed before **P5 DEC-R1 GO + DEC-02 +
DEC-03** (F4).

## 1. P0 — Architecture, provider/control approvals and security-plan freeze

- **Scope:** approve the **architecture, provider selections and planned security
  controls** required to *build* each phase (F4), plus the security *test plan*.
  Resolve the build-enabling decisions — DEC-S1, DEC-S2, DEC-06 (SoD), revocation
  representation, and a compulsory finite release TTL — and the legal/retention
  questions that shape *sandbox architecture* (region-pinned design, lifecycle
  mechanics). **DEC-R1 is NOT approved here**; only its test plan is frozen.
  Capture dated S3/GuardDuty pricing.
- **Affected modules:** none (documentation + issue #69 records only).
- **Dependencies / blockers:** build-enabling decisions BLOCKED today.
- **Migrations:** none.
- **Implementation steps:** (1) resolve each build-enabling row in boundary §9
  with owner + date; (2) record the chosen stack and the object-`VersionId`/
  KMS/region pin in the decision register; (3) capture dated pricing citations;
  (4) freeze the DEC-R1 security test plan and the P5 evidence checklist;
  (5) note that `DEFAULT_RELEASE_POLICY.approved` flips to `True` **only** in a
  target environment's config at P5 activation, never as a code default.
- **Security acceptance criteria:** every build-enabling decision has an owner and
  dated approval; no provider/region is "approved by default"; default-deny
  remains the shipped state; the DEC-R1 test plan is frozen but **not** claimed
  passed.
- **Negative regression tests:** the existing master-gate unit test (unapproved
  policy ⇒ `RELEASE_NOT_ENABLED`) still passes.
- **Operational risks / rollback:** indefinite block is acceptable (default-deny);
  vendor drift → re-verify. Rollback = do nothing (deny stays).
- **Definition of Done:** build-enabling decision matrix complete and linked from
  #69; DEC-R1 test plan recorded as PENDING (P5).
- **Approval checkpoint:** PO + Security + Legal sign-off on build-enabling
  decisions; DEC-R1 GO deferred to P5.

## 2. P1 — Private object-storage foundation

- **Scope:** provider-agnostic object store behind the existing `quarantine.py`
  interface with immutable versioning, exact **`VersionId` identity** and
  version-pinned reads, integrity, KMS, tenant isolation, environment
  restrictions.
- **Affected modules:** `apps/api/app/quarantine.py` → package
  (`quarantine/base.py` protocol `put`/`open_lease`/`delete`/`exists`, plus a
  versioned-read primitive `open_version(key, version_id)`; `quarantine/local.py`
  current adapter; `quarantine/<provider>.py` new adapter;
  `quarantine/__init__.py` factory); `apps/api/app/config.py`
  (`storage_backend` gains the approved value **only after DEC-S1**).
- **Dependencies / blockers:** DEC-S1 approved; sandbox bucket + KMS key +
  least-privilege IAM role provisioned by PO-authorized ops.
- **Proposed migrations:** none required for the adapter; key-metadata table only
  if the chosen design needs it (proposed `0011`, self-checked).
- **Implementation steps:** (1) extract protocol, keep `LocalQuarantine` parity;
  (2) implement provider adapter (SSE-KMS, region-pinned endpoint, Block Public
  Access, versioning ON) returning the immutable provider **`VersionId`** on put;
  (3) compute a **separately verified, server-side whole-object SHA-256** at store
  time and record it alongside the `VersionId`; treat ETag as supplemental
  non-authoritative metadata only; (4) read strictly by `VersionId`
  (`get-object?versionId=…`), never by key alone; (5) per-role IAM
  (uploader/scanner-lease/worker/sweeper); (6) keep `storage_readiness()`
  refusing staging/production until P5.
- **Security acceptance criteria:** no read/list/download primitive exposed; no
  public ACL; wrong-region endpoint refused; rotation keeps old backups
  decryptable; cross-tenant GetObject denied; identical bytes across tenants
  isolated by namespace + server authorization; a mismatch in `VersionId` is
  rejected even when ETags are equal.
- **Negative regression tests:** cross-tenant read denied; public-ACL blocked;
  wrong-region endpoint refused; oversized/partial put cleaned; key rotation
  decrypts pre-rotation objects; storage outage ⇒ 503 with no data loss;
  **equal-ETag/different-`VersionId` request rejected**; **multipart-upload ETag
  (dash-suffixed, not a 64-hex SHA-256) is never treated as an object version or
  content hash.**
- **Operational risks / rollback:** SDK weight, interface drift. Rollback =
  revert `storage_backend` to `"local"`; intake 503 in staging/prod.
- **Definition of Done:** adapter parity tests green; sandbox rotation + outage
  drills passed; existing intake tests green.
- **Approval checkpoint:** DEC-S1 sign-off + PO GO to build P2.

## 3. P2 — Trusted malware scanning

- **Scope:** scanner integration, authenticated verdict ingestion, immutable
  append-only scan evidence, failure/timeout/outage handling, malicious-workbook
  defences, idempotency.
- **Affected modules:** proposed `0010_scan_verdicts...` migration;
  `apps/api/app/release/store.py` (persist/read verdicts) and
  `apps/api/app/release/scanner.py` (trusted-boundary verifier: SigV4/queue/
  control-plane); extend `apps/api/app/release/policy.py` **only** to accept
  persisted inputs — never weaken the evaluator.
- **Dependencies / blockers:** DEC-S2 approved; P1 complete; scanner sandbox.
- **Proposed migrations:** `0010` (number re-checked at kickoff):
  `scan_verdicts` with `NOT NULL` SHA-256 CHECK, an immutable object-**`VersionId`**
  column, a nullable non-authoritative `etag` column (documented as supplemental
  only), provider/policy/event identity, nullable engine/signature version
  (`not exposed by vendor`), `BEFORE UPDATE/DELETE` refusal triggers, composite
  `(tenant_id, client_id, source_intake_id)` FK.
- **Implementation steps:** (1) trusted-boundary consumer with SigV4/queue or
  control-plane verification; (2) persist verbatim status/result + event id with
  dedup; (3) enforce **SHA-256 + `VersionId`** binding and version-pinned reads
  (never key-only, never ETag-as-identity); (4) TTL freshness + re-scan on
  policy/engine change; (5) audit `scan.received/verdict`.
- **Security acceptance criteria:** client-submitted verdicts refused
  (`UNVERIFIED_EVIDENCE`); forged/unknown verdict refused; infected/`FAILED`/
  `TIMEOUT`/`UNSUPPORTED` never release; swapped `VersionId` refused;
  equal-ETag/different-`VersionId` refused; replay single-effect; outage ⇒ no
  release.
- **Negative regression tests:** forged event (bad transport auth) refused;
  replayed event id single-effect; verdict-for-v1 vs v2 bytes refused;
  **ETag matches but `VersionId` differs ⇒ refused**; **multipart ETag (not a
  64-hex SHA-256) never accepted as an object version or hash**; stale/future/
  non-finite timestamp fail closed; EICAR-style synthetic fixture ⇒ not released;
  zip/XML bomb + external-link workbook neutralized.
- **Operational risks / rollback:** accidentally accepting untrusted evidence;
  mutable-flag creep. Rollback = stop persisting verdicts; quarantine stays
  closed; no `CLEAN` column ever added to `document_intakes`.
- **Definition of Done:** attacker matrix green on real PG; append-only triggers
  proven; tenant-isolation negatives green.
- **Approval checkpoint:** DEC-S2 sign-off + Security review of the evidence
  contract.

## 4. P3 — Release authorization

- **Scope:** append-only authorization evidence; **separately appended**
  revocation/supersession events; expiry; trusted authority identity; separation
  of duties; exact source-object binding.
- **Affected modules:** same `0010` (or a follow-on proposed `0011` if split);
  `apps/api/app/release/store.py` (`release_authorizations`,
  `release_revocations`/`release_events`, effective-state projection).
- **Dependencies / blockers:** DEC-S2 + DEC-06 + revocation/TTL decisions.
- **Proposed migrations:** two append-only tables under `0010`:
  (a) `release_authorizations(verdict_id, trusted authority identity,
  scope=extract, issued_at, expires_at, optional SoD approvals)` — **immutable,
  with no `revoked`/`superseded_by` columns**; (b) `release_revocations` /
  `release_events(authorization_id, kind ∈ {revoke, supersede}, effective_at,
  event_id, actor)` — append-only, linked to the immutable authorization. Both
  get `BEFORE UPDATE/DELETE` refusal triggers and composite tenant/client/intake
  FKs. **No historical row is ever updated or deleted.**
- **Implementation steps:** (1) persist authorization bound to exact verdict +
  object SHA-256 + `VersionId`; (2) trusted-authority enforcement; (3) compulsory
  finite TTL (no future `issued_at`, chronology check); (4) SoD approvals when
  required; (5) append revocation/supersession as **new rows**; (6) compute
  effective release state as a **deterministic projection** ordered by
  `(effective_at, event_id)` with replay-dedup, late-arriving events applied by
  `effective_at` (not arrival order), and **default-deny** on any conflict or
  ambiguity (e.g. a revocation and a later reactivation both present without an
  unambiguous chain resolves to revoked).
- **Security acceptance criteria:** untrusted authority refused
  (`UNTRUSTED_RELEASE_AUTHORITY`); binding mismatch refused; scope≠extract
  refused; revoked/expired refused; a revoked authorization can never be
  reactivated by a stale/replayed event; conflicting evidence ⇒ default-deny;
  world where `approved=False` ⇒ `RELEASE_NOT_ENABLED`.
- **Negative regression tests:** authorization for a different verdict/object
  refused; expired/inverted/future timestamps refused; incomplete SoD approvals
  refused; **stale/replayed revocation event single-effect**; **out-of-order
  (late-arriving) revocation still applies by `effective_at`**; **attempt to
  reactivate a revoked authorization is refused / resolves to revoked**;
  conflicting revoke-vs-reactivate ⇒ default-deny; duplicate authorization is a
  single effect.
- **Operational risks / rollback:** perpetual-authorization creep; SoD not
  enforced; mutable-flag regression. Rollback = stop issuing authorizations;
  releases naturally expire; revocations remain append-only.
- **Definition of Done:** authorization + revocation attacker matrix green,
  including replay/late-arrival/conflict; SoD semantics match the approved policy;
  effective-state projection is deterministic and default-deny.
- **Approval checkpoint:** DEC-06 + revocation/TTL sign-off.

## 5. P4 — Controlled extraction integration

- **Scope:** server-side verification of release evidence at **every** protected
  read; the corrected **staged gate sequence** (F1); registration integrity;
  mapping eligibility; worker permissions.
- **Corrected staged gates (F1 — registration must not require mapping
  approval):**
  1. Source intake remains `QUARANTINED`.
  2. Trusted malware scanning + release authorization.
  3. Immutable **dataset-version registration** using verified source metadata
     (raw SHA, format, owner) — the gate is *release*, **not** mapping approval.
  4. Authorized **header extraction** (minimum read) + mapping-proposal
     preparation against the *existing* dataset version and its header
     fingerprint.
  5. Engagement-scoped **human mapping approval** (REC-DATA-02, `0009`).
  6. Validated **normalization** → new fingerprinted dataset version.
  7. **Derived eligibility** verification before reconciliation.

  Three distinct permissions stay explicit: *read source headers* ≠ *normalize* ≠
  *execute financial reconciliation*.
- **Affected modules:** worker claim/read path (`apps/api/worker/`);
  `evaluate_registration` (REC-DATA-01) fed by verified source metadata
  **independent of mapping approval**; REC-DATA-02 mapping approval; normalization;
  eligibility; `apps/api/app/release/store.py` read helpers.
- **Dependencies / blockers:** P2 + P3 complete in sandbox; DEC-S2 approved.
- **Proposed migrations:** none.
- **Implementation steps:** (1) worker requires a live, unexpired release whose
  verdict **SHA-256 + `VersionId`** match the object **before any read**, and
  re-checks at job start; (2) reads only via a version-pinned lease (no opaque
  internal keys, no presigned quarantine URLs); (3) register the immutable dataset
  version from verified source metadata; (4) permit the minimum header read and
  build the mapping proposal against that dataset version's header fingerprint;
  (5) record human mapping approval; (6) run validated normalization to the
  fingerprinted dataset version; (7) gate derived-run eligibility on release +
  approval + fingerprint; (8) least-privilege worker IAM.
- **Security acceptance criteria:** zero reads without a live matching release;
  TOCTOU closed by re-check; **registration succeeds with verified source metadata
  and no mapping approval**; **mapping approval cannot precede the dataset version
  it binds**; release alone is **insufficient** to normalize or run; normalization
  and reconciliation each require their own (distinct) authorization.
- **Negative regression tests:** no release ⇒ no read; expired/revoked mid-flight
  ⇒ abort; SHA-256/`VersionId` change between verdict and job start ⇒ abort;
  cross-tenant job cannot read another tenant's object; orphan/missing object
  fails safe; **mapping approval requested before its dataset version exists ⇒
  refused**; **release present but no mapping approval ⇒ not eligible to run**;
  **mapping approval present but no release ⇒ no header read/normalization**.
- **Operational risks / rollback:** TOCTOU; over-broad worker role; accidental
  re-introduction of the registration↔approval cycle. Rollback = disable
  extraction integration; quarantine stays closed.
- **Definition of Done:** lease-count assertions prove no unverified read;
  integration negatives green on real PG; staged-gate negatives (F1) green.
- **Approval checkpoint:** Security sign-off on the read path.

## 6. P5 — Security verification and controlled rollout

- **Scope:** threat testing, recovery testing, monitoring, operational runbooks,
  cost verification, audit evidence, production GO/NO-GO. **Synthetic sandbox
  construction is separated from actual customer-data activation (F4).**
- **Affected modules:** proposed `0012` lifecycle/tombstone migration;
  `apps/api/app/lifecycle/sweeper.py` (new); ops runbooks.
- **Dependencies / blockers:** P1–P4 complete with staging evidence; then
  DEC-R1 GO + DEC-02 + DEC-03 approved. **DEC-R1 is produced/verified in this
  phase, not required before building P1–P4.**
- **Proposed migrations:** `0012` tombstones / legal holds / erasure manifests
  (only after DEC-02 periods + legal authority).
- **Implementation steps:** (1) lifecycle/sweeper with hold flags; (2) per-class
  erasure manifests + backup-expiry proof; (3) restore drill (RPO ≤24 h /
  RTO ≤8 h evidence); (4) SIEM alerting + metrics; (5) execute the DEC-R1
  pre-prod security review checklist; (6) adversarial red-team + staged pilot
  onboarding gate; (7) only then flip the target environment's master gate.
- **Security acceptance criteria:** DEC-R1 checklist fully passed **after**
  staging evidence; holds block sweeps; erasure manifests complete across all
  classes incl. backups; audits retained per policy; sandbox vs production
  activation clearly separated.
- **Negative regression tests:** hold blocks sweep; expired backup absence
  proven; restore verifies hashes; revoked/expired release produces zero reads;
  abuse/rate limits enforced; SIEM alerts fire on forged evidence; **production
  master gate cannot be enabled for an environment lacking full DEC-R1 sign-off**.
- **Operational risks / rollback:** destructive sweeps, residency violation.
  Rollback = pause sweeps, keep holds, revert config to `local`; prod refuses.
- **Definition of Done:** all drills evidenced; DEC-R1 sign-off; PO GO.
- **Approval checkpoint:** PO + Security GO/NO-GO; staging→production activation.

## 7. Consolidated attacker matrix (fail-closed — owner phases)

| Attack | Expected | Phase |
|---|---|---|
| Malicious/polyglot/zip-bomb workbook | Refused/quarantined, never extracted | P2 (guards partly in `extraction/`) |
| Forged verdict / raw client JSON / self-tag | `UNVERIFIED_EVIDENCE` / refused | P2 |
| Replayed verdict (same event id) | single effect | P2 |
| Swapped object (`VersionId` or SHA-256 mismatch, TOCTOU) | `INTEGRITY_MISMATCH` at release + job start | P2/P4 |
| **ETag matches but `VersionId` differs** | refused (ETag non-authoritative) | P1/P2 |
| **Multipart-upload ETag used as object version/hash** | rejected (not a 64-hex SHA-256) | P1/P2 |
| Infected / `FAILED` / `TIMEOUT` / `UNSUPPORTED` | never released | P2 |
| Stale/future/non-finite timestamps | fail closed | P2/P3 |
| Untrusted scanner/authority | refused | P2/P3 |
| Missing/expired/incomplete-SoD authorization | refused | P3 |
| **Stale / replayed / late-arriving revocation event** | single-effect; applied by `effective_at` | P3 |
| **Reactivate a revoked authorization** | refused / resolves to revoked; ambiguity ⇒ default-deny | P3 |
| **Registration gated on mapping approval (cycle)** | impossible: registration uses verified metadata only | P4 |
| **Mapping approval before its dataset version exists** | refused | P4 |
| Release present but no mapping approval (or vice versa) | not eligible / no read | P4 |
| Cross-tenant read / signed-URL escape | 404/deny, no leak | P1/P4 |
| Storage outage / key rotation | 503 no loss; old backups decrypt | P1/P5 |
| Retention expiry / legal hold / restore | per manifest; hash-verified | P5 |
| Any of the above with no approved policy | `RELEASE_NOT_ENABLED` | all |

## 8. Activation gates (all mandatory before any real document)

1. **Build-enabling** decisions approved at P0: DEC-S1, DEC-S2, DEC-06,
   revocation, TTL (+ the sandbox-shaping parts of DEC-02/DEC-03).
2. P1–P4 attacker matrices green on real PG; sandbox rotation/outage/scan drills.
3. CI 7/7 green; independent GPT-6 review; PO GO.
4. **After** staging evidence, the **DEC-R1** pre-prod GO + DEC-02 + DEC-03
   determinations are signed off (P5) — not before the work that produces their
   evidence (F4).
5. `storage_readiness()` ready **for the target environment only**; production
   stays 503 until the DEC-R1 P5 sign-off.

## 9. Cross-phase risks and rollback principle

Every phase is additive and stays behind `RELEASE_NOT_ENABLED` /
`storage_backend="local"`. Rolling back means reverting config to `local` and
leaving evidence tables inert; no step is destructive, and intake immutability
(`0005`) is never reversed. Existing migrations `0001`–`0009` are never edited.

## 10. Security acceptance-criteria summary

- Default-deny is never weakened; an unapproved policy releases nothing.
- Unscanned bytes are never parsed, downloaded, or promoted.
- Release binds an immutable object **`VersionId`** + a separately verified
  server-computed whole-object SHA-256 through a trusted boundary (ETag is
  non-authoritative); replay and TOCTOU fail closed.
- Evidence and authorization are append-only; revocation/supersession is a
  separately appended event and never mutates history.
- The staged gates keep registration independent of mapping approval, and keep
  header-read, normalization, and reconciliation as distinct permissions.
- Tenant isolation holds across metadata, objects, jobs, and links.

## 11. Definition of Done (slice level)

Design implementable with no ambiguity about authentication, object identity,
trusted verdict, fail-closed availability, tenant isolation, regional/legal
approvals and lifecycle; all undecided items explicitly block implementation; no
real customer data in the repo; PR stays draft awaiting GPT-6 review and PO
approval.

## 12. Following task and fallback

**SEC-SOURCE-02** (bounded trusted object-store quarantine adapter + scanner
integration) starts **only after** SEC-SOURCE-01 technical review, merge
approval, post-merge CI, and explicit PO/Security/Legal decisions. If those
decisions remain blocked, proceed with a **separate safe development slice**
(synthetic/UI or another unblocked reconciliation task) rather than implementing
an unauthorized storage or release path.
