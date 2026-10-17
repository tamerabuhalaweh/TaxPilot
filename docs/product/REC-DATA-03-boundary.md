# REC-DATA-03 boundary (source-release evidence and eligibility gates)

Scope: `apps/api/app/release/policy.py` (pure, default-deny contracts) and
`apps/api/tests/test_release_policy_contracts.py`. **No** migration, **no**
evidence table, **no** release endpoint, **no** scanner integration, **no**
worker wiring. This slice is **design + default-deny contracts + tests only**.

Authoritative spec: GitHub issue #61. Companion architecture:
`docs/architecture/EP04C_SECURITY_ARCHITECTURE.md` §4/§4.1; plan:
`docs/engineering/EP04C_EXECUTION_PLAN.md` (C4); decisions:
`docs/product/EP04C_DECISION_REGISTER.md` (DEC-S1/S2/02/03/R1).

## Why this slice stops at default-deny

The scanner, object store, retention, and residency decisions are **all
BLOCKED and unapproved**, and no scanner or private object store exists in the
codebase:

- `apps/api/app/config.py`: `storage_backend` may only be `"local"` (dev/test);
  `quarantine.py:storage_readiness()` makes staging/production **refuse intake**
  (`503`) because "no private object store, region, encryption, or malware
  scanning exists yet (EP-04C)".
- `apps/api/app/quarantine.py`: the only adapter is local disk (dev/test), with
  no object versioning and no read/scan primitive (`put`/`delete`/`exists` only).
- `db/migrations/versions/0005_document_intakes.sql`: the only legal in-place
  transition is `QUARANTINED → REJECTED`; there is **no `RELEASED` status** and
  `DELETE` is refused. Release state must live in new append-only records.
- Decision register: `DEC-S2` (scanner + verdict trust), `DEC-S1` (object store +
  key rotation + IAM), `DEC-03` (region + transfer basis), `DEC-02`
  (retention/deletion periods), `DEC-R1` (pre-prod security review) — **BLOCKED**.

Per issue #61, when these material decisions are unresolved the deliverable is
the documented design and default-deny contracts only. Creating the evidence
tables/endpoints now would bake in unapproved provider/retention/expiry
semantics and risk a release path that marks real customer files RELEASED. So
**no such path exists in this PR**: `ReleasePolicy.approved` defaults to `False`
and `evaluate_release` returns `RELEASE_NOT_ENABLED` unconditionally.

## Where bytes live, and who can touch them (grounded)

| Layer | Component | Access under quarantine |
|---|---|---|
| Bytes at rest | `LocalQuarantine` (dev/test only) under `quarantine_root` | write/delete/exists only; opaque keys; owner-only `0600`; symlink-refusing; **no read, no list, no download** |
| Metadata | `document_intakes` (0005) | immutable; only `QUARANTINED → REJECTED` (+reason) |
| Registration | `dataset_versions` (0008, REC-DATA-01) | immutable; POST stays default-deny (`SOURCE_NOT_RELEASED`) |
| Scanner | **does not exist** | nothing may read bytes for scanning; nothing may write verdicts |
| Object store | **does not exist** (local adapter only) | staging/production refuse intake |

Consequence: only a future approved private object store with versioning can
supply the exact **object version** that a verdict and a release must bind.

## Trust boundary and no-bypass state machine (design)

```
upload → QUARANTINED (0005, frozen)
  └─▶ scan_verdicts (append-only)        # NOT in this PR
       provider identity + trusted origin + verdict (verbatim) +
       exact object version (versionId) + whole-object SHA-256 +
       plan/policy version + event id + timestamp +
       engine/signature version ONLY if supplied (else `not exposed by vendor`)
  └─▶ release_authorizations (append-only)  # NOT in this PR
       verdict_id + authorizer (policy, not a person) + scope (extract-only) +
       issued_at + expires_at (+ approvals when SoD required)
  └─▶ gated extraction (workers require a live, unexpired release whose
       verdict hash matches the object hash before ANY read)
```

Rules enforced by the design (and by the pure evaluator today):

1. Unscanned bytes are never parsed, downloaded, or promoted (SRS FR-FILE-007).
2. `TIMEOUT`/`UNSUPPORTED`/`ACCESS_DENIED`/`FAILED`/unknown verdicts and provider
   outages **never** mean clean.
3. A hash or object-version mismatch between object, verdict, and release fails
   closed (swapped-object defence).
4. Re-scan is required on policy change; old verdicts expire (verdict TTL).
5. Evidence is accepted only through a trusted boundary (SigV4/queue or
   control-plane verification). Raw webhook JSON and self-reported object tags
   never authorize release.
6. The raw source SHA is **not** the normalized `dataset_fingerprint`
   (REC-DATA-01/02); release never stands in for dataset identity.

## Default-deny policy gates (implemented, pure)

`evaluate_release` returns the first unmet gate (full list in
`release.policy.PRECEDENCE`; each is a typed reason code):

