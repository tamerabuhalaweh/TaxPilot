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

| Phase | Goal | Start gate | Migration | Real data |
|---|---|---|---|---|
| P0 | Decisions + architecture freeze | — | none | no |
| P1 | Private object-storage foundation | DEC-S1 | none (metadata only if needed) | no |
| P2 | Trusted malware scanning | DEC-S2 | proposed `0010` | no (synthetic) |
| P3 | Release authorization | DEC-S2 + DEC-06 + revocation/TTL | proposed `0010` (or split) | no (synthetic) |
| P4 | Controlled extraction integration | DEC-S2 (sandbox) | none | sandbox only |
| P5 | Security verification + controlled rollout | DEC-02 + DEC-03 + DEC-R1 | proposed `0012` if lifecycle | pilot, gated |

P1–P4 may be built in a **sandbox with synthetic files** once their decisions are
approved; no real customer document is read before **P5 + DEC-R1**.

## 1. P0 — Decision approvals and architecture freeze

- **Scope:** obtain signed PO/Security/Legal decisions for DEC-S1, DEC-S2,
  DEC-02, DEC-03, DEC-R1, DEC-06 (SoD), revocation semantics, and a compulsory
  finite release TTL (§9 of the boundary doc); freeze the migration order and the
  provider-aware evidence contract; capture dated S3/GuardDuty pricing.
