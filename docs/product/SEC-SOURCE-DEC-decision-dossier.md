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

**Review corrections:** F1 (free-tier eligibility/term), F2 (incomplete-subtotal /
TCO completeness) and F3 (GuardDuty activation wording) applied in response to PR
#72 review comment `6260871644`. Re-review HEAD is reported in the PR.

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
- **A — AWS S3 (`me-south-1`, Bahrain) + Malware Protection for S3.**
- **B — AWS S3 (`eu-central-1`, Frankfurt) + Malware Protection for S3.**
- **C — Backblaze B2 (S3-compatible) + self-hosted ClamAV.** Versioned storage
  with a separately authenticated scanner under our control.
- **D — Wasabi + self-hosted ClamAV.** Lower-cost S3-compatible alternative.

### 2.2 Comparison matrix

| Dimension | A/B — AWS S3 + Malware Protection for S3 | C — Backblaze B2 + ClamAV | D — Wasabi + ClamAV |
|---|---|---|---|
| Feature regional availability | The feature is offered in the commercial Regions where GuardDuty is offered (incl. `me-south-1`, `eu-central-1`; excl. China/GovCloud); **confirm the exact Region at decision time** | Regions US West/East, EU Central (Amsterdam), CA East — **no Middle East** | 16 regions NA/EMEA/APAC — **no Middle East** |
| Service activation | Configured **per protected bucket and per Region**; base GuardDuty threat-detection service does **not** need to be enabled (see F3 below) | n/a (ours) | n/a (ours) |
| Object versioning | S3 versioning ON; immutable **`VersionId`** per object | B2 file versions (versioning-style); S3-compatible `ListObjectVersions` | Wasabi object versioning; S3-compatible |
| Encryption / KMS | SSE-KMS with customer-managed keys (per-tenant data keys, envelope); rotation with old versions retained | Server-side encryption (SSE-B2 / SSE-C); **no managed KMS equivalent** — app-managed keys | SSE with Wasabi-managed or customer keys; no managed KMS |
| IAM / least privilege | Native IAM roles, per-role scoped policies, VPC endpoints, Block Public Access | Bucket-scoped application keys; coarse compared with IAM | Bucket-scoped keys; coarser |
| Scan verdict authentication | Scan results published to **EventBridge** (`source aws.guardduty`); consume via SigV4-authenticated SQS/control-plane. Result fields `scanStatus` (`COMPLETED`/`SKIPPED`/`FAILED`) and `scanResultStatus` (`NO_THREATS_FOUND`/`THREATS_FOUND`/`UNSUPPORTED`/`ACCESS_DENIED`/`FAILED`); event carries `versionId` **and** `eTag` | We own the boundary: clamd scan runs against a version-pinned read; verdict signed by our service; **engine + CVD signature versions available** | Same as C |
| Engine/signature provenance | **Not exposed by vendor** (no engine/signature version in the event) | ClamAV exposes engine version + CVD versions (e.g. 1.5.4, Aug 2026) | Same as C |
| Known scanning caveat | `ACCESS_DENIED` with reason `SSE_C_ENCRYPTED_OBJECT` — **SSE-C objects cannot be scanned**; use SSE-KMS. `SKIPPED`+`UNSUPPORTED` for e.g. `PASSWORD_PROTECTED` files ⇒ no verdict ⇒ fail closed | Our scanner reads decrypted bytes we supply; we decide handling of protected archives | Same as C |
| Account limits | A limited number of protected buckets per account per Region (reported **25**; confirm at decision) — a **multi-tenant** sizing constraint | Bucket/object limits are ours to manage | Same as C |
| Outage handling | Fully managed; scan events asynchronous/at-least-once; `s3Throttled` flag; outages ⇒ no `NO_THREATS_FOUND` ⇒ fail closed | We operate it: scanner outage is our incident; fail closed by default | Same as C |
| Operational complexity | Lowest (managed) | Highest (scanner fleet, CVD updates, freshness SLO, patching) | High |
| Provider lock-in | AWS-specific (storage, KMS, IAM, EventBridge) | S3-compatible API; ClamAV open source | S3-compatible API |
| Residency | Gulf/EU hyperscaler region; still cross-border vs Jordan | None in-region | None in-region |
| Cost shape | Per-GB storage + per-object/per-GB scan + KMS + requests (partial; see TCO §3.7) | Storage + free egress; adds scanner compute + ops labour | Flat $/TB, 1 TB minimum, 90-day minimum duration, free egress/API; adds scanner compute + ops |

