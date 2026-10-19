# SEC-SOURCE-DEC — Product-owner security and infrastructure decision dossier

Status: **PROPOSED / decision request — nothing approved.** This document does not
authorize any provider, region, credential, scanner, retention period,
separation-of-duties policy, or release path. It is research to let the Product
Owner (PO), Security and Jordan-qualified legal counsel choose safely. All
decisions remain **BLOCKED** until explicit approval; no AI may mark them
APPROVED.

Authoritative issue: **#71**; parent architecture **#69**. Baseline: `main` @
`148e54ae313530b30bd8adab1d2515d734580502` (PR #70 merged); post-merge CI run
`39206070348` — 7/7 SUCCESS at that exact SHA. Companions (merged on `main`,
authoritative detail): `docs/product/SEC-SOURCE-01-boundary.md`,
`docs/engineering/SEC-SOURCE-01-IMPLEMENTATION-PLAN.md`,
`docs/architecture/EP04C_SECURITY_ARCHITECTURE.md`,
`docs/product/EP04C_DECISION_REGISTER.md`, `docs/product/REC-DATA-03-boundary.md`.
All prices/specs below were **checked 2026-10-19** and must be re-verified at
decision time. Prices exclude taxes.

**Non-goals / guardrails:** no provider/bucket provisioning, scanner connection,
credentials, migrations, storage adapters, release endpoints, or real financial
processing. Migrations `0001`–`0009` are frozen. PR #47 files are not touched.

## 1. Grounded current state (what exists vs what is missing)

Already shipped and unchanged: auth/tenancy/RBAC/CSRF; intake upload + local
quarantine; intake immutability (`0005`); durable PG jobs/outbox (`0006`,
EP-04C1); dev-only worker queue; pure default-deny release contracts
(`apps/api/app/release/policy.py`, REC-DATA-03); dataset registry (`0008`);
mapping approvals (`0009`); exact finance, extraction, normalization;
fail-closed CI (7 jobs).

Missing (gated by these decisions): approved private versioned object store +
KMS + region pin; scanner + trusted verdict ingestion; append-only
verdict/release/revocation tables; retention/deletion/backup lifecycle;
production IAM/secrets; pre-production security review.

Default-deny state that must be preserved: `config.storage_backend` may only be
`"local"`; `storage_readiness()` refuses staging/production with 503;
`DEFAULT_RELEASE_POLICY.approved is False` ⇒ `RELEASE_NOT_ENABLED`; registration
refuses `SOURCE_NOT_RELEASED`.

## 2. Infrastructure comparison

### 2.1 Options considered
- **A — AWS S3 (`me-south-1`, Bahrain) + GuardDuty Malware Protection for S3.**
- **B — AWS S3 (`eu-central-1`, Frankfurt) + GuardDuty Malware Protection for S3.**
- **C — Backblaze B2 (S3-compatible) + self-hosted ClamAV.** Versioned storage
  with a separately authenticated scanner under our control.
- **D — Wasabi + self-hosted ClamAV.** Lower-cost S3-compatible alternative.

### 2.2 Comparison matrix

| Dimension | A/B — AWS S3 + GuardDuty | C — Backblaze B2 + ClamAV | D — Wasabi + ClamAV |
|---|---|---|---|
| Region availability | GuardDuty available `me-south-1` and `eu-central-1`; Malware Protection for S3 available in **all commercial Regions where GuardDuty is available** (excl. China/GovCloud) | Regions US West/East, EU Central (Amsterdam), CA East — **no Middle East** | 16 regions NA/EMEA/APAC — **no Middle East** |
| Object versioning | S3 versioning ON; immutable **`VersionId`** per object | B2 file versions (versioning-style); S3-compatible `ListObjectVersions` | Wasabi object versioning; S3-compatible |
| Encryption / KMS | SSE-KMS with customer-managed keys (per-tenant data keys, envelope); rotation with old versions retained | Server-side encryption (SSE-B2 / SSE-C); **no managed KMS equivalent** — app-managed keys | SSE with Wasabi-managed or customer keys; no managed KMS |
| IAM / least privilege | Native IAM roles, per-role scoped policies, VPC endpoints, Block Public Access | Bucket-scoped application keys; coarse compared with IAM | Bucket-scoped keys; coarser |
| Scan verdict authentication | GuardDuty publishes scan results to **EventBridge** (`source aws.guardduty`); consume via SigV4-authenticated SQS/control-plane. Result fields `scanStatus` (`COMPLETED`/`SKIPPED`/`FAILED`) and `scanResultStatus` (`NO_THREATS_FOUND`/`THREATS_FOUND`/`UNSUPPORTED`/`ACCESS_DENIED`/`FAILED`); event carries `versionId` **and** `eTag` | We own the boundary: clamd scan runs against a version-pinned read; verdict signed by our service; **engine + CVD signature versions available** | Same as C |
| Engine/signature provenance | **Not exposed by vendor** (no engine/signature version in the event) | ClamAV exposes engine version + CVD versions (e.g. 1.5.4, Aug 2026) | Same as C |
| Known scanning caveat | `ACCESS_DENIED` with reason `SSE_C_ENCRYPTED_OBJECT` — **SSE-C objects cannot be scanned**; use SSE-KMS. `SKIPPED`+`UNSUPPORTED` for e.g. `PASSWORD_PROTECTED` files ⇒ no verdict ⇒ fail closed | Our scanner reads decrypted bytes we supply; we decide handling of protected archives | Same as C |
| Account limits | Malware Protection for S3 is limited to a number of protected buckets per account per Region (reported **25**; confirm at decision) — a **multi-tenant** sizing constraint | Bucket/object limits are ours to manage | Same as C |
| GuardDuty prerequisite | Malware Protection for S3 does **not** require the GuardDuty service to be enabled | n/a (ours) | n/a (ours) |
| Outage handling | Fully managed; scan events asynchronous/at-least-once; `s3Throttled` flag; outages ⇒ no `NO_THREATS_FOUND` ⇒ fail closed | We operate it: scanner outage is our incident; fail closed by default | Same as C |
| Operational complexity | Lowest (managed) | Highest (scanner fleet, CVD updates, freshness SLO, patching) | High |
| Provider lock-in | AWS-specific (GuardDuty, S3, KMS, IAM) | S3-compatible API; ClamAV open source | S3-compatible API |
| Residency | Gulf/EU hyperscaler region; still cross-border vs Jordan | None in-region | None in-region |
| Cost shape | Per-GB storage + per-object/per-GB scan + KMS + requests | Very low storage; free egress; adds compute + ops labour | Low storage, flat $/TB, free egress/API, 1 TB minimum, 90-day minimum duration |

**GuardDuty region check (verified):** GuardDuty is available in `me-south-1`
Bahrain and `eu-central-1` Frankfurt; Malware Protection for S3 was extended to
all commercial Regions where GuardDuty is available (June 2024), excluding China
and GovCloud. GuardDuty is regional and must be enabled per Region.

**S3 VersionId vs ETag (mandatory design constraint, carried from SEC-SOURCE-01
F2):** the GuardDuty event includes both `versionId` and `eTag`, but **ETag is
not a version id and, for multipart/SSE objects, not a whole-object hash**.
`VersionId` (from versioned storage) plus a **separately server-computed
whole-object SHA-256** are the only identities; ETag is recorded as
non-authoritative supplemental metadata.

## 3. Cost model

### 3.1 Assumptions (state explicitly; all regions differ — verify)
- Binary GB (GiB). Storage retention assumed **12 months** for the estimate only
  — **retention is DEC-02 TBD; a shorter retention lowers every storage line**.
- File sizes/rates are illustrative pilot-shaped assumptions, not measured.
- **Verified** prices: S3 data-transfer-out tiers and free allowances; KMS
  $1/key/mo + $0.03/10k requests (20k free/mo); GuardDuty free tier (1,000
  objects + 1 GB scanned/mo/Region); GuardDuty scanned-GB rate **$0.09/GB**
  (us-east-1, post Feb-2025); Backblaze $6.95/TB/mo; Wasabi $7.99/TB/mo (from
  1 Jul 2026) with 1 TB minimum + 90-day minimum duration; ClamAV engine/CVD
  versions available.
- **Estimated (third-party / needs AWS console confirmation):** S3 region
  storage+request rates (`me-south-1` $0.025/GB, PUT $0.0055/1k, GET $0.00044/1k;
  `eu-central-1` $0.0245/GB, PUT $0.0054/1k, GET $0.00043/1k); GuardDuty
  **$0.215 per 1,000 objects evaluated**; GuardDuty/S3 rates in `me-south-1`.
- **TBD (unknown — not zero):** GuardDuty per-object price in `me-south-1`;
  EventBridge S3 opt-in event ingest cost; S3 Object Tagging cost; self-hosted
  ClamAV compute (instance class/region); ops labour; backup/replication and
  KMS request volume at scan scale.

### 3.2 Workload scenarios

| | Small | Pilot | Growing |
|---|---|---|---|
| uploads/day | 25 | 200 | 1,000 |
| avg file | 2 MB | 3 MB | 4 MB |
| objects/mo | 750 | 6,000 | 30,000 |
| ingested GB/mo | 1.5 | 18 | 120 |
| stored GB (12-mo retention) | 18 | 216 | 1,440 |
| GB scanned/mo | 1.5 | 18 | 120 |

### 3.3 Option A/B — AWS S3 + GuardDuty (per month)

GuardDuty charge = max(0, objects − 1,000)/1,000 × $0.215 + max(0, GB − 1) × $0.09.

| Line (USD/mo) | Small | Pilot | Growing |
|---|---|---|---|
| GuardDuty objects (est.) | $0.00 | 5,000/1k×$0.215 = **$1.08** | 29,000/1k×$0.215 = **$6.24** |
| GuardDuty GB scanned (verified rate) | $0.00 | 17×$0.09 = **$1.53** | 119×$0.09 = **$10.71** |
| S3 storage `me-south-1` (est.) | 18×$0.025 = **$0.45** | 216×$0.025 = **$5.40** | 1,440×$0.025 = **$36.00** |
| S3 PUT (est.) | 750×$0.0055/1k = **$0.004** | **$0.03** | **$0.17** |
| S3 GET (est., ~5/object) | **$0.002** | **$0.01** | **$0.07** |
| KMS key + requests (verified) | **$1.00** | **$1.00** | **$1.00** |
| Egress (first 100 GB free) | $0.00 | $0.00 | $0.00 |
| **Estimated subtotal** | **~$1.46** | **~$9.05** | **~$54.19** |
| TBD add-ons | EventBridge/tagging; `me-south-1` rate confirmation | same | same |

`eu-central-1` (Option B) is within a few percent of these storage/request lines
(the `me-south-1` premium is small); the region decision is legal/latency-driven,
not cost-driven.

### 3.4 Option C — Backblaze B2 + self-hosted ClamAV (per month)

| Line (USD/mo) | Small | Pilot | Growing |
|---|---|---|---|
| B2 storage (first 10 GB free) | 8/1024×$6.95 = **$0.05** | 206/1024×$6.95 = **$1.40** | 1,430/1024×$6.95 = **$9.71** |
| B2 Class A/B/C calls (verified free) | $0.00 | $0.00 | $0.00 |
| B2 Class D calls (2,500/day free) | $0.00 | $0.00 | $0.00 (≤75k/mo free) |
| Egress (first 3× storage free) | $0.00 | $0.00 | $0.00 |
| ClamAV compute (est., shared/spot) | ~$10–20 | ~$15–30 | ~$30–60 |
| Ops labour (CVD freshness SLO, patching, on-call) | **TBD** | **TBD** | **TBD** |
| **Estimated subtotal** | **~$10–20 + labour** | **~$16–31 + labour** | **~$40–70 + labour** |

### 3.5 Option D — Wasabi + self-hosted ClamAV (per month)

Wasabi enforces a **1 TB minimum** and **90-day minimum duration**; at these
scenarios the 1 TB floor dominates: 1 TB × $7.99 = **$7.99/mo** for all three
(scans/egress/API free) **+ ClamAV compute + TBD labour**. The 90-day minimum
duration is a DEC-02 cost-compatibility risk (early deletion billed).

### 3.6 Reading the numbers
- At **small/pilot** sizes AWS + GuardDuty is ~$1–9/mo of metered cost — cheaper
  than operating a scanner when ops labour is counted.
- At **growing** sizes B2/Wasabi storage is far cheaper per GB than S3, but the
  scanner compute + labour can exceed the S3+GuardDuty metered cost unless the
  scanner already runs on existing capacity.
- Managed (A/B) buys the strongest verdict machinery, least ops and clear
  provenance-at-boundary; self-hosted (C/D) buys engine/signature provenance and
  provider independence at the cost of operating the scanner and a residency
  story that is **worse, not better** (no Middle East region).

## 4. Approval-ready decisions

Each: recommendation is **PROPOSED only**; the PO/Security/Legal decide.

### DEC-S1 — Object storage and encryption
- **Recommendation (PROPOSED):** Option A (AWS S3 `me-south-1`) **if** counsel
  accepts a Bahrain transfer basis; otherwise Option B (`eu-central-1`).
  Versioning ON, Block Public Access, SSE-KMS with customer-managed keys
  (per-tenant data keys, envelope), rotation with old versions retained,
  region-pinned endpoint, per-role least-privilege IAM.
- **Alternatives:** C/D (B2/Wasabi + app-managed keys) — weaker KMS/IAM, no ME
  region.
- **Exact question:** *Approve provider, region, bucket/versioning, SSE-KMS key
  ownership and rotation, and the production IAM owner?*
- **Evidence:** §2, §3; AWS docs (checked 2026-10-19).
- **Risks:** cross-region drift; SSE-C would break scanning (use SSE-KMS).
- **Cost:** §3.3–3.5. **Owner:** PO + Tech Lead.

### DEC-S2 — Malware scanning and trusted verdicts
- **Recommendation (PROPOSED):** GuardDuty Malware Protection for S3, consumed
  through a **SigV4-authenticated** EventBridge→SQS/control-plane boundary;
  provider-aware evidence (no engine version ⇒ `not exposed by vendor`); fail
  closed on `UNSUPPORTED`/`ACCESS_DENIED`/`FAILED`/outage. Keep ClamAV (C) as the
  documented fallback.
- **Alternatives:** self-hosted ClamAV (engine/CVD provenance, provider
  independence, higher ops).
- **Exact question:** *Approve scanner, verdict-trust boundary, provider-aware
  evidence fields, outage behaviour, and re-scan/TTL policy?*
- **Evidence:** GuardDuty EventBridge schema + pricing docs (checked 2026-10-19).
- **Risks:** accepting untrusted evidence; SSE-C objects unscannable; managed
  outage ⇒ nothing releases (acceptable fail-closed).
- **Cost:** §3.3 vs §3.4. **Owner:** PO + Security.

### DEC-03 — Hosting region and international data transfer
- **Recommendation (PROPOSED):** Jordan-first; prefer `me-south-1` for proximity
  **pending** a Jordan-qualified legal determination; design
  tenant→zone-pinned deployments for multi-country isolation.
- **Exact question:** *What transfer basis (PDPL Law 24/2023) applies to Bahrain
  vs EU, and which region is authorized for the pilot?* — **legal counsel owns
  this; no requirement is invented here.**
- **Evidence:** §2.2 residency row; region availability docs.
- **Owner:** PO + Tech Lead + Legal. **Related:** SRS DEC-12.

### DEC-02 — Retention, deletion and backups
- **Recommendation (PROPOSED):** no periods invented; adopt the SEC-SOURCE-01
  lifecycle (quarantine-prefix expiry, tombstones sans bytes, legal-hold flags
  that block sweeps, per-class erasure manifests incl. backups, restore drills).
- **Exact question:** *What retention/deletion/backup periods and legal-hold
  rules are authorized, and under what legal authority?*
- **Risks:** Wasabi 90-day minimum-duration cost conflict; S3 Glacier minimum
  durations (90/180 days) if archiving.
- **Owner:** PO + Legal. **Related:** SRS DEC-02 (pre-real-data).

### DEC-06 — Release authorities and separation of duties
- **Recommendation (PROPOSED):** release authorized by a trusted policy
  identity; **two-person approval** for source release (SoD), reconciled with
  REC-DATA-02 reviewer roles so one actor cannot both change mapping approval and
  release source bytes.
- **Exact question:** *Is source release two-person, who are the trusted release
  authorities, and how is SoD enforced?*
- **Owner:** PO + Security.

### DEC-R1 — Pre-production security readiness
- **Sequencing (F4):** P0 approves the **planned controls + test plan**; DEC-R1
  is the **P5 production GO after staging evidence**. Not a build precondition.
- **Checklist:** secrets manager, least-privilege IAM, signed-event authenticity,
  tenant-boundary negatives, KMS + rotation, abuse limits, SIEM alerting,
  adversarial red-team, backup restore, on-call runbooks.
- **Owner:** PO + Security.

### Release TTL, revocation and re-scanning behaviour
- **Recommendation (PROPOSED):** compulsory **finite** release TTL (no perpetual
  authorization, no future `issued_at`); re-scan on policy/engine change and TTL
  expiry; **append-only** revocation/supersession events with a deterministic
  effective-state projection (`(effective_at, event_id)` ordering, replay-dedup,
  late-arrival applied by `effective_at`, **default-deny on conflict**); no
  UPDATE/DELETE of historical evidence.
- **Exact question:** *What release TTL applies, what revokes a release, and how
  is revocation represented append-only?*
- **Owner:** PO + Security + Tech Lead.

## 5. Release-specific choice matrix (carried from SEC-SOURCE-01)

| Concern | Choice | Status |
|---|---|---|
| Object identity | immutable `VersionId` + **separately server-computed whole-object SHA-256**; ETag non-authoritative; version-pinned reads; reject `VersionId` mismatch even if ETag matches; multipart ETag ≠ SHA-256 | PROPOSED |
| Trusted scanner origin | SigV4/queue/control-plane only; raw webhook JSON/self-tags never authorize | PROPOSED |
| Evidence model | append-only `scan_verdicts` + `release_authorizations` (immutable, no `revoked` column) | PROPOSED |
| Revocation | separate append-only `release_revocations`/`release_events`; deterministic projection; default-deny on ambiguity | PROPOSED |
| Freshness / TTL | finite policy TTL; `max_evidence_age_seconds=None` ⇒ nothing fresh | PROPOSED |
| Replay / out-of-order | event-id dedup; single effect; late events applied by `effective_at` | PROPOSED |
| Revocation precedence | revocation wins unless an unambiguous later supersession chain exists | PROPOSED |
| SoD / authorization | trusted authority + two-person approval when required | PROPOSED |
| Binding | tenant + client + intake + region + `VersionId` + SHA-256 | PROPOSED |
| Gate order | registration (verified metadata) **precedes** mapping approval; derived-run eligibility is later and requires release + approval + fingerprint | FIXED (F1) |

## 6. Two-stage approval model

- **P0 (build-enabling):** approve architecture, provider selections and planned
  security controls + the DEC-R1 test plan. Enables **synthetic sandbox**
  construction (P1–P4), no real data.
- **P5 (production GO):** DEC-R1 + DEC-02 + DEC-03 determinations signed after
  staging evidence. Only then may real customer data flow.
- Throughout: `DEFAULT_RELEASE_POLICY.approved is False`; staging/production
  intake 503.

## 7. Outstanding approvals (copy-ready)

| ID | Decision | Owner | Status |
|---|---|---|---|
| DEC-S1 | Storage provider/region, versioning, SSE-KMS + rotation, prod IAM owner | PO + Tech Lead | BLOCKED |
| DEC-S2 | Scanner + trusted verdict boundary, evidence fields, outage, re-scan/TTL | PO + Security | BLOCKED |
| DEC-03 | Region + cross-border transfer basis (PDPL; counsel) | PO + Tech Lead + Legal | BLOCKED |
| DEC-02 | Retention/deletion/backup periods + legal holds | PO + Legal | BLOCKED |
| DEC-06 | Release authorities + separation of duties | PO + Security | BLOCKED |
| DEC-R1 | Pre-prod security GO (after P5 staging evidence) | PO + Security | BLOCKED |
| Revocation semantics | What revokes a release + append-only representation | PO + Security + Tech Lead | BLOCKED |
| Release TTL / chronology | Compulsory finite TTL; no future `issued_at` | PO + Security | BLOCKED |
| Dated cost verification | Confirm `me-south-1` S3 + GuardDuty per-object rates, EventBridge/tagging | PO + Tech Lead | OPEN |

## 8. Sources (checked 2026-10-19; re-verify at decision time)

Authoritative vendor:
- S3 pricing (storage classes, data transfer out, 100 GB free, request semantics):
  <https://aws.amazon.com/s3/pricing/>
- S3 Glacier pricing: <https://aws.amazon.com/s3/glacier/pricing/>
- GuardDuty Malware Protection for S3 pricing (free tier 1,000 req + 1 GB/Region;
  tagging/API/EventBridge extras): <https://docs.aws.amazon.com/guardduty/latest/ug/pricing-malware-protection-for-s3-guardduty.html>
- GuardDuty price reduction (scanned $0.60 → $0.09/GB us-east-1, Feb 2025):
  <https://aws.amazon.com/about-aws/whats-new/2025/02/amazon-guardduty-malware-protection-s3-price-reduction/>
- GuardDuty S3 scan EventBridge schema (statuses; `versionId`+`eTag`;
  `SSE_C_ENCRYPTED_OBJECT` ⇒ `ACCESS_DENIED`; no engine version):
  <https://docs.aws.amazon.com/guardduty/latest/ug/monitor-with-eventbridge-s3-malware-protection.html>
- GuardDuty Region availability / endpoints (`me-south-1`, `eu-central-1`):
  <https://docs.aws.amazon.com/general/latest/gr/guardduty.html>
- Malware Protection for S3 all commercial Regions (June 2024):
  <https://docs.aws.amazon.com/guardduty/latest/ug/doc-history.html>
- KMS pricing ($1/key/mo, $0.03/10k, 20k free):
  <https://aws.amazon.com/kms/pricing/>
- Backblaze B2 pricing ($6.95/TB/mo, free egress 3×, first 10 GB free, no min
  duration): <https://www.backblaze.com/cloud-storage/pricing>
- Backblaze B2 transactions (Class A/B/C free; Class D $0.004/10k after
  2,500/day): <https://www.backblaze.com/cloud-storage/transaction-pricing>
- Wasabi pricing / FAQ ($7.99/TB/mo, 1 TB minimum, 90-day minimum duration):
  <https://wasabi.com/pricing> and <https://wasabi.com/pricing/faq>
- Wasabi pricing change effective 2026-07-01:
  <https://docs.wasabi.com/docs/may-2026-wasabi-pricing>
- Wasabi regions (no Middle East):
  <https://wasabi.com/company/storage-regions>
- ClamAV versions/FLEVEL (1.5.4, Aug 2026; engine + CVD provenance):
  <https://docs.clamav.net/appendix/FunctionalityLevels.html>
- ClamAV signature management (freshclam/CVD):
  <https://docs.clamav.net/manual/Usage/SignatureManagement.html>

Third-party aggregators (**estimated — confirm on the AWS console/pricing page**):
- S3 region rates: <https://cloudcostdb.com/aws/storage/object/standard/>
- GuardDuty per-object $0.215/1,000: <https://cloudburn.io/blog/amazon-guardduty-pricing>

## 9. Explicit non-decisions / residual risks

- No provider, region, credential, scanner, retention period, SoD rule, TTL, or
  release path is approved.
- Region/transfer and retention questions are **legal**; this dossier invents no
  Jordanian requirement or mandatory period.
- S3 `me-south-1` and GuardDuty per-object prices are estimated third-party
  figures; AWS scanned-GB, KMS, B2 and Wasabi prices are vendor-verified here.
- Self-hosted ClamAV compute and ops labour are **TBD**, not zero.
- Wasabi's 1 TB minimum and 90-day minimum duration are DEC-02 cost risks.
- Redis DB-15 cross-process flakiness is a separate maintenance issue.

## 10. Following task

If decisions are approved: **SEC-SOURCE-02 — sandbox-only trusted versioned
storage adapter** (synthetic files). If they remain blocked: **REC-UI-01 —
synthetic accountant reconciliation workspace** with clearly labelled fixture
data and no real-file processing.
