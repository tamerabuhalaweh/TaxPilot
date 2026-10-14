# EP-04C1 Durable Jobs — Recovery & Incident Runbook

> Scope: PostgreSQL-authoritative `extraction_jobs` + `job_outbox` (migration
> 0006), worker code in `apps/api/app/jobs/durable.py`. Production processing
> stays refused until #35 closes (`jobs_durability_approved` false).

## Normal operation

- Producers `enqueue()` (idempotent per tenant+client+operation+key) and
  `outbox_publish()` (idempotent per tenant+job+key, conflicts on reuse) in
  one transaction, then best-effort Redis wakeup (`WakeupBus.notify`).
- Workers `serve()`: claim (fencing token minted) → heartbeat renews every
  lease/3 → handler settles (ok / retry with backoff / terminal fail). A
  handler failing on its last allowed attempt goes DEAD immediately in
  `fail_transient` — retries can never outlive `max_attempts`, heartbeats or not.
- Outbox publishers claim with fencing tokens (`outbox_claim` assigns owner +
  token + lease); `serve_outbox()` publishes, acks, and sweeps. Every sweep
  recovery and every failed ack spends one attempt: repeated publisher crashes
  terminate FAILED instead of redelivering forever. Delivery is at-least-once —
  downstream effects MUST be idempotent per event id (publish-once is never
  claimed; exactly-once even less so).
- Handler fault text never persists: diagnostics store an allowlisted code
  (`HANDLER_RETRYABLE` / `HANDLER_TERMINAL` / `HANDLER_UNEXPECTED`) plus an
  opaque correlation ref; logs carry code + ref only.

## Symptoms → actions

| Symptom (metric) | Meaning | Action |
|---|---|---|
| `jobs.QUEUED.oldest_seconds` growing, `RUNNING` flat | No worker claiming (fleet down or wakeup loss) | Start/check workers; wakeups are advisory — sweeper + poll recover without Redis fixes |
| `RUNNING` stuck past lease TTL | Crashed workers | Nothing: sweeper requeues automatically; verify `recovered` counter moves |
| `DEAD` rising | Poison jobs exhausting attempts | Inspect `terminal_error`/`last_error`; fix handler or payload; re-enqueue via new idempotency key (history immutable) |
| `outbox PENDING` backlog growing | Publisher down/slow | Check publisher; events replay idempotently by `(tenant, job, event_key)` |
| `stale` settlements rising | Over-tenancy of leases (TTL too short for handler) | Raise lease TTL; check heartbeat errors in logs |
| Redis `PING` failing | Wakeup bus down | Nothing urgent: PG polling covers; restore Redis, no job action needed |

## Procedures

- **Worker SIGKILL / forced termination:** restart the worker process. Claims
  held by the dead worker expire; the sweeper requeues them. Never hand-edit
  job rows; never restart Redis to "fix" stuck jobs.
- **Redis restart / FLUSHALL:** safe by design — committed jobs and outbox rows
  live in PostgreSQL. Workers fall back to polling; wakeups resume on reconnect.
- **PostgreSQL connection failure:** operations raise loudly (no phantom
  success). In-flight handler work retries after reconnect; idempotency keys
  prevent double effects. Verify with `metrics()` that counts reconcile.
- **Lost commit acknowledgement:** re-query by `(tenant_id, idempotency_key)`
  (jobs) or `(tenant_id, event_key)` (outbox) — the rows are the truth, not the
  ack. Duplicate submissions converge; never invent a second version manually.
- **Suspected duplicate financial effect:** check the sentinel/effects table for
  the job id (one row per logical job); handlers must be `INSERT ...
  ON CONFLICT DO NOTHING` idempotent. Exactly-once is never claimed.

## What NOT to do

- Never UPDATE/DELETE job or outbox rows by hand (history is the audit trail).
- Never enable `jobs_durability_approved` without #35 closure + PO/security sign-off.
- Never point workers at a non-migrated database (migration ledger gates startup).
- Never store file bytes, secrets, or storage keys in payloads, logs, or metrics.