**F3 — activation vs availability (corrected).** Malware Protection for S3 is a
protection capability that can be configured on **selected buckets per Region**
and can be used with the **base GuardDuty threat-detection service not enabled**
(AWS FAQ). This is distinct from the paid **S3 Protection** plan (S3 data-event
analysis), which *does* require GuardDuty to be enabled. Feature *availability*
follows the Regions where GuardDuty is offered, but availability is **not** the
same as a requirement to activate GuardDuty. The prior wording ("GuardDuty is
regional and must be enabled per Region") is withdrawn. Confirm exact-Region
feature availability at decision time.

**S3 VersionId vs ETag (mandatory design constraint, carried from SEC-SOURCE-01
F2):** the scan event includes both `versionId` and `eTag`, but **ETag is not a
version id and, for multipart/SSE objects, not a whole-object hash**. `VersionId`
(from versioned storage) plus a **separately server-computed whole-object
SHA-256** are the only identities; ETag is recorded as non-authoritative
supplemental metadata.

## 3. Cost model

### 3.1 Assumptions, units and confidence (state explicitly)
- **Units.** Storage figures are binary GiB (2³⁰). AWS publishes S3 and scan rates
  **per GB** without stating the denominator; using decimal GB (10⁹) instead of
  GiB would move the storage lines by roughly **7%** — within the uncertainty
  flagged below and not resolved here. Backblaze/Wasabi TB are treated as 1000 GB
  unless noted. Request and scan rates are per unit as published.
- **Retention.** Storage modelled at **12 months** for illustration only —
  **retention is DEC-02 TBD**; a shorter retention lowers every storage line
  (sensitivity in §3.7).
- **File sizes / rates** are illustrative pilot-shaped assumptions, **not
  measured**.
- **GuardDuty free tier is term-limited (F1).** Per AWS, Malware Protection for S3
  carries a **12-month Free Tier** (1,000 requests + 1 GB data scanned per month
  per Region) for **new accounts**, and existing accounts were eligible **only
  until 2025-06-11**. For accounts past that window, or existing accounts, the
  free tier **does not apply**. A TaxPilot AWS account as of 2026-10 **cannot be
  assumed eligible**; both cases are therefore modelled (§3.3).
- **Verified** figures: S3 data-transfer-out free allowance (first 100 GB/mo);
  KMS `$1/key/mo` + `$0.03/10k` requests (20,000 free/mo); GuardDuty scanned-data
  rate **`$0.09/GB`** (cited **us-east-1** example — **not confirmed** for
  `me-south-1`/`eu-central-1`); Backblaze `$6.95/TB/mo`; Wasabi `$7.99/TB/mo`
  (from 2026-07-01) with 1 TB minimum + 90-day minimum duration; ClamAV
  engine/CVD versions available.
- **Estimated (third-party; confirm in the AWS console/pricing page):** S3 region
  storage+request rates (`me-south-1` `$0.025/GB`, PUT `$0.0055/1k`, GET
  `$0.00044/1k`; `eu-central-1` `$0.0245/GB`, PUT `$0.0054/1k`, GET
  `$0.00043/1k`); GuardDuty **`$0.215 per 1,000 objects`** (us-east-1 example —
  **not confirmed** for `me-south-1`/`eu-central-1`).
- **TBD (unknown — never $0):** GuardDuty per-object and per-GB rates in
  `me-south-1`/`eu-central-1`; EventBridge S3 opt-in event ingest cost; S3 Object
  Tagging cost; backup/replication; additional KMS keys (per region/tenant) and
  request volume beyond the 20k free tier; self-hosted ClamAV compute; operations
  labour; monitoring/engineering support; outbound data transfer beyond the free
  allowance.

### 3.2 Workload scenarios

| | Small | Pilot | Growing |
|---|---|---|---|
| uploads/day | 25 | 200 | 1,000 |
| avg file | 2 MB | 3 MB | 4 MB |
| objects/mo | 750 | 6,000 | 30,000 |
| ingested GB/mo | 1.5 | 18 | 120 |
| stored GB (12-mo retention assumption) | 18 | 216 | 1,440 |
| GB scanned/mo | 1.5 | 18 | 120 |

### 3.3 Option A/B — AWS S3 + Malware Protection for S3 (per month)

GuardDuty charge = `max(0, objects − allowance)/1,000 × $0.215` + `max(0, GB − allowance) × $0.09`, with allowance = 1,000 objects and 1 GB only in the **eligible free-tier** case.

| Line (USD/mo) | Small | Pilot | Growing |
|---|---|---|---|
| GD objects — free tier applies (F1 case a) | $0.00 | 5×$0.215 = **$1.075** | 29×$0.215 = **$6.235** |
| GD GB scanned — free tier applies | 0.5×$0.09 = **$0.045** | 17×$0.09 = **$1.53** | 119×$0.09 = **$10.71** |
| **GD subtotal — free tier applies** | **$0.045** | **$2.605** | **$16.945** |
| GD objects — no free tier (F1 case b) | 750/1k×$0.215 = **$0.161** | 6×$0.215 = **$1.29** | 30×$0.215 = **$6.45** |
| GD GB scanned — no free tier | 1.5×$0.09 = **$0.135** | 18×$0.09 = **$1.62** | 120×$0.09 = **$10.80** |
| **GD subtotal — no free tier** | **$0.296** | **$2.91** | **$17.25** |
| S3 storage — `me-south-1` (est.) | 18×$0.025 = **$0.45** | 216×$0.025 = **$5.40** | 1,440×$0.025 = **$36.00** |
| S3 PUT (est.) | 750×$0.0055/1k = **$0.004** | 6,000×$0.0055/1k = **$0.03** | 30,000×$0.0055/1k = **$0.17** |
| S3 GET, ~5/object (est.) | 3,750×$0.00044/1k = **$0.002** | 30,000×$0.00044/1k = **$0.01** | 150,000×$0.00044/1k = **$0.07** |
| KMS — **1 key assumed** + requests (verified) | **$1.00** | **$1.00** | **$1.00** |
| Egress — first 100 GB/mo free | **$0.00** | **$0.00** | **$0.00** |
| **Illustrative partial metered subtotal — free tier applies** | **≈$1.50** | **≈$9.05** | **≈$54.18** |
| **Illustrative partial metered subtotal — no free tier** | **≈$1.75** | **≈$9.36** | **≈$54.48** |

**Free-tier expiration effect (F1.4):** crediting the free tier understates cost by
**+$0.25/mo (small)** and **+$0.31/mo (pilot, growing)** — about **$3.0–3.7/year**.
The allowance is trivial against these volumes, but it must not be claimed without
eligibility. All above are **partial** (see §3.7); `eu-central-1` (Option B) is
within a few percent on the estimated storage/request lines — the region decision
is legal/latency-driven, not cost-driven.

### 3.4 Option C — Backblaze B2 + self-hosted ClamAV (per month)

| Line (USD/mo) | Small | Pilot | Growing |
|---|---|---|---|
| B2 storage (first 10 GB free) | 8/1000×$6.95 = **≈$0.06** | 206/1000×$6.95 = **≈$1.43** | 1,430/1000×$6.95 = **≈$9.94** |
| B2 Class A/B/C calls (verified free) | $0.00 | $0.00 | $0.00 |
| B2 Class D calls (2,500/day free) | $0.00 | $0.00 | $0.00 (≤75k/mo free) |
| Egress (first 3× storage free) | $0.00 | $0.00 | $0.00 |
| ClamAV compute (est., shared/spot) | ~$10–20 | ~$15–30 | ~$30–60 |
| Operations labour (CVD freshness SLO, patching, on-call) | **TBD** | **TBD** | **TBD** |
| **Illustrative partial subtotal** | **≈$10–20 + labour** | **≈$16–31 + labour** | **≈$40–70 + labour** |

### 3.5 Option D — Wasabi + self-hosted ClamAV (per month)

Wasabi enforces a **1 TB minimum** and **90-day minimum duration**; the 1 TB floor
dominates: 1 TB × $7.99 = **$7.99/mo** for all three scenarios (egress/API free)
**+ ClamAV compute (est.) + TBD labour**. The 90-day minimum duration is a DEC-02
cost-compatibility risk (early deletion billed).

### 3.6 What these numbers are and are not (F2)

The AWS figures above are an **illustrative partial metered subtotal
(excludes TBD services and labour)**. They are **not** a total cost of ownership
and **cannot** establish total-cost superiority over Options C/D. In particular,
EventBridge event ingest, object tagging, backups/replication, KMS keys beyond the
single assumed key, request volume beyond the free tier, monitoring, and
engineering/operations support are **not** included in the AWS column, while the
self-hosted column already surfaces compute and labour. Any like-for-like
comparison is only possible once the TBD items below are priced (§3.7).

### 3.7 TCO completeness checklist and sensitivity (F2)

| Cost component | AWS A/B | B2 C | Wasabi D |
|---|---|---|---|
| Object storage | ✓ modelled (est., region unconfirmed) | ✓ modelled | ✓ 1 TB floor modelled |
| API requests (GET/PUT/Class D) | ✓ modelled (est.) | ✓ free | ✓ free |
| Scan (objects + GB) | ✓ modelled; **free tier NOT assumed** | ✓ ours (compute) | ✓ ours (compute) |
| EventBridge event ingest | **TBD** | n/a | n/a |
| Object tagging | **TBD** | n/a | n/a |
| KMS keys (per region/tenant) | **partial** (1 key assumed; +$1 each) | n/a (app keys) | n/a |
| KMS requests beyond 20k free | **TBD** | n/a | n/a |
| Backups / replication | **TBD** | **TBD** | **TBD** |
| Outbound data transfer beyond free allowance | **TBD** | **TBD** | ✓ free |
| Scanner compute | included in scan charge | **TBD** | **TBD** |
| Operations / on-call labour | **TBD** | **TBD** | **TBD** |
| Monitoring / engineering support | **TBD** | **TBD** | **TBD** |

**Sensitivity (illustrative, no invented prices):**
- **Retention (S3 `me-south-1` storage only):** 3 / 6 / 12 months ⇒ storage
  `$0.11 / $0.23 / $0.45` (small), `$1.35 / $2.70 / $5.40` (pilot),
  `$9.00 / $18.00 / $36.00` (growing) — retention is the dominant lever for
  storage-heavy options.
- **Free tier:** eligible vs expired shifts the partial subtotal by **+$0.25–0.30/mo**
  (§3.3).
- **Region / units:** AWS scan and object rates are cited for **us-east-1** and are
  **not confirmed** for Bahrain/Frankfurt; a GB↔GiB misread moves storage ~7%.
- **KMS keys:** each additional customer-managed key adds `$1/mo` (e.g. per-tenant
  keys multiply this line).

### 3.8 Reading the numbers (corrected)
- The AWS partial metered subtotal is **low and roughly flat with size**, and is
  driven by storage, not scanning; but it **excludes** the TBD services and labour
  listed in §3.7, so it must not be presented as a total.
- B2/Wasabi storage is far cheaper per GB, but both add **scanner compute and
  labour (TBD)** and neither offers a Middle East region.
- **No total-cost ranking is made here.** Within the like-for-like components that
  are priced, AWS is competitive at these volumes; the decision should turn on
  security/legal fit and the priced TBD items, not on these partial subtotals.

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
- **Cost:** §3.3–3.7 (partial; TBD items outstanding). **Owner:** PO + Tech Lead.

### DEC-S2 — Malware scanning and trusted verdicts
- **Recommendation (PROPOSED):** Malware Protection for S3, configured per
  protected bucket/Region **without requiring base GuardDuty**, consumed through a
  **SigV4-authenticated** EventBridge→SQS/control-plane boundary; provider-aware
  evidence (no engine version ⇒ `not exposed by vendor`); fail closed on
  `UNSUPPORTED`/`ACCESS_DENIED`/`FAILED`/outage. Keep ClamAV (C) as the documented
  fallback.
- **Alternatives:** self-hosted ClamAV (engine/CVD provenance, provider
  independence, higher ops).
- **Exact question:** *Approve scanner, verdict-trust boundary, provider-aware
  evidence fields, outage behaviour, and re-scan/TTL policy?*
- **Evidence:** GuardDuty EventBridge schema + pricing + FAQ (checked 2026-10-19).
- **Risks:** accepting untrusted evidence; SSE-C objects unscannable; managed
  outage ⇒ nothing releases (acceptable fail-closed).
- **Cost:** §3.3 vs §3.4 (partial). **Owner:** PO + Security.

### DEC-03 — Hosting region and international data transfer
- **Recommendation (PROPOSED):** Jordan-first; prefer `me-south-1` for proximity
  **pending** a Jordan-qualified legal determination; design tenant→zone-pinned
  deployments for multi-country isolation.
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
  durations (90/180 days) if archiving; retention drives the storage sensitivity
  in §3.7.
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
| Account eligibility | Whether the TaxPilot AWS account qualifies for the 12-month free tier, or budget the standard paid rates | PO + Tech Lead | OPEN |
| Dated cost verification | Confirm `me-south-1`/`eu-central-1` S3 + GuardDuty rates, EventBridge/tagging, KMS volume, backup/replication | PO + Tech Lead | OPEN |

## 8. Sources (checked 2026-10-19; re-verify at decision time)

Authoritative vendor:
- S3 pricing (storage classes, data transfer out, 100 GB free, request semantics):
  <https://aws.amazon.com/s3/pricing/>
- S3 Glacier pricing: <https://aws.amazon.com/s3/glacier/pricing/>
- Malware Protection for S3 pricing (free tier 1,000 req + 1 GB/Region;
  tagging/API/EventBridge excluded): <https://docs.aws.amazon.com/guardduty/latest/ug/pricing-malware-protection-for-s3-guardduty.html>
- GuardDuty pricing (free tier vs trial; Malware Protection for S3 has a free tier
  without a 30-day trial): <https://aws.amazon.com/guardduty/pricing/>
- GuardDuty FAQs (S3 Malware Protection **does not require base GuardDuty**; free
  tier term; S3 Protection **does** require GuardDuty):
  <https://aws.amazon.com/guardduty/faqs/>
- Free-tier term/eligibility (12-month Free Tier for new accounts; existing
  accounts until 2025-06-11), GA announcement 2024-06-11:
  <https://aws.amazon.com/blogs/aws/introducing-amazon-guardduty-malware-protection-for-amazon-s3/>
- Free-tier term clarification (existing accounts to 2025-06-11; new accounts 12
  months from creation): <https://repost.aws/questions/QURMzSyJv-SgWAUMZm7ht4gw/amazon-guard-duty-malware-protection-for-amazon-s3-free-tier>
- GuardDuty price reduction (scanned `$0.60 → $0.09/GB` us-east-1, Feb 2025;
  objects-evaluated price unchanged):
  <https://aws.amazon.com/about-aws/whats-new/2025/02/amazon-guardduty-malware-protection-s3-price-reduction/>
- GuardDuty S3 scan EventBridge schema (statuses; `versionId`+`eTag`;
  `SSE_C_ENCRYPTED_OBJECT` ⇒ `ACCESS_DENIED`; `PASSWORD_PROTECTED` ⇒ `UNSUPPORTED`;
  no engine version):
  <https://docs.aws.amazon.com/guardduty/latest/ug/monitor-with-eventbridge-s3-malware-protection.html>
- GuardDuty Region availability / endpoints (`me-south-1`, `eu-central-1`):
  <https://docs.aws.amazon.com/general/latest/gr/guardduty.html>
- Malware Protection for S3 all commercial Regions (June 2024):
  <https://docs.aws.amazon.com/guardduty/latest/ug/doc-history.html>
- KMS pricing (`$1/key/mo`, `$0.03/10k`, 20k free):
  <https://aws.amazon.com/kms/pricing/>
- Backblaze B2 pricing (`$6.95/TB/mo`, free egress 3×, first 10 GB free, no min
  duration): <https://www.backblaze.com/cloud-storage/pricing>
- Backblaze B2 transactions (Class A/B/C free; Class D `$0.004/10k` after
  2,500/day): <https://www.backblaze.com/cloud-storage/transaction-pricing>
- Wasabi pricing / FAQ (`$7.99/TB/mo`, 1 TB minimum, 90-day minimum duration):
  <https://wasabi.com/pricing> and <https://wasabi.com/pricing/faq>
- Wasabi pricing change effective 2026-07-01:
  <https://docs.wasabi.com/docs/may-2026-wasabi-pricing>
- Wasabi regions (no Middle East):
  <https://wasabi.com/company/storage-regions>
- ClamAV versions/FLEVEL (1.5.4, Aug 2026; engine + CVD provenance):
  <https://docs.clamav.net/appendix/FunctionalityLevels.html>
- ClamAV signature management (freshclam/CVD):
  <https://docs.clamav.net/manual/Usage/SignatureManagement.html>

Third-party aggregators (**estimated — confirm in the AWS console/pricing page**):
- S3 region rates: <https://cloudcostdb.com/aws/storage/object/standard/>
- GuardDuty per-object `$0.215/1,000`: <https://cloudburn.io/blog/amazon-guardduty-pricing>

## 9. Explicit non-decisions / residual risks

- No provider, region, credential, scanner, retention period, SoD rule, TTL, or
  release path is approved.
- Region/transfer and retention questions are **legal**; this dossier invents no
  Jordanian requirement or mandatory period.
- The AWS cost figures are an **illustrative partial metered subtotal**, not a
  TCO; EventBridge/tagging/backup/replication/KMS-volume/labour are TBD, and no
  total-cost superiority is claimed (§3.6–3.7).
- GuardDuty free-tier eligibility is **not assumed**: new-account 12-month term,
  existing accounts only until 2025-06-11 (§3.1, §3.3).
- AWS scan (`$0.09/GB`) and object (`$0.215/1k`) rates are cited for **us-east-1**
  and are **not confirmed** for `me-south-1`/`eu-central-1`; S3 `me-south-1`
  region rates are third-party estimates.
- Self-hosted ClamAV compute and operations labour are **TBD**, not zero.
- Wasabi's 1 TB minimum and 90-day minimum duration are DEC-02 cost risks.
- Redis DB-15 cross-process flakiness is a separate maintenance issue.

## 10. Following task

If decisions are approved: **SEC-SOURCE-02 — sandbox-only trusted versioned
storage adapter** (synthetic files). If they remain blocked: **REC-UI-01 —
synthetic accountant reconciliation workspace** with clearly labelled fixture
data and no real-file processing.
