"""Worker entrypoint: python -m worker.runner (from apps/api). Processes queued jobs in a loop.

Sprint 0 supports the `noop` and `echo` kinds only — enough to prove queue → process →
status visibility end to end. Reconciliation handlers arrive with approved contracts.

Delivery is at-least-once: handlers MUST be idempotent (retries and crash recovery can
redeliver). Exactly-once is never claimed.
"""

import logging
import time

from app.config import get_settings
from app.logging_setup import setup_logging
from worker.jobs import MemoryBackend, RedisBackend, process_one

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


def recover_and_serve(max_stale_seconds: float = 300.0) -> None:
    """Requeue jobs left RUNNING by crashed workers, then serve forever."""
    setup_logging(get_settings().log_level)
    backend, _ = make_backend()
    try:
        recovered = backend.recover_stale(max_stale_seconds)
    except Exception:
        recovered = 0
    log.info("worker started (recovered=%s)", recovered)
    while True:
        job = process_one(backend, handle)
        if job is None:
            time.sleep(1.0)


def main() -> None:
    recover_and_serve()


if __name__ == "__main__":
    main()
