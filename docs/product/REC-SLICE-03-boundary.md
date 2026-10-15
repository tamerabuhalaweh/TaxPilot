# REC-SLICE-03 execution boundary (engagement foundation + run refusal contracts)

Scope: `db/migrations/versions/0007_rec_engagements.sql`,
`apps/api/app/routers/engagements.py`, `apps/api/app/schemas/engagement.py`,
`apps/api/app/recon/eligibility.py`, `apps/api/app/recon/execution.py`.
No worker wiring, no dataset persistence, no financial contents anywhere.

## Dataset eligibility decision matrix (first failure wins)

| Order | Gate | Satisfied from | Refusal reason |
|---|---|---|---|
| 0 | Engagement exists + caller tenant owns it | `engagements` row (else 404, no oracle) | — |
| 1 | Engagement is ACTIVE | `engagements.status` | `ENGAGEMENT_NOT_ACTIVE` (409 STATE_CONFLICT, nothing persisted) |
| 2 | Confirmed jurisdiction context | `tax_contexts` same tenant+client, `confirmation_status = CONFIRMED` (read-only; confirmation owned by jurisdiction slice) | `UNCONFIRMED_JURISDICTION` |
| 3 | Both dataset versions present | persisted version registry — **absent on main** | `MISSING_DATASET_VERSION` |
| 4 | Mapping approved | mapping-approval store — **absent on main** | `UNAPPROVED_MAPPING` |
| 5 | Source released | quarantine release-gate log — **absent** (`document_intakes` has no release states) | `SOURCE_NOT_RELEASED` |
| 6 | JoFotara profile supported | approved profile catalog — **absent on main** | `UNSUPPORTED_JOFO_PROFILE` |

Gates 3–6 can never pass yet, so every run request is recorded BLOCKED.
Caller-supplied version IDs are references only, never proof of anything.

## Idempotency + transaction behavior

- Run identity = (tenant, engagement, operation `rec.reconcile.v1`,
  caller idempotency key, exact versions + rules/projection + period +
  jurisdiction). Same identity replays the identical 409 body; same key with
  different inputs → 409 STATE_CONFLICT; version change + new key → new run
  with a new source-set fingerprint.
- Check-then-insert runs under a transaction-scoped advisory lock
  (`recon-run:{tenant}:{engagement}:{operation}:{key}`); concurrent
  same-key requests converge on one row (integration-proven).
- `recon_runs` rows are trigger-immutable (no UPDATE/DELETE); engagements are
  never deleted (client RESTRICT + event RESTRICT); every transition and
  refusal is audited. No mutation route exists for runs.
- Engagement mutation is compare-and-swap on observed (status, revision): a
  stale concurrent writer matches zero rows and fails closed with a stable
  409, writing no history; late arrivals with a still-legal target commit as
  audited chained transitions, never regressions.
- Lineage is triple-scoped at the database level: events bind
  (tenant, engagement), runs bind (tenant, engagement, client) — cross-tenant
  or wrong-client lineage is rejected by foreign keys, not just by the API.
- `engagement_events` is trigger-immutable (no UPDATE/DELETE): history is
  append-only audit evidence.

## Explicitly blocked (not in this slice)

1. **Durable-job enqueue.** `DurableJobs.claim()` is not operation-scoped, so
   a queued `rec.reconcile` job could be claimed by an unrelated worker.
   Wiring execution needs operation-scoped claiming under separate review;
   fencing/lease machinery untouched here.
2. **Dataset-version registry, mapping approvals, release gates, JoFotara
   profile catalog.** Required before any run can pass eligibility.
3. **Review decisions, findings persistence, reports, UI.** Later slices.
