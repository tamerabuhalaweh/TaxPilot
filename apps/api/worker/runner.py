"""Worker entrypoint: python -m worker.runner (from apps/api). Processes queued jobs in a loop.

Sprint 0 supports the `noop` and `echo` kinds only — enough to prove queue → process →
status visibility end to end. Reconciliation handlers arrive with approved contracts.

Reliability model: each worker owns its claims via fencing token + lease. A heartbeat
thread renews the lease while a job runs; a bounded periodic recovery pass requeues
jobs whose leases expired (crashed workers) WITHOUT operator action or fleet restart.
Recovery runs and stale rejections are logged with counts (observable). Delivery is
at-least-once: handlers MUST be idempotent. Exactly-once is never claimed.

Production block: starting this worker with environment=production is refused unless
explicit durability approval is configured (jobs_durability_approved, OPS-JOBS-01 #35).
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.config import get_settings
from app.logging_setup import setup_logging
from worker.jobs import (
    OUT_COMPLETED,
    OUT_EMPTY,
    OUT_FAILED,
    OUT_RETRIED,
    OUT_STALE,
    MemoryBackend,
    RedisBackend,
    new_worker_id,
)

log = logging.getLogger("taxpilot.worker")


def make_backend():  # type: ignore[no-untyped-def]
    settings = get_settings()
    if settings.queue_backend == "memory":
        if settings.environment == "production":
            raise RuntimeError("production refuses the non-durable memory queue backend")
        log.warning("memory queue backend: non-durable, explicit local/dev use only")
        return MemoryBackend(), "memory-fallback"
    backend = RedisBackend(settings.redis_url)  # raises loudly when Redis is unreachable
    return backend, "up"


def handle(job):  # type: ignore[no-untyped-def]
    if job.kind in ("noop", "echo"):
        return
    raise ValueError(f"unsupported job kind: {job.kind}")


def _heartbeat(backend: Any, job_id: str, owner: str, lease_ttl: float, stop: threading.Event) -> None:
    """Renew the lease until told to stop. A lost lease (False) is logged, not fatal:
    the attempt simply becomes eligible for recovery while this worker finishes."""
    from worker.jobs import Job as _Job

    probe = _Job(id=job_id)
    while not stop.wait(lease_ttl / 3.0):
        try:
            if not backend.renew(probe, owner, lease_ttl):
                log.warning("heartbeat lost lease (job=%s owner=%s)", job_id, owner)
                return
        except Exception:
            log.exception("heartbeat error (job=%s)", job_id)
            return


def service_tick(
    backend: Any,
    handler: Callable[[Any], None],
    worker_id: str,
    lease_ttl: float,
    heartbeat: bool = True,
) -> tuple[Any, str]:
    """One claim → handle (with lease heartbeat) → settle cycle. Returns (job, outcome)."""
    job = backend.claim(worker_id, lease_ttl)
    if job is None:
        return None, OUT_EMPTY
    stop = threading.Event()
    beat = None
    if heartbeat:
        beat = threading.Thread(
            target=_heartbeat, args=(backend, job.id, worker_id, lease_ttl, stop), daemon=True
        )
        beat.start()
    try:
        try:
            handler(job)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if job.attempts < job.max_attempts:
                if backend.requeue(job, worker_id, f"retryable: {message}"):
                    return job, OUT_RETRIED
            else:
                if backend.finish(job, worker_id, False, error=message, error_class=type(exc).__name__):
                    return job, OUT_FAILED
            log.warning("stale attempt discarded (job=%s owner=%s)", job.id, worker_id)
            return job, OUT_STALE
        if backend.finish(job, worker_id, True):
            return job, OUT_COMPLETED
        log.warning("stale completion rejected (job=%s owner=%s)", job.id, worker_id)
        return job, OUT_STALE
    finally:
        stop.set()
        if beat is not None:
            beat.join(timeout=lease_ttl)


def serve(
    backend: Any,
    handler: Callable[[Any], None] = handle,
    worker_id: str | None = None,
    lease_ttl: float = 60.0,
    recover_interval: float = 30.0,
    stop_after_jobs: int | None = None,
    idle_timeout: float | None = None,
) -> dict[str, int]:
    """Serve until stop_after_jobs completions or idle_timeout without work.

    Runs bounded automatic recovery (every recover_interval) so crashed workers'
    leases are reclaimed while this worker keeps running — no operator action,
    no fleet restart. Returns observable counters.
    """
    wid = worker_id or new_worker_id()
    stats = {"completed": 0, "retried": 0, "failed": 0, "stale": 0, "recovered": 0, "recover_runs": 0}
    last_recover = 0.0
    idle_since: float | None = None
    # Opening pass: fast-forward leases abandoned by previously crashed workers.
    try:
        first = backend.recover_stale()
    except Exception:
        log.exception("opening recovery failed")
        first = 0
    if first:
        log.info("opening recovery requeued=%s worker=%s", first, wid)
    stats["recovered"] += first
    stats["recover_runs"] += 1
    while True:
        now = time.time()
        if now - last_recover >= recover_interval:
            last_recover = now
            try:
                found = backend.recover_stale()
            except Exception:
                log.exception("periodic recovery failed worker=%s", wid)
                found = 0
            if found:
                log.info("periodic recovery requeued=%s worker=%s", found, wid)
            stats["recovered"] += found
            stats["recover_runs"] += 1
        _job, outcome = service_tick(backend, handler, wid, lease_ttl)
        if outcome in stats:
            stats[outcome] += 1
        done = stats["completed"] + stats["failed"] + stats["stale"]
        if stop_after_jobs is not None and done >= stop_after_jobs:
            break
        if outcome == OUT_EMPTY:
            idle_since = idle_since or now
            if idle_timeout is not None and now - idle_since >= idle_timeout:
                break
            time.sleep(0.2)
        else:
            idle_since = None
    log.info("worker stopping worker=%s stats=%s", wid, stats)
    return stats


def recover_and_serve(
    max_stale_seconds: float = 300.0,  # kept for CLI compat; leases now govern recovery
) -> None:
    """Production entrypoint: enforce the durability gate, then serve forever."""
    del max_stale_seconds
    settings = get_settings()
    if settings.environment == "production" and not settings.jobs_durability_approved:
        raise RuntimeError(
            "production job processing is blocked until OPS-JOBS-01 (#35) closes: "
            "set JOBS_DURABILITY_APPROVED=true only with an approved persistence/recovery policy"
        )
    setup_logging(settings.log_level)
    backend, _ = make_backend()
    serve(
        backend,
        handle,
        lease_ttl=settings.worker_lease_ttl_seconds,
        recover_interval=settings.worker_recover_interval_seconds,
    )


def main() -> None:
    recover_and_serve()


if __name__ == "__main__":
    main()

# Re-export for tests importing from the runner module.
__all__ = ["handle", "make_backend", "serve", "recover_and_serve", "main"]