- **Affected modules:** none (documentation + issue #69 records only).
- **Dependencies / blockers:** all decisions BLOCKED today.
- **Migrations:** none.
- **Implementation steps:** (1) resolve each row in boundary §9 with owner +
  date; (2) record the chosen stack and the object-version/KMS/region pin in the
  decision register; (3) capture dated pricing citations; (4) freeze
  `DEFAULT_RELEASE_POLICY.approved=True` **only** via target-environment config,
  never a code default.
- **Security acceptance criteria:** every decision has an owner and dated
  approval; no provider/region is "approved by default"; default-deny remains the
  shipped state.
- **Negative regression tests:** the existing master-gate unit test (unapproved
  policy ⇒ `RELEASE_NOT_ENABLED`) still passes.
- **Operational risks / rollback:** indefinite block is acceptable (default-deny);
  vendor drift → re-verify. Rollback = do nothing (deny stays).
- **Definition of Done:** decision matrix complete and linked from #69.
- **Approval checkpoint:** PO + Security + Legal sign-off on the matrix.

## 2. P1 — Private object-storage foundation

- **Scope:** provider-agnostic object store behind the existing `quarantine.py`
  interface with versioning, integrity, KMS, tenant isolation, environment
  restrictions.
- **Affected modules:** `apps/api/app/quarantine.py` → package
  (`quarantine/base.py` protocol `put`/`open_lease`/`delete`/`exists`,
  `quarantine/local.py` current adapter, `quarantine/<provider>.py` new adapter,
  `quarantine/__init__.py` factory); `apps/api/app/config.py`
  (`storage_backend` gains the approved value **only after DEC-S1**).
- **Dependencies / blockers:** DEC-S1 approved; sandbox bucket + KMS key +
  least-privilege IAM role provisioned by PO-authorized ops.
- **Proposed migrations:** none required for the adapter; key-metadata table only
  if the chosen design needs it (proposed `0011`, self-checked).
- **Implementation steps:** (1) extract protocol, keep `LocalQuarantine` parity;
  (2) implement provider adapter (SSE-KMS, region-pinned endpoint, Block Public
  Access, versioning ON); (3) server-side SHA-256 computed at store time and
  recorded; (4) per-role IAM (uploader/scanner-lease/worker/sweeper); (5) keep
  `storage_readiness()` refusing staging/production until P5.
- **Security acceptance criteria:** no read/list/download primitive exposed; no
  public ACL; wrong-region endpoint refused; rotation keeps old backups
  decryptable; cross-tenant GetObject denied; identical bytes across tenants
  isolated by namespace + server authorization.
- **Negative regression tests:** cross-tenant read denied; public-ACL blocked;
  wrong-region endpoint refused; oversized/partial put cleaned; key rotation
  decrypts pre-rotation objects; storage outage ⇒ 503 with no data loss.
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
  `scan_verdicts` with `NOT NULL` SHA-256 CHECK, exact object-version column,
  provider/policy/event identity, nullable engine/signature version
  (`not exposed by vendor`), `BEFORE UPDATE/DELETE` refusal triggers, composite
  `(tenant_id, client_id, source_intake_id)` FK.
- **Implementation steps:** (1) trusted-boundary consumer with SigV4/queue or
  control-plane verification; (2) persist verbatim status/result + event id with
  dedup; (3) enforce hash+version binding; (4) TTL freshness + re-scan on
  policy/engine change; (5) audit `scan.received/verdict`.
- **Security acceptance criteria:** client-submitted verdicts refused
  (`UNVERIFIED_EVIDENCE`); forged/unknown verdict refused; infected/`FAILED`/
  `TIMEOUT`/`UNSUPPORTED` never release; swapped version refused; replay
  single-effect; outage ⇒ no release.
- **Negative regression tests:** forged event (bad transport auth) refused;
  replayed event id single-effect; verdict-for-v1 vs v2 bytes refused; stale/
  future/non-finite timestamp fail closed; EICAR-style synthetic fixture ⇒ not
  released; zip/XML bomb + external-link workbook neutralized.
- **Operational risks / rollback:** accidentally accepting untrusted evidence;
  mutable-flag creep. Rollback = stop persisting verdicts; quarantine stays
  closed; no `CLEAN` column ever added to `document_intakes`.
- **Definition of Done:** attacker matrix green on real PG; append-only triggers
  proven; tenant-isolation negatives green.
- **Approval checkpoint:** DEC-S2 sign-off + Security review of the evidence
  contract.

## 4. P3 — Release authorization

- **Scope:** append-only authorization/revocation evidence, expiry, trusted
  authority identity, separation of duties, exact source-object binding.
- **Affected modules:** same `0010` (or a follow-on proposed `0011` if split);
  `apps/api/app/release/store.py` (`release_authorizations`).
- **Dependencies / blockers:** DEC-S2 + DEC-06 + revocation/TTL decisions.
- **Proposed migrations:** `release_authorizations` append-only: `verdict_id`,
  trusted authority identity, `scope=extract`, `issued_at`, finite `expires_at`,
  `revoked`/`superseded_by`, optional SoD approvals.
- **Implementation steps:** (1) persist authorization bound to exact verdict +
  object hash/version; (2) trusted-authority enforcement; (3) compulsory finite
  TTL (no future `issued_at`, chronology check); (4) SoD approvals when required;
  (5) append-only revocation/supersede (never mutate history).
- **Security acceptance criteria:** untrusted authority refused
  (`UNTRUSTED_RELEASE_AUTHORITY`); binding mismatch refused; scope≠extract
  refused; revoked/expired refused; world where `approved=False` ⇒
  `RELEASE_NOT_ENABLED`.
- **Negative regression tests:** authorization for a different verdict/object
  refused; expired/inverted/future timestamps refused; incomplete SoD approvals
  refused; revoked release cannot be resurrected; duplicate authorization is a
  single effect.
- **Operational risks / rollback:** perpetual-authorization creep; SoD not
  enforced. Rollback = stop issuing authorizations; releases naturally expire.
- **Definition of Done:** authorization + revocation attacker matrix green;
  SoD semantics match the approved policy.
- **Approval checkpoint:** DEC-06 + revocation/TTL sign-off.

## 5. P4 — Controlled extraction integration

- **Scope:** server-side verification of release evidence at **every** protected
  read; registration integrity; mapping eligibility; worker permissions.
- **Affected modules:** worker claim/read path (`apps/api/worker/`); integration
  of `evaluate_release`/`source_released` into REC-DATA-01
  `evaluate_registration` and eligibility; `apps/api/app/release/store.py` read
  helpers.
- **Dependencies / blockers:** P2 + P3 complete in sandbox; DEC-S2 approved.
- **Proposed migrations:** none.
- **Implementation steps:** (1) worker requires a live, unexpired release whose
  verdict hash+version match the object **before any read**, and re-checks at job
  start; (2) reads only via `open_lease` (no opaque internal keys, no presigned
  quarantine URLs); (3) registration refuses unless released + REC-DATA-02
  approved; (4) least-privilege worker IAM.
- **Security acceptance criteria:** zero reads without a live matching release;
  TOCTOU closed by re-check; mapping eligibility cannot be achieved without
  release + approval + normalized fingerprint.
- **Negative regression tests:** no release ⇒ no read; expired/revoked mid-flight
  ⇒ abort; hash change between verdict and job start ⇒ abort; cross-tenant job
  cannot read another tenant's object; orphan/missing object fails safe.
- **Operational risks / rollback:** TOCTOU; over-broad worker role. Rollback =
  disable extraction integration; quarantine stays closed.
- **Definition of Done:** lease-count assertions prove no unverified read;
  integration negatives green on real PG.
- **Approval checkpoint:** Security sign-off on the read path.

## 6. P5 — Security verification and controlled rollout

- **Scope:** threat testing, recovery testing, monitoring, operational runbooks,
  cost verification, audit evidence, production GO/NO-GO.
- **Affected modules:** proposed `0012` lifecycle/tombstone migration;
  `apps/api/app/lifecycle/sweeper.py` (new); ops runbooks.
- **Dependencies / blockers:** DEC-02 + DEC-03 + DEC-R1 approved; P1–P4 done;
  sandbox drills.
- **Proposed migrations:** `0012` tombstones / legal holds / erasure manifests
  (only after DEC-02 periods + legal authority).
- **Implementation steps:** (1) lifecycle/sweeper with hold flags; (2) per-class
  erasure manifests + backup-expiry proof; (3) restore drill (RPO ≤24 h /
  RTO ≤8 h evidence); (4) SIEM alerting + metrics; (5) pre-prod security review
  checklist; (6) adversarial red-team + staged pilot onboarding gate.
- **Security acceptance criteria:** DEC-R1 checklist fully passed; holds block
  sweeps; erasure manifests complete across all classes incl. backups; audits
  retained per policy.
- **Negative regression tests:** hold blocks sweep; expired backup absence
  proven; restore verifies hashes; revoked/expired release produces zero reads;
  abuse/rate limits enforced; SIEM alerts fire on forged evidence.
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
| Swapped object version/hash (TOCTOU) | `INTEGRITY_MISMATCH` at release + job start | P2/P4 |
| Infected / `FAILED` / `TIMEOUT` / `UNSUPPORTED` | never released | P2 |
| Stale/future/non-finite timestamps | fail closed | P2/P3 |
| Untrusted scanner/authority | refused | P2/P3 |
| Missing/expired/revoked/incomplete-SoD authorization | refused | P3 |
| Cross-tenant read / signed-URL escape | 404/deny, no leak | P1/P4 |
| Storage outage / key rotation | 503 no loss; old backups decrypt | P1/P5 |
| Retention expiry / legal hold / restore | per manifest; hash-verified | P5 |
| Any of the above with no approved policy | `RELEASE_NOT_ENABLED` | all |

## 8. Activation gates (all mandatory before any real document)

1. DEC-S1, DEC-S2, DEC-02, DEC-03, DEC-R1, DEC-06, revocation, TTL approved (P0).
2. P1–P4 attacker matrices green on real PG; sandbox rotation/outage/scan drills.
3. CI 7/7 green; independent GPT-6 review; PO GO.
4. `storage_readiness()` ready **for the target environment only**; production
   stays 503 until DEC-R1 sign-off.

## 9. Cross-phase risks and rollback principle

Every phase is additive and stays behind `RELEASE_NOT_ENABLED` /
`storage_backend="local"`. Rolling back means reverting config to `local` and
leaving evidence tables inert; no step is destructive, and intake immutability
(`0005`) is never reversed. Existing migrations `0001`–`0009` are never edited.

## 10. Security acceptance-criteria summary

- Default-deny is never weakened; an unapproved policy releases nothing.
- Unscanned bytes are never parsed, downloaded, or promoted.
- Release binds the exact whole-object SHA-256 + object version through a
  trusted boundary; replay and TOCTOU fail closed.
- Evidence and authorization are append-only; revocation never mutates history.
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