| # | Gate | Refusal |
|---|---|---|
| 0 | Approved release policy exists (master default-deny) | `RELEASE_NOT_ENABLED` |
| 1 | Declared type is `csv`/`xlsx` | `UNSUPPORTED_FILE_TYPE` |
| 2 | Intake not `REJECTED` | `SOURCE_REJECTED` |
| 3 | Intake still `QUARANTINED` | `INTAKE_NOT_QUARANTINED` |
| 4 | Scan evidence present | `MISSING_SCAN_EVIDENCE` |
| 5 | Evidence went through the trusted boundary | `UNVERIFIED_EVIDENCE` |
| 6 | Provider explicitly trusted | `UNTRUSTED_SCANNER` |
| 7 | Provider not in outage | `PROVIDER_OUTAGE` |
| 8 | Verdict is a known value | `UNKNOWN_SCAN_VERDICT` |
| 9 | Verdict is explicitly clean | `SCAN_VERDICT_NOT_CLEAN` |
| 10 | Evidence within an approved freshness window | `STALE_SCAN_EVIDENCE` |
| 11 | Scanned object hash + version = stored object | `INTEGRITY_MISMATCH` |
| 12 | Engine provenance present when required | `MISSING_ENGINE_PROVENANCE` |
| 13 | Evidence produced under current policy version | `POLICY_VERSION_MISMATCH` |
| 14 | Release authorization present | `MISSING_RELEASE_AUTHORIZATION` |
| 15 | Authorization binds this exact verdict | `AUTHORIZATION_BINDING_MISMATCH` |
| 16 | Authorizing authority trusted | `UNTRUSTED_RELEASE_AUTHORITY` |
| 17 | Scope is `extract` only | `UNSUPPORTED_RELEASE_SCOPE` |
| 18 | Authorization not revoked | `RELEASE_REVOKED` |
| 19 | SoD approvals satisfied when required | `INCOMPLETE_APPROVALS` |
| 20 | Authorization not expired | `RELEASE_EXPIRED` |

The only path to `RELEASE_AUTHORIZED` requires a **non-default** policy object
that only an approved configuration surface may build. Because
`DEFAULT_RELEASE_POLICY.approved is False`, `source_released(...)` — the future
wiring point for REC-DATA-01 registration and REC-SLICE-03 eligibility — returns
`False` everywhere today, inheriting default-deny with no release path.

## Attacker matrix this contract already refuses (unit-proven)

| Attack | Result |
|---|---|
| Client-submitted "clean" verdict | `UNVERIFIED_EVIDENCE` (transport flag is boundary-only) |
| Forged/unknown verdict value | `UNKNOWN_SCAN_VERDICT` |
| Malware verdict (`THREATS_FOUND`) / `FAILED` / `TIMEOUT` / `UNSUPPORTED` | `SCAN_VERDICT_NOT_CLEAN` |
| Swapped object version / hash mismatch | `INTEGRITY_MISMATCH` |
| Stale or future-dated evidence | `STALE_SCAN_EVIDENCE` |
| Untrusted provider / authority | `UNTRUSTED_SCANNER` / `UNTRUSTED_RELEASE_AUTHORITY` |
| Missing / revoked / expired / incompletely-approved authorization | respective refusal |
| Any of the above with no approved policy | `RELEASE_NOT_ENABLED` |

Real-PG evidence (append-only tables, composite-FK tenant/client isolation,
cross-tenant scanner-evidence denial, concurrent single-effect release) is
**deferred to the implementation PR** that follows the decisions below — it
cannot be written against tables this slice deliberately does not create.

## Proposed future schema (NOT applied; needs decisions first)

A future migration (number to be re-checked against `main` + active PRs at
kickoff; `0009` is free at the time of writing) would add two append-only tables
separate from `0005`, each with a composite `(tenant_id, client_id, source_intake_id)`
FK, a `NOT NULL` whole-object SHA-256 CHECK, explicit provider/policy/event
identity columns, an optional engine/signature version (nullable, with the
literal `not exposed by vendor` semantics), and `BEFORE UPDATE/DELETE` refusal
triggers — mirroring the 0005/0008 immutability pattern. Exact columns depend on
`DEC-S2` (provider-aware evidence) and `DEC-S1` (object version binding), so the
DDL is intentionally not authored yet.

## Unresolved decisions to escalate (owners from the decision register)

1. **DEC-S2** — scanner provider and verdict-trust model, provider-aware evidence
   fields, fallback, outage behavior, rescan policy, verdict TTL. *(PO + Security)*
2. **DEC-S1** — object store provider/bucket, object versioning, key rotation,
   production IAM owner; required for object-version binding. *(PO + Tech Lead)*
3. **DEC-03** — hosting region + cross-border transfer basis. *(PO + Tech Lead + Legal)*
4. **DEC-02** — retention/deletion/backup periods + legal authority (blocks
   lifecycle/TTL semantics). *(PO + Legal)*
5. **DEC-R1** — pre-prod security review, environment credentials, pilot gate.
6. **Separation of duties** — whether release requires two-person approval
   (`require_two_person`), and who the trusted release authorities are
   (DEC-06 blocker/SoD territory).
7. **Revocation semantics** — what revokes a release (policy change, verdict
   re-scan, admin action), and how revocation is represented without mutating
   historical evidence.

Until these are approved, staging/production continue to refuse intake, and
registration/eligibility continue to refuse with `SOURCE_NOT_RELEASED`.

## Integration plan (after approval)

1. Persist append-only `scan_verdicts` + `release_authorizations` (trusted
   boundary only; never client payloads).
2. Wire `SourceFacts`/`ScanEvidence`/`ReleaseAuthorization` assembly from
   server-side reads, then feed `evaluate_release` into REC-DATA-01
   `evaluate_registration` and REC-SLICE-03 `EligibilitySnapshot.source_released`.
3. REC-DATA-02 mapping approvals + normalized `dataset_fingerprint` become the
   separate identity that final eligibility requires; release alone is never
   sufficient.
