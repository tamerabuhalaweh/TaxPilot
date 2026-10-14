# EP-04C Decision Register (all PROPOSED — nothing approved)

> Every entry defaults to **BLOCKED** until explicit PO (or delegated reviewer)
> approval. No provider, region, credential, period, or compliance posture in
> this file is authorized. Re-verify all vendor facts at decision time.

## Candidate stacks (PROPOSED options, not recommendations-as-decisions)

### Stack A — AWS Bahrain (me-south-1), full managed surface
- Object storage: S3, versioning ON, Block Public Access, SSE-KMS (CMKs).
- Scanning: GuardDuty Malware Protection for S3 (per-bucket plans, isolated
  in-region scanning VPC, `GuardDutyMalwareScanStatus` tags
  `NO_THREATS_FOUND/THREATS_FOUND/UNSUPPORTED/ACCESS_DENIED/FAILED`,
  EventBridge results at-least-once, TBAC deny-unless-clean).
- Database/queue: RDS PostgreSQL + ElastiCache Redis in me-south-1 (both are
  core AWS services available in-region; verify instance classes at decision).
- Residency: closest hyperscaler region to Amman (~30–40 ms reported); still
  cross-border (Bahrain ≠ Jordan) — counsel must rule on PDPL basis.
- Cost posture: highest of the three (managed services + per-GB scan billing);
  verify current S3/GuardDuty pricing at decision time.
- Trade-offs: smallest ops burden, strongest verdict machinery, highest cost,
  cross-border by construction.

### Stack B — AWS EU (Frankfurt eu-central-1), same managed surface
- Same services as A, pinned EU. GDPR-adjacent posture reviewers understand;
  farther latency; still cross-border (EU ≠ Jordan) with a different counsel
  question (adequacy/transfer basis, not proximity).
- Cost posture: comparable to A. Use only if counsel prefers EU posture over
  Gulf proximity.

### Stack C — S3-compatible independent store + self-hosted scanning
- Object storage: Backblaze B2 (regions: US West/East, EU Central Amsterdam,
  CA East — NO Middle East; $6.95/TB/mo verified Oct 2026; account region
  immutable) or Wasabi (16 regions NA/EMEA/APAC; verify ME presence at decision;
  90-day minimum retention on pay-as-you-go CONFLICTS with undecided DEC-02).
- Scanning: self-hosted ClamAV (`clamd` + `freshclam` CVD updates; version
  freshness SLO owned by us) or evaluated SaaS (extra subprocessor + DPA).
- Database/queue: managed Postgres/Redis from an approved host, or self-managed
  on the chosen compute (highest ops burden).
- Trade-offs: lowest list cost, highest operational load, weakest residency
  story (no ME pinning verified), retention-minimum conflicts.

### Notably NOT viable as drawn
- Cloudflare R2 with ME data-residency guarantee: jurisdictions offered are
  default/eu/us/fedramp(-high) only; location hints are best-effort, not a
  guarantee (verified Oct 2026). Revisit only if their jurisdiction list gains
  a suitable option.
- Supabase Cloud pinned primary region in the Middle East: no ME-specific
  region offered (verify at decision; third-party UAE-hosted Supabase resellers
  are unevaluated and NOT recommended here).
- il-central-1 (Tel Aviv) for Jordanian customer data: excluded on
  political/customer-acceptance grounds without explicit PO direction.

## Decisions required

| ID | Question | Options (PROPOSED) | Default | Owner |
|---|---|---|---|---|
| DEC-03 | Hosting region + transfer basis (ADR-001 Q1–Q8) | A Bahrain / B EU / C independent (above) | BLOCKED | PO + Tech Lead + Legal |
| DEC-S1 | Object-storage provider, bucket, key rotation, prod IAM owner | A/B/C per above | BLOCKED | PO + Tech Lead |
| DEC-S2 | Malware scanner + engine version + verdict trust + fallback | GuardDuty managed / ClamAV self-hosted / evaluated SaaS | BLOCKED | PO + Security |
| DEC-02 | Retention/deletion/backup/hold periods + legal authority | Periods TBD by PO/legal; mechanics in C5 | BLOCKED (open) | PO + Legal |
| DEC-J1 | Job durability source of truth + SLO + ops owner | PG-authoritative + Redis wakeups (PROPOSED) | BLOCKED | PO + Tech Lead |
| DEC-R1 | Pre-prod security review, env credentials, pilot onboarding gate | Checklist in execution plan §6 | BLOCKED | PO + Security |

## Pre-conditions per decision (evidence required before approval)

- DEC-03: PDPL Law 24/2023 assessment + counsel opinion; subprocessor DPAs;
  transfer basis documented; pilot-firm residency expectations sampled.
- DEC-S1/S2: sandbox drill results ( outage/rotation/scan-latency evidence).
- DEC-02: legal authority + hold process + backup-expiry compatibility.
- DEC-J1: C1 fault-test suite green + metrics/alerts wired.
- DEC-R1: C5 staging drills + reviewer sign-off recorded.
